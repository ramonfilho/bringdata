# Teto de CPL por criativo — referência técnica

*Escrito em 16/08/2026, no dia em que a entrega foi ao ar. As DECISÕES e seus
porquês vivem em `TETO_DE_CPL_DECISOES.md` (Decisões 1 a 9); este documento é o
mapa de ONDE cada coisa está: código, dados, fórmulas, testes e operação.*

---

## 1. A fórmula, e onde cada pedaço mora

O número entregue por chave (criativo ou campanha do Meta):

```
teto_cpl = conversão_esperada × fator_rastreamento × valor_por_venda ÷ 2
```

| pedaço | o que é | onde mora |
|---|---|---|
| aritmética do teto | a divisão final | `src/monitoring/teto.py::teto_cpl` |
| funil único de montagem | aplica fator, valor, ROAS e carimbos; TODO teto nasce aqui | `teto.py::CalculadoraDeTeto._monta` |
| conversão da campanha | mistura de decis DOS LEADS da chave, ponderada pela conversão de cada decil na referência | `teto.py::CalculadoraDeTeto.por_mistura_de_decis` |
| conversão da unidade (criativo×campanha) | Decisão 9: `cm × (peso × lift + (1−peso))`, `peso = n/(n+K)`, K=2.000 | `teto.py::conversao_prevista_da_unidade` (K em `K_HISTORICO_CRIATIVO`) |
| composição por chave | unidade é a ÚNICA conta; criativo e campanha são as duas agregações dela ponderadas por leads (metodologia fixada em 16/08: campanha = decis + criativos, nunca decis puros) | `src/monitoring/teto_por_chave.py::tetos_por_chave`, `_conv_composta_da_unidade` |
| porta da conversão composta | entra no MESMO funil, sem conta paralela | `teto.py::CalculadoraDeTeto.de_conversao_medida` |
| fator de rastreamento | MEDIDO toda segunda na própria janela: `(casadas + sumidas) ÷ casadas`; só a venda "sumida" (não existe em cadastro nenhum) corrige — 84% das não-casadas são gente conhecida de outro funil e NÃO corrigem | `src/monitoring/rolling_reference.py::fator_de_rastreamento` (faixa de alerta `FATOR_RASTREAMENTO_FAIXA`), gravado em `conversion.tracking` no payload |
| valor por venda | mistura real cartão(R$2.000)/boleto(R$1.000) das vendas da janela | `teto.py::value_per_sale_from_sales`, gravado em `conversion.economics` |
| ROAS alvo = 2 | política de negócio (Decisão 2) | `teto.py::ROAS_ALVO_PADRAO` |
| carimbo de proveniência | referência + fator + commit + config em cada Teto; vira a coluna `teto_referencia` | `teto.py::Teto` (campos), `teto_por_chave.py::carimbo` |

## 2. Os dados: papel e origem de cada tabela

| tabela | papel | quem escreve |
|---|---|---|
| `analytics.launch_calendar` | calendário canônico dos lançamentos (cap_start/cap_end/vendas_start/vendas_end); define a janela de compra de cada lead | job diário 05:30 (planilha PC FORMULÁRIOS) |
| `analytics.captacoes` | leads com utm_content/utm_campaign/email/phone/captured_at; base dos históricos e testes | ingestão contínua |
| `analytics.sales` | vendas dos 5 gateways; casamento por email/telefone | `ingestion-sales-daily` |
| `public.registros_ml` (ledger) | decil/score por lead, DUAS duplas de colunas (champion/challenger) casadas por run_id | consumer Pub/Sub |
| `public.scores_historicos` | PONTE congelada: a régua abr_28 do passado (pré-cutover 23/05); recuperou a cobertura de decil de 21%→73% nos testes | congelada |
| `analytics.reference_rolling` | a referência semanal: conversão por decil/canal/balde + economia + `tracking` (fator) + `conversion_window` (regra do calendário) | job `refresh-rolling-reference` (seg 06:30 UTC) |
| `analytics.criativo_historico` | memória por criativo: leads/compradores/esperados maduros (lançamentos FECHADOS, folga de 2 dias p/ ingestão) + `prior_conversao`/`prior_fonte` (o slot do TEXTO, que o refresh NUNCA sobrescreve) | mesmo job semanal (`src/data/criativo_historico.py`) |
| `analytics.ad_insights` | gasto/impressões/cliques POR ANÚNCIO por dia (Meta, level=ad, dia a dia), retroativo a 01/11/2025 | `scripts/ingest_ad_insights.py` (rodada diária a agendar) |
| `analytics.criativo_id_map` | nome ↔ ad_id (da mesma resposta da Meta); resolve utm_content numérico (macro falhou) | idem |
| `public.scores_inbound` (Supabase da agência) | A ENTREGA: nota de qualidade + `teto_cpl`/`teto_roas_alvo`/`teto_referencia` por criativo e por campanha, 4 janelas rolantes (90 dias, 7 dias, 3 dias, hoje) | job `push-scores-zanelato` (hora em hora, :22) — `scripts/push_scores_zanelato.py` |

Regras de contagem que valem em TUDO (referência, histórico, testes):
a compra pertence ao lançamento em que o lead entrou — conta da captação até o
`vendas_end` dele (`src/data/matured_window.py::compra_conta_para_o_lead`,
`limites_de_compra`); a régua se busca pelo run_id NAS DUAS duplas de colunas do
ledger (fix #204, `matured_window.py` `ledger_sql`); lead de janela aberta fica
fora da referência (`rolling_reference.py::_aplica_janela_do_calendario`).

## 3. Os testes, as métricas escolhidas e por quê

**3.1 Trava de ordenação** — `scripts/trava_ordenacao_teto.py` (portão da Decisão 7;
roda antes de popular e antes de cada mudança no valor entregue; exit code gate).
Julga ORDEM e não nível porque, dentro de um lançamento, fator e valor por venda
multiplicam todas as unidades igualmente (cancelam), e ordem é a decisão do gestor.
Métricas e motivo: Spearman por lançamento (a fila prevista bate com a real?);
"aponta o melhor da campanha" contra CHUTE DE 29% (escolha de 3-4 faces, não
moeda); "apontado no top-2" e "evita o desastre" (as duas versões tolerantes a
célula pequena); terços empilhados (robusto a unidade com zero comprador).
Resultado 15/08 (referência viva): modelo +0,283 · composto +0,401 (p=0,009) ·
terços 1,70x → 2,34x · evita desastre 96%. O composto está a ~106% do teto de
ruído (máximo mensurável com este volume de compradores por unidade).

**3.2 Assertividade com caixa real** — `scripts/assertividade_teto.py` (o script
versionado é O MESMO que produziu os números publicados, para reprodutibilidade).
Grão criativo×campanha com gasto REAL de `ad_insights`. TUDO fora do tempo: mapa
de conversão, valor por venda, fator e histórico do criativo reconstruídos só com
lançamentos anteriores ao julgado (janela de época de 90d, a mesma da produção).
Por que duas leituras: DISCRIMINAÇÃO dentro do lançamento (pagou-abaixo vs
pagou-acima do MESMO lançamento — imune à maré; num lançamento todo ruim vira
"quem perdeu menos") e CALIBRAÇÃO entre lançamentos (o nível acompanha as épocas;
Spearman −0,05 = em dia). A matriz simples só aparece por lançamento, nunca
agregada crua (um lançamento inteiro ruim enganaria a matriz global).
Resultado final 16/08: 483 unidades, 25 lançamentos, R$ 1.333.245 auditados;
dentro do teto 60% batem ROAS 2 (ROAS médio 2,52, ponderado por gasto) × fora
23% (1,18); melhor em 20/21 lançamentos; Wilcoxon p<0,001.
Funil de cobertura: 538 unidades 100+ leads → 14 sem época → 7 sem decil → 34
sem gasto casado → 483. Cobertura de decil: ledger + ponte = 73% (LF40-42 ficam
em 17%; fontes externas de nov/2025 são polimento possível).

**3.3 Paridade local×nuvem** — `push_scores_zanelato.py --dump-parity` imprime
cada linha calculada; o job-ensaio `push-scores-ensaio` (clone do real, imagem
nova, zero escrita) roda o mesmo na nuvem; comparação por chave exige carimbo
idêntico e |Δteto| ≤ R$0,01. Por que existe: pega diferença de AMBIENTE (imagem,
env, referência), a classe de bug que testes unitários não veem. Resultado
16/08: 48/48 idênticas.

**3.4 Números publicados (16/08, SEM o sinal de texto)** — headline: "60% batem
dentro (ROAS 2,52) × 23% fora (1,18)"; exemplos por lançamento: LF56 17 unidades
dentro ROAS 2,97 × 4 acima 0,55; LF50 71% dentro (3,10) × 8% fora (1,18).
Obrigatório re-medir com o texto quando ele entrar.

## 4. Como o gestor de tráfego lê e usa (consumo)

Onde: `public.scores_inbound` no Supabase da agência (o painel deles lê dali),
atualizada de hora em hora no minuto :22. Chave única `(tipo, chave)`.

| coluna | leitura do gestor |
|---|---|
| `tipo` | **`criativo_campanha` = O GRÃO DO PRODUTO e a linha principal do gestor** (chave "anúncio @ campanha"; o mesmo anúncio tem um teto por campanha). `criativo_conjunto_campanha` (18/08) = o split por PÚBLICO (chave "anúncio @ conjunto @ campanha", conjunto = utm_medium = {{adset.name}}); só aparece quando o anúncio roda em 2+ conjuntos nomeados na MESMA campanha - com 1 conjunto a linha criativo_campanha já é o número exato. `criativo`/`campanha` = agregados. GOOGLE (18/08): a campanha real não viaja na UTM (chega 'devlf'), então a linha criativo_campanha de anúncio Google usa a campanha REAL buscada no Google Ads (criativo_id_map.campaign_name) - cada ID é uma colocação com teto próprio; o agregado `criativo` e o histórico/lift seguem por vídeo. SUFIXOS = a ESCADA DE JANELAS ROLANTES (19/08, Decisão 11), todas terminando HOJE e sem nenhum grampo de lançamento: sem sufixo e `_historico` = 90 dias (a mesma conta, o sem-sufixo é cópia reetiquetada pra não quebrar quem já lê `tipo='criativo'`); `_7dias`; `_3dias`; `_hoje` = só quem cruzou 100 leads no próprio dia. Virada de LF não zera mais ninguém: anúncio que estreou de fato não cruza o piso e só aparece quando merecer. MOEDA (18/08): teto de linha Meta sai convertido pra leads do GERENCIADOR (Decisão 10; selo `ger`/`ger_agg`/`moeda_real` no teto_referencia) |
| `chave` | nome do anúncio/campanha (ou "anúncio @ campanha" nas unidades). Anúncio do GOOGLE leva prefixo `[G]` (resolvedor via Google Ads API v22, PR #212); dois anúncios com o mesmo nome fundem por soma ponderada de leads (PR #214) |
| `teto_cpl` | pague até ISTO por lead desta chave pra dobrar o dinheiro |
| `teto_roas_alvo` | a meta embutida no número acima (2,0) |
| `teto_referencia` | o selo: qual referência+fator+commit geraram o número, ou o MOTIVO de não haver teto |
| `pct_top20`/`delta_vs_referencia` | a nota de qualidade do público que já existia antes |

Uso no dia a dia: comparar o CPL do gerenciador com o `teto_cpl` da linha
correspondente. Abaixo com folga = margem pra escalar; acima = reduzir lance/
orçamento ou trocar criativo. Linha sem teto = ler o motivo no selo (quase sempre
volume < 100 leads). O guia em linguagem do gestor está na doc do cliente
(artifact "Teto de custo por lead", seção "Como usar no dia a dia").

## 4b. Operação

| ação | comando/mecanismo |
|---|---|
| referência semanal (+fator +histórico por criativo) | job `refresh-rolling-reference`, seg 06:30 UTC; manual: `python -m scripts.refresh_rolling_reference [--dry-run]` |
| entrega de hora em hora | job `push-scores-zanelato` (:22); `--check` mostra sem escrever; `--dump-parity` alimenta o portão |
| ingestão por anúncio | `python -m scripts.ingest_ad_insights [--backfill INI FIM]` (diária A AGENDAR) |
| portões antes de mudar o valor entregue | `python -m scripts.trava_ordenacao_teto` (exit!=0 reprova) + paridade 3.3 |
| flip executado em 16/08 | job do push → imagem `v20260815_151525` (digest 07edfe37…) + `deploy-gate.sh promote --revision smart-ads-api-01073-dah` |
| rollback | job: apontar de volta o digest anterior; serviço: comando impresso pelo gate no promote |

Pendências conhecidas: agendar a ingestão diária por anúncio; migrar
`criativo_historico`/push de nome→ad_id (o mapa já existe); dia 06/04 com gasto
por anúncio ≠ por campanha (investigar); LF40-42 com decil magro.
