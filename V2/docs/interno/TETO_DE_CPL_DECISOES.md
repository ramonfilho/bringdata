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

**O problema, medido.** Todo criativo abaixo do D9 recebia o mesmo teto, quando a
conversão real dentro dessa faixa varia **3,85 vezes**.

Números sobre a referência **que o leitor de fato serve** (`as_of` 03/08, janela até
13/07, 86.141 leads, 700 compradores, valor por venda R$ 1.349,61):

| balde | leads | compradores | conversão | teto (ROAS 2) |
|---|---|---|---|---|
| D1-D2 | 10.720 | 26 | 0,243% | R$ 1,64 |
| D3-D4 | 14.872 | 60 | 0,403% | R$ 2,72 |
| D5-D6 | 17.507 | 106 | 0,605% | R$ 4,09 |
| D7-D8 | 20.660 | 193 | 0,934% | R$ 6,30 |
| D9-D10 | 22.382 | 315 | 1,407% | R$ 9,50 |
| *(antes: tudo de D1 a D8)* | *63.759* | *385* | *0,604%* | *R$ 4,07* |

Custo operacional do achatamento: uma campanha inteiramente D7-D8 recebia teto de
R$ 4,07 quando o correto é R$ 6,30, e o gestor era mandado cortar verba de uma campanha
com **55% de folga escondida**. No sentido oposto, uma campanha D1-D2 recebia teto
2,5 vezes acima do que sustenta.

> **Correção de 14/08/2026.** A primeira versão desta tabela saiu da referência de
> **10/08** e prometia D9-D10 a R$ 10,47. Aquela linha foi construída com maturação de
> 60 dias, a política abandonada em 07/08, e **não é a que o leitor serve** — a servida
> é a de 03/08, com maturação de 21. O erro era de 9,3% na manchete, e o teste que
> defendia a separação usava o limiar de 5x, que só passa na referência errada. Ambos
> corrigidos. É exatamente o tipo de deslize que a **decisão 3 (o carimbo)** existe para
> tornar detectável: sem registrar de qual referência o número saiu, essa divergência
> não teria como aparecer.

**Por que cinco e não dez.** Teste de duas proporções em cada par vizinho. Com dez
baldes, 5 dos 9 pares vizinhos são estatisticamente indistinguíveis (D2-D3, D3-D4,
D4-D5, D5-D6 e D8-D9) — separá-los seria vender ruído como precisão.

Com cinco, todos os vizinhos se separam, e isso foi verificado nas **duas** referências
disponíveis, o que é a evidência que sustenta a decisão independentemente de qual delas
esteja sendo servida:

| par vizinho | na referência servida (03/08) |
|---|---|
| D1-D2 vs D3-D4 | p = 2,8 × 10⁻² |
| D3-D4 vs D5-D6 | p = 1,1 × 10⁻² |
| D5-D6 vs D7-D8 | p = 2,8 × 10⁻⁴ |
| D7-D8 vs D9-D10 | p = 5,6 × 10⁻⁶ |

O pior par dá 1 chance em 35 de ser acaso.

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

*Os valores neste documento saem da referência **servida** (`as_of` 03/08, maturação de
21 dias). Eles mudam a cada reconstrução da referência — é por isso que cada teto
entregue carrega o carimbo de qual delas veio (decisão 3).*

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

## Decisão 8 — Uma régua só de contagem de compra: o calendário. E o 1,21 morreu.

**O contexto.** Para medir conversão, cada lead ganha um prazo: comprou dentro, conta;
depois, não. Existiam **duas regras convivendo**: a nota do criativo contava pelo
calendário (a compra vale até o `vendas_end` do lançamento do lead), e a referência
rolante, que alimenta o teto, contava com **prazo fixo de 21 dias** para todo lead.

**A medição que decidiu (14/08/2026, 317 mil leads, 26 lançamentos fechados, 2.437
compradores casados por email/telefone).** Dentro da regra do calendário:

| recorte | compra depois do dia 21 |
|---|---|
| todos os lançamentos | 3,7% |
| só LF56+ (o que a janela de 90d da referência enxerga) | **0,0%** |
| DEV19 (ciclo de 40 dias) | **15,4%** |

Nos lançamentos de ciclo de 21 dias não existe dia 22, então o prazo fixo não perdia
nada. Mas os lançamentos estilo DEV têm ciclo maior (DEV19: 40d; DEV21: 26d), e neles o
prazo fixo **descartava até 15% dos compradores**, subestimando a conversão e, por
consequência, o teto.

**O que mudou.** O construtor da referência (`rolling_reference.label_matured`) passou a
contar a compra pela mesma regra do calendário (`compra_conta_para_o_lead`), com o piso
de 21 dias para lead fora de calendário. Lead cujo lançamento ainda vende fica **fora**
da referência até a janela fechar (contá-lo cedo subestimaria a taxa). A regra usada
fica carimbada no payload (`conversion.conversion_window`), pra ninguém precisar de
arqueologia de git pra saber como o número foi contado.

**E o 1,21 morreu.** O documento de teto de 03/08 aplicava um fator 1,21 porque "17%
compram depois de 21 dias". Medido de novo dentro da regra do calendário, esse 17% era
em maioria gente comprando **depois do fim das vendas do lançamento dela**, isto é, no
lançamento seguinte, dinheiro que a nossa regra de atribuição credita ao lançamento
seguinte, não ao criativo que captou meses antes. A cauda legítima é 3,7% no histórico e
zero nos ciclos de 21d. **Nenhum teto futuro reaplica o 1,21**: com a contagem pelo
calendário, a correção não corrige nada, só infla. (Conferido em 14/08: o fator nunca
existiu em código, só na conta manual daquele documento.)

---

## Decisão 9 — A fórmula da conversão prevista: lift normalizado por época, K = 2.000

**Decidido em 15/08/2026, com backtest.** A conversão prevista de cada unidade (um
criativo rodando numa campanha do Meta) é:

```
conversão = conv_modelo × (peso × lift + (1 − peso))        peso = n ÷ (n + 2.000)
```

- `conv_modelo` = mistura de decis da campanha lida na referência rolante (o braço
  "público": conta quantos leads da campanha caíram em cada decil e pondera pela
  conversão de cada decil).
- `lift` = compradores reais do criativo ÷ compradores esperados se ele fosse médio
  **na época de cada lançamento em que rodou** (soma de leads × conversão geral daquele
  lançamento). Sempre com lançamentos ANTERIORES ao avaliado, nunca o próprio.
- `n` = leads maduros que o criativo já trouxe; `peso` vai de 0 (estreante, fica só o
  modelo) a ~0,95 (40 mil leads). **O modelo nunca sai da fórmula.**

**Por que normalizar por época:** o mercado caiu ao longo de 2026 (a faixa D9-D10
convertia 3,67% nos lançamentos de fevereiro e 1,74% nos de junho). Histórico bruto de
criativo antigo carrega época boa como se fosse mérito do criativo. O lift é
adimensional: se o mercado voltar a subir, a referência rolante (refeita toda semana)
sobe o nível, e o mérito relativo do criativo permanece comparável. A fórmula acompanha
o mercado nos dois sentidos, com o atraso da maturação (semanas).

**Empate empírico declarado:** no backtest a versão lift ganhou da aditiva bruta em
quase tudo (ordem +0,39 vs +0,37; terços 2,33x vs 2,25x; 15 de 26 lançamentos), mas sem
significância (p = 0,17). O desempate foi o argumento de época, não o dado. K é platô
(250 a 4.000 dão quase o mesmo), mantido em 2.000.

**Limitação registrada:** o lift é acumulado na vida do criativo; se um criativo
específico piorar de verdade, o acumulado demora a refletir (a ordem entre criativos se
mostrou estável por 6 meses nos artifacts, então o risco é baixo, mas existe).

**Registro: a queda de 2026 foi de NÍVEL (mercado), não de separação (modelo).** A
premissa da fórmula lift é que o nível se move para todo mundo e o mérito relativo
fica. O dado sustenta: de LF43-46 (fev) para LF56-59 (jun), o topo D9-D10 caiu de
3,67% para 1,74% (−53%) e a média geral caiu de 1,85% para 0,83% (−55%) — proporcional,
com a razão topo÷média indo de 1,98x para 2,10x. No corte só-Meta (LF56-61), o ponto do
topo caiu mais que o do meio (−53% vs −31%), mas a diferença se apoia em 16-21 compras
e não passa no teste estatístico; a ordem nunca inverteu. Vigília aberta: o DEV21, onde
a separação do pago da Meta deu 1,23x no dia 1 (não-Meta: 2,28x) — fenômeno posterior,
específico do canal, com teste pré-registrado pendente. Se ele se confirmar, o problema
é do braço do MODELO na Meta, não da fórmula do criativo.

### As métricas do backtest (documentação do resultado)

Base: 314.752 leads deduplicados de 26 lançamentos fechados (25/11/2025 a 30/07/2026),
2.366 compradores casados por email/telefone, compra contada da captação até o fim das
vendas do lançamento. 534 unidades criativo×campanha com 100+ leads (130 campanhas Meta,
66 criativos; 85% das unidades com histórico próprio). Previsão sempre fora do tempo.

| métrica (o que mede) | só modelo | aditiva K=2.000 | **lift K=2.000** |
|---|---|---|---|
| Correlação de posto previsto×realizado, média por lançamento | +0,29 | +0,37 | **+0,39** |
| Aponta o criativo que MAIS converteu na campanha (28 campanhas com 3+ criativos; chute = 29%) | 39% (11/28) | 50% (14/28) | 46% (13/28) |
| O apontado está entre os 2 melhores reais | 82% | 89% (25/28) | 89% (25/28) |
| O apontado como pior nunca era o melhor ("evita o desastre") | 93% | 96% (27/28) | 96% (27/28) |
| Terço previsto-melhor ÷ terço previsto-pior (conversão real, ~500 compradores/terço) | 1,75x | 2,25x | **2,33x** |

Contra o acaso: composto vs só-modelo dá p = 0,045 (Wilcoxon nos 26 lançamentos), e a
correlação observada está em ~106% do teto de ruído (o máximo que um preditor perfeito
mostraria com esse volume de compradores por unidade). Dentro do lançamento, taxa de
rastreamento e valor por venda multiplicam todas as unidades pelo mesmo fator, então a
ORDEM é imune a elas — o nível, não (ver tabela abaixo).

### Os confundidores do NÍVEL do teto (e o estado de cada um)

`teto = conversão prevista × valor por venda ÷ 2`

| insumo | como obtemos | viés conhecido | estado |
|---|---|---|---|
| conversão prevista | fórmula acima (ordem validada) | **subestima o nível: só ~6 de 10 compradores casam com um lead (rastreamento)** | ÚNICO ponto aberto; ver faixa abaixo |
| valor por venda | medido por janela na mistura real de gateways (cartão a 2k, boleto a 50%) | premissa do boleto a 50% | documentado; melhorável com taxa real de compensação |
| ROAS alvo = 2 | política do negócio | nenhum | fechado (Decisão 2) |

**A faixa do rastreamento:** sem correção, o teto é um PISO (quem paga abaixo garante
ROAS ≥ 2 na parte contada, mas o empate real permite pagar mais). Correção cheia pela
taxa de reconhecimento da planilha do cliente (57,6% a 66,2%, estável; mediana 0,615)
multiplica o teto por ~1,63, mas assume que todo comprador não-casado era lead nosso, o
que corrige demais (parte nunca foi lead: aluno antigo, outro funil).

**Medido em 15/08/2026** (25 lançamentos com 30+ vendas na janela de vendas; 4.517
vendas): 2.034 casaram com lead da captação do próprio lançamento; das 2.483 restantes,
**84% são pessoas CONHECIDAS da base** (existem na espinha de cadastros ou em captação
anterior — compraram pelo funil antigo/outro produto, não pela captação daquele
lançamento) e só 401 (16%) "sumidas" (não existem em lugar nenhum — teto superior das
falhas de casamento, porque inclui também quem comprou direto no checkout sem nunca
preencher formulário). O fator de correção legítimo fica em **×1,18 na mediana por
lançamento (×1,27 nos LF56+)**, contra os ×1,63 da correção cheia e os ×2,22 que a taxa
bruta desta medição sugeriria. A faixa real do nível do teto é **×1,0 (piso) a ~×1,2
(teto defensável)** — a decisão piso × fator medido é de negócio; se adotado o fator,
ele deve ser calculado pelo próprio job da referência na mesma janela e carimbado no
payload, como os demais insumos.

**Como explicar o fator ao cliente (a versão de 30 segundos, aprovada em 15/08):**

> "De cada 100 vendas na janela de um lançamento, 45 a gente liga a um lead daquela
> captação. Se calculássemos o teto só com essas, ele sairia baixo demais e mandaria
> pagar menos do que o lead vale. A tentação era inflar tudo pela taxa de casamento,
> mas fomos conferir venda a venda: 84% das não-ligadas são pessoas que já conhecemos
> e que compraram por outro caminho — aluno antigo, outro produto — e essas não são
> mérito da campanha de captação. Só 16% são compradores que não existem em cadastro
> nenhum, os únicos que podem ser leads nossos que o casamento perdeu. Corrigindo só
> por esses, o fator é 1,2. E mesmo ele é teto, não chute."

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

## Resolvido — O criativo converte diferente por TIPO de campanha?

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

### O confundimento temporal era real, e foi testado

O caso levantado por quem opera: o AD0150 rodou em campanha de Lead **quando era o melhor
criativo e o ML mal existia**; hoje roda nos dois e vai mal nos dois. Logo o "2,50x melhor
no ML" dele era a FASE dele, não o tipo de campanha.

Teste correto: comparar o criativo consigo mesmo **dentro da mesma janela**, e agregar por
Mantel-Haenszel, que junta tabelas estratificadas sem deixar a mistura entre estratos criar
efeito que não existe.

| estratificado por | estratos | leads | razão de chances (ML vs Lead) | p |
|---|---|---|---|---|
| lançamento | 13 | 17.947 | **2,33** | 0,0002 |
| mês | 10 | 31.962 | **2,26** | 0,0000 |

**O efeito sobreviveu.** Controlando a época, campanha de ML converte ~2,3x mais que
campanha de Lead **para o mesmo criativo**.

### Mas 2,3x não é interação: é o modelo funcionando

Antes de dividir a nota por tipo, era obrigatório descartar a explicação óbvia: campanha
de ML **otimiza pelo nosso próprio evento de qualidade**, então o Meta a entrega para quem
o modelo pontuaria alto, e essa gente converte mais **por construção**.

O que separa as duas hipóteses é a **homogeneidade**:

- razão parecida em todo criativo → é efeito de NÍVEL, ou seja, o modelo
- razão que muda por criativo → é interação real, e aí a nota precisa dividir

| criativo | estratos | leads | razão | p |
|---|---|---|---|---|
| DEV-AD0141-vid-captação-V0-PODCAST | 2 | 11.522 | 4,97 | 0,009 |
| DEV-AD0150-vid-captação-V0 | 2 | 6.473 | 5,07 | 0,012 |
| DEV-AD0027-vid-captação-V0-DEV | 2 | 4.052 | 2,42 | 0,050 |
| DEV-AD0160 - VID - CAPTAÇÃO | 2 | 9.176 | 1,66 | 0,034 |
| DEV-AD0135-vid-captação-V0-PODCAST | 1 | 364 | 1,63 | 0,97 |

**Teste de heterogeneidade: qui-quadrado 9,65 com 8 graus, p = 0,29.** As razões não
diferem entre criativos além do acaso.

**Veredito: NÃO dividir a nota por tipo de campanha.** O 2,3x é o mesmo para todo mundo, o
que é assinatura do modelo entregando a pessoa certa, não do criativo se comportando
diferente. E **o teto já captura isso**: campanha de ML traz leads de decil mais alto, e o
teto sai da mistura de decis da campanha. Dividir a nota por tipo contaria o mesmo efeito
duas vezes.

**Ressalva honesta.** São 6 criativos com dado suficiente, então o teste de heterogeneidade
tem pouca força: p = 0,29 é "não há evidência de diferença", não "prova de igualdade". Mas
o ônus da prova é de quem quer dividir, e ele não foi cumprido.

**Onde isso reaparece:** se um dia a nota do criativo passar a alimentar algo que NÃO usa
mistura de decis, a pergunta volta, porque aí o efeito deixa de estar capturado.

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
campanha saiu do plano: foi investigado e o efeito dele já está capturado pela mistura de
decis (ver a seção "Resolvido" acima).

## Decisão 10 — O teto publicado fala a MOEDA DO GERENCIADOR (18/08)

**O problema:** o gestor compara o teto com o CPL que ele vê no gerenciador da
Meta, e as duas contagens de lead divergem de forma sistemática: medido sobre
agosto/2026 inteiro (86 pares unidade-dia com 30+ leads, zero sem par), o
gerenciador conta 20-25% MAIS leads que o nosso banco (razão real÷gerenciador:
mediana 0,82, p10-p90 0,65-0,90, agregado 0,778 na era do pixel novo). Publicar
teto por lead real contra CPL do gerenciador faria o gestor pagar ~22% acima do
teto achando que está dentro.

**A regra:** o teto continua CALCULADO por lead real (a régua honesta); na
publicação, cada linha Meta é convertida: `teto_ger = teto_real × (leads_reais ÷
leads_gerenciador)` **da própria janela do corte**, no grão da própria linha
(campanha, anúncio, anúncio@campanha, anúncio@conjunto@campanha; cópias de
anúncio SOMAM no lado do gerenciador — cópia é o mesmo anúncio).

**Por que a decisão do gestor não muda:** o gasto é o mesmo dos dois lados, e a
razão cancela: `CPL_ger < teto_ger ⟺ CPL_real < teto_real` — identidade
algébrica, não aproximação. Só a moeda do número muda.

**Faixa de sanidade:** razão da própria linha vale se estiver em [0,5-1,5] e
houver casamento; senão a linha usa a razão AGREGADA do corte (selo `ger_agg`).
Linha que não é da Meta (Google, campanha sem |id) fica na moeda real com selo
`moeda_real` — o gerenciador dela é outro. O selo da linha SEMPRE diz qual
razão foi usada (`ger0.84`, `ger_agg0.78`, `moeda_real`).

**Fonte da contagem do gerenciador:** `analytics.ad_insights.leads` = coluna
"Leads" da conta (action_type `lead`, = `fb_pixel_lead`), ingerida por anúncio
por dia. O aviso antigo de "3,1 eventos por lead real" era do pixel velho.

**Como uma linha é reconhecida como do GOOGLE (correção de 19/08):** pelo
carimbo `[G] ` na chave, testado ANTES de qualquer outro critério
(`criativo_historico.tem_carimbo_google`, o mesmo padrão que a chave canônica
usa para tirar o carimbo — um lugar só). O critério anterior era pelo formato da
campanha da Meta (`nome|id`, "tem `|` logo é de lá"), e as campanhas do Google
se chamam `DEVLF | CAP | Dgen | Cold | ...`: **18 das 35 têm barra vertical no
nome**. A linha do Google passava por linha da Meta, não achava par no
gerenciador e caía na razão AGREGADA de lá — 37 linhas publicadas a 0,77 do
valor devido, o teto do Google 23% mais apertado do que a régua manda, no
sentido contrário ao lift de plataforma da Decisão anterior. Ficou escondido
enquanto a campanha do Google chegava como `devlf` (sem pipe) e apareceu quando
o mapa de IDs passou a ter a campanha real de cada colocação. A linha do Google
também ficava DENTRO da média que forma a razão agregada, então contaminava o
teto de anúncios da Meta que dependem dela. Travado em
`tests/test_moeda_do_gerenciador.py`, com os dois casos falhando se a guarda sair.

---

## Decisão 11 — A escada de janelas ROLANTES; nenhuma corta na virada de LF (19/08)

**O gatilho:** na virada do LF64 para o LF65 (17→18/08) o painel da agência foi
de 7 criativos para 1, embora **17 anúncios tivessem atravessado a virada
rodando**, os mesmos. Não foi perda de histórico: o corte de 3 dias era grampeado
no início do lançamento (`max(cap_start, hoje-2)`) e no dia 1 a janela colapsou
para 1 dia; o acumulado era a janela do LF e nasceu vazio junto.

**A regra:** o painel publica QUATRO janelas, todas terminando hoje e contando
para trás, **nenhuma ancorada no calendário**:

| tipo | janela | para quê |
|---|---|---|
| `criativo` / `campanha` (sem sufixo) | 90 dias | o mesmo cálculo do `_historico`, reetiquetado (compatibilidade com o painel deles) |
| `..._historico` | 90 dias | o teto estável do anúncio |
| `..._7dias` | 7 dias | a semana |
| `..._3dias` | 3 dias | o curto prazo que ainda passa do piso de 100 |
| `criativo_hoje` | o dia | o mais fresco que ainda é honesto |

Vale nos quatro grãos (`criativo`, `campanha`, `criativo_campanha`,
`criativo_conjunto_campanha`), todos com o mesmo piso de N = 100.

**Por que zerar deixa de ser problema, sem regra nova:** anúncio que estreou de
fato não tem lead nos dias anteriores, não cruza o piso e simplesmente não
aparece até merecer. Quem continuou rodando mantém a linha inteira. O "só zera
quem começou do zero" é consequência do piso, não de um caso especial.

**Por que 90 dias:** não é escolha de calendário, é o alcance da RÉGUA. A
distribuição de decis só conta lead scoreado pelo champion ATUAL, que começou a
scorear em **25/05/2026** — por isso 90 dias e 180 dias devolvem o mesmo
conjunto. É também a janela em que a referência rolante mede conversão por
decil, valor por venda e fator de rastreamento.

**Por que o sem-sufixo é reetiquetado e não recalculado:** duas contas separadas
para a mesma janela divergiriam na primeira mudança de régua e ninguém saberia
qual está certa — é o erro de escritor×leitor que já custou 9 dias de sinal
neste projeto. A linha do histórico é copiada com o outro rótulo, byte a byte.

**O que sai:** a visão "acumulado DO LANÇAMENTO" deixa de existir neste painel.
Ela continua no relatório interno (Slack/DM), que é onde a pergunta "este
criativo prestou neste LF?" é feita. O painel da agência é ferramenta de compra
de mídia, e para comprar hoje a pergunta é de recência, não de calendário.

**Volume medido no `--check` de 19/08:** 404 linhas (histórico 164, 7 dias 52,
3 dias 25, hoje 1, mais a cópia sem sufixo) contra as 17 que o painel tinha.

---

## Decisão 12 — O cadastro sem pesquisa vale o CRÉDITO medido, não zero (20/08)

**O gatilho:** investigando um teto de R$ 2 (anúncio `[ADVTG_ABERTO]`), a razão
da moeda do gerenciador foi decomposta e mostrou que ela mistura DUAS coisas:

| componente | medido (17-19/08, anúncios 50+ leads) |
|---|---|
| inflação real do gerenciador (cadastros÷ger) | **0,93** — a Meta conta só ~7% a mais |
| taxa de resposta da pesquisa (respondentes÷cadastros) | **0,81** |
| razão usada até 20/08 (respondentes÷ger) | 0,75 — as duas coladas |

Converter o teto por respondentes÷gerenciador assume que o cadastro que não
respondeu vale ZERO — mas ele compra. Medido em **343k cadastros de 27
lançamentos fechados**: conversão de 0,534% contra 0,863% do respondente.

**A regra:** o numerador da razão vira `respondentes + crédito × (cadastros −
respondentes)` — os "leads valorados". O **crédito** é a fração da conversão do
respondente que o não-respondente carrega, **medido toda segunda pelo refresh na
mesma janela madura de 90 dias** (`conversion.survey_coverage` no payload), com
faixa de sanidade [0,10-0,90] e massa mínima (2.000 não-respondentes, 15
compradores). Inválido/ausente → comportamento antigo (crédito zero), nunca
inventa valor. Cadastros da linha vêm de `analytics.captacoes` no mesmo grão
das cestas do gerenciador; contagem menor que a de respondentes clampa (crédito
negativo seria punir a linha por defeito de contagem nossa).

**Por que MEDIDO e não constante:** o valor depende do regime de resposta.
Base cheia (517k cadastros, 27 LFs): crédito **~0,79** no regime antigo
(resposta 53-65%, o não-respondente era gente comum sem pesquisa) e **~0,33**
no regime atual (resposta 83-90%, quem sobra é o desengajado de verdade); os 9
LFs mais recentes deram 0,45. Congelar um número quebraria na próxima mudança
de operação.

**Efeito esperado:** tetos da Meta sobem ~8% na média — mais nos anúncios cuja
audiência responde pouco (o `[ADVTG_ABERTO]`, com 65% de resposta, sobe ~24%).
Google não muda (linha `[G]` é moeda_real; o gerenciador da Meta não conta lead
de lá). O anúncio de teto R$ 2 continua ruim depois da correção (R$ 2,62):
2/3 dos leads dele caem no pior quarto dos decis — a Decisão só tira a punição
indevida, não salva anúncio fraco.

**O que o review adversarial de 20/08 mudou no desenho** (11 achados
confirmados; os que mexiam no número entraram antes do merge):

| achado | conserto |
|---|---|
| crédito medido em TODOS os canais, aplicado só na Meta | medição **só Meta** (`_META_SOURCES`) — medir multicanal e aplicar mono-canal é a armadilha dos baldes (PRs #220/#221), e o lead google converte 1,5× o previsto |
| cadastros contados por INSCRIÇÃO, respondentes por pessoa | `count(DISTINCT email)`: a duplicata da reinscrição virava "não-respondente fantasma" creditado |
| chave dos cadastros = utm_content CRU | traduzida pelo mesmo `mapa_nome` da publicação e canonizada (`chave_canonica`): sem isso o anúncio de macro quebrada ficava sem crédito e o irmão ganhava, com o mesmo selo |
| dedup por email sem ordenação | ordena por `captured_at DESC` (convenção do `build_matured_window`): o crédito mudava entre rodadas sem dado novo |
| cadastro de lançamento ainda vendendo entrava com buy=0 | filtro `limite <= as_of`, o mesmo que `_aplica_janela_do_calendario` faz |
| falha da medição derrubava o refresh inteiro | `try/except` best-effort, como perfil de comprador e histórico de criativo |

**Limitação aceita e explícita:** o teto já embute o fator de rastreamento, que
atribui 100% das vendas "sumidas" aos respondentes casados; a fatia creditada
recebe esse fator junto (~1,7% a mais). Corrigir exigiria decidir a que
população pertencem vendas que não existem em base nenhuma — não há dado para
isso, e distribuí-las proporcionalmente ao total de leads reais é a hipótese
mais defensável das disponíveis. Fica registrado, não corrigido.

Travado em `tests/test_credito_nao_respondente.py` (medição, régua do
calendário, faixa, massa, telefone, só-Meta, janela aberta, determinismo) e
`tests/test_moeda_do_gerenciador.py` (aplicação, fallbacks, clamp, Google
intocado, agregada valorada).

---

*Decisões registradas em 14-20/08/2026. Constantes da nota do criativo em
[NOTA_DO_CRIATIVO_PARAMETROS.md](NOTA_DO_CRIATIVO_PARAMETROS.md).*
