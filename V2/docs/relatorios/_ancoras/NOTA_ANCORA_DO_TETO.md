# A âncora do teto: dois formatos de referência, e por que o teto encolhe 17% em silêncio

**Escrito em 23/08/2026.** Destinatário: qualquer sessão mexendo no código do teto.
Tudo aqui foi medido contra o banco vivo nesta data, não é dedução.

---

## 1. O que é a "referência" e por que ela decide o teto

O teto é o preço máximo que um anúncio pode pagar por um lead. Para calculá-lo o
sistema precisa de três coisas sobre o negócio:

- **quanto converte**: de cada 100 leads, quantos viram aluno
- **quanto vale uma venda**: o `value_per_sale`
- **quanto de compra atrasada existe**: gente que compra depois do relatório fechar,
  então a conversão medida precisa ser inflada. É o **fator**.

Fórmula em produção (`src/monitoring/teto.py`):

```
teto = conversão × value_per_sale × fator ÷ ROAS_alvo
```

- `conversão` (0 a 1): a taxa esperada da unidade. Vem da mistura de decis daquele
  anúncio naquela campanha.
- `value_per_sale` (R$): quanto entra por venda. Hoje entre R$ 1.294 e R$ 1.362.
- `fator` (adimensional, ≥ 1): a correção de compra atrasada. **É o vilão desta nota.**
- `ROAS_alvo`: a meta, hoje 2,0.

Exemplo real, com a régua do DEV21: `0,8126% × 1.349,61 × 1,2105 ÷ 2 = R$ 6,64`.
Com o fator caindo para 1,0 o mesmo cálculo dá **R$ 5,49**, ou seja **17,4% menos**.

O que muda na prática: um anúncio que pagou R$ 6,00 por lead está **dentro** do teto
de R$ 6,64 e **acima** do teto de R$ 5,49. O veredito inverte sem que nada no anúncio
tenha mudado.

---

## 2. A causa: existem DOIS formatos de referência na mesma tabela

`analytics.reference_rolling`, coluna `conversion` (jsonb). As 10 linhas de devclub,
medidas em 23/08/2026:

| window_end | generated_at | `tracking.factor` | `economics.late_purchase_uplift` | value_per_sale | overall.rate | platform_lift google | survey_coverage.credito |
|---|---|---|---|---|---|---|---|
| 2026-05-30 | 2026-07-29 20:23 | ausente | ausente | 1320,24 | 0,0084130 | ausente | ausente |
| 2026-05-31 | 2026-07-30 21:48 | ausente | ausente | 1320,34 | 0,0084511 | ausente | ausente |
| 2026-06-04 | 2026-08-03 11:27 | ausente | ausente | 1301,57 | 0,0083900 | ausente | ausente |
| 2026-06-11 | 2026-08-10 06:32 | ausente | ausente | 1293,98 | 0,0084344 | ausente | ausente |
| **2026-07-13** | **2026-08-03 19:15** | **ausente** | **1,2105** | **1349,61** | **0,0081262** | ausente | ausente |
| 2026-07-25 | 2026-08-15 13:11 | 1,2467 | ausente | 1362,05 | 0,0075837 | ausente | ausente |
| 2026-07-26 | 2026-08-16 17:26 | 1,2457 | ausente | 1361,86 | 0,0075324 | ausente | ausente |
| 2026-07-27 | 2026-08-17 06:33 | 1,2394 | ausente | 1362,84 | 0,0075644 | ausente | ausente |
| 2026-07-28 | 2026-08-18 20:04 | 1,2364 | ausente | 1357,52 | 0,0076448 | 1,5362 | ausente |
| **2026-07-31** | **2026-08-21 09:16** | **1,2349** | ausente | 1360,44 | 0,0079603 | 1,4856 | **0,3838** |

Chaves de primeiro nível de cada formato:

- **formato ANTIGO** (linha 13/07): `by_bucket, by_channel, by_decile,
  channel_bucket_coverage, economics, late_purchase, overall`
- **formato NOVO** (linha 31/07): `by_bucket, by_channel, by_decile,
  channel_bucket_coverage, conversion_window, economics, overall, platform_lift,
  survey_coverage, tracking`

O formato antigo guarda a compra atrasada em `economics.late_purchase_uplift`.
O novo guarda em `conversion.tracking.factor`. **Nenhuma linha tem os dois.**

---

## 3. A falha silenciosa

`src/monitoring/teto.py:270-272`:

```python
# (conversion.tracking.factor). Referência antiga sem a chave → 1,0.
self._fator = float((conv.get('tracking') or {}).get('factor') or 1.0)
```

O código **já documenta** o comportamento. Lendo uma linha de formato antigo ele não
acha `tracking`, cai no `or 1.0`, e **todo teto sai 17% menor sem levantar nenhum erro,
log ou alerta**. Não há como perceber olhando a saída: os tetos simplesmente vêm menores
e mais anúncios aparecem como "estourou".

O script ad-hoc do DEV21 (`docs/relatorios/dev21_modelo_criativo_teto/scripts/teto_v2.py`,
linhas 30-31) contorna isso sobrescrevendo `conv['tracking']` com o valor pescado de
`economics.late_purchase_uplift`. Ou seja: **o relatório do DEV21 não roda na régua de
produção**, e isso está registrado na METODOLOGIA seção 6 item 12 e seção 9.

---

## 4. Qual linha é a point-in-time de cada lançamento

O leitor é `src/data/reference_reader.py:58`, que faz `ORDER BY window_end DESC LIMIT 1`.
Repare: ele ordena por **window_end**, mas quem decide se a linha já existia é o
**generated_at**. Confundir os dois é o erro fácil aqui.

Regra: a referência que servia um lançamento é a de **maior window_end entre as que já
tinham sido geradas** (`generated_at <= cap_start` do lançamento).

- **LF64** (começou a captar em 07/08): existiam 4 linhas (gen 29/07, 30/07, 03/08 11:27,
  03/08 19:15). Maior window_end entre elas = **2026-07-13**, formato ANTIGO.
- **DEV21** (começou a captar em 21/07): **nenhuma linha tinha sido gerada ainda**. A
  primeira é de 29/07. O relatório do DEV21 usou a de 13/07 (gerada em 03/08, o último
  dia da captação dele) e declarou isso.

Consequência para o LF64: a âncora honesta é a de 13/07, que é **formato antigo**, logo
cai exatamente na armadilha acima.

---

## 5. O risco de sobrescrita, e o congelamento

`analytics.reference_rolling` é **upsert por `(client_id, window_end, source)`**. Uma
foto nova com o mesmo `window_end` **substitui** a anterior, não empilha.

O job agendado é `refresh-rolling-reference-weekly`, `30 6 * * MON`, timezone **Etc/UTC**,
ENABLED. Isso é **03:30 BRT de toda segunda**.

Dois riscos distintos, não confundir:

1. **Sobrescrita da linha-âncora**: baixo. O histórico mostra window_end sempre novo a
   cada rodada (05-30, 05-31, 06-04, 06-11, 07-13, 07-25 a 07-31), então a rodada de
   24/08 deve criar uma linha nova, não pisar a de 13/07. Mas nada no schema impede.
2. **Troca do que a produção serve**: certo. Depois de 03:30 BRT de 24/08 haverá uma
   linha com window_end maior, e `read_rolling_reference` passa a servir ela. Qualquer
   número recalculado depois disso muda, e sem carimbo ninguém sabe por quê.

**Congelamento feito em 23/08:** as 10 linhas estão salvas em
`V2/docs/relatorios/_ancoras/reference_rolling_devclub_congelado_2026-08-23.json`
(65.646 bytes, colunas `client_id, window_end, window_start, as_of, ruler_run_id, source,
n_leads, conversion, calibration, generated_at, audience_profile`). Qualquer reprodução
futura deve ler esse arquivo, não a tabela viva.

---

## 6. Recomendação para quem mexer no código do teto

1. **Fazer o `or 1.0` falar alto.** Ler a referência antiga e assumir fator 1,0 é uma
   decisão silenciosa que muda o teto em 17%. O mínimo é um log de aviso nomeando o
   `window_end` da linha e o formato detectado; o correto é um campo explícito de
   procedência do fator na saída do cálculo.
2. **Aceitar os dois formatos numa camada só.** Uma função que receba o `conversion` e
   devolva o fator, olhando `tracking.factor` e caindo para `economics.late_purchase_uplift`
   antes de chegar em 1,0. Hoje esse fallback existe copiado num script de relatório,
   fora de produção, o que é a definição de duas fontes de verdade para o mesmo número.
3. **Idem para o lift do Google.** O script do DEV21 crava `LIFT_GOOGLE=1.31` e a
   produção tem `calc.lift_da_plataforma('google')`. As linhas de 28/07 e 31/07 trazem
   1,5362 e 1,4856 medidos; a de 13/07 não tem a chave. Mesma decisão silenciosa.
4. **Separar as duas réguas que hoje se misturam.** O teto depende de dois eixos
   independentes: o **fator** (1,0 ou 1,2105) e o **crédito do não-respondente**
   (1,00 no backtest do DEV21, 0 na produção até 20/08, 0,3838 desde 21/08, campo
   `survey_coverage.credito`). Qualquer comparação de teto entre dois períodos precisa
   declarar os dois, senão compara coisas diferentes. A METODOLOGIA seção 9 já mede o
   efeito: a razão de ROAS dentro contra fora do teto cai de 1,73x para 1,50x só
   trocando o crédito.
5. **Point-in-time é `generated_at`, não `window_end`.** O leitor ordena por window_end,
   o que está certo para servir produção, mas errado para reconstruir o passado.
   Qualquer backtest precisa filtrar por `generated_at <= início da captação`.

Ver `V2/docs/relatorios/dev21_modelo_criativo_teto/METODOLOGIA.md` seções 5, 6 (itens 7 e
12) e 9.
