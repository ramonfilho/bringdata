"""Testes do utm_quality.py migrado para o LeadRepository.

Rodável sem pytest:  python tests/test_utm_quality_via_repo.py

Cobre as funções puras (_classify_variant_from_record, _aggregate) com
LeadRecords pré-fabricados. compute_utm_quality não é testado aqui — depende
de ABTestConfig real e LF window, validado por smoke contra Railway no commit.
"""
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data import LeadRecord
from src.monitoring.utm_quality import _aggregate, _classify_variant_from_record


def _lead(score=0.5, decil=5, variant=None, src='facebook-ads', med='Aberto',
          cnt='ad-1', idx=0):
    return LeadRecord(
        event_id=f'e{idx}',
        email=f'l{idx}@x',
        criado_em=datetime.now(timezone.utc),
        status_envio='success',
        score=score, decil=decil, variant=variant,
        utm_source=src, utm_medium=med, utm_content=cnt,
    )


def _fake_ab_cfg(champion_name='champion', challenger_name='challenger'):
    """Stub do ABTestConfig — match_variant sempre retorna None (cai no
    fallback). Suficiente pra testar a lógica de classificação."""
    return SimpleNamespace(
        variants={champion_name: object(), challenger_name: object()},
        match_variant=lambda utms, event_source_url='': None,
    )


# ──────────────────────────────────────────────────────────────────────────
# _classify_variant_from_record
# ──────────────────────────────────────────────────────────────────────────

def test_classify_usa_variant_direto_quando_existe():
    r = _lead(variant='champion')
    ab = _fake_ab_cfg('champion', 'challenger')
    assert _classify_variant_from_record(r, ab, 'champion', 'challenger') == 'champion'


def test_classify_usa_variant_challenger_direto():
    r = _lead(variant='challenger')
    ab = _fake_ab_cfg('champion', 'challenger')
    assert _classify_variant_from_record(r, ab, 'champion', 'challenger') == 'challenger'


def test_classify_cai_em_fallback_quando_variant_none():
    # variant=None → cai em ab.match_variant → fake retorna None → champion
    r = _lead(variant=None)
    ab = _fake_ab_cfg('champion', 'challenger')
    assert _classify_variant_from_record(r, ab, 'champion', 'challenger') == 'champion'


# ──────────────────────────────────────────────────────────────────────────
# _aggregate
# ──────────────────────────────────────────────────────────────────────────

def test_aggregate_conta_por_utm_e_variante():
    leads = [
        _lead(decil=10, variant='champion',   src='facebook-ads', idx=1),
        _lead(decil=8,  variant='champion',   src='facebook-ads', idx=2),
        _lead(decil=3,  variant='challenger', src='facebook-ads', idx=3),
        _lead(decil=5,  variant='champion',   src='instagram',    idx=4),
    ]
    ab = _fake_ab_cfg('champion', 'challenger')
    out = _aggregate(leads, 'source', ab, 'champion', 'challenger')

    assert out['facebook-ads']['champion']['n'] == 2
    assert out['facebook-ads']['champion']['avg_decil'] == 9.0
    assert out['facebook-ads']['champion']['pct_d8_d10'] == 100.0
    assert out['facebook-ads']['challenger']['n'] == 1
    assert out['facebook-ads']['challenger']['avg_decil'] == 3.0
    assert out['instagram']['champion']['n'] == 1


def test_aggregate_ignora_records_sem_score_ou_decil():
    leads = [
        _lead(decil=10, score=0.9, variant='champion', idx=1),
        LeadRecord(event_id='e2', email='x', criado_em=datetime.now(timezone.utc),
                   status_envio='skipped_allowlist', utm_source='facebook-ads',
                   score=None, decil=None, variant=None),  # sem score/decil
    ]
    ab = _fake_ab_cfg('champion', 'challenger')
    out = _aggregate(leads, 'source', ab, 'champion', 'challenger')
    assert out['facebook-ads']['champion']['n'] == 1


def test_aggregate_normaliza_utm_vazio_pra_sem_utm():
    leads = [
        _lead(decil=5, variant='champion', src=None, idx=1),
        _lead(decil=5, variant='champion', src='', idx=2),
        _lead(decil=5, variant='champion', src='   ', idx=3),
    ]
    ab = _fake_ab_cfg('champion', 'challenger')
    out = _aggregate(leads, 'source', ab, 'champion', 'challenger')
    assert 'sem_utm' in out
    assert out['sem_utm']['champion']['n'] == 3


if __name__ == '__main__':
    tests = [v for k, v in list(globals().items()) if k.startswith('test_') and callable(v)]
    print(f"Rodando {len(tests)} testes...")
    falhas = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            falhas += 1
            print(f"  ✗ {t.__name__}: {e}")
        except Exception as e:
            falhas += 1
            print(f"  ✗ {t.__name__}: {type(e).__name__}: {e}")
    print(f"\nResultado: {len(tests) - falhas}/{len(tests)} passaram")
    sys.exit(0 if falhas == 0 else 1)
