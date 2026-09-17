"""Fila de scoring: /railway/process-pending e /pubsub/process-pending.

Gerado a partir do app.py monolítico (corte por domínio, corpo dos handlers intacto)."""
import os
import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile, File
from typing import Annotated, List, Dict, Any, Optional
import time
import tempfile
import uuid
from datetime import datetime
from api.capi_integration import send_batch_events, should_send_to_destination
from src.model.decil_thresholds import atribuir_decil_por_threshold
from fastapi import APIRouter
import logging
from api.state import PipelineDep

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/railway/process-pending")
async def railway_process_pending(pipeline: PipelineDep, dry_run: bool = False):
    """
    Processa leads pendentes do Railway PostgreSQL (leadScore IS NULL).

    Chamado pelo Cloud Scheduler a cada 5 minutos.

    Fluxo:
    1. Conecta ao Railway PostgreSQL via pg8000
    2. Busca até 50 leads sem score (ORDER BY createdAt ASC)
    3. Converte pesquisa JSONB → formato Google Sheets via railway_mapping
    4. Roda pipeline ML em batch → lead_score + decil
    5. Atualiza Railway: leadScore, decil, updatedAt
    6. Envia eventos CAPI para Meta

    Args:
        dry_run: Quando True, executa passos 1-4 (leitura + scoring) mas PULA
                 passos 5-6 (escrita no banco + envio CAPI). Usado pelo smoke
                 test pós-canary pra exercitar o caminho de polling sem efeito
                 colateral em produção. Resposta inclui `dry_run: true`.
    """

    import pg8000.native
    import json as _json
    from api.railway_mapping import railway_lead_to_sheets_row

    railway_conn = None
    try:
        # 1. Conectar ao Railway PostgreSQL
        railway_conn = pg8000.native.Connection(
            host=os.environ['RAILWAY_DB_HOST'],
            port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
            database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
            user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
            password=os.environ['RAILWAY_DB_PASSWORD'],
            timeout=30,
        )

        # 2. Re-scoring da Lead APOSENTADO — Etapa 5 do PLANO_LEDGER_CLOUDSQL.
        # A tabela Lead morreu (~17/05); o scoring novo é via Pub/Sub → ledger
        # registros_ml no Cloud SQL. Re-scorear aqui re-popularia o
        # leadScore/decil que a Etapa 5 anula (UPDATE Lead) E re-enviaria CAPI ao
        # Meta dos 142k leads antigos. Forçamos `rows = []` → o endpoint cai no
        # caminho "nenhum lead pendente", que ainda dispara os alertas críticos +
        # heartbeat (que SÓ rodam aqui — vide /sw-architect). O bloco de scoring
        # abaixo fica inalcançável; remoção + desacoplamento dos alertas pra job
        # próprio = follow-up (item 3.7 do plano).
        _polling_limit = pipeline._client_config.api.railway_polling_batch_size  # noqa: F841 (legado)
        rows = []

        def _run_critical_alerts_safely(_conn):
            """Hook crítico: registra status do polling + roda as 6 regras.
            Falha NÃO pode quebrar o polling. Vide docs/CRITICAL_ALERTS_SPEC.md."""
            try:
                from src.monitoring.critical_alerts import (
                    run_critical_checks, record_polling_status, GcsStateStore,
                )
                _store = GcsStateStore()
                record_polling_status(_store, status='ok')
                _store.flush()
                _ca_summary = run_critical_checks(_conn)
                logger.info(f"🚨 critical_alerts: {_ca_summary}")
            except Exception as _cae:
                logger.warning(f"⚠️ critical_alerts falhou (não bloqueia polling): {_cae}")

        def _run_survey_branch_safely(_conn):
            """I4: ramo isolado lead_surveys → CAPI scoreado. NUNCA propaga
            (não pode derrubar o polling do Lead). Off por SURVEY_CAPI_ENABLED
            (deploy ≠ ligar). Vide docs/PROCESSO_CAPI_LEAD_SURVEYS.md §9."""
            try:
                from api.survey_branch import is_enabled, process_pending_surveys
                if not is_enabled():
                    return
                _sb = process_pending_surveys(_conn, pipeline, dry_run=dry_run)
                logger.info(f"🧩 survey_branch: {_sb}")
            except Exception as _sbe:
                logger.error(f"❌ survey_branch falhou (não bloqueia polling): {_sbe}")

        if not rows:
            logger.info("✅ Railway polling: nenhum lead pendente")
            # Regras de critical_alerts avaliam janelas de 60min — rodam
            # independente de haver batch atual de leads pendentes.
            _run_critical_alerts_safely(railway_conn)
            _run_survey_branch_safely(railway_conn)
            return {"processed": 0, "skipped": 0, "dry_run": dry_run,
                    "message": "Nenhum lead pendente"}

        logger.info(f"📋 Railway polling: {len(rows)} leads pendentes encontrados")

        # 3. Construir lista de dicts (pg8000.native retorna listas, não dicts)
        col_names = [
            'id', 'data', 'nomeCompleto', 'email', 'telefone', 'pesquisa',
            'source', 'medium', 'campaign', 'content', 'term',
            'remoteIp', 'userAgent', 'fbc', 'fbp', 'pageUrl',
        ]

        lead_dicts = []
        for row in rows:
            lead = dict(zip(col_names, row))
            # pesquisa JSONB: pg8000 pode retornar string ou dict
            if isinstance(lead.get('pesquisa'), str):
                try:
                    lead['pesquisa'] = _json.loads(lead['pesquisa'])
                except Exception:
                    lead['pesquisa'] = {}
            elif lead.get('pesquisa') is None:
                lead['pesquisa'] = {}
            # Fallback: fbp/fbc podem estar no JSONB pesquisa (frontend v2)
            if not lead.get('fbp') and lead['pesquisa'].get('fbp'):
                lead['fbp'] = lead['pesquisa']['fbp']
            if not lead.get('fbc') and lead['pesquisa'].get('fbc'):
                lead['fbc'] = lead['pesquisa']['fbc']
            lead_dicts.append(lead)

        # 4. Converter para formato Google Sheets via railway_mapping
        sheets_rows = []
        valid_leads = []
        for lead in lead_dicts:
            try:
                sheets_row = railway_lead_to_sheets_row(lead, client_config=pipeline._client_config if pipeline else None)
                sheets_rows.append(sheets_row)
                valid_leads.append(lead)
            except Exception as e:
                logger.warning(f"⚠️ Erro ao mapear lead {lead.get('email')}: {e}")

        if not sheets_rows:
            return {
                "processed": 0,
                "skipped": len(lead_dicts),
                "message": "Todos os leads falharam no mapeamento",
            }

        # 5. A/B routing: particionar leads por variante antes de rodar o pipeline
        # Cada grupo usa o predictor e os thresholds da sua variante
        ab_variant_per_lead = []   # índice → ABTestVariantConfig ou None
        ab_name_per_lead = []      # índice → nome da variante ou None
        for lead in valid_leads:
            lead_utms = {
                'utm_campaign': lead.get('campaign'),
                'utm_content':  lead.get('content'),
                'utm_source':   lead.get('source'),
                'utm_medium':   lead.get('medium'),
                'utm_term':     lead.get('term'),
            }
            ab_variant = pipeline.get_ab_variant(
                lead_utms,
                event_source_url=lead.get('pageUrl') or lead.get('event_source_url'),
            )
            ab_variant_per_lead.append(ab_variant)
            if ab_variant:
                ab_variant_name = next(
                    n for n, v in pipeline._ab_test_config.variants.items() if v is ab_variant
                )
                ab_name_per_lead.append(ab_variant_name)
            else:
                ab_name_per_lead.append(None)

        # Agrupar índices por nome de variante (None = fora do teste)
        from collections import defaultdict
        variant_groups = defaultdict(list)   # variant_name_or_None → [i, ...]
        for i, vname in enumerate(ab_name_per_lead):
            variant_groups[vname].append(i)

        # Rodar pipeline por grupo, coletar score+decil por índice
        score_by_index = {}   # i → (lead_score, decil_str)
        # [Estancar o estrago] grupos que o validador pós-encoding bloquear
        # ficam aqui pra status terminal + alerta fail-loud (em vez de derrubar
        # o ciclo inteiro com HTTP 500 e re-tentar os mesmos leads pra sempre).
        feature_blocked_lead_ids: list = []
        feature_blocked_feature_names: set = set()
        feature_blocked_run_id = ''
        for vname, indices in variant_groups.items():
            predictor_ov = pipeline.get_variant_predictor(vname) if vname else pipeline.predictor
            # DT-12: encoding_overrides por variante (ex: jan30 usa ordinal para idade/salário).
            # Leads sem variante (vname=None) vão para o Champion — buscar o config da variante
            # cujo run_id coincide com pipeline.predictor para aplicar os mesmos overrides.
            if vname:
                variant_cfg = pipeline._ab_test_config.variants.get(vname)
            else:
                champion_run_id = pipeline.predictor.mlflow_run_id if hasattr(pipeline.predictor, 'mlflow_run_id') else None
                variant_cfg = next(
                    (v for v in pipeline._ab_test_config.variants.values() if v.run_id == champion_run_id),
                    None,
                ) if champion_run_id else None
            enc_overrides = variant_cfg.encoding_overrides if variant_cfg else None
            group_sheets = [sheets_rows[i] for i in indices]
            group_df = pd.DataFrame(group_sheets)
            temp_file = None
            group_result = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp:
                    group_df.to_csv(tmp, index=False)
                    temp_file = tmp.name
                group_label = vname or 'default'
                logger.info(f"   Executando pipeline para {len(group_sheets)} leads [{group_label}]...")
                group_result = pipeline.run(temp_file, with_predictions=True, predictor_override=predictor_ov, encoding_overrides=enc_overrides)
            except ValueError as _enc_err:
                # [Estancar o estrago] O validador pós-encoding ("feature zerada
                # em massa", T1-16 / grupo OHE todo-zerado, DT-19) levanta
                # ValueError com prefixo conhecido. ANTES: propagava, derrubava
                # o ciclo inteiro (HTTP 500), os leads ficavam leadScore IS NULL
                # e o polling re-selecionava os mesmos a cada 5min — loop
                # infinito, nunca iam pro Meta, e o hook de alertas nem rodava.
                # AGORA: segura só os leads deste grupo (status terminal lá
                # embaixo) e segue com os outros grupos. ValueError de outra
                # origem continua propagando (comportamento inalterado).
                _msg = str(_enc_err)
                if not (_msg.startswith('[T1-16]') or _msg.startswith('[DT-19]')):
                    raise
                import re as _re
                _feats = _re.findall(r'([A-Za-z0-9_]+) \(obs=', _msg) or \
                         _re.findall(r'([A-Za-z0-9_]+)=[0-9.]+ \(', _msg)
                feature_blocked_feature_names.update(_feats)
                if not feature_blocked_run_id:
                    feature_blocked_run_id = getattr(predictor_ov, 'mlflow_run_id', '') or ''
                _grp_ids = [valid_leads[k]['id'] for k in indices]
                feature_blocked_lead_ids.extend(_grp_ids)
                logger.error(
                    f"🛑 [feature_blocked] grupo [{vname or 'default'}] bloqueado "
                    f"pelo validador pós-encoding: {len(_grp_ids)} leads NÃO "
                    f"scoreados, segurados pra não entrar em loop. {_msg}"
                )
                continue
            finally:
                if temp_file and os.path.exists(temp_file):
                    os.remove(temp_file)

            if group_result is None or len(group_result) == 0:
                logger.warning(f"⚠️ Pipeline retornou resultado vazio para grupo [{vname}]")
                continue

            group_thresholds = predictor_ov.metadata.get('decil_thresholds', {}).get('thresholds', {})
            for j, orig_i in enumerate(indices):
                try:
                    score = float(group_result['lead_score'].iloc[j])
                    decil = atribuir_decil_por_threshold(score, group_thresholds) if group_thresholds else "D05"
                    score_by_index[orig_i] = (score, decil)
                except Exception as e:
                    logger.warning(f"⚠️ Erro ao extrair score para índice {orig_i}: {e}")

        if not score_by_index and not feature_blocked_lead_ids:
            # Vazio genuíno (pipeline retornou nada e não foi bloqueio de
            # feature) → 500 como antes. Se TUDO foi bloqueado pelo validador,
            # NÃO dá 500: segue o fluxo normal (leads são segurados + alerta
            # fail-loud + hook de alertas roda no caminho de sucesso).
            raise HTTPException(status_code=500, detail="Pipeline retornou resultado vazio para todos os grupos")

        # 7. Atualizar Railway + preparar payload CAPI
        processed = 0
        skipped = 0
        capi_leads = []
        blocked_lead_ids = []  # leads bloqueados (utm_blocklist) — capiStatus='blocked'
        skipped_lead_ids = []  # leads ignorados (utm_source_allowlist) — capiStatus='skipped'

        for i, lead in enumerate(valid_leads):
            try:
                if i not in score_by_index:
                    skipped += 1
                    continue

                lead_score_value, decil_str = score_by_index[i]
                decil_int = int(decil_str[1:])  # 'D05' → 5

                # Atualizar Railway (pg8000 named parameters com :name).
                # Em dry_run, pula a escrita pra não interferir no estado
                # de produção (smoke test pós-canary).
                if not dry_run:
                    railway_conn.run(
                        'UPDATE "Lead" SET "leadScore" = :score, decil = :decil, '
                        '"updatedAt" = NOW() WHERE id = :lead_id',
                        score=lead_score_value,
                        decil=decil_int,
                        lead_id=lead['id'],
                    )
                processed += 1

                # Preparar evento CAPI com overrides A/B se variante identificada
                nome = (lead.get('nomeCompleto') or '').strip()
                parts = nome.split(' ', 1)
                capi_lead = {
                    '_railway_id':      lead['id'],   # para UPDATE capiSentAt/capiStatus
                    'email':            lead.get('email'),
                    'phone':            lead.get('telefone'),
                    'first_name':       parts[0] if parts else None,
                    'last_name':        parts[1] if len(parts) > 1 else None,
                    'lead_score':       lead_score_value,
                    'decil':            decil_str,
                    'event_id':         str(uuid.uuid4()),
                    'fbp':              lead.get('fbp'),
                    'fbc':              lead.get('fbc'),
                    'user_agent':       lead.get('userAgent'),
                    'client_ip':        lead.get('remoteIp'),
                    'event_source_url': lead.get('pageUrl'),
                    'event_timestamp':  int(time.time()) - 60,
                    'survey_data':      None,
                }
                ab_v = ab_variant_per_lead[i]
                if ab_v:
                    capi_lead['ab_event_name'] = ab_v.capi_event_name
                    capi_lead['ab_event_name_hq'] = ab_v.capi_event_name_high_quality
                    capi_lead['ab_conversion_rates'] = ab_v.conversion_rates
                    capi_lead['ab_pixel_id'] = ab_v.pixel_id_override
                    capi_lead['ab_high_quality_decils'] = ab_v.capi_high_quality_decils
                    capi_lead['ab_secondary_hq_events'] = ab_v.capi_secondary_hq_events

                # UTM filter: blocklist por campaign + allowlist por source (DT-CAPI-01/02)
                _allowed, _reason = should_send_to_destination(lead, pipeline._client_config.capi, destination='meta')
                if not _allowed:
                    logger.info(f"   ⏭️ CAPI {_reason}: source={lead.get('source')} campaign={lead.get('campaign')}")
                    if _reason == 'blocked_by_blocklist':
                        blocked_lead_ids.append(lead['id'])
                    else:
                        skipped_lead_ids.append(lead['id'])
                else:
                    capi_leads.append(capi_lead)

                logger.info(
                    f"   ✅ {lead.get('email')}: score={lead_score_value:.4f} ({decil_str})"
                )

            except Exception as e:
                logger.error(f"⚠️ Erro ao processar lead {lead.get('email')}: {e}")
                skipped += 1

        # 8. Enviar eventos CAPI (db=None — Railway não usa Cloud SQL).
        # Em dry_run, pula o envio pra não duplicar evento no Meta (smoke test).
        capi_result: Dict = {"success": 0, "total": 0, "errors": 0}
        if capi_leads and not dry_run:
            logger.info(f"📤 Enviando {len(capi_leads)} eventos CAPI (Railway)...")
            capi_result = send_batch_events(capi_leads, db=None, capi_config=pipeline._client_config.capi,
                                            business_config=pipeline._client_config.business,
                                            client_id=pipeline._client_config.client_id)
            logger.info(
                f"✅ CAPI Railway: {capi_result.get('success', 0)}/"
                f"{capi_result.get('total', 0)} enviados"
            )
        elif capi_leads and dry_run:
            logger.info(f"🧪 dry_run=true — {len(capi_leads)} eventos CAPI montados mas NÃO enviados")
            capi_result = {"success": 0, "total": len(capi_leads), "errors": 0, "dry_run": True}

        # 9. Atualizar capiSentAt + capiStatus no Railway.
        # Em dry_run pula — `details` está vazio porque CAPI foi pulado acima.
        details = capi_result.get('details', []) if not dry_run else []
        for i, detail in enumerate(details):
            if i >= len(capi_leads):
                break
            capi_status = 'success' if detail.get('status') == 'success' else 'error'
            try:
                railway_conn.run(
                    'UPDATE "Lead" SET "capiSentAt" = NOW(), "capiStatus" = :status, '
                    '"updatedAt" = NOW() WHERE id = :lead_id',
                    status=capi_status,
                    lead_id=capi_leads[i]['_railway_id'],
                )
            except Exception as e:
                logger.warning(f"⚠️ Erro ao atualizar capiSentAt para {capi_leads[i].get('email')}: {e}")

        # 9b. Marcar leads bloqueados (utm_blocklist) e ignorados (utm_source_allowlist).
        # Em dry_run pula — não muda o estado de capiStatus em produção.
        if not dry_run:
            for lead_id, status in [(lid, 'blocked') for lid in blocked_lead_ids] + \
                                   [(lid, 'skipped') for lid in skipped_lead_ids]:
                try:
                    railway_conn.run(
                        'UPDATE "Lead" SET "capiSentAt" = NOW(), "capiStatus" = :status, '
                        '"updatedAt" = NOW() WHERE id = :lead_id',
                        status=status,
                        lead_id=lead_id,
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Erro ao marcar lead {status} {lead_id}: {e}")

        # 9c. [Estancar o estrago] Leads cujo grupo o validador pós-encoding
        # bloqueou: status terminal 'blocked_feature' (a busca de pendentes não
        # os re-seleciona → mata o loop infinito) + alerta fail-loud dedicado.
        # Decisão de produto registrada no desenho: "segurar o lead" — leadScore
        # continua nulo, não scoreamos degradado. Em dry_run (smoke test) não
        # muta estado nem dispara alerta.
        if feature_blocked_lead_ids and not dry_run:
            for _bid in feature_blocked_lead_ids:
                try:
                    railway_conn.run(
                        'UPDATE "Lead" SET "capiStatus" = :status, '
                        '"updatedAt" = NOW() WHERE id = :lead_id',
                        status='blocked_feature',
                        lead_id=_bid,
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Erro ao marcar lead blocked_feature {_bid}: {e}")
            try:
                from src.monitoring.critical_alerts import alert_feature_encoding_blocked
                _disp = alert_feature_encoding_blocked(
                    feature_names=sorted(feature_blocked_feature_names),
                    n_leads=len(feature_blocked_lead_ids),
                    model_run_id=feature_blocked_run_id,
                )
                logger.info(f"🚨 feature_encoding_blocked alerta: dispatch={_disp}")
            except Exception as _ae:
                logger.warning(f"⚠️ alerta feature_encoding_blocked falhou (não bloqueia polling): {_ae}")
        elif feature_blocked_lead_ids and dry_run:
            logger.info(
                f"🧪 dry_run=true — {len(feature_blocked_lead_ids)} leads seriam "
                f"marcados blocked_feature e o alerta NÃO seria disparado"
            )

        if dry_run:
            logger.info(
                f"🧪 Railway polling DRY-RUN concluído: {processed} scoreados (não escritos), "
                f"{skipped} erros, {len(capi_leads)} CAPI montados (não enviados), "
                f"{len(blocked_lead_ids)} seriam bloqueados, {len(skipped_lead_ids)} seriam ignorados, "
                f"{len(feature_blocked_lead_ids)} seriam segurados por feature quebrada"
            )
        else:
            logger.info(
                f"✅ Railway polling concluído: {processed} processados, "
                f"{skipped} erros, {capi_result.get('success', 0)} CAPI enviados, "
                f"{len(blocked_lead_ids)} bloqueados, {len(skipped_lead_ids)} ignorados por source, "
                f"{len(feature_blocked_lead_ids)} segurados por feature quebrada"
            )
            # Critical alerts — caminho de sucesso normal (com batch processado).
            # Mesma chamada do early-return ("nenhum lead pendente") via helper.
            # Pulado em dry_run pra não disparar alertas a partir de smoke test.
            # Roda mesmo quando todos os grupos foram segurados por feature
            # quebrada (não damos mais 500 nesse caso → o hook deixa de ser
            # pulado, que era parte do dano silencioso).
            _run_critical_alerts_safely(railway_conn)

        # I4: ramo isolado lead_surveys (roda também no caminho com batch Lead;
        # no-op se SURVEY_CAPI_ENABLED!=true; nunca propaga).
        _run_survey_branch_safely(railway_conn)

        return {
            "processed":     processed,
            "skipped":       skipped,
            "capi_sent":     capi_result.get('success', 0),
            "capi_errors":   capi_result.get('errors', 0),
            "capi_blocked":  len(blocked_lead_ids),
            "capi_skipped":  len(skipped_lead_ids),
            "feature_blocked": len(feature_blocked_lead_ids),
            "dry_run":       dry_run,
            "timestamp":     datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erro no polling Railway: {str(e)}")
        # Registra falha pro tracker da regra 9 antes de propagar — best-effort.
        try:
            from src.monitoring.critical_alerts import GcsStateStore, record_polling_status
            _s = GcsStateStore()
            record_polling_status(_s, status='error')
            _s.flush()
        except Exception as _re:
            logger.warning(f"⚠️ critical_alerts: falha registrando 'error' no tracker: {_re}")
        raise HTTPException(status_code=500, detail=f"Erro no polling Railway: {str(e)}")
    finally:
        if railway_conn:
            try:
                railway_conn.close()
            except Exception:
                pass


@router.post("/pubsub/process-pending")
async def pubsub_process_pending(pipeline: PipelineDep, dry_run: bool = False):
    """Consumer Pub/Sub do sistema novo (lead-capture-ingest-sub) → CAPI scoreado.

    Chamado pelo Cloud Scheduler em cadência fixa.

    Fluxo (delega tudo a api.pubsub_branch.drain_pending_pubsub):
      0. Repete os passos abaixo até a fila esvaziar (tetos de tempo e de rodadas
         no pubsub_branch). Antes era UM pull por invocação e o resto esperava o
         tick seguinte de 5 min, o que fazia mensagem envelhecer em degrau e
         disparar o alerta de backlog com a fila drenando normalmente.
      1. Pull batch da sub Pub/Sub.
      2. Por mensagem: parse → traduz slugs → classifica → scoreia (pipeline.run)
                       → CAPI (send_batch_events) → ledger registros_ml → ack.

    Off por padrão via env `PUBSUB_CAPI_ENABLED`. Deploy ≠ ligar: enquanto o
    env não estiver `true`, o endpoint volta no-op (sem pull, sem ack).
    Arquitetura nova — substitui o ramo I3/I4 (api/survey_branch.py e
    api/survey_enrichment.py, marcados DEPRECATED 2026-05-23).

    Args:
        dry_run: Se True, processa e loga (pull → score → monta CAPI) mas NÃO
                 envia Meta, NÃO grava ledger e NÃO acka mensagens. Permite
                 smoke contra o backlog real do canary sem efeito colateral.
    """
    import pg8000.native
    from api.pubsub_branch import drain_pending_pubsub, is_enabled, ledger_target

    if not is_enabled():
        return {
            "enabled": False,
            "message": "PUBSUB_CAPI_ENABLED=false; no-op",
            "timestamp": datetime.now().isoformat(),
        }

    # Import lazy: só puxa o SDK do Pub/Sub quando o env tá ligado.
    from google.cloud import pubsub_v1

    railway_conn = None
    ledger_conn = None
    subscriber = None
    try:
        railway_conn = pg8000.native.Connection(
            host=os.environ['RAILWAY_DB_HOST'],
            port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
            database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
            user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
            password=os.environ['RAILWAY_DB_PASSWORD'],
            timeout=30,
        )
        if ledger_target() in ('dual', 'cloudsql'):
            # Cloud SQL nosso (PLANO_LEDGER_CLOUDSQL.md Etapa 1). Falha aqui
            # derruba a request (500) — Scheduler tenta de novo em 5min e as
            # mensagens ficam na fila; melhor do que processar sem o primário.
            import ssl as _ssl
            _lctx = _ssl.create_default_context()
            _lctx.check_hostname = False
            _lctx.verify_mode = _ssl.CERT_NONE
            ledger_conn = pg8000.native.Connection(
                host=os.environ['LEDGER_DB_HOST'],
                port=int(os.environ.get('LEDGER_DB_PORT', '5432')),
                database=os.environ.get('LEDGER_DB_NAME', 'ledger'),
                user=os.environ.get('LEDGER_DB_USER', 'ledger_app'),
                password=os.environ['LEDGER_DB_PASSWORD'],
                ssl_context=_lctx,
                timeout=30,
            )
        subscriber = pubsub_v1.SubscriberClient()
        # DRENA até a fila esvaziar (antes era um pull só por invocação, e o resto
        # esperava o próximo tick de 5 min — era isso que obrigava a drenar na mão).
        # Os tetos de tempo/rodadas vivem no `pubsub_branch`; ver drain_pending_pubsub.
        summary = drain_pending_pubsub(
            subscriber, railway_conn, pipeline, dry_run=dry_run,
            ledger_conn=ledger_conn,
        )
        return {**summary, "timestamp": datetime.now().isoformat()}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erro no Pub/Sub processing: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro no Pub/Sub processing: {e}",
        )
    finally:
        if subscriber is not None:
            try:
                subscriber.close()
            except Exception:
                pass
        for _c in (railway_conn, ledger_conn):
            if _c is not None:
                try:
                    _c.close()
                except Exception:
                    pass
