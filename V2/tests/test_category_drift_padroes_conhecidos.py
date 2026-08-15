"""Vocabulário que o pipeline já traduz não pode virar alarme permanente.

Contexto (14/08/2026, PR #190): o detector de categoria nova passou a ler o
valor CRU do Medium para que a unificação não escondesse uma troca de
nomenclatura do cliente. Isso devolveu a detecção, mas criou o defeito oposto:
com o passo 3b traduzindo `[ADVTG_ABERTO]...` → `Aberto` normalmente em
produção, o relatório das 06:00 seguiu listando as 16 variantes e 86,2% dos
leads TODO DIA, e a lista crescia a cada anúncio novo que o time criava.

O detector sabia o que o modelo espera (`categorias_esperadas`) mas não sabia
o que o pipeline já traduz (`pattern_mappings`). Estes testes travam as duas
pontas: o conhecido cala, o desconhecido continua gritando.
"""
import pandas as pd
import pytest

from src.monitoring.data_quality import check_category_drift


CATEGORIAS_TREINO = {
    'Medium': ['Aberto', 'Outros', 'Linguagem_programacao', 'dgen'],
}

# O padrão real que vive em configs/clients/devclub.yaml.
PADROES_DEVCLUB = {'Medium': [r'^\[ADVTG_ABERTO\]']}


def _df(valores):
    return pd.DataFrame({'Medium': valores})


def test_variantes_do_padrao_conhecido_nao_alertam():
    """O caso que motivou o fix: 16 variantes, 86,2% dos leads, todo dia."""
    crus = [
        '[ADVTG_ABERTO]',
        '[ADVTG_ABERTO]DEV-AD0160 - VID - CAPTAÇÃO',
        '[ADVTG_ABERTO]DEV-AD0424-vid-captação-casa de Rodolfo',
        '[ADVTG_ABERTO]DEV-0002-V1_LFP',
    ]
    df = _df(crus)
    alertas = check_category_drift(
        df, CATEGORIAS_TREINO,
        valores_crus={'Medium': df['Medium'].copy()},
        padroes_conhecidos=PADROES_DEVCLUB,
    )
    assert alertas == [], f"padrão conhecido não pode alertar: {alertas}"


def test_sem_os_padroes_o_alerta_volta():
    """Controle: é o MESMO dado. A única diferença é o conhecimento do padrão.

    Sem este teste, o primeiro poderia passar por acidente (ex.: alguém
    silenciar a coluna inteira) e ninguém notaria.
    """
    crus = ['[ADVTG_ABERTO]DEV-AD0160 - VID - CAPTAÇÃO']
    df = _df(crus)
    alertas = check_category_drift(
        df, CATEGORIAS_TREINO,
        valores_crus={'Medium': df['Medium'].copy()},
        padroes_conhecidos=None,
    )
    assert len(alertas) == 1
    assert alertas[0]['type'] == 'new_categories'


def test_prefixo_novo_continua_alertando():
    """A detecção não pode ser enfraquecida: `[ADVTG_QUENTE]` é vocabulário novo."""
    crus = [
        '[ADVTG_ABERTO]DEV-AD0160 - VID - CAPTAÇÃO',
        '[ADVTG_QUENTE]DEV-AD9999 - VID - NOVO',
    ]
    df = _df(crus)
    alertas = check_category_drift(
        df, CATEGORIAS_TREINO,
        valores_crus={'Medium': df['Medium'].copy()},
        padroes_conhecidos=PADROES_DEVCLUB,
    )
    assert len(alertas) == 1
    assert alertas[0]['new_categories'] == ['[ADVTG_QUENTE]DEV-AD9999 - VID - NOVO']


def test_valores_realmente_sem_mapeamento_sobrevivem():
    """Os 2 sobreviventes reais do relatório de 15/08 — e devem sobreviver.

    `{{adset.name}}` é macro da Meta que não renderizou (bug do lado do
    cliente); `ENVOLVIMENTO 365D IG` é público de retargeting sem mapeamento.
    Nenhum dos dois casa com o padrão, então continuam visíveis.
    """
    crus = [
        '[ADVTG_ABERTO]DEV-AD0160 - VID - CAPTAÇÃO',
        'ENVOLVIMENTO 365D IG',
        '{{adset.name}}',
    ]
    df = _df(crus)
    alertas = check_category_drift(
        df, CATEGORIAS_TREINO,
        valores_crus={'Medium': df['Medium'].copy()},
        padroes_conhecidos=PADROES_DEVCLUB,
    )
    assert len(alertas) == 1
    assert sorted(alertas[0]['new_categories']) == ['ENVOLVIMENTO 365D IG', '{{adset.name}}']


def test_contagem_de_leads_exclui_os_tratados():
    """O % do alerta tem que refletir só o que sobrou, senão a severidade mente.

    8 leads no total, 6 tratados pelo padrão e 2 realmente novos → 25%, não 100%.
    """
    crus = ['[ADVTG_ABERTO]A'] * 6 + ['{{adset.name}}'] * 2
    df = _df(crus)
    alertas = check_category_drift(
        df, CATEGORIAS_TREINO,
        valores_crus={'Medium': df['Medium'].copy()},
        padroes_conhecidos=PADROES_DEVCLUB,
    )
    assert len(alertas) == 1
    assert alertas[0]['count'] == 2
    assert alertas[0]['percentage'] == pytest.approx(25.0)
    assert alertas[0]['severity'] == 'HIGH'  # >20%


def test_regex_invalido_nao_derruba_o_relatorio():
    """Fail-soft: yaml quebrado degrada para o comportamento antigo, não para 500.

    O relatório das 06:00 não pode morrer por causa de um padrão mal escrito.
    """
    crus = ['[ADVTG_ABERTO]DEV-AD0160']
    df = _df(crus)
    alertas = check_category_drift(
        df, CATEGORIAS_TREINO,
        valores_crus={'Medium': df['Medium'].copy()},
        padroes_conhecidos={'Medium': ['[unclosed', r'^\[ADVTG_ABERTO\]']},
    )
    # O padrão válido segue valendo mesmo com o inválido na lista.
    assert alertas == []


def test_padrao_nao_ancorado_nao_vaza_para_outra_coluna():
    """Padrão de Medium não pode filtrar valor de outra coluna."""
    df = pd.DataFrame({
        'Medium': ['[ADVTG_ABERTO]X'],
        'Source': ['[ADVTG_ABERTO]X'],
    })
    alertas = check_category_drift(
        df,
        {'Medium': ['Aberto'], 'Source': ['facebook-ads']},
        valores_crus={'Medium': df['Medium'].copy()},
        padroes_conhecidos=PADROES_DEVCLUB,
    )
    colunas = {a['column'] for a in alertas}
    assert colunas == {'Source'}, f"só Source deveria alertar, veio {colunas}"
