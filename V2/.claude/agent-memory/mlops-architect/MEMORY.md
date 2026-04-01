# Bring Data - MLOps Architect Memory

## Project Overview
- Lead scoring system for DevClub (educational product)
- Predicts conversion probability for leads, sends scores to Meta CAPI for ad optimization
- Migrating from Google Sheets + Cloud SQL (GCP) to Railway PostgreSQL

## Architecture (AS-IS)
- **API**: FastAPI on Cloud Run (`/Users/ramonmoreira/Desktop/bring_data/V2/api/app.py`)
- **ML Pipeline**: `src/production_pipeline.py` - LeadScoringPipeline class (11 steps, 0.5-5s)
- **Monitoring**: `src/monitoring/orchestrator.py` - MonitoringOrchestrator (drift, CAPI quality, Slack)
- **Cloud SQL (GCP)**: `leads_capi` table (SQLAlchemy model in `api/database.py`)
- **Railway PostgreSQL**: `Lead` table (Prisma, managed by frontend) - has `pesquisa` JSONB field
- **Apps Script**: `api/apps-script-code.js` - polling 5min + monitoring 2x/day

## Key Architectural Decisions (Feb 2026)
1. **Event-driven via webhook (Option A)** with polling fallback (30min) for orphaned leads
2. **Cloud Scheduler 2x/day** replaces Apps Script for monitoring
3. **Collapse /predict/batch + /capi/process_daily_batch** into internal `process_pending_leads()`
4. **Migration strategy**: parallel run, CAPI on one path only, 24-48h validation window

## Critical Migration Risks
- **Schema mismatch**: Railway `Lead` uses camelCase; pipeline expects Google Sheets column names
- **JSONB extraction**: Railway `pesquisa` field stores survey as JSONB; pipeline expects flat columns
- **Dual-bank dedup**: During migration, same lead can exist in Cloud SQL AND Railway -> CAPI duplicates
- **Column mapping needed**: Railway -> Sheets (different from Cloud SQL -> Sheets at app.py:839-862)

## Key Endpoints
- `POST /predict/batch` - batch scoring (Apps Script, TO BE DEPRECATED)
- `POST /capi/process_daily_batch` - batch CAPI send (Apps Script, TO BE DEPRECATED)
- `POST /monitoring/daily-check` - receives leads, runs quality checks
- `GET /monitoring/daily-check` - auto-fetches from Sheets (needs Railway variant)
- `POST /webhook/lead_capture` - Page 1: saves to Cloud SQL
- `POST /webhook/update_survey` - Page 2: full pipeline (update + ML + CAPI) - ALREADY WORKING

## Database Details
- `api/database.py`: LeadCAPI model, supports DATABASE_URL/CLOUD_SQL/components/SQLite
- Railway `Lead` fields: id, data, hora, nomeCompleto, email, telefone, pesquisa(JSONB), source, campaign, medium, content, term, remoteIp, userAgent, fbc, fbp, pageUrl, leadScore, decil, createdAt, updatedAt

## ML Pipeline Details
- Model trained with Google Sheets column names (Portuguese questions as headers)
- Column mapping PostgreSQL->Sheets at app.py:839-862
- Pipeline expects CSV input, uses temp file + pipeline.run()
- Decil thresholds in model metadata
- CAPI: LeadQualified (all) + LeadQualifiedHighQuality (D9-D10 only)

## Dual Write (Shadow Deploy)
- Page 2 JS (`docs/pagina2_codigo_modificado.js`) sends to BOTH Google Sheets AND PostgreSQL
- `/webhook/update_survey` is ALREADY the target architecture (DB -> ML -> CAPI in one call)
