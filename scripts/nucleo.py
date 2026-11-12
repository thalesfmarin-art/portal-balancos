"""Funções comuns: períodos, trimestres, indicadores e resumo automático."""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import time
from typing import Iterable

import requests

HOJE = dt.date.today()
UA_NAVEGADOR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


# ---------------------------------------------------------------- HTTP

def baixar(url: str, destino: str | None = None, headers: dict | None = None,
           tentativas: int = 4, timeout: int = 180) -> bytes:
    """Baixa uma URL com novas tentativas. Se `destino` for dado, grava em disco."""
    h = {"User-Agent": UA_NAVEGADOR}
    if headers:
        h.update(headers)
    erro = None
    for i in range(tentativas):
        try:
            r = requests.get(url, headers=h, timeout=timeout)
            if r.status_code == 404:
                raise FileNotFoundError(url)
            r.raise_for_status()
            if destino:
                os.makedirs(os.path.dirname(destino), exist_ok=True)
                with open(destino, "wb") as f:
                    f.write(r.content)
            return r.content
        except FileNotFoundError:
            raise
        except Exception as e:  # noqa: BLE001
            erro = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"Falha ao baixar {url}: {erro}")


# ---------------------------------------------------------------- datas

def para_data(s) -> dt.date | None:
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return None
    if isinstance(s, dt.date):
        return s
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def meses(ini: dt.date, fim: dt.date) -> int:
    return round(((fim - ini).days + 1) / 30.44)


def rotulo_trimestre(fim: dt.date) -> tuple[str, str]:
    """Rótulo de trimestre calendário a partir da data final (aceita anos fiscais 52/53 semanas)."""
    d = fim - dt.timedelta(days=45)
    q = (d.month - 1) // 3 + 1
    return f"{d.year}Q{q}", f"{q}T{d.year % 100:02d}"


def rotulo_ano(fim: dt.date) -> str:
    return str((fim - dt.timedelta(days=45)).year)


def perto(a: dt.date, b: dt.date, tol: int = 12) -> bool:
    return abs((a - b).days) <= tol


# ---------------------------------------------------------------- séries

class Contas:
    """Acumula valores de contas (fluxo ou saldo) vindos de qualquer fonte."""

    def __init__(self):
        self.fluxos: dict[str, dict[tuple, tuple]] = {}   # conta -> (ini,fim) -> (valor, prioridade)
        self.saldos: dict[str, dict[dt.date, tuple]] = {}  # conta -> fim -> (valor, prioridade)
        self.nomes: dict[str, str] = {}

    def fluxo(self, conta, ini, fim, valor, prio=0, nome=None):
        if ini is None or fim is None or valor is None:
            return
        d = self.fluxos.setdefault(conta, {})
        k = (ini, fim)
        if k not in d or prio >= d[k][1]:
            d[k] = (float(valor), prio)
        if nome:
            self.nomes[conta] = nome

    def saldo(self, conta, fim, valor, prio=0, nome=None):
        if fim is None or valor is None:
            return
        d = self.saldos.setdefault(conta, {})
        if fim not in d or prio >= d[fim][1]:
            d[fim] = (float(valor), prio)
        if nome:
            self.nomes[conta] = nome

    # ---- trimestres a partir de períodos de 3 meses ou acumulados no ano
    def trimestral(self, conta) -> dict[dt.date, float]:
        regs = {k: v[0] for k, v in self.fluxos.get(conta, {}).items()}
        out: dict[dt.date, float] = {}
        for (ini, fim), v in regs.items():
            if meses(ini, fim) == 3:
                out[fim] = v
        for (ini, fim), v in sorted(regs.items(), key=lambda x: meses(*x[0])):
            m = meses(ini, fim)
            if m not in (6, 9, 12):
                continue
            if any(perto(fim, f, 5) for f in out):
                continue
            ant = [val for (i2, f2), val in regs.items()
                   if i2 == ini and meses(i2, f2) == m - 3]
            if ant:
                out[fim] = v - ant[0]
                continue
            # alternativa: soma dos trimestres anteriores do mesmo exercício
            soma, ok = 0.0, True
            for j in range(1, m // 3):
                alvo = fim - dt.timedelta(days=round(91.3 * j))
                achado = [val for f, val in out.items() if perto(f, alvo)]
                if not achado:
                    ok = False
                    break
                soma += achado[0]
            if ok:
                out[fim] = v - soma
        return out

    def anual(self, conta) -> dict[dt.date, float]:
        return {fim: v[0] for (ini, fim), v in self.fluxos.get(conta, {}).items()
                if meses(ini, fim) == 12}

    def instantes(self, conta) -> dict[dt.date, float]:
        return {f: v[0] for f, v in self.saldos.get(conta, {}).items()}


def alinhar(serie: dict[dt.date, float], fins: list[dt.date]) -> list:
    out = []
    for f in fins:
        v = serie.get(f)
        if v is None:
            for f2, v2 in serie.items():
                if perto(f, f2, 6):
                    v = v2
                    break
        out.append(None if v is None or (isinstance(v, float) and math.isnan(v)) else round(v, 3))
    return out


# ---------------------------------------------------------------- indicadores

def _div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def _var(atual, antes):
    if atual is None or antes in (None, 0):
        return None
    return (atual - antes) / abs(antes)


def soma_ltm(vals: list, i: int):
    if i < 3:
        return None
    janela = vals[i - 3:i + 1]
    if any(v is None for v in janela):
        return None
    return sum(janela)


def indicadores(base: dict[str, list], financeira: bool) -> dict[str, list]:
    """`base` traz listas alinhadas aos trimestres. Devolve indicadores por trimestre."""
    n = len(base["receita"])
    get = lambda k, i: (base.get(k) or [None] * n)[i]  # noqa: E731
    ebitda = []
    for i in range(n):
        e, da = get("ebit", i), get("da", i)
        ebitda.append(None if e is None else e + (abs(da) if da is not None else 0))
    out = {k: [] for k in ("ebitda", "margem_bruta", "margem_ebitda", "margem_liquida",
                           "divida_liquida", "alavancagem", "roe", "fcl")}
    for i in range(n):
        rec = get("receita", i)
        out["ebitda"].append(None if financeira else ebitda[i])
        out["margem_bruta"].append(None if financeira else _div(get("lucro_bruto", i), rec))
        out["margem_ebitda"].append(None if financeira else _div(ebitda[i], rec))
        out["margem_liquida"].append(_div(get("lucro", i), rec))
        dl = None
        if not financeira and get("divida", i) is not None:
            dl = get("divida", i) - (get("caixa", i) or 0)
        out["divida_liquida"].append(dl)
        e_ltm = soma_ltm(ebitda, i)
        out["alavancagem"].append(_div(dl, e_ltm) if (dl is not None and e_ltm and e_ltm > 0) else None)
        l_ltm = soma_ltm(base.get("lucro") or [None] * n, i)
        pl = get("pl", i)
        out["roe"].append(_div(l_ltm, pl) if (pl and pl > 0) else None)
        fco, capex = get("fco", i), get("capex", i)
        out["fcl"].append(None if fco is None else fco - abs(capex or 0))
    return out


# ---------------------------------------------------------------- resumo automático

def _pct(x):
    return "n/d" if x is None else f"{x * 100:+.1f}%".replace(".", ",")


def _pp(x):
    return f"{x * 100:+.1f} p.p.".replace(".", ",")


def resumo_automatico(rotulos: list[str], base: dict[str, list], ind: dict[str, list],
                      financeira: bool, moeda: str) -> dict:
    """Veredito (Bom / Misto / Ruim), motivos e o que esperar, só com base nos números."""
    n = len(rotulos)
    if n == 0 or base.get("receita") is None:
        return {"veredito": "Sem dados", "pontos": [], "esperar": []}
    i = n - 1
    while i >= 0 and (base["receita"][i] is None and (base.get("lucro") or [None])[i] is None):
        i -= 1
    if i < 0:
        return {"veredito": "Sem dados", "pontos": [], "esperar": []}
    a = i - 4  # mesmo trimestre do ano anterior
    pts, score, pos, neg = [], 0, [], []

    def get(k, j):
        s = base.get(k) or ind.get(k)
        return None if s is None or j < 0 else s[j]

    rec_v = _var(get("receita", i), get("receita", a))
    if rec_v is not None:
        nome = "Receita" if not financeira else "Receitas"
        txt = f"{nome} {_pct(rec_v)} na comparação anual"
        if rec_v > 0.05:
            score += 1; pos.append(txt)
        elif rec_v < -0.05:
            score -= 1; neg.append(txt)
        else:
            pts.append(txt + " (estável)")

    if not financeira:
        eb_v = _var(get("ebitda", i), get("ebitda", a))
        if eb_v is not None:
            txt = f"EBITDA {_pct(eb_v)} no ano"
            if eb_v > 0.05:
                score += 1; pos.append(txt)
            elif eb_v < -0.05:
                score -= 1; neg.append(txt)
            else:
                pts.append(txt + " (estável)")
        m1, m0 = get("margem_ebitda", i), get("margem_ebitda", a)
        if m1 is not None and m0 is not None:
            d = m1 - m0
            txt = f"margem EBITDA de {m1 * 100:.1f}% ({_pp(d)})".replace(".", ",", 1)
            if d > 0.01:
                score += 1; pos.append(txt)
            elif d < -0.01:
                score -= 1; neg.append(txt)

    l1, l0 = get("lucro", i), get("lucro", a)
    if l1 is not None and l0 is not None:
        if l0 < 0 <= l1:
            score += 2; pos.append("voltou a dar lucro (tinha prejuízo há um ano)")
        elif l0 >= 0 > l1:
            score -= 2; neg.append("passou a ter prejuízo (tinha lucro há um ano)")
        elif l1 < 0 and l0 < 0:
            if l1 > l0:
                score += 1; pos.append("prejuízo menor que há um ano")
            else:
                score -= 1; neg.append("prejuízo maior que há um ano")
        else:
            v = _var(l1, l0)
            txt = f"lucro líquido {_pct(v)} no ano"
            if v > 0.10:
                score += 1; pos.append(txt)
            elif v < -0.10:
                score -= 1; neg.append(txt)
            else:
                pts.append(txt + " (estável)")

    if financeira:
        r1, r0 = get("roe", i), get("roe", a)
        if r1 is not None:
            txt = f"ROE de {r1 * 100:.1f}% em 12 meses".replace(".", ",")
            if r0 is not None and r1 - r0 > 0.01:
                score += 1; pos.append(txt + f" ({_pp(r1 - r0)})")
            elif r0 is not None and r1 - r0 < -0.01:
                score -= 1; neg.append(txt + f" ({_pp(r1 - r0)})")
            else:
                pts.append(txt)
    else:
        al1, al0 = get("alavancagem", i), get("alavancagem", a)
        if al1 is not None:
            txt = f"dívida líquida/EBITDA de {al1:.1f}x".replace(".", ",")
            if al0 is not None and al1 - al0 > 0.5 and al1 > 2.5:
                score -= 1; neg.append(txt + f" (subiu de {al0:.1f}x)".replace(".", ","))
            elif al0 is not None and al0 - al1 > 0.5:
                score += 1; pos.append(txt + f" (caiu de {al0:.1f}x)".replace(".", ","))
            elif al1 > 3.5:
                neg.append(txt + " (alavancagem alta)")
            else:
                pts.append(txt)

    veredito = "Bom" if score >= 2 else ("Ruim" if score <= -2 else "Misto")
    if a < 0:
        veredito = "Sem comparação"

    # ---- o que esperar (tendências)
    esperar = []
    yoys = []
    for j in range(max(4, i - 3), i + 1):
        yoys.append(_var(get("receita", j), get("receita", j - 4)))
    yoys = [y for y in yoys if y is not None]
    if len(yoys) >= 3:
        if yoys[-1] > yoys[-2] > yoys[-3]:
            esperar.append("Crescimento da receita vem acelerando há 3 trimestres; se o ritmo continuar, a próxima comparação tende a ser positiva.")
        elif yoys[-1] < yoys[-2] < yoys[-3]:
            esperar.append("Crescimento da receita vem desacelerando há 3 trimestres; vale acompanhar se a perda de ritmo continua.")
    if not financeira:
        ms = [get("margem_ebitda", j) for j in range(max(0, i - 2), i + 1)]
        if len(ms) == 3 and all(m is not None for m in ms):
            if ms[2] > ms[1] > ms[0]:
                esperar.append("Margem EBITDA em expansão nos últimos 3 trimestres, sinal de ganho de eficiência ou de preço.")
            elif ms[2] < ms[1] < ms[0]:
                esperar.append("Margem EBITDA em queda nos últimos 3 trimestres; custos ou preços estão pressionando a rentabilidade.")
        al = get("alavancagem", i)
        if al is not None and al > 3:
            esperar.append("Alavancagem acima de 3x: juros pesam no lucro e o mercado deve olhar geração de caixa e desalavancagem.")
        fcl = ind["fcl"][i] if ind.get("fcl") else None
        if fcl is not None and fcl < 0:
            esperar.append("Fluxo de caixa livre negativo no trimestre (caixa operacional menor que os investimentos).")
    if i + 1 < n:
        pass
    if not esperar:
        esperar.append("Sem mudança clara de tendência nos últimos trimestres; o próximo resultado deve seguir a linha recente.")

    return {
        "veredito": veredito,
        "periodo": rotulos[i],
        "positivos": pos,
        "negativos": neg,
        "neutros": pts,
        "esperar": esperar,
        "fonte": "automatico",
    }


# ---------------------------------------------------------------- resumo com IA (opcional)

def resumo_ia(nome: str, ticker: str, rotulos, base, ind, auto: dict, moeda: str,
              modelo: str, cache: dict) -> dict | None:
    """Gera um texto analítico com a API do Claude, se ANTHROPIC_API_KEY estiver configurada.
    Usa cache por empresa+período para só gastar quando sai resultado novo."""
    chave = os.environ.get("ANTHROPIC_API_KEY")
    if not chave or not auto.get("periodo"):
        return None
    ck = f"{ticker}|{auto['periodo']}"
    if ck in cache:
        return cache[ck]
    ult = slice(max(0, len(rotulos) - 8), len(rotulos))
    dados = {"trimestres": rotulos[ult]}
    for k in ("receita", "lucro_bruto", "ebit", "lucro", "fco", "capex", "divida", "caixa", "pl"):
        if base.get(k):
            dados[k] = base[k][ult]
    for k in ("ebitda", "margem_ebitda", "margem_liquida", "alavancagem", "roe"):
        if ind.get(k):
            dados[k] = [None if v is None else round(v, 4) for v in ind[k][ult]]
    unidade = "R$ mil" if moeda == "BRL" else "US$ mil"
    prompt = (
        f"Você é analista de ações escrevendo para assessores de investimento no Brasil. "
        f"Empresa: {nome} ({ticker}). Valores em {unidade}. Dados trimestrais: {json.dumps(dados, ensure_ascii=False)}.\n"
        f"Leitura automática prévia: {json.dumps(auto, ensure_ascii=False)}.\n"
        "Escreva em português, sem inventar fatos que não estejam nos números: "
        "1) uma frase dizendo se o resultado de " + auto["periodo"] + " foi bom, misto ou ruim; "
        "2) duas ou três frases explicando por quê, citando números; "
        "3) duas frases sobre o que observar nos próximos trimestres com base nas tendências. "
        "Responda em JSON: {\"veredito\": \"Bom|Misto|Ruim\", \"texto\": \"...\", \"esperar\": \"...\"}"
    )
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": chave, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": modelo, "max_tokens": 600,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        r.raise_for_status()
        txt = "".join(b.get("text", "") for b in r.json().get("content", []))
        ini, fim = txt.find("{"), txt.rfind("}")
        res = json.loads(txt[ini:fim + 1])
        cache[ck] = res
        return res
    except Exception as e:  # noqa: BLE001
        print(f"  [IA] falhou para {ticker}: {e}")
        return None


def proxima_data_util(d: dt.date) -> dt.date:
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def ordenar_codigos(codigos: Iterable[str]) -> list[str]:
    def chave(c):
        return [int(p) if p.isdigit() else p for p in str(c).split(".")]
    return sorted(codigos, key=chave)
