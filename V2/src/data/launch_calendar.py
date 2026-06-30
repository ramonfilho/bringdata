"""
launch_calendar.py — Repositório compartilhado do calendário de LFs.

FONTE ÚNICA das datas de lançamento = a planilha do Google (aba FORMS). Este
módulo lê a planilha, parseia as janelas (captação/vendas) e GERA o
`configs/launches.yaml`, que vira projeção/cache — nunca mais editado à mão.
Todos os consumidores continuam lendo por `core.launches.load_launches()`; só a
origem do arquivo muda.

Regras (decididas com o usuário):
  - "Se não está na planilha, não aconteceu" — a planilha manda nas DATAS. Sem
    camada de override de datas.
  - Linha sem data de vendas legível → fallback de segunda-feira + AVISO
    (mesma filosofia de core.launches.resolve_launch_window_brt).
  - Parser falha ALTO em formato que não entende — nunca inventa data.
  - Metadados que a planilha NÃO tem (ex.: `excluded_from_reference` dos
    outliers, usado pelo Top 5) NÃO são datas — são preservados do yaml atual no
    sync (eixo ortogonal, fora do "fonte única pra datas").

IO (gspread) fica aqui em src/data/ (camada de dados), não em core/ (sem IO).

Uso:
  python -m src.data.launch_calendar --dry-run     # reconcilia planilha × yaml
  python -m src.data.launch_calendar --sync        # regenera o launches.yaml
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1gZlXL9-S-LmQceTdJy9MAYfqUrXySVNiY-Z6W5i_B3U/edit"
FORMS_TAB = "FORMS"

# Cabeçalhos na aba FORMS (localizados por nome, robusto a reordenação de coluna).
COL_TAG = "PROJETO (TAG)"
COL_CAP = "DATAS CAPTAÇÃO"
COL_VENDAS = "DATAS VENDAS"

_YAML_PATH = Path(__file__).resolve().parents[2] / "configs" / "launches.yaml"
# Chaves do yaml que NÃO vêm da planilha (eixo de curadoria) — preservadas no sync.
_NON_DATE_KEYS = ("notes", "excluded_from_reference", "excluded_reason", "first_peak_days")
_DATE_KEYS = ("cap_start", "cap_end", "vendas_start", "vendas_end")

# Sanity-guards: bloqueiam datas implausíveis (erro de digitação na planilha) de
# virarem dado torto no yaml — viram aviso "corrigir na planilha".
MAX_CAP_SPAN_DAYS = 45      # captação típica 1-4 semanas (DEV chega a ~29d)
MAX_VENDAS_LAG_DAYS = 90    # vendas abrem semanas após captação, não meses
MAX_VENDAS_SPAN_DAYS = 31   # carrinho não passa de ~1 mês


# ───────────────────────── parser de datas (puro, fail-loud) ────────────────
def _parse_dm(token: str) -> tuple[Optional[int], Optional[int]]:
    """'30/05' -> (30,5); '28' -> (28,None); lixo -> (None,None)."""
    token = token.strip()
    m = re.fullmatch(r"(\d{1,2})\s*/\s*(\d{1,2})", token)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.fullmatch(r"(\d{1,2})", token)
    if m:
        return int(m.group(1)), None
    return None, None


_SEP = re.compile(r"\s*(?:-|–|—|\ba\b|\bà\b|\bate\b|\baté\b)\s*", re.IGNORECASE)


def parse_range(raw) -> Optional[tuple[tuple[int, int], tuple[int, int]]]:
    """Parseia 'DD/MM - DD/MM' / 'DD a DD/MM' → ((d_ini,m_ini),(d_fim,m_fim)),
    SEM ano. Retorna None quando não dá pra resolver mês das duas pontas
    (ex.: '22 a 28', vazio, 'nan') — o chamador aplica fallback.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return None

    parts = [p for p in _SEP.split(s) if p.strip()]
    if len(parts) < 2:
        return None  # ponto único ou formato não-range → fallback
    start_str, end_str = parts[0], parts[-1]  # ignora tokens do meio (listas)

    d0, m0 = _parse_dm(start_str)
    d1, m1 = _parse_dm(end_str)
    if d0 is None or d1 is None:
        return None

    # resolver meses: ponta sem mês herda da outra
    if m1 is None and m0 is None:
        return None  # nenhuma ponta tem mês → impossível resolver
    if m1 is None:
        m1 = m0
    if m0 is None:
        m0 = m1
        if d0 > d1:  # início num mês anterior (ex.: '29 a 04/05')
            m0 = 12 if m1 == 1 else m1 - 1
    return (d0, m0), (d1, m1)


# ───────────────────────── inferência de ano (ordem cronológica) ────────────
def _assign_years(caps: list[Optional[tuple]], today: date) -> list[Optional[int]]:
    """Atribui ano a cada cap_start. A aba é cronológica (topo→base = mais
    antigo→recente). Caminha detectando virada de ano (mês anda pra trás) e
    ancora pelo último LF datado ≈ hoje."""
    rel, prev_key, rels = 0, None, []
    for cap in caps:
        if cap is None:
            rels.append(None)
            continue
        (ds, ms), _ = cap
        key = (ms, ds)
        if prev_key is not None and key < prev_key:
            rel += 1
        prev_key = key
        rels.append(rel)

    parseables = [(i, rels[i]) for i in range(len(rels)) if rels[i] is not None]
    if not parseables:
        return [None] * len(rels)

    last_i, last_rel = parseables[-1]
    (ds, ms), _ = caps[last_i]
    limit = today + timedelta(days=14)  # tolera LF atual em captação
    base = limit.year + 1 - last_rel
    while date(base + last_rel, ms, ds) > limit:
        base -= 1
    return [None if r is None else base + r for r in rels]


# ───────────────────────── leitura da planilha (gspread + CSV) ──────────────
def fetch_forms_rows(sheet_url: str = DEFAULT_SHEET_URL) -> list[dict]:
    """Lê a aba FORMS e devolve [{tag, cap_raw, vendas_raw}, ...] em ordem.

    Reusa o padrão do projeto: gspread (ADC/service account) só pra achar a aba,
    download via CSV-export (curl) pra contornar o hang do gspread.get_all_values.
    """
    import subprocess
    import tempfile

    import gspread
    import pandas as pd
    from google.auth import default as gauth_default

    sheet_id = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_url).group(1)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds, _ = gauth_default(scopes=scopes)
    gc = gspread.authorize(creds)
    ss = gc.open_by_url(sheet_url)
    ws = next((w for w in ss.worksheets() if w.title == FORMS_TAB), None)
    if ws is None:
        raise RuntimeError(f"Aba {FORMS_TAB!r} não encontrada em {sheet_url}")

    export = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={ws.id}"
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".csv", delete=False) as tmp:
        r = subprocess.run(["curl", "-sL", "--max-time", "30", export, "-o", tmp.name], timeout=35)
        if r.returncode != 0:
            raise RuntimeError(f"curl falhou (exit {r.returncode}) baixando aba {FORMS_TAB}")
        df = pd.read_csv(tmp.name, low_memory=False, header=None, dtype=str)
    Path(tmp.name).unlink(missing_ok=True)

    header = [str(c).strip() for c in df.iloc[0].tolist()]

    def col(name):
        if name not in header:
            raise RuntimeError(f"Coluna {name!r} não achada na aba FORMS (cabeçalhos: {header})")
        return header.index(name)

    ci_tag, ci_cap, ci_vendas = col(COL_TAG), col(COL_CAP), col(COL_VENDAS)
    rows = []
    for i in range(1, len(df)):
        tag_raw = str(df.iat[i, ci_tag]).strip()
        if not tag_raw or tag_raw.lower() == "nan":
            continue
        rows.append({
            "tag": tag_raw,
            "cap_raw": df.iat[i, ci_cap],
            "vendas_raw": df.iat[i, ci_vendas],
        })
    return rows


# ───────────────────────── construção do calendário ─────────────────────────
def _norm_tag(tag: str) -> Optional[str]:
    """'[LF56]'/'LF56' -> 'LF56'; só aceita tags de lançamento (LFnn / DEVnn)."""
    t = tag.strip().strip("[]").upper().replace(" ", "")
    if re.fullmatch(r"(LF|DEV)\d+", t):
        return t
    return None


def _monday_fallback(cap_end: Optional[date]) -> Optional[tuple[date, date]]:
    """Vendas sem data legível → janela de segunda-feira após cap_end + 1 semana
    (heurística de exibição; marcada inferida + AVISO no chamador)."""
    if cap_end is None:
        return None
    # primeira segunda >= cap_end + 5 dias (padrão: carrinho ~1 semana após captação)
    d = cap_end + timedelta(days=5)
    d += timedelta(days=(7 - d.weekday()) % 7)  # avança até segunda
    return d, d + timedelta(days=6)


def build_calendar(rows: list[dict], today: date) -> tuple[dict, list[str]]:
    """rows (de fetch_forms_rows) → ({LF: {cap_*, vendas_*}}, avisos)."""
    warnings: list[str] = []
    caps = [parse_range(r["cap_raw"]) for r in rows]
    cap_years = _assign_years(caps, today)

    calendar: dict[str, dict] = {}
    for r, cap, cy in zip(rows, caps, cap_years):
        tag = _norm_tag(r["tag"])
        if tag is None:
            continue
        if cap is None or cy is None:
            warnings.append(f"{r['tag']}: DATAS CAPTAÇÃO ilegível ({r['cap_raw']!r}) — LF ignorado")
            continue
        try:
            (ds, ms), (de, me) = cap
            ce_year = cy + 1 if me < ms else cy  # captação cruza virada de ano
            cap_start, cap_end = date(cy, ms, ds), date(ce_year, me, de)
        except ValueError as e:
            warnings.append(f"{tag}: captação inválida ({r['cap_raw']!r}: {e}) — LF ignorado · corrigir na planilha")
            continue
        cap_span = (cap_end - cap_start).days
        if not 0 <= cap_span <= MAX_CAP_SPAN_DAYS:
            warnings.append(f"{tag}: captação implausível ({cap_start}..{cap_end}, {cap_span}d) "
                            f"— LF ignorado · corrigir na planilha")
            continue

        entry = {"cap_start": cap_start.isoformat(), "cap_end": cap_end.isoformat()}

        # vendas: parseia, e SÓ aceita se cai plausivelmente após a captação
        vs = ve = None
        vr = parse_range(r["vendas_raw"])
        if vr is not None:
            try:
                (vds, vms), (vde, vme) = vr
                vy = cap_end.year + (1 if vms < cap_end.month else 0)  # vendas após captação
                ve_year = vy + 1 if vme < vms else vy
                vs, ve = date(vy, vms, vds), date(ve_year, vme, vde)
            except ValueError:
                vs = ve = None
        lag = (vs - cap_end).days if vs else None
        span = (ve - vs).days if (vs and ve) else None
        plausible = (vs and ve and 0 <= lag <= MAX_VENDAS_LAG_DAYS and 0 <= span <= MAX_VENDAS_SPAN_DAYS)
        if plausible:
            entry["vendas_start"], entry["vendas_end"] = vs.isoformat(), ve.isoformat()
        else:
            fb = _monday_fallback(cap_end)
            if fb:
                entry["vendas_start"], entry["vendas_end"] = fb[0].isoformat(), fb[1].isoformat()
                entry["vendas_inferred"] = True
            detalhe = (f"{r['vendas_raw']!r} implausível (lag={lag}d, span={span}d)"
                       if vr is not None else f"ausente ({r['vendas_raw']!r})")
            fb_txt = f"fallback segunda {fb[0].isoformat()}..{fb[1].isoformat()} (inferido)" if fb else "sem fallback"
            warnings.append(f"{tag}: DATAS VENDAS {detalhe} — {fb_txt} · corrigir na planilha")
        calendar[tag] = entry
    return calendar, warnings


# ───────────────────────── reconcile / sync ─────────────────────────────────
def _load_current_yaml() -> dict:
    import yaml
    if not _YAML_PATH.exists():
        return {}
    with open(_YAML_PATH) as f:
        return yaml.safe_load(f) or {}


def reconcile(calendar: dict, current: dict) -> list[str]:
    """Diff legível planilha (calendar) × yaml atual (current), só nas datas."""
    diffs = []
    for lf in sorted(set(calendar) | set(current), key=lambda x: (x[:2], int(re.sub(r"\D", "", x) or 0))):
        new, old = calendar.get(lf, {}), current.get(lf, {})
        if not old:
            diffs.append(f"  + {lf}: novo na planilha → {new.get('cap_start')}..{new.get('cap_end')}")
            continue
        if not new:
            diffs.append(f"  - {lf}: no yaml mas não na planilha (mantido)")
            continue
        for k in _DATE_KEYS:
            if str(old.get(k)) != str(new.get(k)):
                diffs.append(f"  ~ {lf}.{k}: yaml={old.get(k)} → planilha={new.get(k)}")
    return diffs


def merge_for_write(calendar: dict, current: dict) -> dict:
    """Datas da planilha + metadados de curadoria preservados do yaml atual.

    Datas vêm 100% da planilha (fonte única). Chaves NÃO-data (excluded_*, notes,
    first_peak_days) são preservadas do yaml — a planilha não as tem e elas são
    decisões de curadoria (ex.: outliers do Top 5).
    """
    out = {}
    for lf, entry in calendar.items():
        merged = dict(entry)
        for k in _NON_DATE_KEYS:
            if k in current.get(lf, {}):
                merged[k] = current[lf][k]
        out[lf] = merged
    # LFs que existem no yaml mas sumiram da planilha: preserva (não apaga histórico)
    for lf, entry in current.items():
        if lf not in out:
            out[lf] = entry
    return out


# ───────────────────────── check contra o ledger ───────────────────────────
def check_against_ledger(
    calendar: dict, ledger_conn, today: date,
    min_orphan_leads: int = 100, lookback_days: int = 90,
) -> list[str]:
    """Cruza os leads do ledger com as janelas cadastradas. Avisa quando há lead
    entrando fora de qualquer LF — detector proativo do lançamento não cadastrado
    (que faz o resolver inventar janela torta) e do dia órfão na borda entre LFs.
    """
    warnings: list[str] = []
    covered: set[date] = set()
    last_cap_end: Optional[date] = None
    last_lf: Optional[str] = None
    for lf, e in calendar.items():
        try:
            cs, ce = date.fromisoformat(e["cap_start"]), date.fromisoformat(e["cap_end"])
        except (KeyError, ValueError, TypeError):
            continue
        d = cs
        while d <= ce:
            covered.add(d)
            d += timedelta(days=1)
        if last_cap_end is None or ce > last_cap_end:
            last_cap_end, last_lf = ce, lf

    start = today - timedelta(days=lookback_days)
    rows = ledger_conn.run(
        "SELECT created_at::date AS d, COUNT(*) FROM registros_ml "
        "WHERE created_at >= :s AND lead_score IS NOT NULL GROUP BY 1",
        s=start.isoformat(),
    )
    daily: dict[date, int] = {}
    for r in rows:
        d = r[0] if isinstance(r[0], date) else date.fromisoformat(str(r[0])[:10])
        daily[d] = int(r[1])

    if last_cap_end is None:
        return warnings

    # 1. leads recentes além do último LF cadastrado → cadastrar o próximo na planilha
    recent = {d: n for d, n in daily.items() if d > last_cap_end}
    if sum(recent.values()) >= min_orphan_leads:
        warnings.append(
            f"{sum(recent.values())} leads desde {min(recent)} ALÉM do último LF cadastrado "
            f"({last_lf}, cap_end {last_cap_end}) → cadastrar o próximo LF na planilha"
        )
    # 2. dia órfão: volume dentro do histórico, fora de qualquer janela (gap entre LFs)
    for d in sorted(daily):
        if d <= last_cap_end and d not in covered and daily[d] >= min_orphan_leads:
            warnings.append(
                f"{d}: {daily[d]} leads fora de qualquer janela de captação "
                f"(dia órfão entre LFs) → ajustar bordas na planilha"
            )
    return warnings


def main():
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Sincroniza launches.yaml a partir da planilha do calendário")
    ap.add_argument("--sheet-url", default=DEFAULT_SHEET_URL)
    ap.add_argument("--today", help="data de referência YYYY-MM-DD (default: hoje)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="só reconcilia planilha × yaml, não escreve")
    g.add_argument("--sync", action="store_true", help="regenera o launches.yaml")
    g.add_argument("--check", action="store_true", help="checa o calendário contra o ledger (LF não cadastrado / dia órfão)")
    args = ap.parse_args()

    from datetime import datetime
    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else date.today()

    rows = fetch_forms_rows(args.sheet_url)
    calendar, warnings = build_calendar(rows, today)

    print(f"\n=== {len(calendar)} LFs lidos da planilha (today={today}) ===")
    for w in warnings:
        print(f"  [aviso] {w}")

    if args.check:
        from src.data.ledger_connection import open_ledger_read_connection
        conn = open_ledger_read_connection()
        try:
            chk = check_against_ledger(calendar, conn, today)
        finally:
            conn.close()
        print("\n=== check contra o ledger ===")
        print("\n".join(f"  [ledger] {w}" for w in chk) if chk
              else "  (calendário cobre os leads do ledger)")
        return

    current = _load_current_yaml()
    print("\n=== reconcile planilha × launches.yaml atual ===")
    diffs = reconcile(calendar, current)
    print("\n".join(diffs) if diffs else "  (sem diferenças nas datas)")

    if args.sync:
        import yaml
        merged = merge_for_write(calendar, current)
        tmp = _YAML_PATH.with_suffix(".yaml.tmp")
        header = ("# launches.yaml — GERADO por src/data/launch_calendar.py a partir da\n"
                  "# planilha FORMS. NÃO editar à mão (datas são sobrescritas no próximo sync).\n"
                  "# Metadados de curadoria (excluded_from_reference, notes) são preservados.\n\n")
        with open(tmp, "w") as f:
            f.write(header)
            yaml.safe_dump(merged, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
        tmp.replace(_YAML_PATH)
        print(f"\n✅ launches.yaml regenerado ({len(merged)} LFs) em {_YAML_PATH}")


if __name__ == "__main__":
    main()
