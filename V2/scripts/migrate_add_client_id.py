"""
Migration: adiciona coluna client_id à tabela leads_capi.

Execução:
    cd /Users/ramonmoreira/Desktop/bring_data_refactor/V2
    # Railway (DevClub):
    export RAILWAY_DB_HOST=... RAILWAY_DB_PASSWORD=...
    python scripts/migrate_add_client_id.py

    # Cloud SQL:
    export DATABASE_URL=postgresql://user:pass@host/db
    python scripts/migrate_add_client_id.py

O script é idempotente — verifica se a coluna já existe antes de tentar criar.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.database import get_database_url
from sqlalchemy import create_engine, text


def run_migration():
    url = get_database_url()
    engine = create_engine(url)

    with engine.connect() as conn:
        # Verificar se coluna já existe
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'leads_capi'
              AND column_name = 'client_id'
        """))
        already_exists = result.fetchone() is not None

        if already_exists:
            print("✅ Coluna client_id já existe em leads_capi — nenhuma ação necessária.")
            return

        print("🔄 Adicionando coluna client_id à tabela leads_capi...")

        # Adicionar coluna com default 'devclub'
        # Em PostgreSQL 11+: operação instantânea (default gravado no catálogo)
        conn.execute(text("""
            ALTER TABLE leads_capi
            ADD COLUMN client_id VARCHAR(50) NOT NULL DEFAULT 'devclub'
        """))

        # Criar índice para performance de queries por cliente
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_leads_capi_client_id
            ON leads_capi (client_id)
        """))

        conn.commit()

        # Verificar contagem
        result = conn.execute(text(
            "SELECT client_id, COUNT(*) FROM leads_capi GROUP BY client_id"
        ))
        rows = result.fetchall()
        print("✅ Migration concluída. Distribuição de client_id:")
        for row in rows:
            print(f"   {row[0]}: {row[1]} registros")


if __name__ == '__main__':
    run_migration()
