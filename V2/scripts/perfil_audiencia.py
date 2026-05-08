"""
Compara o perfil de leads (pesquisa de captação) de um lançamento alvo
contra duas referências:
  - ref_pool: pool histórico (default Top 5 ROAS = LF40/41/44/45/47), via Sheets
  - ref_launch: lançamento mais recente já completo (default DEV20), via Railway ou Sheets

Reusa `normalizar_categoria_para_comparacao` de src.monitoring.data_quality
para evitar falsos shifts por acento/caixa/espaço.

Uso:
    python -m scripts.perfil_audiencia                    # default: LF54 vs Top5 vs DEV20
    python -m scripts.perfil_audiencia --target LF54
    python -m scripts.perfil_audiencia --target LF54 --no-markdown

Saída:
  - stdout: tabela por característica + chi²
  - V2/docs/perfil_audiencia_<target>.md (a menos que --no-markdown)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml
import pandas as pd
import numpy as np
import pg8000.native
from dotenv import load_dotenv
from scipy.stats import chi2_contingency

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from ml_evolution_report import load_sheets_data
from src.monitoring.data_quality import normalizar_categoria_para_comparacao

load_dotenv(REPO_ROOT / '.env')

RAILWAY_CUTOVER = pd.Timestamp('2026-02-25')

DEFAULT_REF_POOL = ['LF40', 'LF41', 'LF44', 'LF45', 'LF47']
DEFAULT_REF_LAUNCH = 'DEV20'
DEFAULT_TARGET = 'LF54'

SURVEY_MAP = [
    ('O seu gênero:',                          'Gênero'),
    ('Qual a sua idade?',                      'Idade'),
    ('O que você faz atualmente?',             'Ocupação'),
    ('Atualmente, qual a sua faixa salarial?', 'Faixa Salarial'),
    ('Você possui cartão de crédito?',         'Tem Cartão de Crédito'),
    ('Já estudou programação?',                'Já Estudou Programação'),
    ('Tem computador/notebook?',               'Tem Computador'),
]

PESQUISA_KEYS = {
    'O seu gênero:':                          'genero',
    'Qual a sua idade?':                      'idade',
    'O que você faz atualmente?':             'ocupacao',
    'Atualmente, qual a sua faixa salarial?': 'faixaSalarial',
    'Você possui cartão de crédito?':         'cartaoCredito',
    'Já estudou programação?':                'estudouProgramacao',
    'Tem computador/notebook?':               'computador',
}

# Mapeia variantes de rótulo do formulário para um único canônico (após normalize_series).
# Chaves devem estar normalizadas (lower, sem acento). Valor = label canônico de exibição.
UNIFICATION = {
    'Qual a sua idade?': {
        'menos de 18 anos':   '<18',
        'menos de 18':        '<18',
        '18 24 anos':         '18-24',
        '18 24':              '18-24',
        '25 34 anos':         '25-34',
        '25 34':              '25-34',
        '35 44 anos':         '35-44',
        '35 44':              '35-44',
        '45 54 anos':         '45-54',
        '45 54':              '45-54',
        'mais de 55 anos':    '55+',
        '55':                 '55+',
    },
    'O que você faz atualmente?': {
        'sou cltfuncionario publico': 'CLT/funcionário público',
        'clt funcionario publico':    'CLT/funcionário público',
        'sou autonomo':               'Autônomo',
        'autonomo empreendedor':      'Autônomo',
        'sou apenas estudante':       'Estudante',
        'estudante':                  'Estudante',
        'sou aposentado':             'Aposentado',
        'aposentado':                 'Aposentado',
        'nao trabalho e nem estudo':  'Não trabalho/nem estudo',
        'desempregado':               'Não trabalho/nem estudo',
    },
    'Atualmente, qual a sua faixa salarial?': {
        'entre r1000 a r2000 reais ao mes': 'Até R$2.000',
        'ate r 2000':                       'Até R$2.000',
        'entre r2001 a r3000 reais ao mes': 'R$2.001-3.000',
        'r 2001 a 3000':                    'R$2.001-3.000',
        'entre r3001 a r5000 reais ao mes': 'R$3.001-5.000',
        'r 3001 a 5000':                    'R$3.001-5.000',
        'mais de r5001 reais ao mes':       'Acima de R$5.000',
        'acima de r 5000':                  'Acima de R$5.000',
        'nao tenho renda':                  'Sem renda',
        'nenhuma renda':                    'Sem renda',
    },
    'O seu gênero:': {
        'masculino': 'Masculino',
        'feminino':  'Feminino',
    },
    'Você possui cartão de crédito?': {
        'sim': 'Sim',
        'nao': 'Não',
    },
    'Já estudou programação?': {
        'sim': 'Sim',
        'nao': 'Não',
    },
    'Tem computador/notebook?': {
        'sim': 'Sim',
        'nao': 'Não',
    },
}


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--target', default=DEFAULT_TARGET, help=f'Lançamento alvo (default {DEFAULT_TARGET})')
    p.add_argument('--ref-pool', default=','.join(DEFAULT_REF_POOL),
                   help=f'Pool histórico, vírgula-separado (default {",".join(DEFAULT_REF_POOL)})')
    p.add_argument('--ref-pool-label', default='Top 5 ROAS', help='Label exibido para o pool')
    p.add_argument('--ref-launch', default=DEFAULT_REF_LAUNCH,
                   help=f'Lançamento de referência adicional (default {DEFAULT_REF_LAUNCH}). Use "" para desativar.')
    p.add_argument('--output', default=None, help='Caminho do markdown (default V2/docs/perfil_audiencia_<target>.md)')
    p.add_argument('--no-markdown', action='store_true', help='Não escrever markdown, só stdout')
    return p.parse_args()


def load_launches() -> dict:
    with open(REPO_ROOT / 'configs' / 'launches.yaml') as f:
        return yaml.safe_load(f)


def source_for(cap_start: str) -> str:
    return 'railway' if pd.Timestamp(cap_start) >= RAILWAY_CUTOVER else 'sheets'


def slice_sheets(sheets: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    s = pd.Timestamp(cfg['cap_start'])
    e = pd.Timestamp(cfg['cap_end']) + pd.Timedelta(days=1)
    return sheets[(sheets['data'] >= s) & (sheets['data'] < e)].copy()


def query_lead_railway(cap_start: str, cap_end: str) -> pd.DataFrame:
    end_excl = (pd.to_datetime(cap_end) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    conn = pg8000.native.Connection(
        host=os.environ['RAILWAY_DB_HOST'],
        port=int(os.environ['RAILWAY_DB_PORT']),
        user=os.environ['RAILWAY_DB_USER'],
        password=os.environ['RAILWAY_DB_PASSWORD'],
        database=os.environ['RAILWAY_DB_NAME'],
        ssl_context=True,
    )
    cols_select = ', '.join(f"pesquisa->>'{k}' AS \"{q}\"" for q, k in PESQUISA_KEYS.items())
    sql = f"""
        SELECT data, {cols_select},
               source AS "Source", medium AS "Medium"
        FROM "Lead"
        WHERE data >= :s AND data < :e
    """
    rows = conn.run(sql, s=cap_start, e=end_excl)
    conn.close()
    cols = ['data'] + list(PESQUISA_KEYS.keys()) + ['Source', 'Medium']
    return pd.DataFrame(rows, columns=cols)


def load_launch(name: str, launches: dict, sheets_cache: pd.DataFrame | None) -> tuple[pd.DataFrame, str]:
    cfg = launches[name]
    src = source_for(cfg['cap_start'])
    if src == 'railway':
        df = query_lead_railway(cfg['cap_start'], cfg['cap_end'])
    else:
        df = slice_sheets(sheets_cache, cfg)
    return df, src


def normalize_series(s: pd.Series, col: str | None = None) -> pd.Series:
    s = s.fillna('(nulo)').astype(str).str.strip()
    s = s.replace({'': '(nulo)', 'None': '(nulo)', 'nan': '(nulo)'})
    s = s.apply(lambda v: '(nulo)' if v == '(nulo)' else (normalizar_categoria_para_comparacao(v) or '(nulo)'))
    if col and col in UNIFICATION:
        mapping = UNIFICATION[col]
        s = s.map(lambda v: mapping.get(v, v))
    return s


def compare(col: str, label: str, ref_pool: pd.DataFrame, ref_launch: pd.DataFrame | None,
            target: pd.DataFrame, ref_launch_name: str | None) -> dict:
    rp = normalize_series(ref_pool[col], col) if col in ref_pool.columns else pd.Series(dtype=str)
    rl = normalize_series(ref_launch[col], col) if (ref_launch is not None and col in ref_launch.columns) else pd.Series(dtype=str)
    tg = normalize_series(target[col], col) if col in target.columns else pd.Series(dtype=str)

    rp_vc, rl_vc, tg_vc = rp.value_counts(), rl.value_counts(), tg.value_counts()
    rp_n, rl_n, tg_n = int(rp_vc.sum()), int(rl_vc.sum()), int(tg_vc.sum())

    if rp_n == 0 or tg_n == 0:
        return {'label': label, 'col': col, 'empty': True, 'rp_n': rp_n, 'rl_n': rl_n, 'tg_n': tg_n}

    all_idx = list(set(rp_vc.index) | set(rl_vc.index) | set(tg_vc.index))
    combined = (rp_vc.reindex(all_idx, fill_value=0)
                + rl_vc.reindex(all_idx, fill_value=0)
                + tg_vc.reindex(all_idx, fill_value=0))
    top_cats = combined.sort_values(ascending=False).head(10).index.tolist()

    others_rp = rp_n - int(rp_vc.reindex(top_cats, fill_value=0).sum())
    others_rl = rl_n - int(rl_vc.reindex(top_cats, fill_value=0).sum())
    others_tg = tg_n - int(tg_vc.reindex(top_cats, fill_value=0).sum())

    rows = []
    for cat in top_cats:
        rows.append([int(rp_vc.get(cat, 0)), int(rl_vc.get(cat, 0)), int(tg_vc.get(cat, 0))])
    if others_rp > 0 or others_rl > 0 or others_tg > 0:
        rows.append([others_rp, others_rl, others_tg])
        top_cats = top_cats + ['(outros)']

    cont = np.array([[r[0] for r in rows], [r[2] for r in rows]])
    if (cont.sum(axis=0) > 0).all() and cont.sum() > 0:
        chi2, p, _, _ = chi2_contingency(cont)
    else:
        chi2, p = float('nan'), float('nan')

    detail = []
    for i, cat in enumerate(top_cats):
        rpp = rows[i][0] / rp_n * 100
        rlp = rows[i][1] / rl_n * 100 if rl_n else None
        tgp = rows[i][2] / tg_n * 100
        detail.append({
            'cat': str(cat),
            'rp_pct': rpp,
            'rl_pct': rlp,
            'tg_pct': tgp,
            'd_pool': tgp - rpp,
            'd_launch': (tgp - rlp) if rlp is not None else None,
        })

    return {
        'label': label, 'col': col, 'empty': False,
        'rp_n': rp_n, 'rl_n': rl_n, 'tg_n': tg_n,
        'chi2': chi2, 'p': p,
        'detail': detail,
        'ref_launch_name': ref_launch_name,
    }


def flag(d: float | None) -> str:
    if d is None:
        return ''
    a = abs(d)
    return ' ⚠⚠' if a >= 5 else (' ⚠' if a >= 2 else '')


def print_stdout(results: list, target_name: str, ref_pool_label: str, ref_launch_name: str | None):
    print()
    print('═' * 100)
    print(f'  PERFIL — {ref_pool_label}  vs  {ref_launch_name or "(sem ref_launch)"}  vs  {target_name}')
    print('═' * 100)
    for r in results:
        print(f'\n══════ {r["label"]} ══════')
        if r.get('empty'):
            print(f'  amostra vazia (rp={r["rp_n"]}, rl={r["rl_n"]}, tg={r["tg_n"]})')
            continue
        ref_label = r['ref_launch_name'] or '—'
        print(f'{"categoria":<48} {"pool %":>7} {ref_label[:7]:>8} {target_name[:7]:>8} {"Δ pool":>9} {"Δ ref":>9}')
        print('-' * 100)
        for d in r['detail']:
            cat_s = d['cat'][:48]
            rl_str = f"{d['rl_pct']:>7.1f}%" if d['rl_pct'] is not None else '       —'
            d_launch_str = f"{d['d_launch']:>+8.1f}{flag(d['d_launch']):<3}" if d['d_launch'] is not None else '       —'
            print(f'{cat_s:<48} {d["rp_pct"]:>6.1f}% {rl_str} {d["tg_pct"]:>7.1f}% '
                  f'{d["d_pool"]:>+8.1f}{flag(d["d_pool"]):<3} {d_launch_str}')
        sig = 'SHIFT' if r['p'] < 0.001 else ('shift?' if r['p'] < 0.05 else 'sem shift')
        print(f'\n  chi² (pool vs {target_name}): chi²={r["chi2"]:.1f} | p={r["p"]:.2e} | {sig}')
        print(f'  n_pool={r["rp_n"]:,} | n_{ref_label}={r["rl_n"]:,} | n_{target_name}={r["tg_n"]:,}')


def emit_markdown(path: Path, results: list, target_name: str, target_cfg: dict,
                  ref_pool_label: str, ref_pool_names: list[str], ref_pool_n: int,
                  ref_launch_name: str | None, ref_launch_cfg: dict | None, ref_launch_n: int,
                  target_n: int):
    today = pd.Timestamp.today().strftime('%Y-%m-%d')
    cap_now = min(pd.Timestamp.today(), pd.Timestamp(target_cfg['cap_end']))
    cap_pct = (cap_now - pd.Timestamp(target_cfg['cap_start'])).days
    cap_total = (pd.Timestamp(target_cfg['cap_end']) - pd.Timestamp(target_cfg['cap_start'])).days + 1
    in_progress = pd.Timestamp.today() <= pd.Timestamp(target_cfg['cap_end'])

    lines = []
    lines.append(f'# Perfil de audiência — {target_name}' + (' (em captação)' if in_progress else ''))
    lines.append('')
    lines.append(f'**Atualizado:** {today}  ')
    lines.append(f'**Janela {target_name}:** captação {target_cfg["cap_start"]} → {target_cfg["cap_end"]} '
                 f'({target_n:,} leads' + (f', {cap_pct}/{cap_total} dias' if in_progress else '') + ').  ')
    if 'vendas_start' in target_cfg:
        lines.append(f'**Vendas:** {target_cfg["vendas_start"]} → {target_cfg["vendas_end"]}.')
    lines.append('')
    n_refs = 2 if ref_launch_name else 1
    lines.append(f'Comparação contra {"duas referências" if n_refs == 2 else "uma referência"}:')
    lines.append(f'- **{ref_pool_label}:** {", ".join(ref_pool_names)} ({ref_pool_n:,} leads pooled, via Sheets)')
    if ref_launch_name and ref_launch_cfg:
        src = source_for(ref_launch_cfg['cap_start'])
        lines.append(f'- **{ref_launch_name}:** cap {ref_launch_cfg["cap_start"]} → {ref_launch_cfg["cap_end"]} '
                     f'({ref_launch_n:,} leads, via {src.title()})')
    lines.append('')
    lines.append('Teste estatístico: chi-quadrado por característica categórica '
                 '(`pool vs target`). Categorias normalizadas via '
                 '`src.monitoring.data_quality.normalizar_categoria_para_comparacao` (sem acento, lower).')
    lines.append('')
    lines.append('---')
    lines.append('')

    # Tabela 1: pool vs target
    lines.append(f'## {target_name} vs {ref_pool_label}')
    lines.append('')
    lines.append(f'| Característica | Categoria | {ref_pool_label} | {target_name} | Δ |')
    lines.append('|---|---|---:|---:|---:|')
    for r in results:
        if r.get('empty'):
            continue
        for d in r['detail']:
            if abs(d['d_pool']) < 2 and d['cat'] not in ('feminino', 'masculino'):
                continue
            sign = flag(d['d_pool'])
            lines.append(f'| {r["label"]} | {d["cat"]} | {d["rp_pct"]:.1f}% | {d["tg_pct"]:.1f}% | '
                         f'**{d["d_pool"]:+.1f}**{sign} |')
    lines.append('')

    # Tabela 2: ref_launch vs target
    if ref_launch_name:
        lines.append(f'## {target_name} vs {ref_launch_name}')
        lines.append('')
        lines.append(f'| Característica | Categoria | {ref_launch_name} | {target_name} | Δ |')
        lines.append('|---|---|---:|---:|---:|')
        for r in results:
            if r.get('empty'):
                continue
            for d in r['detail']:
                if d['rl_pct'] is None:
                    continue
                if abs(d['d_launch']) < 2 and d['cat'] not in ('feminino', 'masculino'):
                    continue
                sign = flag(d['d_launch'])
                lines.append(f'| {r["label"]} | {d["cat"]} | {d["rl_pct"]:.1f}% | {d["tg_pct"]:.1f}% | '
                             f'**{d["d_launch"]:+.1f}**{sign} |')
        lines.append('')

    # chi² summary
    lines.append('## Significância (chi² pool vs target)')
    lines.append('')
    lines.append('| Característica | n_pool | n_target | chi² | p | resultado |')
    lines.append('|---|---:|---:|---:|---:|---|')
    for r in results:
        if r.get('empty'):
            lines.append(f'| {r["label"]} | {r["rp_n"]} | {r["tg_n"]} | — | — | amostra vazia |')
            continue
        sig = 'SHIFT' if r['p'] < 0.001 else ('shift?' if r['p'] < 0.05 else 'sem shift')
        lines.append(f'| {r["label"]} | {r["rp_n"]:,} | {r["tg_n"]:,} | {r["chi2"]:.1f} | {r["p"]:.2e} | {sig} |')
    lines.append('')
    lines.append('Legenda Δ: ⚠ ≥ 2pp · ⚠⚠ ≥ 5pp.')
    if in_progress:
        lines.append('')
        lines.append(f'> **Captação ainda aberta:** dia {cap_pct}/{cap_total}. Re-rodar quando fechar '
                     f'em {target_cfg["cap_end"]}.')

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines), encoding='utf-8')
    print(f'\n→ Markdown salvo em {path.relative_to(REPO_ROOT)}')


def main():
    args = parse_args()
    launches = load_launches()
    if args.target not in launches:
        sys.exit(f'ERRO: {args.target} não está em configs/launches.yaml')

    ref_pool_names = [x.strip() for x in args.ref_pool.split(',') if x.strip()]
    for n in ref_pool_names:
        if n not in launches:
            sys.exit(f'ERRO: {n} (ref_pool) não está em configs/launches.yaml')

    ref_launch_name = args.ref_launch.strip() or None
    if ref_launch_name and ref_launch_name not in launches:
        sys.exit(f'ERRO: {ref_launch_name} (ref_launch) não está em configs/launches.yaml')

    # Pool histórico sempre via Sheets (cobertura uniforme; Sheets continua ingerindo após cutover do Railway).
    # Target e ref_launch são lançamentos correntes — Railway se post-cutover.
    print('Carregando Sheets pesquisa...')
    sheets = load_sheets_data()
    sheets['data'] = pd.to_datetime(sheets['data'], errors='coerce')
    # Dedup de colunas (alguns dumps têm colunas repetidas após merge prod/backup)
    sheets = sheets.loc[:, ~sheets.columns.duplicated()]

    pool_frames = []
    for n in ref_pool_names:
        df = slice_sheets(sheets, launches[n])
        print(f'  {n} (sheets): {len(df):,} leads')
        pool_frames.append(df)
    pool = pd.concat(pool_frames, ignore_index=True)
    print(f'  POOL {args.ref_pool_label}: {len(pool):,} leads')

    target_df, target_src = load_launch(args.target, launches, sheets)
    print(f'  {args.target} ({target_src}): {len(target_df):,} leads')

    ref_launch_df = None
    if ref_launch_name:
        ref_launch_df, ref_launch_src = load_launch(ref_launch_name, launches, sheets)
        print(f'  {ref_launch_name} ({ref_launch_src}): {len(ref_launch_df):,} leads')

    results = [compare(col, label, pool, ref_launch_df, target_df, ref_launch_name)
               for col, label in SURVEY_MAP]

    print_stdout(results, args.target, args.ref_pool_label, ref_launch_name)

    if not args.no_markdown:
        out = Path(args.output) if args.output else REPO_ROOT / 'docs' / f'perfil_audiencia_{args.target.lower()}.md'
        if not out.is_absolute():
            out = REPO_ROOT / out
        emit_markdown(
            out, results, args.target, launches[args.target],
            args.ref_pool_label, ref_pool_names, len(pool),
            ref_launch_name, launches.get(ref_launch_name) if ref_launch_name else None,
            len(ref_launch_df) if ref_launch_df is not None else 0,
            len(target_df),
        )


if __name__ == '__main__':
    main()
