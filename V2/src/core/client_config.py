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
    # Banco de dados (prep para A2 — pipeline dict por cliente)
    # "RAILWAY" = compor URL a partir de RAILWAY_DB_* env vars (DevClub)
    # Qualquer outro valor = nome da env var que contém a URL completa (Cloud SQL)
    db_url_env_var: str = 'DATABASE_URL'


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
    # TMB dual-source: arquivo de pedidos (email + telefone, sem risco) (#154–#156)
    tmb_pedidos_detection_columns: Optional[List[str]] = None   # #154 — colunas que identificam arquivo de pedidos
    tmb_pedidos_column_mapping: Optional[Dict[str, str]] = None  # #155 — renomeação para formato canônico
    tmb_pedidos_active_status_exclude: Optional[str] = None      # #156 — valor de status a excluir (ex: "Cancelado")
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
    mlflow_experiment_id: Optional[str] = None              # #71 — DEPRECATED: derivado em runtime via mlflow.get_run(). Mantido como fallback de emergência.
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
    # decil_to_value removido (DT-5): calculado em runtime como business.product_value × business.conversion_rates[decil]


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


@dataclass
class BusinessConfig:
    """Métricas de negócio e parâmetros de otimização de budget. (#90–#98)"""
    product_value: float = 1563.75                          # #90 — valor médio ponderado Guru + TMB
    conversion_rates: Optional[Dict[str, float]] = None    # #91 — taxa por decil D01–D10
    spend_threshold_zero_leads: float = 100.0               # #92 — R$ mínimo com 0 leads para pausar
    minimum_leads_threshold: int = 3                        # #93 — leads mínimos para dados suficientes
    color_thresholds: Optional[Dict[str, int]] = None      # #94 — thresholds de cor (green_min, yellow_min)
    min_roas_safety: float = 2.5                            # #95 — ROAS mínimo de segurança
    cap_variation_max: float = 100.0                        # #96 — cap de aumento de budget (%)
    confidence_sigmoid_l50: float = 15.0                    # #97 — ponto médio da sigmoid de confiança
    confidence_sigmoid_k: float = 0.15                      # #97 — inclinação da sigmoid
    roas_target: float = 8.0                                # #98 — ROAS alvo para confiança máxima

    # --- Previsão de faturamento (base empírica: LF42–LF47, modelo jan30) ---
    # Suposição: tracking rate uniforme entre decis (não verificado por ausência
    # de dados por decil nos relatórios históricos). Decis D01–D06 agrupados como
    # bloco único (volume histórico insuficiente para taxas individuais confiáveis).
    tracking_rate: float = 0.528                           # mediana histórica dos 6 lançamentos (range: 43.9%–66.4%)
    scenario_pessimistic_factor: float = 0.97              # fator empírico — piso da conv. rate histórica vs mediana
    scenario_optimistic_factor: float = 1.03               # fator empírico — teto da conv. rate histórica vs mediana
    launch_benchmark: Optional[Dict[str, Any]] = None      # mediana histórica para indexação comparativa
    # Estrutura esperada de launch_benchmark:
    #   periodo_referencia: str     (ex: "mediana_LF42-LF47")
    #   leads_mediana: int          (mediana de leads dos 6 lançamentos)
    #   vendas_mediana: int         (mediana de vendas totais)
    #   pct_d9d10_mediana: float    (mediana de % D9+D10)

    # Ticket contratado (valor nominal da venda, sem desconto de inadimplência)
    # Guru (cartão) e TMB (boleto parcelado) têm o mesmo ticket contratado.
    # Inadimplência do boleto é risco operacional — não entra na previsão de faturamento.
    ticket_contracted: float = 2200.0                      # valor nominal do produto — base do faturamento total

    # Guru: preço real e fator de realização
    # O ticket_contracted (R$2.200) é o objetivo de negócio, mas o Guru vende a R$1.997 (payment.gross via API).
    # guru_realizacao_factor absorve cancelamentos + chargebacks (~13%, back-calculado de LF42–LF47).
    guru_ticket_price: float = 1997.0                      # preço real no Guru (payment.gross) — ≠ ticket contratado
    guru_realizacao_factor: float = 0.87                   # fator de realização Guru (1 - taxa cancelamento/chargeback)

    # Proporção histórica cartão/boleto (mediana LF42–LF47, audience-dependent)
    # Cartão = Guru + Hotmart | Boleto = TMB + ASAAS
    pct_cartao_historico: float = 0.468                    # % mediana de vendas via cartão (Guru + Hotmart)

    # Parcelas do boleto TMB/ASAAS (entrada + N mensais)
    # Fonte: contas_a_receber TMB — oferta padrão "Entr. + 11x" = 12 pagamentos
    # Usado para calcular faturamento_recebido = cartão líquido Guru + 1ª parcela boleto
    n_parcelas_boleto: int = 12                            # número total de pagamentos (entrada + mensais)

    # Benchmark de taxa de conversão por faixa de decil (base: produção observada)
    # Usado para calcular tc_esperada do lançamento em curso a partir da distribuição atual de leads.
    # Estrutura: { periodo_referencia, D1_D5, D6_D9, D10 }
    conversion_rate_benchmark: Optional[Dict[str, Any]] = None

    # Taxa de conversão rastreada mediana — base do forecast flat-rate (metodologia do backtest)
    # conv_rastr = vendas_matched / total_leads_meta
    # Mediana LF42–LF47: [0.54%, 0.62%, 0.64%, 0.66%, 0.73%, 0.74%] → mediana = 0.65%
    # forecast: buyers = total_leads_meta × (conv_rastr_mediana / tracking_rate)
    conv_rastr_mediana: float = 0.0065                      # mediana histórica LF42–LF47



@dataclass
class ValidationConfig:
    """Validação de schema e qualidade de dados pré-treino. (DT item 7)

    Dois pontos de uso no train_pipeline.py:
      - validate_ingestion(): após Célula 4 — schema bruto (colunas obrigatórias, tamanho, datas)
      - validate_features(): após Célula 8 — missing rates das features críticas

    on_error: "raise" aborta o pipeline; "warn" loga e continua (útil durante exploração do Cliente B).
    """
    # Ponto A — schema de ingestão (df_pesquisa + df_vendas brutos)
    required_survey_columns: Optional[List[str]] = None        # colunas obrigatórias no df_pesquisa
    required_sales_columns: Optional[List[str]] = None         # colunas obrigatórias no df_vendas
    min_survey_records: int = 500                              # mínimo de linhas em df_pesquisa
    max_email_missing_rate: float = 0.30                       # threshold de nulos em coluna de email
    min_date_parse_rate: float = 0.80                          # fração mínima de datas parseáveis

    # Ponto B — qualidade de features (df pós-Célula 8)
    feature_missing_thresholds: Optional[Dict[str, float]] = None  # {coluna: max_missing_rate}; None = sem validação

    # Comportamento
    on_error: str = "raise"                                    # "raise" | "warn"


# ---------------------------------------------------------------------------
# ABTestConfig — carregado de configs/active_models/{client_id}.yaml
# Independente do ClientConfig (que vem de configs/clients/).
# ---------------------------------------------------------------------------

@dataclass
class ABTestVariantConfig:
    """Configuração de uma variante do teste A/B (champion ou challenger)."""
    run_id: str
    utm_pattern: Dict[str, str]          # OR logic: basta 1 campo casar
    capi_event_name: str
    capi_event_name_high_quality: str
    conversion_rates: Dict[str, float]   # D01–D10, com PAV aplicado se necessário
    encoding_overrides: Optional["EncodingConfig"] = None  # DT-12 — encoding específico do modelo


@dataclass
class ABTestConfig:
    """
    Teste A/B champion/challenger. Carregado pelo LeadScoringPipeline de
    configs/active_models/{client_id}.yaml (bloco 'ab_test').

    Quando enabled=False, o pipeline ignora completamente este config.
    """
    enabled: bool = False
    variants: Dict[str, ABTestVariantConfig] = field(default_factory=dict)

    @classmethod
    def from_active_model_yaml(cls, path: str | Path) -> "ABTestConfig":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        ab = data.get("ab_test", {})
        if not ab or not ab.get("enabled", False):
            return cls(enabled=False)
        variants = {}
        for name, vdata in ab.get("variants", {}).items():
            enc_raw = vdata.get("encoding_overrides")
            encoding_overrides = EncodingConfig(
                ordinal_variables=enc_raw.get("ordinal_variables"),
                categorical_detection_max_unique=enc_raw.get("categorical_detection_max_unique", 20),
                features_to_drop_after_encoding=enc_raw.get("features_to_drop_after_encoding"),
                column_name_corrections=enc_raw.get("column_name_corrections"),
            ) if enc_raw else None
            variants[name] = ABTestVariantConfig(
                run_id=vdata["run_id"],
                utm_pattern=vdata.get("utm_pattern") or {},
                capi_event_name=vdata["capi_event_name"],
                capi_event_name_high_quality=vdata["capi_event_name_high_quality"],
                conversion_rates=vdata["conversion_rates"],
                encoding_overrides=encoding_overrides,
            )
        return cls(enabled=True, variants=variants)

    def match_variant(self, lead_utms: Dict[str, Optional[str]]) -> Optional[ABTestVariantConfig]:
        """
        Retorna a variante cuja utm_pattern casa com os UTMs do lead (OR logic).
        Retorna None se nenhuma variante casar — lead fica fora do teste.

        lead_utms: dict com chaves utm_source, utm_medium, utm_campaign,
                   utm_content, utm_term (valores podem ser None).
        """
        for variant in self.variants.values():
            if not variant.utm_pattern:
                continue
            for field_name, pattern in variant.utm_pattern.items():
                value = lead_utms.get(field_name) or ""
                if pattern.lower() in value.lower():
                    return variant
        return None


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
    business: BusinessConfig = field(default_factory=BusinessConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)

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
            business=_make(BusinessConfig, data.get("business", {})),
            validation=_make(ValidationConfig, data.get("validation", {})),
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
