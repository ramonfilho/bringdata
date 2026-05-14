# Perfil de audiência — LF48

> **Nota:** análise feita com pool de referência anterior (Top 5/6 antigo). Definição canônica atual em [docs/METODOLOGIA_TOP5_ROAS.md](METODOLOGIA_TOP5_ROAS.md) (recalibrada 2026-05-14: LF45, LF44, LF46, LF41, LF43).

**Atualizado:** 2026-05-12  
**Janela LF48:** captação 2026-03-10 → 2026-03-16 (14,828 leads).  
**Vendas:** 2026-03-23 → 2026-03-29.

Comparação contra uma referência:
- **Top 6 ROAS atribuível 60d:** LF44, LF45, LF41, LF46, LF43, LF47 (54,215 leads pooled, via Sheets)

Teste estatístico: chi-quadrado por característica categórica (`pool vs target`). Categorias normalizadas via `src.monitoring.data_quality.normalizar_categoria_para_comparacao` (sem acento, lower).

---

## LF48 vs Top 6 ROAS atribuível 60d

| Característica | Categoria | Top 6 ROAS atribuível 60d | LF48 | Δ |
|---|---|---:|---:|---:|
| Gênero | Masculino | 81.7% | 74.2% | **-7.6** ⚠⚠ |
| Gênero | Feminino | 18.2% | 25.8% | **+7.6** ⚠⚠ |
| Idade | 35-44 | 23.3% | 25.6% | **+2.3** ⚠ |
| Idade | 18-24 | 23.1% | 20.2% | **-2.9** ⚠ |
| Idade | 45-54 | 11.9% | 14.1% | **+2.1** ⚠ |
| Ocupação | CLT/funcionário público | 45.4% | 41.1% | **-4.3** ⚠ |
| Ocupação | Autônomo | 24.6% | 28.0% | **+3.4** ⚠ |
| Ocupação | Estudante | 18.5% | 15.6% | **-2.9** ⚠ |
| Ocupação | Não trabalho/nem estudo | 10.3% | 13.7% | **+3.4** ⚠ |
| Tem Cartão de Crédito | Não | 57.8% | 65.4% | **+7.7** ⚠⚠ |
| Tem Cartão de Crédito | Sim | 42.2% | 34.5% | **-7.7** ⚠⚠ |
| Já Estudou Programação | Não | 63.9% | 72.0% | **+8.1** ⚠⚠ |
| Já Estudou Programação | Sim | 36.1% | 28.0% | **-8.1** ⚠⚠ |
| Tem Computador | Sim | 87.1% | 77.5% | **-9.6** ⚠⚠ |
| Tem Computador | Não | 12.9% | 22.5% | **+9.6** ⚠⚠ |

## Significância (chi² pool vs target)

| Característica | n_pool | n_target | chi² | p | resultado |
|---|---:|---:|---:|---:|---|
| Gênero | 54,215 | 14,828 | 419.9 | 6.71e-92 | SHIFT |
| Idade | 54,215 | 14,828 | 170.0 | 4.58e-34 | SHIFT |
| Ocupação | 54,215 | 14,828 | 296.2 | 6.73e-62 | SHIFT |
| Faixa Salarial | 54,215 | 14,828 | 65.8 | 7.80e-13 | SHIFT |
| Tem Cartão de Crédito | 54,215 | 14,828 | 285.3 | 1.12e-62 | SHIFT |
| Já Estudou Programação | 54,215 | 14,828 | 338.6 | 2.95e-74 | SHIFT |
| Tem Computador | 54,215 | 14,828 | 836.2 | 2.64e-182 | SHIFT |

Legenda Δ: ⚠ ≥ 2pp · ⚠⚠ ≥ 5pp.