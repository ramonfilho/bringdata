# Entrega de dados para o gestor de tráfego — as duas fontes

Existem **duas** formas de a gente entregar banco de dados para a agência que gerencia o
tráfego (Zanelato). Elas fazem a mesma coisa por caminhos opostos, e **só uma está
ligada**. Este documento existe porque as duas dividem código, e mexer numa sem saber da
outra quebra a que ninguém estava olhando.

Última verificação contra produção: **2026-08-11**.

| | Fonte A — banco `dash` | Fonte B — Supabase deles |
|---|---|---|
| **Onde mora o banco** | nosso Cloud SQL | Supabase deles (AWS sa-east-1) |
| **Quem conecta em quem** | eles leem o nosso | nós escrevemos no deles |
| **Estado** | 📐 **TEMPLATE de onboarding** (não roda, não apagar) | ✅ **no ar** |
| **Script** | `V2/scripts/provisiona_dash_zanelato.py` | `V2/scripts/push_supabase_zanelato.py` |
| **O que dispara** | cron `dash-zanelato-refresh-daily` (PAUSADO) | 4 jobs do Cloud Run |
| **Tabelas de destino** | `dash.leads_2026`, `dash.qualidade_por_anuncio` | `public.leads_inbound`, `public.scores_inbound` |
| **De onde LÊ** | 3 tabelas + calendário + vendas | **só `analytics.captacoes`** |
| **Colunas de lead** | 27 | 11 |
| **Janela** | ano de 2026 inteiro | últimos 90 dias |

---

## Por que existem duas

A Fonte A foi a primeira: criamos um banco no nosso Cloud SQL, com um usuário só de
`SELECT`, e eles conectariam de fora. Funcionou do nosso lado e **nunca funcionou do
lado deles**. A causa não foi permissão nem bloqueio de IP: a ferramenta deles não
conseguia configurar o TLS contra o Cloud SQL, cujo certificado é de autoridade interna
e não fecha cadeia com raiz pública.

A Fonte B inverteu o sentido. Quem conecta passa a ser o nosso cliente, que a gente
controla, e o problema deixa de existir em vez de ser contornado. De quebra desaparece a
credencial de leitura na nossa base.

**Ironia registrada:** o certificado do pooler do Supabase **também** não fecha cadeia
com raiz pública. A conexão daqui falha com `CERTIFICATE_VERIFY_FAILED` se o contexto
verificar. O `sslmode=require` que eles pediram significa "criptografa e não verifica",
que é o mesmo conselho que a gente havia dado a eles.

---

## Fonte A — banco `dash` no nosso Cloud SQL (desligada)

**Script:** `V2/scripts/provisiona_dash_zanelato.py`

Reconstrói a tabela inteira uma vez por dia. Entrega 27 colunas por lead, incluindo
coisas que a Fonte B não manda: `lead_id` (hash do e-mail), `lf` (a qual lançamento a
data pertence), `comprou`, as 9 perguntas da pesquisa e as colunas de grupo de WhatsApp.

Também mantém `dash.qualidade_por_anuncio`, com **qualidade agregada por criativo**, 95
linhas. Agregado, com mínimo de 30 leads por linha. Nunca score por lead.

**Estado: TEMPLATE DE ONBOARDING.** O cron está pausado e o banco não roda mais para a
Zanelato. Decidido em 12/08/2026 que ele **FICA**, e a razão não é nostalgia:

Este é o único lugar do projeto que sabe **provisionar uma entrega de dados para um cliente
do zero** — cria banco separado, papel somente-leitura, tabela, e traz um teste de aceitação
(`--aceitacao`) que PROVA o isolamento tentando ler cada tabela proibida e exigindo
`permission denied` em todas, antes de qualquer credencial sair daqui.

E ele resolve por construção um problema que uma view não resolve: todo banco Postgres tem um
catálogo de si mesmo legível por qualquer role que consiga conectar, e o catálogo mostra nome
de coluna. Uma view protegeria os dados e ainda deixaria o cliente ver que existem colunas
chamadas `lead_score` e `decil`. Banco separado tem catálogo separado.

Quando o segundo cliente chegar, é daqui que se parte. Por isso o rótulo é **template** e não
"desligada": "desligada" convida alguém a apagar.

Se a Fonte B tiver problema, religar continua sendo despausar um cron.

---

## Fonte B — Supabase deles (no ar)

**Script:** `V2/scripts/push_supabase_zanelato.py`

Quatro jobs do Cloud Run. **A ordem dos dois primeiros importa:**

| Job | Quando | O que faz |
|---|---|---|
| `captacoes-ingest-railway` | 5 min | Railway → nossa `captacoes` (`ingest_captacoes_railway.py`) |
| `zanelato-supabase-incremental` | 5 min, **depois** | nossa `captacoes` → Supabase deles |
| `zanelato-supabase-podar` | 1x/dia | apaga o que passou de 90 dias |
| `zanelato-supabase-auditar` | 1x/dia | conta as duas pontas por mês e **avisa no DM** |

Se a entrega rodar antes da ingestão, ela manda o estado velho e o lead novo só chega na
rodada seguinte.

Existe um quarto modo, `--full`, que manda os 90 dias inteiros. Não tem cron: é para a
primeira carga e para recuperação.

### A marca d'água vem do destino

`max(recebido_em)` na tabela deles é o horário da **nossa** última gravação, porque a
coluna tem default `now()`. Isso evita criar tabela de controle (não temos permissão de
criar nada no schema deles) e, se eles truncarem a tabela, a marca desaparece junto e a
próxima rodada percebe em vez de continuar de um ponteiro que não vale mais.

A janela tem **folga** em vez de ser marca exata, porque marca exata perde linha quando
os relógios discordam ou quando uma rodada falha e a seguinte avança o ponteiro.

### O upsert é na mão, e isso não é preguiça

A chave primária da tabela deles é `id` sequencial, e **não existe restrição de
unicidade em (email, data)**. Então `INSERT ... ON CONFLICT` não tem em que conflitar. O
upsert apaga as chaves do lote e insere o lote.

> **Pedido em aberto para eles:** `CREATE UNIQUE INDEX ON public.leads_inbound (email, data)`.
> Uma linha, dispensa o apaga-e-insere e fecha a porta da duplicação.

**Limite que morde em toda mudança:** o `DELETE` é escopado em (email, data). Se uma
mudança nossa alterar o **valor** de `data`, a linha com a data antiga fica órfã ao lado
da nova e o lead aparece duas vezes. Toda mudança que mexa em `data` exige uma `--full`
logo depois do deploy. Aconteceu no conserto de fuso de 10/08/2026, que mudou ~12% das
linhas.

### A data sai em horário de Brasília

Até 10/08/2026 ela saía em UTC, e a agência compara essa coluna com a planilha de leads
dela e com o painel da Meta, os dois em Brasília. O sintoma foi um "leads faltando" que
não existia: ela apontou 15 leads do dia 09/08 ausentes, 14 estavam lá datados 10/08, e
os 14 chegaram entre 21:05 e 23:55 de Brasília do dia 09.

O UTC não estava escrito no código: a conexão tem `TimeZone = UTC` e
`to_char(timestamptz, ...)` renderiza no fuso da **sessão**. Vinha do ambiente.

A fronteira dos 90 dias usa o **mesmo** fuso da coluna. Fronteira num fuso e valor em
outro faria a linha da borda entrar na carga e sair na poda a cada rodada, para sempre,
sem erro nenhum aparecendo.

---

## De onde saem os dados (Fonte B) — mudou em 11/08/2026

**UMA tabela: `analytics.captacoes`.** Nada mais.

```
Railway (Client LEFT JOIN UTMTracking)
         ↓  scripts/ingest_captacoes_railway.py   (job, 5 min)
   analytics.captacoes          ← a nossa tabela, uma linha por INSCRIÇÃO
         ↓  scripts/push_supabase_zanelato.py     (job, 5 min, logo depois)
   Supabase deles: public.leads_inbound
```

A ordem dos dois jobs importa: se a entrega rodar antes da ingestão, ela manda o estado
velho e o lead novo só chega 5 minutos depois.

### Por que uma fonte só

Antes eram TRÊS somadas num `UNION` com desempate por prioridade (`analytics.leads` para
respondente, `analytics.cadastros` para não-respondente, o ledger `registros_ml` para o lead
do dia), com a consulta herdada da Fonte A. Funcionava, e era difícil de explicar: a mesma
coluna podia vir de três lugares com regras diferentes, e responder "de onde saiu este lead"
exigia ler três braços.

### E SEM enriquecimento na hora de entregar

**Regra do cliente:** se o dado falta no lead, ele falta na tabela da agência. A versão
anterior preenchia `utm_url` de fontes de fora (o ledger, a `lead_legado`, a repescagem de
backup) no momento de entregar.

O motivo de tirar: remendo na entrega faz a tabela do cliente parecer melhor do que o dado
é, e esconde o que precisa ser consertado na origem. Foi assim que a falha de cobertura do
front em 05-06/08/2026 apareceu. **Completar dado é trabalho da INGESTÃO**, dentro da
`captacoes`, num lugar só e igual para todo consumidor —
`scripts/completa_url_captacoes.py` faz isso para a `utm_url` do histórico.

### O grão: uma linha por inscrição, e o limite honesto dele

A chave da `captacoes` saiu de `(lf, chave)` para `(lf, chave, origem_id)`. Era a chave
antiga que PROIBIA a mesma pessoa duas vezes no mesmo lançamento.

`origem_id` é `NOT NULL` de propósito: em Postgres dois NULL **não** conflitam num índice
único, então discriminador nulável faria a ingestão reinserir as mesmas linhas para sempre,
sem erro nenhum.

Mas o Railway só registra recadastro parcialmente:

| tabela | linhas por pessoa | |
|---|---|---|
| `Client` | **1,00** | não sabe dizer que alguém se inscreveu duas vezes |
| `UTMTracking` | 1,06 | 7.328 pessoas com 2+ eventos, cada um com data e UTM |

Então "uma linha por inscrição" é, na prática: pessoa com N eventos → N linhas; pessoa sem
evento → 1 linha com UTM nula. É o teto da fonte, não uma escolha.

**Efeito prático medido:** no backfill de 04 a 11/08, 1.936 linhas para 1.923 pessoas
(1,007 por pessoa). O recadastro aparece mais ENTRE lançamentos, que a chave antiga já
permitia. Quem muda a contagem para a agência é o **não-respondente**, não o recadastro.

### `SEM_LF`: a sentinela de quem cai entre lançamentos

`lf` sai do calendário por data de captação e é `NOT NULL`. Existe cadastro FORA de qualquer
janela: 04 a 06/08/2026 cai entre o fim do DEV21 (03/08) e o início do LF64 (07/08), e são
377 leads. Eles entram com `lf = 'SEM_LF'`, não descartados — a agência pagou por eles.

### A folga da janela é de HORAS, e o número é medido

Atraso da `UTMTracking` em relação ao `Client`, sobre 36.621 cadastros de 30 dias:

| quando a UTM chegou | |
|---|---|
| antes ou junto | 0,2% |
| até 1 HORA | **98,3%** |
| entre 1h e 48h | **0,0%** |
| depois de 48h | 6 casos em 36.621 |
| nunca | 1,6% |

Por isso a folga da ingestão é de 2 horas. A primeira versão usava 48, que era chute e
errava por um fator de 48.

> **CUIDADO ao ler cobertura baixa como atraso.** Os cadastros dos últimos 7 dias apareciam
> com 78,2% de UTM contra 98,4% nos de 30 dias, e é tentador aumentar a folga. Não era
> atraso: por semana, a taxa SEM nenhuma UTM ficou entre 0,2% e 1,7% durante oito semanas
> (01/06 a 27/07) e saltou para 8,4% em 03/08 e 5,4% em 10/08. Degrau, não curva: falha de
> cobertura no front. **Folga nenhuma conserta dado que nunca foi gravado.**

### Sem teto por rodada, com AVISO

Cronometrado contra o Railway: 1 dia = 639 registros em 3,7s; 8 dias = 2.558 em 3,0s;
**30 dias = 39.684 em 6,6s**. Um atraso catastrófico de 30 dias cabe em 7 segundos de um
limite de 600 — o caso está 85x longe, e código para problema que não existe é código que
ninguém testa.

O que existe é o aviso: a rodada reporta quanto do orçamento de tempo usou e **reclama acima
de 50%**. Sem ele, estourar seria silencioso — o job morre, a transação é desfeita, a marca
não avança e a rodada seguinte tenta o mesmo volume.

### A trava de concorrência

Cron de 5 minutos com rodada de 6 não espera a anterior: o Cloud Run dispara as duas.
`pg_try_advisory_lock` no banco DELES, porque é o único ponto que as duas têm em comum, e
lock de SESSÃO porque morre com a conexão — job morto não deixa cadeado órfão.

**Não há cascata:** rodada pulada não acumula, porque a seguinte parte da marca que a
anterior deixou. E rodada pendurada é morta pelo `timeoutSeconds=600` do job.

### Os dois relógios

A janela sai de `max(recebido_em)` da tabela DELES e filtra `ingested_at` na NOSSA. São dois
relógios: se o deles estiver adiantado, a janela começaria no futuro em relação ao nosso
carimbo e pularia linhas em silêncio. Medido: **+2,5 segundos** de diferença contra 360s de
folga, 144x de margem.

### `ingested_at` NÃO é a data do lead

`captured_at` é a data fiel da entrada, e é ela que vai na coluna `data`. `ingested_at` é o
carimbo da NOSSA escrita, e é por ele que o incremental filtra — um lead de ontem cuja UTM
chegou hoje tem `captured_at` de ontem, e filtrando pela data do lead ele nunca mais seria
reenviado, ficando sem campanha para sempre.

### O que ainda falta em tempo real

`Client.hasComputer` **parou de ser gravado pelo front**: 13% em maio, **0,0% em junho,
julho e agosto**. Não está escondido em JSON (procurado em `Activity.metadata`,
`Client.device` e no log do payload cru: zero menções a "comput" em 30 dias de payload).

O dado CHEGA no nosso webhook (no ledger é 100%), então o front tem a informação. **Pedido
aberto:** voltar a preencher `Client.hasComputer` e não remover a coluna. Do nosso lado nada
muda: `leads_unify` já lê de lá.

## O acoplamento entre as duas (leia antes de mexer)

`push_supabase_zanelato.py` **importa `sql_fonte()` de `provisiona_dash_zanelato.py`**.
Uma definição, duas entregas. A razão é boa: duas definições da mesma entrega divergem com
o tempo, alguém conserta uma e esquece a outra, e o sintoma aparece como coluna trocada no
painel do cliente.

O preço é que a Fonte B arrastava o trabalho inteiro da Fonte A. Medido por `EXPLAIN` em
10/08/2026, a consulta calculava e jogava fora `lead_id`, `lf`, `comprou`,
`entrou_no_grupo`, `grupo_whatsapp` e 8 das 9 perguntas da pesquisa. O sintoma mais
visível: o job do Supabase pedia o segredo `dash-lead-id-salt` **só para calcular um hash
que descartava**.

### O parâmetro `magro`

`sql_fonte(magro=True)` produz **as mesmas linhas com menos colunas**. É o que a Fonte B
usa.

O corte que importa para o custo é o `launch_calendar`. Ele casa um lead com **toda**
janela de captação que contém a data dele, e três pares de janelas se sobrepõem em 2026,
então ele **multiplica linhas** — e o `DISTINCT ON` existe para desfazer a multiplicação.

Resultado medido:

| | antes | depois |
|---|---|---|
| custo estimado do plano | 1.520.923 | 588.252 (**−61%**) |
| pico de linhas ordenadas | 789.840 | 327.847 (**−58%**) |

> **REGRA para quem for mexer:** `magro` pode remover **coluna**, nunca mudar quais
> **linhas** saem. O calendário pôde sair porque as linhas que ele duplica são idênticas
> em tudo menos em `lf` — o `DISTINCT ON` escolhia entre cópias. **Se o calendário algum
> dia passar a filtrar (deixar de ser `LEFT JOIN`), esse raciocínio cai.** Os testes em
> `V2/tests/test_entrega_dash.py` comparam as cláusulas de linha dos dois modos uma a uma.

No modo magro a **venda** também sai da lista do que mudou, porque `comprou` não é
entregue: em 06/08/2026 foram 5.329 vendas num dia só, todas de compra antiga, que
virariam 5.329 regravações sem efeito nenhum.

---

## O que NUNCA sai nesta entrega

Score e decil por lead são **proibidos**, nas duas fontes. Isso inclui `lead_score`,
`decil`, `score_champion`, `score_challenger`, `decil_champion`, `decil_challenger`,
`decile_propensity`, `decile_roas_v1`, `hotleads_hot` e qualquer nota derivada.

Nome, e-mail e telefone **são** autorizados. CPF, endereço e documento não.

**Agregado por criativo ou campanha é autorizado**, com mínimo de 30 leads por linha. É o
que `dash.qualidade_por_anuncio` e `public.scores_inbound` fazem.

O ponto do código onde vazar sem querer é mais fácil é o braço de `registros_ml`: essa
tabela guarda todas as colunas de score **ao lado** das que a entrega usa, então um
`SELECT r.*` ou um copiar-colar de outra query bastaria. Há teste travando isso.

---

## Onde a coisa é vista quando dá errado

A auditoria manda o resultado no **DM** (`SLACK_USER_DM`, com o mesmo último recurso fixo
do resto do projeto). Ela manda **também quando está tudo certo, em uma linha** — sem
isso, silêncio significaria duas coisas ao mesmo tempo: nada divergiu, ou o job não rodou.

Até 10/08/2026 ela não avisava ninguém: detectava, saía com erro, e o erro morria no log
do Cloud Run. Das 3 políticas de alerta do projeto, **nenhuma** cobre este job — a de
`Cron falhou` dispara quando o Scheduler não consegue **disparar** o job (403/500), não
quando o job roda e falha por dentro.

---

## Estado pendente

**No front (pedido a eles)**
- [ ] Voltar a preencher `Client.hasComputer` no Railway, e **não remover a coluna** (0,0%
      desde junho; o dado chega no nosso webhook, então eles têm a informação).
- [ ] Consertar a cobertura de UTM que caiu em 03/08 (de 0,2-1,7% sem UTM em oito semanas
      para 8,4%). Já em recuperação: 98,6% em 11/08.
- [ ] Não mexer em `Client` e `UTMTracking` sem avisar — são as duas vivas de que a ingestão
      depende. E não apagar `leads_capi`: é a única do Railway sem cópia nossa (300 mil
      linhas). Precedente: `leads_capi.event_source_url` esvaziou numa migração de schema e
      recuperar a URL de janeiro exigiu um backup de fevereiro.

**Deles (Supabase)**
- [ ] `CREATE UNIQUE INDEX ON public.leads_inbound (email, data)` — uma linha, dispensa o
      apaga-e-insere.
- [ ] `public.scores_inbound` criada com 7 colunas e chave única, ainda **vazia**.

**Nosso**
- [ ] Ligar `SLACK_BOT_TOKEN` no job de auditoria (o segredo `slack-bot-token` já existe).
      Sem ele o aviso registra o erro e segue.
- [ ] Levar o AVISO de teto da ingestão para o DM. Hoje ele sai só em `stderr`, o que
      repete o problema que a auditoria já teve: aviso que ninguém vê.
- [ ] Copiar `leads_capi` do Railway para o nosso banco.
- [ ] Completar `utm_medium` e `utm_term` do histórico. Fonte: `UTMTracking`, com 143 mil
      linhas contra 503 mil da `captacoes` — recuperação PARCIAL por construção, e merece a
      própria medição antes.
- [ ] Aposentar de vez a Fonte A, ou decidir mantê-la como plano B por escrito.

## Onde olhar no código

| O que | Arquivo |
|---|---|
| Fonte A + a consulta compartilhada `sql_fonte` | `V2/scripts/provisiona_dash_zanelato.py` |
| Fonte B (4 modos, auditoria, aviso no DM) | `V2/scripts/push_supabase_zanelato.py` |
| Testes da consulta compartilhada e do modo magro | `V2/tests/test_entrega_dash.py` |
| Testes da Fonte B | `V2/tests/test_push_supabase.py` |
| Ingestão Railway → `captacoes` | `V2/scripts/ingest_captacoes_railway.py` |
| Migração do grão da `captacoes` | `V2/scripts/migrate_captacoes_por_inscricao.py` |
| Preenchimento da `utm_url` histórica | `V2/scripts/completa_url_captacoes.py` |
| Testes da ingestão | `V2/tests/test_ingest_captacoes.py` |
| Repescagem das URLs de janeiro/fevereiro | `V2/scripts/recupera_url_legado.py` |
