"""Guarda de recência do relatório de criativo: não desliga (🔴) criativo só
marginalmente abaixo do alvo E melhorando. Roda direto: PYTHONPATH=. python3 tests/test_creative_recency_guard.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.monitoring.utm_quality import _mark_with_recency_guard, RECENCY_GUARD_PP

BAR = 28.4  # alvo TOP5


def _row(pct, status):
    return {'pct_d9_d10': pct, 'status': status}


def run():
    casos = [
        # (nome, ref_lançamento, win_ontem, esperado)
        ("AD07: 1.4pp abaixo + melhorou (27→33) → poupa",
         _row(27.0, 'abaixo'), _row(33.0, 'neutro'), '⚪'),
        ("2pp exatos abaixo + melhorou → poupa (limite inclusivo)",
         _row(26.4, 'abaixo'), _row(30.0, 'neutro'), '⚪'),
        ("Muito abaixo (20%, 8.4pp) mesmo melhorando → 🔴 (gap grande)",
         _row(20.0, 'abaixo'), _row(21.0, 'neutro'), '🔴'),
        ("Marginal mas PIOROU ontem (27→25) → 🔴 (não melhorou)",
         _row(27.0, 'abaixo'), _row(25.0, 'abaixo'), '🔴'),
        ("Marginal, abaixo, sem dado de ontem → 🔴 (não confirma melhora)",
         _row(27.0, 'abaixo'), None, '🔴'),
        ("Acima do alvo → 🟢 (inalterado)",
         _row(35.0, 'acima'), _row(30.0, 'neutro'), '🟢'),
        ("Neutro → ⚪ (inalterado)",
         _row(28.0, 'neutro'), _row(29.0, 'neutro'), '⚪'),
        ("2.1pp abaixo + melhorou → 🔴 (fora do limite de 2pp)",
         _row(26.3, 'abaixo'), _row(30.0, 'neutro'), '🔴'),
    ]
    ok = 0
    for nome, ref, win, esperado in casos:
        got = _mark_with_recency_guard(ref, win, BAR)
        status = "✓" if got == esperado else "✗"
        if got == esperado:
            ok += 1
        else:
            print(f"  {status} FALHOU: {nome} — esperado {esperado}, veio {got}")
        if got == esperado:
            print(f"  {status} {nome}")
    assert RECENCY_GUARD_PP == 2.0, "limite mudou"
    print(f"\nResultado: {ok}/{len(casos)} passaram")
    return ok == len(casos)


if __name__ == '__main__':
    sys.exit(0 if run() else 1)
