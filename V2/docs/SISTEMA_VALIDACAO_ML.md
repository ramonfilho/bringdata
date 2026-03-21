# Sistema de Validação ML

**Atualizado:** 2026-03-17

---

## 1. OBJETIVO

Medir se campanhas Meta Ads com ML (lead scoring via `LeadQualified` CAPI) geram melhor ROAS que campanhas sem ML, e acompanhar a evolução por lançamento.

---

## 2. FONTES DE DADOS

### Leads
| Fonte | Período | Como é carregada |
|-------|---------|-----------------|
| Google Sheets (Produção + Backup) | LF01–LF45 | `load_leads_from_sheets()` |
| Cloud SQL backup (SQL) | até 2026-02-17 | Parse direto do `.sql` |
| Railway PostgreSQL | a partir de 2026-02-18 | `pg8000` direto |
| `[LFxx] Leads.xlsx` em `outputs/validation/` | por período | Auto-detecção por datas |

### Vendas
| Fonte | Detecção | Filtro de status |
|-------|----------|-----------------|
| **Guru API** | `GURU_DATA_SOURCE=api` (padrão) | Aprovada (+ Cancelada se fechamento) |
| **HotPay** (a partir do LF46) | Colunas: `chave` + `Data de Confirmação` + `Código do Produto` | Aprovado |
| **TMB** (contas a receber) | Colunas: `Pedido` + `Parcela` + `Grau de risco` | Efetivado |

> **LF46 em diante:** DevClub migrou para HotPay. Guru continua ativo mas com produtos legados/upsells não relacionados ao lançamento.

### Meta Ads
- Dados de gasto e leads via Meta API (contas `act_188005769808959` + `act_786790755803474`)
- Cache habilitado por padrão; usar `--no-cache` para forçar atualização

---

## 3. MATCHING LEADS → VENDAS

1. **Email exato** (normalizado: lower + strip)
2. **Telefone completo** (fallback se email não bater)
3. Sem validação temporal (modo análise de resultados — `use_temporal_validation=False`)

**Tracking rate histórico:** ~55–62%. Abaixo de 30% indica problema de dados.

---

## 4. ROAS — METODOLOGIA

| Métrica | Cálculo | Uso |
|---------|---------|-----|
| **ROAS Traqueado** | receita matched / gasto | Nunca reportar ao cliente — subestimado |
| **ROAS REAL Estimado** | receita_traqueada / tracking_rate | Reportado no relatório |
| **ROAS Total** | (receita ML + receita Ctrl) / gasto total | Visão global do período |

> **Importante:** ROAS Ajustado TMB foi removido de todos os relatórios (era confuso e gerava margens negativas sem documentação clara).

---

## 5. CLASSIFICAÇÃO DE CAMPANHAS

| Grupo | Critério |
|-------|---------|
| **Eventos ML** | Nome contém "MACHINE LEARNING" ou "\| ML \|" **E** usa `LeadQualified`/`LQHQ` |
| **Controle** | Não contém "MACHINE LEARNING" ou "\| ML \|" |

> A partir do LF45, praticamente 100% do budget está em campanhas ML. Quando não há Controle, a coluna aparece com "—" no relatório.

---

## 6. ESTRUTURA DO RELATÓRIO EXCEL (4 abas)

### Aba 1: Performance Geral
Contexto do período: leads, vendas totais, vendas identificadas, % tracking, gasto total, **ROAS Total**.

### Aba 2: Comparação ML
Tabela ML vs Controle com:
- Leads, Conversões (Real Estimado + Traqueado), Taxa Conversão
- Receita (Real + Traqueada), Gasto, CPL
- **CPA** ← adicionado
- ROAS (Real + Traqueado)
- Margem
- **ROAS Total** ← adicionado
- Quando sem Controle: coluna aparece com "—" + nota de rodapé

### Aba 3: ML Monitoring
Saúde do modelo: AUC produção vs test set, concentração por decil, distribuição.

### Aba 4: Detalhes das Conversões
Todas as 62 vendas do período (trackeadas e não-trackeadas), com: email, telefone, campanha, grupo, data captura, data venda, valor, fonte (guru/hotpay/tmb).

---

## 7. COMO RODAR

```bash
# Rodar da pasta raiz smart_ads/
python V2/src/validation/validate_ml_performance.py \
  --config V2/configs/validation_config.yaml \
  --start-date 2026-02-24 \      # início captação
  --end-date 2026-03-03 \        # fim captação
  --sales-start-date 2026-03-09 \
  --sales-end-date 2026-03-15

# Flags opcionais:
#   --no-cache         força recarregar Sheets e Meta API
#   --report-type pos-devolucoes   (padrão: fechamento)
```

**Atenção:** o script deve ser rodado de `smart_ads/` (pai de `V2/`). O path `V2/data/devclub` é relativo a esse diretório.

---

## 8. DETECÇÃO AUTOMÁTICA DE ARQUIVOS

Todos os arquivos em `V2/data/devclub/` são inspecionados por estrutura de colunas:

```python
# TMB
'Pedido' in cols and 'Parcela' in cols and 'Grau de risco' in cols

# HotPay
'chave' in cols and 'Data de Confirmação' in cols and 'Código do Produto' in cols
```

Arquivos `*.xls` e `*.xlsx` são ambos detectados.

---

## 9. ARQUIVOS RELEVANTES

```
V2/src/validation/
  validate_ml_performance.py   # script principal
  data_loader.py               # carrega leads (Sheets/Railway) e vendas (Guru/HotPay/TMB)
  matching.py                  # matching email + telefone
  metrics_calculator.py        # ROAS, CPA, margem por campanha
  report_generator.py          # geração do Excel (4 abas)
  guru_sales_extractor.py      # Guru API

V2/outputs/validation/
  {DD:MM - DD:MM}/             # relatório por período de vendas
  historico/
    cpa_historico.csv          # evolução de CPA por lançamento
    evolucao_ml_devclub_*.xlsx # ROAS ML vs Controle histórico
```

---

## 10. HISTÓRICO DE LANÇAMENTOS

| Lançamento | Vendas | Track% | ROAS ML | ROAS Ctrl | ROAS Total |
|-----------|--------|--------|---------|-----------|------------|
| LF40 | 72 | 18% | 5.85x | 5.70x | 5.75x |
| LF41 | 104 | 45% | 8.45x | 7.28x | 7.68x |
| LF42 | 54 | 57% | 5.96x | 2.60x | 3.69x |
| DEV19 | 406 | 58% | 5.60x | 2.29x | 2.24x |
| LF44 | 134 | 63% | 6.97x | 0.89x | 2.29x |
| LF45 | 93 | 62% | 6.61x | 3.19x | 4.70x |
| LF45b | 164 | 56% | 3.43x | — | 3.43x |
| **LF46** | **62** | **55%** | **2.17x** | **—** | **1.49x*** |

> *LF46: ROAS Total calculado sobre receita real HotPay (R$96k / R$64k). LF40–LF45b: estimado por extrapolação do tracking rate.
