# Teto de CPL: as decisões tomadas, e por quê

O teto de CPL é o custo máximo por lead que um segmento pode ter sem violar a meta de
retorno. É a métrica que o time de tráfego usa para decidir onde subir e onde cortar verba.

```
teto = conversão esperada do segmento × valor por venda ÷ ROAS alvo
```

Este documento registra as decisões de desenho e a evidência de cada uma. Decisão sem
número aqui é decisão a rever.

---

## Decisão 1 — Cinco baldes de decil, FIXOS

**O que era.** Dois baldes: D9-D10 de um lado, **tudo de D1 a D8** do outro.

**O problema, medido.** Todo criativo abaixo do D9 recebia o mesmo teto de R$ 3,96,
quando a conversão real dentro dessa faixa varia 5,2 vezes:

| balde | leads | compradores | conversão | teto (ROAS 2) |
|---|---|---|---|---|
| D1-D2 | 17.623 | 37 | 0,210% | R$ 1,36 |
| D3-D4 | 19.443 | 80 | 0,411% | R$ 2,66 |
| D5-D6 | 21.032 | 129 | 0,613% | R$ 3,97 |
| D7-D8 | 22.309 | 246 | 1,103% | R$ 7,13 |
| D9-D10 | 24.046 | 389 | 1,618% | R$ 10,47 |
| *(antes: tudo de D1 a D8)* | *80.407* | *492* | *0,612%* | *R$ 3,96* |

Custo operacional do achatamento: uma campanha inteiramente D7-D8 recebia teto de
R$ 3,96 quando o correto é R$ 7,13, e o gestor era mandado cortar verba de uma campanha
com **59% de folga escondida**. No sentido oposto, uma campanha D1-D2 recebia teto quase
3 vezes acima do que sustenta.

**Por que cinco e não dez.** Teste de duas proporções em cada par vizinho, sobre a
referência viva (104.453 leads, 881 compradores):

| corte | pior par vizinho | veredito |
|---|---|---|
| 2 baldes | p ≈ 0 | todos separam |
| 3 baldes | p = 7,5 × 10⁻¹² | todos separam |
| 4 baldes | p = 1,9 × 10⁻⁶ | todos separam |
| **5 baldes** | **p = 4,6 × 10⁻³** | **todos separam** |
| 10 baldes | — | **5 dos 9 pares são indistinguíveis** |

Com dez baldes, os pares D2-D3, D3-D4, D4-D5, D5-D6 e D8-D9 não se separam do ruído.
Com cinco, o pior par ainda dá 1 em 216 de chance de ser acaso.

**Sobre o erro relativo do balde de baixo.** D1-D2 tem ±16,4% de erro na taxa, contra
±5,1% do D9-D10. Parece desequilibrado e não é: 16,4% de R$ 1,36 são **22 centavos**, e
ninguém otimiza verba nessa faixa. A precisão é mais alta exatamente onde o dinheiro está.

**Sobre monotonia.** Nos experimentos de treino a monotonia raramente é 100%, por falta de
compradores no conjunto de teste. Na referência viva ela é **9 de 9 passos, sem quebra
nenhuma** — é outro regime de volume, e por isso o corte por decil se sustenta aqui.

**O que ficou de fora, deliberadamente.** Chegou a ser proposto que o número de baldes
fosse recalculado a cada reconstrução da referência (tenta cinco, funde se algum par não
separar). Foi **rejeitado como engenharia prematura** em 14/08/2026: resolve um problema
que ainda não existe e acrescenta um caminho de código que só roda em condição rara, que
é a pior espécie para manter. Fica cinco, fixo.

**Quando revisitar.** Se o volume da referência cair muito (novo cliente, ou queda forte de
captação neste), rodar o teste par a par de novo antes de assumir que cinco ainda separa. O
critério é o mesmo: todo par vizinho com p < 0,05.

---

## Decisão 2 — ROAS alvo passa de 1,0 para 2,0

**O que era.** ROAS alvo 1,0, ou seja, **breakeven**: o teto respondia "qual o CPL máximo
para não dar prejuízo".

**O que passa a ser.** ROAS alvo 2,0: "qual o CPL máximo para o retorno ser o dobro do
investido". Todo teto cai pela metade.

**Por que.** Decisão de negócio de 13/08/2026. Breakeven não é meta, é piso de
sobrevivência; operar mirando nele significa aceitar lucro zero como resultado aceitável.

**Nota de implantação.** O alvo já era parâmetro da função (`roas_alvo`), apenas chamado
com 1,0 em todos os pontos. A mudança é de valor, não de fórmula. O que exige cuidado é a
**comunicação**: o gestor vê todos os tetos caírem pela metade de um dia para o outro, e
precisa saber disso antes, não depois.

---

## Decisão 3 — Cada teto carrega o carimbo da referência que o gerou

**O que faz.** Toda linha de teto guarda de qual versão da referência (`as_of`) ela saiu.

**Por que.** A conversão por balde e o valor por venda são reconstruídos **toda segunda às
06:30**. O teto de hoje e o da semana que vem saem de bases diferentes sem ninguém ter
mexido em nada. Sem o carimbo, "por que em 14/08 o teto era R$ 7,13 e hoje é R$ 5,80?" não
tem resposta, porque a referência daquele dia já foi sobrescrita.

**Que a variação é real, medida:**

| referência | % cartão | valor por venda |
|---|---|---|
| 03/08 (anterior) | 35,0% | R$ 1.349,61 |
| 03/08 | 30,2% | R$ 1.301,57 |
| 10/08 | 29,4% | R$ 1.293,98 |

Os preços são constantes (cartão R$ 2.000, boleto R$ 1.000, este último já com o desconto
de 50% por risco de calote). **O que varia é só a mistura entre os dois** — e 5,6 pontos a
menos de cartão derrubaram todo teto em 4,1%.

Numa métrica que move verba, ter recibo é o que separa "erramos" de "não sabemos".

### Achado: o job da referência roda código congelado em 31/07

Ao conferir o teto contra o banco real (14/08/2026), a referência devolvida foi a de
**03/08**, não a de **10/08**. Puxando o fio, o que estava por baixo não era uma escolha
de ordenação e sim **um job de produção rodando código velho**.

A janela madura é `as_of − maturação`. Aplicando a cada linha:

| gerado em | as_of | fim da janela | maturação implícita | leads |
|---|---|---|---|---|
| 10/08 06:32 (cron) | 2026-08-10 | 2026-06-11 | **60 dias** | 104.453 |
| **03/08 19:15 (manual)** | 2026-08-03 | 2026-07-13 | **21 dias** | 86.141 |
| 03/08 11:27 (cron) | 2026-08-03 | 2026-06-04 | 60 dias | 107.986 |
| 30/07 21:48 (cron) | 2026-07-30 | 2026-05-31 | 60 dias | 112.766 |
| 29/07 20:23 (cron) | 2026-07-29 | 2026-05-30 | 60 dias | 113.752 |

**21 é o valor correto**, e a mudança de 60 para 21 foi feita em **07/08/2026** justamente
porque 60 inflava o teto: com a maturação longa, a conversão de um balde vinha de amostra
minúscula (7 vendas em 438 leads = 1,598%) e empurrava o teto do Champion para R$ 20,81
quando o real é ~R$ 9,29.

**Mas o job semanal nunca recebeu essa mudança.** Ele roda um contêiner fixado por digest,
construído em **31/07**, uma semana antes da correção. Toda segunda ele escreve uma
referência com a maturação que o projeto já abandonou.

**A ordenação está acidentalmente nos salvando.** O leitor ordena por fim da janela, e
maturação de 21 dias produz um fim MAIS RECENTE que a de 60. Por isso ele serve a única
linha correta que existe — a manual de 03/08 — e ignora as do cron.

**A armadilha, e é o motivo de isto estar escrito aqui:** "consertar" a ordenação para
data de geração **sem antes atualizar o job** faria o teto pular para os números inflados
da maturação de 60. A ordem certa é o contrário: primeiro reconstruir o job, depois
revisar a ordenação (que aí passa a ser indiferente, porque a linha mais nova também terá
o fim de janela mais recente).

*As tabelas de valores neste documento foram calculadas sobre a referência correta, a de
maturação 21.*

---

## Decisão 4 — O teto é obrigatório; quem pode faltar é o CPL

**O achado.** Foram encontrados 7 pontos onde o teto desaparecia sem avisar, e no resumo
diário ele virava string vazia: "não há teto" e "não conseguimos calcular" ficavam
visualmente idênticos na tela do gestor.

**Por que dá para resolver por construção.** O teto é `conversão do balde × valor por venda
÷ ROAS`, e os três ingredientes vêm da referência e da mistura de decis do criativo.
**Nenhum deles é gasto.** Assim que um criativo tem um lead, ele tem mistura de decis, e
portanto tem teto. **Não existe "hoje não temos teto".**

O que pode faltar é o **gasto**, e aí falta o CPL — que é a coisa com que o teto é
comparado, não o teto.

```
criativo             CPL      teto     folga
DEV-AD0160          R$ 4,12   R$ 6,30  +R$ 2,18
DEV-AD0389            —       R$ 4,57     —      (sem gasto casado)
```

Traço no CPL e na folga, **nunca no teto**. Teto ausente é falha, e falha alto.

**Como isso está implementado.** `CalculadoraDeTeto` (em `src/monitoring/teto.py`) devolve
um `Teto` com `motivo` explícito, e não um `None` solto: `sem_referencia`,
`sem_valor_por_venda`, `sem_conversao` ou `segmento_vazio`. É o motivo que torna as duas
situações distinguíveis.

---

## Decisão 5 — Entregamos o teto, não o gasto

**Por quê.** O time de tráfego já vê o gasto no gerenciador, várias vezes por dia. Entregar
gasto de volta para quem já está olhando para ele é redundante e chega sempre atrasado.

**O que muda no desenho.** Como o teto não precisa de gasto, ele **tira do caminho crítico**
a ingestão de gasto no grão de anúncio, que era o passo mais caro do projeto. O teto por
criativo vai ao ar sem ela.

**O que guardamos para nós.** Uma conferência diária, depois da ingestão de gasto das
09:45: o teto de ontem foi respeitado, em quantos criativos, e qual foi o delta de cada um.
Backward-looking, sem pressa, e é ela que prova se a métrica está funcionando.

---

## Decisão 6 — O teto vira coluna na tabela que já existe

**Onde entrega.** `public.scores_inbound`, no Supabase da agência, empurrada de hora em
hora no minuto 22 e viva desde 12/08/2026. O grão dela já é por criativo e por campanha,
que é o grão do teto.

**Por que não tabela nova.** Menos uma peça, menos um job, e o painel deles já lê dali.

**Duas ressalvas.** Acrescentar coluna é **mudança de contrato** com o painel da agência, e
precisa ser combinada, não empurrada. E o objetivo final é teto por criativo **em cada
campanha onde ele roda**, que é o cruzamento dos dois; a tabela hoje traz criativo **ou**
campanha em linhas separadas.

---

## Decisão 7 — A trava de segurança vem antes de POPULAR a coluna, e repete

**O que é.** Pegar criativos de lançamentos já encerrados, calcular o teto que teríamos
mandado, e comparar com o que de fato aconteceu. É o único teste que pega erro de fórmula,
porque confere contra a realidade em vez de contra a própria conta.

**Por que antes e não depois.** Uma nota de qualidade errada custa ranking. **Um teto
errado custa dinheiro direto**, porque o gestor mexe na verba com base nele. Métrica de
otimização de negócio não estreia para depois ser conferida.

**A trava é sobre POPULAR, não sobre CRIAR** (esclarecido em 14/08/2026). Criar a coluna do
lado da agência é mudança de contrato com prazo próprio deles, então o pedido pode ser
feito **agora**, em paralelo com a construção. Coluna vazia não engana ninguém; coluna com
número errado, sim. A trava fica entre "a coluna existe" e "a coluna tem valor".

**E repete.** Vale antes da primeira população e antes de cada mudança que altere o valor
entregue (entrada da nota de conversão, entrada do palpite pela fala). Cada uma delas muda
o número na tela do gestor, e cada uma passa pelo mesmo portão.

---

## Em aberto 1 — Guardar o histórico de CPL contra teto

**O que se quer.** Poder reconstruir depois: em quantos dias, em qual criativo, o gasto
ficou acima ou abaixo do esperado. É um pedido de **memória**, e ele não estava no plano.

**A cadência proposta era de 10 em 10 minutos, e ela não serve ao objetivo.** O gasto é
ingerido **uma vez por dia**, às 09:45. Empurrar de 10 em 10 minutos escreveria o mesmo
número 144 vezes por dia sem torná-lo mais fresco:

| cadência | linhas/dia (~50 criativos) | linhas/ano | informação nova/dia |
|---|---|---|---|
| a cada 10 min | 7.200 | ~2,6 milhões | 50 |
| **1× por dia, append** | **50** | **~18 mil** | **50** |

Custo de infraestrutura não é o gargalo (o job de 10 minutos já existe e o acréscimo
seria de centavos). O gargalo é que uma tabela com 144 vezes de redundância fica cara de
consultar exatamente quando alguém for fazer a pergunta que motivou guardá-la.

**Encaminhamento:** uma linha por (dia, criativo, campanha) que **nunca é sobrescrita**,
carregando CPL, teto, folga e o carimbo da referência. Serve o objetivo inteiro com 1/144
do volume, e é a mesma linha que a conferência diária (passo 7) já vai produzir.

**Quando 10 minutos seria certo:** se o objetivo virasse *pegar um criativo queimando
dinheiro às 14h em vez de amanhã*. Isso é requisito diferente, exige bater na API do Meta
a cada 10 minutos (~21 mil chamadas/dia) e esbarra em dois problemas: o limite de
requisições da plataforma, e o fato de o Meta **reafirmar o gasto ao longo do dia**, o
que torna leitura de meio de dia pouco confiável para decidir verba.

---

## Em aberto 2 — O criativo converte diferente por TIPO de campanha? SIM

**O buraco, apontado em 14/08/2026.** A nota do criativo se divide por **canal**
(Meta/Google), porque os dois convertem diferente. Mas o mesmo criativo também roda em
tipos de campanha diferentes — otimizada por Lead puro, ou otimizada pelo evento de
qualidade do modelo — e **é a campanha que decide a quem o Meta entrega o anúncio**. Nada
no escopo cobria isso.

**Não confundir com o que o teto já faz.** O teto já muda por campanha, porque usa a
mistura de decis daquela campanha. Isso captura *quem esta campanha traz*. O que falta é
diferente: *como este criativo VENDE neste tipo de campanha*. Já foi medido que as duas
coisas divergem (49,2% do topo do modelo vinha de anúncios que convertem mal).

### Correção de uma medição errada

A primeira medição desta pergunta usou uma regra de classificação **inventada por
substring** e concluiu que só 3 criativos tinham volume nos dois tipos, portanto que não
havia como decidir. Estava errada em dois pontos:

1. O projeto tem classificação canônica: `campaign_classifier.tag_signature` mais a
   curadoria em `analytics.campaign_labels` (Controle / Champion / Challenger / Lead /
   Excluir), curada em 22/07/2026. Reimplementar por substring violou a regra de nunca
   refazer transformação que já existe.
2. A regra inventada colapsava **Controle** e **Excluir** dentro de "Lead". Controle é
   grupo de controle deliberado, não campanha de lead padrão.

**E a cobertura sempre existiu: 95,8% das captações têm categoria curada**, sobre 501.105
linhas de dez/2024 a hoje. Não havia nada a esperar.

### O que o rótulo certo mostra

| categoria | leads | compradores | conversão |
|---|---|---|---|
| Lead | 152.736 | 1.849 | 1,211% |
| Champion | 240.407 | 1.827 | 0,760% |
| Controle | 75.747 | 689 | 0,910% |
| Challenger | 5.995 | 49 | 0,817% |

Sobreposição real: **17 criativos** rodaram nos dois tipos com pelo menos 100 leads em
cada, somando 176.927 leads — não 3. E o efeito é grande e vai **nos dois sentidos**:

| criativo | Lead | ML | razão | p |
|---|---|---|---|---|
| DEV-AD0017-vid-captação-V0-PODCAST | 1,44% (9k) | 0,42% (3k) | **0,29x** | 0,0000 |
| DEV-AD0141-vid-captação-V0-PODCAST | 0,05% (6k) | 0,31% (17k) | **6,53x** | 0,0003 |
| DEV-AD0150-vid-captação-V0 | 0,24% (3k) | 0,60% (34k) | 2,50x | 0,0082 |
| DEV-AD0160 - VID - CAPTAÇÃO | 0,77% (5k) | 1,09% (23k) | 1,41x | 0,0377 |

**4 de 17 diferem a p < 0,05**, e os dois primeiros sobrevivem até a correção para
múltiplos testes (limiar 0,0029 para 17 comparações). Com 17 testes, o esperado por acaso
seria menos de um.

**O que torna isto convincente não é a contagem, é a bidirecionalidade.** Um viés
sistemático (por exemplo "campanha de ML sempre entrega público pior") apareceria como
razões todas do mesmo lado. Aqui um criativo converte 3,4 vezes PIOR no ML e outro 6,5
vezes MELHOR. Isso é assinatura de interação real entre criativo e tipo de campanha, não
de ruído nem de viés de nível.

### A ameaça que ainda não foi descartada

As células são acumuladas sobre toda a história. Se um criativo rodou em campanha de Lead
num período e em ML noutro, **a diferença pode ser de período e não de tipo**. É o único
concorrente sério à explicação de interação, e ele se testa comparando só dentro de
janelas onde o criativo rodou nos dois tipos ao mesmo tempo.

**Encaminhamento:** vale perseguir, e o próximo passo é descartar o confundimento
temporal — não instrumentar e esperar, porque o dado já existe. Se a diferença sobreviver
ao recorte por período, a nota passa a se dividir por tipo do mesmo jeito que já se divide
por canal.

**Armadilha de leitura, registrada.** No agregado o Lead converte melhor (1,211% contra
0,760% do Champion), o que parece dizer que a campanha de ML é pior. É ilusão de
composição: são criativos, períodos e públicos diferentes. A comparação válida é a de
dentro do criativo.

---

## A ordem de execução

| # | passo | entrega valor sozinho? | estado |
|---|---|---|---|
| 1 | Montagem do teto vira função única; os dois relatórios viram clientes finos dela | não, é base | **feito** |
| 2 | Cinco baldes + ROAS 2 + carimbo da referência | sim | **feito** |
| 3 | **Trava: reconferência contra lançamentos passados** | portão | |
| 4 | Popular o teto em `scores_inbound` (coluna já pedida à agência em paralelo) | sim, o gestor recebe | |
| 5 | Nota de conversão do criativo entra no teto | sim | |
| 6 | Palpite pela fala do vídeo entra no teto | sim | |
| 7 | Histórico diário de CPL contra teto (serve "em aberto 1") + grão de anúncio | sim, para nós | |

Os passos 5 e 6 passam pelo portão do passo 3 antes de chegar ao gestor. O tipo de
campanha ("em aberto 2") entra no passo 5, se o recorte por período confirmar que a
diferença não é de época.

---

*Decisões registradas em 14/08/2026. Constantes da nota do criativo em
[NOTA_DO_CRIATIVO_PARAMETROS.md](NOTA_DO_CRIATIVO_PARAMETROS.md).*
