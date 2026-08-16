"""O bloco "Features zeradas em batch" confirma no AGREGADO DO DIA, não na
média das linhas flagradas.

Contexto (auditoria de 16/08/2026): o agregador antigo resumia com a média
das linhas que JÁ tinham disparado o T1-16 — média condicionada ao disparo
apresentada como média do dia. Em 14/08 isso suprimiu por 0,0007 o único bug
real (Medium_Aberto, razão 0,1007) e mostrou 3 features benignas vindas do
tráfego do gate de deploy. Medido em 7 dias de logs: 61 linhas = só 29
batches reais; 55,7% vieram de revisões canário/gate com 0% de tráfego, com
o mesmo batch logado em dupla a cada deploy (~0,7s) e triplicatas no mesmo
segundo.

Estes testes reproduzem os DOIS lados do incidente com os números reais e
travam o dedup temporal, o fallback por feature e o contexto anti-cegueira
(ressalvas dos architects, 16/08).

Rodável sem pytest: python tests/test_training_drift_agregado.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

from src.monitoring.training_drift_summary import (
    CONTEXTO_MIN_EVENTOS,
    DEDUP_JANELA_S,
    ZEROED_OBS_FACTOR,
    _aggregate_t116,
    _parse_linha,
)

T0 = datetime(2026, 8, 15, 18, 18, 21, tzinfo=timezone.utc)


def _linha(feats, batch=50, run='5d158f0a'):
    """Monta uma linha T1-16 no formato REAL do encoding.py:466-472."""
    preview = ', '.join(f"{f} (obs={o:.3f} vs exp={e:.3f})" for f, o, e in feats)
    return (f"  [T1-16] (observa, NÃO bloqueia) {len(feats)} colunas OHE caíram "
            f"vs distribuição do treino (batch={batch}, mlflow_run_id={run}). "
            f"Exemplos: {preview}. Conformidade com o treino ≠ bug.")


def _entrada(feats, ts, revisao='rev-a', batch=50, run='5d158f0a'):
    return {'texto': _linha(feats, batch=batch, run=run), 'revisao': revisao, 'ts': ts}


# ─────────────────────────── parse ───────────────────────────

def test_parse_linha_extrai_run_id_batch_e_features():
    p = _parse_linha(_linha([('Medium_Aberto', 0.0, 0.499)], batch=120))
    assert p['run_id8'] == '5d158f0a'
    assert p['batch'] == 120
    assert p['features'] == [('Medium_Aberto', 0.0, 0.499)]


# ─────────────────────────── dedup temporal ───────────────────────────

def test_par_do_gate_colapsa_em_um_evento():
    """O padrão medido: revisão servindo + candidata logam o MESMO batch com
    ~0,7s de diferença (20 pares em 7 dias). Cruzando fronteira de segundo."""
    feats = [('Qual_a_sua_idade_25_34_anos', 0.080, 0.319)]
    entradas = [
        _entrada(feats, T0, revisao='api-01064-dek'),
        _entrada(feats, T0 + timedelta(seconds=0.7), revisao='api-01073-dah'),
    ]
    out = _aggregate_t116(entradas)
    assert out['linhas_brutas'] == 2
    assert out['eventos_dedup'] == 1
    assert sorted(out['revisoes']) == ['api-01064-dek', 'api-01073-dah']


def test_triplicata_no_mesmo_segundo_colapsa():
    """Padrão medido: mesma revisão, mesmo batch, 3 linhas no mesmo segundo."""
    feats = [('nome_tem_sobrenome_False', 0.046, 0.172)]
    entradas = [_entrada(feats, T0 + timedelta(milliseconds=m), revisao='api-01069-sag')
                for m in (0, 230, 278)]
    out = _aggregate_t116(entradas)
    assert out['eventos_dedup'] == 1


def test_batches_reais_com_minutos_de_distancia_nao_colapsam():
    """Dia de bug real: obs imprime 0.000 em todo batch (conteúdo idêntico),
    mas batches distintos distam minutos. O dedup NÃO pode subcontá-los —
    ressalva 1 dos dois architects."""
    feats = [('Medium_Aberto', 0.0, 0.499)]
    entradas = [_entrada(feats, T0 + timedelta(minutes=3 * i)) for i in range(4)]
    out = _aggregate_t116(entradas)
    assert out['eventos_dedup'] == 4, \
        "batches reais separados por minutos devem contar separados"


def test_janela_deslizante_encadeia_dentro_do_limite():
    """3 linhas a 3s uma da outra: cada uma está a <=5s da ANTERIOR (encadeia),
    então colapsam em 1 evento mesmo a 1ª e a 3ª distando 6s."""
    feats = [('Medium_Aberto', 0.0, 0.499)]
    entradas = [_entrada(feats, T0 + timedelta(seconds=3 * i)) for i in range(3)]
    out = _aggregate_t116(entradas)
    assert out['eventos_dedup'] == 1
    assert DEDUP_JANELA_S == 5.0


# ─────────────── confirmação no agregado do dia (o incidente) ───────────────

def test_incidente_1408_medium_aberto_teria_sido_MOSTRADO():
    """O lado que o filtro antigo ERROU: Medium_Aberto com média das flagradas
    = 0,0502 (razão 0,1007 > 0,10 → suprimido por 0,0007). Com o agregado do
    dia (~0 nos dias do bug), é CONFIRMADO e aparece."""
    entradas = [
        _entrada([('Medium_Aberto', 0.000, 0.499)], T0, batch=50),
        _entrada([('Medium_Aberto', 0.067, 0.499)], T0 + timedelta(minutes=10), batch=120),
        _entrada([('Medium_Aberto', 0.083, 0.499)], T0 + timedelta(minutes=20), batch=120),
    ]
    taxas = {'5d158f0a': {'Medium_Aberto': 0.001}}  # agregado real do dia do bug
    out = _aggregate_t116(entradas, taxas)
    assert out['confirmacao'] == 'agregado_do_dia'
    feats = [f['feature'] for f in out['top_features']]
    assert feats == ['Medium_Aberto']
    assert out['top_features'][0]['taxa_dia'] == 0.001
    assert out['batches_com_drift'] == 3


def test_incidente_1408_benignas_do_gate_teriam_sido_SUPRIMIDAS():
    """O outro lado: Source_facebook_ads flagrada só pelo tráfego do gate
    (obs média 0,083, razão 0,0906 → o filtro antigo MOSTRAVA). O agregado
    real do dia era ~87% → suprimida como saudável."""
    entradas = [
        _entrada([('Source_facebook_ads', 0.083, 0.916)], T0, batch=120),
        _entrada([('Source_facebook_ads', 0.083, 0.916)], T0 + timedelta(minutes=1), batch=120),
    ]
    taxas = {'5d158f0a': {'Source_facebook_ads': 0.87}}
    out = _aggregate_t116(entradas, taxas)
    assert out['top_features'] == []
    assert out['batches_com_drift'] == 0
    assert len(out['suprimidas_saudaveis']) == 1
    s = out['suprimidas_saudaveis'][0]
    assert s['feature'] == 'Source_facebook_ads'
    assert s['taxa_dia'] == 0.87
    assert s['eventos'] == 2


def test_controle_sem_taxas_vale_a_heuristica_antiga():
    """Controle: MESMOS dados do teste do Medium_Aberto, sem taxas → fallback
    reproduz a decisão antiga (razão 0,1007 > 0,10 → suprimido). Garante que
    a diferença vem do agregado, não de outra mudança."""
    entradas = [
        _entrada([('Medium_Aberto', 0.000, 0.499)], T0, batch=50),
        _entrada([('Medium_Aberto', 0.067, 0.499)], T0 + timedelta(minutes=10), batch=120),
        _entrada([('Medium_Aberto', 0.083, 0.499)], T0 + timedelta(minutes=20), batch=120),
    ]
    out = _aggregate_t116(entradas, None)
    assert out['confirmacao'] == 'heuristica_fallback'
    assert out['top_features'] == []  # a heurística antiga errava assim mesmo
    assert out['suppressed_features'] == 1


def test_fallback_por_feature_nao_tudo_ou_nada():
    """Ressalva dos architects: run_id fora do dict de taxas cai no fallback
    SÓ para aquelas features; as com taxa seguem confirmadas pelo agregado."""
    entradas = [
        _entrada([('Medium_Aberto', 0.0, 0.499)], T0, run='5d158f0a'),
        _entrada([('Feature_X', 0.0, 0.400)], T0 + timedelta(minutes=1), run='deadbeef'),
    ]
    taxas = {'5d158f0a': {'Medium_Aberto': 0.0}}  # deadbeef ausente
    out = _aggregate_t116(entradas, taxas)
    por_nome = {f['feature']: f for f in out['top_features']}
    assert por_nome['Medium_Aberto']['taxa_dia'] == 0.0      # confirmada
    assert por_nome['Feature_X']['taxa_dia'] is None          # fallback marcado


def test_contexto_para_colapso_parcial_persistente():
    """O único cenário em que o desenho novo enxergaria MENOS que o velho
    (mlops-architect, cenário e): taxa do dia entre 10% e 30% do treino grita
    em batch o dia inteiro mas nunca cruza o corte. Com >= CONTEXTO_MIN_EVENTOS
    eventos dedup, entra em suprimidas_saudaveis para a linha de contexto."""
    feats = [('Term_instagram', 0.100, 0.727)]
    entradas = [_entrada(feats, T0 + timedelta(minutes=2 * i))
                for i in range(CONTEXTO_MIN_EVENTOS + 1)]
    taxas = {'5d158f0a': {'Term_instagram': 0.15}}  # 20% do exp: acima do corte
    out = _aggregate_t116(entradas, taxas)
    assert out['top_features'] == []
    assert out['suprimidas_saudaveis'][0]['eventos'] >= CONTEXTO_MIN_EVENTOS


# ─────────────────────────── contrato do payload ───────────────────────────

def test_contrato_estavel_todas_as_chaves_sempre_presentes():
    """O payload_schema do daily-check falha ALTO em chave produzida sem
    declarar — e chave condicional quebra só no dia em que aparece. Contrato:
    TODAS as chaves presentes em TODOS os caminhos (vazio, só ruído, confirmado)."""
    chaves = {'window_hours', 'batches_com_drift', 'total_observacoes',
              'top_features', 'suppressed_features', 'observacao',
              'confirmacao', 'linhas_brutas', 'eventos_dedup', 'revisoes',
              'suprimidas_saudaveis'}
    vazio = _aggregate_t116([])
    ruido = _aggregate_t116([_entrada([('F', 0.3, 0.5)], T0)])
    cheio = _aggregate_t116([_entrada([('F', 0.0, 0.5)], T0)],
                            {'5d158f0a': {'F': 0.0}})
    for caso in (vazio, ruido, cheio):
        assert chaves <= set(caso), f"faltam: {chaves - set(caso)}"
    for item in cheio['top_features']:
        assert 'taxa_dia' in item


def test_zeroed_factor_inalterado():
    """O corte continua 0,10 — a mudança é SOBRE O QUE ele é aplicado
    (taxa real do dia), não o quão rígido ele é."""
    assert ZEROED_OBS_FACTOR == 0.10


# ──────────────────── compute_ohe_daily_rates (fonte das taxas) ────────────────────

class _PredictorFake:
    def __init__(self, run_id, feature_names):
        self.mlflow_run_id = run_id
        self.model_path = None
        self.feature_names = feature_names

    def load_model(self):
        pass


def _monitor_com_variantes(variantes):
    """Seam de teste nomeado pelo sw-architect: injeta o cache de variantes
    com fakes, sem desserializar modelo real (padrão fake-sem-mock da casa)."""
    from src.monitoring.data_quality import DataQualityMonitor
    m = DataQualityMonitor.__new__(DataQualityMonitor)
    m._active_variants_cache = variantes
    return m


def test_ohe_daily_rates_dropa_decil_e_filtra_binarias(monkeypatch):
    from src.monitoring import data_quality as dq

    capturado = {}

    def _fake_apply_encoding(df, config, artifacts=None):
        capturado['colunas_entrada'] = list(df.columns)
        return pd.DataFrame({
            'Medium_Aberto': [1.0, 0.0, 0.0, 0.0],   # binária → taxa 0.25
            'nome_comprimento': [12, 30, 7, 22],      # numérica → excluída
        })

    import core.encoding as core_enc
    monkeypatch.setattr(core_enc, 'apply_encoding', _fake_apply_encoding)

    m = _monitor_com_variantes([
        ('champion', _PredictorFake('5d158f0aabcdef00',
                                    ['Medium_Aberto', 'nome_comprimento']),
         object()),
    ])
    df = pd.DataFrame({'Medium': ['Aberto'] * 4, 'decil': [1, 2, 3, 4],
                       'lead_score': [0.1, 0.2, 0.3, 0.4]})
    out = m.compute_ohe_daily_rates(df)

    assert 'decil' not in capturado['colunas_entrada'], \
        "decil precisa ser dropado ANTES do encoding (viraria coluna OHE)"
    assert 'lead_score' not in capturado['colunas_entrada']
    assert out == {'5d158f0a': {'Medium_Aberto': 0.25}}


def test_ohe_daily_rates_pula_variante_sem_run_id_e_nunca_levanta():
    m = _monitor_com_variantes([
        ('legacy', _PredictorFake(None, ['F']), None),
    ])
    df = pd.DataFrame({'Medium': ['Aberto']})
    assert m.compute_ohe_daily_rates(df) == {}
    assert m.compute_ohe_daily_rates(pd.DataFrame()) == {}
    assert m.compute_ohe_daily_rates(None) == {}


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
