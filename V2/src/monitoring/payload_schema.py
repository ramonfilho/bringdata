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
    'alerts[].details.missing_count':                                                   (R, None),  # ex: 234 — n de leads c/ campo nulo no missing_rate_high
    'alerts[].details.missing_rate':                                                    (R, None),  # ex: 0.85 — proporção 0–1
    'alerts[].details.total_rows':                                                      (R, None),  # ex: 276 — total avaliado no missing_rate_high
    'alerts[].details.total_leads':                                                     (R, None),  # ex: 325 — total na janela de score_distribution_change
    'alerts[].details.baseline_source':                                                 (R, None),  # ex: 'rolling_30d' — origem do baseline (rolling x treino)
    'alerts[].details.changes[].decil':                                                 (R, None),  # ex: 'D10' — decil afetado em score_distribution_change
    'alerts[].details.changes[].atual':                                                 (R, None),  # ex: 0.246 — pct atual no decil
    'alerts[].details.changes[].esperado':                                              (R, None),  # ex: 0.349 — pct esperado no baseline
    'alerts[].details.changes':                                                         (R, None),  # ex: list(3)
    'alerts[].details.changes[].categoria':                                             (R, None),  # ex: 'aberto'
    'alerts[].details.changes[].diff':                                                  (S, 'computamos de producao - treino na renderização'),
    'alerts[].details.changes[].producao':                                              (R, None),  # ex: 0.7752120640904807
    'alerts[].details.changes[].treino':                                                (R, None),  # ex: 0.14457314065440197
    'alerts[].details.changes[].outros_breakdown':                                      (R, None),  # ex: list — decomposição da categoria "Outros" em valores raw com contagens
    'alerts[].details.changes[].outros_breakdown[].count':                              (R, None),  # ex: int
    'alerts[].details.changes[].outros_breakdown[].raw_value':                          (R, None),  # ex: str — valor canônico que caiu em "Outros"
    'alerts[].details.n_silenced':                                                      (R, None),  # ex: int — quantas categorias do diff foram silenciadas (renderer lê em digest.py:392, 831)
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
    'alerts[].details.top_list[].prev_day_pct':                                         (R, None),  # ex: None — D-2 full BRT day (anteontem)
    'alerts[].details.top_list[].prev_day_delta_pp':                                    (R, None),  # ex: None
    'alerts[].details.top_list[].direction':                                            (R, None),  # ex: 'positive' | 'negative' | 'neutral' | 'uncertain' | 'insufficient_data' | None — vem do audience_direction_map.json (ver docs/METODOLOGIA_TOP5_ROAS.md)
    'alerts[].details.top_list[].day_quality':                                          (R, None),  # ex: 'bom' | 'ruim' | 'neutro' — direction × sign(delta_pp)
    'alerts[].details.top_list[].launch_quality':                                       (R, None),  # ex: 'bom' | 'ruim' | 'neutro' | None
    'alerts[].details.prev_day_n_responses':                                            (S, 'header line removido'),
    'alerts[].details.top_threshold_pp':                                                (S, 'header line removido'),
    # audience_profile_drift_by_variant — split por Champion/Challenger (alert novo)
    'alerts[].details.window':                                                          (S, 'usado no título da seção, não renderizado standalone'),
    'alerts[].details.window_label':                                                    (S, 'título da seção'),
    'alerts[].details.champion_name':                                                   (S, 'usado em label da coluna; não renderizado standalone'),
    'alerts[].details.challenger_name':                                                 (S, 'usado em label da coluna; não renderizado standalone'),
    'alerts[].details.champion_n':                                                      (R, None),  # ex: 640
    'alerts[].details.challenger_n':                                                    (R, None),  # ex: 95
    'alerts[].details.top_list[].champion_pct':                                         (R, None),  # ex: None
    'alerts[].details.top_list[].champion_delta_pp':                                    (R, None),  # ex: None
    'alerts[].details.top_list[].champion_quality':                                     (R, None),  # ex: 'bom' | 'ruim' | 'neutro' | None
    'alerts[].details.top_list[].challenger_pct':                                       (R, None),  # ex: None
    'alerts[].details.top_list[].challenger_delta_pp':                                  (R, None),  # ex: None
    'alerts[].details.top_list[].challenger_quality':                                   (R, None),  # ex: 'bom' | 'ruim' | 'neutro' | None
    # Coluna Lead — dimensão ortogonal ao A/B model split (campaign optimization_goal = Lead padrão)
    'alerts[].details.lead_n':                                                          (R, None),  # ex: 487
    'alerts[].details.top_list[].lead_pct':                                             (R, None),
    'alerts[].details.top_list[].lead_delta_pp':                                        (R, None),
    'alerts[].details.top_list[].lead_quality':                                         (R, None),
    'alerts[].details.top_list[].winner':                                               (R, None),  # ex: 'champion' | 'challenger' | None
    # audience_profile_drift_by_source — split por fonte (Meta / Google)
    'alerts[].details.meta_n':                                                          (R, None),  # ex: 1095
    'alerts[].details.google_n':                                                        (R, None),  # ex: 71
    # outros_n — exposto pelo alerta by_variant (header) pra leads sem Meta nem Google
    # (orgânico, tiktok pré-allowlist, sem source, etc.). Não entra nas colunas Δ.
    'alerts[].details.outros_n':                                                        (R, None),  # ex: 13
    'alerts[].details.top_list[].meta_pct':                                             (R, None),  # ex: None
    'alerts[].details.top_list[].meta_delta_pp':                                        (R, None),  # ex: None
    'alerts[].details.top_list[].meta_quality':                                         (R, None),  # ex: 'bom' | 'ruim' | 'neutro' | None
    'alerts[].details.top_list[].google_pct':                                           (R, None),  # ex: None
    'alerts[].details.top_list[].google_delta_pp':                                      (R, None),  # ex: None
    'alerts[].details.top_list[].google_quality':                                       (R, None),  # ex: 'bom' | 'ruim' | 'neutro' | None
    'alerts[].details.total_expected_union':                                            (R, None),  # ex: None
    'alerts[].details.total_received_union':                                            (R, None),  # ex: None
    'alerts[].details.variant_name':                                                    (R, None),  # ex: 'champion_jan30'
    # audience_quality_signal — sinal de qualidade vs baseline (terminal paralelo "Outros")
    'alerts[].details.baseline':                                                        (R, None),
    'alerts[].details.baseline.pct_d10':                                                (R, None),
    'alerts[].details.baseline.pct_d8_d10':                                             (R, None),
    'alerts[].details.baseline.pct_d9_d10':                                             (R, None),
    'alerts[].details.baseline.score_mean':                                             (R, None),
    'alerts[].details.baseline_n_leads':                                                (R, None),
    'alerts[].details.baseline_pool_label':                                             (R, None),
    'alerts[].details.cap_start':                                                       (R, None),
    'alerts[].details.cap_end':                                                         (R, None),
    'alerts[].details.current':                                                         (R, None),
    'alerts[].details.current.pct_d10':                                                 (R, None),
    'alerts[].details.current.pct_d8_d10':                                              (R, None),
    'alerts[].details.current.pct_d9_d10':                                              (R, None),
    'alerts[].details.current.score_mean':                                              (R, None),
    'alerts[].details.delta':                                                           (R, None),
    'alerts[].details.delta.pct_d10_pp':                                                (R, None),
    'alerts[].details.delta.pct_d8_d10_pp':                                             (R, None),
    'alerts[].details.delta.pct_d9_d10_pp':                                             (R, None),
    'alerts[].details.delta.score_pct':                                                 (R, None),
    'alerts[].details.lf_name':                                                         (R, None),
    'alerts[].details.n_leads_launch':                                                  (R, None),
    'alerts[].details.model':                                                           (R, None),
    'alerts[].details.model.label':                                                     (R, None),
    'alerts[].details.model.rationale':                                                 (R, None),
    'alerts[].details.model.run_id':                                                    (R, None),
    'alerts[].details.model.trained_at':                                                (R, None),
    'alerts[].details.sinal':                                                           (R, None),
    # outros_bucket_inflated — details breakdown (terminal paralelo "Outros")
    'alerts[].details.breakdown':                                                       (R, None),
    'alerts[].details.breakdown[].count':                                               (R, None),
    'alerts[].details.breakdown[].pct_total':                                           (R, None),
    'alerts[].details.breakdown[].raw_value':                                           (R, None),
    'alerts[].details.min_pct_threshold':                                               (R, None),
    'alerts[].details.outros_count':                                                    (R, None),
    'alerts[].details.outros_pct_of_total':                                             (R, None),
    'alerts[].details.restrict_to_sources':                                             (R, None),
    'alerts[].details.total_count':                                                     (R, None),
    'alerts[].details.window_hours':                                                    (R, None),
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
    'funnel_metrics.conversion':                                                        (S, 'trivial — Railway só registra Lead com pesquisa preenchida, survey_rate é 100% por construção'),
    'funnel_metrics.conversion.survey_rate':                                            (S, 'trivial — sempre 100% (vide funnel_metrics.conversion)'),
    'funnel_metrics.conversion.total_with_survey':                                      (S, 'igual a funnel_metrics.scoring.total_scored — Railway só registra Lead com pesquisa'),
    'funnel_metrics.data_quality':                                                      (R, None),  # ex: dict(7)
    'funnel_metrics.data_quality.fbc_percentage':                                       (R, None),  # ex: 81.73258003766477
    'funnel_metrics.data_quality.fbc_present':                                          (S, 'rendero só percentage'),
    'funnel_metrics.data_quality.fbp_percentage':                                       (R, None),  # ex: 82.86252354048965
    'funnel_metrics.data_quality.fbp_present':                                          (S, 'rendero só percentage'),
    'funnel_metrics.data_quality.total_meta_leads':                                     (R, None),  # leads Meta na janela (denominador correto de FBP/FBC)
    'funnel_metrics.data_quality.phone_percentage':                                     (R, None),  # ex: 100.0
    'funnel_metrics.data_quality.phone_present':                                        (S, 'rendero só percentage'),
    'funnel_metrics.data_quality.total_leads':                                          (S, 'rendero só percentage'),
    'funnel_metrics.data_quality.fbp_fbc_rolling':                                      (R, None),  # dict(3): janelas 1d/3d/7d
    'funnel_metrics.data_quality.fbp_fbc_rolling.1d':                                   (R, None),  # dict(3)
    'funnel_metrics.data_quality.fbp_fbc_rolling.1d.n':                                 (R, None),  # leads Meta na janela 1d
    'funnel_metrics.data_quality.fbp_fbc_rolling.1d.fbp_pct':                           (R, None),  # ex: 97.2
    'funnel_metrics.data_quality.fbp_fbc_rolling.1d.fbc_pct':                           (R, None),  # ex: 77.1
    'funnel_metrics.data_quality.fbp_fbc_rolling.3d':                                   (R, None),  # dict(3)
    'funnel_metrics.data_quality.fbp_fbc_rolling.3d.n':                                 (R, None),
    'funnel_metrics.data_quality.fbp_fbc_rolling.3d.fbp_pct':                           (R, None),
    'funnel_metrics.data_quality.fbp_fbc_rolling.3d.fbc_pct':                           (R, None),
    'funnel_metrics.data_quality.fbp_fbc_rolling.7d':                                   (R, None),  # dict(3)
    'funnel_metrics.data_quality.fbp_fbc_rolling.7d.n':                                 (R, None),
    'funnel_metrics.data_quality.fbp_fbc_rolling.7d.fbp_pct':                           (R, None),
    'funnel_metrics.data_quality.fbp_fbc_rolling.7d.fbc_pct':                           (R, None),
    'funnel_metrics.unified_funnel':                                                    (R, None),  # funil completo todas as fontes
    'funnel_metrics.unified_funnel.window':                                             (R, None),  # dict(2)
    'funnel_metrics.unified_funnel.window.date_brt':                                     (R, None),  # ex: '15/05'
    'funnel_metrics.unified_funnel.window.label':                                        (R, None),  # 'dia anterior'
    'funnel_metrics.unified_funnel.phone_pct':                                           (R, None),  # % com telefone (dia anterior)
    'funnel_metrics.unified_funnel.capture':                                            (R, None),  # dict(1)
    'funnel_metrics.unified_funnel.capture.leads_capi':                                 (R, None),  # leads_capi na janela (todas as fontes)
    'funnel_metrics.unified_funnel.pipeline':                                           (R, None),  # dict(4) etapas
    'funnel_metrics.unified_funnel.pipeline.pesquisa':                                  (R, None),  # dict(4): total/fb/ggl/outr
    'funnel_metrics.unified_funnel.pipeline.pesquisa.total':                            (R, None),
    'funnel_metrics.unified_funnel.pipeline.pesquisa.fb':                               (R, None),  # facebook-ads/ig/fb
    'funnel_metrics.unified_funnel.pipeline.pesquisa.ggl':                              (R, None),  # google-ads
    'funnel_metrics.unified_funnel.pipeline.pesquisa.outr':                             (R, None),  # demais fontes
    'funnel_metrics.unified_funnel.pipeline.scoreado':                                  (R, None),
    'funnel_metrics.unified_funnel.pipeline.scoreado.total':                            (R, None),
    'funnel_metrics.unified_funnel.pipeline.scoreado.fb':                               (R, None),
    'funnel_metrics.unified_funnel.pipeline.scoreado.ggl':                              (R, None),
    'funnel_metrics.unified_funnel.pipeline.scoreado.outr':                             (R, None),
    'funnel_metrics.unified_funnel.pipeline.capi_enviado':                              (R, None),
    'funnel_metrics.unified_funnel.pipeline.capi_enviado.total':                        (R, None),
    'funnel_metrics.unified_funnel.pipeline.capi_enviado.fb':                           (R, None),
    'funnel_metrics.unified_funnel.pipeline.capi_enviado.ggl':                          (R, None),
    'funnel_metrics.unified_funnel.pipeline.capi_enviado.outr':                         (R, None),
    'funnel_metrics.unified_funnel.pipeline.aceito':                                    (R, None),
    'funnel_metrics.unified_funnel.pipeline.aceito.total':                              (R, None),
    'funnel_metrics.unified_funnel.pipeline.aceito.fb':                                 (R, None),
    'funnel_metrics.unified_funnel.pipeline.aceito.ggl':                                (R, None),
    'funnel_metrics.unified_funnel.pipeline.aceito.outr':                               (R, None),
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
    # Distribuição de decis por janela — usado nas barras horizontais do digest cliente
    'lead_quality_metrics.decil_distribution_previous_day':                             (R, None),  # ex: dict(3)
    'lead_quality_metrics.decil_distribution_previous_day.distribution':                (R, None),  # ex: dict(10) D01..D10 counts
    'lead_quality_metrics.decil_distribution_previous_day.distribution.D01':            (R, None),  # ex: 81
    'lead_quality_metrics.decil_distribution_previous_day.distribution.D02':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.distribution.D03':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.distribution.D04':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.distribution.D05':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.distribution.D06':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.distribution.D07':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.distribution.D08':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.distribution.D09':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.distribution.D10':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.total':                       (R, None),  # ex: 735
    'lead_quality_metrics.decil_distribution_previous_day.window_label':                (R, None),  # ex: '12/05 BRT (24h)'
    'lead_quality_metrics.decil_distribution_previous_day.baseline':                    (R, None),  # ex: dict — Top 6 ROAS ponderado Champion/Challenger
    'lead_quality_metrics.decil_distribution_previous_day.baseline.pct':                (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline.pct.D01':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline.pct.D02':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline.pct.D03':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline.pct.D04':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline.pct.D05':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline.pct.D06':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline.pct.D07':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline.pct.D08':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline.pct.D09':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline.pct.D10':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline.n_champion':         (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline.n_challenger':       (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline.w_champion':         (S, 'derivado dos counts, não renderizado standalone'),
    'lead_quality_metrics.decil_distribution_previous_day.baseline.w_challenger':       (S, 'derivado dos counts, não renderizado standalone'),
    'lead_quality_metrics.decil_distribution_previous_day.baseline.label':              (R, None),
    # Baselines puras por variante — usadas pelo KPI panel pra comparar cada bucket
    # contra a régua dele (Lead/Champion/Google contra Champion; Challenger contra Challenger).
    # Bug corrigido 2026-05-29: antes só existia baseline ponderada, fazendo Challenger
    # bucket aparecer -31pp ruim mesmo estando dentro da própria régua.
    'lead_quality_metrics.decil_distribution_previous_day.baseline_champion':           (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_champion.pct':       (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_champion.pct.D01':   (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_champion.pct.D02':   (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_champion.pct.D03':   (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_champion.pct.D04':   (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_champion.pct.D05':   (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_champion.pct.D06':   (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_champion.pct.D07':   (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_champion.pct.D08':   (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_champion.pct.D09':   (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_champion.pct.D10':   (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_champion.n_leads':   (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_champion.label':     (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_challenger':         (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_challenger.pct':     (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_challenger.pct.D01': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_challenger.pct.D02': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_challenger.pct.D03': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_challenger.pct.D04': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_challenger.pct.D05': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_challenger.pct.D06': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_challenger.pct.D07': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_challenger.pct.D08': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_challenger.pct.D09': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_challenger.pct.D10': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_challenger.n_leads': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.baseline_challenger.label':   (R, None),
    # by_source — split por fonte (Meta vs Google) renderizado side-by-side ao lado do Total
    'lead_quality_metrics.decil_distribution_previous_day.by_source':                   (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.meta':              (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.meta.distribution': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.meta.distribution.D01': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.meta.distribution.D02': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.meta.distribution.D03': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.meta.distribution.D04': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.meta.distribution.D05': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.meta.distribution.D06': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.meta.distribution.D07': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.meta.distribution.D08': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.meta.distribution.D09': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.meta.distribution.D10': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.meta.total':        (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.google':            (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.google.distribution': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.google.distribution.D01': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.google.distribution.D02': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.google.distribution.D03': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.google.distribution.D04': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.google.distribution.D05': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.google.distribution.D06': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.google.distribution.D07': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.google.distribution.D08': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.google.distribution.D09': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.google.distribution.D10': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_source.google.total':      (R, None),
    # by_optgoal — 3 buckets excludentes (Lead/Champion/Challenger) por optimization_goal Meta
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal':                  (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.lead':             (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.lead.distribution': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.lead.distribution.D01': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.lead.distribution.D02': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.lead.distribution.D03': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.lead.distribution.D04': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.lead.distribution.D05': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.lead.distribution.D06': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.lead.distribution.D07': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.lead.distribution.D08': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.lead.distribution.D09': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.lead.distribution.D10': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.lead.total':       (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.champion':         (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.champion.distribution': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.champion.distribution.D01': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.champion.distribution.D02': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.champion.distribution.D03': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.champion.distribution.D04': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.champion.distribution.D05': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.champion.distribution.D06': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.champion.distribution.D07': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.champion.distribution.D08': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.champion.distribution.D09': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.champion.distribution.D10': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.champion.total':   (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.challenger':       (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.challenger.distribution': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.challenger.distribution.D01': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.challenger.distribution.D02': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.challenger.distribution.D03': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.challenger.distribution.D04': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.challenger.distribution.D05': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.challenger.distribution.D06': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.challenger.distribution.D07': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.challenger.distribution.D08': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.challenger.distribution.D09': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.challenger.distribution.D10': (R, None),
    'lead_quality_metrics.decil_distribution_previous_day.by_optgoal.challenger.total': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch':                           (R, None),  # ex: dict(3)
    'lead_quality_metrics.decil_distribution_current_launch.distribution':              (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.distribution.D01':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.distribution.D02':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.distribution.D03':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.distribution.D04':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.distribution.D05':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.distribution.D06':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.distribution.D07':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.distribution.D08':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.distribution.D09':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.distribution.D10':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.total':                     (R, None),  # ex: 5371
    'lead_quality_metrics.decil_distribution_current_launch.window_label':              (R, None),  # ex: 'LF54 (29/04→06/05 BRT)'
    'lead_quality_metrics.decil_distribution_current_launch.baseline':                  (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline.pct':              (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline.pct.D01':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline.pct.D02':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline.pct.D03':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline.pct.D04':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline.pct.D05':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline.pct.D06':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline.pct.D07':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline.pct.D08':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline.pct.D09':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline.pct.D10':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline.n_champion':       (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline.n_challenger':     (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline.w_champion':       (S, 'derivado dos counts, não renderizado standalone'),
    'lead_quality_metrics.decil_distribution_current_launch.baseline.w_challenger':     (S, 'derivado dos counts, não renderizado standalone'),
    'lead_quality_metrics.decil_distribution_current_launch.baseline.label':            (R, None),
    # Baselines puras por variante — ver comentário equivalente em decil_distribution_previous_day.
    'lead_quality_metrics.decil_distribution_current_launch.baseline_champion':           (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_champion.pct':       (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_champion.pct.D01':   (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_champion.pct.D02':   (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_champion.pct.D03':   (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_champion.pct.D04':   (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_champion.pct.D05':   (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_champion.pct.D06':   (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_champion.pct.D07':   (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_champion.pct.D08':   (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_champion.pct.D09':   (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_champion.pct.D10':   (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_champion.n_leads':   (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_champion.label':     (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_challenger':         (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_challenger.pct':     (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_challenger.pct.D01': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_challenger.pct.D02': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_challenger.pct.D03': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_challenger.pct.D04': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_challenger.pct.D05': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_challenger.pct.D06': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_challenger.pct.D07': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_challenger.pct.D08': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_challenger.pct.D09': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_challenger.pct.D10': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_challenger.n_leads': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.baseline_challenger.label':   (R, None),
    # by_source — split por fonte (Meta vs Google) renderizado side-by-side ao lado do Total
    'lead_quality_metrics.decil_distribution_current_launch.by_source':                 (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.meta':            (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.meta.distribution': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.meta.distribution.D01': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.meta.distribution.D02': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.meta.distribution.D03': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.meta.distribution.D04': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.meta.distribution.D05': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.meta.distribution.D06': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.meta.distribution.D07': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.meta.distribution.D08': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.meta.distribution.D09': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.meta.distribution.D10': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.meta.total':      (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.google':          (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.google.distribution': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.google.distribution.D01': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.google.distribution.D02': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.google.distribution.D03': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.google.distribution.D04': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.google.distribution.D05': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.google.distribution.D06': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.google.distribution.D07': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.google.distribution.D08': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.google.distribution.D09': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.google.distribution.D10': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_source.google.total':    (R, None),
    # by_optgoal — 3 buckets excludentes (Lead/Champion/Challenger) por optimization_goal Meta
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal':                (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.lead':           (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.lead.distribution': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.lead.distribution.D01': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.lead.distribution.D02': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.lead.distribution.D03': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.lead.distribution.D04': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.lead.distribution.D05': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.lead.distribution.D06': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.lead.distribution.D07': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.lead.distribution.D08': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.lead.distribution.D09': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.lead.distribution.D10': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.lead.total':     (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.champion':       (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.champion.distribution': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.champion.distribution.D01': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.champion.distribution.D02': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.champion.distribution.D03': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.champion.distribution.D04': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.champion.distribution.D05': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.champion.distribution.D06': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.champion.distribution.D07': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.champion.distribution.D08': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.champion.distribution.D09': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.champion.distribution.D10': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.champion.total': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.challenger':     (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.challenger.distribution': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.challenger.distribution.D01': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.challenger.distribution.D02': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.challenger.distribution.D03': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.challenger.distribution.D04': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.challenger.distribution.D05': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.challenger.distribution.D06': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.challenger.distribution.D07': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.challenger.distribution.D08': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.challenger.distribution.D09': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.challenger.distribution.D10': (R, None),
    'lead_quality_metrics.decil_distribution_current_launch.by_optgoal.challenger.total': (R, None),

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
    'operational_routines.leads_capi_by_variant_24h':                                   (R, None),  # ex: dict(2) — denominador do CPL Meta
    'operational_routines.leads_capi_by_variant_24h.challenger_abr28':                  (R, None),  # ex: 120
    'operational_routines.leads_capi_by_variant_24h.champion_jan30':                    (R, None),  # ex: 900
    'operational_routines.spend_by_variant_24h_brl':                                    (R, None),  # ex: dict(2) — split por campaign.name
    'operational_routines.spend_by_variant_24h_brl.challenger_abr28':                   (R, None),  # ex: 234.56
    'operational_routines.spend_by_variant_24h_brl.champion_jan30':                     (R, None),  # ex: 1234.56
    'operational_routines.cpl_by_variant_24h_brl':                                      (R, None),  # ex: dict(2) — spend/leads_capi
    'operational_routines.cpl_by_variant_24h_brl.challenger_abr28':                     (R, None),  # ex: 1.95
    'operational_routines.cpl_by_variant_24h_brl.champion_jan30':                       (R, None),  # ex: 1.37
    'operational_routines.spend_ml_24h_brl':                                            (R, None),  # ex: 630.92 — adsets otimizando evento ML (Champion+Challenger)
    'operational_routines.spend_nonml_24h_brl':                                         (R, None),  # ex: 7291.33 — adsets otimizando evento Lead padrão
    'operational_routines.minutes_since_last_score':                                    (S, 'debug interno; último scoring não renderizado'),

    # ──────────────────────────────────────────────────────────────────────────
    # LAUNCH_RESOLUTION — fonte da janela do LF atual (src.core.launches)
    # ──────────────────────────────────────────────────────────────────────────
    'launch_resolution':                                                                (R, None),  # ex: dict(6)
    'launch_resolution.lf_name':                                                        (S, 'rendererizado embutido no label / aviso fallback'),
    'launch_resolution.source':                                                         (R, None),  # ex: 'launches_yaml' | 'monday_heuristic' — DM avisa quando vier do fallback
    'launch_resolution.inferred':                                                       (S, 'sinalizado visualmente no label/aviso, sem campo dedicado'),
    'launch_resolution.cap_start':                                                      (S, 'já presente no label'),
    'launch_resolution.cap_end':                                                        (S, 'já presente no label; None quando fallback'),
    'launch_resolution.label':                                                          (S, 'consumido pelo aviso de fallback no DM'),

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

    'revenue_forecast.lf_anterior':                                                    (R, None),
    'revenue_forecast.lf_anterior.inputs.lf_name':                                      (R, None),
    'revenue_forecast.lf_anterior.cenario_base':                                        (R, None),
    'revenue_forecast.lf_anterior.cenario_base.cartao_avista_liquido':                  (R, None),
    'revenue_forecast.lf_anterior.cenario_base.faturamento':                            (R, None),
    'revenue_forecast.lf_anterior.cenario_base.faturamento_recebido':                   (R, None),
    'revenue_forecast.lf_anterior.cenario_base.primeira_parcela_boleto':                (R, None),
    'revenue_forecast.lf_anterior.cenario_base.vendas_guru':                            (R, None),
    'revenue_forecast.lf_anterior.cenario_base.vendas_tmb':                             (R, None),
    'revenue_forecast.lf_anterior.cenario_base.vendas_total':                           (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware':                                    (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware.cartao_avista_liquido':              (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware.faturamento':                        (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware.faturamento_recebido':               (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware.primeira_parcela_boleto':            (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware.vendas_guru':                        (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware.vendas_tmb':                         (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware.vendas_total':                       (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware_pessimista':                         (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware_pessimista.cartao_avista_liquido':   (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware_pessimista.faturamento':             (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware_pessimista.faturamento_recebido':    (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware_pessimista.primeira_parcela_boleto': (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware_pessimista.vendas_guru':             (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware_pessimista.vendas_tmb':              (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware_pessimista.vendas_total':            (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware_otimista':                           (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware_otimista.cartao_avista_liquido':     (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware_otimista.faturamento':               (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware_otimista.faturamento_recebido':      (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware_otimista.primeira_parcela_boleto':   (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware_otimista.vendas_guru':               (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware_otimista.vendas_tmb':                (R, None),
    'revenue_forecast.lf_anterior.cenario_ml_aware_otimista.vendas_total':              (R, None),
    'revenue_forecast.lf_anterior.cenario_otimista':                                    (R, None),
    'revenue_forecast.lf_anterior.cenario_otimista.cartao_avista_liquido':              (R, None),
    'revenue_forecast.lf_anterior.cenario_otimista.faturamento':                        (R, None),
    'revenue_forecast.lf_anterior.cenario_otimista.faturamento_recebido':               (R, None),
    'revenue_forecast.lf_anterior.cenario_otimista.primeira_parcela_boleto':            (R, None),
    'revenue_forecast.lf_anterior.cenario_otimista.vendas_guru':                        (R, None),
    'revenue_forecast.lf_anterior.cenario_otimista.vendas_tmb':                         (R, None),
    'revenue_forecast.lf_anterior.cenario_otimista.vendas_total':                       (R, None),
    'revenue_forecast.lf_anterior.cenario_pessimista':                                  (R, None),
    'revenue_forecast.lf_anterior.cenario_pessimista.cartao_avista_liquido':            (R, None),
    'revenue_forecast.lf_anterior.cenario_pessimista.faturamento':                      (R, None),
    'revenue_forecast.lf_anterior.cenario_pessimista.faturamento_recebido':             (R, None),
    'revenue_forecast.lf_anterior.cenario_pessimista.primeira_parcela_boleto':          (R, None),
    'revenue_forecast.lf_anterior.cenario_pessimista.vendas_guru':                      (R, None),
    'revenue_forecast.lf_anterior.cenario_pessimista.vendas_tmb':                       (R, None),
    'revenue_forecast.lf_anterior.cenario_pessimista.vendas_total':                     (R, None),
    'revenue_forecast.lf_anterior.expected_conversion':                                 (S, 'redundante com cenário ML-aware'),
    'revenue_forecast.lf_anterior.expected_conversion.compradores_esperados':           (S, 'integrado ao cenário ML-aware'),
    'revenue_forecast.lf_anterior.expected_conversion.compradores_esperados.D10':       (S, 'integrado ao cenário ML-aware'),
    'revenue_forecast.lf_anterior.expected_conversion.compradores_esperados.D1_D5':     (S, 'integrado ao cenário ML-aware'),
    'revenue_forecast.lf_anterior.expected_conversion.compradores_esperados.D6_D9':     (S, 'integrado ao cenário ML-aware'),
    'revenue_forecast.lf_anterior.expected_conversion.compradores_esperados.taxa_media_corrigida': (S, 'detalhes da metodologia'),
    'revenue_forecast.lf_anterior.expected_conversion.compradores_esperados.total':     (S, 'integrado ao cenário ML-aware'),
    'revenue_forecast.lf_anterior.expected_conversion.distribuicao_leads':              (S, 'redundante com cenário ML-aware'),
    'revenue_forecast.lf_anterior.expected_conversion.distribuicao_leads.D10':          (S, 'redundante'),
    'revenue_forecast.lf_anterior.expected_conversion.distribuicao_leads.D10.leads':    (S, 'redundante'),
    'revenue_forecast.lf_anterior.expected_conversion.distribuicao_leads.D10.pct':      (S, 'redundante'),
    'revenue_forecast.lf_anterior.expected_conversion.distribuicao_leads.D1_D5':        (S, 'redundante'),
    'revenue_forecast.lf_anterior.expected_conversion.distribuicao_leads.D1_D5.leads':  (S, 'redundante'),
    'revenue_forecast.lf_anterior.expected_conversion.distribuicao_leads.D1_D5.pct':    (S, 'redundante'),
    'revenue_forecast.lf_anterior.expected_conversion.distribuicao_leads.D6_D9':        (S, 'redundante'),
    'revenue_forecast.lf_anterior.expected_conversion.distribuicao_leads.D6_D9.leads':  (S, 'redundante'),
    'revenue_forecast.lf_anterior.expected_conversion.distribuicao_leads.D6_D9.pct':    (S, 'redundante'),
    'revenue_forecast.lf_anterior.expected_conversion.distribuicao_leads.response_rate_pct': (S, 'redundante'),
    'revenue_forecast.lf_anterior.expected_conversion.distribuicao_leads.total_db':     (S, 'redundante'),
    'revenue_forecast.lf_anterior.expected_conversion.fonte':                           (S, 'redundante com cenário ML-aware'),
    'revenue_forecast.lf_anterior.expected_conversion.taxa_implicita_por_meta_lead':    (S, 'redundante'),
    'revenue_forecast.lf_anterior.expected_conversion.taxas_corrigidas':                (S, 'detalhes da metodologia'),
    'revenue_forecast.lf_anterior.expected_conversion.taxas_corrigidas.D10':            (S, 'detalhes da metodologia'),
    'revenue_forecast.lf_anterior.expected_conversion.taxas_corrigidas.D1_D5':          (S, 'detalhes da metodologia'),
    'revenue_forecast.lf_anterior.expected_conversion.taxas_corrigidas.D6_D9':          (S, 'detalhes da metodologia'),
    'revenue_forecast.lf_anterior.expected_conversion.taxas_corrigidas.tracking_rate_aplicado': (S, 'detalhes da metodologia'),
    'revenue_forecast.lf_anterior.inputs':                                              (R, None),
    'revenue_forecast.lf_anterior.inputs.conv_rastr_mediana':                           (S, 'detalhes da metodologia no payload da API'),
    'revenue_forecast.lf_anterior.inputs.fonte_flat_rate':                              (S, 'detalhes da metodologia no payload da API'),
    'revenue_forecast.lf_anterior.inputs.fonte_ml_aware':                               (S, 'detalhes da metodologia no payload da API'),
    'revenue_forecast.lf_anterior.inputs.launch_window_start_brt':                      (R, None),
    'revenue_forecast.lf_anterior.inputs.metodologia':                                  (R, None),
    'revenue_forecast.lf_anterior.inputs.pct_cartao_historico':                         (S, 'detalhes da metodologia no payload da API'),
    'revenue_forecast.lf_anterior.inputs.taxa_real_implicita':                          (S, 'detalhes da metodologia no payload da API'),
    'revenue_forecast.lf_anterior.inputs.ticket_contracted':                            (R, None),
    'revenue_forecast.lf_anterior.inputs.total_leads_meta':                             (R, None),
    'revenue_forecast.lf_anterior.inputs.tracking_rate_usado':                          (S, 'detalhes da metodologia no payload da API'),
    # SURVEY_FUNNEL_METRICS — renderer removido em 13/05/2026 (digest.py:
    # _slack_survey/_render_text_survey já não são mais chamados). Campos
    # mantidos no payload pra reuso futuro/debug; catalogados como SKIPPED.
    # ──────────────────────────────────────────────────────────────────────────
    'survey_funnel_metrics':                                                            (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.historico':                                                  (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.historico.capi_rate':                                        (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.historico.capi_sent':                                        (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.historico.db_leads':                                         (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.historico.meta_leads':                                       (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.historico.response_rate':                                    (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.periodo_query':                                              (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.periodo_query.capi_rate':                                    (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.periodo_query.capi_sent':                                    (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.periodo_query.db_leads':                                     (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.periodo_query.meta_leads':                                   (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.periodo_query.response_rate':                                (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultima_semana':                                              (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultima_semana.capi_rate':                                    (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultima_semana.capi_sent':                                    (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultima_semana.db_leads':                                     (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultima_semana.meta_leads':                                   (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultima_semana.response_rate':                                (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultimas_24h':                                                (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultimas_24h.capi_rate':                                      (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultimas_24h.capi_sent':                                      (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultimas_24h.db_leads':                                       (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultimas_24h.meta_leads':                                     (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultimas_24h.response_rate':                                  (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultimo_mes':                                                 (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultimo_mes.capi_rate':                                       (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultimo_mes.capi_sent':                                       (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultimo_mes.db_leads':                                        (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultimo_mes.meta_leads':                                      (S, 'renderer removido do digest em 13/05/2026'),
    'survey_funnel_metrics.ultimo_mes.response_rate':                                   (S, 'renderer removido do digest em 13/05/2026'),

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
    'traffic_metrics.dia_anterior':                                                     (R, None),  # dia BRT anterior (funil unificado)
    'traffic_metrics.dia_anterior.clicks':                                              (R, None),
    'traffic_metrics.dia_anterior.cpl':                                                 (R, None),
    'traffic_metrics.dia_anterior.ctr_lead':                                            (R, None),
    'traffic_metrics.dia_anterior.meta_leads':                                          (R, None),
    'traffic_metrics.dia_anterior.spend':                                               (R, None),
    # Por variante (Lead/Champion/Challenger) — CPL real + conv LP no funil.
    'traffic_metrics.dia_anterior.por_variante':                                        (R, None),  # dict(3) buckets
    'traffic_metrics.dia_anterior.por_variante.Lead':                                   (R, None),
    'traffic_metrics.dia_anterior.por_variante.Lead.leads':                             (R, None),  # leads reais Client (source Meta)
    'traffic_metrics.dia_anterior.por_variante.Lead.cpl':                               (R, None),  # spend ÷ leads
    'traffic_metrics.dia_anterior.por_variante.Lead.conv_lp':                           (R, None),  # leads ÷ landing_page_views
    'traffic_metrics.dia_anterior.por_variante.Lead.spend':                             (S, 'insumo do CPL; não renderizado direto'),
    'traffic_metrics.dia_anterior.por_variante.Lead.lpv':                               (S, 'insumo da conv LP; não renderizado direto'),
    'traffic_metrics.dia_anterior.por_variante.Champion':                               (R, None),
    'traffic_metrics.dia_anterior.por_variante.Champion.leads':                         (R, None),
    'traffic_metrics.dia_anterior.por_variante.Champion.cpl':                           (R, None),
    'traffic_metrics.dia_anterior.por_variante.Champion.conv_lp':                       (R, None),
    'traffic_metrics.dia_anterior.por_variante.Champion.spend':                         (S, 'insumo do CPL; não renderizado direto'),
    'traffic_metrics.dia_anterior.por_variante.Champion.lpv':                           (S, 'insumo da conv LP; não renderizado direto'),
    'traffic_metrics.dia_anterior.por_variante.Challenger':                             (R, None),
    'traffic_metrics.dia_anterior.por_variante.Challenger.leads':                       (R, None),
    'traffic_metrics.dia_anterior.por_variante.Challenger.cpl':                         (R, None),
    'traffic_metrics.dia_anterior.por_variante.Challenger.conv_lp':                     (R, None),
    'traffic_metrics.dia_anterior.por_variante.Challenger.spend':                       (S, 'insumo do CPL; não renderizado direto'),
    'traffic_metrics.dia_anterior.por_variante.Challenger.lpv':                         (S, 'insumo da conv LP; não renderizado direto'),
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

    # ──────────────────────────────────────────────────────────────────────────
    # PUBSUB_24H_SUMMARY  (Etapa 7 do refator do monitoramento — 2026-05-24)
    # Lê do ledger novo (`registros_ml`); todas as chaves canônicas estão
    # sempre presentes (zeradas se sem dados na janela).
    # ──────────────────────────────────────────────────────────────────────────
    'pubsub_24h_summary':                                                               (R, None),  # ex: dict(4)
    'pubsub_24h_summary.total':                                                         (R, None),  # ex: 527
    'pubsub_24h_summary.by_status':                                                     (R, None),  # ex: dict(4)
    'pubsub_24h_summary.by_status.success':                                             (R, None),
    'pubsub_24h_summary.by_status.error':                                               (R, None),
    'pubsub_24h_summary.by_status.skipped_allowlist':                                   (R, None),
    'pubsub_24h_summary.by_status.skipped_missing_data':                                (R, None),
    'pubsub_24h_summary.decil_distribution':                                            (R, None),  # ex: dict(10)
    'pubsub_24h_summary.decil_distribution.D01':                                        (R, None),
    'pubsub_24h_summary.decil_distribution.D02':                                        (R, None),
    'pubsub_24h_summary.decil_distribution.D03':                                        (R, None),
    'pubsub_24h_summary.decil_distribution.D04':                                        (R, None),
    'pubsub_24h_summary.decil_distribution.D05':                                        (R, None),
    'pubsub_24h_summary.decil_distribution.D06':                                        (R, None),
    'pubsub_24h_summary.decil_distribution.D07':                                        (R, None),
    'pubsub_24h_summary.decil_distribution.D08':                                        (R, None),
    'pubsub_24h_summary.decil_distribution.D09':                                        (R, None),
    'pubsub_24h_summary.decil_distribution.D10':                                        (R, None),
    'pubsub_24h_summary.top_errors':                                                    (R, None),  # ex: list até 5
    'pubsub_24h_summary.top_errors[].message':                                          (R, None),
    'pubsub_24h_summary.top_errors[].count':                                            (R, None),

    # ──────────────────────────────────────────────────────────────────────────
    # TRAINING_DRIFT_24H_SUMMARY  (Paridade treino × produção via T1-16 — 2026-05-25)
    # Lê logs `[T1-16] (observa, ...)` do Cloud Run via google-cloud-logging;
    # agrega quantos batches dispararam e as top features afetadas.
    # ──────────────────────────────────────────────────────────────────────────
    'training_drift_24h_summary':                                                       (R, None),
    'training_drift_24h_summary.window_hours':                                          (R, None),
    'training_drift_24h_summary.batches_com_drift':                                     (R, None),
    'training_drift_24h_summary.total_observacoes':                                     (R, None),
    'training_drift_24h_summary.observacao':                                            (R, None),
    'training_drift_24h_summary.top_features':                                          (R, None),  # ex: list até 5
    'training_drift_24h_summary.top_features[].feature':                                (R, None),
    'training_drift_24h_summary.top_features[].obs_media':                              (R, None),
    'training_drift_24h_summary.top_features[].exp':                                    (R, None),
    'training_drift_24h_summary.top_features[].delta_pp':                               (R, None),
    'training_drift_24h_summary.top_features[].count':                                  (R, None),
    'training_drift_24h_summary.erro':                                                  (R, None),
}
