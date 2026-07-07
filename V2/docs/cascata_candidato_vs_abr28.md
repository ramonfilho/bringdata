# Cascata candidato × abr28 — checklist de testes

## Testes executados

| # | Teste | Executado | Métricas | Conclusão |
|---|---|---|---|---|
| 1 | Threshold de missing 20% | cutoff 15% → 20% (deixar `tem computador` passar) | AUC 0.716 vs 0.715 | Nulo — a feature já entrava a 15% |
| 2 | Candidato full-history (sem pesos) | todas as vendas, sem `--max-date`, sem pesos | AUC 0.716 · Lift 3.0x · Top3 60% · mono 100% | Base para o backtest |
| 3 | Backtest out-of-sample LF56/57/58 | candidato × abr28 nos 3 lançamentos não vistos | Top-30%: **45% vs 67%** · compradores no D10: **13 vs 17** | **abr28 vence** — candidato não superou |

## Testes a executar (ordem da cascata)

| # | Teste | A executar | Métricas | Conclusão |
|---|---|---|---|---|
| 4 | Candidato full-history **com pesos** | mesma config do #2 + buyer weights | — | — |
| 5 | Recency 6 meses (com pesos) | dados ~jan/26+, com pesos | — | — |
| 6 | Outubro **sem** `tem computador` | dados out/25+, feature removida | — | — |
| 7 | Outubro + todas as features | dados out/25+ forçado | — | — |
| 8 | Tratamento: categoria "Não Respondeu" | missing de `tem computador` → categoria própria | — | — |
| 9 | Tratamento: remover leads sem a pergunta | dropar leads sem `tem computador` | — | — |
| 10 | Tuning de hiperparâmetros | grid no melhor candidato | — | — |

## Pendências (nesta ordem, antes de continuar a cascata)

### 1. Paridade de dados SQL × fontes anteriores — bit-to-bit  (cobertura atual: **PARCIAL**)
Comparar o SQL montado (`analytics.leads` / reconstrução `train_unified`) contra as fontes
anteriores (Sheets = `train_pesquisa`; Railway = `lead_legado`/`leads_historico`; ledger =
`registros_ml`), por período:
- [ ] **Nomes das colunas** — inventário completo 1:1 (mapeando camelCase / snake_case / texto-pergunta)
- [ ] **Tipos de dado** por coluna
- [ ] **Conteúdo bit-to-bit** de TODAS as colunas (join por e-mail), não só as já checadas
- [ ] **Contagem de registros por período** (mês/LF) — SQL vs cada fonte no mesmo recorte

*Feito:* auditoria `train_unified × train_pesquisa` (255.410 submissões 1:1) — **veredito FIEL**:
0 leads perdidos, campos estáveis 100%, `interesse`/`investiu` 100% + 119k recuperados; diferenças
de idade/salário/cartão/ocupação = formato/rótulo que o `core` canonicaliza (verificado com
`core.unify_categories`: salário 100%, ocupação 95,5% + respostas legítimas distintas).
*Feito (nível ATÔMICO):* rodado o próprio pipeline com o novo flag `--export-pesquisa` (captura o
`df_pesquisa_unificado` — todas as fontes atômicas + dedup cross-source). Fontes atômicas de Leads:
36 `.xlsx` locais + Google Sheets Produção/Backup (ao vivo) + Railway `Lead` (LIVE, 142.943 — **não
está anulada**, só o score/decil foram zerados). Resultado: reproduz o `train_pesquisa` EXATO
(267.677, proveniência idêntica: Railway 130.248 + Sheets 59.726 + xlsx 77.703) e **todos os 267.514
leads estão no `train_unified`** (0 perdidos); o `train_unified` é isso + 40.040 leads novos do ledger.
*Correção:* a `Lead` do Railway NÃO está vazia (memória dizia 142.940→0 — era só score/decil).
*Falta (opcional):* auditoria de conteúdo direta contra `registros_ml` (ledger vivo).

### 2. Integridade dos dados do backtest
- [ ] Explicar o gap de vendas (casou 35/19/19 compradores, abaixo das vendas reais dos LFs) — fonte/janela/matching/respondentes

### 3. Priorização dos experimentos
- [ ] Ordenar os testes 4–10 do **mais provável ao menos provável** de aumentar performance

### Reconstruir escopo de "controle"
- [ ] champion/challenger/controle tiveram vários nomes ao longo do tempo — definição única e datada antes de usar pesos de grupo de controle

## Notas

- Regra travada: candidato e abr28 sempre no **mesmo tratamento** do `tem computador`.
- Todos os testes a executar são re-scoreados nos mesmos LF56/57/58.
- Run IDs — jan30: `d51757f5…` · abr28: `5d158f0a…` · candidato fresco: `3112d794…`
