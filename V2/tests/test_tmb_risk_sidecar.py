"""Guarda da frente TMB-risco: parser do relatório de contas a receber + filtro de
risco no modo db. Prova, sem banco, que:

  1. `read_tmb_risk_report` extrai {email_norm → grau} do export de parcelas, filtrando
     efetivados, normalizando email (strip/lower) e agregando por email (.first()) —
     mesma agregação do caminho de arquivos (`core/ingestion`), garantindo paridade.
  2. `filtrar_risco_tmb` (usado com sales_source='db') aplica só o grau de risco:
     all mantém tudo, none tira toda TMB, low/low_medium restringem TMB pelos graus,
     mantendo intactos os outros gateways e o TMB de risco desconhecido (igual files).

Rodável sem pytest:  python tests/test_tmb_risk_sidecar.py
"""
import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.validation.tmb_risk_store import read_tmb_risk_report
from src.core.ingestion import filtrar_risco_tmb


def test_read_tmb_risk_report():
    df = pd.DataFrame({
        "Pedido": [1, 1, 2, 3, 4],
        "Cliente Email": ["  Ana@X.com ", "ana@x.com", "BIA@x.com", "cadu@x.com", "dan@x.com"],
        "Grau de risco": ["Baixo", "Baixo", "Médio", "Alto", "Baixo"],
        "Status Pedido": ["Efetivado", "Efetivado", "Efetivado", "Efetivado", "Cancelado"],
    })
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    df.to_excel(path, index=False)
    try:
        risk = read_tmb_risk_report(path)
    finally:
        os.unlink(path)

    assert risk == {"ana@x.com": "Baixo", "bia@x.com": "Médio", "cadu@x.com": "Alto"}, risk
    assert "dan@x.com" not in risk, "cancelado não deve entrar"
    print("OK read_tmb_risk_report:", risk)


def _vendas():
    # 4 TMB (graus variados + 1 desconhecido) + 2 guru (não-TMB, nunca filtradas)
    return pd.DataFrame({
        "email":  ["ana@x.com", "bia@x.com", "cadu@x.com", "eva@x.com", "gui@x.com", "hel@x.com"],
        "origem": ["tmb", "tmb", "tmb", "tmb", "guru", "guru"],
    })


def test_filtrar_risco_tmb():
    lookup = {"ana@x.com": "Baixo", "bia@x.com": "Médio", "cadu@x.com": "Alto"}  # eva = desconhecido
    risk_values = ["Baixo", "Médio"]
    v = _vendas()

    allf = filtrar_risco_tmb(v, "all", lookup, risk_values)
    assert len(allf) == 6, len(allf)

    none = filtrar_risco_tmb(v, "none", lookup, risk_values)
    assert set(none["origem"]) == {"guru"} and len(none) == 2, none.to_dict()

    low = filtrar_risco_tmb(v, "low", lookup, risk_values)
    # TMB mantidas: ana(Baixo) + eva(desconhecido) ; fora: bia(Médio), cadu(Alto). +2 guru = 4
    assert set(low["email"]) == {"ana@x.com", "eva@x.com", "gui@x.com", "hel@x.com"}, low["email"].tolist()

    lowmed = filtrar_risco_tmb(v, "low_medium", lookup, risk_values)
    # TMB mantidas: ana(Baixo)+bia(Médio)+eva(desconhecido) ; fora: cadu(Alto). +2 guru = 5
    assert set(lowmed["email"]) == {"ana@x.com", "bia@x.com", "eva@x.com", "gui@x.com", "hel@x.com"}, lowmed["email"].tolist()
    print("OK filtrar_risco_tmb: all=6 none=2 low=4 low_medium=5")


if __name__ == "__main__":
    test_read_tmb_risk_report()
    test_filtrar_risco_tmb()
    print("\n✅ todos os testes passaram")
