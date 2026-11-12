"""Empresas da B3: universo (índices da B3), balanços (CVM DFP/ITR) e calendário."""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import os
import re
import unicodedata
import zipfile

import pandas as pd

from nucleo import (HOJE, Contas, alinhar, baixar, indicadores, meses, ordenar_codigos,
                    para_data, perto, proxima_data_util, resumo_automatico, resumo_ia,
                    rotulo_ano, rotulo_trimestre)

CVM = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC"
CACHE = os.environ.get("CACHE_DIR", "cache")
DEMONS = {"BPA": "Balanço – Ativo", "BPP": "Balanço – Passivo e PL",
          "DRE": "Resultado (DRE)", "DFC_MI": "Fluxo de caixa", "DFC_MD": "Fluxo de caixa"}

# Lista de reserva caso a B3 não responda (composição aproximada do IBrX-100).
RESERVA_IBRX = """ABEV3 ALOS3 ALPA4 ASAI3 AURE3 AXIA3 AZZA3 B3SA3 BBAS3 BBDC3 BBDC4 BBSE3 BEEF3 BPAC11
BRAP4 BRAV3 BRFS3 BRKM5 CMIG4 CMIN3 COGN3 CPFE3 CPLE6 CSAN3 CSMG3 CSNA3 CVCB3 CXSE3 CYRE3 DIRR3
EGIE3 EMBR3 ENEV3 ENGI11 EQTL3 EZTC3 FLRY3 GGBR4 GOAU4 HAPV3 HYPE3 IGTI11 IRBR3 ISAE4 ITSA4 ITUB4
KLBN11 LREN3 MGLU3 MOTV3 MRFG3 MRVE3 MULT3 NTCO3 PCAR3 PETR3 PETR4 PETZ3 POMO4 PRIO3 PSSA3 RADL3
RAIL3 RAIZ4 RDOR3 RECV3 RENT3 SANB11 SBSP3 SLCE3 SMFT3 SMTO3 STBP3 SUZB3 TAEE11 TIMS3 TOTS3 UGPA3
USIM5 VALE3 VAMO3 VBBR3 VIVA3 VIVT3 WEGE3 YDUQ3 CEAB3 GMAT3 MDIA3 ODPV3 SAPR11 SIMH3 TEND3 CURY3
DXCO3 INTB3 LWSA3 RAPT4""".split()


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn").lower()


# ---------------------------------------------------------------- universo

def carteira_indice(indice: str) -> list[dict]:
    out, pagina = [], 1
    while True:
        p = {"language": "pt-br", "pageNumber": pagina, "pageSize": 120, "index": indice, "segment": "1"}
        cod = base64.b64encode(json.dumps(p).encode()).decode()
        url = f"https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/{cod}"
        j = json.loads(baixar(url, timeout=60))
        for r in j.get("results", []):
            peso = str(r.get("part", "0")).replace(".", "").replace(",", ".")
            try:
                peso = float(peso)
            except ValueError:
                peso = 0.0
            out.append({"ticker": r.get("cod", "").strip(), "nome": (r.get("asset") or "").strip(), "peso": peso})
        tot = (j.get("page") or {}).get("totalPages", 1) or 1
        if pagina >= tot:
            break
        pagina += 1
    return out


def universo(cfg: dict) -> list[dict]:
    lista: dict[str, dict] = {}
    for ind in cfg.get("indices_b3", ["IBXX"]):
        try:
            itens = carteira_indice(ind)
            print(f"[B3] índice {ind}: {len(itens)} ações")
            for it in itens:
                if it["ticker"] and it["ticker"] not in lista:
                    lista[it["ticker"]] = it
        except Exception as e:  # noqa: BLE001
            print(f"[B3] não consegui ler o índice {ind}: {e}")
    if not lista:
        print("[B3] usando lista de reserva do IBrX-100")
        lista = {t: {"ticker": t, "nome": "", "peso": 0.0} for t in RESERVA_IBRX}
    for t in cfg.get("tickers_b3_extras", []):
        lista.setdefault(t, {"ticker": t, "nome": "", "peso": 0.0})
    for t in cfg.get("tickers_b3_excluir", []):
        lista.pop(t, None)
    return list(lista.values())


def _cnpj_b3(raiz: str) -> str | None:
    """Consulta o cadastro de empresas da B3 pela raiz do ticker (ex.: CSNA)."""
    try:
        p = {"language": "pt-br", "pageNumber": 1, "pageSize": 20, "company": raiz}
        cod = base64.b64encode(json.dumps(p).encode()).decode()
        url = f"https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetInitialCompanies/{cod}"
        for r in json.loads(baixar(url, timeout=30, tentativas=2)).get("results", []):
            if (r.get("issuingCompany") or "").upper() == raiz and r.get("cnpj"):
                c = re.sub(r"\D", "", r["cnpj"]).zfill(14)
                return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"
    except Exception as e:  # noqa: BLE001
        print(f"[B3] cadastro B3 indisponível para {raiz}: {e}")
    return None


# ---------------------------------------------------------------- arquivos da CVM

def zip_cvm(tipo: str, ano: int, forcar: bool = False) -> zipfile.ZipFile | None:
    nome = f"{tipo.lower()}_cia_aberta_{ano}.zip"
    caminho = os.path.join(CACHE, nome)
    antigo = ano < HOJE.year - 1 and tipo != "FCA"
    if forcar or not os.path.exists(caminho) or not antigo:
        try:
            baixar(f"{CVM}/{tipo}/DADOS/{nome}", destino=caminho, timeout=600)
        except FileNotFoundError:
            return None
        except Exception as e:  # noqa: BLE001
            if not os.path.exists(caminho):
                print(f"[CVM] falha em {nome}: {e}")
                return None
            print(f"[CVM] falha em {nome}, usando cópia anterior: {e}")
    try:
        return zipfile.ZipFile(caminho)
    except zipfile.BadZipFile:
        print(f"[CVM] arquivo corrompido: {nome}")
        return None


def ler_csv(z: zipfile.ZipFile, parte: str) -> pd.DataFrame | None:
    nomes = [n for n in z.namelist() if n.lower().endswith(".csv") and parte.lower() in n.lower()]
    if not nomes:
        return None
    with z.open(nomes[0]) as f:
        return pd.read_csv(io.BytesIO(f.read()), sep=";", encoding="latin-1", dtype=str)


def _col(df: pd.DataFrame, *palavras) -> str | None:
    for c in df.columns:
        cl = _sem_acento(c)
        if all(p in cl for p in palavras):
            return c
    return None


def mapa_tickers() -> tuple[dict, dict]:
    """ticker -> CNPJ e CNPJ -> {setor, nome} a partir do Formulário Cadastral (FCA) da CVM."""
    t2c, info = {}, {}
    for ano in (HOJE.year, HOJE.year - 1):
        z = zip_cvm("FCA", ano)
        if not z:
            continue
        vm = ler_csv(z, "valor_mobiliario")
        if vm is not None:
            c_cnpj, c_tk = _col(vm, "cnpj"), _col(vm, "codigo", "negocia")
            if c_cnpj and c_tk:
                for cnpj, tk in zip(vm[c_cnpj], vm[c_tk]):
                    if isinstance(tk, str) and tk.strip():
                        t2c.setdefault(tk.strip().upper(), cnpj)
        ge = ler_csv(z, "geral")
        if ge is not None:
            c_cnpj, c_set = _col(ge, "cnpj"), _col(ge, "setor")
            c_nome = _col(ge, "nome_empresarial") or _col(ge, "nome")
            for _, r in ge.iterrows():
                cnpj = r.get(c_cnpj)
                if cnpj and cnpj not in info:
                    info[cnpj] = {"setor": (r.get(c_set) or "") if c_set else "",
                                  "razao": (r.get(c_nome) or "") if c_nome else ""}
    print(f"[CVM] FCA: {len(t2c)} tickers mapeados")
    return t2c, info


# ---------------------------------------------------------------- balanços

def carregar_demonstracoes(cnpjs: set[str], anos: int):
    contas: dict[str, Contas] = {c: Contas() for c in cnpjs}
    entregas: dict[str, dict] = {c: {} for c in cnpjs}   # cnpj -> DT_REFER -> {receb, link, tipo}
    usa_con: dict[tuple, bool] = {}
    acoes: dict[str, dict] = {}
    arquivos = [("ITR", a) for a in range(HOJE.year, HOJE.year - anos, -1)] + \
               [("DFP", a) for a in range(HOJE.year, HOJE.year - anos - 1, -1)]
    for tipo, ano in arquivos:
        z = zip_cvm(tipo, ano)
        if not z:
            continue
        print(f"[CVM] lendo {tipo} {ano}")
        cab = ler_csv(z, f"cia_aberta_{ano}")
        if cab is not None:
            cab = cab[cab["CNPJ_CIA"].isin(cnpjs)]
            for r in cab.itertuples(index=False):
                d = entregas[r.CNPJ_CIA].setdefault(r.DT_REFER, {"tipo": tipo, "versoes": []})
                d["versoes"].append((int(r.VERSAO), r.DT_RECEB, getattr(r, "LINK_DOC", "")))
        cc = ler_csv(z, "composicao_capital")
        if cc is not None:
            _absorver_capital(acoes, cc, cnpjs)
        for dem in ("BPA", "BPP", "DRE", "DFC_MI", "DFC_MD"):
            for escopo in ("con", "ind"):
                df = ler_csv(z, f"_{dem}_{escopo}_")
                if df is None:
                    continue
                df = df[df["CNPJ_CIA"].isin(cnpjs)]
                if df.empty:
                    continue
                # só a última versão de cada entrega
                df["VERSAO"] = df["VERSAO"].astype(int)
                mx = df.groupby(["CNPJ_CIA", "DT_REFER"])["VERSAO"].transform("max")
                df = df[df["VERSAO"] == mx]
                dem_key = "DFC" if dem.startswith("DFC") else dem
                for cnpj, g in df.groupby("CNPJ_CIA"):
                    k = (cnpj, dem_key)
                    if escopo == "ind" and usa_con.get(k):
                        continue
                    if escopo == "con":
                        usa_con[k] = True
                    _absorver(contas[cnpj], dem_key, g)
    for cnpj, d in entregas.items():
        for ref, info in d.items():
            vs = sorted(info["versoes"])
            info["receb"] = vs[0][1][:10] if vs else None
            info["link"] = vs[-1][2] if vs else ""
            del info["versoes"]
    print(f"[CVM] composição do capital encontrada para {len(acoes)} empresas")
    return contas, entregas, acoes


_COLS_LOGADAS = False


def _absorver_capital(acoes: dict, cc: pd.DataFrame, cnpjs: set[str]):
    """Quantidade de ações ON e PN em circulação (capital integralizado menos tesouraria)."""
    global _COLS_LOGADAS
    if not _COLS_LOGADAS:
        print(f"[CVM] colunas da composição do capital: {list(cc.columns)}")
        _COLS_LOGADAS = True
    c_cnpj = _col(cc, "cnpj")
    c_ref = _col(cc, "data_referencia") or _col(cc, "dt_refer")
    c_ver = _col(cc, "versao")
    c_on = _col(cc, "ordin", "integr") or _col(cc, "ordin", "cap")
    c_pn = _col(cc, "pref", "integr") or _col(cc, "pref", "cap")
    c_ton = _col(cc, "ordin", "tesour")
    c_tpn = _col(cc, "pref", "tesour")
    if not (c_cnpj and c_ref and c_on):
        print("[CVM] não reconheci as colunas da composição do capital")
        return
    num = lambda v: float(str(v).replace(",", ".")) if v not in (None, "") and str(v) != "nan" else 0.0  # noqa: E731
    for r in cc[cc[c_cnpj].isin(cnpjs)].to_dict("records"):
        ref = str(r.get(c_ref))[:10]
        ver = int(num(r.get(c_ver))) if c_ver else 0
        atual = acoes.get(r[c_cnpj])
        if atual and (atual["ref"], atual["ver"]) >= (ref, ver):
            continue
        on = num(r.get(c_on)) - (num(r.get(c_ton)) if c_ton else 0)
        pn = (num(r.get(c_pn)) if c_pn else 0) - (num(r.get(c_tpn)) if c_tpn else 0)
        if on + pn > 0:
            acoes[r[c_cnpj]] = {"on": on, "pn": max(pn, 0), "ref": ref, "ver": ver}


def _absorver(c: Contas, dem: str, g: pd.DataFrame):
    escala = g["ESCALA_MOEDA"].fillna("MIL").str.upper()
    fator = escala.map(lambda e: 0.001 if e.startswith("UNID") else 1.0)
    vals = pd.to_numeric(g["VL_CONTA"], errors="coerce") * fator
    ultimo = g["ORDEM_EXERC"].fillna("").map(lambda s: 1 if _sem_acento(s).startswith("ult") else 0)
    tem_ini = "DT_INI_EXERC" in g.columns
    for i, r in enumerate(g.itertuples(index=False)):
        v = vals.iloc[i]
        if pd.isna(v):
            continue
        fim = para_data(r.DT_FIM_EXERC)
        ref = para_data(r.DT_REFER)
        prio = ultimo.iloc[i] * 10_000_000 + (ref.toordinal() if ref else 0)
        conta = f"{dem}|{r.CD_CONTA}"
        if dem in ("BPA", "BPP"):
            c.saldo(conta, fim, v, prio, r.DS_CONTA)
        else:
            ini = para_data(r.DT_INI_EXERC) if tem_ini else None
            c.fluxo(conta, ini, fim, v, prio, r.DS_CONTA)


# ---------------------------------------------------------------- contas-chave

def _achar(c: Contas, dem: str, padrao: str, nivel: int | None = None, excluir: str | None = None) -> list[str]:
    out = []
    for k, nome in c.nomes.items():
        d, cod = k.split("|", 1)
        if d != dem:
            continue
        if nivel is not None and cod.count(".") + 1 != nivel:
            continue
        n = _sem_acento(nome)
        if re.search(padrao, n) and not (excluir and re.search(excluir, n)):
            out.append(k)
    return ordenar_codigos(out) if out else out


def series_base(c: Contas, fins: list[dt.date]) -> tuple[dict, bool]:
    tri = lambda k: alinhar(c.trimestral(k), fins) if k else [None] * len(fins)  # noqa: E731
    sal = lambda k: alinhar(c.instantes(k), fins) if k else [None] * len(fins)  # noqa: E731

    def soma(listas):
        out = []
        for vals in zip(*listas) if listas else [[None]] * len(fins):
            vs = [v for v in vals if v is not None]
            out.append(sum(vs) if vs else None)
        return out

    rec = "DRE|3.01" if "DRE|3.01" in c.nomes else None
    ebit = (_achar(c, "DRE", r"antes do resultado financeiro", 2) or [None])[0]
    financeira = ebit is None
    bruto = (_achar(c, "DRE", r"resultado bruto", 2) or [None])[0]
    cands = _achar(c, "DRE", r"(lucro|prejuizo).*(periodo|exercicio)", 2, r"continuad|antes|por acao")
    ordem = []
    for k in reversed(cands):  # do mais "final" para o anterior
        filhos = [f for f in _achar(c, "DRE", r"controlador", None, r"nao controlador") if f.startswith(k + ".")]
        ordem += filhos[:1] + [k]
    ordem += _achar(c, "DRE", r"(lucro|prejuizo).*continuad", 2, r"descontinuad")
    da = [k for k in _achar(c, "DFC", r"deprecia|amortiza|exaust") if k.split("|")[1].startswith("6.01")]
    # evita contar pai e filho
    da = [k for k in da if not any(o != k and o.startswith(k + ".") for o in da)]
    fco = "DFC|6.01" if "DFC|6.01" in c.nomes else None
    capex = [k for k in _achar(c, "DFC", r"(aquisi|compra|adic|investimento).*(imobilizado|intangivel)")
             if k.split("|")[1].startswith("6.02")]
    capex = [k for k in capex if not any(o != k and o.startswith(k + ".") for o in capex)]
    divs = [k for k in _achar(c, "DFC", r"dividend|juros sobre (o )?capital|jscp")
            if k.split("|")[1].startswith("6.03")]
    divs = [k for k in divs if not any(o != k and o.startswith(k + ".") for o in divs)]
    c.debug_divs = [f"{k.split('|')[1]} {c.nomes[k]}" for k in divs]
    pl = _achar(c, "BPP", r"patrimonio liquido", 2)
    pl = pl[-1] if pl else None
    divida = _achar(c, "BPP", r"emprestimos e financiamentos", 3)
    caixa = _achar(c, "BPA", r"caixa e equivalentes|aplicacoes financeiras", 3)
    caixa = [k for k in caixa if k.split("|")[1].startswith("1.01.")]

    lucro_s = [None] * len(fins)
    for k in ordem:  # usa a conta preferida e completa lacunas com as alternativas
        for j, v in enumerate(tri(k)):
            if lucro_s[j] is None and v is not None:
                lucro_s[j] = v
    base = {
        "receita": tri(rec),
        "lucro_bruto": tri(bruto) if not financeira else [None] * len(fins),
        "ebit": tri(ebit),
        "da": soma([tri(k) for k in da]) if da else [None] * len(fins),
        "lucro": lucro_s,
        "fco": tri(fco),
        "capex": soma([tri(k) for k in capex]) if capex else [None] * len(fins),
        "ativo": sal("BPA|1" if "BPA|1" in c.nomes else None),
        "pl": sal(pl),
        "divida": soma([sal(k) for k in divida]) if (divida and not financeira) else [None] * len(fins),
        "caixa": soma([sal(k) for k in caixa]) if caixa else [None] * len(fins),
        "dividendos": [None if v is None else abs(v) for v in soma([tri(k) for k in divs])] if divs else [None] * len(fins),
    }
    return base, financeira


# ---------------------------------------------------------------- montagem por empresa

def demonstracoes_completas(c: Contas, fins: list[dt.date], fins_anuais: list[dt.date]) -> dict:
    out = {}
    for dem in ("DRE", "BPA", "BPP", "DFC"):
        cods = ordenar_codigos([k.split("|", 1)[1] for k in c.nomes if k.startswith(dem + "|")])
        linhas_t, linhas_a = [], []
        for cod in cods:
            k = f"{dem}|{cod}"
            if dem in ("BPA", "BPP"):
                vt = alinhar(c.instantes(k), fins)
                va = alinhar(c.instantes(k), fins_anuais)
            else:
                vt = alinhar(c.trimestral(k), fins)
                va = alinhar(c.anual(k), fins_anuais)
            if all(v is None for v in vt) and all(v is None for v in va):
                continue
            nivel = cod.count(".")
            linhas_t.append({"c": cod, "n": c.nomes[k], "nv": nivel, "v": vt})
            linhas_a.append({"c": cod, "n": c.nomes[k], "nv": nivel, "v": va})
        out[dem] = {"trimestral": linhas_t, "anual": linhas_a}
    return out


def processar(cfg: dict, cache_ia: dict) -> list[dict]:
    acoes = universo(cfg)
    t2c, info = mapa_tickers()
    grupos: dict[str, dict] = {}
    raiz = {}
    for tk, cn in t2c.items():
        raiz.setdefault(tk[:4], cn)
    for a in acoes:
        tk = a["ticker"].upper()
        cnpj = t2c.get(tk) or raiz.get(tk[:4]) or _cnpj_b3(tk[:4])
        if not cnpj:
            print(f"[B3] sem CNPJ para {a['ticker']}")
            continue
        g = grupos.setdefault(cnpj, {"tickers": [], "nome": a["nome"], "peso": 0.0})
        g["tickers"].append(a["ticker"])
        g["peso"] += a["peso"]
    print(f"[B3] {len(grupos)} empresas no universo")
    contas, entregas, acoes = carregar_demonstracoes(set(grupos), cfg.get("anos_historico", 3))

    empresas = []
    for cnpj, g in grupos.items():
        try:
            emp = _montar_empresa(cnpj, g, contas[cnpj], entregas[cnpj], info.get(cnpj, {}), cfg, cache_ia)
            if emp:
                emp["acoes"] = acoes.get(cnpj)
            if emp:
                empresas.append(emp)
        except Exception as e:  # noqa: BLE001
            print(f"[B3] erro em {g['tickers']}: {e}")
    return empresas


def _montar_empresa(cnpj, g, c: Contas, entregas, info, cfg, cache_ia):
    if not c.nomes:
        print(f"[B3] sem demonstrações para {g['tickers']}")
        return None
    # trimestres disponíveis = datas de saldo do ativo total
    q_rec = c.trimestral("DRE|3.01")
    fins_all = sorted(set(c.instantes("BPA|1")) | set(q_rec))
    fins = [f for f in fins_all if any(perto(f, g, 6) for g in q_rec)] or fins_all
    fins = fins[-12:]
    anuais = sorted(c.anual("DRE|3.01").keys())[-4:] or sorted(
        {f for (i, f) in c.fluxos.get("DRE|3.01", {}) if meses(i, f) == 12})[-4:]
    if not fins:
        return None
    ticker = sorted(g["tickers"], key=lambda t: (not t.endswith("4") and not t.endswith("11"), t))[0] \
        if len(g["tickers"]) > 1 else g["tickers"][0]
    rot = [rotulo_trimestre(f) for f in fins]
    base, financeira = series_base(c, fins)
    if ticker[:4] in ("VALE", "PETR"):
        print(f"[Debug] {ticker} contas de dividendos: {getattr(c, 'debug_divs', [])}")
    ind = indicadores(base, financeira)
    auto = resumo_automatico([r[1] for r in rot], base, ind, financeira, "BRL")
    nome = (g["nome"] or info.get("razao", "")).title() if g["nome"] else info.get("razao", ticker)
    ia = resumo_ia(nome, ticker, [r[1] for r in rot], base, ind, auto, "BRL",
                   cfg.get("modelo_ia", "claude-haiku-5-5"), cache_ia)

    # entrega do último período
    ult = fins[-1].isoformat()
    ent = entregas.get(ult, {})
    proximo = _proxima_entrega(fins[-1], entregas, anuais)

    return {
        "id": ticker,
        "ticker": ticker,
        "tickers": sorted(g["tickers"]),
        "nome": nome,
        "razao": info.get("razao", ""),
        "setor": info.get("setor", ""),
        "mercado": "B3",
        "moeda": "BRL",
        "financeira": financeira,
        "peso_indice": round(g["peso"], 3),
        "trimestres": [{"k": r[0], "l": r[1], "fim": f.isoformat()} for r, f in zip(rot, fins)],
        "anos": [{"l": rotulo_ano(f), "fim": f.isoformat()} for f in anuais],
        "base": base,
        "ind": {k: [None if v is None else round(v, 5) for v in vs] for k, vs in ind.items()},
        "demonstracoes": demonstracoes_completas(c, fins, anuais),
        "resumo": auto,
        "resumo_ia": ia,
        "divulgado_em": ent.get("receb"),
        "link": ent.get("link") or "",
        "fonte": "CVM – Dados Abertos (DFP/ITR)",
        "proximo": proximo,
    }


def _fim_mes(d: dt.date) -> dt.date:
    prox = (d.replace(day=28) + dt.timedelta(days=4))
    return prox - dt.timedelta(days=prox.day)


def _proxima_entrega(ultimo_fim: dt.date, entregas: dict, anuais: list[dt.date]) -> dict:
    alvo = _fim_mes(ultimo_fim + dt.timedelta(days=80))
    mes_fy = anuais[-1].month if anuais else 12
    eh_anual = alvo.month == mes_fy
    tipo = "Resultado anual (DFP)" if eh_anual else "Resultado trimestral (ITR)"
    # mesmo período do ano anterior
    ref_ant = None
    for ref, inf in entregas.items():
        d = para_data(ref)
        if d and perto(d, alvo.replace(year=alvo.year - 1), 6) and inf.get("receb"):
            ref_ant = para_data(inf["receb"])
    prazo = alvo + dt.timedelta(days=90 if eh_anual else 45)
    if ref_ant:
        est = proxima_data_util(ref_ant + dt.timedelta(days=364))
        base = "mesma época do ano passado"
        if est > prazo:
            est = prazo
    else:
        est = prazo
        base = "prazo da CVM"
    lbl = rotulo_trimestre(alvo)[1]
    return {"data": est.isoformat(), "periodo": lbl, "tipo": tipo, "base": base,
            "atrasado": est < HOJE}
