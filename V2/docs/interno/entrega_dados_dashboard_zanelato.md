# Entrega de dados para o dashboard (Zanelato)

Documento de trabalho para desenhar a **view somente-leitura** que vai ser exposta ao time
da Zanelato, com credencial própria. Estado: em definição, nada implementado ainda.

Pedido original: doc **"Dados - Dashboard"**, criado em 04/08/2026 pela Ariane Crosa
(`1EwboNs5ELp-rEELcus7RYYsNLxFp1BSfo3-5WC9K0UY`).

---

## 1. Regra inegociável: score e decil NÃO saem

**Proibido entregar, a qualquer pessoa fora do projeto:**

| Campo | Onde vive |
|---|---|
| `lead_score`, `score` | `registros_ml`, `analytics.leads`, `cadastros`, `lead_legado` |
| `decil` | idem |
| `score_champion`, `score_challenger` | `registros_ml` |
| `decil_champion`, `decil_challenger` | `registros_ml` |
| `decile_propensity`, `decile_roas_v1` | `registros_ml` |
| `hotleads_hot` | `registros_ml` |
| Qualquer nota derivada (A/B/C/D, faixa, quartil, "quente/frio") | - |

**Por que a nota agrupada também está fora:** trocar 10 decis por 4 letras não protege o
método. Com volume, a ordenação é recuperável, e a ordenação **é** o método.

**Conflito direto com o pedido:** o item 3 do doc da Ariane pede literalmente
`"Nota/qualificação do lead (ex.: A / B / C / D, ou lead score)"`. Isso não vai ser
atendido. Precisa de uma resposta explícita para ela, não silêncio na entrega.

**Sobre entregar pesquisa + marcador de compra na mesma tabela:** avaliado e **aceito**.
São gestores de tráfego; o máximo que fazem é um score caseiro cruzando a taxa de
conversão de cada resposta. O risco de reconstruírem o modelo é baixo e os dados já são
obteníveis por outros caminhos.

---

## 2. Escopo definido

| Decisão | Valor |
|---|---|
| Recorte temporal | **somente 2026** |
| Identificador de funil | **`lf`** (o lançamento) |
| Canal (Meta / Google) | **derivado do `utm_source`**, não é campo próprio |
| Formato | view somente-leitura + credencial dedicada |

---

## 3. Aviso sobre `utm_term` (texto aprovado)

> **Atenção ao campo `utm_term`: ele significa coisas diferentes em cada canal.**
>
> No **Meta**, `utm_term` carrega o termo definido no parâmetro da campanha e, na nossa
> operação, ele identifica a **variante do modelo de otimização** usada naquele anúncio.
>
> No **Google Ads**, `utm_term` carrega o **ID numérico da campanha**, não um termo de
> busca. É um número como `23514603013`.
>
> **Consequência prática:** qualquer agrupamento, filtro ou gráfico que use `utm_term` sem
> separar por `utm_source` vai misturar duas grandezas sem relação e produzir números sem
> significado. Se o dashboard precisa de granularidade de criativo, o campo correto é
> `utm_content`: no Meta ele traz o nome do anúncio, e no Google traz o ID do anúncio, que
> a gente consegue traduzir em nome.
>
> **Como o gestor de tráfego pode mudar isso, se quiser:** o `utm_term` do Google é
> preenchido automaticamente pelo próprio Google Ads através do parâmetro `{campaignid}`
> no template de rastreamento da conta. Para que ele passe a carregar algo comparável ao
> Meta, é preciso editar o template de rastreamento (em Configurações da conta →
> Rastreamento) e substituir `{campaignid}` por um valor fixo por campanha, ou por
> `{keyword}` se a intenção original era mesmo o termo de busca. Enquanto o template não
> mudar, nenhum ajuste no dashboard resolve: o dado chega assim da origem.

---

## 4. Situação do "entrou no grupo": dado existe, fluxo está morto

Tabela: **`whatsapp_group_joins`**, no **Railway** (não no Cloud SQL).
Alimentada pelo endpoint `POST /webhook/sendflow_group_join`, tradução em
`api/sendflow_receiver.py`, chave canônica DDD + últimos 8 dígitos.

**112.825 linhas · 101.133 telefones · 98 grupos.** Diagnóstico por origem:

| Fase | Período | Entradas | Ritmo | Grupos |
|---|---|---:|---:|---:|
| `backfill` | 10/03 a **31/05** | 109.252 | **1.316/dia** | 81 |
| **buraco** | **01/06 a 09/06** | **0** | - | - |
| `sendhook` saudável | 10/06 a 13/06 | 3.233 | **~1.060/dia** | 6 |
| `sendhook` degradando | 14/06 a 23/06 | 340 | 34/dia | 2 |
| morto | **24/06 em diante** | **0** | - | - |

Dia a dia da fase sendhook: 255, **1.260**, 973, 745, então **60**, 166, 79, 17, 2, 9, 1,
2, 3, 1.

**Leitura:** o webhook **não** capturava parcial. Ele funcionou no ritmo certo por 4 dias
(o pico de 1.260 bate com os 1.316/dia do backfill) e **quebrou em 14/06**. Depois só
pingou e morreu.

Isso confirma a desconfiança levantada: 3.573 linhas em 13 dias era baixo demais para um
cliente que capta 6 a 8 mil leads por semana com ~80% de entrada no grupo. O número certo
seria da ordem de 1.000/dia, que é exatamente o que aparece nos 4 primeiros dias.

**Decisão:** construir a view primeiro; recuperar o fluxo automático depois. **A view não
deve expor "entrou no grupo" enquanto o fluxo não voltar**: campo congelado em 23/06 e
sem aviso é lido como "não entrou", o que é pior que a ausência do campo.

---

## 5. Mapa das fontes (check-up completo)

### Cloud SQL, schema `analytics`

| Tabela | Linhas | Período | O que tem de útil | O que falta |
|---|---:|---|---|---|
| `captacoes` | 503.438 | 12/2024 a 08/2026 | **grão lead × LF**, nome 89,3%, e-mail 100%, fone 100%, `utm_source`/`utm_campaign`/`utm_content` (98,6%), `ad_base`, `has_computer`, `bought_45d`, `bought_ever` | **sem `utm_medium`, sem `utm_term`, sem URL, sem pesquisa** |
| `leads` | 366.384 | 12/2024 a 08/2026 | **pesquisa em 100% das linhas** (253.474 são de 2026) | `utm_source` só 61,7%, `utm_url` 0%, nome 0% |
| `cadastros` | 454.515 | - | 1 linha por pessoa, **as 5 UTMs**, `is_buyer` | grão errado para lead × LF |
| `sales` | 14.127 | 2022 a 08/2026 | vendas com e-mail, fone, produto, gateway, valor | - |
| `hotleads_seal` | 323.134 | - | selo Hotmart | não entra na entrega |
| `launch_calendar` | 27 | 11/2025 a 08/2026 | janelas canônicas de cada LF | - |

### Cloud SQL, banco `ledger`, schema `public`

| Tabela | Linhas | Período | Observação |
|---|---:|---|---|
| `registros_ml` | 85.491 | **05/2026** em diante | **a mais rica**: 5 UTMs, `utm_url`, pesquisa, nome, fone, `has_computer`. Também tem score e decil, **que ficam fora** |
| `leads_historico` | 202.803 | histórico | pesquisa 100%, 5 UTMs, `tem_computador` |
| `lead_legado` | 142.943 | 18/02 a 14/06/2026 | pesquisa, `page_url` **100%** |
| `scores_historicos` | 221.415 | pré-cutover | só score, **não entra** |

### Railway (banco operacional)

| Tabela | Linhas | Observação |
|---|---:|---|
| `Client` | 135.164 | cadastro do front, `campaignKey`, `isBuyer` |
| `UTMTracking` | 141.989 | 5 UTMs + `url`, 1:N por `clientEmail`, desde 03/2026 |
| `Activity` | 257.014 | log de eventos do lead |
| `whatsapp_group_joins` | 112.825 | grupo, **parado em 23/06** |

---

## 6. Cobertura da URL de captura

Correção de uma avaliação anterior que estava pessimista. A cobertura é **boa**, e o campo
certo não é o que eu havia indicado primeiro.

| Fonte | Período | Cobertura |
|---|---|---:|
| **`registros_ml.utm_url`** (recomendado) | 05/2026 em diante | 88,1% em maio, **100%** de junho em diante |
| `UTMTracking.url` (Railway) | 03/2026 em diante | 92,6% mar · 92,7% abr · 91,9% mai · **100%** jun-ago |
| `lead_legado.page_url` | 18/02 a 14/06/2026 | **100%** |

`registros_ml.utm_url` é o melhor: está na **mesma linha do lead**, sem precisar juntar
tabela. A razão de eu não ter visto antes é o nome: procurei por `url`/`pageUrl` e o campo
se chama `utm_url`.

---

## 7. Como a `captacoes` foi montada (para replicar o critério de UTM)

Gerada por `carrega_captacoes.py` a partir de **`dataset_historico.pkl`**, que consolida as
**planilhas de lançamento** do cliente. Dois movimentos:

1. **Cria `analytics.captacoes`** no grão **lead × LANCAMENTO**. Esse grão existe porque a
   `cadastros` é 1 linha por pessoa, e **11% das pessoas entraram por criativos diferentes
   em lançamentos diferentes**. Colapsar para 1 linha por pessoa perderia **63.305 linhas e
   474 compradores**.
2. **Completa `analytics.cadastros`** preenchendo `utm_*` e `has_computer` **só onde está
   nulo**, marcando `source` com `'+planilha'`. O upsert diário usa
   `COALESCE(EXCLUDED.col, cadastros.col)`, então o preenchimento sobrevive ao cron.

Chave: `chave = email` quando existe, senão `'tel:' + últimos 8 dígitos`.
Primary key `(lf, chave)`.

**Consequência para a view:** a UTM da `captacoes` vem da **planilha**, não do tracking.
É por isso que ela tem `utm_content` em 98,6% mas não tem `utm_medium` nem `utm_term`.
Para ter as 5 UTMs no grão lead × LF é preciso enriquecer a partir de `registros_ml`
(2026-05 em diante) ou `UTMTracking` / `cadastros`.

---

## 8. Pedido dela × o que temos

| Item do doc | Situação | Fonte |
|---|---|---|
| **1. Leads reais** (nome, e-mail, fone, data/hora, URL, funil/canal) | **OK**, com ressalvas | `captacoes` + `registros_ml` |
| nome | 89,3% na `captacoes` | - |
| data e hora com fuso | OK, gravamos em UTC e convertemos para BRT | - |
| URL de captura | 100% de junho/2026 | `registros_ml.utm_url` |
| identificador de funil | **usar `lf`** | `captacoes.lf` |
| canal | **derivar de `utm_source`** | - |
| **2. As 5 UTMs** | **parcial no grão certo** | ver seção 7 |
| `utm_source`, `utm_campaign`, `utm_content` | OK | `captacoes` |
| `utm_medium`, `utm_term` | **só via enriquecimento** | `registros_ml` / `cadastros` / `UTMTracking` |
| **3. Qualificação (nota / lead score)** | **NEGADO** | ver seção 1 |
| respostas da pesquisa | OK, 253.474 linhas em 2026 | `analytics.leads` (100%) |
| data/hora da resposta | a confirmar | - |
| **4. Entrou no grupo** | **NÃO ENTREGAR AGORA** | ver seção 4 |
| **5. Chave de dedupe** | OK | e-mail + `phone8`, mesma chave que casa venda |

---

## 9. Furos e pendências

1. **`utm_medium` não existe na `captacoes`**, que é justamente a tabela com o histórico
   mais longo e o grão que o dashboard precisa. Existe em `cadastros`, `registros_ml` e
   `UTMTracking`, todas com alcance menor.
2. ~~**Não existe um campo único de "funil/canal"**~~ **RESOLVIDO.** Decidido: funil = `lf`,
   canal derivado do `utm_source`. Faltava conferir se o `utm_source` cobre 2026 inteiro, e
   a resposta é: **cobre, desde que se leia dos dois lugares.** A coluna `utm_source` sozinha
   é 0% em janeiro (aquele mês veio de planilha do Google Sheets, que só trazia a campanha).
   O mesmo dado está no jsonb, na chave `'Source'`. Lendo
   `COALESCE(utm_source, survey_responses->>'Source')`:

   | mês | leads | canal identificado |
   |---|---|---|
   | 01/2026 | 16.166 | 99,8% (era 0% na coluna) |
   | 02/2026 | 24.233 | 99,6% |
   | 03/2026 | 59.308 | 99,8% |
   | 04/2026 | 47.439 | 98,8% |
   | 05/2026 | 27.956 | 90,4% |
   | 06/2026 | 31.543 | 99,0% |
   | 07/2026 | 39.603 | 99,5% |
   | 08/2026 | 7.226 | 100% |

   Maio é o mês mais fraco (90,4%) porque foi a virada de sistema: três fontes diferentes
   escreveram no mesmo mês. Os valores são os canais de sempre (`facebook-ads` 194 mil,
   `google-ads` 22 mil, mais cauda de `tiktok`, `manychat`, `youtube-bio`, orgânico), então
   a normalização Meta/Google/outros é direta.
3. ~~**Data e hora da resposta da pesquisa**~~ **RESOLVIDO, e minha leitura anterior estava
   errada.** Eu tinha dito que na `analytics.leads` esse campo era 0% e que precisaria ser
   populado. Não precisa: **está lá, com cobertura de 100%.** O que dá 0% é só a chave
   `submittedAt` dentro do jsonb, porque o escritor canônico (`src/data/leads_unify.py`)
   **renomeia** esse campo. Ele promove a data pra coluna `capturado_em` e guarda a mesma
   informação no jsonb sob a chave `'Data'`. Eu procurei pelo nome inglês e concluí ausência
   onde havia renomeação.

   Medido nas 366.384 linhas da fonte `leads_treino_prod`:

   | | cobertura | com hora real (≠ 00:00:00) |
   |---|---|---|
   | 2024 | 100% | 0% (só data) |
   | 2025 | 100% | 75,2% |
   | **2026** | **100%** | **100%** (253.472 de 253.474) |

   Para o recorte que interessa (2026), **todas** as linhas têm data e hora cheias. A
   precisão varia por procedência, e a diferença é de minutos: para as 141.976 linhas que
   vieram da `Lead` e as 1.613 da `lead_surveys`, o horário É o instante em que a pessoa
   enviou a pesquisa; para as 85.478 que vieram do ledger vivo (`registros_ml`, de 23/05 em
   diante), é o instante de criação da linha, que fica de 1 a 4 minutos depois do envio.
   Irrelevante para o dashboard, mas fica registrado para não parecer inconsistência depois.
4. **`carrega_captacoes.py` vive só em diretório temporário.** A tabela que vai virar a
   base da entrega ao cliente foi criada por um script fora do repositório.
5. **Fluxo do Sendflow a recuperar** depois da view.

---

## 10. Como a tabela de WhatsApp era alimentada (o que a documentação diz)

Duas fontes documentadas, e **nenhuma das duas é automática hoje**.

**a) Exports manuais em CSV (foi a origem do backfill).**
`V2/docs/interno/analise_lift_entrada_grupo_whatsapp.md` registra: *"os 9 exports 'Histórico de
atividades' do SendFlow (`data/devclub/SendFlow*.csv`), evento 'Entrou no grupo', LF48 a
LF56 (~10/03 a 30/05). 97.760 telefones únicos."*

Isso casa exatamente com o que o banco mostra: origem `backfill`, 10/03 a 31/05, 101.133
telefones distintos. **Confirma que a carga histórica dependeu de alguém exportar CSV na
mão do painel do SendFlow.** O período documentado (até 30/05) é o mesmo em que a série
termina.

**b) Webhook Sendhook (a coleta live).**
`V2/docs/INDICE_DOCUMENTACAO.md` descreve como *"coleta live em produção via Sendhook"*, e
`V2/docs/bring_data_02_execução.md:278` tem o item de roadmap *"Criar feature 'entrou no
grupo de whatsapp' (api sendflow)"*. Implementado em `api/sendflow_receiver.py` +
`POST /webhook/sendflow_group_join`. É o que rodou de 10/06 a 23/06 e morreu.

**Conclusão:** a memória de que *"só pela API não conseguimos popular e precisava de ação
manual"* está correta na origem. A ação manual **foi feita** (os 9 CSVs), o webhook
**chegou a funcionar** por 4 dias no ritmo certo, e o que falta hoje é diagnosticar por que
ele parou em 14/06. Nada na documentação explica a parada.

**Nota de inventário:** `V2/docs/interno/RECONSTRUCAO_LEADS_UNIFICADA.md` já lista a
`whatsapp_group_joins` com 112.825 linhas, marcada como fora do `train_unified` porque não
carrega pesquisa. O número não mudou desde então, o que é outra confirmação de que a tabela
está parada.

---

## 11. Nível de acesso: desenho verificado

**Aprovado**, com a exigência de acesso a **nada além da view**. O que foi verificado no
banco, não presumido:

| Verificação | Resultado |
|---|---|
| Versão do Postgres | **15.17** |
| `PUBLIC` tem SELECT em `registros_ml`, `cadastros`, `captacoes`, `leads`, `sales`, `lead_legado`, `scores_historicos`? | **Não.** Todas só com ACL do dono (`ledger_app` / `postgres`) |
| `PUBLIC` pode conectar no banco `ledger`? | **Não.** ACL `=T` concede só TEMP, não CONNECT |
| `PUBLIC` pode conectar no banco `mlflow`? | **Não.** Mesmo caso |
| `PUBLIC` pode conectar nos bancos `postgres` e `cloudsqladmin`? | Podia. **FECHADO em 05/08/2026** (ver abaixo) |
| `PUBLIC` tem USAGE no schema `public`? | Sim (`=U`), mas **sem CREATE** (default do PG 15) e sem privilégio de tabela |

**Furo do CONNECT: fechado.** Por default o Postgres deixa qualquer role autenticada conectar
em todo banco novo. Comprovado antes de mexer: o `ledger_app`, que não tem privilégio nenhum
de banco, **conectava** nos bancos `postgres` e `template1`. Depois de
`REVOKE CONNECT ... FROM PUBLIC` nos dois, ele passou a levar *permission denied* em
`postgres`, `mlflow` e `cloudsqladmin`, e a produção segue lendo o `ledger` normalmente
(85.497 linhas no `registros_ml` conferidas depois da mudança). O `template1` ficou aberto de
propósito: é banco-modelo vazio, sem dado de cliente, e revogar CONNECT nele pode atrapalhar
`CREATE DATABASE`.

**Por que a view protege:** no PG 15, uma view executa com os privilégios do **dono**, não
de quem consulta, a menos que se marque `security_invoker = true`. Portanto **a view NÃO
deve ser criada com `security_invoker`**. Assim o usuário lê a view sem ter, e sem poder
ter, qualquer privilégio nas tabelas base.

**Desenho:**

1. Schema dedicado `dash`, dono `ledger_app`. A view mora só ali.
2. Role `dash_zanelato`: `LOGIN`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOINHERIT`.
3. `GRANT CONNECT ON DATABASE ledger TO dash_zanelato` (obrigatório, porque PUBLIC não
   conecta).
4. `GRANT USAGE ON SCHEMA dash TO dash_zanelato` e `GRANT SELECT` **apenas na view**.
5. **Nada** de USAGE em `analytics`. **Nada** de GRANT em tabela nenhuma.
6. `REVOKE CONNECT ON DATABASE postgres FROM PUBLIC` para fechar o furo da linha 4 da
   tabela acima.
7. **Teste de aceitação obrigatório:** conectar COMO `dash_zanelato` e tentar
   `SELECT` em `registros_ml`, `cadastros`, `captacoes`, `analytics.leads` e
   `scores_historicos`. Todos precisam devolver *permission denied*. Só depois entregar a
   credencial.

**O catálogo: o que é, e como resolver de verdade.** Todo banco Postgres carrega um índice
interno de si mesmo (`information_schema`, `pg_class`, `pg_attribute`), e **qualquer** role
que consiga conectar num banco lê esse índice daquele banco. Ele lista nome de tabela e nome
de coluna, **nunca o conteúdo**. Ou seja: com a senha da view, a pessoa não lê um único
score, mas descobre que existe uma coluna chamada `lead_score`. Não dá para revogar isso sem
quebrar qualquer cliente de banco (o próprio psql precisa do catálogo para funcionar).

O que resolve é mudar de estratégia: **a entrega não fica no banco `ledger`, fica num banco
separado.** Como o catálogo é por banco, um banco que só contém a tabela da entrega tem um
catálogo que só menciona a tabela da entrega. Aí o problema desaparece por construção, em vez
de ser mitigado.

| | View no `ledger` | Tabela em banco `dash` separado |
|---|---|---|
| Lê os dados sensíveis? | Não | Não |
| Vê no catálogo que `lead_score` existe? | **Sim** | **Não** |
| Frescor | Tempo real | O do job (diário basta) |
| Consulta do dashboard compete com produção? | **Sim**, no mesmo `db-f1-micro` | Não |
| Custo | Zero | Um job de refresh |

Vale dizer que a segunda coluna ganha nos dois quesitos que importam, e o preço é um job de
refresh. O ganho de isolamento de carga não é detalhe: a instância é uma `db-f1-micro`, a
menor que existe, e uma consulta mal escrita do dashboard deles hoje disputaria CPU com o
scoring de produção. Recomendo o banco separado. Como view e tabela têm o mesmo formato de
saída, a decisão não muda o esquema de colunas, só onde ele é materializado.

### Segurança da instância: o detalhe fica fora deste repositório

Este documento é candidato a ser commitado, e o repositório é **público**. Descrever
aqui quais defesas da nossa infraestrutura estão abertas seria publicar um mapa de
ataque. Então o estado de segurança da instância vive num documento **privado**, fora
do repositório, no acervo sincronizado do iCloud:

```
claude-config/security/postura_seguranca_bringdata.md
```

Lá está o placar completo, com evidência medida de cada item, o que quebra se
consertar sem cuidado, e o caminho de correção. O que importa saber aqui, e é seguro
dizer: **duas frentes de endurecimento de infraestrutura estão em aberto, e as duas
precisam estar fechadas antes de qualquer credencial sair para a agência.** Isso é
pré-requisito da entrega, não item paralelo.

Do que já foi fechado em 05/08/2026, o que é relevante para esta entrega:

| Item | Estado |
|---|---|
| Conexão ao banco só criptografada (`sslMode = ENCRYPTED_ONLY`) | fechado |
| `PUBLIC` do Postgres não conecta mais em banco que não devia | fechado |
| Credencial de banco fora dos arquivos versionados | PR #141 |

O post-mortem do incidente de credencial que apareceu no meio desta tarefa está
público e completo em [registro_erros_ml.md](registro_erros_ml.md), Erro 20. Vale a
leitura porque a causa-raiz dele (nada verificava, então degradou em silêncio por
meses) é a mesma que justifica o teste de aceitação obrigatório da seção 11 aqui:
sem uma checagem que **falhe**, "só a view está exposta" é esperança, não garantia.

---

## 12. Resposta para a Ariane sobre o score (rascunho)

> Oi Ariane, tudo certo. Sobre a lista, quase tudo a gente entrega, e vou te explicar um
> item que não vai e o que colocamos no lugar dele.
>
> **O que não vai:** a nota ou score de qualificação por lead, item 3 da sua lista.
>
> **Por quê:** essa nota é artefato e produto do meu sistema, e fica sob o meu domínio. Não
> é desconfiança de ninguém, é a mesma regra que vale para todo mundo: essa coluna não sai
> do ambiente do projeto.
>
> **O que vai no lugar, e resolve o mesmo problema:**
>
> - **As respostas completas da pesquisa de perfil, lead por lead.** Faixa etária, renda,
>   objetivo, profissão, nível de conhecimento. É a matéria-prima da qualificação, e com
>   ela vocês montam a segmentação que quiserem no dashboard.
> - **A qualidade agregada por criativo e por campanha**, que vocês já recebem hoje no
>   relatório diário do grupo de tráfego. Ali está a proporção de leads qualificados de
>   cada anúncio, que é justamente o número que orienta decisão de verba. É a mesma
>   informação, no nível em que ela é acionável.
> - **O marcador de compra por lead**, para vocês fecharem o funil do criativo até a venda.
>
> E o mais prático de todos: **se vocês quiserem público na Meta com os leads mais
> qualificados, é só falar que eu crio.** A nota entra na conta do mesmo jeito, o público
> chega pronto na conta de anúncios para vocês usarem em campanha, e vocês têm o efeito que
> queriam sem precisar da coluna.
>
> Para decidir onde colocar verba, o agregado por criativo responde melhor que a nota
> individual: ninguém decide campanha olhando lead por lead.
>
> Se aparecer um caso de uso que você acha que só a nota individual resolve, me manda que a
> gente pensa junto em como atender.

---

## 13. Próximo passo

Os bloqueios da seção 9 caíram: o timestamp da resposta existe (item 3) e o canal cobre 2026
inteiro lendo dos dois lugares (item 2). Sobra **uma decisão sua e um passo mecânico**:

1. **Decidir onde a entrega mora:** banco separado com refresh diário (recomendado, mata o
   vazamento de catálogo e isola a carga) ou view no `ledger` (tempo real, mas o catálogo
   fica visível). A tabela comparativa está na seção 11.
2. **Fechar o esquema de colunas, campo por campo.** Só depois escrever o DDL, o `GRANT` e o
   usuário, e rodar o teste de aceitação (conectar como `dash_zanelato` e exigir
   *permission denied* em `registros_ml`, `cadastros`, `captacoes`, `analytics.leads` e
   `scores_historicos`).

Depois disso, e nessa ordem, recuperar o fluxo automático do Sendflow (seção 4).

**Esquema proposto para a entrega**, com a cobertura já medida em 2026, para você aprovar ou
cortar campo por campo:

| Campo | De onde vem | Cobertura 2026 |
|---|---|---|
| `lead_id` | hash do e-mail (identificador estável, sem expor o e-mail) | 100% |
| `capturado_em` | `analytics.leads.capturado_em` (data e hora) | 100% |
| `lf` | `analytics.launch_calendar`, pela data de captação | 100% |
| `canal` | `COALESCE(utm_source, survey_responses->>'Source')`, normalizado em meta / google / outros | 90 a 100% por mês |
| `utm_campaign`, `utm_content`, `utm_term` | `analytics.leads` | 95 a 100% |
| respostas da pesquisa (uma coluna por pergunta) | `survey_responses` | ~100% |
| `comprou` | cruzamento com `analytics.sales` | marcador booleano |

Fora, por decisão já tomada: **score, decil, e qualquer nota derivada**.
