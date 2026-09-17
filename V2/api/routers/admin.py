"""Rotas administrativas: migrações, limpeza de duplicados e de tags de canário, refresh de CPL.

Gerado a partir do app.py monolítico (corte por domínio, corpo dos handlers intacto)."""
import os
from fastapi import FastAPI, HTTPException, UploadFile, File
from typing import Annotated, List, Dict, Any, Optional
from api.database import get_db, init_database, create_lead_capi, count_leads, count_leads_with_fbp, count_leads_with_fbc, get_leads_by_emails, LeadCAPI
from fastapi import Depends, Header, Request
from api.auth import exigir_token, exigir_token_interno
from sqlalchemy.orm import Session
from fastapi import APIRouter
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/admin/migrate_capi_sent_at", dependencies=[Depends(exigir_token_interno())])
async def migrate_capi_sent_at(db: Session = Depends(get_db)):
    """Endpoint temporário para executar migração da coluna capi_sent_at"""
    try:
        from sqlalchemy import text

        logger.info("📝 Adicionando coluna capi_sent_at...")
        db.execute(text("""
            ALTER TABLE leads_capi
            ADD COLUMN IF NOT EXISTS capi_sent_at TIMESTAMP NULL
        """))
        db.commit()
        logger.info("✅ Coluna adicionada!")

        logger.info("📝 Criando índice idx_capi_sent_at...")
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_capi_sent_at
            ON leads_capi(capi_sent_at)
        """))
        db.commit()
        logger.info("✅ Índice criado!")

        logger.info("🔍 Verificando estrutura...")
        result = db.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'leads_capi' AND column_name = 'capi_sent_at'
        """))

        row = result.fetchone()
        if row:
            return {
                "status": "success",
                "message": "Migração executada com sucesso",
                "column": {
                    "name": row[0],
                    "type": row[1],
                    "nullable": row[2]
                }
            }
        else:
            return {
                "status": "error",
                "message": "Coluna não encontrada após migração"
            }

    except Exception as e:
        logger.error(f"❌ Erro na migração: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro na migração: {str(e)}")


@router.post("/admin/cleanup_duplicates", dependencies=[Depends(exigir_token_interno())])
async def cleanup_duplicates(ids_to_delete: List[int], db: Session = Depends(get_db)):
    """
    Deleta registros duplicados da página Parabéns

    SEGURANÇA:
    - Requer lista explícita de IDs
    - Executa em transação (rollback automático em caso de erro)
    - Retorna estatísticas da deleção
    """
    try:
        from sqlalchemy import text

        if not ids_to_delete:
            raise HTTPException(status_code=400, detail="Lista de IDs vazia")

        if len(ids_to_delete) > 5000:
            raise HTTPException(status_code=400, detail="Limite de 5000 IDs por execução")

        logger.info(f"🗑️ Iniciando deleção de {len(ids_to_delete)} registros duplicados...")

        # Executar deleção em batches de 100
        batch_size = 100
        total_deleted = 0

        for i in range(0, len(ids_to_delete), batch_size):
            batch = ids_to_delete[i:i+batch_size]
            ids_str = ','.join(map(str, batch))

            result = db.execute(text(f"DELETE FROM leads_capi WHERE id IN ({ids_str})"))
            deleted = result.rowcount
            total_deleted += deleted
            logger.info(f"✅ Batch {i//batch_size + 1}: {deleted} registros deletados")

        db.commit()
        logger.info(f"✅ SUCESSO! Total deletado: {total_deleted} registros")

        return {
            "status": "success",
            "total_deleted": total_deleted,
            "expected": len(ids_to_delete),
            "message": f"Deletados {total_deleted} registros duplicados"
        }

    except Exception as e:
        logger.error(f"❌ Erro na deleção: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro na deleção: {str(e)}")


@router.post("/admin/cleanup-canary-tags", dependencies=[Depends(exigir_token_interno())])
async def cleanup_canary_tags(dry_run: bool = False):
    """Remove tags canary-* de revisões sem tráfego (percent==0).

    Cada tag canary mantém a revisão "ready to serve", o que respeita
    min-instances e gera custo always-on mesmo com 0% de tráfego. O
    deploy_capi.sh já limpa no início de cada deploy, mas se ficam dias
    sem deploy as tags órfãs sangram ~R$ 4-5/dia cada. Este endpoint é
    disparado por Cloud Scheduler diário (canary-tag-cleanup-daily) pra
    cobrir esse gap — independente de deploy.

    Proteções: só remove entry que tem tag começando com 'canary-' E
    percent ausente/0. Nunca toca tag 'prod', tag não-canary, nem
    revisão com tráfego > 0.

    Args:
        dry_run: se True, retorna o que removeria sem aplicar.
    """
    import os as _os
    import requests as _requests
    from google.auth import default as gauth_default
    from google.auth.transport.requests import Request as _GAuthRequest

    PROJECT = _os.getenv("GCP_PROJECT", "smart-ads-451319")
    REGION = _os.getenv("CLOUD_RUN_REGION", "us-central1")
    SERVICE = _os.getenv("SERVICE_NAME", "smart-ads-api")

    try:
        # REST direto na Cloud Run Admin API v1 (Knative). Evita googleapiclient
        # — que arrasta httplib2/pyparsing e quebra por conflito de versão na
        # imagem. 'requests' já está instalado (HEALTHCHECK do Dockerfile usa).
        creds, _ = gauth_default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(_GAuthRequest())
        headers = {"Authorization": f"Bearer {creds.token}"}
        base = (
            f"https://{REGION}-run.googleapis.com/apis/serving.knative.dev/v1"
            f"/namespaces/{PROJECT}/services/{SERVICE}"
        )

        g = _requests.get(base, headers=headers, timeout=30)
        g.raise_for_status()
        svc = g.json()

        traffic = svc.get("spec", {}).get("traffic", [])
        keep, removed = [], []
        for t in traffic:
            tag = t.get("tag", "")
            pct = t.get("percent", 0) or 0
            if tag.startswith("canary-") and pct == 0:
                removed.append({"tag": tag, "revision": t.get("revisionName", "?")})
            else:
                keep.append(t)

        if dry_run:
            return {
                "status": "dry_run",
                "would_remove": removed,
                "would_remove_count": len(removed),
                "kept_count": len(keep),
            }

        if not removed:
            logger.info("[canary-cleanup] nenhuma tag órfã encontrada")
            return {"status": "noop", "removed": [], "removed_count": 0}

        svc["spec"]["traffic"] = keep
        p = _requests.put(
            base,
            headers={**headers, "Content-Type": "application/json"},
            json=svc, timeout=30,
        )
        p.raise_for_status()
        logger.info(
            f"[canary-cleanup] {len(removed)} tag(s) canary órfã(s) removida(s): "
            f"{[r['tag'] for r in removed]}"
        )
        return {"status": "success", "removed": removed, "removed_count": len(removed)}

    except Exception as e:
        logger.error(f"[canary-cleanup] erro: {e}")
        raise HTTPException(status_code=500, detail=f"Erro no cleanup de tags canary: {str(e)}")


@router.post("/admin/refresh-cpl")
async def refresh_cpl(
    client_id: str = "devclub",
    window_days: int = 30,
    dry_run: bool = False,
):
    """Refresh do lookup de custo por adset (Bloco B/4 do EVENTOS_E_DECIS_PLANO).

    Puxa Meta Insights API da janela móvel dos últimos `window_days` dias
    (default 30, excluindo dia corrente) e UPSERTa nas tabelas Railway
    `cpl_adset` e `ad_to_adset_map`. Idempotente — rodar 2× no mesmo dia
    produz o mesmo estado final.

    Disparado por Cloud Scheduler 1×/dia às 04:00 BRT (job
    `cpl-refresh-daily` configurado em GCP). Custo praticamente zero —
    reusa o container já rodando, sem Cloud Run Job dedicado.

    Args:
        client_id: identificador do cliente. Default 'devclub'.
        window_days: tamanho da janela móvel (default 30).
        dry_run: se True, calcula sem escrever no Railway. Útil pra debug.
    """
    import pg8000.native as _pg8000
    from src.data.cost_attribution.refresh import refresh_cpl_for_client
    from src.validation.meta_api_client import MetaAPIClient

    railway_conn = None
    try:
        railway_conn = _pg8000.Connection(
            host=os.environ['RAILWAY_DB_HOST'],
            port=int(os.environ['RAILWAY_DB_PORT']),
            user=os.environ['RAILWAY_DB_USER'],
            password=os.environ['RAILWAY_DB_PASSWORD'],
            database=os.environ['RAILWAY_DB_NAME'],
        )
        meta = MetaAPIClient()
        stats = refresh_cpl_for_client(
            client_id=client_id,
            railway_conn=railway_conn,
            meta_client=meta,
            window_days=window_days,
            dry_run=dry_run,
        )
        return {
            "status": "dry_run" if dry_run else "success",
            "client_id": stats.client_id,
            "window_start": stats.window_start.isoformat(),
            "window_end": stats.window_end.isoformat(),
            "n_adsets_upserted": stats.n_adsets_upserted,
            "n_mappings_upserted": stats.n_mappings_upserted,
            "total_spend": round(stats.total_spend, 2),
            "total_leads": stats.total_leads,
            "cpl_global": round(stats.cpl_global, 4) if stats.cpl_global else None,
            "duration_seconds": round(stats.duration_seconds, 1),
        }
    except Exception as e:
        logger.error(f"[refresh-cpl] erro: {e}")
        raise HTTPException(status_code=500, detail=f"Erro no refresh CPL: {str(e)}")
    finally:
        if railway_conn:
            railway_conn.close()
