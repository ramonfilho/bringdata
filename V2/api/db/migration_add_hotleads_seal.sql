-- Migração: analytics.hotleads_seal — selo do HotLeads da base HISTÓRICA
-- Data: 2026-07-31
--
-- Por que uma tabela separada e não colunas no registros_ml: o ledger só tem os
-- ~75k respondentes de pesquisa desde 23/05, enquanto o universo de leads
-- (`analytics.leads`) tem ~339k e vem de bem antes. O enriquecimento em massa é
-- por EMAIL, sem `event_id`, e não tem nada a ver com o ciclo
-- submitted→scored→sent do fluxo ao vivo — misturar os dois na mesma coluna
-- confundiria "selo do lead corrente" com "selo histórico levantado em lote".
--
-- ⚠️ LEITURA TEMPORAL: `hot` aqui é a resposta da Hotmart em `sealed_at`, ou seja
-- "já comprou algo na Hotmart ATÉ ESSA DATA". NÃO é o estado na época em que o
-- lead foi captado. Para medir valor preditivo isso é teto otimista; para virar
-- feature de treino exige o diagnóstico de lift por idade de coorte (ver
-- reference_hotleads_selo_significado).

CREATE TABLE IF NOT EXISTS analytics.hotleads_seal (
    email          TEXT PRIMARY KEY,
    hot            BOOLEAN NOT NULL,
    sealed_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    execution_id   VARCHAR(64)
);

COMMENT ON TABLE  analytics.hotleads_seal            IS 'Selo do HotLeads da base histórica (enriquecimento em lote, por email)';
COMMENT ON COLUMN analytics.hotleads_seal.hot        IS 'true = já comprou ALGUM produto na Hotmart até sealed_at (qualquer produtor)';
COMMENT ON COLUMN analytics.hotleads_seal.sealed_at  IS 'Quando perguntamos — o selo é um retrato desta data, não da captura do lead';

CREATE INDEX IF NOT EXISTS idx_hotleads_seal_hot ON analytics.hotleads_seal (hot) WHERE hot IS TRUE;

SELECT COUNT(*) AS total,
       COUNT(*) FILTER (WHERE hot) AS quentes
FROM analytics.hotleads_seal;
