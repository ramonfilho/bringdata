-- Migração: colunas do HotLeads (lead scoring da Hotmart) no ledger registros_ml
-- Data: 2026-07-30
-- Objetivo: guardar o selo binário quente/frio por lead e o estado do envio do
--           evento CAPI correspondente (LeadScoringHot).
--
-- Banco: Cloud SQL `ledger` (LEDGER_DB_*), onde registros_ml vive desde 24/06.
-- Aplicar com: psql "$LEDGER_URL" -f api/db/migration_add_hotleads_columns.sql
--
-- Máquina de estados de `hotleads_status` (transições válidas):
--     NULL          -> lead nunca submetido
--     'submitted'   -> enviado ao batch_enrich, aguardando webhook
--     'scored'      -> webhook chegou; hotleads_hot tem o selo (true/false)
--     'sent'        -> hot=true E evento CAPI disparado (hotleads_capi_sent_at)
--     'error'       -> falha registrada em hotleads_error
-- Um lead frio termina em 'scored' de propósito: não gera evento, e é isso que
-- diferencia "sem evento porque é frio" de "sem evento porque falhou".

ALTER TABLE registros_ml
ADD COLUMN IF NOT EXISTS hotleads_status       VARCHAR(20),
ADD COLUMN IF NOT EXISTS hotleads_hot          BOOLEAN,
ADD COLUMN IF NOT EXISTS hotleads_execution_id VARCHAR(64),
ADD COLUMN IF NOT EXISTS hotleads_submitted_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS hotleads_scored_at    TIMESTAMP,
ADD COLUMN IF NOT EXISTS hotleads_capi_sent_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS hotleads_error        TEXT;

COMMENT ON COLUMN registros_ml.hotleads_status       IS 'submitted|scored|sent|error — estágio no fluxo HotLeads';
COMMENT ON COLUMN registros_ml.hotleads_hot          IS 'Selo binário da Hotmart: true=lead quente (score=1), false=frio (score=0)';
COMMENT ON COLUMN registros_ml.hotleads_execution_id IS 'executionId do batch_enrich que submeteu este lead';
COMMENT ON COLUMN registros_ml.hotleads_submitted_at IS 'Quando o lead foi submetido ao batch_enrich';
COMMENT ON COLUMN registros_ml.hotleads_scored_at    IS 'Quando o selo voltou pelo webhook';
COMMENT ON COLUMN registros_ml.hotleads_capi_sent_at IS 'Quando o evento LeadScoringHot foi disparado (só leads quentes)';
COMMENT ON COLUMN registros_ml.hotleads_error        IS 'Mensagem de erro do último passo que falhou';

-- Índice do seletor de elegíveis do job: a query filtra por status (NULL ou
-- 'submitted' velho) dentro de uma janela de created_at. Parcial pra não pesar
-- sobre as linhas já resolvidas ('scored'/'sent'), que são a maioria com o tempo.
CREATE INDEX IF NOT EXISTS idx_registros_ml_hotleads_pending
    ON registros_ml (created_at DESC)
    WHERE hotleads_status IS NULL OR hotleads_status = 'submitted';

-- Verificação
SELECT
    COUNT(*)                                                      AS total,
    COUNT(*) FILTER (WHERE hotleads_status IS NULL)               AS nunca_submetidos,
    COUNT(*) FILTER (WHERE hotleads_status = 'submitted')         AS aguardando_selo,
    COUNT(*) FILTER (WHERE hotleads_status = 'scored')            AS com_selo,
    COUNT(*) FILTER (WHERE hotleads_status = 'sent')              AS evento_enviado
FROM registros_ml;
