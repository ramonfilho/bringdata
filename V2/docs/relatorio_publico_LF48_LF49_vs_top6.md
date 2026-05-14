# Relatório de público — LF48, LF49 vs Top 6 ROAS atribuível 60d

**Atualizado:** 2026-05-12
**Modelo de scoring:** Challenger abr28 (run_id `5d158f0aa6e54b489498470446194a6c`)

---

## 1. Pool de referência (Top 6)

| LF | n leads captação | ROAS atribuível 60d |
|---|---:|---:|
| LF44 | 5.806 | > 1.5× |
| LF45 | 15.325 | 2.04× |
| LF41 | 2.464 | > 1.5× |
| LF46 | 11.592 | > 1.5× |
| LF43 | 6.851 | 1.64× |
| LF47 | 12.382 | 1.55× |
| **Total** | **54.420** | — |

Critério de inclusão: ROAS atribuível 60d ≥ 1.5×. Cobertura: jan/26 a mar/26.

---

## 2. Sinal de composição da audiência (categórico)

Comparação por feature da pesquisa de captação, agnóstica ao modelo. Chi² por categoria, p < 0.001 = SHIFT estatisticamente significante.

### LF48 vs Top 6

| Feature | Top 6 | LF48 | Δ pp | Severidade |
|---|---:|---:|---:|---|
| Tem computador = Sim | 87.1% | 77.5% | **-9.6** | 🔴 ALTA |
| Estudou programação = Sim | 36.1% | 28.0% | **-8.1** | 🔴 ALTA |
| Tem cartão = Sim | 42.2% | 34.5% | **-7.7** | 🔴 ALTA |
| Gênero = Masculino | 81.7% | 74.2% | **-7.6** | 🔴 ALTA |
| Ocupação = CLT | 45.4% | 41.1% | -4.3 | 🟡 MÉDIA |
| Ocupação = Autônomo | 24.6% | 28.0% | +3.4 | 🟡 MÉDIA |
| Não trabalho/nem estudo | 10.3% | 13.7% | +3.4 | 🟡 MÉDIA |
| Idade 18-24 | 23.1% | 20.2% | -2.9 | 🟡 MÉDIA |
| Estudante | 18.5% | 15.6% | -2.9 | 🟡 MÉDIA |
| Idade 35-44 | 23.3% | 25.6% | +2.3 | 🟡 MÉDIA |
| Idade 45-54 | 11.9% | 14.1% | +2.1 | 🟡 MÉDIA |

Todas as 7 features categóricas têm chi² SHIFT (p ≪ 0.001). Direção consistente: LF48 atraiu público com **menos computador, menos cartão, menos programação prévia, mais feminino**. Composição claramente degradada em relação à referência.

### LF49 vs Top 6

| Feature | Top 6 | LF49 | Δ pp | Severidade |
|---|---:|---:|---:|---|
| Tem computador = Sim | 87.1% | 69.5% | **-17.6** | 🔴 ALTA |
| Estudou programação = Sim | 36.1% | 24.0% | **-12.1** | 🔴 ALTA |
| Tem cartão = Sim | 42.2% | 30.5% | **-11.7** | 🔴 ALTA |
| Gênero = Masculino | 81.7% | 71.1% | **-10.6** | 🔴 ALTA |
| Ocupação = CLT | 45.4% | 38.6% | **-6.8** | 🔴 ALTA |
| Sem renda | 26.5% | 32.5% | **+6.0** | 🔴 ALTA |
| Não trabalho/nem estudo | 10.3% | 15.2% | +4.9 | 🟡 MÉDIA |
| R$3.001-5.000 | 15.6% | 11.7% | -3.9 | 🟡 MÉDIA |
| Idade 25-34 | 30.9% | 27.6% | -3.3 | 🟡 MÉDIA |
| Até R$2.000 | 28.8% | 31.4% | +2.6 | 🟡 MÉDIA |

LF49 tem **degradação em magnitude ~2× maior que LF48** em todas as features-chave. "Tem computador" cai 17.6pp (de 87% pra 69%). Chi² SHIFT em todas as 7 features.

---

## 3. Sinal do modelo (ML score)

Re-score com Challenger abr28 + comparação com baseline NEW6.

| Métrica | Baseline Top 6 | LF48 | LF49 |
|---|---:|---:|---:|
| n leads scoreados | 61.790 | 14.827 | 15.619 |
| score_mean | 0.4413 | 0.4084 | 0.3805 |
| % em D10 | 11.8% | 9.7% | 7.4% |
| % em D9+D10 | 28.4% | 20.0% | 15.2% |
| % em D8-D10 | 38.5% | 30.6% | 23.8% |

| Δ vs baseline | LF48 | LF49 |
|---|---:|---:|
| Δ score_mean (%) | **-7.46%** | **-13.77%** |
| Δ pct_d10 (pp) | -2.10 | **-4.43** |
| Δ pct_d9_d10 (pp) | **-8.35** | **-13.16** |
| Δ pct_d8_d10 (pp) | **-7.85** | **-14.64** |

Limiares da baseline (em `devclub_quality_signal.json`):
- `delta_score_mean_pct_warn` = -5% / `alert` = -10%
- `delta_pct_d9_d10_warn` = -3pp / `alert` = -5pp

**Resultado em produção:**
- **LF48:** Δscore -7.46% → MEDIUM (entre warn e alert) | Δpct_d9_d10 -8.35pp → HIGH (pior que alert) → **alerta HIGH** (max das severidades)
- **LF49:** Δscore -13.77% → HIGH (pior que alert) | Δpct_d9_d10 -13.16pp → HIGH → **alerta HIGH**

---

## 4. Leitura

1. **Os dois sinais convergem.** O categórico mostra que LF48/LF49 atraíram público sistematicamente menos qualificado nas features socioeconômicas-chave (computador, cartão, programação, gênero, ocupação). O ML score confirma: o modelo Challenger, ao rodar nesses leads, produz menos D9/D10 e score médio mais baixo. Não é problema de sinal — é problema real de público.

2. **LF49 ≈ 2× pior que LF48.** Em todos os indicadores. Coerente com a observação histórica de que LF48 e LF49 vieram do período "campanhas ML RUIM" (notas no `launches.yaml`), mas LF49 foi a pior versão.

3. **Magnitude tem consequência operacional.** Com a baseline NEW6 plugada no `audience_quality_signal`, batches diários durante esses lançamentos teriam disparado alerta HIGH desde os primeiros dias de captação — o que dá tempo de reação, em vez de descobrir o problema só após o carrinho fechar.

4. **O viés de feature mais discriminante é "Tem computador".** Em LF49 cai 17.6pp. Faz sentido intuitivamente: vender curso de programação pra quem não tem computador é o caso mais claro de público mal-segmentado. Esse delta sozinho explica boa parte do colapso de ROAS desses dois lançamentos.

---

## Arquivos detalhados

- [Perfil completo LF48 vs Top 6](perfil_audiencia_LF48_vs_top6.md) — tabela com todas as categorias + chi² por feature
- [Perfil completo LF49 vs Top 6](perfil_audiencia_LF49_vs_top6.md) — idem
- [Comparativo dos 3 pools (OLD, NEW4, NEW6)](compare_reference_pools_3way.csv) — análise que motivou a escolha do NEW6
- Baselines atualizadas:
  - `configs/reference_audience_profiles/devclub.json` (categórico)
  - `configs/reference_audience_profiles/devclub_quality_signal.json` (ML score)
