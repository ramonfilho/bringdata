"""Testes do `compute_pubsub_summary` — Etapa 7 do refator do monitoramento.

Rodável sem pytest:  python tests/test_pubsub_summary.py
"""
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data import LeadRecord
from src.monitoring.pubsub_summary import compute_pubsub_summary


@dataclass
class FakeRepo:
    leads: list = field(default_factory=list)
    def recent_leads(self, window_minutes, limit=10_000):
        return self.leads
    def leads_in_range(self, start, end, limit=10_000):
        return self.leads


def _lead(status='success', decil=None, erro=None, idx=0):
    return LeadRecord(
        event_id=f'e{idx}',
        email=f'l{idx}@x',
        criado_em=datetime.now(timezone.utc),
        status_envio=status, decil=decil, erro=erro,
    )


def test_repo_none_devolve_skeleton_zerado():
    s = compute_pubsub_summary(None)
    assert s['total'] == 0
    assert s['by_status'] == {'success': 0, 'error': 0,
                              'skipped_allowlist': 0, 'skipped_missing_data': 0}
    assert s['top_errors'] == []
    # Decis canônicos: 10 chaves zeradas
    assert len(s['decil_distribution']) == 10
    assert all(v == 0 for v in s['decil_distribution'].values())


def test_repo_vazio_devolve_skeleton_zerado():
    s = compute_pubsub_summary(FakeRepo([]))
    assert s['total'] == 0
    assert all(v == 0 for v in s['by_status'].values())


def test_quebra_por_status_cobre_4_categorias():
    leads = (
        [_lead('success', decil=8, idx=i) for i in range(10)]
        + [_lead('error', erro='timeout', idx=i+100) for i in range(3)]
        + [_lead('skipped_allowlist', idx=i+200) for i in range(20)]
        + [_lead('skipped_missing_data', idx=i+300) for i in range(5)]
    )
    s = compute_pubsub_summary(FakeRepo(leads))
    assert s['total'] == 38
    assert s['by_status']['success'] == 10
    assert s['by_status']['error'] == 3
    assert s['by_status']['skipped_allowlist'] == 20
    assert s['by_status']['skipped_missing_data'] == 5


def test_decil_distribution_so_conta_sucessos():
    # 5 success em D10, 5 success em D08, 3 error em D10 — error não conta
    leads = (
        [_lead('success', decil=10, idx=i) for i in range(5)]
        + [_lead('success', decil=8, idx=i+50) for i in range(5)]
        + [_lead('error', decil=10, erro='x', idx=i+100) for i in range(3)]
    )
    s = compute_pubsub_summary(FakeRepo(leads))
    assert s['decil_distribution']['D10'] == 5
    assert s['decil_distribution']['D08'] == 5
    # decis que não tiveram sucesso ficam zerados
    assert s['decil_distribution']['D01'] == 0
    assert s['decil_distribution']['D05'] == 0


def test_top_errors_ordena_por_contagem_desc():
    leads = (
        [_lead('error', erro='timeout', idx=i) for i in range(10)]
        + [_lead('error', erro='invalid fbp', idx=i+100) for i in range(3)]
        + [_lead('error', erro='slug desconhecido', idx=i+200) for i in range(7)]
        + [_lead('success', decil=5, idx=i+300) for i in range(20)]  # ignorados
    )
    s = compute_pubsub_summary(FakeRepo(leads))
    assert len(s['top_errors']) == 3
    assert s['top_errors'][0] == {'message': 'timeout', 'count': 10}
    assert s['top_errors'][1] == {'message': 'slug desconhecido', 'count': 7}
    assert s['top_errors'][2] == {'message': 'invalid fbp', 'count': 3}


def test_top_errors_limita_a_5_msgs():
    # 7 mensagens distintas; só as top 5 entram
    leads = []
    for i, msg in enumerate(['a', 'b', 'c', 'd', 'e', 'f', 'g']):
        leads.extend([_lead('error', erro=msg, idx=i*10+j) for j in range(7 - i)])
    s = compute_pubsub_summary(FakeRepo(leads))
    assert len(s['top_errors']) == 5
    assert [t['message'] for t in s['top_errors']] == ['a', 'b', 'c', 'd', 'e']


def test_erro_vazio_ou_none_nao_entra_no_top():
    leads = [
        _lead('error', erro=None, idx=1),
        _lead('error', erro='', idx=2),
        _lead('error', erro='   ', idx=3),  # só whitespace
        _lead('error', erro='real failure', idx=4),
    ]
    s = compute_pubsub_summary(FakeRepo(leads))
    # erro=None e erro='' filtrados pela list comp; whitespace é considerado erro vazio também
    msgs = [t['message'] for t in s['top_errors']]
    assert 'real failure' in msgs
    assert '' not in msgs


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
