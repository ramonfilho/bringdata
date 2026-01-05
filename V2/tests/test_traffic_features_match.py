"""
Teste de match entre Medium de leads e features de tráfego Meta.

Valida se a normalização de adset_name funciona e qual % de leads conseguem match.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
from src.data_processing.traffic_features import (
    consolidar_relatorios_meta,
    renomear_colunas_meta,
    normalizar_adset_name_para_medium,
    adicionar_features_trafego_meta
)


def criar_dataset_leads_mock():
    """
    Cria dataset mock com as 8 categorias Medium de produção.
    """
    categorias_medium = [
        'Aberto',
        'Interesse Programação',
        'Linguagem de programação',
        'Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação',
        'Lookalike 2% Alunos + Interesse Linguagem de Programação',
        'Lookalike 2% Cadastrados - DEV 2.0 + Interesses',
        'Outros',
        'dgen'
    ]

    # Criar 1000 leads distribuídos pelas categorias
    import numpy as np
    np.random.seed(42)

    n_leads = 1000
    mediums = np.random.choice(categorias_medium, size=n_leads, p=[0.3, 0.15, 0.1, 0.1, 0.1, 0.15, 0.08, 0.02])

    df_mock = pd.DataFrame({
        'Medium': mediums,
        'target': np.random.binomial(1, 0.007, n_leads),  # ~0.7% conversão
        'feature_1': np.random.randn(n_leads),
        'feature_2': np.random.randn(n_leads)
    })

    return df_mock


def testar_normalizacao_adset_names():
    """
    Testa se a normalização de adset_name funciona corretamente.
    """
    print("\n" + "="*80)
    print("TESTE 1: NORMALIZAÇÃO DE ADSET NAMES")
    print("="*80)

    # Casos de teste (adset_name → medium esperado)
    casos_teste = [
        # Com prefixo ADV
        ("ADV | Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação",
         "Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação"),

        ("ADV | Linguagem de programação",
         "Linguagem de programação"),

        # Com prefixo Leads DEVLF (deve virar Outros)
        ("Leads DEVLF | CPL04 É Hoje",
         "Outros"),

        # Sem prefixo
        ("Aberto",
         "Aberto"),

        ("Lookalike 2% Cadastrados - DEV 2.0 + Interesses",
         "Lookalike 2% Cadastrados - DEV 2.0 + Interesses"),

        # Descontinuadas (deve virar Outros)
        ("Lookalike 3% Alunos + Interesses",
         "Outros"),

        ("Interesse Python",
         "Outros"),
    ]

    print(f"\nTestando {len(casos_teste)} casos:")
    print("-" * 80)
    print(f"{'ADSET NAME':<60} {'ESPERADO':<18} {'✓/✗':<4}")
    print("-" * 80)

    passou = 0
    falhou = 0

    for adset_name, esperado in casos_teste:
        resultado = normalizar_adset_name_para_medium(adset_name)
        match = "✓" if resultado == esperado else "✗"

        adset_display = adset_name[:57] + "..." if len(adset_name) > 57 else adset_name

        if resultado == esperado:
            passou += 1
            print(f"{adset_display:<60} {esperado[:15]:<18} {match:<4}")
        else:
            falhou += 1
            print(f"{adset_display:<60} {esperado[:15]:<18} {match:<4}")
            print(f"  → Obtido: '{resultado}'")

    print("-" * 80)
    print(f"Resultado: {passou}/{len(casos_teste)} passaram")

    if falhou > 0:
        print(f"⚠️  {falhou} casos falharam!")
    else:
        print(f"✅ Todos os casos passaram!")

    return passou == len(casos_teste)


def testar_match_com_dados_reais():
    """
    Testa match usando dados reais de relatórios Meta.
    """
    print("\n" + "="*80)
    print("TESTE 2: MATCH COM DADOS REAIS")
    print("="*80)

    # Caminho absoluto
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    pasta_trafego = os.path.join(base_dir, 'data', 'devclub', 'treino', 'features_trafego')

    # Verificar se pasta existe
    if not os.path.exists(pasta_trafego):
        print(f"❌ Pasta não encontrada: {pasta_trafego}")
        print("Pulando teste com dados reais.")
        return False

    # Criar dataset mock de leads
    df_leads = criar_dataset_leads_mock()

    print(f"\nDataset de leads (mock):")
    print(f"  Registros: {len(df_leads):,}")
    print(f"  Categorias Medium:")
    for cat, count in df_leads['Medium'].value_counts().items():
        pct = count / len(df_leads) * 100
        print(f"    {cat[:50]:<52} {count:>4} ({pct:>5.1f}%)")

    # Adicionar features de tráfego
    try:
        df_com_trafego = adicionar_features_trafego_meta(
            df_leads=df_leads,
            pasta_trafego=pasta_trafego
        )

        # Analisar resultado
        print(f"\n📊 ANÁLISE DO MATCH:")
        print("=" * 60)

        colunas_traffic = [col for col in df_com_trafego.columns if col.startswith('traffic_')]

        # Ver cobertura por categoria
        print(f"\nCobertura por categoria Medium:")
        print("-" * 70)
        print(f"{'CATEGORIA':<50} {'LEADS':<8} {'COM DATA':<10} {'%':<6}")
        print("-" * 70)

        for cat in df_leads['Medium'].unique():
            total = (df_com_trafego['Medium'] == cat).sum()
            com_data = ((df_com_trafego['Medium'] == cat) & (df_com_trafego['traffic_impressions'] > 0)).sum()
            pct = (com_data / total * 100) if total > 0 else 0

            cat_display = cat[:47] + "..." if len(cat) > 47 else cat
            print(f"{cat_display:<50} {total:<8,} {com_data:<10,} {pct:<6.1f}%")

        # Estatísticas das features de tráfego
        print(f"\n📈 ESTATÍSTICAS DAS FEATURES DE TRÁFEGO:")
        print("=" * 60)

        for col in colunas_traffic:
            valores_nao_zero = df_com_trafego[df_com_trafego[col] > 0][col]
            if len(valores_nao_zero) > 0:
                print(f"\n{col}:")
                print(f"  Não-zero: {len(valores_nao_zero):,} ({len(valores_nao_zero)/len(df_com_trafego)*100:.1f}%)")
                print(f"  Média: {valores_nao_zero.mean():.2f}")
                print(f"  Min: {valores_nao_zero.min():.2f}")
                print(f"  Max: {valores_nao_zero.max():.2f}")

        return True

    except Exception as e:
        print(f"❌ Erro ao adicionar features de tráfego: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """
    Executa todos os testes.
    """
    print("\n" + "🧪 " + "="*76 + " 🧪")
    print("TESTE DE FEATURES DE TRÁFEGO META")
    print("🧪 " + "="*76 + " 🧪")

    resultados = []

    # Teste 1: Normalização
    print("\n" + "🔬 Executando Teste 1...")
    resultado1 = testar_normalizacao_adset_names()
    resultados.append(("Normalização de adset_name", resultado1))

    # Teste 2: Match com dados reais
    print("\n" + "🔬 Executando Teste 2...")
    resultado2 = testar_match_com_dados_reais()
    resultados.append(("Match com dados reais", resultado2))

    # Resumo final
    print("\n" + "="*80)
    print("RESUMO DOS TESTES")
    print("="*80)

    for nome, passou in resultados:
        status = "✅ PASSOU" if passou else "❌ FALHOU"
        print(f"{nome:<40} {status}")

    total_passou = sum(1 for _, p in resultados if p)
    print(f"\n{total_passou}/{len(resultados)} testes passaram")

    if total_passou == len(resultados):
        print("\n🎉 Todos os testes passaram! Features de tráfego prontas para uso.")
    else:
        print("\n⚠️  Alguns testes falharam. Revisar implementação.")


if __name__ == "__main__":
    main()
