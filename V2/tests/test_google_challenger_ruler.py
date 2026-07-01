"""Ponto 1: o bucket Google no painel de decis é avaliado na régua ÚNICA do
Challenger (decil_challenger, scores_historicos) — NUNCA no jan_30 (Champion).

Guarda contra regressão: (a) quando `by_source_challenger.google` vem preenchido,
a linha Google usa a distribuição Challenger e compara com a ref Challenger
(abr_28), não com a ref Champion (jan_30); (b) degrada limpo (sem jan_30) quando
a régua Challenger não veio.

Rodável sem pytest:  python tests/test_google_challenger_ruler.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.monitoring.digest import _slack_decis_window


def _dist(**kw):
    d = {f"D{i:02d}": 0 for i in range(1, 11)}
    d.update(kw)
    return d


def _base_view(ggl_source_dist, ggl_source_total, by_source_challenger):
    """Monta um `v` mínimo com uma janela de decis que tem Google."""
    # baseline champion (jan_30) alto em D9-D10; challenger (abr_28) mais baixo —
    # se o Google fosse comparado ao jan_30, o Δ seria muito diferente.
    return {
        "lead_quality": {
            "decil_distribution_previous_day": {
                "distribution": _dist(D05=10, D09=5, D10=5),
                "total": 20,
                "window_label": "Ontem",
                "baseline": {"pct": {f"D{i:02d}": 10.0 for i in range(1, 11)}, "label": "Base"},
                "baseline_champion": {"pct": {"D09": 30.0, "D10": 30.0}},   # jan_30: 60% D9-D10
                "baseline_challenger": {"pct": {"D09": 12.0, "D10": 12.0}}, # abr_28: 24% D9-D10
                "by_source": {
                    "meta": {"distribution": _dist(D05=8), "total": 8},
                    "google": {"distribution": ggl_source_dist, "total": ggl_source_total},
                },
                "by_source_challenger": by_source_challenger,
                "by_optgoal": {},
            }
        }
    }


def _google_line(blocks):
    for b in blocks:
        txt = (b.get("text") or {}).get("text", "")
        for ln in txt.splitlines():
            if ln.lstrip().startswith("Google"):
                return ln
    return None


def test_google_usa_regua_challenger_abr28():
    # Google combinado (Champion) seria D10-pesado; a régua Challenger diz outra coisa.
    ggl_champ = _dist(D09=20, D10=20)          # combinado/Champion: 100% D9-D10
    ggl_chal = {"google": {"distribution": _dist(D05=30, D09=5, D10=5), "total": 40}}  # Challenger: 25%
    v = _base_view(ggl_champ, 40, ggl_chal)
    B = []
    _slack_decis_window(v, B, "previous_day")
    line = _google_line(B)
    assert line is not None, "linha Google ausente"
    assert "abr_28" in line, f"Google deveria referir abr_28 (Challenger): {line!r}"
    assert "jan_30" not in line, f"Google NÃO pode referir jan_30: {line!r}"
    # n reflete o total da régua Challenger (40), não some
    assert "40" in line, f"n da régua Challenger esperado: {line!r}"


def test_google_degrada_sem_jan30_quando_challenger_ausente():
    ggl_champ = _dist(D09=20, D10=20)
    v = _base_view(ggl_champ, 40, None)         # régua Challenger não veio
    B = []
    _slack_decis_window(v, B, "previous_day")
    line = _google_line(B)
    assert line is not None
    assert "jan_30" not in line, f"degradação NÃO pode cair no jan_30: {line!r}"


def test_google_degrada_quando_challenger_total_zero():
    ggl_champ = _dist(D09=20, D10=20)
    ggl_chal = {"google": {"distribution": _dist(), "total": 0}}
    v = _base_view(ggl_champ, 40, ggl_chal)
    B = []
    _slack_decis_window(v, B, "previous_day")
    line = _google_line(B)
    assert line is not None
    assert "jan_30" not in line, f"total=0 não pode cair no jan_30: {line!r}"


if __name__ == "__main__":
    for fn in (test_google_usa_regua_challenger_abr28,
               test_google_degrada_sem_jan30_quando_challenger_ausente,
               test_google_degrada_quando_challenger_total_zero):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
