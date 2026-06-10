-- Armazenamento da feature "entrou no grupo de WhatsApp" (SendFlow Sendhook).
-- Tabela nossa no Railway (modelo registros_ml). Aditiva — não toca tabelas existentes.
-- joined_at SEMPRE em UTC (o receiver converte o BRT do SendFlow). phone_canonical = DDD+8.
CREATE TABLE IF NOT EXISTS whatsapp_group_joins (
  id              BIGSERIAL PRIMARY KEY,
  client_id       TEXT        NOT NULL DEFAULT 'devclub',
  phone_canonical TEXT        NOT NULL,            -- DDD + últimos 8 dígitos (telefone_chave_grupo)
  phone_raw       TEXT,                            -- como veio no payload (E.164)
  group_id        TEXT,
  group_name      TEXT,
  joined_at       TIMESTAMPTZ NOT NULL,            -- hora do evento, em UTC
  received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  source          TEXT        NOT NULL DEFAULT 'sendhook',  -- 'sendhook' | 'backfill'
  raw_payload     JSONB,
  UNIQUE (client_id, phone_canonical, group_id)    -- idempotência
);
CREATE INDEX IF NOT EXISTS idx_wgj_lookup ON whatsapp_group_joins (client_id, phone_canonical);
