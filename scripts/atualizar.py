"""Atualiza todos os dados do portal. Rodado pelo GitHub Actions todos os dias."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

class _Tee:
    """Duplica a saída em site/data/log.txt para diagnóstico."""
    def __init__(self, *fs):
        self.fs = fs
    def write(self, x):
        for f in self.fs:
            f.write(x); f.flush()
    def flush(self):
        for f in self.fs:
            f.flush()


_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(os.path.join(_RAIZ, "site", "data"), exist_ok=True)
sys.stdout = _Tee(sys.__stdout__, open(os.path.join(_RAIZ, "site", "data", "log.txt"), "w", encoding="utf-8"))

import b3  # noqa: E402
import fundamentos  # noqa: E402
import sec  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA = os.path.join(RAIZ, "site", "data")
CACHE = os.environ.get("CACHE_DIR", os.path.join(RAIZ, "cache"))
os.environ["CACHE_DIR"] = CACHE
b3.CACHE = CACHE


def _var(a, b):
    if a is None or b in (None, 0):
        return None
    return (a - b) / abs(b)


def _ult(lst):
    for i in range(len(lst) - 1, -1, -1):
        if lst[i] is not None:
            return i
    return None


def resumo_indice(e: dict) -> dict:
    rec, luc = e["base"]["receita"], e["base"]["lucro"]
    i = _ult(rec) if _ult(rec) is not None else _ult(luc)
    i = i if i is not None else len(e["trimestres"]) - 1
    a = i - 4
    g = lambda s, j: s[j] if s and 0 <= j < len(s) else None  # noqa: E731
    ver = (e.get("resumo_ia") or {}).get("veredito") or e["resumo"]["veredito"]
    return {
        "id": e["id"], "ticker": e["ticker"], "nome": e["nome"], "setor": e["setor"],
        "mercado": e["mercado"], "moeda": e["moeda"], "financeira": e["financeira"],
        "periodo": e["trimestres"][i]["l"] if e["trimestres"] else None,
        "divulgado_em": e.get("divulgado_em"),
        "veredito": ver,
        "receita": g(rec, i), "receita_yoy": _var(g(rec, i), g(rec, a)),
        "lucro": g(luc, i), "lucro_yoy": _var(g(luc, i), g(luc, a)),
        "lucro_ant": g(luc, a),
        "margem_ebitda": g(e["ind"].get("margem_ebitda"), i),
        "margem_liquida": g(e["ind"].get("margem_liquida"), i),
        "proximo": e.get("proximo"),
        "pendente": e.get("pendente"),
        "positivos": e["resumo"].get("positivos", [])[:2],
        "negativos": e["resumo"].get("negativos", [])[:2],
        "fund": e.get("fund"),
    }


def main():
    cfg = json.load(open(os.path.join(RAIZ, "config.json"), encoding="utf-8"))
    os.makedirs(os.path.join(SAIDA, "empresas"), exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    cache_ia_path = os.path.join(CACHE, "resumos_ia.json")
    cache_ia = json.load(open(cache_ia_path)) if os.path.exists(cache_ia_path) else {}

    so = os.environ.get("SOMENTE", "")  # "b3" ou "sec" para testes
    empresas = []
    if so in ("", "sec"):
        empresas += sec.processar(cfg, cache_ia)
    if so in ("", "b3"):
        empresas += b3.processar(cfg, cache_ia)

    fundamentos.aplicar(empresas)

    indice = []
    for e in empresas:
        with open(os.path.join(SAIDA, "empresas", f"{e['id']}.json"), "w", encoding="utf-8") as f:
            json.dump(e, f, ensure_ascii=False, separators=(",", ":"))
        indice.append(resumo_indice(e))
    indice.sort(key=lambda x: x.get("divulgado_em") or "", reverse=True)

    agora = dt.datetime.now(dt.timezone(dt.timedelta(hours=-3)))
    with open(os.path.join(SAIDA, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"atualizado_em": agora.strftime("%Y-%m-%d %H:%M"), "empresas": indice},
                  f, ensure_ascii=False, separators=(",", ":"))
    json.dump(cache_ia, open(cache_ia_path, "w"), ensure_ascii=False)

    nb3 = sum(1 for e in empresas if e["mercado"] == "B3")
    nbdr = len(empresas) - nb3
    print(f"\nPRONTO: {nb3} empresas da B3 e {nbdr} BDRs. IA: {'sim' if os.environ.get('ANTHROPIC_API_KEY') else 'não'}")
    if not empresas:
        sys.exit("Nenhuma empresa processada")


if __name__ == "__main__":
    main()
