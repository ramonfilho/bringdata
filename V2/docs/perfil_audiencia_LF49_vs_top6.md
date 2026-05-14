# Perfil de audiência — LF49

> **Nota:** análise feita com pool de referência anterior (Top 5/6 antigo). Definição canônica atual em [docs/METODOLOGIA_TOP5_ROAS.md](METODOLOGIA_TOP5_ROAS.md) (recalibrada 2026-05-14: LF45, LF44, LF46, LF41, LF43).

**Atualizado:** 2026-05-12  
**Janela LF49:** captação 2026-03-17 → 2026-03-23 (15,622 leads).  
**Vendas:** 2026-03-30 → 2026-04-05.

Comparação contra uma referência:
- **Top 6 ROAS atribuível 60d:** LF44, LF45, LF41, LF46, LF43, LF47 (54,215 leads pooled, via Sheets)

Teste estatístico: chi-quadrado por característica categórica (`pool vs target`). Categorias normalizadas via `src.monitoring.data_quality.normalizar_categoria_para_comparacao` (sem acento, lower).

---

## LF49 vs Top 6 ROAS atribuível 60d

| Característica | Categoria | Top 6 ROAS atribuível 60d | LF49 | Δ |
|---|---|---:|---:|---:|
| Gênero | Masculino | 81.7% | 71.1% | **-10.6** ⚠⚠ |
| Gênero | Feminino | 18.2% | 28.9% | **+10.7** ⚠⚠ |
| Idade | 25-34 | 30.9% | 27.6% | **-3.3** ⚠ |
| Idade | 45-54 | 11.9% | 14.3% | **+2.4** ⚠ |
| Ocupação | CLT/funcionário público | 45.4% | 38.6% | **-6.8** ⚠⚠ |
| Ocupação | Não trabalho/nem estudo | 10.3% | 15.2% | **+4.9** ⚠ |
| Faixa Salarial | Até R$2.000 | 28.8% | 31.4% | **+2.6** ⚠ |
| Faixa Salarial | Sem renda | 26.5% | 32.5% | **+6.0** ⚠⚠ |
| Faixa Salarial | R$2.001-3.000 | 20.5% | 17.9% | **-2.6** ⚠ |
| Faixa Salarial | R$3.001-5.000 | 15.6% | 11.7% | **-3.9** ⚠ |
| Faixa Salarial | Acima de R$5.000 | 8.6% | 6.5% | **-2.1** ⚠ |
| Tem Cartão de Crédito | Não | 57.8% | 69.5% | **+11.7** ⚠⚠ |
| Tem Cartão de Crédito | Sim | 42.2% | 30.5% | **-11.7** ⚠⚠ |
| Já Estudou Programação | Não | 63.9% | 76.0% | **+12.1** ⚠⚠ |
| Já Estudou Programação | Sim | 36.1% | 24.0% | **-12.1** ⚠⚠ |
| Tem Computador | Sim | 87.1% | 69.5% | **-17.6** ⚠⚠ |
| Tem Computador | Não | 12.9% | 30.5% | **+17.6** ⚠⚠ |

## Significância (chi² pool vs target)

| Característica | n_pool | n_target | chi² | p | resultado |
|---|---:|---:|---:|---:|---|
| Gênero | 54,215 | 15,622 | 841.2 | 2.16e-183 | SHIFT |
| Idade | 54,215 | 15,622 | 223.3 | 2.05e-45 | SHIFT |
| Ocupação | 54,215 | 15,622 | 430.5 | 7.97e-91 | SHIFT |
| Faixa Salarial | 54,215 | 15,622 | 421.0 | 8.98e-89 | SHIFT |
| Tem Cartão de Crédito | 54,215 | 15,622 | 696.1 | 7.12e-152 | SHIFT |
| Já Estudou Programação | 54,215 | 15,622 | 801.4 | 9.51e-175 | SHIFT |
| Tem Computador | 54,215 | 15,622 | 2677.8 | 0.00e+00 | SHIFT |

Legenda Δ: ⚠ ≥ 2pp · ⚠⚠ ≥ 5pp.