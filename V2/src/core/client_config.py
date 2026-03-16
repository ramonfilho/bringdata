"""
ClientConfig — Single Source of Truth para configurações por cliente.

Carregado de configs/clients/{client}.yaml. Cada sub-config mapeia os
hardcodes da varredura (seção 6 do plano) para campos tipados.

Os valores são preenchidos incrementalmente durante a Fase 2, componente
por componente. Campos ainda não migrados permanecem None.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def _make(cls, data: dict):
    """Instancia dataclass filtrando chaves desconhecidas do YAML."""
    if not data:
        return cls()
    known = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})


# ---------------------------------------------------------------------------
# Sub-configs — Grupo A: Pipelines ML core (Fases 1–2)
# ---------------------------------------------------------------------------

@dataclass
class InfraConfig:
    """Infraestrutura GCP — valores que mudam por cliente/ambiente. (#101, #102, #120, #124, #150, #153)"""
    gcp_project_id: Optional[str] = None
    cloud_run_url: Optional[str] = None
    validation_bucket: Optional[str] = None
    bigquery_dataset_id: Optional[str] = None
    bigquery_table_id: Optional[str] = None
    guru_api_base_url: Optional[str] = None
    guru_api_transactions_endpoint: Optional[str] = None


@dataclass
class IngestionConfig:
    """Ingestão de dados brutos e unificação de colunas. (#6–#26, #38, #57–#62, #68–#69)"""
    training_data_dir: Optional[str] = None
    tmb_detection_columns: Optional[List[str]] = None       # #6
    bare_campaign_names: Optional[List[str]] = None         # #8
    api_source_name: Optional[str] = None                   # #11
    has_tmb: bool = False                                    # #12
    sales_platform_identifier: Optional[str] = None         # #21
    approved_status_value: Optional[str] = None             # #22
    tmb_risk_column: Optional[str] = None                   # #23
    tmb_risk_values: Optional[List[str]] = None             # #62
    tmb_risk_filter_default: str = "all"                    # #26
    product_filter_keyword: Optional[str] = None            # #24
    pesquisa_date_column: Optional[str] = None              # #25
    lf_file_prefix: Optional[str] = None                    # #57
    lf_guru_exception_files: Optional[List[str]] = None     # #57
    local_sales_filename_identifier: Optional[str] = None   # #58
    min_survey_columns: int = 10                            # #59
    score_column_prefixes: Optional[List[str]] = None       # #60
    vendas_utm_columns_to_remove: Optional[List[str]] = None  # #61
    columns_to_remove: Optional[List[str]] = None           # #69 — substitui cleaning.colunas_remover
    column_rename_mapping: Optional[Dict[str, str]] = None  # #68
    dataset_cutoff_date: Optional[str] = None               # #38
    # Unificação de colunas (#13–#20) — sub-dict com pesquisa_merges,
    # valor_columns, produto_columns, nome_columns, email_columns, telefone_columns
    column_unification: Optional[Dict[str, Any]] = None


@dataclass
class UTMConfig:
    """Unificação de UTMs. (#35, #63, #67)"""
    source_to_outros: Optional[List[str]] = None            # #35
    source_to_channel_mapping: Optional[Dict[str, str]] = None  # dev/retreino — ex: {'youtube-bio': 'youtube'}
    term_mappings: Optional[Dict[str, str]] = None          # #63
    term_outros_patterns: Optional[List[str]] = None        # #63
    term_long_id_threshold: int = 10                        # #67


@dataclass
class MediumConfig:
    """Unificação de Medium — consolida 3 arquivos atuais. (#7, #36, #37, #50)"""
    valid_categories: Optional[List[str]] = None            # #7 — None = modo treino (threshold); preenchido = modo produção (whitelist)
    discontinued_categories: Optional[List[str]] = None     # #7 — deprecated; mantido para compatibilidade
    category_mappings: Optional[Dict[str, str]] = None      # #7 — mapeamento de variantes históricas
    adv_prefix: Optional[str] = None                        # #36 — prefixo a remover (ex: 'ADV')
    manual_unifications: Optional[Dict[str, str]] = None    # #37 — unificações adicionais pós-mapping
    binary_top3_categories: Optional[List[str]] = None      # #50 — pendente resolução em encoding
    frequency_threshold: float = 0.025                      # #7 — freq mínima para categoria válida no treino


@dataclass
class CategoryConfig:
    """Normalização de categorias. (#27–#33)"""
    categorical_columns: Optional[List[str]] = None         # #27
    category_mappings: Optional[Dict[str, Any]] = None      # #28–#33


@dataclass
class MatchingConfig:
    """Estratégia de matching leads→vendas — consolida 6 arquivos atuais. (#41–#46)"""
    strategy: Optional[str] = None
    pesquisa_email_column: Optional[str] = None             # #41
    pesquisa_phone_column: Optional[str] = None             # #42
    country_code: int = 55                                  # #43
    phone_digits: Optional[List[int]] = None                # #43
    alunos_todos_path: Optional[str] = None                 # #44
    validation_products: Optional[List[str]] = None         # #45
    alunos_email_column: Optional[str] = None               # #46


@dataclass
class FeatureConfig:
    """Feature engineering e seleção de features. (#2, #3, #34, #39, #40, #47, #48, #52, #65, #66)"""
    critical_columns: Optional[List[str]] = None            # #3, #40
    columns_to_remove: Optional[List[str]] = None           # #34
    columns_to_remove_post_cutoff: Optional[List[str]] = None  # #39
    columns_to_drop_after_fe: Optional[List[str]] = None    # #48
    pesquisa_name_column: Optional[str] = None              # #47
    pesquisa_phone_column: Optional[str] = None             # #42 (também em MatchingConfig)
    telefone_comprimento_keep_values: Optional[List[int]] = None  # #157 — valores válidos (ex: [9, 11]); resto → 'outros'
    ordering_rules: Optional[Dict[str, Any]] = None         # #2
    survey_column_stems: Optional[List[str]] = None         # #52
    utm_feature_prefixes_for_registry: Optional[List[str]] = None   # #65
    derived_feature_prefixes_for_registry: Optional[List[str]] = None  # #66
    nlp_columns: List[str] = field(default_factory=list)    # reservado — sempre vazio por ora


@dataclass
class EncodingConfig:
    """Encoding categórico e ordinal. (#49, #50, #51, #64, #70, #71)"""
    ordinal_variables: Optional[Dict[str, Any]] = None      # #49
    categorical_detection_max_unique: int = 20              # #64
    features_to_drop_after_encoding: Optional[List[str]] = None  # #51
    column_name_corrections: Optional[Dict[str, str]] = None     # #70


@dataclass
class ModelConfig:
    """Treino e artefatos de modelo. (#1, #10, #53, #54, #55, #56, #71, #72, #89)"""
    hyperparameters: Optional[Dict[str, Any]] = None        # #1
    buyer_weights: Optional[Dict[str, float]] = None        # #158 — PESOS_COMPRADOR por decil (dev/retreino)
    mlflow_experiment_name: Optional[str] = None            # #10
    mlflow_experiment_id: Optional[str] = None              # #71
    model_name_template: Optional[str] = None               # #53
    legacy_model_dir: Optional[str] = None                  # #72
    business_config_path: Optional[str] = None              # #55
    tuning_improvement_thresholds: Optional[Dict[str, float]] = None  # #56
    metadata_filename_pattern: Optional[str] = None         # #89
    top_decils_to_monitor: Optional[List[str]] = None       # #79


@dataclass
class MonitoringConfig:
    """Monitoramento contínuo e detecção de drift. (#4, #5, #9, #73–#86)"""
    model_name: Optional[str] = None                        # #5
    conversion_window_days: int = 20                        # #9
    medium_strategy: Optional[str] = None                   # #4
    survey_sheet_tab_index: int = 1                         # #73
    sheet_date_format: Optional[str] = None                 # #74
    timezone_offset_hours: int = -3                         # #75
    main_sheet_tab_index: int = 0                           # #76
    invalid_decil_values: Optional[List[str]] = None        # #77
    main_sheet_date_format: Optional[str] = None            # #78
    funnel_lookback_hours: int = 12                         # #80
    display_date_format: Optional[str] = None               # #81
    capi_events_per_lead_estimate: float = 1.3              # #82
    thresholds: Optional[Dict[str, Any]] = None             # #83
    missing_rate_ignore_columns: Optional[List[str]] = None # #84
    sheets_url: Optional[str] = None                        # #85
    backup_sheets_url: Optional[str] = None                 # #128
    drift_features_to_analyze: Optional[List[str]] = None   # #86


@dataclass
class CAPIConfig:
    """Integração Meta CAPI. (#103–#106, #140)"""
    pixel_id: Optional[str] = None                          # #103
    event_name_with_value: Optional[str] = None             # #104
    event_name_high_quality: Optional[str] = None           # #104
    event_name_faixa_a: Optional[str] = None                # #140
    high_quality_decils: Optional[List[str]] = None         # #105
    country_code: Optional[str] = None                      # #106
    currency: Optional[str] = None                          # #106
    decil_to_value: Optional[Dict[str, float]] = None


# ---------------------------------------------------------------------------
# Sub-configs — Grupo B: API operacional (Fase 2)
# ---------------------------------------------------------------------------

@dataclass
class APIConfig:
    """Constantes operacionais do servidor FastAPI. (#8, #109–#122)"""
    cors_origins: Optional[List[str]] = None                # #111
    batch_processing_size: int = 500                        # #114
    railway_polling_batch_size: int = 50                    # #122
    default_analysis_period_days: int = 30                  # #115
    utm_main_sources: Optional[List[str]] = None            # #116
    bare_medium_names: Optional[List[str]] = None           # #109
    generic_utm_terms: Optional[List[str]] = None           # #109, #117
    generic_utms_set: Optional[List[str]] = None            # #118
    sheets_column_names: Optional[Dict[str, str]] = None    # #100, #113
    railway_field_mappings: Optional[Dict[str, Any]] = None # #99
    utm_campaign_structure: Optional[Dict[str, str]] = None # #107


@dataclass
class RetainConfig:
    """Orquestração de retreino. (#87, #88, #89)"""
    quality_gate_warning_threshold: float = 0.10            # #87
    quality_gate_critical_threshold: float = 0.20          # #87


# ---------------------------------------------------------------------------
# ClientConfig — ponto de entrada
# ---------------------------------------------------------------------------

@dataclass
class ClientConfig:
    """
    Configuração completa de um cliente. Carregada via ClientConfig.from_yaml().

    Uso:
        config = ClientConfig.from_yaml('configs/clients/devclub.yaml')
        config.validate()
    """
    client_id: str = ""
    infra: InfraConfig = field(default_factory=InfraConfig)
    ingestion: IngestionConfig = field(default_factory=IngestionConfig)
    utm: UTMConfig = field(default_factory=UTMConfig)
    medium: MediumConfig = field(default_factory=MediumConfig)
    category: CategoryConfig = field(default_factory=CategoryConfig)
    matching: MatchingConfig = field(default_factory=MatchingConfig)
    feature: FeatureConfig = field(default_factory=FeatureConfig)
    encoding: EncodingConfig = field(default_factory=EncodingConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    capi: CAPIConfig = field(default_factory=CAPIConfig)
    api: APIConfig = field(default_factory=APIConfig)
    retrain: RetainConfig = field(default_factory=RetainConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ClientConfig":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(
            client_id=data.get("client_id", ""),
            infra=_make(InfraConfig, data.get("infra", {})),
            ingestion=_make(IngestionConfig, data.get("ingestion", {})),
            utm=_make(UTMConfig, data.get("utm", {})),
            medium=_make(MediumConfig, data.get("medium", {})),
            category=_make(CategoryConfig, data.get("category", {})),
            matching=_make(MatchingConfig, data.get("matching", {})),
            feature=_make(FeatureConfig, data.get("feature", {})),
            encoding=_make(EncodingConfig, data.get("encoding", {})),
            model=_make(ModelConfig, data.get("model", {})),
            monitoring=_make(MonitoringConfig, data.get("monitoring", {})),
            capi=_make(CAPIConfig, data.get("capi", {})),
            api=_make(APIConfig, data.get("api", {})),
            retrain=_make(RetainConfig, data.get("retrain", {})),
        )

    def validate(self) -> None:
        """Levanta ValueError com mensagem acionável se config inválida."""
        errors = []
        if not self.client_id:
            errors.append("client_id é obrigatório")
        if errors:
            raise ValueError(
                "ClientConfig inválida:\n" + "\n".join(f"  - {e}" for e in errors)
            )
