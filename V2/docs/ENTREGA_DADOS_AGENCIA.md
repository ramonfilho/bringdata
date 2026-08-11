# Entrega de dados para o gestor de tráfego — as duas fontes

Existem **duas** formas de a gente entregar banco de dados para a agência que gerencia o
tráfego (Zanelato). Elas fazem a mesma coisa por caminhos opostos, e **só uma está
ligada**. Este documento existe porque as duas dividem código, e mexer numa sem saber da
outra quebra a que ninguém estava olhando.

Última verificação contra produção: **2026-08-10**.

| | Fonte A — banco `dash` | Fonte B — Supabase deles |
|---|---|---|
| **Onde mora o banco** | nosso Cloud SQL | Supabase deles (AWS sa-east-1) |
| **Quem conecta em quem** | eles leem o nosso | nós escrevemos no deles |
| **Estado** | ⏸ **desligada** | ✅ **no ar** |
| **Script** | `V2/scripts/provisiona_dash_zanelato.py` | `V2/scripts/push_supabase_zanelato.py` |
| **O que dispara** | cron `dash-zanelato-refresh-daily` (PAUSADO) | 3 jobs do Cloud Run |
| **Tabelas de destino** | `dash.leads_2026`, `dash.qualidade_por_anuncio` | `public.leads_inbound`, `public.scores_inbound` |
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

**Estado:** o cron está PAUSADO. O banco `dash` e o papel de leitura da agência **não
foram removidos**, de propósito: se a Fonte B tiver problema, religar é despausar um cron.

---

## Fonte B — Supabase deles (no ar)

**Script:** `V2/scripts/push_supabase_zanelato.py`

Três jobs do Cloud Run, cada um com um horário:

| Job | Quando | O que faz |
|---|---|---|
| `zanelato-supabase-incremental` | de hora em hora | manda só o que mudou desde a nossa última gravação |
| `zanelato-supabase-podar` | 1x/dia | apaga o que passou de 90 dias |
| `zanelato-supabase-auditar` | 1x/dia | conta as duas pontas por mês e avisa no DM |

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

## De onde saem os dados (Fonte B)

Sete tabelas nossas, e só **três dão lead**:

| tabela | quem vem dela | viva? |
|---|---|---|
| `analytics.leads` | quem respondeu a pesquisa | não, refeita 09:00 |
| `analytics.cadastros` | quem **não** respondeu | não, refeita 10:00 |
| `public.registros_ml` | quem respondeu, **em minutos** | **sim, tempo real** |

As outras quatro só completam campo: `public.lead_legado` e
`analytics.url_captura_legado` preenchem `utm_url`; `analytics.sales` e
`analytics.launch_calendar` são usadas **apenas** pela Fonte A (ver acoplamento abaixo).

O braço de `registros_ml` entrou em 10/08/2026. Antes dele, as duas primeiras tabelas
serem reconstruídas uma vez por dia significava que **o lead de hoje só chegava amanhã**,
para uma agência que abre o painel várias vezes ao dia para decidir verba. Medido no dia:
165 leads estavam no ledger e ausentes das derivadas, e a entrega do dia tinha 33 linhas
contra 215 na planilha deles.

### O que AINDA falta em tempo real

`registros_ml` é **só respondente** (medido: 244 de 244 linhas de hoje têm a pesquisa
preenchida). Quem se cadastrou e não respondeu só aparece no dia seguinte, via
`analytics.cadastros`.

A tabela viva com **não-respondente** existe e é nossa: **Railway `Client`**. Medido em
10/08/2026, ela tinha 294 cadastros no dia contra 244 respondentes no ledger. Trazer
esses ~50 esbarra em dois problemas que precisam ser resolvidos ANTES:

1. **A origem vem pobre.** `Client` + `UTMTracking` dão `source` em 71,7% e `campaign`
   em 68,9%, contra 100% e 91,9% no ledger. A diferença é o nosso preenchimento pelo
   slug da página (`cap-meta` → facebook-ads), que roda **só no caminho da pesquisa**
   (`src/scoring/service.py`, `api/pubsub_branch.py`) e preenche **só `source`**.
2. **A data não bate.** `Client.createdAt` é o primeiro cadastro; `cadastros.first_seen_at`
   é a primeira vez que a pessoa foi vista, na vida. Para quem já se cadastrou antes, são
   meses de diferença. Como o `DELETE` é por (email, data), isso **duplicaria** em vez de
   substituir.

---

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

- [ ] Ligar `SLACK_BOT_TOKEN` no job `zanelato-supabase-auditar` (o segredo
      `slack-bot-token` já existe). Sem ele o aviso registra o erro e segue.
- [ ] Tirar `dash-lead-id-salt` do job do Supabase — o modo magro não usa mais.
- [ ] Popular `public.scores_inbound` (criada por eles com 7 colunas e chave única em
      `(tipo, chave)`, ainda **vazia**).
- [ ] Decidir a cadência do incremental. Está de hora em hora; com o ledger vivo, 5
      minutos passou a fazer sentido.
- [ ] Decidir se o não-respondente do dia entra via Railway `Client` (ver os dois
      problemas na seção acima).
- [ ] Pedir a eles o índice único em `(email, data)`.

## Onde olhar no código

| O que | Arquivo |
|---|---|
| Fonte A + a consulta compartilhada `sql_fonte` | `V2/scripts/provisiona_dash_zanelato.py` |
| Fonte B (4 modos, auditoria, aviso no DM) | `V2/scripts/push_supabase_zanelato.py` |
| Testes da consulta compartilhada e do modo magro | `V2/tests/test_entrega_dash.py` |
| Testes da Fonte B | `V2/tests/test_push_supabase.py` |
| Repescagem das URLs de janeiro/fevereiro | `V2/scripts/recupera_url_legado.py` |
