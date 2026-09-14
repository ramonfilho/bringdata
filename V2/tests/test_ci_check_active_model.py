"""
Gate do modelo no CI: a régua vale para quem ENTRA no YAML, lida do run do MLflow.

Só a parte pura (sem MLflow, sem bucket): quem entra, e como cada run é julgado. Os
números dos limiares são os de configs/retreino_mensal.yaml; os do champion atual são
os do run real (AUC 0,7531, monotonia 77,8%), que justamente NÃO passaria no piso de
80% e por isso não pode ser rejulgado a cada PR.
"""
from scripts.ci_check_active_model import julgar, limiares_de, runs_do_yaml, runs_que_entram

LIM = limiares_de({"comparison": {"min_auc": 0.65, "min_monotonia": 0.80,
                                  "manual_approval_threshold": 0.005, "auto_approve_threshold": 0.02}})
BOM = {"auc": 0.7297, "monotonia_percentage": 88.89, "lift_maximum": 3.32}
LIMPO = {"git_commit": "135b219", "git_dirty": "false"}


def _yaml(champion, variantes=None, enabled=True):
    return {"active_model": {"mlflow_run_id": champion},
            "ab_test": {"enabled": enabled, "variants": {k: {"run_id": v} for k, v in (variantes or {}).items()}}}


def test_runs_do_yaml_le_champion_e_variantes_so_com_ab_ligado():
    assert runs_do_yaml(_yaml("c1", {"a": "r1", "b": "r2"})) == {"champion": "c1", "variante:a": "r1", "variante:b": "r2"}
    assert runs_do_yaml(_yaml("c1", {"a": "r1"}, enabled=False)) == {"champion": "c1"}
    assert runs_do_yaml({}) == {}


def test_so_quem_muda_entra_no_julgamento():
    base = _yaml("c1", {"a": "r1", "b": "r2"})
    head = _yaml("c1", {"a": "r1", "b": "r9", "c": "r3"})
    assert sorted(runs_que_entram(base, head)) == [("variante:b", "r9", "r2"), ("variante:c", "r3", None)]
    assert runs_que_entram(base, base) == []


def test_champion_trocado_carrega_o_anterior_para_o_delta():
    assert runs_que_entram(_yaml("c1"), _yaml("c2")) == [("champion", "c2", "c1")]


def test_aprova_run_limpo_acima_dos_pisos():
    ok, motivos, nota = julgar("variante:x", BOM, LIMPO, "FINISHED", True, LIM)
    assert ok and motivos == []


def test_reprova_abaixo_do_piso_de_monotonia():
    ok, motivos, _ = julgar("variante:x", {**BOM, "monotonia_percentage": 77.78}, LIMPO, "FINISHED", True, LIM)
    assert not ok and any("monotonia" in m for m in motivos)


def test_reprova_sem_lineage_ou_arvore_suja():
    ok, motivos, _ = julgar("variante:x", BOM, {}, "FINISHED", True, LIM)
    assert not ok and any("git_commit" in m for m in motivos)
    ok, motivos, _ = julgar("variante:x", BOM, {"git_commit": "abc", "git_dirty": "true"}, "FINISHED", True, LIM)
    assert not ok and any("suja" in m for m in motivos)


def test_reprova_run_nao_finalizado_ou_sem_artefato():
    ok, motivos, _ = julgar("variante:x", BOM, LIMPO, "RUNNING", True, LIM)
    assert not ok and any("FINISHED" in m for m in motivos)
    ok, motivos, _ = julgar("variante:x", BOM, LIMPO, "FINISHED", False, LIM)
    assert not ok and any("artefatos" in m for m in motivos)


def test_champion_novo_precisa_bater_o_anterior_pela_politica_do_retreino():
    anterior = {"auc": 0.7531}
    ok, motivos, _ = julgar("champion", {**BOM, "auc": 0.7540}, LIMPO, "FINISHED", True, LIM, anterior)
    assert not ok and any("manter champion" in m for m in motivos)          # +0,0009 < +0,005
    ok, _, nota = julgar("champion", {**BOM, "auc": 0.7600}, LIMPO, "FINISHED", True, LIM, anterior)
    assert ok and nota.startswith("manual")                                  # +0,0069: entre os dois
    ok, _, nota = julgar("champion", {**BOM, "auc": 0.7800}, LIMPO, "FINISHED", True, LIM, anterior)
    assert ok and nota.startswith("auto")                                    # +0,0269 >= +0,02


def test_variante_nova_nao_e_comparada_com_champion():
    ok, motivos, nota = julgar("variante:x", {**BOM, "auc": 0.66}, LIMPO, "FINISHED", True, LIM, {"auc": 0.75})
    assert ok and nota == "ok"
