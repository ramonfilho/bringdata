"""
PAYLOAD_SCHEMA — declaração explícita de TODOS os paths produzidos pelo endpoint
/monitoring/daily-check/railway, com decisão de render/skip por path.

Auto-gerado a partir do payload em 2026-05-12. Curadoria manual depois.

Regras:
  - Todo path produzido pelo endpoint precisa estar declarado aqui.
  - Decisão obrigatória: RENDERED (mostra no digest) ou SKIPPED (não mostra; razão obrigatória).
  - Se o endpoint adicionar campo novo sem declaração, audit_payload_schema() falha alto.
"""
from __future__ import annotations
from enum import Enum


class FieldDecision(Enum):
    RENDERED = 'rendered'
    SKIPPED  = 'skipped'


R = FieldDecision.RENDERED
S = FieldDecision.SKIPPED


# Cada entrada: (decisão, razão|None)
#   - razão é OBRIGATÓRIA pra SKIPPED
#   - razão é None pra RENDERED
#
# Bootstrap: todos os paths começam RENDERED. Cure movendo pra SKIPPED conforme
# revisar o output do digest e identificar o que é ruído.
PAYLOAD_SCHEMA: dict[str, tuple[FieldDecision, str | None]] = {

    # ──────────────────────────────────────────────────────────────────────────
    # ACTIONABLE_ALERTS
    # ──────────────────────────────────────────────────────────────────────────
    'actionable_alerts':                                                                (R, None),  # ex: list(3)
    'actionable_alerts[].category':                                                     (S, 'redundante; vai implícito no formato curto'),
    'actionable_alerts[].column':                                                       (S, 'embutido na mensagem'),
    'actionable_alerts[].message':                                                      (R, None),  # ex: "[champion_jan30] Medium: 3 mudança(s) significativa(s) nas …
    'actionable_alerts[].percentage':                                                   (S, 'detalhe técnico; rendero só mensagem curta'),
    'actionable_alerts[].severity':                                                     (R, None),  # ex: 'HIGH'
    'actionable_alerts[].type':                                                         (R, None),  # ex: 'distribution_drift'

    # ──────────────────────────────────────────────────────────────────────────
    # ALERTS
    # ──────────────────────────────────────────────────────────────────────────
    'alerts':                                                                           (R, None),  # ex: list(7)
    'alerts[].category':                                                                (S, 'redundante com tipo do alert'),
    'alerts[].details':                                                                 (R, None),  # ex: dict(4)
    'alerts[].details.affected_count':                                                  (R, None),  # ex: None
    'alerts[].details.changes':                                                         (R, None),  # ex: list(3)
    'alerts[].details.changes[].categoria':                                             (R, None),  # ex: 'aberto'
    'alerts[].details.changes[].diff':                                                  (S, 'computamos de producao - treino na renderização'),
    'alerts[].details.changes[].producao':                                              (R, None),  # ex: 0.7752120640904807
    'alerts[].details.changes[].treino':                                                (R, None),  # ex: 0.14457314065440197
    'alerts[].details.column':                                                          (R, None),  # ex: 'Medium'
    'alerts[].details.compared_window':                                                 (S, 'header line removido'),
    'alerts[].details.compared_window_kind':                                            (S, 'header line removido'),
    'alerts[].details.day_n_responses':                                                 (S, 'header line removido'),
    'alerts[].details.extra_count':                                                     (S, 'alert type não é renderizado'),
    'alerts[].details.extra_features':                                                  (S, 'alert type extra_unexpected_features não é renderizado (redundante com category_drift social)'),
    'alerts[].details.launch_cap_end':                                                  (S, 'header line removido'),
    'alerts[].details.launch_cap_start':                                                (S, 'header line removido'),
    'alerts[].details.launch_lf_name':                                                  (S, 'header line removido'),
    'alerts[].details.launch_n_responses':                                              (S, 'header line removido'),
    'alerts[].details.launch_window':                                                   (S, 'header line removido; valores ficam só na tabela'),
    'alerts[].details.mlflow_run_id':                                                   (S, 'ruído visual nos blocos de drift'),
    'alerts[].details.new_categories':                                                  (R, None),  # ex: None
    'alerts[].details.percentage':                                                      (R, None),  # ex: None
    'alerts[].details.reference_pool_label':                                            (S, 'descrição vai no título da seção'),
    'alerts[].details.reference_pool_n':                                                (S, 'header line removido'),
    'alerts[].details.today_n_responses':                                               (S, 'header line removido'),
    'alerts[].details.today_window':                                                    (S, 'header line removido'),
    'alerts[].details.top_count':                                                       (R, None),  # ex: None
    'alerts[].details.top_list':                                                        (R, None),  # ex: None
    'alerts[].details.top_list[].category':                                             (R, None),  # ex: None
    'alerts[].details.top_list[].day_pct':                                              (R, None),  # ex: None
    'alerts[].details.top_list[].delta_pp':                                             (R, None),  # ex: None
    'alerts[].details.top_list[].feature_column':                                       (R, None),  # ex: None
    'alerts[].details.top_list[].feature_label':                                        (R, None),  # ex: None
    'alerts[].details.top_list[].is_critical':                                          (R, None),  # ex: None
    'alerts[].details.top_list[].launch_delta_pp':                                      (R, None),  # ex: None
    'alerts[].details.top_list[].launch_pct':                                           (R, None),  # ex: None
    'alerts[].details.top_list[].reference_pct':                                        (R, None),  # ex: None
    'alerts[].details.top_list[].today_delta_pp':                                       (R, None),  # ex: None
    'alerts[].details.top_list[].today_pct':                                            (R, None),  # ex: None
    'alerts[].details.top_threshold_pp':                                                (S, 'header line removido'),
    'alerts[].details.total_expected_union':                                            (R, None),  # ex: None
    'alerts[].details.total_received_union':                                            (R, None),  # ex: None
    'alerts[].details.variant_name':                                                    (R, None),  # ex: 'champion_jan30'
    'alerts[].details.variants_checked':                                                (S, 'alert type não é renderizado'),
    'alerts[].message':                                                                 (R, None),  # ex: "[champion_jan30] Medium: 3 mudança(s) significativa(s) nas …
    'alerts[].metric_value':                                                            (S, 'detalhe técnico, não pro relatório'),
    'alerts[].severity':                                                                (R, None),  # ex: 'HIGH'
    'alerts[].threshold':                                                               (S, 'detalhe técnico, não pro relatório'),
    'alerts[].timestamp':                                                               (S, 'redundante com timestamp top-level'),
    'alerts[].type':                                                                    (R, None),  # ex: 'distribution_drift'

    # ──────────────────────────────────────────────────────────────────────────
    # ALERTS_BY_CATEGORY
    # ──────────────────────────────────────────────────────────────────────────
    'alerts_by_category':                                                               (S, 'irrelevante pra leitura'),
    'alerts_by_category.capi_quality':                                                  (S, 'irrelevante'),
    'alerts_by_category.data_quality':                                                  (S, 'irrelevante'),
    'alerts_by_category.operational':                                                   (S, 'irrelevante'),

    # ──────────────────────────────────────────────────────────────────────────
    # ALERTS_BY_SEVERITY
    # ──────────────────────────────────────────────────────────────────────────
    'alerts_by_severity':                                                               (S, 'redundante'),
    'alerts_by_severity.HIGH':                                                          (S, 'redundante'),
    'alerts_by_severity.LOW':                                                           (S, 'redundante'),
    'alerts_by_severity.MEDIUM':                                                        (S, 'redundante'),

    # ──────────────────────────────────────────────────────────────────────────
    # CRITICAL_SUMMARY
    # ──────────────────────────────────────────────────────────────────────────
    'critical_summary':                                                                 (S, 'texto cru — substituído por blocos estruturados'),

    # ──────────────────────────────────────────────────────────────────────────
    # FUNNEL_METRICS
    # ──────────────────────────────────────────────────────────────────────────
    'funnel_metrics':                                                                   (R, None),  # ex: dict(7)
    'funnel_metrics.capi_sent':                                                         (R, None),  # ex: dict(3)
    'funnel_metrics.capi_sent.estimated_events':                                        (R, None),  # ex: 2472
    'funnel_metrics.capi_sent.leads_sent':                                              (R, None),  # ex: 1902
    'funnel_metrics.capi_sent.send_rate':                                               (R, None),  # ex: 89.54802259887006
    'funnel_metrics.capture':                                                           (R, None),  # ex: dict(2)
    'funnel_metrics.capture.total_database':                                            (R, None),  # ex: 2124
    'funnel_metrics.capture.total_scored':                                              (S, 'duplicate de funnel_metrics.scoring.total_scored'),
    'funnel_metrics.conversion':                                                        (S, 'redundante com survey_funnel_metrics'),
    'funnel_metrics.conversion.survey_rate':                                            (S, 'redundante'),
    'funnel_metrics.conversion.total_with_survey':                                      (S, 'redundante'),
    'funnel_metrics.data_quality':                                                      (R, None),  # ex: dict(7)
    'funnel_metrics.data_quality.fbc_percentage':                                       (R, None),  # ex: 81.73258003766477
    'funnel_metrics.data_quality.fbc_present':                                          (S, 'rendero só percentage'),
    'funnel_metrics.data_quality.fbp_percentage':                                       (R, None),  # ex: 82.86252354048965
    'funnel_metrics.data_quality.fbp_present':                                          (S, 'rendero só percentage'),
    'funnel_metrics.data_quality.total_meta_leads':                                     (R, None),  # leads Meta na janela (denominador correto de FBP/FBC)
    'funnel_metrics.data_quality.phone_percentage':                                     (R, None),  # ex: 100.0
    'funnel_metrics.data_quality.phone_present':                                        (S, 'rendero só percentage'),
    'funnel_metrics.data_quality.total_leads':                                          (S, 'rendero só percentage'),
    'funnel_metrics.meta_response':                                                     (R, None),  # ex: dict(7)
    'funnel_metrics.meta_response.acceptance_rate':                                     (R, None),  # ex: 100.0
    'funnel_metrics.meta_response.error_count':                                         (R, None),  # ex: 0
    'funnel_metrics.meta_response.events_received':                                     (S, 'campo zerado, sem sinal'),
    'funnel_metrics.meta_response.events_rejected':                                     (S, 'campo zerado, sem sinal'),
    'funnel_metrics.meta_response.leads_with_response':                                 (S, 'redundante com success_count'),
    'funnel_metrics.meta_response.partial_count':                                       (R, None),  # ex: 0
    'funnel_metrics.meta_response.success_count':                                       (R, None),  # ex: 1902
    'funnel_metrics.scoring':                                                           (R, None),  # ex: dict(3)
    'funnel_metrics.scoring.avg_score':                                                 (R, None),  # ex: 0.42229626632184114
    'funnel_metrics.scoring.decil_distribution':                                        (R, None),  # ex: dict(10)
    'funnel_metrics.scoring.decil_distribution.D01':                                    (R, None),  # ex: 67
    'funnel_metrics.scoring.decil_distribution.D02':                                    (R, None),  # ex: 58
    'funnel_metrics.scoring.decil_distribution.D03':                                    (R, None),  # ex: 41
    'funnel_metrics.scoring.decil_distribution.D04':                                    (R, None),  # ex: 70
    'funnel_metrics.scoring.decil_distribution.D05':                                    (R, None),  # ex: 93
    'funnel_metrics.scoring.decil_distribution.D06':                                    (R, None),  # ex: 164
    'funnel_metrics.scoring.decil_distribution.D07':                                    (R, None),  # ex: 226
    'funnel_metrics.scoring.decil_distribution.D08':                                    (R, None),  # ex: 259
    'funnel_metrics.scoring.decil_distribution.D09':                                    (R, None),  # ex: 300
    'funnel_metrics.scoring.decil_distribution.D10':                                    (R, None),  # ex: 844
    'funnel_metrics.scoring.total_scored':                                              (R, None),  # ex: 2122
    'funnel_metrics.window':                                                            (R, None),  # ex: dict(4)
    'funnel_metrics.window.end_brt':                                                    (R, None),  # ex: '12/05/2026 09:29'
    'funnel_metrics.window.end_utc':                                                    (S, 'usamos BRT'),
    'funnel_metrics.window.start_brt':                                                  (R, None),  # ex: '09/05/2026 09:29'
    'funnel_metrics.window.start_utc':                                                  (S, 'usamos BRT'),

    # ──────────────────────────────────────────────────────────────────────────
    # LEAD_QUALITY_METRICS
    # ──────────────────────────────────────────────────────────────────────────
    'lead_quality_metrics':                                                             (R, None),  # ex: dict(4)
    'lead_quality_metrics.historico':                                                   (R, None),  # ex: dict(4)
    'lead_quality_metrics.historico.count':                                             (R, None),  # ex: 140989
    'lead_quality_metrics.historico.d10':                                               (R, None),  # ex: 30.559830908794304
    'lead_quality_metrics.historico.d9':                                                (R, None),  # ex: 12.419408606345176
    'lead_quality_metrics.historico.score':                                             (R, None),  # ex: 0.3722399594597989
    'lead_quality_metrics.ultima_semana':                                               (R, None),  # ex: dict(4)
    'lead_quality_metrics.ultima_semana.count':                                         (R, None),  # ex: 5668
    'lead_quality_metrics.ultima_semana.d10':                                           (R, None),  # ex: 36.53846153846153
    'lead_quality_metrics.ultima_semana.d9':                                            (R, None),  # ex: 13.214537755822159
    'lead_quality_metrics.ultima_semana.score':                                         (R, None),  # ex: 0.40532260969871026
    'lead_quality_metrics.ultimas_24h':                                                 (R, None),  # ex: dict(4)
    'lead_quality_metrics.ultimas_24h.count':                                           (R, None),  # ex: 762
    'lead_quality_metrics.ultimas_24h.d10':                                             (R, None),  # ex: 39.76377952755906
    'lead_quality_metrics.ultimas_24h.d9':                                              (R, None),  # ex: 12.073490813648293
    'lead_quality_metrics.ultimas_24h.score':                                           (R, None),  # ex: 0.4195559754654827
    'lead_quality_metrics.ultimo_mes':                                                  (R, None),  # ex: dict(4)
    'lead_quality_metrics.ultimo_mes.count':                                            (R, None),  # ex: 46703
    'lead_quality_metrics.ultimo_mes.d10':                                              (R, None),  # ex: 33.899321242746716
    'lead_quality_metrics.ultimo_mes.d9':                                               (R, None),  # ex: 13.500203413056976
    'lead_quality_metrics.ultimo_mes.score':                                            (R, None),  # ex: 0.38199086355564005
    'lead_quality_metrics.lf_referencia':                                               (R, None),  # qualidade do LF ativo (ou mais recente terminado)
    'lead_quality_metrics.lf_referencia.score':                                         (R, None),
    'lead_quality_metrics.lf_referencia.d9':                                            (R, None),
    'lead_quality_metrics.lf_referencia.d10':                                           (R, None),
    'lead_quality_metrics.lf_referencia.count':                                         (R, None),
    'lead_quality_metrics.lf_referencia_label':                                         (R, None),  # ex: 'LF54'

    # ──────────────────────────────────────────────────────────────────────────
    # OPERATIONAL_ROUTINES
    # ──────────────────────────────────────────────────────────────────────────
    'operational_routines':                                                             (R, None),  # ex: dict(12)
    'operational_routines.ab_test_enabled':                                             (S, 'redundante — se há variants, está ligado'),
    'operational_routines.ab_variants':                                                 (R, None),  # ex: list(2)
    'operational_routines.ab_variants[].name':                                          (R, None),  # ex: 'champion_jan30'
    'operational_routines.ab_variants[].routing_active':                                (R, None),  # ex: False
    'operational_routines.ab_variants[].routing_desc':                                  (R, None),  # ex: 'default (não match)'
    'operational_routines.ab_variants[].run_id':                                        (S, 'ruído visual'),
    'operational_routines.active_model_yaml_path':                                      (S, 'debug interno, não pro relatório'),
    'operational_routines.active_run_id':                                               (S, 'redundante com lista de variants'),
    'operational_routines.capi_sent_24h':                                               (S, 'não renderizado standalone'),
    'operational_routines.cloud_run_revision':                                          (S, 'debug interno, não pro relatório'),
    'operational_routines.cloud_run_service':                                           (S, 'debug interno, não pro relatório'),
    'operational_routines.last_scored_at':                                              (S, 'debug interno'),
    'operational_routines.leads_received_24h':                                          (S, 'não renderizado standalone'),
    'operational_routines.leads_scored_24h':                                            (S, 'não renderizado; total computado de sum(variants)'),
    'operational_routines.leads_scored_by_variant_24h':                                 (R, None),  # ex: dict(2)
    'operational_routines.leads_scored_by_variant_24h.challenger_abr28':                (R, None),  # ex: 88
    'operational_routines.leads_scored_by_variant_24h.champion_jan30':                  (R, None),  # ex: 676
    'operational_routines.minutes_since_last_score':                                    (S, 'debug interno; último scoring não renderizado'),

    # ──────────────────────────────────────────────────────────────────────────
    # REVENUE_FORECAST
    # ──────────────────────────────────────────────────────────────────────────
    'revenue_forecast':                                                                 (R, None),  # ex: dict(6)
    'revenue_forecast.cenario_base':                                                    (R, None),  # ex: dict(7)
    'revenue_forecast.cenario_base.cartao_avista_liquido':                              (R, None),  # ex: 1216
    'revenue_forecast.cenario_base.faturamento':                                        (R, None),  # ex: 3748
    'revenue_forecast.cenario_base.faturamento_recebido':                               (R, None),  # ex: 1399
    'revenue_forecast.cenario_base.primeira_parcela_boleto':                            (R, None),  # ex: 183
    'revenue_forecast.cenario_base.vendas_guru':                                        (R, None),  # ex: 0.7
    'revenue_forecast.cenario_base.vendas_tmb':                                         (R, None),  # ex: 1.0
    'revenue_forecast.cenario_base.vendas_total':                                       (R, None),  # ex: 1.7
    'revenue_forecast.cenario_ml_aware':                                                (R, None),  # ex: dict(7)
    'revenue_forecast.cenario_ml_aware.cartao_avista_liquido':                          (R, None),  # ex: 1911
    'revenue_forecast.cenario_ml_aware.faturamento':                                    (R, None),  # ex: 5500
    'revenue_forecast.cenario_ml_aware.faturamento_recebido':                           (R, None),  # ex: 2168
    'revenue_forecast.cenario_ml_aware.primeira_parcela_boleto':                        (R, None),  # ex: 257
    'revenue_forecast.cenario_ml_aware.vendas_guru':                                    (R, None),  # ex: 1.1
    'revenue_forecast.cenario_ml_aware.vendas_tmb':                                     (R, None),  # ex: 1.4
    'revenue_forecast.cenario_ml_aware.vendas_total':                                   (R, None),  # ex: 2.5
    'revenue_forecast.cenario_ml_aware_pessimista':                                     (R, None),
    'revenue_forecast.cenario_ml_aware_pessimista.cartao_avista_liquido':               (R, None),
    'revenue_forecast.cenario_ml_aware_pessimista.faturamento':                         (R, None),
    'revenue_forecast.cenario_ml_aware_pessimista.faturamento_recebido':                (R, None),
    'revenue_forecast.cenario_ml_aware_pessimista.primeira_parcela_boleto':             (R, None),
    'revenue_forecast.cenario_ml_aware_pessimista.vendas_guru':                         (R, None),
    'revenue_forecast.cenario_ml_aware_pessimista.vendas_tmb':                          (R, None),
    'revenue_forecast.cenario_ml_aware_pessimista.vendas_total':                        (R, None),
    'revenue_forecast.cenario_ml_aware_otimista':                                       (R, None),
    'revenue_forecast.cenario_ml_aware_otimista.cartao_avista_liquido':                 (R, None),
    'revenue_forecast.cenario_ml_aware_otimista.faturamento':                           (R, None),
    'revenue_forecast.cenario_ml_aware_otimista.faturamento_recebido':                  (R, None),
    'revenue_forecast.cenario_ml_aware_otimista.primeira_parcela_boleto':               (R, None),
    'revenue_forecast.cenario_ml_aware_otimista.vendas_guru':                           (R, None),
    'revenue_forecast.cenario_ml_aware_otimista.vendas_tmb':                            (R, None),
    'revenue_forecast.cenario_ml_aware_otimista.vendas_total':                          (R, None),
    'revenue_forecast.cenario_otimista':                                                (R, None),  # ex: dict(7)
    'revenue_forecast.cenario_otimista.cartao_avista_liquido':                          (R, None),  # ex: 1390
    'revenue_forecast.cenario_otimista.faturamento':                                    (R, None),  # ex: 3935
    'revenue_forecast.cenario_otimista.faturamento_recebido':                           (R, None),  # ex: 1573
    'revenue_forecast.cenario_otimista.primeira_parcela_boleto':                        (R, None),  # ex: 183
    'revenue_forecast.cenario_otimista.vendas_guru':                                    (R, None),  # ex: 0.8
    'revenue_forecast.cenario_otimista.vendas_tmb':                                     (R, None),  # ex: 1.0
    'revenue_forecast.cenario_otimista.vendas_total':                                   (R, None),  # ex: 1.8
    'revenue_forecast.cenario_pessimista':                                              (R, None),  # ex: dict(7)
    'revenue_forecast.cenario_pessimista.cartao_avista_liquido':                        (R, None),  # ex: 1216
    'revenue_forecast.cenario_pessimista.faturamento':                                  (R, None),  # ex: 3560
    'revenue_forecast.cenario_pessimista.faturamento_recebido':                         (R, None),  # ex: 1381
    'revenue_forecast.cenario_pessimista.primeira_parcela_boleto':                      (R, None),  # ex: 165
    'revenue_forecast.cenario_pessimista.vendas_guru':                                  (R, None),  # ex: 0.7
    'revenue_forecast.cenario_pessimista.vendas_tmb':                                   (R, None),  # ex: 0.9
    'revenue_forecast.cenario_pessimista.vendas_total':                                 (R, None),  # ex: 1.6
    'revenue_forecast.expected_conversion':                                             (S, 'redundante com cenário ML-aware'),
    'revenue_forecast.expected_conversion.compradores_esperados':                       (S, 'integrado ao cenário ML-aware'),
    'revenue_forecast.expected_conversion.compradores_esperados.D10':                   (S, 'integrado ao cenário ML-aware'),
    'revenue_forecast.expected_conversion.compradores_esperados.D1_D5':                 (S, 'integrado ao cenário ML-aware'),
    'revenue_forecast.expected_conversion.compradores_esperados.D6_D9':                 (S, 'integrado ao cenário ML-aware'),
    'revenue_forecast.expected_conversion.compradores_esperados.taxa_media_corrigida':  (S, 'detalhes da metodologia'),
    'revenue_forecast.expected_conversion.compradores_esperados.total':                 (S, 'integrado ao cenário ML-aware'),
    'revenue_forecast.expected_conversion.distribuicao_leads':                          (S, 'redundante com cenário ML-aware'),
    'revenue_forecast.expected_conversion.distribuicao_leads.D10':                      (S, 'redundante'),
    'revenue_forecast.expected_conversion.distribuicao_leads.D10.leads':                (S, 'redundante'),
    'revenue_forecast.expected_conversion.distribuicao_leads.D10.pct':                  (S, 'redundante'),
    'revenue_forecast.expected_conversion.distribuicao_leads.D1_D5':                    (S, 'redundante'),
    'revenue_forecast.expected_conversion.distribuicao_leads.D1_D5.leads':              (S, 'redundante'),
    'revenue_forecast.expected_conversion.distribuicao_leads.D1_D5.pct':                (S, 'redundante'),
    'revenue_forecast.expected_conversion.distribuicao_leads.D6_D9':                    (S, 'redundante'),
    'revenue_forecast.expected_conversion.distribuicao_leads.D6_D9.leads':              (S, 'redundante'),
    'revenue_forecast.expected_conversion.distribuicao_leads.D6_D9.pct':                (S, 'redundante'),
    'revenue_forecast.expected_conversion.distribuicao_leads.response_rate_pct':        (S, 'redundante'),
    'revenue_forecast.expected_conversion.distribuicao_leads.total_db':                 (S, 'redundante'),
    'revenue_forecast.expected_conversion.fonte':                                       (S, 'redundante com cenário ML-aware'),
    'revenue_forecast.expected_conversion.taxa_implicita_por_meta_lead':                (S, 'redundante'),
    'revenue_forecast.expected_conversion.taxas_corrigidas':                            (S, 'detalhes da metodologia'),
    'revenue_forecast.expected_conversion.taxas_corrigidas.D10':                        (S, 'detalhes da metodologia'),
    'revenue_forecast.expected_conversion.taxas_corrigidas.D1_D5':                      (S, 'detalhes da metodologia'),
    'revenue_forecast.expected_conversion.taxas_corrigidas.D6_D9':                      (S, 'detalhes da metodologia'),
    'revenue_forecast.expected_conversion.taxas_corrigidas.tracking_rate_aplicado':     (S, 'detalhes da metodologia'),
    'revenue_forecast.inputs':                                                          (R, None),  # ex: dict(10)
    'revenue_forecast.inputs.conv_rastr_mediana':                                       (S, 'detalhes da metodologia no payload da API'),
    'revenue_forecast.inputs.fonte_flat_rate':                                          (S, 'detalhes da metodologia no payload da API'),
    'revenue_forecast.inputs.fonte_ml_aware':                                           (S, 'detalhes da metodologia no payload da API'),
    'revenue_forecast.inputs.launch_window_start_brt':                                  (R, None),  # ex: '12/05/2026'
    'revenue_forecast.inputs.metodologia':                                              (R, None),  # ex: 'flat-rate LF43-LF53 (recalibrado 08/05)'
    'revenue_forecast.inputs.pct_cartao_historico':                                     (S, 'detalhes da metodologia no payload da API'),
    'revenue_forecast.inputs.taxa_real_implicita':                                      (S, 'detalhes da metodologia no payload da API'),
    'revenue_forecast.inputs.ticket_contracted':                                        (R, None),  # ex: 2200.0
    'revenue_forecast.inputs.total_leads_meta':                                         (R, None),  # ex: 165
    'revenue_forecast.inputs.tracking_rate_usado':                                      (S, 'detalhes da metodologia no payload da API'),

    # ──────────────────────────────────────────────────────────────────────────
    # SURVEY_FUNNEL_METRICS
    # ──────────────────────────────────────────────────────────────────────────
    'survey_funnel_metrics':                                                            (R, None),  # ex: dict(5)
    'survey_funnel_metrics.historico':                                                  (R, None),  # ex: dict(5)
    'survey_funnel_metrics.historico.capi_rate':                                        (R, None),  # ex: 95.7
    'survey_funnel_metrics.historico.capi_sent':                                        (R, None),  # ex: 134891
    'survey_funnel_metrics.historico.db_leads':                                         (R, None),  # ex: 140991
    'survey_funnel_metrics.historico.meta_leads':                                       (R, None),  # ex: None
    'survey_funnel_metrics.historico.response_rate':                                    (R, None),  # ex: None
    'survey_funnel_metrics.periodo_query':                                              (R, None),  # ex: dict(5)
    'survey_funnel_metrics.periodo_query.capi_rate':                                    (R, None),  # ex: 89.5
    'survey_funnel_metrics.periodo_query.capi_sent':                                    (R, None),  # ex: 1902
    'survey_funnel_metrics.periodo_query.db_leads':                                     (R, None),  # ex: 2124
    'survey_funnel_metrics.periodo_query.meta_leads':                                   (R, None),  # ex: 165
    'survey_funnel_metrics.periodo_query.response_rate':                                (R, None),  # ex: 1287.3
    'survey_funnel_metrics.ultima_semana':                                              (R, None),  # ex: dict(5)
    'survey_funnel_metrics.ultima_semana.capi_rate':                                    (R, None),  # ex: 84.0
    'survey_funnel_metrics.ultima_semana.capi_sent':                                    (R, None),  # ex: 4765
    'survey_funnel_metrics.ultima_semana.db_leads':                                     (R, None),  # ex: 5670
    'survey_funnel_metrics.ultima_semana.meta_leads':                                   (R, None),  # ex: 5536
    'survey_funnel_metrics.ultima_semana.response_rate':                                (R, None),  # ex: 102.4
    'survey_funnel_metrics.ultimas_24h':                                                (R, None),  # ex: dict(5)
    'survey_funnel_metrics.ultimas_24h.capi_rate':                                      (R, None),  # ex: 85.5
    'survey_funnel_metrics.ultimas_24h.capi_sent':                                      (R, None),  # ex: 653
    'survey_funnel_metrics.ultimas_24h.db_leads':                                       (R, None),  # ex: 764
    'survey_funnel_metrics.ultimas_24h.meta_leads':                                     (R, None),  # ex: 918
    'survey_funnel_metrics.ultimas_24h.response_rate':                                  (R, None),  # ex: 83.2
    'survey_funnel_metrics.ultimo_mes':                                                 (R, None),  # ex: dict(5)
    'survey_funnel_metrics.ultimo_mes.capi_rate':                                       (R, None),  # ex: 89.5
    'survey_funnel_metrics.ultimo_mes.capi_sent':                                       (R, None),  # ex: 41814
    'survey_funnel_metrics.ultimo_mes.db_leads':                                        (R, None),  # ex: 46705
    'survey_funnel_metrics.ultimo_mes.meta_leads':                                      (R, None),  # ex: 58805
    'survey_funnel_metrics.ultimo_mes.response_rate':                                   (R, None),  # ex: 79.4

    # ──────────────────────────────────────────────────────────────────────────
    # TIMESTAMP
    # ──────────────────────────────────────────────────────────────────────────
    'timestamp':                                                                        (S, 'data fica no título; não pro corpo'),

    # ──────────────────────────────────────────────────────────────────────────
    # TOTAL_ALERTS
    # ──────────────────────────────────────────────────────────────────────────
    'total_alerts':                                                                     (S, 'redundante com lista de alertas'),

    # ──────────────────────────────────────────────────────────────────────────
    # TRAFFIC_METRICS
    # ──────────────────────────────────────────────────────────────────────────
    'traffic_metrics':                                                                  (R, None),  # ex: dict(4)
    'traffic_metrics.periodo_query':                                                    (R, None),  # ex: dict(5)
    'traffic_metrics.periodo_query.clicks':                                             (R, None),  # ex: 836
    'traffic_metrics.periodo_query.cpl':                                                (R, None),  # ex: 7.97
    'traffic_metrics.periodo_query.ctr_lead':                                           (R, None),  # ex: 19.7
    'traffic_metrics.periodo_query.meta_leads':                                         (R, None),  # ex: 165
    'traffic_metrics.periodo_query.spend':                                              (R, None),  # ex: 1315.65
    'traffic_metrics.ultima_semana':                                                    (R, None),  # ex: dict(5)
    'traffic_metrics.ultima_semana.clicks':                                             (R, None),  # ex: 26625
    'traffic_metrics.ultima_semana.cpl':                                                (R, None),  # ex: 7.31
    'traffic_metrics.ultima_semana.ctr_lead':                                           (R, None),  # ex: 20.8
    'traffic_metrics.ultima_semana.meta_leads':                                         (R, None),  # ex: 5536
    'traffic_metrics.ultima_semana.spend':                                              (R, None),  # ex: 40471.02
    'traffic_metrics.ultimas_24h':                                                      (R, None),  # ex: dict(5)
    'traffic_metrics.ultimas_24h.clicks':                                               (R, None),  # ex: 4051
    'traffic_metrics.ultimas_24h.cpl':                                                  (R, None),  # ex: 6.79
    'traffic_metrics.ultimas_24h.ctr_lead':                                             (R, None),  # ex: 22.7
    'traffic_metrics.ultimas_24h.meta_leads':                                           (R, None),  # ex: 918
    'traffic_metrics.ultimas_24h.spend':                                                (R, None),  # ex: 6228.81
    'traffic_metrics.ultimo_mes':                                                       (R, None),  # ex: dict(5)
    'traffic_metrics.ultimo_mes.clicks':                                                (R, None),  # ex: 238846
    'traffic_metrics.ultimo_mes.cpl':                                                   (R, None),  # ex: 5.46
    'traffic_metrics.ultimo_mes.ctr_lead':                                              (R, None),  # ex: 24.6
    'traffic_metrics.ultimo_mes.meta_leads':                                            (R, None),  # ex: 58805
    'traffic_metrics.ultimo_mes.spend':                                                 (R, None),  # ex: 321316.24
}
