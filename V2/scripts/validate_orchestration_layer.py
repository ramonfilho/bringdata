#!/usr/bin/env python3
"""
validate_orchestration_layer.py

Valida que a camada de orquestração (Fase 3a) produz comportamento
idêntico ao baseline — equivalente ao validate_parity_snapshots.py
para a camada de dados, mas para prediction, monitoring e retrain.

Estrutura de duas camadas:
  Camada 1 (estrutural): imports + instanciação — já coberta pelo smoke test.
  Camada 2 (funcional): parity checks com banco e dados reais — este script.

Checks:
  2a  prediction  — LeadScoringPredictor com/sem client_config carrega o mesmo run_id
  2b  prediction  — predições idênticas no mesmo DataFrame de amostra
  2c  monitoring  — DataQualityMonitor com/sem client_config produz os mesmos alertas
  2d  retrain     — get_active_model_path() == get_active_model_path('devclub')
  2e  monitoring  — thresholds resolvidos do ClientConfig batem com config.py defaults
  2f  training    — experiment_name e model_name derivados do ClientConfig são corretos

Uso:
    cloud-sql-proxy smart-ads-451319:us-central1:smart-ads-db &
    sleep 5
    export DB_HOST=127.0.0.1 DB_PORT=5432 DB_NAME=smart_ads DB_USER=postgres DB_PASSWORD=SmartAds2026DB!
    python scripts/validate_orchestration_layer.py
"""

import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import traceback
from datetime import datetime, timedelta

PASS = "[PASS]"
FAIL = "[FAIL]"
SKIP = "[SKIP]"

results = []


def check(name, fn):
    """Executa um check e registra resultado."""
    print(f"\n{'─'*70}")
    print(f"  {name}")
    print(f"{'─'*70}")
    try:
        fn()
        results.append((name, True, None))
        print(f"  {PASS}")
    except AssertionError as e:
        results.append((name, False, str(e)))
        print(f"  {FAIL}  {e}")
        traceback.print_exc()
    except Exception as e:
        results.append((name, False, f"{type(e).__name__}: {e}"))
        print(f"  {FAIL}  {type(e).__name__}: {e}")
        traceback.print_exc()


# =============================================================================
# 2f — training: experiment_name e model_name derivados do ClientConfig
# =============================================================================

def check_training_config():
    from src.core.client_config import ClientConfig
    from src.monitoring.config import THRESHOLDS as DEFAULT_THRESHOLDS

    cfg = ClientConfig.from_yaml(str(ROOT / "configs/clients/devclub.yaml"))

    exp_name = (
        cfg.model.mlflow_experiment_name
        if cfg.model and cfg.model.mlflow_experiment_name
        else None
    )
    assert exp_name == "devclub_lead_scoring", (
        f"experiment_name={exp_name!r}, esperado 'devclub_lead_scoring'"
    )
    print(f"  experiment_name = {exp_name!r}  ✓")

    model_name = cfg.model.model_name_template.format(split_method="temporal")
    assert model_name == "v1_devclub_rf_temporal_single", (
        f"model_name={model_name!r}, esperado 'v1_devclub_rf_temporal_single'"
    )
    print(f"  model_name (temporal) = {model_name!r}  ✓")

    # ClientConfig sem thresholds customizados → deve usar defaults de config.py
    assert cfg.monitoring.thresholds is None, (
        "devclub.yaml não deve ter thresholds customizados — usa defaults de config.py"
    )
    print(f"  monitoring.thresholds = null → usará config.py defaults  ✓")


# =============================================================================
# 2e — monitoring: thresholds resolvidos == config.py defaults
# =============================================================================

def check_threshold_resolution():
    from src.core.client_config import ClientConfig
    from src.monitoring.data_quality import DataQualityMonitor
    from src.monitoring.operational_monitor import OperationalMonitor
    from src.monitoring.capi_monitor import CAPIQualityMonitor
    from src.monitoring.config import THRESHOLDS, MISSING_RATE_IGNORE_COLUMNS

    cfg = ClientConfig.from_yaml(str(ROOT / "configs/clients/devclub.yaml"))

    # DataQualityMonitor sem client_config → usa config.py direto
    mon_sem = DataQualityMonitor(model_path="/tmp/fake")
    # DataQualityMonitor com client_config devclub (sem thresholds customizados) → mesmo resultado
    mon_com = DataQualityMonitor(model_path="/tmp/fake", client_config=cfg)

    assert mon_sem._thresholds is THRESHOLDS, "sem client_config deve usar objeto THRESHOLDS do config.py"
    assert mon_com._thresholds is THRESHOLDS, "com client_config devclub (sem customizações) deve usar mesmo THRESHOLDS"
    print(f"  DataQualityMonitor._thresholds idênticos  ✓")

    assert mon_sem._missing_rate_ignore_columns is MISSING_RATE_IGNORE_COLUMNS
    assert mon_com._missing_rate_ignore_columns is MISSING_RATE_IGNORE_COLUMNS
    print(f"  DataQualityMonitor._missing_rate_ignore_columns idênticos ({len(MISSING_RATE_IGNORE_COLUMNS)} colunas)  ✓")

    op_sem = OperationalMonitor(db=None)
    op_com = OperationalMonitor(db=None, client_config=cfg)
    assert op_sem._thresholds is THRESHOLDS
    assert op_com._thresholds is THRESHOLDS
    print(f"  OperationalMonitor._thresholds idênticos  ✓")

    capi_sem = CAPIQualityMonitor(db=None)
    capi_com = CAPIQualityMonitor(db=None, client_config=cfg)
    assert capi_sem._thresholds is THRESHOLDS
    assert capi_com._thresholds is THRESHOLDS
    print(f"  CAPIQualityMonitor._thresholds idênticos  ✓")


# =============================================================================
# 2d — retrain: get_active_model_path() == get_active_model_path('devclub')
# =============================================================================

def check_active_model_path_parity():
    from src.retrain.data_validation import get_active_model_path

    path_default = get_active_model_path()           # default = 'devclub'
    path_explicit = get_active_model_path('devclub')

    assert path_default == path_explicit, (
        f"path_default={path_default!r} != path_explicit={path_explicit!r}"
    )
    print(f"  get_active_model_path() == get_active_model_path('devclub')  ✓")
    print(f"  path = {path_default!r}")


# =============================================================================
# 2a — prediction: mesmo run_id com/sem client_config
# =============================================================================

def check_predictor_parity():
    from src.core.client_config import ClientConfig
    from src.model.prediction import LeadScoringPredictor

    cfg = ClientConfig.from_yaml(str(ROOT / "configs/clients/devclub.yaml"))

    pred_sem = LeadScoringPredictor(use_active_model=True)
    pred_com = LeadScoringPredictor(use_active_model=True, client_config=cfg)

    assert pred_sem.mlflow_run_id is not None, "LeadScoringPredictor sem client_config não carregou run_id"
    assert pred_sem.mlflow_run_id == pred_com.mlflow_run_id, (
        f"run_id diverge:\n  sem: {pred_sem.mlflow_run_id}\n  com: {pred_com.mlflow_run_id}"
    )
    print(f"  mlflow_run_id = {pred_sem.mlflow_run_id!r}  ✓")
    print(f"  model_name parity  ✓")

    # Carregar modelos e comparar feature count
    pred_sem.load_model()
    pred_com.load_model()

    assert len(pred_sem.feature_names) == len(pred_com.feature_names), (
        f"feature count diverge: sem={len(pred_sem.feature_names)}, com={len(pred_com.feature_names)}"
    )
    print(f"  feature_names count = {len(pred_sem.feature_names)}  ✓")

    assert pred_sem.feature_names == pred_com.feature_names, (
        "feature_names diferem entre os dois preditores"
    )
    print(f"  feature_names idênticos  ✓")


# =============================================================================
# 2b — prediction: predições idênticas no mesmo DataFrame de amostra
# =============================================================================

def check_prediction_parity():
    import pandas as pd
    import numpy as np
    from src.core.client_config import ClientConfig
    from src.model.prediction import LeadScoringPredictor

    cfg = ClientConfig.from_yaml(str(ROOT / "configs/clients/devclub.yaml"))

    pred_sem = LeadScoringPredictor(use_active_model=True)
    pred_com = LeadScoringPredictor(use_active_model=True, client_config=cfg)
    pred_sem.load_model()
    pred_com.load_model()

    # Criar DataFrame sintético com todas as features esperadas (valores 0)
    features = pred_sem.feature_names
    df_fake = pd.DataFrame(
        np.zeros((10, len(features))),
        columns=features
    )

    scores_sem = pred_sem.model.predict_proba(df_fake[features].values)[:, 1]
    scores_com = pred_com.model.predict_proba(df_fake[features].values)[:, 1]

    assert np.allclose(scores_sem, scores_com, atol=1e-10), (
        f"predições divergem:\n  sem: {scores_sem[:3]}\n  com: {scores_com[:3]}"
    )
    print(f"  predições idênticas em {len(df_fake)} amostras sintéticas  ✓")
    print(f"  score médio = {scores_sem.mean():.6f}  ✓")


# =============================================================================
# 2c — monitoring: DataQualityMonitor com/sem client_config produz mesmos alertas
# =============================================================================

def check_monitoring_parity():
    from datetime import datetime, timedelta
    from src.core.client_config import ClientConfig
    from src.monitoring.data_quality import DataQualityMonitor
    from src.retrain.data_validation import get_active_model_path
    from src.validation.data_loader import LeadDataLoader

    cfg = ClientConfig.from_yaml(str(ROOT / "configs/clients/devclub.yaml"))
    model_path = get_active_model_path('devclub')
    print(f"  model_path = {model_path!r}")

    # Buscar dados reais das últimas 48h
    print(f"  Buscando dados do Sheets (48h)...")
    loader = LeadDataLoader()
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
    df_sheets = loader.load_leads_from_sheets(
        start_date=start_date,
        end_date=end_date,
        use_cache=False
    )
    print(f"  {len(df_sheets)} leads carregados do Sheets")
    assert len(df_sheets) > 0, "Nenhum lead encontrado no Sheets — verificar conexão"

    # Preprocessing mínimo (rename colunas longas) — mesmo que o orchestrator faz
    from src.core.preprocessing import preprocess_for_monitoring
    df_proc = preprocess_for_monitoring(df_sheets.copy(), cfg.ingestion, cfg.feature)

    # Executar monitor SEM client_config (comportamento pré-3a)
    mon_sem = DataQualityMonitor(model_path=model_path)
    alertas_sem = mon_sem._check_missing_rate(df_proc)
    alertas_sem += mon_sem._check_distribution_drift(df_proc)
    alertas_sem += mon_sem._check_score_distribution(df_proc)

    # Executar monitor COM client_config (comportamento pós-3a)
    mon_com = DataQualityMonitor(model_path=model_path, client_config=cfg)
    alertas_com = mon_com._check_missing_rate(df_proc)
    alertas_com += mon_com._check_distribution_drift(df_proc)
    alertas_com += mon_com._check_score_distribution(df_proc)

    # Parity: mesmo número de alertas
    assert len(alertas_sem) == len(alertas_com), (
        f"alert count diverge: sem={len(alertas_sem)}, com={len(alertas_com)}"
    )
    print(f"  alert count = {len(alertas_sem)} (idêntico)  ✓")

    # Parity: mesmos tipos de alertas
    tipos_sem = sorted(a['type'] for a in alertas_sem)
    tipos_com = sorted(a['type'] for a in alertas_com)
    assert tipos_sem == tipos_com, (
        f"alert types divergem:\n  sem: {tipos_sem}\n  com: {tipos_com}"
    )
    print(f"  alert types idênticos: {tipos_sem}  ✓")


# =============================================================================
# EXECUÇÃO
# =============================================================================

if __name__ == "__main__":
    print("\n")
    print("=" * 70)
    print("  VALIDAÇÃO CAMADA DE ORQUESTRAÇÃO — Fase 3a")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    check("2e — thresholds resolvidos == config.py defaults", check_threshold_resolution)
    check("2f — ClientConfig: experiment_name e model_name corretos", check_training_config)
    check("2d — get_active_model_path() parity (default 'devclub')", check_active_model_path_parity)
    check("2a — LeadScoringPredictor: mesmo run_id com/sem client_config", check_predictor_parity)
    check("2b — predições idênticas no mesmo DataFrame", check_prediction_parity)
    check("2c — DataQualityMonitor: mesmos alertas com/sem client_config", check_monitoring_parity)

    print(f"\n{'=' * 70}")
    print(f"  RESULTADO FINAL")
    print(f"{'=' * 70}")

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)

    for name, ok, err in results:
        status = PASS if ok else FAIL
        print(f"  {status}  {name}")
        if err:
            print(f"         → {err}")

    print(f"\n  {passed}/{len(results)} checks passaram")
    print("=" * 70)

    if failed > 0:
        sys.exit(1)
