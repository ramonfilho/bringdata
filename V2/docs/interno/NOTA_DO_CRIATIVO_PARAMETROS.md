# A nota do criativo: as três constantes, e como mudá-las para outro cliente

Documento curto e de consulta. Explica os três números que governam a nota do criativo,
como cada um foi escolhido, e o que precisa mudar quando um segundo cliente entrar.

O código vive em `V2/src/core/nota_criativo.py`. Os testes que travam as decisões abaixo
vivem em `V2/tests/test_nota_criativo.py`.

---

## O que a nota é

Um número por criativo que diz **quanto ele convertia antes da semana em que o lead
entrou**. Entra no lugar do nome do anúncio, que o pipeline remove de propósito (nome de
anúncio como categoria faz o modelo decorar lançamento em vez de aprender sobre a pessoa).

```
lift  = conversão do criativo ÷ conversão do período
peso  = n ÷ (n + K)
NOTA  = peso × lift + (1 − peso) × alvo
```

- `n` = quantos leads aquele criativo já trouxe no histórico **maduro**
- `alvo` = para onde a nota é puxada quando falta histórico próprio (o neutro 1,0, ou o
  palpite pela fala do vídeo)
- `NOTA = 1,0` significa "converte como a média do período". Acima é melhor, abaixo é pior.

---

## Constante 1 — `K_ENCOLHIMENTO = 4000`

**O que faz.** Define quantos leads um criativo precisa ter para a conversão dele própria
começar a mandar na nota. É o `K` da fórmula do peso: com `n = K`, o peso é exatamente
0,5, ou seja, metade da nota vem do histórico e metade do alvo.

**Como foi escolhido.** Varredura de 0 a 16.000 em passos de 250, avaliando a nota
composta com o modelo. 4.000 venceu; 2.000 empata dentro do ruído. Nada foi ajustado à
mão.

**Por que ele não pode ser zero.** Sem encolhimento (`K = 0`) todo criativo recebe a
conversão crua dele, e a nota fica **pior que chutar a média**: um criativo com 300 leads
e 9 compradores receberia nota 3,0 e sequestraria o ranking inteiro.

**O que 4.000 significa neste cliente** (medido na semana de 04/05/2026, 287 criativos
acima do piso):

| faixa | criativos | % do volume de leads |
|---|---|---|
| peso ≥ 0,50 (o histórico próprio manda) | 14 (4,9%) | 67,3% |
| peso ≥ 0,25 | 37 (12,9%) | 83,8% |
| peso ≥ 0,10 | 66 (23,0%) | 90,6% |

O criativo **mediano** tem 144 leads, o que dá peso 0,035: **96,5% da nota dele vem do
alvo, não do histórico próprio**. O maior tem 57.840 leads e peso 0,935.

**Consequência que vale registrar:** como o alvo domina na maioria esmagadora dos
criativos, a qualidade do alvo importa mais que a da conversão própria. É exatamente por
isso que trocar o alvo cego 1,0 pelo palpite da fala do vídeo respondeu por **+16 dos +29**
compradores ganhos no topo 30%. Um `K` alto e um alvo bom são duas faces da mesma decisão.

---

## Constante 2 — `JANELA_DESFECHO_DIAS = 21` (e a carência, que é o mesmo número)

**O que faz.** Define em quantos dias depois da captação uma compra ainda conta para o
criativo, **e** quantos dias de histórico recente são descartados no cálculo.

**Por que os dois são o mesmo número, por construção.** Um desfecho de W dias só existe W
dias depois. Usar carência menor que a janela devolve vazamento pela porta dos fundos: ler
um desfecho de 45 dias com carência de 21 deixaria 24 dias de futuro dentro da nota.
No código a carência **deriva** da janela em vez de ser constante própria, e há um teste
(`test_carencia_e_janela_do_desfecho_sao_o_mesmo_numero`) que quebra se alguém baixar só
uma das duas.

**Por que 21 e não 45.** A compra tem mediana de 13 dias; 21 cobre 73% delas contra 85,8%
de 45. Como a nota é uma **razão**, perder comprador tardio no numerador e no denominador
se cancela. O que 45 custava era **cobertura**: derrubava a fração de leads com nota de
82,5% para 49,8%, e metade dos leads em nota neutra é onde o ganho morria.

Medido em 67 mil leads: com 45 o composto dava AUC 0,6510 e 71 compradores no top 10%;
com 21 dá 0,6763 e 79 (modelo sozinho: 0,6348 e 61).

---

## Constante 3 — `MIN_HIST = 50`

**O que faz.** Piso de leads para o criativo ganhar nota própria. Abaixo disso ele fica
neutro.

**Por que existe mesmo com o encolhimento.** O encolhimento já protege contra nota
extrema, mas abaixo de algumas dezenas de leads a conversão observada é quase toda ruído
de amostra, e a nota resultante não carrega informação nenhuma — só custa uma consulta.

Constante irmã: `MIN_HIST_PERIODO = 20_000`, o mínimo de leads no passado para a semana
inteira ser calculável. Sem ela, as primeiras semanas do histórico produziriam uma
"conversão do período" instável, e como ela é o **denominador** do lift, todo o lift da
semana sairia distorcido.

---

## Como parametrizar para um segundo cliente

Hoje as três constantes são **módulo-nível** em `nota_criativo.py`, o que é adequado
enquanto há um cliente só. Quando o segundo entrar, elas viram campos do `ClientConfig`,
seguindo a regra do projeto de que nenhum valor específico de cliente mora dentro de
`src/core/`.

O caminho, quando chegar a hora:

1. Criar uma sub-config (algo como `nota_criativo:` no `configs/clients/<cliente>.yaml`)
   com `k_encolhimento`, `janela_desfecho_dias` e `min_hist`, todos com **valor default
   igual ao de hoje** — assim o DevClub não sente a mudança.
2. `adicionar_nota_criativo()` passa a receber a sub-config em vez de ler as constantes
   do módulo. A carência continua **derivada** da janela dentro da função, nunca exposta
   como campo próprio no YAML: expor os dois convida alguém a configurá-los diferentes e
   reabre o vazamento.
3. Rodar a varredura de `K` no histórico do cliente novo antes de aceitar o 4.000. O valor
   depende do volume típico por criativo, que é justamente o que muda entre clientes: um
   cliente com criativos de 500 leads precisa de `K` muito menor para que o histórico
   próprio pese alguma coisa.
4. A janela de 21 dias depende do **ciclo de compra** do produto, não do volume. Medir a
   mediana de dias entre captação e compra no cliente novo antes de reusar o número.

**O que NÃO parametrizar:** a igualdade entre janela e carência. Ela não é preferência, é
correção; deixar configurável só cria a chance de alguém desalinhá-las.

---

## Referência rápida dos resultados medidos

Conjunto de teste de 75.551 leads, 658 compradores, mesma régua para todos:

| composição | AUC | compradores no topo 30% |
|---|---|---|
| modelo sozinho | 0,7365 | 413 |
| modelo × nota por canal | 0,7546 | 426 |
| nota como feature dentro do modelo | 0,7541 | 438 |
| **modelo × nota por canal e texto** | **0,7575** | **442** |

A última é a única cujo intervalo de confiança de 95% não toca o zero (97,8% das
reamostragens de criativos inteiros deram ganho positivo).
