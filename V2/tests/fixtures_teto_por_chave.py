"""Insumos sintéticos do teto por chave: referência, histórico e ledger fakes.

Vivem FORA do teste porque a prova de não regressão roda a versão ANTIGA do
módulo (git show) contra estas MESMAS fixtures. Fixture duplicada não prova nada.
"""
import copy

# Referência de formato NOVO (com tracking e platform_lift), na escala da real de
# 03/08/2026: value_per_sale R$ 1.349,61 e fator 1,2312.
DECIS = [(4922, 5), (5798, 21), (7058, 21), (7814, 39), (8254, 53),
         (9253, 53), (10371, 82), (10289, 111), (10859, 135), (11523, 180)]
VPS = 1349.61
FATOR = 1.2312
LIFT_GOOGLE = 1.4834

CONVERSION = {
    'economics': {'value_per_sale': VPS, 'pct_cartao': 0.350},
    'by_decile': {f'D{i:02d}': {'leads': n, 'conv': k}
                  for i, (n, k) in enumerate(DECIS, 1)},
    'by_bucket': {'Lead': {'rate': 0.0087}},
    'tracking': {'factor': FATOR},
    'platform_lift': {'google': {'lift': LIFT_GOOGLE, 'valido': True}},
}

# Linha da tabela na ordem exata do SELECT do reference_reader.
LINHA_REFERENCIA = ("2026-05-04", "2026-08-03", "2026-08-24", "abr28", 86141,
                    CONVERSION, {"x": [0, 1], "y": [0, 0.1]}, None,
                    "2026-08-24 06:32:26")

# (criativo, leads, compradores, esperados, prior_conversao, prior_fonte)
HISTORICO = [
    ("DEV-AD0140", 6000, 90, 60.0, None, None),      # lift 1,5 e peso 0,75
    ("DEV-AD0999", 0, 0, 0.0, 0.009, "texto"),       # estreante com prior do texto
    ("1234567890", 8000, 40, 50.0, None, None),      # id do Google (vira nome pelo mapa)
]
MAPA_ID = [("1234567890", "DEV-AD0777")]

# (utm_campaign, utm_content, utm_medium, decil, n)
LEDGER = [
    ("CAMP_FRIA", "DEV-AD0140", "conj_a", 9, 300),
    ("CAMP_FRIA", "DEV-AD0140", "conj_a", 10, 200),
    ("CAMP_FRIA", "DEV-AD0140", "conj_b", 3, 400),
    ("CAMP_FRIA", "DEV-AD0999", "conj_a", 8, 250),
    ("CAMP_QUENTE", "DEV-AD0001", "conj_c", 5, 150),
    ("CAMP_QUENTE", "DEV-AD0001", "conj_c", 10, 150),
    ("devlf", "1234567890", "", 7, 500),             # colocação do Google
]


class FakeAnalytics:
    """Responde as três leituras que `tetos_completos` faz no analytics."""

    def __init__(self, linha_referencia=LINHA_REFERENCIA, historico=HISTORICO,
                 mapa_id=MAPA_ID):
        self.ref, self.hist, self.mapa = linha_referencia, historico, mapa_id
        self.sqls = []

    def run(self, sql, **params):
        self.sqls.append(sql)
        if "reference_rolling" in sql:
            # CÓPIA: teste que mexe no payload lido não pode contaminar o
            # próximo (o jsonb do banco também chega novo a cada leitura).
            return [copy.deepcopy(list(self.ref))] if self.ref else []
        if "criativo_id_map" in sql:
            return [list(r) for r in self.mapa]
        if "criativo_historico" in sql:
            return [list(r) for r in self.hist]
        raise AssertionError(f"SQL inesperado no analytics: {sql[:60]}")

    def close(self):
        pass


class FakeLedger:
    def __init__(self, linhas=LEDGER):
        self.linhas = linhas

    def run(self, sql, **params):
        return [list(r) for r in self.linhas]

    def close(self):
        pass
