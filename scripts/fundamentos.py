"""Cotações e indicadores fundamentalistas (valuation, qualidade, saúde financeira, crescimento, dividendos).

As notas e a classificação (Atrativa / Neutra / Pouco atrativa) são calculadas no próprio site,
comparando cada empresa com o seu grupo, para que os pesos possam ser ajustados por quem usa.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import math
import statistics
import time
import zipfile

from nucleo import HOJE, baixar


# ---------------------------------------------------------------- cotações

def _cotahist() -> tuple[dict, str | None]:
    """Arquivo diário oficial da B3 com o fechamento de todos os papéis (tenta os últimos 7 dias)."""
    for i in range(0, 8):
        d = HOJE - dt.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        url = f"https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{d:%d%m%Y}.ZIP"
        try:
            z = zipfile.ZipFile(io.BytesIO(baixar(url, timeout=60, tentativas=2)))
        except Exception:  # noqa: BLE001
            continue
        precos = {}
        with z.open(z.namelist()[0]) as f:
            for linha in io.TextIOWrapper(f, encoding="latin-1"):
                if not linha.startswith("01"):
                    continue
                if linha[24:27] != "010":  # mercado à vista
                    continue
                tk = linha[12:24].strip()
                try:
                    precos[tk] = int(linha[108:121]) / 100.0
                except ValueError:
                    pass
        if precos:
            print(f"[Preços] COTAHIST B3 de {d:%d/%m/%Y}: {len(precos)} papéis")
            return precos, d.isoformat()
    print("[Preços] COTAHIST da B3 indisponível; usando Yahoo")
    return {}, None


def _yahoo(simbolo: str) -> tuple[float, str] | None:
    for host in ("query1", "query2"):
        try:
            url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{simbolo}?range=5d&interval=1d"
            j = json.loads(baixar(url, timeout=20, tentativas=1))
            meta = j["chart"]["result"][0]["meta"]
            p = meta.get("regularMarketPrice")
            t = meta.get("regularMarketTime")
            if p:
                return float(p), dt.datetime.utcfromtimestamp(t).date().isoformat() if t else HOJE.isoformat()
        except Exception:  # noqa: BLE001
            continue
    return None


def _stooq(simbolo: str) -> tuple[float, str] | None:
    try:
        txt = baixar(f"https://stooq.com/q/l/?s={simbolo.lower()}.us&f=sd2c&h&e=csv", timeout=20, tentativas=1).decode()
        linha = txt.strip().splitlines()[1].split(",")
        return float(linha[2]), linha[1]
    except Exception:  # noqa: BLE001
        return None


def cotacoes(empresas: list[dict]) -> dict:
    """Devolve {simbolo: (preço, data)} para tudo que os cálculos precisam."""
    out: dict[str, tuple] = {}
    b3 = [e for e in empresas if e["mercado"] == "B3"]
    eua = [e for e in empresas if e["mercado"] == "BDR"]
    hist, data = _cotahist() if b3 else ({}, None)
    for e in b3:
        raiz = e["ticker"][:4]
        for tk in set(e["tickers"]) | {raiz + s for s in ("3", "4", "5", "6", "11")}:
            if tk in hist:
                out[tk] = (hist[tk], data)
        if not any(t in out for t in e["tickers"]):
            for tk in e["tickers"]:
                r = _yahoo(f"{tk}.SA")
                time.sleep(0.3)
                if r:
                    out[tk] = r
    for e in eua:
        tk = e["ticker_eua"]
        r = _yahoo(tk) or _stooq(tk)
        time.sleep(0.3)
        if r:
            out[tk] = r
    ok_b3 = sum(1 for e in b3 if any(t in out for t in e["tickers"]))
    ok_eua = sum(1 for e in eua if e["ticker_eua"] in out)
    print(f"[Preços] B3: {ok_b3}/{len(b3)} | EUA: {ok_eua}/{len(eua)}")
    return out


# ---------------------------------------------------------------- indicadores

def _ltm(serie, i):
    if not serie or i < 3:
        return None
    j = serie[i - 3:i + 1]
    return None if any(v is None for v in j) else sum(j)


def _ltm_parcial(serie, i):
    """Soma dos últimos 4 trimestres tratando vazio como zero (para dividendos)."""
    if not serie or i < 3:
        return None
    j = serie[i - 3:i + 1]
    return None if all(v is None for v in j) else sum(v or 0 for v in j)


def _div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def _cresc(a, b):
    if a is None or b is None or b <= 0 or a <= 0:
        return None
    return a / b - 1


def _valor_mercado(e: dict, precos: dict):
    """Em milhares da moeda da empresa (mesma unidade dos balanços)."""
    ac = e.get("acoes")
    if not ac:
        return None, None, None
    if e["mercado"] == "BDR":
        p = precos.get(e["ticker_eua"])
        if not p:
            return None, None, None
        return ac["total"] * p[0] / 1000.0, p, None
    raiz = e["ticker"][:4]
    qualquer = next((precos[t] for t in e["tickers"] if t in precos), None)
    p_on = precos.get(raiz + "3")
    p_pn = next((precos[raiz + s] for s in ("4", "5", "6") if raiz + s in precos), None)
    ref = precos.get(e["ticker"]) or qualquer
    if not ref:
        return None, None, None
    on, pn = ac.get("on", 0), ac.get("pn", 0)
    preco_on = (p_on or p_pn or ref)[0]
    preco_pn = (p_pn or p_on or ref)[0]
    vm = (on * preco_on + pn * preco_pn) / 1000.0
    return vm, ref, {"on": on, "pn": pn}


def calcular(e: dict, precos: dict) -> dict | None:
    b, ind = e["base"], e["ind"]
    rec = b.get("receita") or []
    i = len(rec) - 1
    while i >= 0 and rec[i] is None and (b.get("lucro") or [None])[i] is None:
        i -= 1
    if i < 3:
        return None
    vm, preco, _ = _valor_mercado(e, precos)
    fin = e.get("financeira")
    lucro = _ltm(b.get("lucro"), i)
    receita = _ltm(rec, i)
    ebitda = _ltm(ind.get("ebitda"), i) if not fin else None
    fcl = _ltm(ind.get("fcl"), i) if not fin else None
    divs = _ltm_parcial(b.get("dividendos"), i)
    pl_patr = (b.get("pl") or [None] * (i + 1))[i]
    dl = (ind.get("divida_liquida") or [None] * (i + 1))[i]
    margens = [m for m in (ind.get("margem_liquida") or [])[max(0, i - 7):i + 1] if m is not None]
    escala_ajustada = False
    if e["mercado"] == "B3" and vm and pl_patr and pl_patr > 0 and vm / pl_patr < 0.02:
        # algumas empresas informam a quantidade de ações à CVM em milhares
        vm *= 1000
        escala_ajustada = True
        print(f"[Fund] {e['ticker']}: quantidade de ações informada em milhares; ajustada")

    f = {
        "periodo": e["trimestres"][i]["l"],
        "preco": preco[0] if preco else None,
        "preco_data": preco[1] if preco else None,
        "preco_ticker": (e["ticker_eua"] if e["mercado"] == "BDR" else e["ticker"]) if preco else None,
        "valor_mercado": vm,
        "escala_acoes_ajustada": escala_ajustada,
        "lucro_ltm": lucro, "receita_ltm": receita, "ebitda_ltm": ebitda,
        # valuation
        "pl": _div(vm, lucro) if (lucro and lucro > 0) else None,
        "lucro_negativo": bool(lucro is not None and lucro <= 0),
        "ev_ebitda": _div(vm + (dl or 0), ebitda) if (vm and ebitda and ebitda > 0 and not fin) else None,
        "pvp": _div(vm, pl_patr) if (pl_patr and pl_patr > 0) else None,
        "fcf_yield": _div(fcl, vm) if (vm and not fin) else None,
        "dy": _div(divs, vm) if vm else None,
        # qualidade
        "roe": (ind.get("roe") or [None] * (i + 1))[i],
        "margem_liquida": _div(lucro, receita) if (receita and receita > 0) else None,
        "margem_ebitda": _div(ebitda, receita) if (ebitda is not None and receita and receita > 0) else None,
        "volatilidade_margem": statistics.pstdev(margens) if len(margens) >= 4 else None,
        # saúde
        "div_ebitda": None if fin else (ind.get("alavancagem") or [None] * (i + 1))[i],
        "caixa_liquido": bool(dl is not None and dl < 0) if not fin else None,
        # crescimento
        "cresc_receita_1a": _cresc(receita, _ltm(rec, i - 4)),
        "cresc_lucro_1a": _cresc(lucro, _ltm(b.get("lucro"), i - 4)),
        "cresc_receita_2a": (lambda c: None if c is None else (1 + c) ** 0.5 - 1)(_cresc(receita, _ltm(rec, i - 8))),
    }
    # quando a dívida líquida é negativa (caixa líquido), a alavancagem fica negativa: é o melhor caso
    for k, v in list(f.items()):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            f[k] = None
    return f


def aplicar(empresas: list[dict]) -> None:
    precos = cotacoes(empresas)
    n = 0
    for e in empresas:
        try:
            e["fund"] = calcular(e, precos)
            if e["fund"] and e["fund"].get("valor_mercado"):
                n += 1
        except Exception as ex:  # noqa: BLE001
            print(f"[Fund] erro em {e['ticker']}: {ex}")
            e["fund"] = None
    print(f"[Fund] valuation calculado para {n}/{len(empresas)} empresas")
    for t in ("PETR4", "ITUB4", "WEGE3", "VALE3", "NVDC34", "MSFT34"):
        e = next((x for x in empresas if x["ticker"] == t), None)
        if e and e.get("fund"):
            f = e["fund"]
            vm = f.get("valor_mercado")
            print(f"[Fund] {t}: preço {f.get('preco')} | valor de mercado {vm / 1e6 if vm else None:.1f} bi | "
                  f"P/L {f.get('pl') and round(f['pl'], 1)} | P/VP {f.get('pvp') and round(f['pvp'], 2)} | "
                  f"DY {f.get('dy') and round(f['dy'] * 100, 1)}%" if vm else f"[Fund] {t}: sem valor de mercado")
