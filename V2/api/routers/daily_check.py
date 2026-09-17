"""Daily-check do monitoramento (o handler grande, /monitoring/daily-check/railway) e o digest do Slack.

Gerado a partir do app.py monolítico (corte por domínio, corpo dos handlers intacto)."""
import os
from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from typing import Annotated, List, Dict, Any, Optional
import time
from datetime import datetime
from api.database import get_db, init_database, create_lead_capi, count_leads, count_leads_with_fbp, count_leads_with_fbc, get_leads_by_emails, LeadCAPI
from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session
from fastapi import APIRouter
import logging
from api.state import PipelineOptDep, pipelines

logger = logging.getLogger(__name__)
router = APIRouter()


class DailyCheckRequest(BaseModel):
    """Request para check diário de monitoramento"""
    leads: List[Dict[str, Any]] = Field(..., description="Dados do Sheets das últimas 24h")


class DailyCheckResponse(BaseModel):
    """Response do check diário"""
    total_alerts: int
    alerts_by_severity: Dict[str, int]
    alerts_by_category: Dict[str, int]
    # Subset HIGH+MEDIUM em formato compacto (type, severity, column, percentage, message).
    # Lista de leitura humana direta — ver V.2 de docs/registro_erros_ml.md.
    actionable_alerts: List[Dict[str, Any]] = []
    alerts: List[Dict[str, Any]]
    critical_summary: str
    timestamp: str
    funnel_metrics: Optional[Dict[str, Any]] = None
    lead_quality_metrics: Optional[Dict[str, Any]] = None
    revenue_forecast: Optional[Dict[str, Any]] = None
    survey_funnel_metrics: Optional[Dict[str, Any]] = None
    traffic_metrics: Optional[Dict[str, Any]] = None
    operational_routines: Optional[Dict[str, Any]] = None
    # Resolução do LF atual (lf_name, source: 'launches_yaml'|'monday_heuristic',
    # cap_start, cap_end, inferred). Permite ao digest avisar quando está usando
    # fallback de segunda (vide src/core/launches.py).
    launch_resolution: Optional[Dict[str, Any]] = None
    # revenue_forecast inclui expected_conversion quando conversion_rate_benchmark está configurado

    # Sumário do consumer Pub/Sub 24h (Etapa 7 do refator do monitoramento).
    # Renderizado no bloco "📨 Pub/Sub 24h" do digest do Slack.
    pubsub_24h_summary: Optional[Dict[str, Any]] = None
    # Sumário T1-16: paridade treino × produção 24h (2026-05-25).
    # Renderizado no bloco "🎯 Paridade treino × produção (24h)" do digest.
    training_drift_24h_summary: Optional[Dict[str, Any]] = None
    # Saúde do pipeline HotLeads 24h (selo da Hotmart → evento LeadScoringHot).
    # Renderizado no bloco "🔥 HotLeads 24h" do digest (só DM).
    hotleads_24h_summary: Optional[Dict[str, Any]] = None


@router.get("/monitoring/daily-check", response_model=DailyCheckResponse)
async def daily_monitoring_check_auto(
    pipeline: PipelineOptDep,
    hours: int = 24,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    include_today_partial: bool = False,
):
    """
    Executa check diário de monitoramento com dados do Railway PostgreSQL.

    Delega para /monitoring/daily-check/railway, que é a fonte primária de dados.
    Railway cobre 99.9% dos leads (verificado em 23/02/2026).

    Args:
        hours: Número de horas para buscar (padrão: 24). Ignorado se start_date/end_date forem passados.
        start_date: Data de início no formato YYYY-MM-DD (BRT). Ex: 2026-02-01
        end_date: Data de fim no formato YYYY-MM-DD (BRT). Ex: 2026-02-20

    Returns:
        Alertas consolidados por severidade e categoria
    """
    return await daily_monitoring_check_railway(
        pipeline=pipeline,
        hours=hours,
        start_date=start_date,
        end_date=end_date,
        include_today_partial=include_today_partial,
    )


@router.get("/monitoring/daily-check/railway", response_model=DailyCheckResponse)
async def daily_monitoring_check_railway(
    pipeline: PipelineOptDep,
    hours: int = 24,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    include_today_partial: bool = False,
    anchor_date: Optional[str] = None,
):
    """
    Executa check diário de monitoramento 100% com dados do Railway PostgreSQL.

    Fluxo:
    1. Busca leads scored das últimas N horas (para alertas/drift ML)
    2. Busca stats agregados da janela (total, CAPI, qualidade de dados)
    3. Busca todos os leads scored (para métricas de qualidade por período)
    4. Constrói funnel_metrics e lead_quality_metrics do Railway — sem Sheets/Cloud SQL
    5. Executa orchestrator.run_daily_check() para gerar alertas de drift/qualidade
    6. Substitui funnel_metrics e lead_quality_metrics pelo resultado Railway

    Args:
        hours: Número de horas para buscar (padrão: 24). Ignorado se start_date/end_date forem passados.
        start_date: Data de início no formato YYYY-MM-DD (BRT). Ex: 2026-02-01
        end_date: Data de fim no formato YYYY-MM-DD (BRT). Ex: 2026-02-20
        db: Sessão PostgreSQL Cloud SQL (mantida para assinatura, não usada nas métricas)
    """
    import pg8000.native
    import json as _json
    import yaml
    from src.monitoring.orchestrator import MonitoringOrchestrator
    from api.railway_mapping import railway_lead_to_sheets_row
    from datetime import timezone as _tz, timedelta

    start_time = time.time()

    try:
        # ------------------------------------------------------------------
        # 0. Calcular janela de tempo (UTC) — start_date/end_date têm prioridade
        # ------------------------------------------------------------------
        brt = _tz(timedelta(hours=-3))
        now_utc = datetime.now(_tz.utc)

        # Âncora opcional: renderiza o relatório de um lançamento PASSADO ancorando
        # "hoje" na data informada. Deriva start/end da janela cap do LF resolvido
        # (reusa a maquinaria de start_date/end_date abaixo) e propaga `_anchor`
        # pras seções de "lançamento atual" (decis + drift). None = hoje real
        # (o cron das 06:00 nunca passa esse param → comportamento intacto).
        _anchor = None
        if anchor_date:
            from datetime import date as _date_cls
            try:
                _anchor = _date_cls.fromisoformat(anchor_date)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"anchor_date inválido: '{anchor_date}'. Use YYYY-MM-DD.",
                )
            if not (start_date and end_date):
                from src.core.launches import resolve_launch_window_brt as _rlw_anchor
                _alw = _rlw_anchor(today=_anchor)
                start_date = _alw.cap_start.isoformat()
                end_date   = (_alw.cap_end or _anchor).isoformat()

        if start_date and end_date:
            try:
                from datetime import date as _date
                _start = datetime.strptime(start_date, '%Y-%m-%d').replace(
                    hour=0, minute=0, second=0,
                    tzinfo=brt
                ).astimezone(_tz.utc)
                _end = datetime.strptime(end_date, '%Y-%m-%d').replace(
                    hour=23, minute=59, second=59,
                    tzinfo=brt
                ).astimezone(_tz.utc)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Formato de data inválido. Use YYYY-MM-DD. Ex: start_date=2026-02-01&end_date=2026-02-20"
                )
            window_start = _start
            window_end   = _end
            window_label = f"{start_date} → {end_date}"
        else:
            window_start = now_utc - timedelta(hours=hours)
            window_end   = now_utc
            window_label = f"últimas {hours}h"

        # ------------------------------------------------------------------
        # 1. Conectar ao Railway e buscar todos os dados necessários
        # ------------------------------------------------------------------
        railway_conn = pg8000.native.Connection(
            host=os.environ['RAILWAY_DB_HOST'],
            port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
            database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
            user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
            password=os.environ['RAILWAY_DB_PASSWORD'],
            timeout=30,
        )

        # 1a. Leads com score na janela — via LeadRepository (ledger novo
        # `registros_ml`). Substitui SQL inline na Lead antiga (morta desde
        # 2026-05-17). Fatia A do refator daily-check pra fonte unificada.
        # O ledger é lido pela fonte escolhida por LEDGER_READ_SOURCE
        # (railway|cloudsql) — conn dedicada, separada da `railway_conn` que
        # serve só tabelas Railway-only (Client). PLANO_LEDGER_CLOUDSQL Etapa 3.
        from src.data import compose_repository
        from src.data.ledger_connection import open_ledger_read_connection
        ledger_conn = open_ledger_read_connection()
        _repo_leads = compose_repository('registros_ml', railway_conn=ledger_conn)
        _records = _repo_leads.leads_in_range(window_start, window_end)
        # Filtra: só leads efetivamente scoreados (equivalente ao
        # `WHERE leadScore IS NOT NULL` da query antiga).
        scored_rows = [r for r in _records if r.score is not None]

        # 1b. Stats agregados da janela (total, CAPI, phone) — Fatia B do refator.
        # Agregação pura em cima de `_records` (já lidos pelo LeadRepository).
        # Substitui SQL inline na Lead morta.
        from src.monitoring.daily_check_aggregations import (
            compute_stats_window,
            compute_fbp_fbc_meta_population,
            compute_fbp_fbc_rolling,
        )
        stats_dict = compute_stats_window(_records)
        # `stats_row` mantido como tupla pra compat com o resto do código que
        # ainda lê via `stats_row[0]` mais abaixo (será limpo em Fatia E).
        stats_row = [(
            stats_dict['total'], stats_dict['scored'], stats_dict['capi_sent'],
            stats_dict['capi_success'], stats_dict['capi_error'], stats_dict['with_phone'],
        )]

        # FBP/FBC sobre população Meta-elegível na janela do report — Fatia B.
        # No ledger novo, "leads_capi" vira "leads que passaram pelo CAPI"
        # (status_envio != 'skipped_allowlist').
        fbp_pop = compute_fbp_fbc_meta_population(_records)
        capi_fbp_row = [(fbp_pop['with_fbp'], fbp_pop['with_fbc'], fbp_pop['total_meta_leads'])]

        # FBP/FBC em janelas rolling 7d/3d/1d — Fatia C. Independente do `hours`
        # do report. Lê 7d do registros_ml via repo (não a janela do report).
        _fb_anchor = window_end
        _fb_d7 = _fb_anchor - timedelta(days=7)
        _records_7d = _repo_leads.leads_in_range(_fb_d7, _fb_anchor)
        fbp_fbc_rolling = compute_fbp_fbc_rolling(_records_7d, anchor=_fb_anchor)

        # 1b-bis. unified_funnel — funil completo (TODAS as fontes), com quebra
        # por origem fb (facebook-ads/ig/fb) · ggl (google-ads) · outr (resto).
        # Camada anúncio (spend/cliques/pixel) vem do traffic_metrics (Meta
        # Insights — não há ad-data de Google aqui). Camada pipeline conta TODAS
        # as fontes — nada é eliminado da observação.
        # JANELA = dia BRT anterior completo (00:00→23:59 ontem), igual o resto
        # do digest (drift "Ontem") — NÃO rolling 24h.
        # Fatia E do refator: 13 queries SQL inline na Lead morta substituídas
        # por agregação pura sobre LeadRecord vindo do LeadRepository.
        from src.monitoring.daily_check_aggregations import compute_unified_funnel
        _uf_brt = _tz(timedelta(hours=-3))
        _uf_today_mid = datetime.now(_uf_brt).replace(hour=0, minute=0, second=0, microsecond=0)
        _uf_e = _uf_today_mid.astimezone(_tz.utc)                       # hoje 00:00 BRT
        _uf_s = (_uf_today_mid - timedelta(days=1)).astimezone(_tz.utc)  # ontem 00:00 BRT
        _uf_date_brt = (_uf_today_mid - timedelta(days=1)).strftime('%d/%m')
        _uf_records = _repo_leads.leads_in_range(_uf_s, _uf_e)
        unified_funnel = compute_unified_funnel(
            _uf_records, date_brt_label=_uf_date_brt,
        )

        # 1b-ter. Taxa de resposta da pesquisa (cadastro→pesquisa), série diária 7d
        # BRT pro grupo de dados. Numerador = registros_ml (respostas) via repo
        # (honra LEDGER_READ_SOURCE); denominador = tabela Client (cadastros
        # all-source, Railway, schema do DevClub) — query GROUP BY dia guardada.
        # Janela = 7 dias BRT COMPLETOS terminando ontem ([hoje-7d 00:00, hoje 00:00)).
        # Tudo guardado: falha (inclusive cliente futuro sem Client) só omite a
        # métrica, não derruba o relatório das 06:00.
        survey_response_rate = None
        try:
            from src.monitoring.daily_check_aggregations import compute_survey_response_rate
            _rr_days = 7
            _rr_start_utc = (_uf_today_mid - timedelta(days=_rr_days)).astimezone(_tz.utc)
            # Respostas: e-mails que responderam, de _rr_start até AGORA (não _uf_e =
            # 00:00 BRT de hoje). Crucial pra coorte: a resposta do lead de ontem chega
            # de madrugada/manhã de hoje; cortar na meia-noite perderia essa cauda e
            # reintroduziria a distorção que estamos corrigindo.
            _rr_end_utc = datetime.now(_tz.utc)
            _rr_resp = _repo_leads.leads_in_range(_rr_start_utc, _rr_end_utc, limit=50_000)
            # Cadastros por dia BRT de cadastro, com e-mail normalizado (lower/trim) —
            # coorte por dia de cadastro, não por hora de processamento da resposta.
            # Acesso ao Client mora aqui por ser schema-específico do Railway.
            _cad_rows = railway_conn.run(
                'SELECT (("createdAt" - interval \'3 hours\')::date)::text AS d, '
                'lower(trim("email")) AS e '
                'FROM "Client" WHERE "createdAt" >= :s AND "createdAt" < :e '
                'AND "email" IS NOT NULL',
                s=_rr_start_utc, e=_uf_e,
            )
            _cad_emails_by_day = {}
            for _d, _e in _cad_rows:
                if _e:
                    _cad_emails_by_day.setdefault(_d, []).append(_e)
            survey_response_rate = compute_survey_response_rate(
                _rr_resp, _cad_emails_by_day, today_brt_mid=_uf_today_mid, days=_rr_days,
            )
            if survey_response_rate:
                logger.info(
                    f"📋 taxa de resposta 7d: ontem={survey_response_rate['ontem']['taxa']}% "
                    f"· média={survey_response_rate['media_taxa']}%"
                )
        except Exception as _rre:
            logger.warning(f"⚠️ taxa de resposta indisponível (segue sem): {_rre}")
            survey_response_rate = None

        # 1c. Todos os leads com score (para métricas de qualidade por período)
        # UTMs + pageUrl extras pra split por variante A/B (baseline ponderado dos decis).
        # _calc_quality / _after / _decil_dist usam só [0]/[1]/[2], extras são ignorados.
        # Fatia D do refator: quality_rows agora vem via LeadRepository
        # (ledger novo) em vez da Lead morta. Histórico máximo = 90 dias
        # (limite do repository); volume atual ~270/dia → ~24k em 90d, bem
        # abaixo do limit. Quando o ledger crescer, as janelas histórico/mês
        # crescem junto naturalmente.
        from src.monitoring.daily_check_aggregations import records_to_quality_rows
        _quality_window_start = now_utc - timedelta(days=90)
        # Projeção LEVE: os consumidores de 90d (quality_rows, forecast de decil,
        # funil de pesquisa, decis por variante) só usam score/decil/data/variante/
        # status/UTMs — nenhum toca survey/PII. summaries_in_range pula o parse do
        # JSONB de pesquisa + PII em ~24k linhas, cortando o maior pico de RAM do
        # relatório. Mesmo conjunto de linhas que leads_in_range.
        _records_90d = _repo_leads.summaries_in_range(
            _quality_window_start, now_utc, limit=50_000,
        )
        _records_90d_scored = [r for r in _records_90d if r.score is not None and r.decil is not None]
        # Mesmo schema da query antiga: (leadScore, decil, createdAt, source,
        # medium, campaign, content, term, pageUrl). Consumidores downstream
        # (decil_dist, _after, _calc_quality) continuam funcionando intactos.
        quality_rows = records_to_quality_rows(_records_90d_scored)

        # 1d. Leads do lançamento atual — exclusivo para revenue_forecast.
        # Se start_date/end_date foram passados, usa essa janela.
        # Senão, src.core.launches.resolve_launch_window_brt() resolve:
        #   1) LF do launches.yaml com cap_start ≤ hoje ≤ cap_end, OU
        #   2) Fallback: desde a última segunda BRT (com warning no log).
        # Nunca cai no último LF encerrado — esse fallback escondia o gap quando o YAML
        # está desatualizado (vide caso LF55 detectado em 13/05/2026).
        now_brt = now_utc.astimezone(brt)
        launch_resolution_payload: Optional[Dict[str, Any]] = None
        if start_date and end_date:
            launch_window_start     = datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=brt)
            launch_window_start_utc = window_start
            launch_window_end_utc   = window_end
            launch_window_label     = f"{start_date} → {end_date}"
        else:
            from src.core.launches import resolve_launch_window_brt
            _lw = resolve_launch_window_brt()
            launch_window_start = datetime(
                _lw.cap_start.year, _lw.cap_start.month, _lw.cap_start.day,
                0, 0, 0, tzinfo=brt,
            )
            launch_window_start_utc = launch_window_start.astimezone(_tz.utc)
            launch_window_end_utc   = now_utc
            # "→ hoje": a janela do lançamento ATUAL termina no momento da
            # execução, não no cap_end do calendário. Sem o sufixo, o DM de
            # 15/08 mostrava "LF64 07/08 → 15/08" ao lado do anterior
            # "07/08 → 17/08" e parecia divergência de dados — era só rótulo.
            if _lw.lf_name and not _lw.inferred:
                launch_window_label = (
                    f"{_lw.lf_name} {_lw.cap_start.strftime('%d/%m/%Y')} → "
                    f"{now_brt.strftime('%d/%m/%Y')} (até hoje)"
                )
            elif _lw.lf_name and _lw.inferred:
                launch_window_label = (
                    f"{_lw.lf_name} (inferido) {_lw.cap_start.strftime('%d/%m/%Y')} → "
                    f"{now_brt.strftime('%d/%m/%Y')} (até hoje)"
                )
            else:
                launch_window_label = (
                    f"{_lw.cap_start.strftime('%d/%m/%Y')} → "
                    f"{now_brt.strftime('%d/%m/%Y')} (LF não cadastrado em launches.yaml)"
                )
            launch_resolution_payload = {
                'lf_name':   _lw.lf_name,
                'source':    _lw.source,
                'inferred':  _lw.inferred,
                'cap_start': _lw.cap_start.isoformat(),
                'cap_end':   _lw.cap_end.isoformat() if _lw.cap_end else None,
                'label':     _lw.label,
            }

        # Distribuição de decis na janela do lançamento — usada pelo
        # expected_conversion e pelos cenários ML-aware (Método 2 do bloco
        # 'Previsão de Faturamento' no Slack). Fatia E do refator: substitui
        # query SQL na Lead morta por filtro in-memory sobre _records_90d
        # (que já cobre a janela do LF ativo, sempre <90d de captação).
        forecast_decil_dist: Dict[str, int] = {}
        forecast_decil_dist_by_variant: Dict[str, Dict[str, int]] = {}
        for _rec in _records_90d:
            if _rec.criado_em is None or _rec.decil is None or _rec.score is None:
                continue
            _c = _rec.criado_em.replace(tzinfo=_tz.utc) if _rec.criado_em.tzinfo is None else _rec.criado_em
            if launch_window_start_utc <= _c <= launch_window_end_utc:
                _key = f"D{int(_rec.decil):02d}"
                forecast_decil_dist[_key] = forecast_decil_dist.get(_key, 0) + 1
                # Split por variante do A/B (registros_ml.variant gravado no
                # scoring; null/'' = Champion). Base do ML-aware por variante.
                # Lead de FORA da Meta (google/orgânico) tem variant vazio mas
                # NÃO é do Champion — nenhum modelo o roteou por campanha; ele
                # ganha segmento próprio no split ('fora_meta') pra não herdar
                # rótulo/benchmark do Champion (auditoria 16/08). O POOLED
                # continua all-source por desenho (denominador Client).
                _vk = _rec.variant or ''
                if not _vk:
                    from src.monitoring.campaign_classifier import channel_from_source as _cfs
                    if _cfs(_rec.utm_source) != 'meta':
                        _vk = 'fora_meta'
                forecast_decil_dist_by_variant.setdefault(_vk, {})
                forecast_decil_dist_by_variant[_vk][_key] = forecast_decil_dist_by_variant[_vk].get(_key, 0) + 1

        # Total de leads ALL-SOURCE na janela (tabela Client = todas as fontes:
        # Meta + Google + orgânico) — denominador do flat-rate quando
        # business.conv_real_allsource está setado. Corrige a subestimativa de
        # contar só fb_pixel_lead da Meta (~15% a menos). Falha → 0, e o call
        # abaixo cai no denominador Meta como fallback.
        total_leads_allsource_forecast = 0
        try:
            _cl = railway_conn.run(
                'SELECT COUNT(*) FROM "Client" WHERE "firstSeenAt" >= :a AND "firstSeenAt" < :b',
                a=launch_window_start_utc, b=launch_window_end_utc,
            )
            total_leads_allsource_forecast = int(_cl[0][0]) if _cl else 0
            logger.info(f"📊 Leads all-source (Client) na janela: {total_leads_allsource_forecast}")
        except Exception as _cle:
            logger.warning(f"⚠️ contagem Client all-source indisponível: {_cle}")

        # Segmentos por variante pro ML-aware: cada variante com a própria tabela
        # de taxa (Champion = global do business; Challenger = própria, se houver
        # via ABTestVariantConfig.conversion_rate_benchmark). Só ativa com A/B
        # ligado E mais de uma variante presente; senão None → pooled (idêntico).
        ml_aware_segments = None
        try:
            _abc = getattr(pipeline, '_ab_test_config', None) if pipeline else None
            if _abc and getattr(_abc, 'enabled', False) and len(forecast_decil_dist_by_variant) > 1:
                # Champion = arm default (sem utm_pattern e sem url_pattern) — mesma
                # identificação usada em leads_scored_by_variant_24h.
                _champ_name = next((n for n, v in _abc.variants.items()
                                    if not v.utm_pattern and not v.url_pattern), None)
                _segs = [
                    {
                        'variant': (_vk or _champ_name or 'champion'),
                        'decil_distribution': _vdist,
                        'benchmark': getattr(_abc.variants.get(_vk or _champ_name),
                                             'conversion_rate_benchmark', None),
                    }
                    for _vk, _vdist in forecast_decil_dist_by_variant.items()
                ]
                # Fail-loud: a soma por variante tem que bater com o pooled.
                _sv = sum(sum(d.values()) for d in forecast_decil_dist_by_variant.values())
                _sp = sum(forecast_decil_dist.values())
                if _sv != _sp:
                    logger.warning(f"⚠️ forecast split por variante: soma {_sv} != pooled {_sp} — caindo no pooled")
                else:
                    ml_aware_segments = _segs
        except Exception as _seg_e:
            logger.warning(f"⚠️ forecast ml_aware_segments indisponível: {_seg_e}")

        # 1e. Survey funnel metrics por janela histórica — Fatia D do refator.
        # Agregação pura em cima de `_records_90d` (já carregado pra Fatia D
        # quality_rows). Substitui 5 queries SQL na Lead morta. "historico"
        # cobre os 90d que o repository expõe (= todo o ledger novo hoje;
        # cresce naturalmente).
        from src.monitoring.daily_check_aggregations import compute_survey_funnel_db
        _sfm_db: Dict[str, Dict] = {}
        # "Ontem BRT completo" — 00:00→23:59 BRT do dia anterior. Substitui
        # a janela "rolling 24h" antiga (que divergia da Distribuição de
        # Decis 'Ontem' por ter cortes em horas diferentes).
        _brt_q = _tz(timedelta(hours=-3))
        _today_brt_mid_q = datetime.now(_brt_q).replace(hour=0, minute=0, second=0, microsecond=0)
        _dia_ant_start_utc = (_today_brt_mid_q - timedelta(days=1)).astimezone(_tz.utc)
        _dia_ant_end_utc   = _today_brt_mid_q.astimezone(_tz.utc)
        try:
            _sfm_windows_cut = {
                'historico':     _quality_window_start,            # 90d atrás
                'ultimo_mes':    now_utc - timedelta(days=30),
                'ultima_semana': now_utc - timedelta(days=7),
            }
            _sfm_db = compute_survey_funnel_db(
                _records_90d, windows=_sfm_windows_cut, anchor=now_utc,
            )
            # 'ultimas_24h' agora reflete "Ontem BRT completo" — chave mantida
            # pra compat com PAYLOAD_SCHEMA/Pydantic/digest. Anchor ≠ now, então
            # roda em chamada separada de compute_survey_funnel_db.
            _sfm_db['ultimas_24h'] = compute_survey_funnel_db(
                _records_90d,
                windows={'ultimas_24h': _dia_ant_start_utc},
                anchor=_dia_ant_end_utc,
            )['ultimas_24h']
            # `periodo_query` = janela do lançamento atual (cap_start → now).
            _sfm_db['periodo_query'] = compute_survey_funnel_db(
                _records_90d,
                windows={'periodo_query': launch_window_start_utc},
                anchor=launch_window_end_utc,
            )['periodo_query']
        except Exception as _sfm_e:
            logger.warning(f"⚠️ survey_funnel DB queries: {_sfm_e}")

        railway_conn.close()
        try:
            ledger_conn.close()
        except Exception:
            pass

        # ------------------------------------------------------------------
        # 2. Processar scored_rows → leads_data (para o orquestrador)
        # ------------------------------------------------------------------
        if not scored_rows:
            logger.info(f"⚠️ Railway: nenhum lead com score no período {window_label}")
            # Mesmo sem leads na Lead antiga (morta desde 2026-05-17), os
            # sumários novos (ledger novo e logs T1-16) têm vida própria.
            # Composição local: abre conn pg8000 → repo registros_ml → calcula.
            _ps_early, _td_early, _hl_early = None, None, None
            try:
                from src.data import compose_repository
                from src.data.ledger_connection import open_ledger_read_connection
                from src.monitoring.pubsub_summary import compute_pubsub_summary
                from src.monitoring.training_drift_summary import compute_training_drift_summary
                # Ledger pela fonte de LEDGER_READ_SOURCE (railway|cloudsql).
                _early_conn = open_ledger_read_connection()
                try:
                    _early_repo = compose_repository('registros_ml', railway_conn=_early_conn)
                    _ps_early = compute_pubsub_summary(_early_repo)
                finally:
                    try: _early_conn.close()
                    except Exception: pass
                _td_early = compute_training_drift_summary()
                # HotLeads: cron proprio, vida independente do fluxo de scoring.
                # Justamente no dia sem lead scoreado e que importa saber se ele
                # segue vivo — por isso entra tambem neste retorno antecipado.
                from src.monitoring.hotleads_summary import compute_hotleads_summary
                _hl_early = compute_hotleads_summary(
                    source_allowlist=(pipeline._client_config.capi.utm_source_allowlist or None)
                    if pipeline else None,
                    submit_window_days=(pipeline._client_config.hotleads.submit_window_days
                                        if pipeline else 7),
                )
            except Exception as _e:
                logger.warning(f"⚠️ early-return: falha calculando sumários top-level: {_e}")
            return DailyCheckResponse(
                total_alerts=0,
                alerts_by_severity={"HIGH": 0, "MEDIUM": 0, "LOW": 0},
                alerts_by_category={},
                alerts=[],
                critical_summary=f"Nenhum lead Railway no período {window_label}.",
                timestamp=datetime.now().isoformat(),
                pubsub_24h_summary=_ps_early,
                training_drift_24h_summary=_td_early,
                hotleads_24h_summary=_hl_early,
            )

        logger.info(f"🔍 Railway monitoring: {len(scored_rows)} leads com score — {window_label}")

        # `scored_rows` agora é `list[LeadRecord]` (do registros_ml via
        # LeadRepository), não mais tupla SQL crua da Lead antiga.
        # Conversão pra `leads_data` (formato que o orchestrator espera)
        # passa pela tradução slug→PT-Long que o railway_lead_to_sheets_row
        # exige (mesma tradução que pubsub_branch faz em produção).
        from api.railway_mapping import traduzir_survey_slugs
        leads_data = []
        for record in scored_rows:
            try:
                survey_pt = traduzir_survey_slugs(record.survey_responses or {})
            except ValueError as e:
                logger.warning(f"⚠️ skip lead {record.event_id[:8]}…: slug inválido ({e})")
                continue
            # `has_computer` vive top-level no ledger novo (não em survey_responses)
            # mas o railway_lead_to_sheets_row espera `pesquisa.computador` pra
            # popular a coluna 'Tem computador/notebook?'. Sem essa injeção, a
            # coluna chega 100% NULL no df do orchestrator e dispara
            # missing_rate_high HIGH falso-positivo todo daily-check.
            if record.has_computer and 'computador' not in survey_pt:
                survey_pt = {**survey_pt, 'computador': record.has_computer}
            nome_full = f"{(record.first_name or '').strip()} {(record.last_name or '').strip()}".strip() or None
            lead = {
                'id':            record.event_id,
                'data':          record.criado_em,
                'nomeCompleto':  nome_full,
                'email':         record.email,
                'telefone':      record.phone,
                'pesquisa':      survey_pt,
                'source':        record.utm_source,
                'medium':        record.utm_medium,
                'campaign':      record.utm_campaign,
                'content':       record.utm_content,
                'term':          record.utm_term,
                'remoteIp':      record.ip,
                'userAgent':     record.user_agent,
                'fbc':           record.fbc,
                'fbp':           record.fbp,
                'pageUrl':       record.utm_url,
                'leadScore':     record.score,
                'decil':         record.decil,
            }
            try:
                sheets_row = railway_lead_to_sheets_row(
                    lead, client_config=pipeline._client_config if pipeline else None
                )
                sheets_row['lead_score'] = float(record.score) if record.score is not None else None
                sheets_row['decil']      = f"D{record.decil:02d}" if record.decil is not None else None
                leads_data.append(sheets_row)
            except Exception as e:
                logger.warning(f"⚠️ Erro ao mapear lead {record.email}: {e}")

        logger.info(f"✅ {len(leads_data)} leads convertidos")

        # ------------------------------------------------------------------
        # 3. Construir funnel_metrics 100% Railway
        # ------------------------------------------------------------------
        stats = dict(zip(
            ['total', 'scored', 'capi_sent', 'capi_success', 'capi_error', 'with_phone'],
            stats_row[0]
        ))
        total = stats['total'] or 0
        capi_sent = stats['capi_sent'] or 0
        capi_success = stats['capi_success'] or 0
        capi_error = stats['capi_error'] or 0
        with_phone = stats['with_phone'] or 0

        fbp_stats = dict(zip(['with_fbp', 'with_fbc', 'total_meta_leads'], capi_fbp_row[0]))
        with_fbp = fbp_stats['with_fbp'] or 0
        with_fbc = fbp_stats['with_fbc'] or 0
        total_meta_leads_dq = fbp_stats['total_meta_leads'] or 0

        railway_funnel_metrics = {
            'window': {
                'start_utc': window_start.isoformat(),
                'end_utc': window_end.isoformat(),
                'start_brt': window_start.astimezone(brt).strftime('%d/%m/%Y %H:%M'),
                'end_brt': window_end.astimezone(brt).strftime('%d/%m/%Y %H:%M'),
            },
            'capture': {
                'total_database': total,
                'total_scored': stats['scored'] or 0,
            },
            'data_quality': {
                'total_leads': total,                              # leads no banco (Lead/pesquisa)
                'total_meta_leads': total_meta_leads_dq,           # leads Meta na janela (leads_capi)
                'fbp_present': with_fbp,
                'fbp_percentage': (with_fbp / total_meta_leads_dq * 100) if total_meta_leads_dq > 0 else 0,
                'fbc_present': with_fbc,
                'fbc_percentage': (with_fbc / total_meta_leads_dq * 100) if total_meta_leads_dq > 0 else 0,
                'phone_present': with_phone,
                'phone_percentage': (with_phone / total * 100) if total > 0 else 0,
                'fbp_fbc_rolling': fbp_fbc_rolling,
            },
            'unified_funnel': unified_funnel,
            'survey_response_rate': survey_response_rate,
            'scoring': {
                'total_scored': len(leads_data),
                'decil_distribution': {},
                'avg_score': None,
            },
            'capi_sent': {
                'leads_sent': capi_sent,
                'send_rate': (capi_sent / total * 100) if total > 0 else 0,
                'estimated_events': int(capi_sent * 1.3),
            },
            'meta_response': {
                'leads_with_response': capi_sent,
                'success_count': capi_success,
                'error_count': capi_error,
                'partial_count': 0,
                'acceptance_rate': (capi_success / capi_sent * 100) if capi_sent > 0 else 0,
                # Railway não armazena eventos individuais recebidos/rejeitados pela Meta
                'events_received': None,
                'events_rejected': None,
            },
            'conversion': {
                # No Railway pesquisa e inscrição chegam juntos — 100% dos leads têm pesquisa
                'total_with_survey': stats['scored'] or 0,
                'survey_rate': 100.0 if (stats['scored'] or 0) > 0 else 0,
            },
        }

        # Distribuição de decis e score médio dos leads da janela
        if leads_data:
            decil_dist: dict = {}
            scores = []
            for ld in leads_data:
                d = ld.get('decil')
                if d:
                    decil_dist[d] = decil_dist.get(d, 0) + 1
                s = ld.get('lead_score')
                if s is not None:
                    scores.append(s)
            railway_funnel_metrics['scoring']['decil_distribution'] = decil_dist
            railway_funnel_metrics['scoring']['avg_score'] = (
                sum(scores) / len(scores) if scores else None
            )

        # ------------------------------------------------------------------
        # 4. Construir lead_quality_metrics 100% Railway
        # ------------------------------------------------------------------
        def _calc_quality(rows_subset):
            if not rows_subset:
                return {'score': 0, 'd9': 0, 'd10': 0, 'count': 0}
            scores_q = [r[0] for r in rows_subset if r[0] is not None]
            decils_q  = [r[1] for r in rows_subset if r[1] is not None]
            n = len(rows_subset)
            return {
                'score': sum(scores_q) / len(scores_q) if scores_q else 0,
                'd9':  (sum(1 for d in decils_q if d == 9)  / n * 100) if n > 0 else 0,
                'd10': (sum(1 for d in decils_q if d == 10) / n * 100) if n > 0 else 0,
                'count': n,
            }

        # Cortes em UTC — Railway armazena createdAt em UTC
        now_utc_q = datetime.now(_tz.utc)
        cut_week  = now_utc_q - timedelta(days=7)
        cut_month = now_utc_q - timedelta(days=30)

        def _after(rows_q, cutoff):
            # quality_rows: (leadScore, decil, createdAt)
            # Garante comparação UTC vs UTC
            result_q = []
            for r in rows_q:
                created = r[2]
                if created is None:
                    continue
                if hasattr(created, 'tzinfo') and created.tzinfo is None:
                    created = created.replace(tzinfo=_tz.utc)  # assume UTC se naive
                if created >= cutoff:
                    result_q.append(r)
            return result_q

        def _between(rows_q, start, end):
            # quality_rows: (leadScore, decil, createdAt) — [start, end)
            result_q = []
            for r in rows_q:
                created = r[2]
                if created is None:
                    continue
                if hasattr(created, 'tzinfo') and created.tzinfo is None:
                    created = created.replace(tzinfo=_tz.utc)
                if start <= created < end:
                    result_q.append(r)
            return result_q

        # 'ultimas_24h' agora reflete "Ontem BRT completo" (00:00→23:59 BRT
        # do dia anterior). Mantém a chave do payload pra compat com PAYLOAD_SCHEMA;
        # o digest mostra o label "Ontem" no header. Substitui rolling 24h que
        # divergia da Distribuição de Decis 'Ontem'.
        railway_lead_quality = {
            'historico':     _calc_quality(quality_rows),
            'ultimo_mes':    _calc_quality(_after(quality_rows, cut_month)),
            'ultima_semana': _calc_quality(_after(quality_rows, cut_week)),
            'ultimas_24h':   _calc_quality(_between(quality_rows, _dia_ant_start_utc, _dia_ant_end_utc)),
        }

        # `count` = TOTAL de leads na tabela `Lead` (pesquisa preenchida), não só
        # scoreados. Pedido do usuário: na tabela de séries temporais, mostrar o
        # universo completo de leads que entrou na janela — score/d9/d10
        # continuam calculados sobre o subset scoreado (única forma viável), mas
        # n leads reflete o total. O delta (total − scoreados) sai indiretamente
        # via Funil ("leads db" vs "Scoreados") quando precisar.
        try:
            for _w in ('historico', 'ultimo_mes', 'ultima_semana', 'ultimas_24h'):
                if _w in railway_lead_quality and _w in _sfm_db:
                    railway_lead_quality[_w]['count'] = int(_sfm_db[_w].get('db_leads', 0) or 0)
        except Exception as _ce:
            logger.warning(f"⚠️ lead_quality count override (4 janelas) falhou: {_ce}")

        # Decis distribution por janela - usado no digest do cliente (2 barras horizontais).
        # O cálculo (Total + by_source Meta/Google + by_optgoal Lead/Champion/Challenger na
        # régua ÚNICA do Challenger abr_28, contra a ref única, com fail-soft pra régua de
        # produção) foi extraído pra src/monitoring/decis_by_channel.py - fonte única
        # compartilhada com o endpoint de dashboard /monitoring/audience-quality, pra os
        # números baterem por construção. quality_rows = [(leadScore, decil, createdAt, source, ...), ...].
        from src.monitoring.decis_by_channel import (
            resolve_decis_context, build_decis_window_payload, records_between,
        )
        _decis_ctx = resolve_decis_context(pipeline)

        # Ontem completo BRT (00:00→23:59 BRT do dia anterior)
        _brt = _tz(timedelta(hours=-3))
        _today_brt_midnight = datetime.now(_brt).replace(hour=0, minute=0, second=0, microsecond=0)
        _yesterday_brt_midnight = _today_brt_midnight - timedelta(days=1)
        _yest_start_utc = _yesterday_brt_midnight.astimezone(_tz.utc)
        _yest_end_utc = _today_brt_midnight.astimezone(_tz.utc)
        _yest_rows = [r for r in quality_rows
                      if r[2] is not None and (
                          r[2].replace(tzinfo=_tz.utc) if (hasattr(r[2], 'tzinfo') and r[2].tzinfo is None) else r[2]
                      ) >= _yest_start_utc and (
                          r[2].replace(tzinfo=_tz.utc) if (hasattr(r[2], 'tzinfo') and r[2].tzinfo is None) else r[2]
                      ) < _yest_end_utc]
        railway_lead_quality['decil_distribution_previous_day'] = build_decis_window_payload(
            window_label='Ontem', start_utc=_yest_start_utc, end_utc=_yest_end_utc,
            pin_lf=False, lf_name=None, ctx=_decis_ctx, fallback_rows=_yest_rows,
            fallback_records=records_between(_records_90d_scored, _yest_start_utc, _yest_end_utc, False),
        )

        # Qualidade do LF de referência — apenas LF ativo no launches.yaml,
        # sem fallback ao encerrado (vide commit que adicionou src/core/launches.py).
        try:
            # lf_referencia = qualidade do LF atual. Usa `resolve_launch_window_brt`
            # (não `resolve_active_launch_brt`): se o LF atual não está cadastrado
            # no `launches.yaml`, cai no fallback heurístico (toda segunda começa um
            # LF) e popula com nome inferido — assim a tabela de Drift de Decis no
            # DM aparece mesmo com YAML defasado. O aviso no topo da DM
            # (`_slack_launch_fallback_notice_dm`) lembra de cadastrar.
            from src.core.launches import resolve_launch_window_brt
            _lw = resolve_launch_window_brt(today=_anchor)
            _today_brt = _anchor or datetime.now(brt).date()
            _cap_end_eff = _lw.cap_end or _today_brt
            _ln = _lw.lf_name or 'LF atual (inferido)'
            _cs_dt = datetime(_lw.cap_start.year, _lw.cap_start.month, _lw.cap_start.day,
                              0, 0, 0, tzinfo=brt).astimezone(_tz.utc)
            _ce_dt = datetime(_cap_end_eff.year, _cap_end_eff.month, _cap_end_eff.day,
                              23, 59, 59, tzinfo=brt).astimezone(_tz.utc)
            _lf_rows = [r for r in quality_rows
                        if r[2] is not None and (
                            r[2].replace(tzinfo=_tz.utc) if (hasattr(r[2], 'tzinfo') and r[2].tzinfo is None) else r[2]
                        ) >= _cs_dt and (
                            r[2].replace(tzinfo=_tz.utc) if (hasattr(r[2], 'tzinfo') and r[2].tzinfo is None) else r[2]
                        ) <= _ce_dt]
            railway_lead_quality['lf_referencia'] = _calc_quality(_lf_rows)
            railway_lead_quality['lf_referencia_label'] = _ln
            try:
                if 'periodo_query' in _sfm_db:
                    railway_lead_quality['lf_referencia']['count'] = int(
                        _sfm_db['periodo_query'].get('db_leads', 0) or 0
                    )
            except Exception as _ce:
                logger.warning(f"⚠️ lead_quality lf_referencia count override falhou: {_ce}")
            railway_lead_quality['decil_distribution_current_launch'] = build_decis_window_payload(
                window_label=f"{_ln} ({_lw.cap_start.strftime('%d/%m')}→{_cap_end_eff.strftime('%d/%m')} BRT)",
                start_utc=_cs_dt, end_utc=_ce_dt, pin_lf=False, lf_name=None,
                ctx=_decis_ctx, fallback_rows=_lf_rows,
                fallback_records=records_between(_records_90d_scored, _cs_dt, _ce_dt, True),
            )
            # Refresh incremental ONLINE da scores_historicos: DESLIGADO por padrão
            # (Fase 5a). Depois que a Fase 3 passou a ler o decil direto do ledger
            # (`registros_ml`, flag LEDGER_DECIL_READ_SOURCE=ledger), re-scorear os
            # leads do LF pra dentro da `scores_historicos` virou peso morto: o
            # relatório não lê mais dela. E era ISTO que carregava os 2 modelos e
            # estourava a memória (OOM 2198/2048 MiB) derrubando o digest do DM das
            # 06:20 de forma intermitente. Fica atrás de um flag SÓ pra rollback:
            # REPORT_SCORES_REFRESH=on volta o comportamento antigo; default 'off'.
            _refresh_on = os.environ.get(
                "REPORT_SCORES_REFRESH", "off").strip().lower() in ("on", "true", "1", "yes")
            if _refresh_on and _anchor is None and pipeline is not None and _lw.lf_name:
                try:
                    from api.scores_refresh import refresh_launch_scores
                    _rf = refresh_launch_scores(
                        lf_name=_lw.lf_name,
                        cap_start=_lw.cap_start.isoformat(),
                        cap_end=_cap_end_eff.isoformat(),
                        pipeline=pipeline,
                    )
                    logger.info(f"🔄 scores_historicos refresh: {_rf}")
                except Exception as _rfe:
                    logger.warning(f"⚠️ scores_historicos refresh falhou (segue sem): {_rfe}")
            # Score geral do lançamento — decil médio da população pela régua do
            # Challenger, lido da scores_historicos (Cloud SQL). Leitura pura,
            # guardada: se falhar, só não mostra a nota (não derruba o relatório).
            try:
                from src.data.scores_historicos import launch_score_geral
                _sg = launch_score_geral(_lw.lf_name)
                if _sg:
                    railway_lead_quality['decil_distribution_current_launch']['score_geral'] = _sg
            except Exception as _sge:
                logger.warning(f"⚠️ score_geral falhou: {_sge}")
            logger.info(f"📊 lf_referencia: {_ln} "
                        f"({_lw.cap_start}→{_cap_end_eff}, source={_lw.source}, n={len(_lf_rows)})")
        except Exception as _lf_e:
            logger.warning(f"⚠️ lf_referencia falhou: {_lf_e}")

        # ------------------------------------------------------------------
        # 5. Executar orquestrador (apenas para alertas de drift/qualidade ML)
        # ------------------------------------------------------------------
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'configs/active_models/devclub.yaml'
        )
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            active_model = config['active_model']
            if 'mlflow_run_id' in active_model:
                model_path = os.path.join('mlruns', '1', active_model['mlflow_run_id'], 'artifacts')
            else:
                model_path = active_model['model_path']

        if not os.path.isabs(model_path):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_path = os.path.join(base_dir, model_path)

        # E6: rolling 30d via Railway (Lead.decil) — usado como baseline em
        # _check_score_distribution. Cálculo aqui porque o orchestrator/DataQualityMonitor
        # recebe db=Cloud SQL legacy, que não tem a tabela Lead.
        # Conexão original `railway_conn` já fechou em 2468 — abrir nova dedicada.
        expected_decil_dist = None
        _e6_conn = None
        try:
            _e6_conn = pg8000.native.Connection(
                host=os.environ['RAILWAY_DB_HOST'],
                port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
                database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
                user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
                password=os.environ['RAILWAY_DB_PASSWORD'],
                timeout=30,
            )
            _r30 = _e6_conn.run(
                'SELECT decil, COUNT(*) FROM "Lead" '
                'WHERE "createdAt" >= NOW() - INTERVAL \'31 days\' '
                '  AND "createdAt" <  NOW() - INTERVAL \'1 day\' '
                '  AND decil IS NOT NULL '
                'GROUP BY decil'
            )
            _total_30d = sum(int(r[1]) for r in _r30) if _r30 else 0
            if _total_30d < 1000:
                # Tabela "Lead" morta (17/05) esvazia a janela de 31d em ~18/06.
                # Fallback: ledger registros_ml usa o que tiver desde 23/05
                # (PLANO_LEDGER_CLOUDSQL.md §3.3). Lê pela fonte escolhida por
                # LEDGER_READ_SOURCE (railway|cloudsql) — não pela conn do Railway,
                # que perde a tabela no DROP da Etapa 5.
                from src.data.ledger_connection import open_ledger_read_connection
                _e6_ledger_conn = open_ledger_read_connection()
                try:
                    _r30 = _e6_ledger_conn.run(
                        'SELECT decil, COUNT(*) FROM registros_ml '
                        "WHERE created_at >= NOW() - INTERVAL '31 days' "
                        "  AND created_at <  NOW() - INTERVAL '1 day' "
                        '  AND decil IS NOT NULL '
                        'GROUP BY decil'
                    )
                finally:
                    _e6_ledger_conn.close()
                _total_30d = sum(int(r[1]) for r in _r30) if _r30 else 0
            if _total_30d >= 1000:
                # Normaliza decil pro formato D1..D10 (sem leading zero) — formato usado
                # internamente em _check_score_distribution após decil_normalized regex.
                def _norm_decil(v):
                    s = str(v).strip()
                    if s.startswith('D'):
                        s = s[1:]
                    n = int(s)
                    return f'D{n}'
                _dist = {f'D{i}': 0.0 for i in range(1, 11)}
                for r in _r30:
                    try:
                        _dist[_norm_decil(r[0])] = int(r[1]) / _total_30d
                    except (ValueError, KeyError):
                        pass
                expected_decil_dist = dict(_dist)
                expected_decil_dist['_source'] = f'rolling_30d_n={_total_30d}'
                logger.info(f"📊 E6 baseline: rolling 30d n={_total_30d:,}, D10={_dist['D10']*100:.1f}%")
        except Exception as _e:
            logger.warning(f"⚠️ E6: falha calcular rolling 30d via Railway: {_e}")
        finally:
            if _e6_conn is not None:
                try:
                    _e6_conn.close()
                except Exception:
                    pass

        # A railway_conn original foi fechada em 2715 (depois das 13 queries
        # iniciais). O orchestrator precisa de conn viva pra compor o
        # LeadRepository (registros_ml). Fonte por LEDGER_READ_SOURCE
        # (Railway/Cloud SQL) — PLANO_LEDGER_CLOUDSQL.md Etapa 3. Vida ligada
        # ao orchestrator (fechada no finally abaixo).
        from src.data.ledger_connection import open_ledger_read_connection
        orchestrator_conn = open_ledger_read_connection()
        orchestrator = MonitoringOrchestrator(model_path=model_path, db=None,
                                              expected_decil_dist=expected_decil_dist,
                                              lead_scoring_pipeline=pipelines.get('devclub'),
                                              railway_conn=orchestrator_conn)
        # Propaga include_today_partial pro DataQualityMonitor.
        # Default OFF: cron das 6 AM não traz "Hoje parcial" (madrugada com sample irrelevante).
        # Manual: ?include_today_partial=true pra ver coluna Hoje em chamadas durante o dia.
        try:
            orchestrator.monitors['data_quality'].include_today_partial = bool(include_today_partial)
        except Exception:
            pass
        try:
            # prev_day_window = "ontem BRT completo" (mesma fronteira que o survey
            # funnel e o Drift/Decis já usam) — alinha as contagens por variante do
            # bloco A/B à janela do spend Meta. A seção Meta inteira é now-based hoje,
            # então anchor histórico não muda essa janela (dívida conhecida).
            result = orchestrator.run_daily_check(
                leads_data, anchor_date=_anchor,
                prev_day_window=(_dia_ant_start_utc, _dia_ant_end_utc),
            )
        finally:
            try: orchestrator_conn.close()
            except Exception: pass

        # Substituir funnel_metrics e lead_quality_metrics pelos dados Railway
        result['funnel_metrics'] = railway_funnel_metrics
        result['lead_quality_metrics'] = railway_lead_quality

        # Buscar métricas Meta Ads (campanhas CAP, hoje) — falha silenciosa
        meta_metrics = None
        total_meta_leads_forecast = 0   # leads Meta na janela do lançamento — usado no revenue_forecast
        try:
            from api.meta_integration import MetaAdsIntegration
            from api.meta_config import META_CONFIG
            _token = os.getenv('META_ACCESS_TOKEN')
            _account = os.getenv('META_ACCOUNT_ID', META_CONFIG.get('account_id', 'act_188005769808959'))
            if _token:
                _today      = datetime.now(_tz(timedelta(hours=-3))).strftime('%Y-%m-%d')
                # "Ontem BRT" (dia anterior completo) — janela do spend do bloco A/B.
                # Bate com o que o operador vê na Meta por dia e com Drift/Decis 'Ontem'.
                # Antes o spend ia de ontem até hoje (`until` inclusivo da Meta), somando
                # ontem + parte de hoje. Reusado no bloco de janelas históricas abaixo.
                _dia_ant_str = (datetime.now(_tz(timedelta(hours=-3))) - timedelta(days=1)).strftime('%Y-%m-%d')
                _launch_str = launch_window_start.strftime('%Y-%m-%d')
                _meta = MetaAdsIntegration(access_token=_token)

                # --- métricas do dia (spend/clicks) ---
                _rows_hoje = _meta.get_insights(
                    account_id=_account,
                    level='campaign',
                    fields=['campaign_name', 'spend', 'clicks'],
                    since_date=_today,
                    until_date=_today,
                    filtering=[{'field': 'campaign.name', 'operator': 'CONTAIN', 'value': 'CAP'}]
                )
                _spend  = sum(float(r.get('spend', 0) or 0) for r in _rows_hoje)
                _clicks = sum(int(r.get('clicks', 0) or 0) for r in _rows_hoje)
                _midnight_brt = datetime.now(brt).replace(hour=0, minute=0, second=0, microsecond=0)
                _midnight_utc = _midnight_brt.astimezone(_tz.utc)
                _leads_hoje = len(_after(quality_rows, _midnight_utc))
                meta_metrics = {
                    'date':             _today,
                    'spend':            _spend,
                    'clicks':           _clicks,
                    'cpl':              (_spend / _leads_hoje) if _leads_hoje > 0 else None,
                    'taxa_clique_lead': (_leads_hoje / _clicks * 100) if _clicks > 0 else None,
                }
                logger.info(f"📊 Meta Ads CAP: spend=R${_spend:.2f}, clicks={_clicks}, leads={_leads_hoje}")

                # --- total de leads Meta desde o início da janela de lançamento ---
                # Usado pelo revenue_forecast (flat-rate) como denominador real da população.
                # Inclui leads que não responderam à pesquisa e não chegam ao DB.
                # Janela fechada: quando start_date/end_date são passados (chamada
                # individual de um LF já encerrado), o fim é end_date — espelha o que
                # o caminho do YAML (lf_anterior) já faz com cap_end. Sem isso, a
                # query iria de start_date até hoje e inflaria o denominador com os
                # LFs seguintes. No fluxo padrão (LF ativo) segue indo até hoje.
                _launch_until = end_date if (start_date and end_date) else _today
                _rows_launch = _meta.get_insights(
                    account_id=_account,
                    level='campaign',
                    fields=['campaign_name', 'actions'],
                    since_date=_launch_str,
                    until_date=_launch_until,
                    filtering=[{'field': 'campaign.name', 'operator': 'CONTAIN', 'value': 'CAP'}]
                )
                for _r in _rows_launch:
                    for _a in (_r.get('actions') or []):
                        if _a.get('action_type') == 'offsite_conversion.fb_pixel_lead':
                            total_meta_leads_forecast += int(_a.get('value', 0) or 0)
                logger.info(f"📊 Meta leads janela lançamento ({_launch_str}–{_launch_until}): {total_meta_leads_forecast}")

                # --- spend Meta por variante A/B (janela 24h, alinhada com leads_capi_by_variant_24h) ---
                # Split por campaign.name: Challenger = casa com utm_pattern.utm_campaign do YAML; Champion = demais.
                # CPL usa leads_capi_by_variant_24h (já calculado em operational_routines).
                try:
                    _ab_cfg_local = getattr(pipeline, '_ab_test_config', None) if pipeline else None
                    _challenger_pat = None
                    _challenger_name = None
                    _champion_name = None
                    if _ab_cfg_local and _ab_cfg_local.enabled:
                        for _vname, _vc in _ab_cfg_local.variants.items():
                            _pat = (_vc.utm_pattern or {}).get('utm_campaign')
                            if _pat:
                                _challenger_pat = _pat
                                _challenger_name = _vname
                            elif not _vc.utm_pattern and not _vc.url_pattern:
                                _champion_name = _vname
                    if _challenger_pat and _challenger_name and _champion_name:
                        _rows_24h_v = _meta.get_insights(
                            account_id=_account, level='campaign',
                            fields=['campaign_name', 'spend'],
                            since_date=_dia_ant_str, until_date=_dia_ant_str,
                            filtering=[{'field': 'campaign.name', 'operator': 'CONTAIN', 'value': 'CAP'}]
                        )
                        _spend_v = {_champion_name: 0.0, _challenger_name: 0.0}
                        for _r in _rows_24h_v:
                            _cn = (_r.get('campaign_name') or '').lower()
                            _sp = float(_r.get('spend', 0) or 0)
                            # utm_pattern carrega LISTA de substrings por campo (um modelo pode
                            # servir campanhas de gerações diferentes) — basta uma casar.
                            if any(_p.lower() in _cn for _p in _challenger_pat):
                                _spend_v[_challenger_name] += _sp
                            else:
                                _spend_v[_champion_name] += _sp
                        result.setdefault('operational_routines', {})['spend_by_variant_24h_brl'] = _spend_v
                        _leads_v = (result.get('operational_routines', {}) or {}).get('leads_capi_by_variant_24h') or {}
                        _cpl_v: Dict[str, Optional[float]] = {}
                        for _vn, _sp in _spend_v.items():
                            _n = int(_leads_v.get(_vn) or 0)
                            _cpl_v[_vn] = round(_sp / _n, 2) if _n > 0 else None
                        result['operational_routines']['cpl_by_variant_24h_brl'] = _cpl_v
                        logger.info(f"📊 Meta spend 24h por variante: {_spend_v} · CPL: {_cpl_v}")
                except Exception as _e:
                    logger.warning(f"⚠️ spend/cpl por variante (24h): {_e}")

                # --- spend Meta 24h split por optimization_goal (ML vs Lead padrão) ---
                # Filtro `campaign.name CONTAIN 'CAP'` — MESMO escopo do
                # `spend_by_variant_24h_brl` acima (só campanhas de captação,
                # excluindo vendas/retargeting/brand). Garante coerência:
                # total ML + total Lead padrão = Champion spend + Challenger spend.
                # Sem esse filtro, a soma da linha de otimização ficava maior
                # que a soma das variants e confundia o operador.
                try:
                    _adsets_cap = _meta.get_insights(
                        account_id=_account, level='adset',
                        fields=['adset_id', 'spend'],
                        since_date=_dia_ant_str, until_date=_dia_ant_str,
                        filtering=[{'field': 'campaign.name', 'operator': 'CONTAIN', 'value': 'CAP'}],
                    )
                    # Eventos de ML DERIVADOS do YAML (dono único: core.client_config).
                    # Era uma lista chumbada {LeadQualified, LeadQualifiedHighQuality,
                    # HQLB, HQLB_LQ} que não conhecia os eventos criados depois. Com o
                    # jul_24 no ar desde 29/07/2026 e as campanhas novas desde 09/08, o
                    # gasto delas caía todo em "Lead padrão": em 17/08 o relatório do
                    # grupo publicou "0% em ML" enquanto R$ 4.528,70 dos R$ 8.098,72 do
                    # dia estavam em adsets otimizando por jul_24_top50 (R$ 3.317,19),
                    # jul_24_top30 (R$ 713,34) e abr_28_top30 (R$ 498,17). Agora modelo
                    # novo entra com 1 edição no YAML, sem código a reboque.
                    from src.core.client_config import ml_event_names
                    _ML_EVENTS = ml_event_names(
                        getattr(pipeline, '_client_config', None) if pipeline else None,
                        getattr(pipeline, '_ab_test_config', None) if pipeline else None,
                    )
                    if not _ML_EVENTS:
                        logger.warning(
                            "⚠️ nenhum evento de ML declarado no config — split ML vs Lead "
                            "padrão sai 100%% Lead. Config carregou?"
                        )
                    # Pré-filtra adsets com spend > 0 e coleta IDs únicos pro batch.
                    _adsets_with_spend = [
                        (_row.get('adset_id'), float(_row.get('spend') or 0))
                        for _row in _adsets_cap
                        if _row.get('adset_id') and float(_row.get('spend') or 0) > 0
                    ]
                    _unique_aids = sorted({_aid for _aid, _ in _adsets_with_spend})
                    # 1 HTTP call por chunk de 50 em vez de 1 por adset.
                    _optgoals = _meta.batch_get_adset_optimization_goals(_unique_aids)
                    _spend_ml = 0.0
                    _spend_nonml = 0.0
                    for _aid, _sp in _adsets_with_spend:
                        _og = _optgoals.get(_aid)
                        if _og in _ML_EVENTS:
                            _spend_ml += _sp
                        else:
                            _spend_nonml += _sp
                    result.setdefault('operational_routines', {})['spend_ml_24h_brl'] = round(_spend_ml, 2)
                    result['operational_routines']['spend_nonml_24h_brl'] = round(_spend_nonml, 2)
                    logger.info(
                        f"📊 Meta spend 24h por evento de otimização (captação only): "
                        f"ML R$ {_spend_ml:.2f} · Lead padrão R$ {_spend_nonml:.2f} "
                        f"(batch: {len(_unique_aids)} adsets)"
                    )
                except Exception as _e:
                    logger.warning(f"⚠️ spend ML vs Lead padrão (24h): {_e}")

                # --- métricas Meta por janela histórica (para survey_funnel_metrics e traffic_metrics) ---
                # ultimo_mes removido do fetch Meta: a chamada com filtro
                # CONTAIN 'CAP' em janela de 30d frequentemente excede o
                # timeout de 12s do executor abaixo, retornando None e
                # rendendo coluna "mês" vazia no Tráfego Meta. Survey funnel
                # e lead quality mantêm "mês" próprio via DB.
                _brt_now = datetime.now(_tz(timedelta(hours=-3)))
                # _dia_ant_str já definido no topo do bloco Meta (janela do spend A/B)
                _meta_hist_windows = {
                    'ultima_semana': (_brt_now - timedelta(days=7)).strftime('%Y-%m-%d'),
                    'ultimas_24h':   (_brt_now - timedelta(hours=24)).strftime('%Y-%m-%d'),
                    'dia_anterior':  _dia_ant_str,   # dia BRT anterior completo (funil unificado)
                    'periodo_query': _launch_str,
                }
                _meta_hist_end = {
                    'ultima_semana': _today,
                    'ultimas_24h':   _today,
                    'dia_anterior':  _dia_ant_str,   # since=until=ontem → dia completo
                    'periodo_query': (_brt_now if not end_date else
                                      datetime.strptime(end_date, '%Y-%m-%d').replace(
                                          tzinfo=_tz(timedelta(hours=-3))
                                      )).strftime('%Y-%m-%d'),
                }
                meta_window_data: Dict[str, Any] = {}

                def _fetch_meta_window(_wlbl, _wsince, _wuntil):
                    _wrows = _meta.get_insights(
                        account_id=_account,
                        level='campaign',
                        fields=['campaign_name', 'spend', 'clicks', 'actions'],
                        since_date=_wsince,
                        until_date=_wuntil,
                        filtering=[{'field': 'campaign.name', 'operator': 'CONTAIN', 'value': 'CAP'}]
                    )
                    _w_spend  = sum(float(r.get('spend',  0) or 0) for r in _wrows)
                    _w_clicks = sum(int(r.get('clicks', 0) or 0) for r in _wrows)
                    _w_leads  = 0
                    for _wr in _wrows:
                        for _wa in (_wr.get('actions') or []):
                            if _wa.get('action_type') == 'offsite_conversion.fb_pixel_lead':
                                _w_leads += int(_wa.get('value', 0) or 0)
                    return {
                        'meta_leads': _w_leads,
                        'clicks':     _w_clicks,
                        'spend':      round(_w_spend, 2),
                        'cpl':        round(_w_spend / _w_leads, 2) if _w_leads > 0 else None,
                        'ctr_lead':   round(_w_leads / _w_clicks * 100, 1) if _w_clicks > 0 else None,
                    }

                import concurrent.futures as _cf
                _meta_futures = {}
                with _cf.ThreadPoolExecutor(max_workers=4) as _executor:
                    for _wlbl, _wsince in _meta_hist_windows.items():
                        _meta_futures[_wlbl] = _executor.submit(
                            _fetch_meta_window, _wlbl, _wsince, _meta_hist_end[_wlbl]
                        )
                for _wlbl, _fut in _meta_futures.items():
                    try:
                        meta_window_data[_wlbl] = _fut.result(timeout=12)
                    except Exception as _we:
                        logger.warning(f"⚠️ Meta window {_wlbl}: {_we}")
                        meta_window_data[_wlbl] = None

                # --- CPL real + conversão de LP por variante (dia anterior) ---
                # 3 buckets Lead/Champion/Challenger pelo NOME da campanha
                # (validation.campaign_classifier.classify_variant — o critério do
                # arquivo de validação do LF, deliberadamente NÃO o optimization_goal
                # do adset). EXTERNO (Google/orgânico/não-captação) fica de fora.
                #   Numerador (leads reais) = tabela Client (TODOS os leads
                #     captados, não respostas de pesquisa).
                #   Denominador custo/conv = spend + landing_page_views da Meta
                #     Insights por campanha.
                # Falha silenciosa: só anexa se conseguir os dois lados.
                try:
                    from src.validation.campaign_classifier import classify_variant as _classify_variant
                    from src.monitoring.daily_check_aggregations import compute_variant_cpl_conv as _variant_cpl
                    _PV_BUCKETS = ('Lead', 'Champion', 'Challenger')
                    # Imposto da Meta (PIS/COFINS+ISS, BR 2026) — entra só no CPL
                    # (custo real); vem do ClientConfig (default 0.0). Aplica nas
                    # duas janelas (diário e lançamento).
                    _tax = float(
                        (pipeline._client_config.monitoring.meta_tax_rate
                         if pipeline and pipeline._client_config and pipeline._client_config.monitoring
                         else 0.0) or 0.0
                    )

                    # Helper local: CPL/conv por variante numa janela [since,until] Meta
                    # + [fs_a,fs_b] de firstSeenAt (BRT) na Client. Reusado pro diário
                    # e pro acumulado do lançamento — mesma forma da query, sem duplicar.
                    def _pv_for_window(since_s, until_s, fs_a, fs_b):
                        _raw = _meta.get_insights(
                            account_id=_account, level='campaign',
                            fields=['campaign_name', 'spend', 'actions'],
                            since_date=since_s, until_date=until_s,
                            filtering=[{'field': 'campaign.name', 'operator': 'CONTAIN', 'value': 'CAP'}],
                        )
                        _mrows = []
                        for _mr in _raw:
                            _lpv = 0
                            for _a in (_mr.get('actions') or []):
                                if _a.get('action_type') == 'landing_page_view':
                                    _lpv = int(float(_a.get('value', 0) or 0))
                                    break
                            _mrows.append({
                                'campaign_name': _mr.get('campaign_name'),
                                'spend': float(_mr.get('spend', 0) or 0),
                                'lpv': _lpv,
                            })
                        _c = pg8000.native.Connection(
                            host=os.environ['RAILWAY_DB_HOST'],
                            port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
                            database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
                            user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
                            password=os.environ['RAILWAY_DB_PASSWORD'],
                            timeout=60,
                        )
                        try:
                            _rows = _c.run(
                                'SELECT LOWER(TRIM(c.email)) AS email, u.campaign, u."trackedAt" '
                                'FROM "Client" c '
                                'JOIN "UTMTracking" u ON LOWER(TRIM(u."clientEmail")) = LOWER(TRIM(c.email)) '
                                'WHERE (c."firstSeenAt" - INTERVAL \'3 hours\')::date >= :a '
                                'AND (c."firstSeenAt" - INTERVAL \'3 hours\')::date <= :b',
                                a=fs_a, b=fs_b,
                            )
                        finally:
                            try: _c.close()
                            except Exception: pass
                        _by_email: Dict[str, tuple] = {}
                        for _em, _cmp, _tat in _rows:
                            if _classify_variant(_cmp) not in _PV_BUCKETS:
                                continue
                            _prev = _by_email.get(_em)
                            if _prev is None or (_tat is not None and (_prev[1] is None or _tat >= _prev[1])):
                                _by_email[_em] = (_cmp, _tat)
                        return _variant_cpl(
                            meta_rows=_mrows,
                            client_campaigns=[v[0] for v in _by_email.values()],
                            classify_fn=_classify_variant,
                            tax_rate=_tax,
                        )

                    # Diário (dia anterior completo).
                    _pv_result = _pv_for_window(_dia_ant_str, _dia_ant_str, _dia_ant_str, _dia_ant_str)
                    if isinstance(meta_window_data.get('dia_anterior'), dict):
                        meta_window_data['dia_anterior']['por_variante'] = _pv_result
                        logger.info(
                            "📊 Por variante (dia anterior): " + " · ".join(
                                f"{_b}: {_d['leads']} leads, CPL {_d['cpl']}, LP {_d['conv_lp']}%"
                                for _b, _d in _pv_result.items()
                            )
                        )

                    # TOTAL de cadastros Meta do dia — a linha que faltava no funil.
                    # O split por variante acima conta só quem tem campanha reconhecida
                    # como Lead/Champion/Challenger e DESCARTA o resto, então o número
                    # dele (ex.: "Lead 136") é um SUBCONJUNTO, não o total da Meta — e
                    # lido sozinho passa a impressão de que a Meta trouxe quase nada.
                    # Aqui contamos por FONTE (utm_source), sem depender da campanha,
                    # reusando a MESMA leitura de cadastros que o funil do Google usa
                    # (por isso o total Meta e o total Google são comparáveis: ambos
                    # saem da Client, fechados por createdAt, deduplicados por email).
                    # Guardado: se falhar, o funil sai como antes, sem a linha.
                    try:
                        from src.data.cadastro_records import (
                            open_railway_connection as _open_rail_m,
                            google_cadastro_records as _cadastros_por_fonte,
                        )
                        _meta_srcs = list(
                            (pipeline._client_config.capi.utm_source_allowlist or [])
                            if (pipeline and pipeline._client_config and pipeline._client_config.capi)
                            else []
                        )
                        if _meta_srcs and isinstance(meta_window_data.get('dia_anterior'), dict):
                            _rc_m = _open_rail_m()
                            try:
                                _meta_cad = _cadastros_por_fonte(
                                    _rc_m, _dia_ant_str, _dia_ant_str, _meta_srcs)
                            finally:
                                try: _rc_m.close()
                                except Exception: pass
                            meta_window_data['dia_anterior']['total_cadastros'] = len(_meta_cad)
                            logger.info(
                                f"📊 Total de cadastros Meta (dia anterior): {len(_meta_cad)} "
                                f"(fontes: {_meta_srcs})"
                            )
                    except Exception as _mce:
                        logger.warning(f"⚠️ total de cadastros Meta indisponível (funil segue sem): {_mce}")
                    # Acumulado do lançamento atual (cap_start..hoje) — pra ver tendência.
                    try:
                        from src.core.launches import resolve_launch_window_brt as _rlw_pv
                        _lw_pv = _rlw_pv(today=_anchor)
                        _cap_s = _lw_pv.cap_start.isoformat()
                        _today_s = _brt_now.strftime('%Y-%m-%d')
                        _pv_lf = _pv_for_window(_cap_s, _today_s, _cap_s, _today_s)
                        meta_window_data['por_variante_lf'] = _pv_lf
                        logger.info(
                            f"📊 Por variante ({_lw_pv.lf_name or 'LF'} acum. {_cap_s}→{_today_s}): "
                            + " · ".join(f"{_b}: {_d['leads']} leads, CPL {_d['cpl']}"
                                         for _b, _d in _pv_lf.items())
                        )
                    except Exception as _pvlfe:
                        logger.warning(f"⚠️ CPL/conv por variante (lançamento): {_pvlfe}")
                except Exception as _pve:
                    logger.warning(f"⚠️ CPL/conv por variante (dia anterior): {_pve}")

        except Exception as _e:
            logger.warning(f"⚠️ Meta Ads metrics indisponível: {_e}")

        # --- Funil Google (LEITURA da Google Ads API) — atrás de flag, isolado ---
        # Read-only: custo/cliques/conversões + CPL agregado + SPLIT POR VARIANTE
        # (Lead/Champion/Challenger), pro bloco "Funil Google" do digest na MESMA
        # forma do Meta. NÃO toca o envio (Data Manager API, outro caminho) nem o
        # funil Meta. Janela = dia BRT anterior completo (idêntica ao "Anúncio
        # (Meta Insights)") + acumulado do lançamento (LF).
        # Pré-req em produção: as 5 env vars GOOGLE_ADS_* (developer token + OAuth)
        # no Cloud Run. Sem elas / token expirado / flag off → só omite o bloco
        # (log "indisponível"), NUNCA derruba o relatório das 06:00.
        try:
            _gcfg = (pipeline._client_config.google_ads
                     if (pipeline and pipeline._client_config) else None)
            if _gcfg and getattr(_gcfg, 'reporting_enabled', False) and _gcfg.customer_id:
                from src.validation.google_ads_api_client import GoogleAdsReportingClient
                from src.monitoring.daily_check_aggregations import (
                    compute_google_funnel,
                    compute_variant_cpl_conv as _variant_cpl_g,
                )
                from src.monitoring.google_variant import (
                    campaign_id_from_utm_term as _gcid,
                    build_campaign_variant_map as _build_gvm,
                    make_classifier as _make_gclassify,
                )
                # Janela = dia BRT anterior completo (idêntica ao Meta), não 7d.
                _g_yest_str = (_uf_today_mid - timedelta(days=1)).strftime('%Y-%m-%d')
                _g_start = _g_yest_str
                _g_end = _g_yest_str
                _our_actions = tuple(
                    a for a in (_gcfg.event_name_with_value, _gcfg.event_name_high_quality) if a
                )
                _g_allow = {s.lower() for s in (_gcfg.source_allowlist or [])}

                # Classificador de variante (Estratégia espelhando o Meta): hoje o
                # mapa goal→variante está vazio (nenhuma campanha Google plugada no
                # A/B de modelo) → tudo cai em 'Lead' e nem bate na API de goals.
                # Quando o gestor ligar o sinal ML, preencher variant_goal_map no
                # YAML e Champion/Challenger populam sozinhos.
                _g_cvm = _build_gvm(None, getattr(_gcfg, 'variant_goal_map', None))
                _g_classify = _make_gclassify(_g_cvm)

                _gclient = GoogleAdsReportingClient(_gcfg.customer_id)
                _g_cmp = _gclient.get_campaign_metrics(_g_start, _g_end)
                _g_conv = _gclient.get_campaign_conversions_by_action(
                    _g_start, _g_end, action_names=_our_actions or None,
                )
                # Volume de leads = CADASTROS (Client/Railway), a fonte da verdade
                # de "quantos leads o Google trouxe" (= o form submit, que é o que
                # o Google Ads conta). NÃO os respondentes do `registros_ml`, que
                # só tem quem respondeu a pesquisa e subestima ~8%. Fail-soft: se o
                # Railway não responder ou o dia não tiver cadastro google, cai nos
                # respondentes — nunca derruba o relatório das 06:00.
                _g_responders = [
                    r for r in _uf_records if (r.utm_source or '').lower() in _g_allow
                ]
                _g_yest_records, _g_basis = _g_responders, 'respondentes'
                try:
                    from src.data.cadastro_records import (
                        open_railway_connection as _open_rail_g,
                        google_cadastro_records as _gcadr,
                    )
                    _rc = _open_rail_g()
                    try:
                        _cad = _gcadr(_rc, _g_yest_str, _g_yest_str, _g_allow)
                    finally:
                        try: _rc.close()
                        except Exception: pass
                    if _cad:
                        _g_yest_records, _g_basis = _cad, 'cadastros'
                    else:
                        logger.warning(
                            "⚠️ Funil Google: 0 cadastros google na Client p/ %s — usando respondentes",
                            _g_yest_str,
                        )
                except Exception as _cade:
                    logger.warning(
                        "⚠️ Funil Google: cadastros da Client indisponíveis (%s) — usando respondentes",
                        _cade,
                    )
                _g_leads = len(_g_yest_records)

                # Helper: CPL/conv por variante reusando a MESMA função pura do
                # Meta. Spend por campanha chaveado por campaign_id; leads por
                # campaign_id extraído do utm_term ValueTrack. lpv = clicks (o
                # análogo Google do landing_page_view); imposto = 0 (Google não
                # tem o imposto Meta). Mesmo formato de saída → render idêntico.
                def _g_pv(cmp_rows, lead_records):
                    _ids = {r['campaign_id'] for r in cmp_rows}
                    _spend_rows = [
                        {'campaign_name': r['campaign_id'], 'spend': r['spend'], 'lpv': r['clicks']}
                        for r in cmp_rows
                    ]
                    _cids, _unm = [], 0
                    for r in lead_records:
                        cid = _gcid(r.utm_term)
                        _cids.append(cid)
                        if cid is not None and cid not in _ids:
                            _unm += 1
                    if _unm:
                        logger.warning(
                            "⚠️ Funil Google: %d leads c/ campaign_id fora da API (template UTM mudou?)",
                            _unm,
                        )
                    return _variant_cpl_g(
                        meta_rows=_spend_rows, client_campaigns=_cids,
                        classify_fn=_g_classify, tax_rate=0.0,
                    )

                _g_funnel = compute_google_funnel(
                    _g_cmp, _g_conv,
                    action_with_value=_gcfg.event_name_with_value,
                    action_high_quality=_gcfg.event_name_high_quality,
                    total_google_leads=_g_leads,
                )
                # Split por variante — IDÊNTICO ao Meta (ontem + acumulado do LF).
                _g_funnel['por_variante'] = _g_pv(_g_cmp, _g_yest_records)
                try:
                    from src.core.launches import resolve_launch_window_brt as _rlw_g
                    from src.data.ledger_connection import open_ledger_read_connection as _open_ledger_g
                    from src.data import compose_repository as _compose_repo_g
                    _lw_g = _rlw_g(today=_anchor)
                    _cap_s = _lw_g.cap_start.isoformat()
                    _today_s = _uf_today_mid.strftime('%Y-%m-%d')
                    _g_cmp_lf = _gclient.get_campaign_metrics(_cap_s, _today_s)
                    _cap_dt = datetime(
                        _lw_g.cap_start.year, _lw_g.cap_start.month, _lw_g.cap_start.day,
                        tzinfo=_uf_brt,
                    ).astimezone(_tz.utc)
                    # Acumulado do LF por CADASTROS (Client/Railway) — MESMA fonte do
                    # diário, pra o bloco não misturar bases. Fallback pros respondentes
                    # do ledger se o Railway falhar ou o LF não tiver cadastro google
                    # (não derruba o bloco). A ledger_conn original foi fechada acima.
                    _g_lf_records = None
                    try:
                        from src.data.cadastro_records import (
                            open_railway_connection as _open_rail_lf,
                            google_cadastro_records as _gcadr_lf,
                        )
                        _rc_lf = _open_rail_lf()
                        try:
                            _g_lf_records = _gcadr_lf(_rc_lf, _cap_s, _today_s, _g_allow) or None
                        finally:
                            try: _rc_lf.close()
                            except Exception: pass
                    except Exception as _lfce:
                        logger.warning(
                            "⚠️ Google LF: cadastros da Client indisponíveis (%s) — fallback ledger", _lfce,
                        )
                    if _g_lf_records is None:
                        _g_lf_conn = _open_ledger_g()
                        try:
                            _g_lf_repo = _compose_repo_g('registros_ml', railway_conn=_g_lf_conn)
                            _lf_records_all = _g_lf_repo.leads_in_range(_cap_dt, datetime.now(_tz.utc))
                            _g_lf_records = [
                                r for r in _lf_records_all if (r.utm_source or '').lower() in _g_allow
                            ]
                        finally:
                            try: _g_lf_conn.close()
                            except Exception: pass
                    _g_funnel['por_variante_lf'] = _g_pv(_g_cmp_lf, _g_lf_records)
                except Exception as _glfe:
                    logger.warning(f"⚠️ Por variante Google (lançamento): {_glfe}")

                result.setdefault('operational_routines', {})['google_funnel'] = _g_funnel
                logger.info(
                    "📊 Funil Google (ontem %s): spend R$ %.0f · %d campanhas · %d leads "
                    "[base=%s; respondentes=%d] · CPL %s · variante %s",
                    _g_yest_str, _g_funnel['total_spend'], len(_g_funnel['por_campanha']),
                    _g_leads, _g_basis, len(_g_responders), _g_funnel['cpl_agregado'],
                    " · ".join(f"{_b}:{_d['leads']}" for _b, _d in _g_funnel['por_variante'].items()),
                )
        except Exception as _gfe:
            logger.warning(f"⚠️ Funil Google indisponível: {_gfe}")

        # Regenerar critical_summary com dados Railway (lead_quality_metrics corretos)
        from src.monitoring.models import Alert as AlertModel
        alerts_objs = [AlertModel.from_dict(a) for a in result['alerts']]
        result['critical_summary'] = orchestrator._generate_critical_summary(
            alerts_objs, railway_funnel_metrics, railway_lead_quality, meta_metrics
        )

        # Gerar previsão de faturamento (falha silenciosa — não deve bloquear monitoring)
        # Metodologia flat-rate: buyers = total_leads_meta × (conv_rastr_mediana / tracking_rate)
        # total_leads_meta vem da Meta Ads API (janela desde terça BRT) — inclui não-respondentes.
        revenue_forecast = None
        try:
            revenue_forecast = orchestrator._generate_revenue_forecast(
                # denominador do flat-rate: leads all-source (Client, todas as fontes);
                # fallback pro Meta-pixel se a contagem Client falhar.
                total_meta_leads=(total_leads_allsource_forecast or total_meta_leads_forecast),
                funnel_metrics=railway_funnel_metrics,
                lead_quality_metrics=railway_lead_quality,
                decil_distribution=forecast_decil_dist or None,
                ml_aware_segments=ml_aware_segments,
            ) or None

            if revenue_forecast:
                revenue_forecast['inputs']['launch_window_start_brt'] = launch_window_label
        except Exception as _fe:
            logger.warning(f"⚠️ revenue_forecast indisponível: {_fe}")

        # Previsão para o LF anterior (mesma metodologia aplicada ao lançamento
        # anterior — permite comparar previsão atual com previsão histórica).
        try:
            # `lf_referencia_label` é o LF ATIVO — usá-lo aqui era o bug que
            # fazia o DM mostrar o MESMO lançamento como "atual" E "anterior"
            # (com rótulos de janela diferentes, parecendo dado corrompido).
            # Latente desde 12/05, vivo desde 24/07 quando o fix do NameError
            # ressuscitou este bloco. O anterior DE VERDADE sai do calendário:
            # o LF com maior cap_end estritamente ANTES do cap_start do ativo.
            _lf_ativo = railway_lead_quality.get('lf_referencia_label')
            # Fonte única via core.launches (analytics.launch_calendar quando
            # LAUNCHES_SOURCE=table, senão yaml). Antes lia `launches_path`, que NUNCA
            # era definido aqui → NameError e esta previsão do LF anterior degradava
            # sempre. Agora enxerga a tabela como o resto do resolvedor.
            from src.core.launches import load_launches as _load_launches2
            _launches_cfg2 = _load_launches2() if (revenue_forecast and _lf_ativo) else {}
            lf_ref_name = None
            _cs_ativo = ((_launches_cfg2.get(_lf_ativo) or {}).get('cap_start')
                         if _lf_ativo else None)
            if _cs_ativo:
                _cands = [(n, c) for n, c in _launches_cfg2.items()
                          if (c or {}).get('cap_end') and (c or {}).get('cap_start')
                          and c['cap_end'] < _cs_ativo]  # ISO: ordem lexicográfica = cronológica
                if _cands:
                    lf_ref_name = max(_cands, key=lambda kv: kv[1]['cap_end'])[0]
            if lf_ref_name == _lf_ativo:
                lf_ref_name = None  # guarda: nunca duplicar o LF corrente
            if revenue_forecast and lf_ref_name and lf_ref_name in _launches_cfg2:
                _lf_cfg = _launches_cfg2.get(lf_ref_name) or {}
                _cs = _lf_cfg.get('cap_start'); _ce = _lf_cfg.get('cap_end')
                if _cs and _ce:
                    _cs_dt = datetime.strptime(_cs, '%Y-%m-%d').replace(tzinfo=brt).astimezone(_tz.utc)
                    _ce_dt = datetime.strptime(_ce, '%Y-%m-%d').replace(hour=23, minute=59, second=59, tzinfo=brt).astimezone(_tz.utc)

                    # Meta leads do LF anterior
                    _lf_total_meta = 0
                    _meta_token2 = os.getenv('META_ACCESS_TOKEN')
                    if _meta_token2:
                        try:
                            from api.meta_integration import MetaAdsIntegration as _MI2
                            from api.meta_config import META_CONFIG as _MC2
                            _meta2 = _MI2(access_token=_meta_token2)
                            _account2 = os.getenv('META_ACCOUNT_ID', _MC2.get('account_id', 'act_188005769808959'))
                            _lf_rows_meta = _meta2.get_insights(
                                account_id=_account2,
                                level='campaign',
                                fields=['campaign_name', 'actions'],
                                since_date=_cs, until_date=_ce,
                                filtering=[{'field': 'campaign.name', 'operator': 'CONTAIN', 'value': 'CAP'}]
                            )
                            for _r in _lf_rows_meta:
                                for _a in (_r.get('actions') or []):
                                    if _a.get('action_type') == 'offsite_conversion.fb_pixel_lead':
                                        _lf_total_meta += int(_a.get('value', 0) or 0)
                        except Exception as _me:
                            logger.warning(f"⚠️ Meta leads LF {lf_ref_name}: {_me}")

                    # Distribuição de decis do LF anterior — filtro in-memory
                    # sobre _records_90d (já carregado pelo LeadRepository). Antes
                    # lia da Lead morta via query SQL; agora cobre desde quando o
                    # ledger novo começou (23/05). Pra LFs com cap_end anterior a
                    # 23/05, o resultado pode ser incompleto até o ledger acumular
                    # histórico — anotado no follow-up de remoção do adaptador
                    # legado (~22/06).
                    _lf_decil_dist: Dict[str, int] = {}
                    try:
                        for _rec in _records_90d:
                            if _rec.criado_em is None or _rec.decil is None or _rec.score is None:
                                continue
                            _c = _rec.criado_em.replace(tzinfo=_tz.utc) if _rec.criado_em.tzinfo is None else _rec.criado_em
                            if _cs_dt <= _c <= _ce_dt:
                                _key = f"D{int(_rec.decil):02d}"
                                _lf_decil_dist[_key] = _lf_decil_dist.get(_key, 0) + 1
                    except Exception as _de:
                        logger.warning(f"⚠️ decis LF {lf_ref_name}: {_de}")

                    # Forecast aplicando a mesma metodologia ao volume LF anterior
                    if _lf_total_meta > 0:
                        _lf_forecast = orchestrator._generate_revenue_forecast(
                            total_meta_leads=_lf_total_meta,
                            funnel_metrics=railway_funnel_metrics,
                            lead_quality_metrics=railway_lead_quality,
                            decil_distribution=_lf_decil_dist or None,
                        ) or None
                        if _lf_forecast:
                            _lf_forecast['inputs']['launch_window_start_brt'] = f"{_cs} → {_ce}"
                            _lf_forecast['inputs']['lf_name'] = lf_ref_name
                            revenue_forecast['lf_anterior'] = _lf_forecast
                            logger.info(f"📊 lf_anterior forecast: {lf_ref_name} · {_lf_total_meta:,} Meta leads · {sum(_lf_decil_dist.values()):,} db leads")
        except Exception as _lfe:
            logger.warning(f"⚠️ revenue_forecast.lf_anterior indisponível: {_lfe}")

        # ------------------------------------------------------------------
        # Build survey_funnel_metrics e traffic_metrics
        # ------------------------------------------------------------------
        _meta_wd = locals().get('meta_window_data', {})

        survey_funnel_metrics: Dict[str, Any] = {}
        for _lbl, _sfm in _sfm_db.items():
            _mw = _meta_wd.get(_lbl) if _meta_wd else None
            _meta_leads = _mw['meta_leads'] if _mw else None
            _db_leads   = _sfm['db_leads']
            _rr = (round(_db_leads / _meta_leads * 100, 1)
                   if (_meta_leads and _meta_leads > 0) else None)
            survey_funnel_metrics[_lbl] = {
                'db_leads':      _db_leads,
                'capi_sent':     _sfm['capi_sent'],
                'capi_rate':     _sfm['capi_rate'],
                'meta_leads':    _meta_leads,
                'response_rate': _rr,
            }

        traffic_metrics: Optional[Dict[str, Any]] = (
            {k: v for k, v in _meta_wd.items() if v is not None}
            if _meta_wd else None
        ) or None

        processing_time = time.time() - start_time
        logger.info(f"✅ Railway monitoring concluído em {processing_time:.2f}s — "
                    f"{result['total_alerts']} alertas")

        return DailyCheckResponse(
            total_alerts=result['total_alerts'],
            alerts_by_severity=result['alerts_by_severity'],
            alerts_by_category=result['alerts_by_category'],
            actionable_alerts=result.get('actionable_alerts', []),
            alerts=result['alerts'],
            critical_summary=result.get('critical_summary', ''),
            timestamp=datetime.now().isoformat(),
            funnel_metrics=result.get('funnel_metrics'),
            lead_quality_metrics=result.get('lead_quality_metrics'),
            revenue_forecast=revenue_forecast if revenue_forecast else None,
            survey_funnel_metrics=survey_funnel_metrics or None,
            traffic_metrics=traffic_metrics,
            operational_routines=result.get('operational_routines'),
            launch_resolution=launch_resolution_payload,
            pubsub_24h_summary=result.get('pubsub_24h_summary'),
            training_drift_24h_summary=result.get('training_drift_24h_summary'),
            hotleads_24h_summary=result.get('hotleads_24h_summary'),
        )

    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"Modelo não encontrado: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Erro no Railway monitoring: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Erro no Railway monitoring: {str(e)}")


@router.get("/monitoring/slack-digest")
async def post_slack_digest(
    pipeline: PipelineOptDep,
    channel: Optional[str] = None,
    channel_client: Optional[str] = None,
    channel_full: Optional[str] = None,
    hours: int = 24,
    include_today_partial: bool = False,
    date: Optional[str] = None,
    force: bool = False,
):
    """
    Renderiza o daily-check em 2 views distintas e posta em canais separados.

    - `channel_client`: view enxuta pro cliente — A/B test + 2 tabelas de drift
      por variante (ontem + lançamento atual) com ✅ por linha + drift geral
      com 🟢🟡🔴 + 2 distribuições de decis.
    - `channel_full`: view completa pro privado — severity, alertas, funil,
      lead quality detalhado, survey funnel, revenue forecast, tráfego Meta.
    - `channel` (legacy): se passado sozinho, usa view full no canal indicado
      (backward compat com o uso antigo).

    Reusa o handler /monitoring/daily-check/railway in-process e aplica os
    renderers do `src/monitoring/digest`. Token vem do env `SLACK_BOT_TOKEN`
    (Secret Manager).

    Trava de tráfego (`src/monitoring/traffic_gate`): sem gasto nem lead pago na
    janela, o daily-check roda mas NÃO posta — devolve 200 com `skipped`. Entre
    lançamentos a captação fica pausada e o relatório seria só tabela de zeros.
    `force=1` posta de qualquer jeito (validação de formatação no DM), e a env
    `REPORTS_REQUIRE_TRAFFIC=0` desliga a trava sem deploy.
    """
    import os
    import json as _json
    import urllib.request
    from src.monitoring.digest import (
        extract_view, render_slack_blocks, render_slack_blocks_client,
        PayloadSchemaDriftError,
    )
    from src.monitoring.traffic_gate import check_from_daily_check, trava_habilitada

    token = os.environ.get('SLACK_BOT_TOKEN')
    if not token:
        raise HTTPException(status_code=500, detail="SLACK_BOT_TOKEN não configurado no ambiente")

    # Resolve quais canais postar
    targets: List[tuple] = []  # [(channel, view_kind), ...]
    if channel_client:
        targets.append((channel_client, 'client'))
    if channel_full:
        targets.append((channel_full, 'full'))
    if not targets and channel:
        # Legacy: 1 canal, view full
        targets.append((channel, 'full'))
    if not targets:
        raise HTTPException(status_code=400,
                            detail="Passe channel_client, channel_full ou channel (legacy)")

    response = await daily_monitoring_check_railway(
        pipeline=pipeline,
        hours=hours,
        start_date=None,
        end_date=None,
        include_today_partial=include_today_partial,
        anchor_date=date,
    )
    payload = response.model_dump() if hasattr(response, 'model_dump') else dict(response)

    # Trava de tráfego ANTES de renderizar: sem veiculação na janela não há
    # relatório. Mede no mesmo payload que seria renderizado, então gate e
    # relatório nunca discordam sobre a janela.
    _gate = check_from_daily_check(payload)
    if not _gate.ativo and not force and trava_habilitada():
        logger.info(f"⏸️ slack-digest NÃO postado — {_gate.motivo}")
        return {
            'ok': True,
            'skipped': 'sem_trafego',
            'posts': [],
            'gate': _gate.as_dict(),
        }

    try:
        view = extract_view(payload)
    except PayloadSchemaDriftError as e:
        raise HTTPException(status_code=500, detail=f"Payload schema drift: {e}")

    results: List[Dict] = []
    for ch, kind in targets:
        blocks = render_slack_blocks_client(view) if kind == 'client' else render_slack_blocks(view)
        body = {
            'channel': ch,
            'blocks': blocks,
            'text': f'Daily Check — DevClub ({kind})',
        }
        req = urllib.request.Request(
            'https://slack.com/api/chat.postMessage',
            data=_json.dumps(body).encode('utf-8'),
            headers={
                'Content-Type': 'application/json; charset=utf-8',
                'Authorization': f'Bearer {token}',
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = _json.load(r)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Falha ao chamar Slack ({kind} → {ch}): {e}")
        if not resp.get('ok'):
            raise HTTPException(status_code=502, detail=f"Slack rejeitou ({kind} → {ch}): {resp}")
        results.append({
            'view': kind,
            'channel': resp.get('channel'),
            'ts': resp.get('ts'),
            'blocks_count': len(blocks),
        })

    return {
        'ok': True,
        'posts': results,
        'gate': _gate.as_dict(),
    }


@router.post("/monitoring/daily-check", response_model=DailyCheckResponse)
async def daily_monitoring_check(
    request: DailyCheckRequest,
    db: Session = Depends(get_db)
):
    """
    Executa check diário de monitoramento consolidado.

    Verifica:
    - Data Quality: category drift, distribution drift, missing rate, score distribution
    - Operational: 6h sem leads, 6h sem CAPI
    - CAPI Quality: missing rate fbp/fbc

    Args:
        request: Dados do Sheets (últimas 24h)
        db: Sessão PostgreSQL (injetada automaticamente)

    Returns:
        Alertas consolidados por severidade e categoria
    """
    from src.monitoring.orchestrator import MonitoringOrchestrator
    import yaml

    start_time = time.time()
    logger.info(f"🔍 Executando check diário de monitoramento ({len(request.leads)} leads)")

    try:
        # Obter model_path do modelo ativo
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'configs/active_models/devclub.yaml'
        )

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            active_model = config['active_model']
            if 'mlflow_run_id' in active_model:
                model_path = os.path.join('mlruns', '1', active_model['mlflow_run_id'], 'artifacts')
            else:
                model_path = active_model['model_path']

        # Garantir path absoluto
        if not os.path.isabs(model_path):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_path = os.path.join(base_dir, model_path)

        logger.info(f"📂 Usando modelo: {model_path}")

        # Inicializar orquestrador
        orchestrator = MonitoringOrchestrator(model_path=model_path, db=db,
                                              lead_scoring_pipeline=pipelines.get('devclub'))

        # Executar checks
        result = orchestrator.run_daily_check(request.leads)

        processing_time = time.time() - start_time

        logger.info(f"✅ Check concluído em {processing_time:.2f}s")
        logger.info(f"📊 Alertas: {result['total_alerts']} total "
                   f"(HIGH: {result['alerts_by_severity']['HIGH']}, "
                   f"MEDIUM: {result['alerts_by_severity']['MEDIUM']}, "
                   f"LOW: {result['alerts_by_severity']['LOW']})")

        # Logar alertas detalhados
        if result['total_alerts'] > 0:
            logger.info(f"\n🚨 ALERTAS DETECTADOS ({result['total_alerts']}):\n")

            # Logar TODOS os alertas (sem limite)
            for i, alert in enumerate(result['alerts'], 1):
                logger.info(f"{i}. [{alert['severity']}] {alert['type']}")
                logger.info(f"   {alert['message']}")
                if alert.get('metric_value'):
                    threshold_msg = f" (threshold: {alert['threshold']})" if alert.get('threshold') else ""
                    logger.info(f"   Valor: {alert['metric_value']}{threshold_msg}")
                logger.info("")  # Linha em branco
        else:
            logger.info("✅ Nenhum alerta detectado - sistema operando normalmente")

        return DailyCheckResponse(
            total_alerts=result['total_alerts'],
            alerts_by_severity=result['alerts_by_severity'],
            alerts_by_category=result['alerts_by_category'],
            actionable_alerts=result.get('actionable_alerts', []),
            alerts=result['alerts'],
            critical_summary=result.get('critical_summary', ''),
            timestamp=datetime.now().isoformat(),
            funnel_metrics=result.get('funnel_metrics'),
            lead_quality_metrics=result.get('lead_quality_metrics'),
            operational_routines=result.get('operational_routines'),
            pubsub_24h_summary=result.get('pubsub_24h_summary'),
            training_drift_24h_summary=result.get('training_drift_24h_summary'),
            hotleads_24h_summary=result.get('hotleads_24h_summary'),
        )

    except FileNotFoundError as e:
        logger.error(f"❌ Arquivo não encontrado: {e}")
        raise HTTPException(status_code=500, detail=f"Modelo não encontrado: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Erro no check de monitoramento: {str(e)}")
        logger.error(f"Traceback: {e.__class__.__name__}")
        raise HTTPException(status_code=500, detail=f"Erro no monitoramento: {str(e)}")
