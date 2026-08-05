"""
Testes do gerador de model card. Focam na parte PURA (render, parse, decisão de
status, append) — nada aqui toca o MLflow, por injeção de dados. Cobre o contrato:
o card reflete os fatos do run, o status é derivado do YAML de produção, e a
inserção é "mais recente no topo".
"""
import textwrap

import pytest

from src.model.model_card import (
    render_card, _pct, decide_status, read_prev_entry, append_to_changelog,
)


def _fixture_data():
    return {
        "run_id": "abc123def456",
        "trained_at": "2026-07-23",
        "model_name": "RF teste",
        "git_commit": "9175264",
        "git_dirty": "false",
        "params": {
            "total_records": "316280", "total_positives": "4043",
            "positive_rate": "0.0083", "dataset_fingerprint": "deadbeef12345678",
            "split_method": "temporal_leads", "cut_date": "2026-05-01",
            "period_start": "2025-03-01", "period_end": "2026-07-01",
            "train_records": "253024", "test_records": "63256",
            "use_buyer_weights": "True", "tmb_risk_filter": "all",
            "matching_method": "email_telefone", "total_features": "53",
            "n_estimators": "300", "max_depth": "8", "max_features": "sqrt",
        },
        "metrics": {
            "auc": 0.7290, "ks": 0.42, "lift_maximum": 3.22, "top3_decil_concentration": 63.07,
            "top5_decil_concentration": 79.55, "monotonia_percentage": 88.89,
            "baseline_conversion_rate": 0.0083,
        },
    }


def test_pct_aceita_fracao_e_percentual():
    assert _pct(0.0083) == "0.83%"      # fração → %
    assert _pct(63.07) == "63.07%"      # já em %
    assert _pct(None) == "?"


def test_render_reflete_os_fatos_do_run():
    md = render_card(_fixture_data(), status_label="CANDIDATO",
                     decision="CANDIDATO — teste.")
    # cabeçalho com data, nome e status
    assert "## 2026-07-23 — RF teste — CANDIDATO" in md
    # fatos-chave presentes
    assert "`abc123def456`" in md          # run_id
    assert "`9175264`" in md               # commit do código
    assert "`deadbeef12345678`" in md      # fingerprint
    assert "0.7290" in md                  # AUC
    assert "0.4200" in md                  # KS
    assert "3.22" in md                    # lift
    assert "63.07%" in md                  # top-3
    assert "features=53" in md
    assert "n_estimators=300" in md
    assert "CANDIDATO — teste." in md


def test_render_marca_arvore_suja():
    d = _fixture_data(); d["git_dirty"] = "true"
    md = render_card(d, status_label="CANDIDATO", decision="x")
    assert "árvore suja" in md


def test_decide_status_deployado_e_candidato(tmp_path):
    yaml_txt = textwrap.dedent("""
        active_model:
          mlflow_run_id: aaa111
        ab_test:
          enabled: true
          variants:
            champion_x:
              run_id: aaa111
              role: champion
            challenger_y:
              run_id: bbb222
              role: challenger
    """)
    yp = tmp_path / "active.yaml"
    yp.write_text(yaml_txt)

    lab, _ = decide_status("aaa111", active_yaml_path=yp)
    assert lab == "DEPLOYADO"
    lab2, det2 = decide_status("bbb222", active_yaml_path=yp)
    assert lab2 == "DEPLOYADO" and "challenger" in det2
    lab3, _ = decide_status("zzz999", active_yaml_path=yp)
    assert lab3 == "CANDIDATO"


def test_decide_status_yaml_ausente_vira_candidato(tmp_path):
    lab, _ = decide_status("qualquer", active_yaml_path=tmp_path / "naoexiste.yaml")
    assert lab == "CANDIDATO"


def test_read_prev_entry_extrai_runid_e_commit(tmp_path):
    cl = textwrap.dedent("""
        # Changelog

        ## Template de entrada
        ```
        ## <data> — algo
        ```
        ---

        ## 2026-07-23 — RF novo — CANDIDATO

        - **run_id:** `1f0f0a71`  ·  **código:** `9175264` (PR #90)  ·  **modelo anterior:** `x`
        - **Dados:** ...

        ---

        ## Referência — abr28
        - **run_id:** `5d158f0a`
    """)
    p = tmp_path / "CL.md"
    p.write_text(cl)
    prev = read_prev_entry(changelog_path=p)
    assert prev["run_id"] == "1f0f0a71"
    assert prev["git_commit"] == "9175264"


def test_append_insere_no_topo(tmp_path):
    cl = textwrap.dedent("""
        # Changelog

        ## Template de entrada
        ```
        exemplo
        ```
        ---

        ## 2026-07-01 — antigo — DEPLOYADO

        - **run_id:** `velho`
    """)
    p = tmp_path / "CL.md"
    p.write_text(cl)
    bloco = "## 2026-07-23 — novo — CANDIDATO\n\n- **run_id:** `novo`"
    append_to_changelog(bloco, changelog_path=p)
    txt = p.read_text()
    # o novo aparece ANTES do antigo
    assert txt.index("novo") < txt.index("antigo")
    # o antigo continua lá
    assert "## 2026-07-01 — antigo" in txt


def test_render_changes_rascunho_e_vazio():
    d = _fixture_data()
    md = render_card(d, status_label="CANDIDATO", decision="x",
                     changes=["abc feat: um", "def fix: dois"])
    assert "rascunho automático" in md and "abc feat: um" in md
    md2 = render_card(d, status_label="CANDIDATO", decision="x", changes=[])
    assert "nenhum commit" in md2
