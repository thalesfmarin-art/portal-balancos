"""BDRs: balanços das empresas americanas pela SEC (XBRL companyfacts) e calendário pelos 8-K."""
from __future__ import annotations

import datetime as dt
import json
import os
import time

from nucleo import (HOJE, Contas, alinhar, baixar, indicadores, meses, para_data, perto,
                    proxima_data_util, resumo_automatico, resumo_ia, rotulo_ano, rotulo_trimestre)

UA = os.environ.get("SEC_USER_AGENT") or "PortalBalancos/1.0 (github.com/thalesfmarin-art/portal-balancos)"
H = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}

# (demonstração, nome da linha, conceitos alternativos em ordem de preferência, unidade)
LINHAS = [
    ("DRE", "Receita líquida", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"], "USD"),
    ("DRE", "Custo dos produtos e serviços", ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"], "USD"),
    ("DRE", "Lucro bruto", ["GrossProfit"], "USD"),
    ("DRE", "Pesquisa e desenvolvimento", ["ResearchAndDevelopmentExpense",
                                           "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"], "USD"),
    ("DRE", "Despesas de vendas, gerais e administrativas", ["SellingGeneralAndAdministrativeExpense"], "USD"),
    ("DRE", "Custos e despesas operacionais totais", ["CostsAndExpenses", "OperatingExpenses"], "USD"),
    ("DRE", "Lucro operacional (EBIT)", ["OperatingIncomeLoss"], "USD"),
    ("DRE", "Resultado não operacional", ["NonoperatingIncomeExpense", "OtherNonoperatingIncomeExpense"], "USD"),
    ("DRE", "Lucro antes dos impostos", [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"], "USD"),
    ("DRE", "Imposto de renda", ["IncomeTaxExpenseBenefit"], "USD"),
    ("DRE", "Lucro líquido", ["NetIncomeLoss", "ProfitLoss"], "USD"),
    ("DRE", "Lucro por ação diluído (US$)", ["EarningsPerShareDiluted"], "USD/shares"),
    ("DRE", "Lucro por ação básico (US$)", ["EarningsPerShareBasic"], "USD/shares"),
    ("BPA", "Caixa e equivalentes", ["CashAndCashEquivalentsAtCarryingValue",
                                     "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"], "USD"),
    ("BPA", "Aplicações financeiras de curto prazo", ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                                                      "AvailableForSaleSecuritiesDebtSecuritiesCurrent"], "USD"),
    ("BPA", "Contas a receber", ["AccountsReceivableNetCurrent"], "USD"),
    ("BPA", "Estoques", ["InventoryNet"], "USD"),
    ("BPA", "Ativo circulante", ["AssetsCurrent"], "USD"),
    ("BPA", "Imobilizado", ["PropertyPlantAndEquipmentNet"], "USD"),
    ("BPA", "Goodwill (ágio)", ["Goodwill"], "USD"),
    ("BPA", "Ativo total", ["Assets"], "USD"),
    ("BPP", "Fornecedores", ["AccountsPayableCurrent"], "USD"),
    ("BPP", "Passivo circulante", ["LiabilitiesCurrent"], "USD"),
    ("BPP", "Dívida de curto prazo", ["LongTermDebtCurrent", "DebtCurrent"], "USD"),
    ("BPP", "Dívida de longo prazo", ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"], "USD"),
    ("BPP", "Passivo total", ["Liabilities"], "USD"),
    ("BPP", "Patrimônio líquido", ["StockholdersEquity",
                                   "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"], "USD"),
    ("BPP", "Passivo total + patrimônio líquido", ["LiabilitiesAndStockholdersEquity"], "USD"),
    ("DFC", "Caixa gerado nas operações", ["NetCashProvidedByUsedInOperatingActivities"], "USD"),
    ("DFC", "Depreciação e amortização", ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
                                          "DepreciationAndAmortization", "Depreciation"], "USD"),
    ("DFC", "Remuneração em ações", ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"], "USD"),
    ("DFC", "Investimento em imobilizado (capex)", ["PaymentsToAcquirePropertyPlantAndEquipment",
                                                    "PaymentsToAcquireProductiveAssets"], "USD"),
    ("DFC", "Caixa de investimentos", ["NetCashProvidedByUsedInInvestingActivities"], "USD"),
    ("DFC", "Recompra de ações", ["PaymentsForRepurchaseOfCommonStock"], "USD"),
    ("DFC", "Dividendos pagos", ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"], "USD"),
    ("DFC", "Caixa de financiamentos", ["NetCashProvidedByUsedInFinancingActivities"], "USD"),
]
SALDOS = {"BPA", "BPP"}


def _get_json(url):
    time.sleep(0.15)
    return json.loads(baixar(url, headers=H, timeout=90))


def mapa_cik() -> dict[str, int]:
    j = _get_json("https://www.sec.gov/files/company_tickers.json")
    return {v["ticker"].upper(): int(v["cik_str"]) for v in j.values()}


def _contas(facts: dict) -> Contas:
    c = Contas()
    limite = HOJE - dt.timedelta(days=int(365 * 4.5))
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for i, (dem, nome, conceitos, unidade) in enumerate(LINHAS):
        chave = f"{dem}|{i:02d}"
        c.nomes[chave] = nome
        for j, conceito in enumerate(conceitos):
            regs = gaap.get(conceito, {}).get("units", {}).get(unidade, [])
            for r in regs:
                if not str(r.get("form", "")).startswith(("10-Q", "10-K")):
                    continue
                fim = para_data(r.get("end"))
                if not fim or fim < limite:
                    continue
                filed = para_data(r.get("filed")) or HOJE
                prio = (len(conceitos) - j) * 10_000_000 + filed.toordinal()
                v = r.get("val")
                if v is None:
                    continue
                v = float(v) if unidade == "USD/shares" else float(v) / 1000.0  # US$ mil
                if dem in SALDOS:
                    c.saldo(chave, fim, v, prio)
                else:
                    c.fluxo(chave, para_data(r.get("start")), fim, v, prio)
    return c


def _k(nome: str) -> str:
    for i, l in enumerate(LINHAS):
        if l[1] == nome:
            return f"{l[0]}|{i:02d}"
    raise KeyError(nome)


def _base(c: Contas, fins):
    tri = lambda n: alinhar(c.trimestral(_k(n)), fins)  # noqa: E731
    sal = lambda n: alinhar(c.instantes(_k(n)), fins)  # noqa: E731

    def soma(*ls):
        return [None if all(v is None for v in vs) else sum(v for v in vs if v is not None) for vs in zip(*ls)]

    return {
        "receita": tri("Receita líquida"),
        "lucro_bruto": tri("Lucro bruto"),
        "ebit": tri("Lucro operacional (EBIT)"),
        "da": tri("Depreciação e amortização"),
        "lucro": tri("Lucro líquido"),
        "fco": tri("Caixa gerado nas operações"),
        "capex": tri("Investimento em imobilizado (capex)"),
        "ativo": sal("Ativo total"),
        "pl": sal("Patrimônio líquido"),
        "divida": soma(sal("Dívida de curto prazo"), sal("Dívida de longo prazo")),
        "caixa": soma(sal("Caixa e equivalentes"), sal("Aplicações financeiras de curto prazo")),
    }


def _demonstracoes(c: Contas, fins, anuais):
    out = {}
    for dem in ("DRE", "BPA", "BPP", "DFC"):
        lt, la = [], []
        for i, (d, nome, _, un) in enumerate(LINHAS):
            if d != dem:
                continue
            k = f"{d}|{i:02d}"
            if dem in SALDOS:
                vt, va = alinhar(c.instantes(k), fins), alinhar(c.instantes(k), anuais)
            else:
                vt, va = alinhar(c.trimestral(k), fins), alinhar(c.anual(k), anuais)
                if un == "USD/shares":  # LPA não é aditivo: trimestre só se reportado direto
                    vt = alinhar({f: v[0] for (ini, f), v in c.fluxos.get(k, {}).items() if meses(ini, f) == 3}, fins)
            if all(v is None for v in vt) and all(v is None for v in va):
                continue
            lt.append({"c": str(i), "n": nome, "nv": 0, "v": vt, "u": un})
            la.append({"c": str(i), "n": nome, "nv": 0, "v": va, "u": un})
        out[dem] = {"trimestral": lt, "anual": la}
    return out


def _filings(cik: int):
    j = _get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    r = j.get("filings", {}).get("recent", {})
    n = len(r.get("form", []))
    out = []
    for i in range(n):
        out.append({
            "form": r["form"][i],
            "filed": para_data(r["filingDate"][i]),
            "report": para_data(r.get("reportDate", [""] * n)[i]),
            "items": r.get("items", [""] * n)[i] or "",
            "accn": r["accessionNumber"][i],
            "doc": r.get("primaryDocument", [""] * n)[i],
        })
    return out


def processar(cfg: dict, cache_ia: dict) -> list[dict]:
    try:
        ciks = mapa_cik()
    except Exception as e:  # noqa: BLE001
        print(f"[SEC] não consegui baixar a lista de CIKs: {e}")
        return []
    out = []
    for b in cfg.get("bdrs", []):
        tk = b["ticker_eua"].upper()
        cik = ciks.get(tk)
        if not cik:
            print(f"[SEC] CIK não encontrado para {tk}")
            continue
        try:
            print(f"[SEC] {tk}")
            facts = _get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
            filings = _filings(cik)
            emp = _montar(b, cik, facts, filings, cfg, cache_ia)
            if emp:
                out.append(emp)
        except Exception as e:  # noqa: BLE001
            print(f"[SEC] erro em {tk}: {e}")
    return out


def _montar(b, cik, facts, filings, cfg, cache_ia):
    c = _contas(facts)
    fins = sorted(c.instantes(_k("Ativo total")).keys())[-12:]
    if not fins:
        return None
    anuais = sorted(c.anual(_k("Receita líquida")).keys())[-4:]
    rot = [rotulo_trimestre(f) for f in fins]
    base = _base(c, fins)
    ind = indicadores(base, False)
    auto = resumo_automatico([r[1] for r in rot], base, ind, False, "USD")
    ia = resumo_ia(b["nome"], b["bdr"], [r[1] for r in rot], base, ind, auto, "USD",
                   cfg.get("modelo_ia", "claude-haiku-5-5"), cache_ia)

    releases = sorted(f["filed"] for f in filings
                      if f["form"].startswith("8-K") and "2.02" in f["items"] and f["filed"])
    ult = fins[-1]
    divulg = next((d for d in releases if ult < d <= ult + dt.timedelta(days=75)), None)
    rel = next((f for f in filings if f["form"].startswith(("10-Q", "10-K")) and f["report"]
                and perto(f["report"], ult, 3)), None)
    if not divulg and rel:
        divulg = rel["filed"]
    link = ""
    if rel:
        link = f"https://www.sec.gov/Archives/edgar/data/{cik}/{rel['accn'].replace('-', '')}/{rel['doc']}"

    # resultado novo já anunciado (8-K) mas ainda sem 10-Q com os números detalhados
    pendente = next((d for d in releases if d > ult + dt.timedelta(days=80)), None)

    # próxima divulgação estimada: data do mesmo trimestre no ano anterior + 364 dias
    ultimo_release = pendente or divulg or ult + dt.timedelta(days=30)
    alvo = ultimo_release + dt.timedelta(days=91)
    ref = [d for d in releases if perto(d, alvo - dt.timedelta(days=364), 25)]
    if ref:
        est, base_est = proxima_data_util(ref[0] + dt.timedelta(days=364)), "mesma época do ano passado"
    else:
        est, base_est = proxima_data_util(alvo), "intervalo trimestral"
    fim_prox = ult + dt.timedelta(days=91 * (2 if pendente else 1))

    return {
        "id": b["bdr"],
        "ticker": b["bdr"],
        "tickers": [b["bdr"]],
        "ticker_eua": b["ticker_eua"],
        "nome": b["nome"],
        "razao": facts.get("entityName", ""),
        "setor": b.get("tema", "Tecnologia"),
        "mercado": "BDR",
        "moeda": "USD",
        "financeira": False,
        "trimestres": [{"k": r[0], "l": r[1], "fim": f.isoformat()} for r, f in zip(rot, fins)],
        "anos": [{"l": rotulo_ano(f), "fim": f.isoformat()} for f in anuais],
        "base": base,
        "ind": {k: [None if v is None else round(v, 5) for v in vs] for k, vs in ind.items()},
        "demonstracoes": _demonstracoes(c, fins, anuais),
        "resumo": auto,
        "resumo_ia": ia,
        "divulgado_em": divulg.isoformat() if divulg else None,
        "link": link,
        "pendente": pendente.isoformat() if pendente else None,
        "fonte": "SEC EDGAR (10-Q/10-K, XBRL)",
        "proximo": {"data": est.isoformat(), "periodo": rotulo_trimestre(fim_prox)[1],
                    "tipo": "Resultado trimestral", "base": base_est, "atrasado": est < HOJE},
    }
