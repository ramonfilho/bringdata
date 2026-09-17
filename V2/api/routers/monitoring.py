"""Relatórios e vigias: feature-report, drift/qualidade de público, UTM, custo, painel, smoke e validação semanal.

Gerado a partir do app.py monolítico (corte por domínio, corpo dos handlers intacto)."""
import os
import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile, File
from typing import Annotated, List, Dict, Any, Optional
import time
from datetime import datetime
import logging
from api.database import get_db, init_database, create_lead_capi, count_leads, count_leads_with_fbp, count_leads_with_fbc, get_leads_by_emails, LeadCAPI
from fastapi import Depends, Header, Request
from api.auth import exigir_token, exigir_token_interno
from sqlalchemy.orm import Session
from fastapi import APIRouter
import logging
from api.state import PipelineDep, PipelineOptDep

# Raiz do V2 (onde vivem configs/, src/, vendas/, files/). Este arquivo está em
# api/routers/, dois níveis abaixo; `Path(__file__).parent.parent` apontaria para api/.
# Foi o que quebrou o daily-check na revisão 01179-jux (17/09/2026): 500 por
# 'api/configs/active_models/devclub.yaml' não existir.
_RAIZ = Path(__file__).resolve().parents[2]

logger = logging.getLogger(__name__)
router = APIRouter()


# URL do Google Sheets para monitoramento
GOOGLE_SHEETS_URL = os.getenv(
    'GOOGLE_SHEETS_URL',
    'https://docs.google.com/spreadsheets/d/1VYti8jX277VNMkvzrfnJSR_Ko8L1LQFDdMEeD6D8_Vo'
)


def fetch_leads_from_sheets(hours: int = 24) -> List[Dict[str, Any]]:
    """
    Busca leads do Google Sheets das últimas N horas.

    Args:
        hours: Número de horas para buscar (padrão: 24)

    Returns:
        Lista de dicts com dados dos leads

    Raises:
        Exception: Se falhar ao buscar dados
    """
    import gspread
    from google.auth import default as gauth_default
    from datetime import timedelta

    try:
        logger.info(f"📊 Buscando leads do Google Sheets (últimas {hours}h)...")

        # Autenticar com Application Default Credentials
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets.readonly',
            'https://www.googleapis.com/auth/drive.readonly'
        ]
        creds, _ = gauth_default(scopes=scopes)
        gc = gspread.authorize(creds)

        # Abrir planilha
        spreadsheet = gc.open_by_url(GOOGLE_SHEETS_URL)
        worksheet = spreadsheet.get_worksheet(0)  # Primeira aba

        # Buscar todos os dados usando get_all_values() para evitar erro com headers duplicados
        valores = worksheet.get_all_values()
        headers = valores[0]
        dados = valores[1:]

        # Converter para lista de dicts
        all_data = [dict(zip(headers, row)) for row in dados]

        # Tentar filtrar por data (últimas N horas)
        try:
            df = pd.DataFrame(all_data)

            # Identificar coluna de data
            date_columns = [col for col in df.columns if any(
                term in col.lower() for term in ['data', 'timestamp', 'hora', 'date', 'time']
            )]

            if date_columns:
                date_col = date_columns[0]
                df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                # Sheets armazena datas em BRT (naive). Cloud Run roda em UTC.
                # datetime.now() em Cloud Run = UTC, causando janela 3h curta.
                # Usar BRT naive para comparar com datas BRT do Sheets.
                from datetime import timezone as _tz
                _brt = _tz(timedelta(hours=-3))
                cutoff = datetime.now(_tz.utc).astimezone(_brt).replace(tzinfo=None) - timedelta(hours=hours)
                df_filtered = df[df[date_col] >= cutoff]

                if len(df_filtered) > 0:
                    leads = df_filtered.to_dict('records')
                    logger.info(f"✅ {len(leads)} leads encontrados das últimas {hours}h")
                    return leads
                else:
                    logger.warning(f"⚠️ Nenhum lead nas últimas {hours}h, usando últimos 100")
                    leads = all_data[-100:] if len(all_data) > 100 else all_data
                    return leads
            else:
                logger.warning(f"⚠️ Coluna de data não encontrada, usando últimos 100 leads")
                leads = all_data[-100:] if len(all_data) > 100 else all_data
                return leads

        except Exception as e:
            logger.warning(f"⚠️ Erro ao filtrar por data: {e}, usando últimos 100 leads")
            leads = all_data[-100:] if len(all_data) > 100 else all_data
            return leads

    except Exception as e:
        logger.error(f"❌ Erro ao buscar dados do Google Sheets: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao buscar dados do Google Sheets: {str(e)}"
        )


@router.get("/monitoring/feature-report")
async def feature_report(
    hours: int = 24,
    revision: Optional[str] = None,
):
    """
    [T1-11 Peça B] Agrega os logs do feature_validator das últimas N horas
    e retorna relatório consolidado do monitoramento pré-encoding.

    Consome os logs estruturados [FV_JSON] emitidos por
    `src/core/feature_validator.py` em produção (um log por batch scoreado).

    Args:
        hours:    janela em horas a consultar (default: 24)
        revision: se informado, filtra só essa revisão Cloud Run

    Returns:
        {
          'window': {'hours': N, 'since': iso_ts},
          'total_batches': int,
          'batches_by_severity': {'OK': N, 'INFO': N, 'WARNING': N, 'ERROR': N},
          'issues_by_feature': {feature_name: {'count': N, 'problems': {problem_type: N}, 'latest_details': {...}}},
          'overall_status': 'OK' | 'INFO' | 'WARNING' | 'ERROR',
          'recommended_action': str,
          'sample_error_log': {... snippet do log mais recente com severity=ERROR ...}  # se houver
        }

    Filtros Cloud Logging:
      resource.type=cloud_run_revision AND
      resource.labels.service_name=smart-ads-api AND
      textPayload:"[FV_JSON]"
    """
    import json as _json
    from datetime import timedelta, timezone
    from google.cloud import logging as gcp_logging

    project = os.getenv('PROJECT_ID', 'smart-ads-451319')
    service = 'smart-ads-api'

    now_utc = datetime.now(timezone.utc)
    since_utc = now_utc - timedelta(hours=hours)
    since_iso = since_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Filtro Cloud Logging — equivalente ao gcloud logging read --freshness Nh
    filter_parts = [
        'resource.type="cloud_run_revision"',
        f'resource.labels.service_name="{service}"',
        'textPayload:"[FV_JSON]"',
        f'timestamp>="{since_iso}"',
    ]
    if revision:
        filter_parts.append(f'resource.labels.revision_name="{revision}"')
    filter_str = ' AND '.join(filter_parts)

    try:
        log_client = gcp_logging.Client(project=project)
        entries = log_client.list_entries(
            filter_=filter_str,
            order_by=gcp_logging.DESCENDING,
            max_results=5000,
        )
        raw_lines = [e.payload for e in entries if isinstance(e.payload, str)]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cloud Logging API falhou: {str(e)[:300]}")

    # Parse dos payloads
    payloads = []
    for line in raw_lines:
        idx = line.find('[FV_JSON] ')
        if idx < 0:
            continue
        try:
            payload = _json.loads(line[idx + len('[FV_JSON] '):])
            if payload.get('event') == 'feature_validator':
                payloads.append(payload)
        except Exception:
            continue

    # Agregação
    batches_by_severity = {'OK': 0, 'INFO': 0, 'WARNING': 0, 'ERROR': 0}
    issues_by_feature: Dict[str, Dict[str, Any]] = {}
    latest_error_log = None
    latest_error_ts = None

    for p in payloads:
        sev = p.get('severity', 'UNKNOWN')
        batches_by_severity[sev] = batches_by_severity.get(sev, 0) + 1

        if sev == 'ERROR':
            ts = p.get('timestamp', '')
            if latest_error_ts is None or ts > latest_error_ts:
                latest_error_ts = ts
                latest_error_log = p

        for issue in p.get('issues', []):
            feat = issue.get('feature', '?')
            prob = issue.get('problem', '?')
            entry = issues_by_feature.setdefault(feat, {
                'count': 0,
                'problems': {},
                'latest_details': None,
                'latest_timestamp': None,
            })
            entry['count'] += 1
            entry['problems'][prob] = entry['problems'].get(prob, 0) + 1
            ts = p.get('timestamp', '')
            if entry['latest_timestamp'] is None or ts > entry['latest_timestamp']:
                entry['latest_timestamp'] = ts
                entry['latest_details'] = issue.get('details')

    # Overall status e ação recomendada
    if batches_by_severity['ERROR'] > 0:
        overall_status = 'ERROR'
        recommended_action = (
            "BLOQUEAR progressão de tráfego. Investigar features com problem in "
            "{missing_column, wrong_dtype, null_rate_high} — o modelo está sendo "
            "scoreado com sinal incompleto. Ver sample_error_log para exemplo concreto."
        )
    elif batches_by_severity['WARNING'] > 0:
        overall_status = 'WARNING'
        recommended_action = (
            "Avaliar novas categorias detectadas (drift em categóricas). Não bloqueia "
            "progressão, mas pode indicar que o modelo está saindo do domínio de treino. "
            "Se frequente, agendar retreino."
        )
    elif batches_by_severity['INFO'] > 0:
        overall_status = 'INFO'
        recommended_action = (
            "Valores numéricos fora do range observado em treino (drift numérico suave). "
            "Progressão liberada. Monitorar tendência para decidir retreino futuro."
        )
    elif batches_by_severity['OK'] > 0:
        overall_status = 'OK'
        recommended_action = "Nenhum problema detectado. Progressão de tráfego liberada do ponto de vista de T1-11."
    else:
        overall_status = 'NO_DATA'
        recommended_action = (
            "Nenhum log [FV_JSON] encontrado na janela. Pipeline pode não estar sendo "
            "exercitado, schema pode não estar carregado na revisão, ou a revisão não "
            "recebeu tráfego. Se revisão é nova, gerar tráfego antes de consultar."
        )

    return {
        'window': {
            'hours': hours,
            'since': since_utc.isoformat(),
            'until': now_utc.isoformat(),
        },
        'revision_filter': revision,
        'total_batches': sum(batches_by_severity.values()),
        'batches_by_severity': batches_by_severity,
        'issues_by_feature': issues_by_feature,
        'overall_status': overall_status,
        'recommended_action': recommended_action,
        'sample_error_log': latest_error_log,
    }


@router.get("/monitoring/audience-drift")
async def audience_drift_endpoint(
    client_id: str = 'devclub',
    date: Optional[str] = None,
):
    """
    Drift de público por característica vs Top 5 ROAS — versão completa.

    Devolve TODAS as categorias (sem cut de 2pp, sem dedup binárias). Mesmo
    cômputo do digest do Slack — só sem os filtros aplicados. Pra consumo
    via dashboard cliente.

    Args:
        client_id: cliente (default `devclub`).
        date: opcional, formato `YYYY-MM-DD`. Quando informado, é o "hoje" da
              simulação — `day_*` vira o dia anterior a ele, `prev_day_*` vira
              D-2, e `launch_*` resolve o LF ativo naquela data. Sem o param,
              tudo é relativo ao dia atual (comportamento default do digest).

    Sem auth — mesmo padrão dos demais `/monitoring/*` endpoints. URL é
    pública na internet; dado é demográfico agregado (sem PII).
    """
    from src.data import compose_repository
    from src.data.ledger_connection import open_ledger_read_connection
    from src.monitoring.data_quality import DataQualityMonitor
    from src.core.client_config import ClientConfig
    from datetime import date as _date
    import pandas as _pd

    anchor_date = None
    if date:
        try:
            anchor_date = _date.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400,
                                detail=f"date inválido: '{date}'. Use YYYY-MM-DD.")

    cfg_path = os.path.join(
        str(_RAIZ),
        'configs', 'clients', f'{client_id}.yaml',
    )
    client_config = ClientConfig.from_yaml(cfg_path)

    # Leitura do ledger via fonte escolhida por LEDGER_READ_SOURCE (railway|cloudsql).
    ledger_conn = open_ledger_read_connection()
    try:
        repo = compose_repository('registros_ml', railway_conn=ledger_conn)
        monitor = DataQualityMonitor(
            model_path='', client_config=client_config, db=None, repo=repo,
        )
        alerts = monitor._check_audience_profile_drift(
            _pd.DataFrame(), raw=True, anchor_date=anchor_date,
        )
    finally:
        ledger_conn.close()

    drift = next((a for a in alerts if a.get('type') == 'audience_profile_drift'), None)
    if drift is None:
        return {'top_list': [], 'details': {}}
    return drift.get('details', {})


@router.get("/monitoring/audience-quality")
async def audience_quality_endpoint(
    pipeline: PipelineOptDep,
    client_id: str = 'devclub',
    date: Optional[str] = None,
):
    """
    Qualidade de público num só lugar, pro dashboard do cliente - SÓ LEITURA.

    Junta, sem vazar receita/tráfego, as duas dimensões que importam:

      • `audience`  → CARACTERÍSTICAS do público vs Top ROAS (perfil do comprador):
          - `general`    : todas as categorias, todas as fontes (ontem / D-2 / lançamento)
          - `by_source`  : Meta vs Google, por categoria (ontem + lançamento)
          - `by_variant` : Lead/Champion/Challenger (A/B), por categoria (ontem + lançamento)
      • `model_score` → NOTA do modelo (decis na régua ÚNICA do Challenger abr_28):
          - `previous_day` / `current_launch`, cada um com `distribution` (Total) +
            `by_source` (Meta/Google) + `by_optgoal` (Lead/Champion/Challenger) +
            `baseline_challenger` (ref Top ROAS) + `score_geral` no lançamento.

    Reusa EXATAMENTE os mesmos cálculos do relatório das 06:00 (métodos do
    `DataQualityMonitor` + módulo `decis_by_channel`), então os números batem com
    o Slack por construção. Sem auth (padrão `/monitoring/*`), sem PII - dado
    demográfico agregado. Leitura do ledger pela fonte de `LEDGER_READ_SOURCE`.
    Latência ~10-20s (várias queries); cachear no front.

    Args:
        client_id: cliente (default `devclub`).
        date: opcional `YYYY-MM-DD` - "hoje" simulado (ontem/D-2/LF ficam relativos).
    """
    from datetime import date as _date_cls, datetime as _dt2, timezone as _tz2, timedelta as _td2
    import pandas as _pd
    from src.data import compose_repository
    from src.data.ledger_connection import open_ledger_read_connection
    from src.monitoring.data_quality import DataQualityMonitor
    from src.monitoring.daily_check_aggregations import records_to_quality_rows
    from src.monitoring.decis_by_channel import (
        resolve_decis_context, build_decis_window_payload, records_between,
    )
    from src.core.client_config import ClientConfig
    from src.core.launches import resolve_launch_window_brt

    anchor_date = None
    if date:
        try:
            anchor_date = _date_cls.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400,
                                detail=f"date inválido: '{date}'. Use YYYY-MM-DD.")

    cfg_path = os.path.join(
        str(_RAIZ),
        'configs', 'clients', f'{client_id}.yaml',
    )
    client_config = ClientConfig.from_yaml(cfg_path)

    ledger_conn = open_ledger_read_connection()
    try:
        repo = compose_repository('registros_ml', railway_conn=ledger_conn)

        # ---- AUDIENCE: características do público vs Top ROAS ----
        # Mesma cadeia do orchestrator.check(): geral raw (todas as categorias) →
        # alimenta os cortes por variante A/B e por fonte com o MESMO top_list, pra
        # o dashboard cobrir todas as categorias com números idênticos aos do Slack.
        monitor = DataQualityMonitor(model_path='', client_config=client_config, db=None, repo=repo)
        _aud_alerts = monitor._check_audience_profile_drift(
            _pd.DataFrame(), raw=True, anchor_date=anchor_date)
        _general = next((a for a in _aud_alerts if a.get('type') == 'audience_profile_drift'), None)
        _general_details = (_general.get('details', {}) if _general else {})
        _top_list = _general_details.get('top_list') or []
        _by_variant = (monitor._check_audience_drift_by_variant(_top_list, anchor_date=anchor_date)
                       if _top_list else [])
        _by_source = (monitor._check_audience_drift_by_source(_top_list, anchor_date=anchor_date)
                      if _top_list else [])
        audience = {
            'general': _general_details,
            'by_source': [a.get('details', {}) for a in _by_source],
            'by_variant': [a.get('details', {}) for a in _by_variant],
        }

        # ---- MODEL SCORE: decis por canal na régua ÚNICA do Challenger ----
        ctx = resolve_decis_context(pipeline, client_id=client_id)
        brt = _tz2(_td2(hours=-3))
        _today_brt = anchor_date or _dt2.now(brt).date()
        _today_mid = _dt2(_today_brt.year, _today_brt.month, _today_brt.day, 0, 0, 0, tzinfo=brt)
        _yest_start = (_today_mid - _td2(days=1)).astimezone(_tz2.utc)
        _yest_end = _today_mid.astimezone(_tz2.utc)
        _lw = resolve_launch_window_brt(today=anchor_date)
        _cap_end_eff = _lw.cap_end or _today_brt
        _ln = _lw.lf_name or 'LF atual (inferido)'
        _cs_dt = _dt2(_lw.cap_start.year, _lw.cap_start.month, _lw.cap_start.day,
                      0, 0, 0, tzinfo=brt).astimezone(_tz2.utc)
        _ce_dt = _dt2(_cap_end_eff.year, _cap_end_eff.month, _cap_end_eff.day,
                      23, 59, 59, tzinfo=brt).astimezone(_tz2.utc)
        # Fetch dos summaries cobrindo ambas as janelas (ontem ∪ lançamento) de uma vez.
        _recs = repo.summaries_in_range(min(_yest_start, _cs_dt), max(_yest_end, _ce_dt), limit=50_000)
        _recs_scored = [r for r in _recs if r.score is not None and r.decil is not None]
        _yest_records = records_between(_recs_scored, _yest_start, _yest_end, False)
        _lf_records = records_between(_recs_scored, _cs_dt, _ce_dt, True)
        previous_day = build_decis_window_payload(
            window_label='Ontem', start_utc=_yest_start, end_utc=_yest_end,
            pin_lf=False, lf_name=None, ctx=ctx,
            fallback_rows=records_to_quality_rows(_yest_records), fallback_records=_yest_records,
        )
        current_launch = build_decis_window_payload(
            window_label=f"{_ln} ({_lw.cap_start.strftime('%d/%m')}→{_cap_end_eff.strftime('%d/%m')} BRT)",
            start_utc=_cs_dt, end_utc=_ce_dt, pin_lf=False, lf_name=None, ctx=ctx,
            fallback_rows=records_to_quality_rows(_lf_records), fallback_records=_lf_records,
        )
        try:
            from src.data.scores_historicos import launch_score_geral
            _sg = launch_score_geral(_lw.lf_name)
            if _sg:
                current_launch['score_geral'] = _sg
        except Exception as _sge:
            logger.warning(f"⚠️ [audience-quality] score_geral falhou: {_sge}")
    finally:
        try:
            ledger_conn.close()
        except Exception:
            pass

    return {
        'ok': True,
        'client_id': client_id,
        'anchor_date': anchor_date.isoformat() if anchor_date else None,
        'audience': audience,
        'model_score': {
            'previous_day': previous_day,
            'current_launch': current_launch,
        },
    }


# Canal do grupo de tráfego pro relatório diário de criativo. Override por env
# opcional; fallback no grupo DevClub. NÃO é param público — só o endpoint
# /monitoring/utm-quality/daily-trafego (chamado pelo scheduler) posta, e só
# nesse canal. Assim quem chama o endpoint de leitura não consegue postar nada.
UTM_QUALITY_TRAFEGO_CHANNEL = os.getenv('UTM_QUALITY_TRAFEGO_CHANNEL', 'C09VD6J8A72')


def _utm_quality_day_range_brt(start_date: str, end_date: str):
    """Valida start_date/end_date (YYYY-MM-DD, dia-calendário BRT, ≤90d) e devolve
    (start_utc, end_utc). Levanta HTTPException 400 em erro."""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    _BRT = _tz(_td(hours=-3))
    try:
        _s = _dt.strptime(start_date, '%Y-%m-%d').replace(hour=0, minute=0, second=0, tzinfo=_BRT)
        _e = _dt.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59, tzinfo=_BRT)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato inválido. Use YYYY-MM-DD.")
    if _e < _s:
        raise HTTPException(status_code=400, detail="end_date não pode ser anterior a start_date.")
    if (_e.date() - _s.date()).days > 90:
        raise HTTPException(status_code=400, detail="Janela máxima de 90 dias.")
    return _s.astimezone(_tz.utc), _e.astimezone(_tz.utc)


def _utm_quality_compute(start_utc, end_utc, *, min_volume: int, top_n: int, client_id: str):
    """Ponto único de composição: abre o ledger na fonte de LEITURA configurada
    (LEDGER_READ_SOURCE), computa o ranking de UTM da janela e fecha a conn."""
    from src.monitoring.utm_quality import compute_utm_quality
    from src.data import compose_repository
    from src.data.ledger_connection import open_ledger_read_connection
    ledger_conn = open_ledger_read_connection()
    repo = compose_repository('registros_ml', railway_conn=ledger_conn)
    try:
        return compute_utm_quality(
            repo, client_id=client_id, top_n=top_n,
            min_volume=min_volume, start_utc=start_utc, end_utc=end_utc,
        )
    finally:
        try:
            ledger_conn.close()
        except Exception:
            pass


def _build_top5_for(result, client_id: str):
    """Comparação vs barra TOP5 ROAS (régua Challenger) por criativo e campanha,
    no nível do LANÇAMENTO acumulado (lê scores_historicos ⋈ registros_ml na
    janela do LF). Composição no endpoint — separado do ranking relativo. Degrada
    pra None (seção omitida)."""
    from src.monitoring.utm_quality import build_top5_comparison
    from datetime import datetime as _dt
    lf_name = result.window_lf.get('label')
    lf_s = result.window_lf.get('start')
    lf_e = result.window_lf.get('end')
    if not (lf_name and lf_s and lf_e and result.champion_run_id):
        return None
    try:
        return build_top5_comparison(
            lf_name=lf_name,
            # régua = CHAMPION (o pega-tudo), resolvido via ab_arm - casa com o
            # baseline fixo (gerado no champion) e segue promoções sozinho.
            challenger_run_id=result.champion_run_id,
            win_start=_dt.fromisoformat(lf_s),
            win_end=_dt.fromisoformat(lf_e),
            client_id=client_id,
        )
    except Exception as e:
        logger.warning("[utm-quality] build_top5 LF falhou (lf=%s): %s", lf_name, e)
        return None


def _build_top5_window(result, client_id: str, min_n: int = 100):
    """vs barra TOP5 da JANELA do ranking (start..end) — 'ontem' no job diário,
    ou o intervalo pedido no endpoint. Mesma régua/barra do LF, só muda a janela
    do `registros_ml` (os leads ainda casam pela scores_historicos do LF atual).

    N MÍNIMO 100, IGUAL À VISÃO DO LANÇAMENTO (era 50 até 12/08/2026)
    ================================================================
    O 50 vinha de "1 dia tem menos volume por criativo", que é verdade e não basta: a
    diferença REAL entre criativos é de ~11 pontos percentuais (desvio-padrão de 13,3pp
    medido em 21 criativos com N≥200, descontado o ruído de amostra desses mesmos 200).
    Dois erros-padrão dão 14,1pp em N=50 contra 10,0pp em N=100. Ou seja, em N=50 a barra
    de erro é MAIOR que a diferença que ela deveria medir, e a coluna de Δpp fica decorativa:
    exibe um número que não distingue criativo ruim de criativo azarado.

    Volume menor no dia é motivo para mostrar MENOS linha, não para baixar o piso. Efeito
    medido no dia 11/08/2026 (658 cadastros): a visão do dia sai de 7 linhas para 4, e as 3
    que somem são exatamente as que tinham entre 50 e 100 leads. Não é blecaute — é a mesma
    régua da visão do lançamento, que já usava 100 (o default de `build_top5_comparison`).

    E alinha com o que a agência recebe: a `scores_inbound` no Supabase deles publica com
    piso 100, então o número que ela lê e o que aparece aqui passam a ser o mesmo. Piso
    diferente nos dois lados é duas contas divergirem sem ninguém saber qual está certa.
    """
    from src.monitoring.utm_quality import build_top5_comparison
    from datetime import datetime as _dt
    lf_name = result.window_lf.get('label')
    w_s = result.window.get('start')
    w_e = result.window.get('end')
    if not (lf_name and w_s and w_e and result.champion_run_id):
        return None
    try:
        return build_top5_comparison(
            lf_name=lf_name,
            # régua = CHAMPION (ver _build_top5_for): casa o baseline fixo e segue promoção.
            challenger_run_id=result.champion_run_id,
            win_start=_dt.fromisoformat(w_s),
            win_end=_dt.fromisoformat(w_e),
            client_id=client_id,
            min_n=min_n,
            pin_lf=False,  # visão do DIA: conta quem entrou na janela, sem amarrar no lf
        )
    except Exception as e:
        logger.warning("[utm-quality] build_top5 janela falhou (lf=%s): %s", lf_name, e)
        return None


@router.get("/monitoring/utm-quality")
async def utm_quality_endpoint(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    min_volume: int = 20,
    top_n: int = 5,
    client_id: str = 'devclub',
):
    """
    Qualidade de Content (criativo) por modelo — SÓ LEITURA, dia(s) fixo(s).

    Ranqueia criativos (`utm_content`) por decil médio dos leads scoreados numa
    janela de dia(s)-calendário BRT `[start 00:00, end 23:59]` (até 90 dias).
    `start_date` e `end_date` são obrigatórios — `start==end` = um dia. A coluna
    LF é contexto/tendência point-in-time (não afeta o ranking). Os decis já estão
    pré-computados no ledger; o endpoint só lê e agrega (nenhum scoring).

    Devolve JSON. **Não posta no Slack** — o relatório diário pro grupo de tráfego
    é o endpoint dedicado `/monitoring/utm-quality/daily-trafego` (canal fixo no
    servidor). Atribuição por modelo reusa `ABTestConfig.match_variant`.

    Args:
        start_date/end_date: YYYY-MM-DD BRT, obrigatórios. start==end = 1 dia. ≤90d.
        min_volume: N mínimo de leads pra um criativo entrar no ranking (default 20).
        top_n: tamanho do Top piores e Top melhores (default 5).
        client_id: cliente (carrega `configs/active_models/{id}.yaml`).
    """
    if not (start_date and end_date):
        raise HTTPException(status_code=400, detail="start_date e end_date são obrigatórios (YYYY-MM-DD).")
    start_utc, end_utc = _utm_quality_day_range_brt(start_date, end_date)
    try:
        result = _utm_quality_compute(start_utc, end_utc, min_volume=min_volume, top_n=top_n, client_id=client_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"compute_utm_quality falhou: {e}")
    return {
        'ok': True,
        'window': result.window,
        'window_lf':  result.window_lf,
        'champion_name':  result.champion_name,
        'challenger_name': result.challenger_name,
        'ranking': result.ranking,
        'top5_vs_padrao_janela': _build_top5_window(result, client_id),
        'top5_vs_padrao_lf': _build_top5_for(result, client_id),
    }


def _resolve_report_channel(dest: str) -> str:
    """Ponto ÚNICO de destino do relatório de criativo. 'trafego' (default) = canal
    do cliente (produção, usado pelo cron); 'dm'/'validacao' = DM do operador
    (validação de formatação antes de liberar pro cliente). Os IDs vêm do config.sh
    (`UTM_QUALITY_TRAFEGO_CHANNEL` / `SLACK_VALIDATION_DM_CHANNEL`) — pinados lá, não
    no default da app, pra não vazarem entre revisões (deploy usa --update-env-vars)."""
    d = (dest or 'trafego').strip().lower()
    if d in ('dm', 'validacao', 'validation'):
        return os.getenv('SLACK_VALIDATION_DM_CHANNEL', 'D0A9USV3XEX')
    return UTM_QUALITY_TRAFEGO_CHANNEL


@router.get("/monitoring/utm-quality/daily-trafego")
async def utm_quality_daily_trafego(min_volume: int = 20, top_n: int = 5,
                                    client_id: str = 'devclub',
                                    dest: str = 'trafego',
                                    date: Optional[str] = None,
                                    start_date: Optional[str] = None,
                                    end_date: Optional[str] = None,
                                    force: bool = False):
    """
    Relatório diário de criativo, postado no Slack. Default: dia ANTERIOR (BRT) →
    grupo de tráfego (cliente), chamado pelo Cloud Scheduler às 06:00.

    Destino parametrizado via `_resolve_report_channel` (ponto único):
      - dest='trafego' (default): canal do cliente. É o que o cron usa.
      - dest='dm' (ou 'validacao'): DM do operador — pra VALIDAR formatação antes
        de liberar pro cliente (política: validação→DM, OK explícito→trafego).

    Janela (BRT), em ordem de precedência:
      - `start_date`+`end_date`: intervalo FUNDIDO (ex.: ontem+hoje num só
        relatório). ≤90d, valida em `_utm_quality_day_range_brt`.
      - `date`: um dia específico.
      - nada: dia ANTERIOR (comportamento do cron da manhã 06:40).
    Aceitam YYYY-MM-DD OU os tokens relativos `hoje`/`ontem` (resolvidos no
    request). É assim que o cron da TARDE (14h) manda ontem+hoje sem a URL saber a
    data: `?start_date=ontem&end_date=hoje`. A linha "Lançamento" é sempre o
    acumulado; só a janela muda.

    Substitui o antigo hack de subir canary com env de canal redirecionado pra
    postar no DM: agora é `?dest=dm[&date=…]` ou `?dest=dm&start_date=…&end_date=…`.

    Trava de tráfego (`src/monitoring/traffic_gate`): sem lead de origem PAGA na
    janela não há criativo pra ranquear, então não posta — devolve 200 com
    `skipped`. `force=1` posta de qualquer jeito; `REPORTS_REQUIRE_TRAFFIC=0`
    desliga a trava sem deploy.
    """
    from src.monitoring.utm_quality import render_slack_blocks, post_to_slack
    from src.monitoring.traffic_gate import check_from_utm_result, trava_habilitada
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    _BRT = _tz(_td(hours=-3))

    def _rel_day(tok):
        """Tokens relativos p/ o cron pedir janela dinâmica numa URL estática:
        'hoje'/'ontem' → 'YYYY-MM-DD' BRT (resolvido no request). YYYY-MM-DD
        explícito passa direto. É o que permite o envio das 14h mandar ontem+hoje
        (start_date=ontem&end_date=hoje) sem a URL saber a data."""
        if not tok:
            return tok
        t = str(tok).strip().lower()
        _today = _dt.now(_BRT).date()
        if t == 'hoje':
            return _today.isoformat()
        if t == 'ontem':
            return (_today - _td(days=1)).isoformat()
        return tok

    date = _rel_day(date)
    start_date = _rel_day(start_date)
    end_date = _rel_day(end_date)
    if start_date and end_date:
        start_utc, end_utc = _utm_quality_day_range_brt(start_date, end_date)
    elif date:
        start_utc, end_utc = _utm_quality_day_range_brt(date, date)
    else:
        _ontem = (_dt.now(_BRT) - _td(days=1)).date()
        _s = _dt(_ontem.year, _ontem.month, _ontem.day, 0, 0, 0, tzinfo=_BRT)
        _e = _dt(_ontem.year, _ontem.month, _ontem.day, 23, 59, 59, tzinfo=_BRT)
        start_utc, end_utc = _s.astimezone(_tz.utc), _e.astimezone(_tz.utc)
    channel = _resolve_report_channel(dest)
    try:
        result = _utm_quality_compute(start_utc, end_utc, min_volume=min_volume, top_n=top_n, client_id=client_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"compute_utm_quality falhou: {e}")

    _gate = check_from_utm_result(result)
    if not _gate.ativo and not force and trava_habilitada():
        logger.info(f"⏸️ utm-quality NÃO postado ({channel}) — {_gate.motivo}")
        return {'ok': True, 'skipped': 'sem_trafego', 'channel': channel, 'dest': dest,
                'window': result.window.get('label'), 'gate': _gate.as_dict()}

    top5_lf = _build_top5_for(result, client_id)
    top5_window = _build_top5_window(result, client_id)
    blocks = render_slack_blocks(result, top5_lf=top5_lf, top5_window=top5_window)
    lf_label = result.window_lf.get('label') or '—'
    win_label = result.window.get('label') or 'ontem'
    post = post_to_slack(channel, blocks, fallback_text=f'UTM Quality {win_label} × {lf_label}')
    post['blocks_count'] = len(blocks)
    if not post.get('ok'):
        raise HTTPException(status_code=502, detail=f"Slack: {post.get('error')}")
    return {'ok': True, 'channel': channel, 'dest': dest, 'window': win_label, 'post': post,
            'gate': _gate.as_dict()}


@router.get("/monitoring/cost-alert")
async def cost_alert(limite: Optional[float] = None,
                     servico: str = 'Cloud Run',
                     date: Optional[str] = None,
                     force: bool = False):
    """
    Alerta de custo de infraestrutura - manda DM se o gasto de um dia estourar o teto.

    É o ponto único de composição do alerta: aqui se decide o dia, o teto e o
    destino; a leitura do faturamento e a regra ficam em
    `src/monitoring/gcp_cost.py` e `src/monitoring/cost_alert.py`.

    Chamado 1x/dia pelo Cloud Scheduler de manhã, logo depois do relatório
    diário. Só produz mensagem quando há o que avisar:
      - uso do dia acima do teto → DM com o ranking de quem gastou
      - faturamento sem nenhuma linha do dia → DM de "não consegui medir"
        (export quebrado devolveria zero, e zero passaria por dia calmo)
      - dentro do teto → responde 200 sem postar nada

    Parâmetros:
      - `limite`: teto do dia em reais. Sem ele, vale o valor da variável de
        ambiente `CLOUD_RUN_COST_ALERT_BRL` (hoje R$ 10) - mudar o teto não
        exige deploy.
      - `servico`: nome do serviço no faturamento do Google ('Cloud Run',
        'Cloud SQL', 'BigQuery'…). Default 'Cloud Run'.
      - `date`: dia YYYY-MM-DD no calendário de Brasília, ou os tokens
        `ontem`/`hoje`. Sem ele, ontem - o último dia completo.
      - `force=1`: posta mesmo estando dentro do teto, pra validar a formatação
        da mensagem sem esperar um estouro real.

    O destino é SEMPRE o DM do operador (`SLACK_USER_DM`), nunca canal de
    cliente: é informação de infraestrutura nossa.
    """
    from datetime import date as _date, datetime as _dt, timedelta as _td
    from src.monitoring.cost_alert import LIMITE_DEFAULT, dia_anterior_brt, executar
    from src.monitoring.gcp_cost import BRT

    dia: Optional[_date] = None
    if date:
        tok = str(date).strip().lower()
        if tok == 'ontem':
            dia = dia_anterior_brt()
        elif tok == 'hoje':
            dia = _dt.now(BRT).date()
        else:
            try:
                dia = _dt.strptime(tok, '%Y-%m-%d').date()
            except ValueError:
                raise HTTPException(status_code=400,
                                    detail="date inválida - use YYYY-MM-DD, 'ontem' ou 'hoje'")

    try:
        resultado = executar(dia=dia,
                             limite=LIMITE_DEFAULT if limite is None else float(limite),
                             servico=servico, force=force)
    except Exception as e:
        # Falha de leitura do faturamento (permissão, tabela sumida, BigQuery
        # fora do ar) é erro de verdade - 500 pra aparecer como falha do cron,
        # não 200 silencioso que passaria por "dia dentro do teto".
        logger.error(f"[cost-alert] falhou ao avaliar custo: {e}")
        raise HTTPException(status_code=500, detail=f"cost-alert falhou: {e}")

    if not resultado.get('ok'):
        raise HTTPException(status_code=502, detail=f"cost-alert: {resultado.get('erro')}")
    return resultado


@router.get("/monitoring/painel-vigia")
async def painel_vigia(horas: Optional[float] = None, force: bool = False):
    """
    Vigia do painel da agência - DM se o painel travar, esvaziar ou ficar cego.

    Ponto único de composição: aqui se escolhem as DUAS conexões (o banco da
    agência onde o painel mora, e o analytics onde vive a janela do
    gerenciador) e o destino do aviso. A regra inteira fica em
    `src/monitoring/painel_vigia.py`.

    Chamado de hora em hora pelo Cloud Scheduler, depois da rodada do robô de
    publicação (cron :22). Só produz mensagem quando há o que avisar:
      - painel sem escrita há mais de `horas` (default 2 = duas rodadas
        perdidas) → 🔴 travado, com onde olhar
      - painel sem nenhuma linha → 🔴 vazio
      - conjuntos de anúncios homônimos na mesma campanha (janela de 3 dias)
        → ⚠️ split por público cego; pedir nome distinto ao tráfego
      - tudo em dia → responde 200 sem postar nada (`force=1` posta o 🟢)

    Nasceu do incidente de 18/08/2026: o robô morreu na estreia do LF65 e o
    painel exibiu o "hoje" de ontem por 11 horas - quem percebeu foi o gestor.
    """
    from src.monitoring.painel_vigia import LIMITE_HORAS_DEFAULT, executar as vigiar

    def _abre_destino():
        from scripts.push_supabase_zanelato import destino
        return destino(porta=5432)

    def _abre_analytics():
        from src.data.analytics_connection import open_analytics_connection
        return open_analytics_connection(timeout=120)

    try:
        resultado = vigiar(_abre_destino, _abre_analytics,
                           limite_horas=(LIMITE_HORAS_DEFAULT if horas is None
                                         else float(horas)),
                           force=force)
    except Exception as e:
        # Vigia que não consegue medir É alarme: 500 aparece como falha do
        # cron, nunca 200 silencioso passando por "painel em dia".
        logger.error(f"[painel-vigia] falhou ao medir: {e}")
        raise HTTPException(status_code=500, detail=f"painel-vigia falhou: {e}")

    if not resultado.get('ok'):
        raise HTTPException(status_code=502,
                            detail=f"painel-vigia: {resultado.get('erro')}")
    return resultado


@router.get("/smoke/run-variants")
async def smoke_run_variants(
    pipeline: PipelineDep,
    limit: int = 5,
    hours: int = 24,
):
    """
    [T1-14] Roda o pipeline para cada variante A/B explicitamente.

    Pega N leads recentes do Railway e força cada variante (incluindo o
    Champion default) a scorear com seu predictor + encoding_overrides
    correspondente. Retorna pass/fail por variante.

    Cobre o gap descoberto via investigação V.1 (registro_erros_ml.md):
    o smoke test antigo chamava `/monitoring/daily-check/railway` sem
    contexto A/B e nunca exercitava Champion com encoding_overrides
    nem variantes shim — bug do Cluster 5 (29/abr–05/mai/2026) passou
    por isso.

    Args:
        limit: Quantos leads usar para o teste (default 5).
        hours: Janela de leads recentes do Railway (default 24h).
    """
    import pg8000.native
    from src.model.decil_thresholds import atribuir_decis_batch

    start_time = time.time()
    results: List[Dict[str, Any]] = []

    # 1. Buscar leads recentes do Railway
    try:
        railway_conn = pg8000.native.Connection(
            host=os.environ['RAILWAY_DB_HOST'],
            port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
            database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
            user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
            password=os.environ['RAILWAY_DB_PASSWORD'],
            timeout=30,
        )
        from datetime import timezone as _tz, timedelta as _td
        cutoff = datetime.now(_tz.utc) - _td(hours=hours)
        rows = railway_conn.run(
            'SELECT id, data, "nomeCompleto", email, telefone, pesquisa, '
            'source, medium, campaign, content, term, '
            '"remoteIp", "userAgent", fbc, fbp, "pageUrl" '
            'FROM "Lead" '
            'WHERE pesquisa IS NOT NULL '
            'AND "createdAt" >= :start '
            'ORDER BY "createdAt" DESC '
            'LIMIT :lim',
            start=cutoff, lim=limit,
        )
        railway_conn.close()
    except Exception as e:
        return {
            'overall_status': 'fail',
            'reason': f'Falha ao buscar leads do Railway: {type(e).__name__}: {str(e)[:200]}',
            'variants_tested': 0,
            'results': [],
        }

    if not rows:
        return {
            'overall_status': 'no_data',
            'reason': f'Nenhum lead com pesquisa nas últimas {hours}h',
            'variants_tested': 0,
            'results': [],
        }

    # 2. Converter para DataFrame no formato que o pipeline espera
    from api.railway_mapping import railway_lead_to_sheets_row
    col_names = [
        'id', 'data', 'nomeCompleto', 'email', 'telefone', 'pesquisa',
        'source', 'medium', 'campaign', 'content', 'term',
        'remoteIp', 'userAgent', 'fbc', 'fbp', 'pageUrl',
    ]
    sheets_rows = [railway_lead_to_sheets_row(dict(zip(col_names, r))) for r in rows]
    df_input_base = pd.DataFrame(sheets_rows)

    # 3. Montar lista de variantes a testar
    variants_to_test: List[Dict[str, Any]] = []

    # Default Champion (sempre — sem A/B, ou caminho default em A/B)
    variants_to_test.append({
        'name': 'default',
        'predictor_override': None,
        'encoding_overrides': None,
        'expected_run_id': pipeline.predictor.mlflow_run_id
            if hasattr(pipeline.predictor, 'mlflow_run_id') else None,
    })

    # Variantes do A/B (se enabled)
    ab_cfg = getattr(pipeline, '_ab_test_config', None)
    if ab_cfg and getattr(ab_cfg, 'enabled', False):
        for vname, variant in (ab_cfg.variants or {}).items():
            try:
                pred = pipeline.get_variant_predictor(vname)
            except Exception as e:
                results.append({
                    'variant': vname,
                    'status': 'fail',
                    'expected_run_id': getattr(variant, 'run_id', None),
                    'errors': f'get_variant_predictor falhou: {type(e).__name__}: {str(e)[:200]}',
                })
                continue
            variants_to_test.append({
                'name': vname,
                'predictor_override': pred,
                'encoding_overrides': getattr(variant, 'encoding_overrides', None),
                'expected_run_id': variant.run_id,
            })

    # 4. Rodar pipeline para cada variante
    for vinfo in variants_to_test:
        name = vinfo['name']
        try:
            pipeline.data = df_input_base.copy()
            df_processed = pipeline.preprocess(
                encoding_overrides=vinfo['encoding_overrides'],
                predictor_override=vinfo['predictor_override'],
            )
            predictor = vinfo['predictor_override'] or pipeline.predictor
            actual_run_id = predictor.mlflow_run_id \
                if hasattr(predictor, 'mlflow_run_id') else None

            # Scoring
            X = df_processed[predictor.feature_names]
            scores = predictor.model.predict_proba(X)[:, 1]
            score_min, score_max = float(scores.min()), float(scores.max())
            scores_valid = (0 <= score_min) and (score_max <= 1)

            # Decis
            decis_dist: Dict[str, int] = {}
            decis_valid = False
            thresholds = (predictor.metadata or {}).get('decil_thresholds', {}).get('thresholds')
            if thresholds:
                decis = atribuir_decis_batch(scores, thresholds)
                expected = {f"D{i:02d}" for i in range(1, 11)}
                decis_valid = set(decis).issubset(expected)
                decis_dist = pd.Series(decis).value_counts().sort_index().to_dict()

            run_id_match = (vinfo['expected_run_id'] is None) or \
                (actual_run_id == vinfo['expected_run_id'])

            all_passed = scores_valid and decis_valid and run_id_match
            results.append({
                'variant': name,
                'status': 'pass' if all_passed else 'fail',
                'expected_run_id': vinfo['expected_run_id'],
                'actual_run_id': actual_run_id,
                'leads_scored': len(df_processed),
                'score_range': [score_min, score_max],
                'decis_distribution': decis_dist,
                'validations': {
                    'scores_in_range': scores_valid,
                    'decis_valid': decis_valid,
                    'run_id_match': run_id_match,
                },
                'errors': None,
            })
        except Exception as e:
            import traceback
            results.append({
                'variant': name,
                'status': 'fail',
                'expected_run_id': vinfo.get('expected_run_id'),
                'actual_run_id': None,
                'errors': f"{type(e).__name__}: {str(e)[:300]}",
                'traceback_snippet': traceback.format_exc()[-500:],
            })

    overall = 'pass' if all(r.get('status') == 'pass' for r in results) else 'fail'
    return {
        'overall_status': overall,
        'leads_used': len(df_input_base),
        'variants_tested': len(results),
        'processing_time_seconds': round(time.time() - start_time, 2),
        'results': results,
    }


@router.get("/validation/test", dependencies=[Depends(exigir_token_interno())])
async def test_validation_dependencies():
    """
    Testa rapidamente se todas as dependências para validação estão OK.
    Retorna em segundos, não minutos.
    """
    try:
        errors = []
        warnings = []

        # 1. Testar imports críticos
        try:
            from src.validation.period_calculator import PeriodCalculator
            from src.validation.slack_notifier import ValidationSlackNotifier
            import matplotlib.pyplot as plt
            import seaborn as sns
            from tabulate import tabulate
            import openpyxl
            import xlsxwriter
        except ImportError as e:
            errors.append(f"Import failed: {str(e)}")

        # 2. Testar paths críticos
        from pathlib import Path
        script_path = _RAIZ / 'src' / 'validation' / 'validate_ml_performance.py'
        if not script_path.exists():
            errors.append(f"Script not found: {script_path}")

        vendas_dir = _RAIZ / 'vendas'
        if not vendas_dir.exists():
            warnings.append(f"Vendas dir not found: {vendas_dir}")

        # 3. Testar env vars
        meta_source = os.getenv('META_DATA_SOURCE', 'local')
        bucket_name = os.getenv('VALIDATION_REPORTS_BUCKET', 'bring-data-validation-reports')

        # 4. Testar Cloud Storage
        try:
            from google.cloud import storage
            storage_client = storage.Client()
            bucket = storage_client.bucket(bucket_name)
            if not bucket.exists():
                warnings.append(f"Bucket doesn't exist: {bucket_name}")
        except Exception as e:
            warnings.append(f"Cloud Storage test failed: {str(e)}")

        # 5. Testar cálculo de datas
        from datetime import datetime, timedelta
        today = datetime.now()
        test_monday = today - timedelta(days=today.weekday() + 28)

        return {
            "status": "error" if errors else "ok",
            "errors": errors,
            "warnings": warnings,
            "config": {
                "meta_data_source": meta_source,
                "bucket": bucket_name,
                "script_exists": script_path.exists(),
                "test_date_calc": test_monday.strftime('%Y-%m-%d')
            },
            "dependencies_ok": len(errors) == 0
        }

    except Exception as e:
        return {
            "status": "error",
            "errors": [str(e)],
            "dependencies_ok": False
        }


@router.post("/validation/weekly", dependencies=[Depends(exigir_token_interno())])
async def execute_weekly_validation(db: Session = Depends(get_db)):
    """
    Executa validação semanal do modelo ML.

    - Calcula período automaticamente (semana anterior)
    - Executa validate_ml_performance.py com flags apropriadas
    - Faz upload do Excel para Cloud Storage
    - Envia sumário para Slack

    Chamado automaticamente por Cloud Scheduler toda segunda-feira às 10h.
    """
    import subprocess
    from pathlib import Path
    from datetime import timedelta
    from google.cloud import storage
    from src.validation.period_calculator import PeriodCalculator
    from src.validation.slack_notifier import ValidationSlackNotifier

    try:
        from datetime import datetime
        today = datetime.now()

        logger.info("🚀 Iniciando validação semanal...")

        # TEMPORÁRIO: Testando com Campanha Atípica 1 (16/12/2025 - 25/01/2026)
        # TODO: Voltar para cálculo automático depois do teste
        start_date = '2025-12-16'
        end_date = '2026-01-12'
        sales_start = '2026-01-19'
        sales_end = '2026-01-25'

        logger.info(f"📅 TESTE Campanha Atípica 1: captação={start_date} a {end_date}, vendas={sales_start} a {sales_end}")

        # 2. Executar script de validação
        script_path = _RAIZ / 'src' / 'validation' / 'validate_ml_performance.py'

        cmd = [
            'python',
            str(script_path),
            '--start-date', start_date,
            '--end-date', end_date,
            '--sales-start-date', sales_start,
            '--sales-end-date', sales_end
        ]

        # Configurar environment variables
        env = os.environ.copy()
        env['GURU_DATA_SOURCE'] = 'api'
        env['META_DATA_SOURCE'] = os.getenv('META_DATA_SOURCE', 'local')  # local para testes, api para produção
        env['INTERNAL_API_URL'] = 'http://localhost:8080'  # Script usa localhost para acessar a própria API

        logger.info(f"🔧 Executando validação (GURU=api, META={env['META_DATA_SOURCE']})...")
        logger.info(f"🔧 Comando: {' '.join(cmd)}")

        # CRÍTICO: NÃO usar capture_output=True para permitir streaming de logs em tempo real
        # Isso faz os logs do script aparecerem diretamente no Cloud Run
        result = subprocess.run(
            cmd,
            capture_output=False,  # Permite streaming de logs!
            text=True,
            cwd=_RAIZ,
            env=env,
            timeout=600  # 10 minutos timeout
        )

        # Nota: Como não estamos capturando output, não temos result.stdout/stderr
        # Mas os logs aparecem em tempo real no Cloud Run, facilitando debug

        if result.returncode != 0:
            error_msg = f"Script falhou (exit code {result.returncode})"
            logger.error(f"❌ {error_msg}")

            # Notificar erro no Slack
            notifier = ValidationSlackNotifier()
            notifier.send_error_notification(
                error_message=error_msg,
                period={'start': start_date, 'sales_start': sales_start, 'sales_end': sales_end}
            )

            raise HTTPException(status_code=500, detail=error_msg)

        logger.info("✅ Script de validação executado com sucesso")

        # 3. Encontrar Excel gerado
        results_dir = _RAIZ / 'files' / 'validation' / 'resultados'
        excel_files = sorted(results_dir.glob('validation_report_*.xlsx'), key=lambda p: p.stat().st_mtime)

        if not excel_files:
            raise HTTPException(status_code=500, detail="Excel não foi gerado")

        latest_excel = excel_files[-1]
        logger.info(f"📊 Excel encontrado: {latest_excel.name}")

        # 4. Upload para Cloud Storage
        bucket_name = os.getenv('VALIDATION_REPORTS_BUCKET', 'bring-data-validation-reports')

        try:
            storage_client = storage.Client()
            bucket = storage_client.bucket(bucket_name)

            # Nome do blob: validation/2026/01/validacao_20260127_103045.xlsx
            blob_name = f"validation/{today.year}/{today.month:02d}/{latest_excel.name}"
            blob = bucket.blob(blob_name)

            blob.upload_from_filename(str(latest_excel))
            blob.make_public()

            excel_url = blob.public_url
            logger.info(f"☁️ Upload concluído: {excel_url}")

        except Exception as storage_error:
            logger.warning(f"⚠️ Erro no upload Cloud Storage: {storage_error}")
            excel_url = None

        # 5. Enviar notificação Slack (sem métricas detalhadas, apenas sucesso)
        # Nota: Como não estamos capturando stdout, não temos acesso às métricas parseadas
        # Mas o Excel tem todas as informações necessárias
        notifier = ValidationSlackNotifier()
        notifier.send_validation_summary(
            metrics={"status": "success", "message": "Validação concluída - detalhes no Excel"},
            excel_url=excel_url,
            period={
                'start': start_date,
                'sales_start': sales_start,
                'sales_end': sales_end
            }
        )

        logger.info("✅ Validação semanal concluída com sucesso!")

        return {
            "status": "success",
            "message": "Validação semanal executada com sucesso",
            "period": {
                "captacao": start_date,
                "vendas": f"{sales_start} a {sales_end}"
            },
            "excel_url": excel_url
        }

    except subprocess.TimeoutExpired:
        error_msg = "Validação excedeu timeout de 10 minutos"
        logger.error(f"❌ {error_msg}")

        notifier = ValidationSlackNotifier()
        notifier.send_error_notification(error_msg)

        raise HTTPException(status_code=408, detail=error_msg)

    except Exception as e:
        logger.error(f"❌ Erro na validação semanal: {str(e)}")

        notifier = ValidationSlackNotifier()
        notifier.send_error_notification(str(e))

        raise HTTPException(status_code=500, detail=str(e))


def _parse_validation_metrics(stdout: str) -> dict:
    """
    Extrai métricas do output do script de validação.

    Procura por linhas como:
    - "AUC Produção: 0.8234 (Test Set: 0.8156, Δ: +0.0078)"
    - "Conversões: 177"
    - "ROAS COM ML: 2.04x"
    """
    import re

    metrics = {
        'auc_production': 0.0,
        'auc_test_set': 0.0,
        'conversoes': 0,
        'roas': 0.0,
        'leads_analisados': 0,
        'top3_production': 0.0,
        'top3_test_set': 0.0
    }

    try:
        # AUC
        auc_match = re.search(r'AUC Produção:\s*([\d.]+)\s*\(Test Set:\s*([\d.]+)', stdout)
        if auc_match:
            metrics['auc_production'] = float(auc_match.group(1))
            metrics['auc_test_set'] = float(auc_match.group(2))

        # Concentração Top 3
        top3_match = re.search(r'Top 3 Decis:\s*([\d.]+)%\s*\(Test Set:\s*([\d.]+)%', stdout)
        if top3_match:
            metrics['top3_production'] = float(top3_match.group(1))
            metrics['top3_test_set'] = float(top3_match.group(2))

        # Conversões
        conv_match = re.search(r'(\d+)\s+trackeadas', stdout)
        if conv_match:
            metrics['conversoes'] = int(conv_match.group(1))

        # ROAS
        roas_match = re.search(r'ROAS COM ML:\s*([\d.]+)x', stdout)
        if roas_match:
            metrics['roas'] = float(roas_match.group(1))

        # Leads
        leads_match = re.search(r'(\d+)\s+leads.*com score válido', stdout)
        if leads_match:
            metrics['leads_analisados'] = int(leads_match.group(1))

    except Exception as e:
        logger.warning(f"⚠️ Erro ao extrair métricas: {e}")

    return metrics
