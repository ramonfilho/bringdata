"""Painel de decis roda numa régua ÚNICA: Challenger/abr_28 (decil_challenger,
scores_historicos). TODOS os buckets — Total, Meta, Google e os de
optimization_goal — vêm reavaliados nessa régua (app.py os reconstrói via
`challenger_decils_in_window`) e comparam contra a MESMA referência abr_28
(`baseline_challenger`). O modelo anterior jan_30 saiu do relatório: não há mais
barra, ref nem Ponderada dele.

Guarda contra regressão: (a) o Google (e o Total) referem abr_28, nunca jan_30 nem
Ponderada; (b) degrada limpo (sem ref, sem jan_30) quando a régua Challenger não
veio (`baseline_challenger` ausente = fail-soft de produção).

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


def _base_view(ggl_dist, ggl_total, *, with_ref=True):
    """Janela de decis mínima na régua única. `by_source.google` JÁ é o
    decil_challenger (app.py o reconstrói). `baseline_challenger` = ref abr_28;
    None = fail-soft (régua não veio) → linhas sem Δ, nunca jan_30."""
    return {
        "lead_quality": {
            "decil_distribution_previous_day": {
                "distribution": _dist(D05=10, D09=5, D10=5),
                "total": 20,
                "window_label": "Ontem",
                # abr_28 baixo em D9-D10 (24%): a única ref do painel.
                "baseline_challenger": (
                    {"pct": {"D09": 12.0, "D10": 12.0}, "label": "Top 6 ROAS"}
                    if with_ref else None
                ),
                "by_source": {
                    "meta": {"distribution": _dist(D05=8), "total": 8},
                    "google": {"distribution": ggl_dist, "total": ggl_total},
                },
                "by_optgoal": {},
            }
        }
    }


def _line(blocks, prefix):
    for b in blocks:
        txt = (b.get("text") or {}).get("text", "")
        for ln in txt.splitlines():
            if ln.lstrip().startswith(prefix):
                return ln
    return None


def _all_text(blocks):
    return "\n".join((b.get("text") or {}).get("text", "") for b in blocks)


def test_google_refere_abr28_nunca_jan30_nem_ponderada():
    ggl = _dist(D05=30, D09=5, D10=5)          # 25% D9-D10 na régua abr_28
    v = _base_view(ggl, 40)
    B = []
    _slack_decis_window(v, B, "previous_day")
    line = _line(B, "Google")
    assert line is not None, "linha Google ausente"
    assert "abr_28" in line, f"Google deveria referir abr_28: {line!r}"
    assert "jan_30" not in line, f"Google NÃO pode referir jan_30: {line!r}"
    assert "40" in line, f"n do Google esperado (40): {line!r}"
    # painel inteiro: sem jan_30, sem Ponderada em lugar nenhum
    txt = _all_text(B)
    assert "jan_30" not in txt, "painel não pode citar jan_30"
    assert "Ponderada" not in txt, "painel não pode citar Ponderada"


def test_total_tambem_refere_abr28():
    v = _base_view(_dist(D05=30, D09=5, D10=5), 40)
    B = []
    _slack_decis_window(v, B, "previous_day")
    line = _line(B, "Total")
    assert line is not None and "abr_28" in line, f"Total deveria referir abr_28: {line!r}"


def test_degrada_sem_ref_e_sem_jan30_quando_regua_ausente():
    v = _base_view(_dist(D09=20, D10=20), 40, with_ref=False)  # baseline_challenger None
    B = []
    _slack_decis_window(v, B, "previous_day")
    txt = _all_text(B)
    assert "jan_30" not in txt, "degradação NÃO pode cair no jan_30"
    assert "Ponderada" not in txt, "degradação NÃO pode citar Ponderada"
    # Google ainda aparece (barra), só que sem Δ vs ref
    assert _line(B, "Google") is not None, "linha Google deve aparecer mesmo sem ref"


if __name__ == "__main__":
    for fn in (test_google_refere_abr28_nunca_jan30_nem_ponderada,
               test_total_tambem_refere_abr28,
               test_degrada_sem_ref_e_sem_jan30_quando_regua_ausente):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
