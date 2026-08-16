"""'Lead padrão' = captação FRIA da META. Google e orgânico nunca entram nele.

Contexto (varredura de 16/08/2026, pedido do Ramon): dois vazamentos reais e
três portas destravadas colocavam leads de google/orgânico no balde de lead
padrão:

1. TREINO: o grupo de CONTROLE do reweighting (o contrafactual que recebe
   control_boost) recebia ~102 mil leads não-Meta — a campanha genérica
   'devlf'/vazia deles tem a mesma assinatura de uma campanha Meta sem tag,
   e a curadoria traduz como 'Lead' → CONTROLE. O modelo aprendia medindo
   contra uma régua torta.
2. REFERÊNCIA ROLANTE: a taxa de conversão do balde 'Lead' era computada
   sobre TODOS os canais (~47% não-Meta na janela de 90d) e alimentava o
   teto de CPL da linha Lead no relatório diário.
3. Portas destravadas: tradução de rótulo desconhecido → 'Lead'; gasto de
   3ª plataforma → 'Lead'; e a portaria por etiqueta com default 'Lead'
   (sem chamadores de produção, docstring corrigida).

Rodável sem pytest: python tests/test_lead_padrao_so_meta.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest


# ─────────────── 1. treino: grupo de controle é só Meta ───────────────

def _pesos(df, **kw):
    from src.train_pipeline import _compute_control_weights
    return _compute_control_weights(df, alpha=1.0,
                                    campaign_col='__campaign_for_weights__', **kw)


def _curadoria(*nomes_categorias):
    """label_map como a curadoria real: assinatura do nome → categoria.
    É o mecanismo exato do vazamento: 'devlf' (google) e campanha Meta sem tag
    têm a MESMA assinatura '(sem tag)', que a tabela traduz como 'Lead'."""
    from src.validation.campaign_classifier import tag_signature
    return {tag_signature(nome): cat for nome, cat in nomes_categorias}


def test_google_e_organico_viram_neutro_no_peso_de_controle():
    """O caso medido: lead google com campanha 'devlf' (assinatura '(sem tag)',
    igual à de Meta-sem-tag) tem que sair do CONTROLE. Peso NEUTRO = 1.0."""
    lm = _curadoria(('devlf', 'Lead'),
                    ('DEVLF | CAP | FRIO | LEADHQLB', 'Champion'))
    df = pd.DataFrame({
        '__campaign_for_weights__': ['devlf', 'devlf', 'devlf',
                                     'DEVLF | CAP | FRIO | LEADHQLB'],
        '__utm_source__': ['google-ads', 'manychat', 'facebook-ads', 'facebook-ads'],
    })
    pesos = _pesos(df, label_map=lm)
    # google e manychat: NEUTRO → peso 1.0 sempre
    assert pesos.iloc[0] == 1.0 and pesos.iloc[1] == 1.0
    # o Meta sem tag (CONTROLE) e o Meta com etiqueta (ML) seguem balanceando
    assert pesos.iloc[2] == pytest.approx(pesos.iloc[3])


def test_controle_sem_guarda_o_google_entrava():
    """Controle do teste acima: MESMO dado sem a coluna de fonte reproduz o
    comportamento antigo (google '(sem tag)' → 'Lead' → CONTROLE, peso de
    balanceamento). Prova que a diferença vem da guarda de canal."""
    lm = _curadoria(('devlf', 'Lead'),
                    ('DEVLF | CAP | FRIO | LEADHQLB', 'Champion'))
    df = pd.DataFrame({
        '__campaign_for_weights__': ['devlf',
                                     'DEVLF | CAP | FRIO | LEADHQLB',
                                     'DEVLF | CAP | FRIO | LEADHQLB'],
    })
    pesos = _pesos(df, label_map=lm)
    # 1 CONTROLE (o google mascarado) vs 2 ML: balanceamento assimétrico
    assert pesos.iloc[0] != 1.0, \
        "sem a guarda, o google entra no CONTROLE — é o bug histórico"


def test_meta_sem_tag_continua_no_controle():
    """Não-enfraquecimento: captação Meta sem etiqueta É o controle legítimo."""
    lm = _curadoria(('devlf', 'Lead'),
                    ('DEVLF | CAP | FRIO | LEADHQLB', 'Champion'))
    df = pd.DataFrame({
        '__campaign_for_weights__': ['devlf',
                                     'DEVLF | CAP | FRIO | LEADHQLB',
                                     'DEVLF | CAP | FRIO | LEADHQLB'],
        '__utm_source__': ['facebook-ads', 'facebook-ads', 'facebook-ads'],
    })
    pesos = _pesos(df, label_map=lm)
    # 1 CONTROLE (Meta sem tag) vs 2 ML: controle pesa mais
    assert pesos.iloc[0] > pesos.iloc[1]


# ─────────── 2. referência rolante: balde só com leads Meta ───────────

def test_taxa_do_balde_lead_ignora_google_e_organico():
    """O caso medido: ~47% do balde 'Lead' era google/orgânico. A taxa do
    balde tem que sair SÓ dos leads Meta; google segue visível em by_channel."""
    from src.monitoring.rolling_reference import conversion_reference
    df = pd.DataFrame({
        'converted': [True, False, False, False, True, True],
        'decil_challenger': [10, 5, 5, 5, 10, 10],
        'utm_source': ['facebook-ads', 'facebook-ads',
                       'google-ads', 'google-ads', 'google-ads', 'manychat'],
        'utm_campaign': ['DEVLF | CAP | FRIO | X'] * 2 + ['devlf'] * 3 + [None],
    })
    ref = conversion_reference(df, bucket_map=None,
                               min_segment_conv=0, min_segment_leads=0)
    lead = ref['by_bucket'].get('Lead')
    assert lead is not None
    assert lead['leads'] == 2, \
        f"o balde Lead deveria ter SÓ os 2 leads Meta, veio {lead['leads']}"
    assert lead['rate'] == pytest.approx(0.5)  # 1 conv / 2 meta
    # google continua medido no lugar certo: por canal
    assert ref['by_channel']['google']['leads'] == 3
    # overall segue all-source (não mudou de propósito)
    assert ref['overall']['leads'] == 6


# ─────────────────── 3. portas destravadas ───────────────────

def test_traducao_de_rotulo_nao_joga_externo_no_lead():
    from src.core.ab_arm import arm_to_bucket, EXTERNO
    assert arm_to_bucket(EXTERNO) is None
    assert arm_to_bucket('QualquerCoisaNova') is None


def test_traducao_dos_rotulos_conhecidos_inalterada():
    from src.core.ab_arm import (arm_to_bucket, CHAMPION, CHALLENGER,
                                 CONTROLE, INDETERMINADO)
    assert arm_to_bucket(CHAMPION) == 'Champion'
    assert arm_to_bucket(CHALLENGER) == 'Challenger'
    assert arm_to_bucket(CONTROLE) == 'Lead'
    assert arm_to_bucket(INDETERMINADO) is None


def test_gasto_de_plataforma_desconhecida_nao_vira_lead():
    from src.validation.model_performance import _spend_by_bucket

    class _Reg:
        bucket_map = {'tags': (), 'display': {}, 'fallback': 'Lead'}
    spend = pd.DataFrame({
        'platform': ['meta', 'google', 'tiktok'],
        'campaign_name': ['DEVLF | CAP | FRIO', 'cap-go-x', 'tk-campanha'],
        'spend': [100.0, 50.0, 30.0],
    })
    out = _spend_by_bucket(spend, _Reg(), meta_gross_up=1.0)
    assert out.get('Google') == pytest.approx(50.0)
    assert 'Tiktok' in out, "3ª plataforma ganha balde próprio, visível"
    assert out.get('Lead', 0) + out.get('Tiktok', 0) == pytest.approx(130.0)
    assert out.get('Lead', 0) == pytest.approx(100.0), \
        "o gasto tiktok NÃO pode entrar no Lead padrão Meta"


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
