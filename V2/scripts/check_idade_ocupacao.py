"""
Verifica se 'idade=18-24' é proxy de 'ocupacao=Estudante' nas pesquisas do Railway.

Reusa as mesmas normalizações de scripts/perfil_audiencia.py para garantir
que a contagem bate com os outros relatórios.

Saída: stdout com crosstab + Cramér's V + condicionais.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import numpy as np
import pg8000.native
from dotenv import load_dotenv
from scipy.stats import chi2_contingency

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.perfil_audiencia import PESQUISA_KEYS, UNIFICATION, normalize_series

load_dotenv(REPO_ROOT / '.env')

RAILWAY_CUTOVER = '2026-02-25'


def fetch() -> pd.DataFrame:
    conn = pg8000.native.Connection(
        host=os.environ['RAILWAY_DB_HOST'],
        port=int(os.environ['RAILWAY_DB_PORT']),
        user=os.environ['RAILWAY_DB_USER'],
        password=os.environ['RAILWAY_DB_PASSWORD'],
        database=os.environ['RAILWAY_DB_NAME'],
        ssl_context=True,
    )
    rows = conn.run(
        """
        SELECT pesquisa->>'idade'    AS idade_raw,
               pesquisa->>'ocupacao' AS ocupacao_raw,
               data
        FROM "Lead"
        WHERE data >= :cut
          AND pesquisa IS NOT NULL
          AND pesquisa->>'idade'    IS NOT NULL
          AND pesquisa->>'ocupacao' IS NOT NULL
        """,
        cut=RAILWAY_CUTOVER,
    )
    conn.close()
    return pd.DataFrame(rows, columns=['idade_raw', 'ocupacao_raw', 'data'])


def cramers_v(crosstab: pd.DataFrame) -> tuple[float, float, float]:
    arr = crosstab.values
    chi2, p, _, _ = chi2_contingency(arr)
    n = arr.sum()
    r, k = arr.shape
    denom = n * (min(r, k) - 1)
    v = float(np.sqrt(chi2 / denom)) if denom > 0 else float('nan')
    return chi2, p, v


def main():
    df = fetch()
    print(f"Leads carregados do Railway (data ≥ {RAILWAY_CUTOVER}): {len(df):,}")

    df['idade']    = normalize_series(df['idade_raw'],    'Qual a sua idade?')
    df['ocupacao'] = normalize_series(df['ocupacao_raw'], 'O que você faz atualmente?')

    df = df[(df['idade'] != '(nulo)') & (df['ocupacao'] != '(nulo)')]
    print(f"Após remover nulos pós-normalização: {len(df):,}")

    # Crosstab absoluto
    ct = pd.crosstab(df['idade'], df['ocupacao'])
    order_idade = ['<18', '18-24', '25-34', '35-44', '45-54', '55+']
    order_ocup  = ['Estudante', 'CLT/funcionário público', 'Autônomo',
                   'Aposentado', 'Não trabalho/nem estudo']
    ct = ct.reindex(index=[c for c in order_idade if c in ct.index],
                    columns=[c for c in order_ocup if c in ct.columns],
                    fill_value=0)
    if ct.shape[0] < 2 or ct.shape[1] < 2:
        print("Crosstab degenerada — abortando.")
        return

    chi2, p, V = cramers_v(ct)
    print()
    print("══════ Crosstab idade × ocupação (absoluto) ══════")
    print(ct.to_string())
    print()

    print("══════ % de cada IDADE que é cada OCUPAÇÃO (linha) ══════")
    row_pct = ct.div(ct.sum(axis=1), axis=0) * 100
    print(row_pct.round(1).to_string())
    print()

    print("══════ % de cada OCUPAÇÃO que é cada IDADE (coluna) ══════")
    col_pct = ct.div(ct.sum(axis=0), axis=1) * 100
    print(col_pct.round(1).to_string())
    print()

    print("══════ Associação geral ══════")
    print(f"  chi² = {chi2:,.1f}")
    print(f"  p    = {p:.2e}")
    print(f"  Cramér's V = {V:.3f}  "
          f"(0=independente, 0.1=fraco, 0.3=moderado, 0.5+=forte)")
    print()

    # Métricas-foco: o quanto Estudante e 18-24 se sobrepõem
    if 'Estudante' in ct.columns and '18-24' in ct.index:
        n_total = ct.values.sum()
        n_est   = ct['Estudante'].sum()
        n_1824  = ct.loc['18-24'].sum()
        n_both  = int(ct.loc['18-24', 'Estudante'])

        print("══════ Sobreposição Estudante × 18-24 ══════")
        print(f"  Total leads válidos    : {n_total:,}")
        print(f"  Estudantes             : {n_est:,}  ({n_est/n_total*100:.1f}% do total)")
        print(f"  Idade 18-24            : {n_1824:,}  ({n_1824/n_total*100:.1f}% do total)")
        print(f"  Estudante E 18-24      : {n_both:,}  ({n_both/n_total*100:.1f}% do total)")
        print()
        print(f"  P(Estudante | 18-24)   : {n_both/n_1824*100:.1f}%   "
              f"(do total de 18-24, quantos são estudantes)")
        print(f"  P(18-24 | Estudante)   : {n_both/n_est*100:.1f}%   "
              f"(do total de estudantes, quantos têm 18-24)")
        # Jaccard
        n_union = n_est + n_1824 - n_both
        print(f"  Jaccard(Est, 18-24)    : {n_both/n_union*100:.1f}%   "
              f"(interseção / união — 100% = mesmo grupo)")


if __name__ == '__main__':
    main()
