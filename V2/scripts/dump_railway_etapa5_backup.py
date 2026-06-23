#!/usr/bin/env python3
"""
dump_railway_etapa5_backup.py — backup de segurança ANTES dos passos destrutivos
da Etapa 5 (PLANO_LEDGER_CLOUDSQL.md). Snapshot das tabelas do Railway do cliente
que a Etapa 5 vai anular/dropar, pro nosso GCS.

Tabelas:
  - Lead          (inteira) — o `UPDATE ... SET leadScore=NULL, decil=NULL` apaga
  - leads_capi    (só linhas com score do modelo — as 21 que o UPDATE anula)
  - registros_ml  (inteira) — o `DROP TABLE` apaga (já espelhada no Cloud SQL)

Saída: parquets locais + upload pra gs://<bucket>/ledger_etapa5_backup/<data>/
+ manifest.json (contagens, timestamp). NÃO toca em nada no Railway (só SELECT).

    python scripts/dump_railway_etapa5_backup.py --date 2026-06-23
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUCKET = "smart-ads-validation-reports"
GCS_PREFIX = "ledger_etapa5_backup"

DUMPS = [
    ("Lead",         'SELECT * FROM "Lead"',                                   "lead.parquet"),
    ("leads_capi",   'SELECT * FROM leads_capi WHERE lead_score IS NOT NULL',  "leads_capi_scored.parquet"),
    ("registros_ml", 'SELECT * FROM registros_ml',                             "registros_ml.parquet"),
]


def _load_dotenv() -> None:
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))


def _railway():
    import pg8000.native
    return pg8000.native.Connection(
        host=os.environ["RAILWAY_DB_HOST"], port=int(os.environ["RAILWAY_DB_PORT"]),
        database=os.environ["RAILWAY_DB_NAME"], user=os.environ["RAILWAY_DB_USER"],
        password=os.environ["RAILWAY_DB_PASSWORD"], timeout=180,
    )


def _to_df(conn, sql) -> pd.DataFrame:
    rows = conn.run(sql)
    cols = [c["name"] for c in conn.columns]
    df = pd.DataFrame(rows, columns=cols)
    # jsonb/dict/list → string pro parquet
    for c in df.columns:
        if df[c].map(lambda v: isinstance(v, (dict, list))).any():
            df[c] = df[c].map(lambda v: json.dumps(v, ensure_ascii=False, default=str)
                              if isinstance(v, (dict, list)) else v)
    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="pasta no GCS, ex: 2026-06-23")
    ap.add_argument("--no-upload", action="store_true", help="só gera parquets locais")
    args = ap.parse_args()
    _load_dotenv()

    out_dir = Path(tempfile.mkdtemp(prefix="etapa5_backup_"))
    manifest = {"date": args.date, "source": "railway", "tables": {}}
    rw = _railway()
    try:
        for tabela, sql, fname in DUMPS:
            df = _to_df(rw, sql)
            path = out_dir / fname
            df.to_parquet(path, index=False)
            manifest["tables"][tabela] = {"rows": len(df), "cols": len(df.columns), "file": fname}
            print(f"  {tabela}: {len(df)} linhas → {fname} ({path.stat().st_size//1024} KB)")
    finally:
        rw.close()

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"\nparquets locais em: {out_dir}")

    if args.no_upload:
        return 0

    dest = f"gs://{BUCKET}/{GCS_PREFIX}/{args.date}/"
    print(f"\nsubindo pra {dest} ...")
    r = subprocess.run(
        ["gcloud", "storage", "cp", str(out_dir / "*"), dest,
         "--project", "smart-ads-451319"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        # fallback: cp arquivo por arquivo (glob pode não expandir)
        ok = True
        for f in sorted(out_dir.iterdir()):
            rr = subprocess.run(["gcloud", "storage", "cp", str(f), dest,
                                 "--project", "smart-ads-451319"],
                                capture_output=True, text=True)
            if rr.returncode != 0:
                ok = False
                print(f"  ERRO subindo {f.name}: {rr.stderr.strip()[:200]}")
        if not ok:
            return 1
    print("✅ backup no GCS:")
    subprocess.run(["gcloud", "storage", "ls", "-l", dest, "--project", "smart-ads-451319"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
