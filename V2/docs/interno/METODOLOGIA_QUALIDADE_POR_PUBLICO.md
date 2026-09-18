# Metodologia — Qualidade dos leads e separação dos modelos, por público

**Criado:** 2026-08-10
**Papel:** receita reproduzível de ponta a ponta para responder três perguntas sobre uma janela de captação: os leads vieram bons? o público quente é melhor que o frio? o modelo consegue separar quem compra de quem não compra?
**Executável:** `scripts/analise_qualidade_publico.py` — a documentação descreve o que o script faz e, principalmente, **por que cada passo é assim**.

---

## Rodar

```bash
cd V2
python -m scripts.analise_qualidade_publico --cap-start 2026-07-21 --cap-end 2026-08-03
```

Saem duas tabelas: qualidade e conversão por público, e capacidade de separação (topo contra base). Com `--json saida.json` o resultado fica em arquivo. Tudo é leitura: nada é gravado no ledger nem no warehouse.

Duas chaves existem para diagnóstico e **não devem ser usadas em número que vá para relatório**:
`--sem-vendas-vivas` (mede só com o warehouse, que atrasa um dia) e `--sem-completar-decil` (deixa a coluna do challenger furada quando ele entrou em produção depois do início da janela).

---

## As sete etapas

### 1. De onde vêm os leads

Fonte: tabela `registros_ml` no Cloud SQL, que é o nosso registro de tudo que foi pontuado. Filtro: data de captura dentro da janela do lançamento.

**Armadilha de fuso.** A coluna `created_at` é `timestamp WITHOUT time zone` gravada em UTC. Converter direto com `created_at AT TIME ZONE 'America/Sao_Paulo'` está errado: o Postgres interpreta o valor como se já fosse horário de Brasília e **desloca três horas para frente**, jogando leads da madrugada para o dia seguinte. O correto é converter de UTC para BRT em dois passos:

```sql
((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'America/Sao_Paulo')::date
```

Para comparação: as colunas de `analytics.cadastros` são `timestamp WITH time zone` e aceitam a conversão simples. Não vale generalizar de uma tabela para a outra.

### 2. O decil de cada modelo

Rodam dois modelos em paralelo: o Champion, que pontua todo mundo, e o Challenger do teste A/B. O ledger guarda o decil dos dois, nas colunas `decil_champion` e `decil_challenger`, mais o identificador de execução de cada um.

**Armadilha de papel.** O papel de um modelo muda com o tempo. O `abr_28` foi Challenger até 25/07/2026 e virou Champion depois. Quem lê a coluna `decil_champion` de forma cega recebe o decil de **modelos diferentes em dias diferentes**, e o número resultante não significa nada. A leitura correta casa sempre pelo identificador de execução:

```sql
CASE WHEN champion_run_id   = '<run_id>' THEN decil_champion
     WHEN challenger_run_id = '<run_id>' THEN decil_challenger END
```

Os identificadores não ficam cravados no script: são lidos de `configs/active_models/{cliente}.yaml`, que é o arquivo que define quem está em produção. É isso que faz a análise continuar correta depois de uma promoção de modelo.

### 3. Completar o decil que falta

Um modelo que entrou em produção no meio da janela não pontuou os leads anteriores. No DEV21 isso atingiu 7.603 dos 24.159 leads, porque o `jul_24` só começou a pontuar em 28/07 e a captação começou em 21/07. Sem completar, a comparação entre os dois modelos é feita sobre populações diferentes, e no caso do público frio a distorção foi grande: 1,23 de lift com a cobertura furada contra 0,98 com a cobertura completa.

O script completa reconstruindo o payload original de cada lead a partir da pesquisa guardada em `survey_responses` e rodando o **mesmo pipeline de produção**, não uma reimplementação.

**Controle obrigatório.** Junto com o modelo que falta, o script recalcula o decil do modelo que **já tem valor gravado** e compara com o ledger. Se a reconstrução do payload estivesse errada, o controle acusaria. O script falha alto se a taxa de acerto não for de 100%. Na apuração de 10/08/2026 o controle deu 7.603 de 7.603.

### 4. Separar quente de frio

O público vive no **nome da campanha**, que chega inteiro no `utm_campaign` porque os anúncios usam a macro `{{campaign.name}}`. A regra é conter a palavra QUENTE ou FRIO.

O que não casa nenhuma das duas vira `sem rotulo`, e isso não é sobra descartável: é Google, orgânico e captação por indicação, que somaram 4.818 leads no DEV21 e converteram mais que os dois públicos pagos.

Vale checar o `utm_medium` junto, porque ele costuma rotular o público de forma ainda mais limpa. No DEV21, 100% do frio tinha `utm_medium = ABERTO` e 100% do quente tinha `ENVOLVIMENTO 365D IG`.

### 5. De onde vêm as vendas

Duas fontes somadas:

- **Histórico:** tabela `analytics.sales`, populada por job diário a partir dos gateways Guru, Hotmart, TMB, Asaas e Boletex.
- **Dia corrente:** consulta viva aos mesmos gateways, pelos carregadores do `SalesDataLoader`.

**Armadilha de atraso.** A `analytics.sales` fica **um dia atrasada**. Em 10/08/2026, dia de abertura do carrinho do DEV21, ela tinha zero vendas do dia mesmo depois de a carga diária ter rodado às 09h32; a venda mais recente nela era das 18h08 do dia anterior. Medir conversão do dia corrente só com o warehouse devolve zero e leva à conclusão de que o lançamento não vendeu. Naquele momento os gateways tinham 164 vendas.

**Consequência para o leitor:** a conversão do dia corrente é uma **foto que se move**. Entre duas execuções separadas por poucas horas no mesmo 10/08, o total foi de 164 para 182 vendas e os casamentos de 132 para 144. Sempre registrar a hora da apuração junto do número.

### 6. Casar lead com venda

Usa `src/validation/matching.py::match_leads_to_sales`, que é o mesmo casador que alimenta a tabela `analytics.validation_metrics`. Ele tenta email normalizado primeiro e telefone depois.

**Armadilha temporal, e é a pior de todas.** O parâmetro `use_temporal_validation=True` é obrigatório. Sem ele o casador aceita compra **anterior** à captura do lead: na apuração do DEV21 apareceram vendas de 2023 casadas com leads de julho de 2026. Isso infla exatamente o público quente, que por definição é feito de gente que já comprou. Com o parâmetro desligado o quente aparecia com 1,018% de conversão, sete vezes o frio; com ele ligado, 0,461%, praticamente empatado com o frio. Uma conclusão de negócio inteira dependia desse booleano.

### 7. As três métricas

**Nota do público** — a fatia de leads que o modelo colocou nos dois decis do topo:

```
%D9-D10 = leads com decil >= 9 / leads com decil daquele modelo
```

Cada modelo tem escala própria. **Comparar o %D9-D10 de um modelo com o de outro não significa nada.** A comparação legítima é de cada modelo contra a régua dele mesmo (etapa 8).

**Taxa de conversão** — leads que casaram com venda dividido por leads do público.

**Capacidade de separação** — é isto que diz se o modelo está fazendo o trabalho dele:

```
lift = taxa de conversão dos decis 9 e 10 / taxa de conversão dos decis 1 a 8
```

Lift 1,00 significa que o topo converte igual à base, ou seja, o modelo não separou nada. Medir isso **dentro de cada público** é o que revela o problema real: no DEV21 o lift agregado era 1,65 e 1,55, mas dentro do público frio caía para 1,08 e 0,98. O lift agregado vinha de o modelo ordenar públicos, não pessoas dentro do mesmo público. Como o público já se sabe pelo nome da campanha, sem precisar de modelo, essa parte do lift não é trabalho do modelo.

---

## A régua de referência (Top 5 ROAS)

Para saber se a nota de uma captação é boa, ela é comparada com os cinco lançamentos de melhor retorno. A referência mora em `configs/reference_audience_profiles/devclub.json`, dentro de `reference_pool`, com uma distribuição por modelo:

| Chave | Régua de qual modelo | %D9-D10 |
|---|---|---|
| `decil_distribution_challenger` | abr_28 | 28,36% |
| `decil_distribution_challenger_variant` | jul_24 | 19,62% |

**Armadilha de amostra.** O Top 5 é composto por LF41, LF43, LF44, LF45 e LF46, cujas captações terminaram em 02/03/2026. O corte de treino do abr_28 é 15/03/2026 e o do jul_24 é 29/04/2026. Ou seja, **a referência está dentro do treino dos dois modelos, na mesma medida**. Só a entrada do jul_24 traz o rótulo `(in-sample)` no arquivo, mas isso é campo não preenchido na outra, não assimetria real. Não usar essa diferença de rótulo para dizer que um número é mais confiável que o outro.

A entrada do abr_28 também está com o identificador de execução **nulo**. Existe uma trava no código de decis que compara esse identificador com o modelo vivo, justamente para não usar régua de modelo aposentado depois de uma promoção. Com o campo nulo, essa trava não protege a régua principal.

---

## Armadilhas em uma tabela

| Armadilha | Sintoma se ignorada | Correção |
|---|---|---|
| Fuso do `created_at` | Leads da madrugada no dia errado | Converter UTC → BRT em dois passos |
| Papel do modelo muda | Compara modelos diferentes achando que é o mesmo | Casar por identificador de execução, nunca pela coluna |
| Modelo novo no meio da janela | Cobertura furada distorce o público mais afetado | Completar com o pipeline de produção + controle |
| `analytics.sales` atrasa 1 dia | Conversão zero, "o lançamento não vendeu" | Somar consulta viva aos gateways |
| Casamento sem validação temporal | Público quente com conversão 7× inflada | `use_temporal_validation=True` |
| Escalas diferentes entre modelos | Ranking falso entre Champion e Challenger | Cada modelo só contra a régua dele |
| Referência dentro do treino | "Este modelo é muito superior" | Tratar como in-sample para os dois |

---

## Conferência da apuração de 10/08/2026

Valores para conferir se uma execução futura sobre a mesma janela continua batendo. A parte de **qualidade é estável** (só depende do ledger); a de **conversão se move** enquanto o carrinho está aberto.

Janela DEV21, captação 21/07 a 03/08/2026, 24.159 leads, cobertura de 100% nos dois modelos.

| Público | Leads | %D9-D10 abr_28 | %D9-D10 jul_24 |
|---|---|---|---|
| quente | 8.451 | 40,97% | 46,75% |
| frio | 10.890 | 24,92% | 17,23% |
| sem rótulo | 4.818 | 41,95% | 37,17% |
| **total** | **24.159** | **33,93%** | **31,53%** |

Conversão às 09h51 de 10/08 (164 vendas no dia, 132 casadas): quente 0,461%, frio 0,422%, sem rótulo 0,976%, total 0,546%. Às 12h30 do mesmo dia (182 vendas, 144 casadas): 0,485%, 0,487%, 1,038%, total 0,596%.

---

## O que NÃO é reproduzível, e por quê

**O treino dos modelos.** O universo de treino é reconstruído a cada rebuild e a versão anterior é destruída. Não dá para regerar o dataset que treinou o `abr_28` em abril nem o `jul_24` em julho. As métricas de treino são lidas do MLflow, que é o único registro que sobrevive.

**A conversão de uma janela já encerrada muda pouco, mas muda.** Boletos compensam depois e reembolsos entram. Um número apurado hoje sobre um lançamento de dois meses atrás não é idêntico ao que foi apurado na época.

---

*Documento operacional. O script é a fonte de verdade do cálculo; este texto é a fonte de verdade do raciocínio.*
