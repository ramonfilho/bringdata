-- =====================================================================
-- Schema analítico — consolidação de leads, vendas e resultados
-- =====================================================================
-- Objetivo: parar de puxar arquivos locais + N APIs separadas (Sheets,
-- Railway antigo/novo, ledger, Guru/Hotmart/Asaas/Boletex/TMB, Meta) a
-- cada execução de treino/validação. Os dados passam a viver aqui, no
-- nosso Cloud SQL, e os pipelines LEEM daqui via camada de repositório
-- (src/data/). Os loaders de API de hoje viram o ETL que ALIMENTA estas
-- tabelas — decoplados dos consumidores.
--
-- Database recomendado: `analytics` (instância própria de schema dentro do
-- mesmo Cloud SQL que hospeda `ledger`; espelha o precedente da Etapa 0 do
-- ledger). Mantém a escrita OLTP do consumer Pub/Sub (registros_ml) isolada
-- da leitura analítica pesada do treino.
--
-- PRINCÍPIOS (decididos com /sw-architect + /mlops-architect):
--   1. Uma tabela por CONCEITO (lead / venda / resultado), não por fonte.
--      A fonte vira coluna de proveniência (`source` / `gateway`).
--   2. APPEND-ONLY + TEMPORAL. `ingested_at` em tudo. Nada é sobrescrito.
--      Permite reconstruir "o que sabíamos na data X" (point-in-time) e
--      torna o treino reprodutível. Dedup/prioridade acontece na LEITURA.
--   3. SEM transformação aqui. As tabelas guardam DADO CRU canônico.
--      Normalização de email/telefone e cálculo de feature continuam 100%
--      em src/core/ — senão vira um 4º ponto de divergência de paridade.
--   4. `client_id` em TODAS as tabelas desde o dia 1 (Cliente B chegando).
--
-- POPULAÇÃO POR FASE (as tabelas nascem juntas; enchem em etapas):
--   Fase 1 → validation_runs / validation_metrics
--   Fase 2 → sales            (habilita o enriquecimento de compradores)
--   Fase 3 → leads
--   (meta_insights entra junto da Fase 1, é fonte de gasto/CPL do relatório)
--
-- ONDE: schema `analytics` DENTRO do database `ledger` (mesma conexão do
-- ledger_connection.py). As tabelas vivem qualificadas como analytics.*.
-- O search_path abaixo vale para a execução deste script como um todo.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS analytics;
SET search_path TO analytics, public;


-- ---------------------------------------------------------------------
-- leads — um lead canônico, de qualquer fonte
-- ---------------------------------------------------------------------
-- Mapeia 1:1 o contrato src/data/lead_record.LeadRecord, + proveniência
-- e tempo de ingestão. Email/telefone gravados CRUS (normalização fica em
-- src/core). `survey_responses` é o jsonb das respostas (features do modelo).
CREATE TABLE IF NOT EXISTS leads (
    id              BIGSERIAL PRIMARY KEY,
    client_id       VARCHAR(64)  NOT NULL DEFAULT 'devclub',

    -- Proveniência: de qual fonte física esta linha veio.
    --   'registros_ml' | 'sheets_prod' | 'sheets_backup'
    --   | 'railway_lead' | 'railway_old' | 'cloudsql_backup' | 'vip'
    source          VARCHAR(32)  NOT NULL,

    -- Identidade e tempo
    event_id        VARCHAR(255),
    email           VARCHAR(255),
    phone           VARCHAR(64),
    first_name      VARCHAR(255),
    last_name       VARCHAR(255),
    capturado_em    TIMESTAMPTZ,            -- data de captura do lead (event time)

    -- Scoring (populado quando o lead foi scoreado)
    status_envio    VARCHAR(32),            -- success|error|skipped_allowlist|skipped_missing_data
    decil           SMALLINT,
    score           DOUBLE PRECISION,
    variant         VARCHAR(16),            -- champion|challenger|null

    -- Origem da campanha (UTM)
    utm_source      VARCHAR(255),
    utm_medium      VARCHAR(255),
    utm_campaign    VARCHAR(255),
    utm_content     VARCHAR(255),
    utm_term        VARCHAR(255),
    utm_url         TEXT,

    -- Envio CAPI ao Meta
    capi_enviado_em TIMESTAMPTZ,
    erro            TEXT,

    -- Respostas da pesquisa (features do modelo) — cru, sem parsing
    survey_responses JSONB,

    -- Meta tracking + sessão (qualidade de tráfego, features futuras)
    fbp             VARCHAR(255),
    fbc             VARCHAR(255),
    user_agent      TEXT,
    ip              VARCHAR(64),
    has_computer    VARCHAR(16),            -- TEXT de propósito: payload manda "SIM"/"NAO"

    -- Temporal (point-in-time / reprodutibilidade)
    ingested_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Idempotência do backfill/ingestão: a mesma linha lógica da mesma fonte
-- não duplica. event_id pode ser null em fontes antigas → cai no par email+capturado_em.
CREATE UNIQUE INDEX IF NOT EXISTS uq_leads_source_event
    ON leads (client_id, source, event_id)
    WHERE event_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_leads_source_email_data
    ON leads (client_id, source, email, capturado_em)
    WHERE event_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_leads_email      ON leads (client_id, email);
CREATE INDEX IF NOT EXISTS idx_leads_phone      ON leads (client_id, phone);
CREATE INDEX IF NOT EXISTS idx_leads_capturado  ON leads (client_id, capturado_em);
CREATE INDEX IF NOT EXISTS idx_leads_ingested   ON leads (client_id, ingested_at);

COMMENT ON TABLE  leads IS 'Lead canônico consolidado de todas as fontes. Append-only. Dedup por prioridade de source na leitura.';
COMMENT ON COLUMN leads.source IS 'Fonte física de origem (proveniência). Define prioridade de dedup na leitura.';
COMMENT ON COLUMN leads.survey_responses IS 'Respostas da pesquisa (jsonb) — features do modelo. Cru, normalização fica em src/core.';
COMMENT ON COLUMN leads.ingested_at IS 'Quando a linha entrou na tabela. Base do filtro point-in-time para reprodutibilidade.';


-- ---------------------------------------------------------------------
-- sales — uma venda/aluno, de qualquer gateway
-- ---------------------------------------------------------------------
-- Conceito novo (não existia em src/data). Mapeia o schema normalizado que
-- validation/data_loader já produz. `ingested_at` é CRÍTICO: vendas chegam
-- atrasadas (boleto/Asaas/reembolso) e mudam o label retroativamente —
-- guardar sale_date E ingested_at preserva o estado de conhecimento.
CREATE TABLE IF NOT EXISTS sales (
    id                   BIGSERIAL PRIMARY KEY,
    client_id            VARCHAR(64)  NOT NULL DEFAULT 'devclub',

    -- Gateway de origem (proveniência). Habilita o enriquecimento de
    -- compradores: hoje o treino só lê guru+tmb; aqui entram todos.
    gateway              VARCHAR(16)  NOT NULL,  -- guru|hotmart|asaas|boletex|tmb|hotpay
    external_id          VARCHAR(255),           -- id da transação no gateway (dedup)
    source_file          VARCHAR(255),           -- arquivo de origem (TMB manual), se aplicável

    -- Identidade do comprador (cru — match fica em src/core/matching)
    email                VARCHAR(255),
    phone                VARCHAR(64),
    nome                 VARCHAR(255),

    -- Venda
    sale_value           DOUBLE PRECISION,       -- valor nominal
    sale_value_realizado DOUBLE PRECISION,       -- valor à vista recebido (1ª parcela p/ boleto)
    sale_date            TIMESTAMPTZ,            -- data da venda (event time)
    produto              VARCHAR(255),
    status               VARCHAR(64),            -- Aprovada|Efetivado|... (vocabulário do gateway, cru)

    -- Temporal (point-in-time)
    ingested_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Mesma transação do mesmo gateway não duplica no backfill/refresh.
-- Caso 1: gateway expõe id de transação → dedup por ele.
CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_gateway_external
    ON sales (client_id, gateway, external_id)
    WHERE external_id IS NOT NULL;
-- Caso 2: loaders atuais NÃO expõem id → chave natural (gateway+email+data+valor).
-- Arbiter do ON CONFLICT DO NOTHING do ETL: re-pull não duplica; ingested_at fica
-- no "primeiro visto" (preserva o timing do label).
CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_natural
    ON sales (client_id, gateway, email, sale_date, sale_value)
    WHERE external_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_sales_email     ON sales (client_id, email);
CREATE INDEX IF NOT EXISTS idx_sales_phone     ON sales (client_id, phone);
CREATE INDEX IF NOT EXISTS idx_sales_date      ON sales (client_id, sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_gateway   ON sales (client_id, gateway);
CREATE INDEX IF NOT EXISTS idx_sales_ingested  ON sales (client_id, ingested_at);

COMMENT ON TABLE  sales IS 'Venda/aluno consolidada de todos os gateways. Append-only. Habilita enriquecimento de compradores no treino.';
COMMENT ON COLUMN sales.gateway IS 'Gateway de origem (proveniência). Treino hoje só usa guru+tmb; consolidar aqui traz hotmart/asaas/boletex/hotpay.';
COMMENT ON COLUMN sales.ingested_at IS 'Quando a venda entrou na tabela. Preserva timing do label (vendas chegam atrasadas).';


-- ---------------------------------------------------------------------
-- validation_runs — cabeçalho de uma execução de validação
-- ---------------------------------------------------------------------
-- Substitui os N arquivos .xlsx sobrescritos por dado consultável. Cada
-- execução é UMA linha; os arquivos viram render/export sob demanda.
CREATE TABLE IF NOT EXISTS validation_runs (
    run_id          VARCHAR(64)  PRIMARY KEY,    -- gerado pelo orquestrador
    client_id       VARCHAR(64)  NOT NULL DEFAULT 'devclub',

    lf              VARCHAR(32),                 -- lançamento (LF49, DEV19, ...)
    cap_start       DATE,
    cap_end         DATE,
    sales_start     DATE,
    sales_end       DATE,

    model_run_id    VARCHAR(64),                 -- run_id do modelo MLflow validado
    report_type     VARCHAR(32),                 -- fechamento|pos-devolucoes
    matching_method VARCHAR(32),                 -- default|unified_last6
    tracking_rate   DOUBLE PRECISION,            -- % de alunos encontrados (denominador = vendas)

    params          JSONB,                       -- args completos da execução (auditoria)
    git_sha         VARCHAR(64),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_valruns_lf      ON validation_runs (client_id, lf);
CREATE INDEX IF NOT EXISTS idx_valruns_created ON validation_runs (client_id, created_at);

COMMENT ON TABLE validation_runs IS 'Cabeçalho de cada validação. Append-only — nunca sobrescrito. Arquivos .xlsx viram export sob demanda.';


-- ---------------------------------------------------------------------
-- validation_metrics — métricas de uma execução (formato longo)
-- ---------------------------------------------------------------------
-- Uma linha por grão (decil / campanha / geral). Formato longo pra
-- permitir consulta cruzando lançamentos (evolução por decil ao longo do
-- tempo) sem reabrir N planilhas.
CREATE TABLE IF NOT EXISTS validation_metrics (
    id                       BIGSERIAL PRIMARY KEY,
    run_id                   VARCHAR(64) NOT NULL REFERENCES validation_runs(run_id) ON DELETE CASCADE,

    grain                    VARCHAR(16) NOT NULL,   -- 'decile' | 'campaign' | 'overall'
    decile                   VARCHAR(8),             -- D01..D10 (quando grain='decile')
    campaign                 VARCHAR(512),           -- nome da campanha (quando grain='campaign')
    comparison_group         VARCHAR(32),            -- Champion|Challenger|Controle (quando aplicável)

    leads                    INTEGER,
    conversions              INTEGER,
    conversion_rate          DOUBLE PRECISION,
    expected_conversion_rate DOUBLE PRECISION,
    performance_ratio        DOUBLE PRECISION,
    revenue                  DOUBLE PRECISION,
    spend                    DOUBLE PRECISION,
    cpl                      DOUBLE PRECISION,
    roas                     DOUBLE PRECISION,
    roas_adjusted            DOUBLE PRECISION,

    extra                    JSONB,                  -- métricas adicionais sem virar coluna nova
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_valmetrics_run    ON validation_metrics (run_id);
CREATE INDEX IF NOT EXISTS idx_valmetrics_grain  ON validation_metrics (run_id, grain);

COMMENT ON TABLE validation_metrics IS 'Métricas por grão (decil/campanha/geral) de cada validação. Formato longo p/ consulta cruzando lançamentos.';


-- ---------------------------------------------------------------------
-- meta_insights — gasto/CPL por campanha por dia (Meta Ads API)
-- ---------------------------------------------------------------------
-- A validação puxa a Meta API toda execução. Consolidar aqui o gasto por
-- (campanha, dia) evita o re-pull. Conceito próprio (gasto de anúncio).
CREATE TABLE IF NOT EXISTS meta_insights (
    id            BIGSERIAL PRIMARY KEY,
    client_id     VARCHAR(64) NOT NULL DEFAULT 'devclub',

    account_id    VARCHAR(64),
    campaign_id   VARCHAR(64),
    campaign_name VARCHAR(512),
    insight_date  DATE NOT NULL,

    spend         DOUBLE PRECISION,
    leads         INTEGER,
    cpl           DOUBLE PRECISION,
    impressions   BIGINT,
    clicks        BIGINT,

    extra         JSONB,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_meta_campaign_date
    ON meta_insights (client_id, account_id, campaign_id, insight_date);
CREATE INDEX IF NOT EXISTS idx_meta_date ON meta_insights (client_id, insight_date);

COMMENT ON TABLE meta_insights IS 'Gasto/CPL por campanha por dia (Meta Ads API). Evita re-pull da Meta a cada validação.';
