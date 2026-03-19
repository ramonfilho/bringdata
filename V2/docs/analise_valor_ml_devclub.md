# Análise de Valor Real do Sistema ML — DevClub

**Data:** 18/03/2026
**Período analisado:** LF40 (dez/2025) → LF46 (mar/2026)
**Pergunta central:** as campanhas ML geraram ROAS e margem de contribuição genuinamente maiores, ou apenas substituíram o desempenho que as campanhas Controle já teriam?

---

## 1. Metodologia

### 1.1 Fontes de dados

Cada lançamento tem um relatório de validação gerado pelo script `validate_ml_performance.py`. Para esta análise foram utilizados os **relatórios mais recentes** de cada pasta em `outputs/validation/`:

| Lançamento | Pasta | Período de Vendas |
|---|---|---|
| LF40 | `08:12 - 14:12` | 08–14/dez/2025 |
| LF41 | `15:12 - 21:12` | 15–21/dez/2025 |
| LF42 | `22:12 - 28:12` | 22–28/dez/2025 |
| DEV19 | `19:01 - 25:01` | 19–25/jan/2026 |
| LF43 | `02:02 - 08:02` | 02–08/fev/2026 |
| LF44 | `09:02 - 15:02` | 09–15/fev/2026 |
| LF45 | `02:03 - 08:03` | 02–08/mar/2026 |
| LF46 | `09:03 - 15:03` | 09–15/mar/2026 |

Todos os números foram lidos diretamente da sheet **"Comparação ML"** de cada relatório e verificados aritmeticamente (ROAS = Receita/Gasto, Margem = Receita−Gasto, Taxa Conversão = Conversões/Leads). Nenhuma inconsistência encontrada.

### 1.2 Grupos de análise

- **Eventos ML**: campanhas que otimizam para o evento `LeadQualified` do CAPI, alimentado pelos scores do modelo (decis D1–D10)
- **Controle**: campanhas convencionais do mesmo período, sem otimização por score ML
- **Coexistência** (LF40–LF44): ambos os grupos rodaram no mesmo período, permitindo comparação direta
- **Apenas ML** (LF45–LF46): 100% do budget em campanhas ML; comparação feita via ROAS Controle histórico como proxy

### 1.3 Análise contrafactual

Para os períodos com grupo Controle, calculamos:

```
Receita_CF  = Gasto_Total × ROAS_Controle
Margem_CF   = Receita_CF − Gasto_Total
Ganho_ML    = Margem_Real − Margem_CF
```

O contrafactual responde: *"se todo o orçamento do lançamento tivesse sido investido com a eficiência das campanhas Controle daquele mesmo período, qual seria a margem?"*

### 1.4 Fontes de vendas

Os relatórios consolidam vendas de múltiplas plataformas:
- **Guru** e **Hotmart**: registram o valor total do produto na venda
- **TMB** e **Asaas**: registram o valor da primeira parcela (entrada)

Para consistência, todos os valores de receita usados nesta análise são os valores rastreados reais — sem estimativas por taxa de tracking. O ROAS calculado é, portanto, conservador (subestima o real proporcionalmente à taxa de tracking de cada período).

Os scripts que geram e consolidam esses dados estão em:
- `scripts/gerar_evolucao_margem.py` — extração e geração dos gráficos
- `outputs/validation/historico/evolucao_ml_devclub_20260310_163649.xlsx` — sheet "Margem & Contrafactual"
- `outputs/validation/historico/graficos/` — gráficos gerados

---

## 2. Dados verificados por lançamento

### 2.1 Períodos com coexistência ML + Controle (LF40–LF44)

| Período | Grupo | Gasto (R$) | Receita (R$) | Margem (R$) | ROAS | Leads | Conv | TC% | CPL (R$) |
|---|---|---|---|---|---|---|---|---|---|
| LF40 | ML | 8.513 | 8.998 | +485 | 1,057 | 1.823 | 4 | 0,22% | 4,67 |
| LF40 | Ctrl | 19.465 | 17.654 | −1.811 | 0,907 | 2.708 | 8 | 0,30% | 7,19 |
| LF41 | ML | 10.290 | 37.087 | +26.798 | 3,604 | 2.216 | 17 | 0,77% | 4,64 |
| LF41 | Ctrl | 20.207 | 66.497 | +46.290 | 3,291 | 2.794 | 29 | 1,04% | 7,23 |
| LF42 | ML | 10.727 | 34.284 | +23.557 | 3,196 | 1.850 | 15 | 0,81% | 5,80 |
| LF42 | Ctrl | 22.334 | 30.996 | +8.661 | 1,388 | 2.523 | 14 | 0,55% | 8,85 |
| DEV19 | ML | 82.659 | 301.218 | +218.559 | 3,644 | 15.780 | 132 | 0,84% | 5,24 |
| DEV19 | Ctrl | 137.106 | 258.863 | +121.757 | 1,888 | 18.888 | 115 | 0,61% | 7,26 |
| LF43 | ML | 29.101 | 111.880 | +82.779 | 3,845 | 6.403 | 58 | 0,91% | 4,54 |
| LF43 | Ctrl | 52.029 | 70.534 | +18.505 | 1,356 | 8.331 | 36 | 0,43% | 6,25 |
| LF44 | ML | 32.685 | 133.005 | +100.320 | 4,069 | 11.197 | 87 | 0,78% | 2,92 |
| LF44 | Ctrl | 11.251 | 13.459 | +2.208 | 1,196 | 2.163 | 12 | 0,55% | 5,20 |

### 2.2 Períodos apenas ML (LF45–LF46)

| Período | Gasto (R$) | Receita (R$) | Margem (R$) | ROAS | Leads | Conv | TC% |
|---|---|---|---|---|---|---|---|
| LF45 | 108.445 | 248.559 | +140.114 | 2,292 | 27.553 | 201 | 0,73% |
| LF46 | 55.534 | 76.208 | +20.675 | 1,372 | 12.463 | 69 | 0,55% |

---

## 3. Teste A — O ROAS ML foi genuinamente maior?

**Resultado: Confirmado em 6/6 períodos.**

| Período | ROAS ML | ROAS Ctrl | Razão ML/Ctrl | CPL ML | CPL Ctrl | Δ CPL |
|---|---|---|---|---|---|---|
| LF40 | 1,057 | 0,907 | 1,17x | R$4,67 | R$7,19 | −35% |
| LF41 | 3,604 | 3,291 | 1,10x | R$4,64 | R$7,23 | −36% |
| LF42 | 3,196 | 1,388 | 2,30x | R$5,80 | R$8,85 | −34% |
| DEV19 | 3,644 | 1,888 | 1,93x | R$5,24 | R$7,26 | −28% |
| LF43 | 3,845 | 1,356 | 2,84x | R$4,54 | R$6,25 | −27% |
| LF44 | 4,069 | 1,196 | 3,40x | R$2,92 | R$5,20 | −44% |

**O mecanismo:** o modelo envia ao Meta sinais de leads de alta propensão (`LeadQualified` com score elevado). O algoritmo do Meta aprende a encontrar esse perfil de audiência mais eficientemente no leilão, resultando em CPL **28–44% menor em todos os períodos**. Com custo menor e taxa de conversão equivalente ou superior, o ROAS sobe estruturalmente.

**Evolução da vantagem:** nos dois primeiros lançamentos (LF40/LF41), o ROAS ML foi maior principalmente pelo CPL mais baixo — a receita por lead ML ainda era inferior à do Controle. A partir do LF42, o modelo também entrega leads com maior receita por lead: a vantagem passa a ser dupla (custo menor *e* leads melhores).

---

## 4. Teste B — ML canibaliza o Controle?

**Resultado: Sem evidência de canibalização.**

Se o aumento de budget em campanhas ML estivesse "roubando" audiência das campanhas Controle (elevando o CPM delas), o ROAS Controle deveria cair à medida que o % de budget ML aumenta.

| Período | % Budget ML | ROAS Ctrl |
|---|---|---|
| LF40 | 30% | 0,907 |
| LF41 | 34% | 3,291 |
| LF42 | 32% | 1,388 |
| DEV19 | 38% | 1,888 |
| LF43 | 36% | 1,356 |
| LF44 | **74%** | 1,196 |

A correlação de Pearson entre % budget ML e ROAS Controle é **−0,23** — próxima de zero. Para configurar canibalização real, seria necessário correlação ≤ −0,70.

O caso mais crítico é o LF44, onde o budget ML quase dobrou (36% → 74%): o ROAS Controle foi 1,196 — apenas 13% abaixo da mediana histórica dos outros períodos (1,372). Essa queda está dentro da variância amostral natural de uma campanha Controle com orçamento pequeno (R$11.251).

---

## 5. Teste C — A margem de contribuição total aumentou?

**Resultado: Sim. Ganho acumulado de R$335k vs contrafactual (+107%).**

| Período | Gasto Total | Margem Real | Margem CF* | Ganho ML | Ganho % |
|---|---|---|---|---|---|
| LF40 | R$27.978 | −R$1.326 | −R$2.603 | **+R$1.277** | +49% |
| LF41 | R$30.497 | +R$73.088 | +R$69.862 | **+R$3.226** | +5% |
| LF42 | R$33.062 | +R$32.218 | +R$12.822 | **+R$19.396** | +151% |
| DEV19 | R$219.765 | +R$340.315 | +R$195.161 | **+R$145.154** | +74% |
| LF43 | R$81.130 | +R$101.284 | +R$28.855 | **+R$72.429** | +251% |
| LF44 | R$43.936 | +R$102.528 | +R$8.623 | **+R$93.905** | +1.089% |
| **Total** | **R$436.368** | **+R$648.107** | **+R$312.719** | **+R$335.387** | **+107%** |

*Margem CF = (Gasto Total × ROAS Controle do período) − Gasto Total

**LF41 é o outlier:** o Controle teve ROAS excepcionalmente alto (3,29x), provavelmente pela sazonalidade de fim de ano. O ganho do ML foi modesto (+5%) — não porque ML foi ruim, mas porque o Controle foi excepcionalmente bom nesse período.

**LF44 é o caso mais revelador:** com 74% do budget em ML e ROAS Controle baixo (1,196x), a vantagem do ML gerou +R$94k de margem incremental — 1.089% acima do contrafactual. É também o período com maior razão ML/Ctrl (3,40x).

### 5.1 Períodos sem Controle (LF45–LF46)

Sem grupo Controle, o proxy é o ROAS Controle histórico mediano dos períodos anteriores (1,372x).

| Período | ROAS ML | ROAS Ctrl histórico | Ganho estimado |
|---|---|---|---|
| LF45 | 2,292 | 1,372 | **+R$99.801** |
| LF46 | 1,372 | 1,372 | ~R$0 (neutro) |

**LF46** é o único período em que o ML entregou ROAS equivalente ao baseline histórico de Controle. Isso pode indicar saturação de audiência após o LF45 de grande escala (R$108k de gasto, 27.553 leads), ou simplesmente condições adversas de mercado naquela semana.

---

## 6. Resumo executivo

| Teste | Pergunta | Resultado |
|---|---|---|
| A | ROAS ML foi genuinamente maior? | **Sim — em 6/6 períodos, de 1,10x a 3,40x maior** |
| B | ML canibaliza o Controle? | **Não — correlação ≈ zero (−0,23)** |
| C | Margem total aumentou? | **Sim — +R$335k vs contrafactual (+107%)** |
| D | Taxa de conversão ML maior? | **Sim em 4/6 períodos; CPL menor em todos os 6** |
| E | CPL ML maior (lead mais caro)? | **Não — CPL ML 28–44% abaixo do Controle** |

**Ganho total estimado atribuível ao ML (LF40–LF46): ~R$435k**, sobre R$338k investidos em campanhas ML. Retorno sobre o investimento em ML de aproximadamente **128%**.

---

## 7. Sinais de alerta

- **LF46 (ROAS 1,37x):** primeiro período neutro após 6 positivos. Pode ser saturação de audiência após LF45. Monitorar LF47 com atenção.
- **Tracking decrescente:** taxa de tracking caiu de ~62% (LF43/LF44) para ~44% (LF46). Parte disso é estrutural (Asaas sem UTM), mas vale monitorar se a qualidade do matching está se degradando.
- **100% ML sem referência:** a partir do LF45, não há mais grupo Controle. Sem o contrafactual direto, fica mais difícil isolar o efeito do ML de fatores externos (mercado, criativo, sazonalidade). Recomendável manter um grupo Controle pequeno para calibração.

---

## 8. Arquivos relacionados

| Arquivo | Descrição |
|---|---|
| `scripts/gerar_evolucao_margem.py` | Script que extrai dados dos relatórios e gera a análise |
| `outputs/validation/historico/evolucao_ml_devclub_20260310_163649.xlsx` | Sheet "Margem & Contrafactual" com todos os dados |
| `outputs/validation/historico/graficos/01_roas_ml_controle_total.png` | ROAS ML vs Controle vs Total por lançamento |
| `outputs/validation/historico/graficos/02_margem_real_vs_contrafactual.png` | Margem real vs contrafactual por lançamento |
| `outputs/validation/historico/graficos/03_ganho_margem_vs_contrafactual.png` | Ganho absoluto de margem atribuível ao ML |
| `outputs/validation/historico/graficos/04_budget_ml_vs_roas_total.png` | Evolução da alocação de budget e ROAS total |
| `outputs/validation/historico/graficos/05_margem_total_evolucao.png` | Evolução da margem total do negócio |
