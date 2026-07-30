"""Testes do resolvedor de braço A/B (core/ab_arm.py).

Casos aterrados em nomes de campanha reais extraídos dos relatórios de validação.
Rodar: python3 -m pytest V2/tests/test_ab_arm.py   (de bring_data/ ou V2/)
ou:    python3 V2/tests/test_ab_arm.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # V2/ no path

from src.core.ab_arm import (
    resolve_arm, CHAMPION, CHALLENGER, CONTROLE, EXTERNO, INDETERMINADO,
)

# (descrição, kwargs, esperado)
CASES = [
    # 1. variant do ledger é a verdade — vence qualquer nome
    # O papel do abr28 MUDOU em 25/07/2026 (challenger -> champion), então este caso
    # precisa de data pra ser determinístico. Antes ele não tinha, e passava só porque
    # o papel estava cravado no código. A datação é o ponto: ver bloco 8.
    ("variant challenger vence (na data em que abr28 era challenger)", dict(
        variant="challenger_abr28", captured_at="2026-06-15",
        campaign_name="DEVLF | CAP | FRIO | ... | LEADQUALIFIED|1"), CHALLENGER),
    ("variant champion vence", dict(variant="champion_jan30",
        campaign_name="DEVLF | CAP | FRIO | ... | LEADHQLB|1"), CHAMPION),
    ("variant desconhecido -> indeterminado", dict(variant="modelo_xpto"), INDETERMINADO),

    # 2. ML_MAR (mar/2026) = Challenger (confirmado pelo usuário)
    ("ML_MAR HLQC = challenger", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | ML_MAR | HLQC | PG2 | 2025-03-31|120241438584920390",
        captured_at="2026-03-31"), CHALLENGER),
    ("ML_MAR LQC = challenger", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | ML_MAR | LQC | PG2 | 2025-03-31|120241438584940390",
        captured_at="2026-03-31"), CHALLENGER),

    # 3. Era moderna (27/05+): LEADHQLB = Challenger, LEADQUALIFIED = Champion
    ("LEADHQLB = challenger", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-05-26 | LEADHQLB|120244794184240390",
        captured_at="2026-05-26"), CHALLENGER),
    ("LEADQUALIFIED = champion", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-05-26 | LEADQUALIFIED|120244717912530390",
        captured_at="2026-05-26"), CHAMPION),
    ("MACHINE LEARNING sem marcador challenger = champion", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 01 | ADV | MACHINE LEARNING | PG2 | 2026-06-08|1",
        captured_at="2026-06-08"), CHAMPION),

    # 4. Era ambígua (PIXEL NOVO API, 29/04-27/05): sem variant -> indeterminado
    ("PIXEL NOVO API ambíguo sem variant -> indeterminado", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | PIXEL NOVO API | MACHINE LEARNING | LEAD | PG2 | 1",
        captured_at="2026-05-10"), INDETERMINADO),
    ("PIXEL NOVO API + variant champion -> champion (variant vence)", dict(
        variant="champion_jan30",
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | PIXEL NOVO API | MACHINE LEARNING | LEAD | PG2 | 1",
        captured_at="2026-05-10"), CHAMPION),

    # 5. Controle: captação sem evento ML (lead puro, score, faixa)
    ("LEAD puro = controle", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-05-25|120244621534140390",
        captured_at="2026-05-25"), CONTROLE),
    ("ABERTO ADV+ SCORE = controle", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 01 | ABERTO ADV+ | PG2 | SCORE | 2025-04-15|1",
        captured_at="2026-04-15"), CONTROLE),
    ("FAIXA A = controle", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | FAIXA A | PG2 | 2025-08-13|1",
        captured_at="2026-04-13"), CONTROLE),
    ("ESCALA SCORE = controle", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | ESCALA SCORE | PG2 | 1",
        captured_at="2026-04-13"), CONTROLE),

    # 6. Externo: não-captação
    ("devlf minúsculo (Google) = externo", dict(campaign_name="devlf"), EXTERNO),
    ("vazio = externo", dict(campaign_name="", captured_at="2026-06-01"), EXTERNO),
    ("None = externo", dict(campaign_name=None, utm_campaign=None), EXTERNO),

    # 6b. NaN (float) em variant/campaign = ausente (regressão: NaN é truthy em Python)
    ("variant NaN não engole — cai no nome (champion)", dict(
        variant=float("nan"),
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | MACHINE LEARNING | PG2 | 2026-05-08|1",
        captured_at="2026-05-08"), CHAMPION),
    ("variant NaN + LEAD puro = controle", dict(
        variant=float("nan"),
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-05-25|1",
        captured_at="2026-05-25"), CONTROLE),
    ("campaign NaN = externo", dict(campaign_name=float("nan")), EXTERNO),

    # 7. utm_campaign tem prioridade sobre campaign_name (mesma tag, fontes diferentes)
    ("utm_campaign usado quando presente", dict(
        utm_campaign="DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-05-26 | LEADHQLB|1",
        campaign_name="qualquer coisa", captured_at="2026-05-26"), CHALLENGER),

    # 8. PAPEL TEM DATA — o abr28 virou champion em 25/07/2026. O mesmo lead, o mesmo
    # nome de campanha, resolve diferente antes e depois. Sem isto, promover um modelo
    # reescreve o passado de todo relatório histórico.
    ("abr28 na véspera da promoção = challenger", dict(
        variant="challenger_abr28", captured_at="2026-07-24"), CHALLENGER),
    ("abr28 no dia da promoção = champion", dict(
        variant="challenger_abr28", captured_at="2026-07-25"), CHAMPION),
    ("HQLB por NOME antes da promoção = challenger", dict(
        utm_campaign="DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-06-18 | LEADHQLB|1",
        captured_at="2026-06-18"), CHALLENGER),
    ("HQLB por NOME depois da promoção = champion", dict(
        utm_campaign="DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-06-18 | LEADHQLB|1",
        captured_at="2026-07-29"), CHAMPION),

    # 9. Challenger jul_24 — antes o variant dele nem existia no mapa e caía em
    # INDETERMINADO; a tag JUL24 caía em 'Lead'. Ambos vinham do YAML não ser lido.
    ("variant jul_24 = challenger", dict(
        variant="challenger_jul_24", captured_at="2026-07-29"), CHALLENGER),
    ("tag JUL24_TOP10 por nome = challenger", dict(
        utm_campaign="DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-06-18 | JUL24_TOP10",
        captured_at="2026-07-29"), CHALLENGER),
    ("tag JUL24_TOP50 por nome = challenger", dict(
        utm_campaign="DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-06-18 | JUL24_TOP50",
        captured_at="2026-07-29"), CHALLENGER),

    # 10. PÚBLICO não define captação. A campanha QUENTE existe desde 29/07/2026 e
    # gastou R$ 2.271 no primeiro dia; o filtro exigia literalmente 'FRIO' e ela caía
    # em EXTERNO (balde de Google/orgânico), desaparecendo do relatório.
    ("QUENTE + HQLB é captação, não externo", dict(
        utm_campaign="DEVLF | CAP | QUENTE | FASE 04 | ADV | LEAD | PG1 | 2026-06-29 | LEADHQLB",
        captured_at="2026-07-29"), CHAMPION),
    ("QUENTE + LEAD puro = controle", dict(
        utm_campaign="DEVLF | CAP | QUENTE | FASE 04 | ADV | LEAD | PG1 | 2026-06-29",
        captured_at="2026-07-29"), CONTROLE),
    ("MORNO tambem é captação", dict(
        utm_campaign="DEVLF | CAP | MORNO | FASE 04 | ADV | LEAD | PG1 | 2026-06-29 | LEADHQLB",
        captured_at="2026-07-29"), CHAMPION),

    # 11. Variações de nome que o gestor cria (sufixo/prefixo) continuam casando pela
    # SUBSTRING da tag — é a vantagem estrutural do YAML sobre a assinatura exata da
    # tabela curada, que precisava de uma linha nova pra cada variação.
    ("HQLB com sufixo TESTEPROMESSA", dict(
        utm_campaign="DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | LEADHQLB | TESTEPROMESSA",
        captured_at="2026-07-29"), CHAMPION),
    ("HQLB com sufixo DUPLICADOS", dict(
        utm_campaign="DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | LEADHQLB | DUPLICADOS",
        captured_at="2026-07-29"), CHAMPION),
]


def run():
    fails = 0
    for desc, kwargs, expected in CASES:
        got = resolve_arm(**kwargs)
        ok = got == expected
        if not ok:
            fails += 1
        print(f"{'OK ' if ok else 'FAIL'}  {desc}: esperado={expected} got={got}")
    print(f"\n{len(CASES)-fails}/{len(CASES)} passaram")
    return fails


# pytest
def test_all_cases():
    for desc, kwargs, expected in CASES:
        assert resolve_arm(**kwargs) == expected, desc


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
