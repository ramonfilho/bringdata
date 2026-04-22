# Erros cometidos — Smart Ads V2

> Registro honesto de decisões erradas, bugs com impacto real e padrões que se repetiram.
> Serve como referência para não repetir os mesmos erros em novos clientes e lançamentos.

---

## Cinco lições fundamentais

1. **Produção não é o lugar de aprender.** Cada bug descoberto ao vivo em vez de antes do deploy foi pago com sinal degradado, dados contaminados ou número errado apresentado ao cliente.

2. **O modelo aprende com o que você decide mostrar a ele — se você não controlar isso, ele decide sozinho.** Sem grupo controle, o sistema criou os próprios dados de treino e entrou em colapso gradual sem que ninguém percebesse por três meses.

3. **A função objetivo errada produz o resultado errado, não importa o quão bom seja o modelo.** O valor enviado ao Meta define o que o algoritmo deles vai otimizar — enquanto esse número estava errado, o resto do sistema estava trabalhando contra si mesmo.

4. **Infraestrutura boa não substitui definição clara do problema.** O refactor, o YAML multi-cliente, o `src/core/` — tudo isso é sólido. Mas foi construído depois dos erros, não antes. Escalar para novos clientes exige inverter essa ordem: definir o problema corretamente primeiro, construir a infraestrutura em cima disso.

5. **Você não pode confiar em um número que nunca foi conferido contra a realidade.** O relatório que prova o valor do sistema para o cliente acumulou erros de cálculo durante meses porque ninguém tinha um total de referência externo para comparar. Um número só é confiável quando existe outro número independente que deveria bater com ele — e esse check precisa ser automático.

---

---

## Erros estratégicos e operacionais

### 1. Cálculo errado do valor de conversão enviado ao Meta

O valor enviado ao Meta para cada lead (o sinal que o algoritmo usa para otimizar) foi calculado de forma incorreta em diferentes momentos, por razões distintas.

**Primeira forma:** os valores por decil estavam definidos como uma tabela fixa hardcoded. O problema é que ela não refletia o produto em venda nem o ticket real — era um número arbitrário descolado da realidade do negócio.

**Segunda forma (15/03/2026):** ao corrigir o formato das chaves de configuração, o mapeamento de `D1–D9` para `D01–D09` foi feito errado, causando valores nulos em 9 dos 10 decis por alguns dias.

**Terceira forma (22/03/2026):** a correção definitiva foi calcular o valor em runtime como `ticket_médio × taxa_de_conversão_do_decil`, eliminando a tabela hardcoded. Mas a fórmula de `ticket_médio` ainda usava a média simples em vez do ticket real ponderado entre Guru (venda à vista) e TMB (parcelado com inadimplência).

**Correção final (03/04/2026):** fórmula ajustada para usar o ticket Guru real e aplicar o fator de realização do TMB. Só então o número ficou correto de ponta a ponta.

---

### 2. Bugs de encoding e divergência treino/produção

Três clusters distintos ao longo do período, cada um com sua causa raiz.

#### Cluster 1 — Bugs isolados de encoding (Jan/2026)

Durante o bootstrap do sistema, vários problemas de encoding foram encontrados e corrigidos de forma pontual, sem uma causa raiz comum:

- **07/01:** features de Medium estavam sendo codificadas duas vezes, duplicando o sinal.
- **09–11/01:** encoding ordinal de `idade` e `faixa_salarial` estava quebrando porque o nome da coluna no YAML não correspondia ao nome real no DataFrame.
- **09–11/01:** o valor `NÃO` em maiúsculo em "Tem computador?" não era normalizado, gerando uma categoria nova a cada lançamento.
- **17/01:** a normalização de `'consegui'` para `'conseguir'` estava ausente — o modelo criava uma feature morta que nunca havia existido no treino.
- **17/01:** `utm_source` não estava sendo normalizado para lowercase, gerando variantes duplicadas (`Facebook-Ads`, `facebook-ads`) como features distintas.

#### Cluster 2 — Divergência sistêmica treino/produção (15/03/2026)

O maior bug de encoding do projeto. Ao ativar um novo modelo treinado com o refactor, percebeu-se que treino e produção aplicavam regras diferentes para encoding, Medium e UTM — divergências que estavam no código há meses, mas mascaradas porque o modelo anterior havia sido treinado e servido com as mesmas regras erradas. Com a troca de modelo, a divergência ficou visível: o score em produção não correspondia ao esperado pelo treino. Corrigido na mesma data, mas o modelo precisou ser retreinado para garantir consistência.

#### Cluster 3 — Medium_Linguagem_programacao zerada (13/04/2026)

Um bug silencioso de encoding fazia com que a coluna `Medium_Linguagem_programacao` — a 5ª feature mais importante do modelo (5,31% de peso) — fosse preenchida com zero para 100% dos leads desde que o modelo foi implantado. O bug não causava erro explícito, apenas eliminava o sinal dessa feature. Descoberto ao investigar a queda de D10% após o rollback: mesmo com o modelo correto, o D10 estabilizou em ~30% em vez de retornar aos ~42% de P1. A correção foi aplicada em 13/04/2026.

---

### 3. D9 com 0% — decil não enviado ao Meta por ~2 meses

Um bug de comparação de strings fazia com que o decil D9 fosse sempre tratado como ausente: o código comparava a string `'D9'` mas o sistema formatava os decis como `'D09'`. O resultado prático é que nenhum lead classificado como D9 gerava evento CAPI durante aproximadamente dois meses.

**Detectado e corrigido em 18/02/2026.** Não havia alerta automático para esse tipo de falha — só foi encontrado ao auditar os dados de distribuição de decis no banco.

---

### 4. Deploy de novo modelo com 100% de tráfego imediato

Em 15/03/2026, um novo modelo foi ativado com 100% do tráfego de produção sem nenhuma estratégia de canário ou rollback gradual. O modelo tinha sido treinado com parâmetros diferentes (TMB All) e a divergência de paridade treino/produção descrita no item 2 veio à tona exatamente nesse momento: D10 colapsou de 20% para 5% em 48 horas.

O rollback para o modelo anterior (jan30) precisou ser feito manualmente alguns dias depois, após análise e confirmação de que o problema era o modelo novo, não a audiência. O tempo de exposição com sinal degradado foi de aproximadamente 10 dias.

A lição direta: qualquer novo modelo deve ser ativado primeiro para 5–10% do tráfego (canário), com monitoramento de D10% e AUC em produção antes de escalar.

---

### 5. Mudança de estratégia de evento de otimização com 100% do orçamento

Em 10/03/2026, o evento de otimização das campanhas foi migrado de `LQHQ` (enviado apenas para leads D9–D10, sinal de topo) para `LQ` (enviado para todos os decis com valor proporcional). A mudança foi feita de uma vez, em todas as campanhas simultaneamente, sem grupo de controle e sem período de transição.

O Meta interpreta os eventos que recebe como exemplos do perfil que deve buscar. Com o sinal mudando de "busque perfis de alta propensão" para "busque qualquer perfil com valores distribuídos", o algoritmo recalibrou para uma audiência mais ampla. O D10% caiu de ~42% para ~30% em dois dias.

A lição: mudanças de evento de otimização — especialmente aquelas que alteram o perfil aprendido pelo Meta — deveriam ser testadas em um subconjunto de campanhas ou com budget reduzido antes de serem aplicadas ao portfólio inteiro.

---

### 6. Ausência de grupo controle — feedback loop não detectado

O modelo foi treinado em dados produzidos por ele mesmo: ao classificar leads em D10 e direcionar o orçamento para esse perfil, o Meta passou a entregar cada vez mais leads com esse perfil, que por sua vez eram super-representados no próximo treino. O D10 chegou a 41% dos leads no LF45 (esperado: ~10%), indicando que o modelo estava otimizando para um público progressivamente mais estreito.

O feedback loop estava ativo desde os primeiros lançamentos com o sistema ligado, mas só foi diagnosticado na reunião de 11/03/2026. O grupo controle (10–20% do budget fora do ML) foi ativado apenas em 15/03/2026 — ou seja, o modelo rodou em loop fechado por aproximadamente 3 meses antes da correção estrutural.

O retreino com importance weighting (pesos maiores para leads da campanha de controle) está pendente para corrigir o viés acumulado no dataset.

---

## Erros de implementação e infraestrutura

### 7. Erros sequenciais de código durante o bootstrap (Nov/25–Fev/26)

No período de construção inicial do sistema, uma série de bugs pequenos foram corrigidos de forma reativa — cada um descoberto só quando algo parava de funcionar em produção. A maioria não era bug de lógica de negócio, mas de infraestrutura, configuração ou integração:

- **Conexão com banco de dados com configuração errada (18/11/25):** o servidor de banco de dados espera ser acessado de uma forma específica quando está rodando na mesma máquina. O parâmetro de conexão estava errado, então nenhuma consulta chegava ao banco.
- **Envio CAPI quebrando ao processar a lista de eventos (20/11/25):** o código tentava iterar sobre um número inteiro pensando que era uma lista — crash silencioso que interrompia o envio sem registrar o erro de forma clara.
- **Leads sendo enviados ao Meta em duplicata (24/11/25):** não havia nenhum controle para verificar se um lead já havia sido enviado antes. Em caso de reprocessamento, o mesmo lead era enviado várias vezes.
- **FBP/FBC não capturados antes do formulário ser submetido (19/11/25):** o FBP e FBC são cookies que o Meta usa para identificar o usuário e dar crédito ao anúncio. A landing page só os enviava ao servidor depois que o formulário era completamente preenchido — se o usuário abandonasse no meio, os cookies se perdiam. A solução foi enviar os cookies assim que o usuário chegava na página, antes de qualquer interação.
- **Crash ao processar um único lead (15/02/26):** o passo de encoding categórico só funcionava corretamente com dois ou mais leads. Com um único lead, o código quebrava silenciosamente sem gerar score.
- **Token da API Guru com caractere especial quebrando o carregamento (23/03/26):** o token de autenticação da Guru contém o caractere `|` no meio. A forma padrão de carregar variáveis de ambiente no terminal interpreta esse caractere como separador de comando — então o token era truncado na hora de ler. Só funcionava usando a biblioteca Python de carregamento de `.env`, nunca via terminal.
- **Credenciais não carregadas quando scripts eram chamados diretamente (23/03/26):** o carregamento das credenciais do arquivo `.env` estava presente em alguns pontos de entrada do sistema mas ausente em outros. Scripts chamados diretamente da linha de comando rodavam sem as credenciais de banco de dados e Meta, falhando sem mensagem de erro clara.
- **Modelo salvo em pasta diferente da que o servidor buscava (12–13/01/26):** o pipeline de treino salvava os artefatos do modelo em um caminho; o servidor de produção e o Dockerfile buscavam em outro. Resultado: qualquer deploy novo subia sem o modelo, e o servidor iniciava em estado inválido.
- **ID do experimento MLflow hardcoded (22/03/26):** o identificador do experimento de ML no sistema de rastreamento estava fixo no código. Quando um novo experimento era criado (novo cliente, novo contexto), o sistema continuava usando o ID antigo e registrava os runs no lugar errado.

O padrão comum: cada componente novo (banco, CAPI, MLflow, deploy) estreou com pelo menos um bug de integração que só apareceu em produção. A causa raiz é ausência de testes de integração no período de bootstrap.

---

### 8. Migração de banco de dados sem inventário dos pontos de integração

O sistema usava inicialmente o banco de dados Cloud SQL (Google Cloud). Quando ele foi descomissionado e o banco migrou para o Railway, a migração foi feita trocando o arquivo central de conexão — mas sem mapear previamente todos os lugares do código que dependiam desse banco.

O resultado foi três bugs em dois dias:

- **25/02/2026:** as rotas de monitoramento da API ainda pediam uma conexão ao banco antigo a cada requisição. O banco antigo não existia mais, então qualquer chamada ao monitoramento retornava erro.
- **25/02/2026 (mesmo dia):** removida a dependência do banco antigo dessas rotas, mas sem garantir que as rotas passassem a usar o novo.
- **26/02/2026:** após o monitoramento ser corrigido para consultar o Railway, a query que buscava os dados de cobertura de cookies (FBP/FBC) estava cruzando as tabelas de forma errada — o resultado aparecia como 0% para todos os leads, independentemente do real.

Três correções em dois dias para a mesma mudança. A causa raiz foi fazer a migração de banco sem antes mapear todos os pontos do sistema que faziam consultas — o que teria permitido atualizar tudo de uma vez de forma coordenada.

---

### 9. Cobertura de cookies no monitoramento — quatro tentativas para acertar o cálculo

FBP e FBC são cookies que o Meta instala no navegador do usuário ao clicar em um anúncio. Quando o lead é enviado ao Meta via CAPI com esses cookies, o Meta consegue identificar com certeza que aquele lead veio de um anúncio específico — o que melhora significativamente a qualidade do sinal. O sumário de monitoramento exibia o percentual de leads com esses cookies para acompanhar essa cobertura.

O percentual estava sendo calculado de forma errada de maneiras diferentes, e todas as correções aconteceram no mesmo dia (03/04/2026), em sequência:

1. **Primeira tentativa:** a consulta ao banco buscava todos os leads da tabela sem filtrar pelo período do lançamento atual — o percentual refletia o histórico inteiro, não os últimos dias.
2. **Segunda tentativa:** o filtro de período foi adicionado, mas o total usado como denominador ainda era o da tabela inteira. O numerador estava correto (leads com cookie no período), mas o denominador estava errado (todos os leads de sempre) — o percentual saía artificialmente baixo.
3. **Terceira tentativa:** o denominador foi corrigido para o período, mas a consulta trazia o mesmo lead mais de uma vez quando ele havia sido atualizado no banco. O percentual saía inflado porque o mesmo lead com cookie era contado várias vezes.
4. **Quarta tentativa (correta):** deduplica por email antes de contar, usa o período correto tanto no numerador quanto no denominador, e cruza as tabelas pela coluna certa.

O padrão aqui é típico de cálculo incremental sem um número de referência conhecido para validar: cada correção resolvia um problema mas criava outro porque não havia como confirmar qual era o valor correto antes de terminar.

---

### 10. Fuso horário — bugs recorrentes em componentes diferentes

Bancos de dados e APIs externas geralmente armazenam datas em UTC (horário de Greenwich). O Brasil está em UTC−3, o que significa que um lead que entrou às 23h de segunda no horário de Brasília aparece no banco como 02h de terça em UTC. Quando o código comparava datas sem levar isso em conta, leads eram descartados ou atribuídos ao dia errado.

O mesmo bug de fuso horário apareceu três vezes em componentes diferentes:

- **17/01/2026:** o monitoramento comparava os timestamps do banco (UTC) com as datas do Google Sheets (que estavam no horário de Brasília) sem converter. Leads das últimas horas do dia apareciam como se fossem do dia seguinte, e o monitoramento os ignorava como "fora da janela".
- **18/02/2026:** ao filtrar leads por data no Google Sheets, o código aplicava a correção de fuso no sentido errado — adicionava 3 horas em vez de subtrair, jogando os leads para uma janela ainda mais distante.
- **19/02/2026:** o Railway (banco principal de produção) armazenava os horários de criação dos leads em UTC, mas o código de monitoramento comparava esses horários com a hora atual do servidor sem converter — leads criados entre 21h e meia-noite nunca apareciam no sumário do dia correto.

A causa raiz é que nunca foi estabelecida uma convenção explícita de fuso horário para o sistema. Cada integração nova tratou o problema de forma independente, resultando em comportamentos inconsistentes entre componentes.

---

### 11. UTM Source: origens de tráfego não mapeadas criando variáveis fantasma no modelo

O `utm_source` identifica de onde veio o lead — `facebook-ads`, `instagram`, `google-ads`, etc. O modelo aprende a partir das origens que existiam no treino. Se em produção aparece uma origem nova que nunca existiu no treino, o modelo não sabe o que fazer com ela e cria uma variável nova com valor zero para todo mundo — ruído que interfere no score sem nenhum benefício.

Três correções pontuais ao longo de dois meses, todas reativas — o problema só foi descoberto quando a origem nova apareceu nos dados:

- **20/02/2026:** `'ig'` (abreviação informal de Instagram) e `'manychat'` (ferramenta de automação de mensagens) não estavam na lista. O sistema os tratava como origens desconhecidas.
- **25/02/2026:** `'org'` (abreviação de orgânico) adicionado pelo mesmo motivo.
- **26/02/2026:** campo `utm_source` completamente vazio também criava uma variável fantasma — leads sem UTM precisavam ser tratados como `nulo`, não como uma categoria chamada `""`.

A causa raiz é que a lista de origens conhecidas era estática e precisava ser atualizada manualmente sempre que uma nova tag de UTM aparecia nas campanhas. Qualquer origem nova que escapasse da lista criava ruído silencioso no modelo sem disparar nenhum alerta.

**Reincidência em UTM Term — 22/04/2026.** A mesma lição se repetiu em outro eixo. O sistema agrupa termos não-reconhecidos em `'outros'` via regra de fallback em `core/utm.py`. A condição tinha uma exceção para preservar códigos numéricos curtos, mas nenhuma categoria numérica existia na whitelist de treino — a exceção só criava uma brecha. Em produção, o valor `utm_term='0405'` começou a aparecer (669 leads/dia, 16% do volume) e escapava para o modelo como categoria inédita, saindo do encoding com todas as três features de Term zeradas — combinação nunca vista no treino. O monitoramento detectou a categoria nova corretamente, mas a lógica da unificação continuava deixando escapar. Registrado como DT-13 em `PLANO_REFACTOR_MLOPS.md` §11 com fix de uma linha (remover a exceção numérica). Lição: regras de unificação UTM precisam ser *whitelist* estrita — o que não está na lista vai para `'outros'`, sem ramos condicionais que "preservam" casos específicos.

---

### 12. Dataset de treino com dois erros silenciosos de preparação

Dois bugs na forma como o dataset de treino era construído, corrigidos em 06/03/2026. Ambos existiam desde o início do projeto mas só foram identificados durante a auditoria do refactor.

**Janela de conversão com corte assimétrico:** o modelo aprende quem comprou e quem não comprou em um determinado período. Para que isso seja justo, é preciso dar o mesmo tempo de observação para todo mundo — se o período de análise vai até o dia X, leads que chegaram perto do dia X simplesmente não tiveram tempo suficiente para comprar. O correto é remover do dataset todos os leads que chegaram tarde demais, independentemente de terem comprado ou não.

O que o código fazia: removia do dataset apenas os compradores que chegaram tarde. Os não-compradores que chegaram no mesmo período ficavam — criando uma ilusão de que "leads que chegaram perto do fim raramente compram", quando na verdade eles simplesmente não tiveram tempo. O modelo aprendia um padrão falso.

**Filtro de risco TMB aplicado na ordem errada:** a TMB é uma plataforma de parcelamento. Alguns compradores TMB têm histórico de inadimplência — esses não deveriam ser tratados como "compradores reais" no treino, porque a venda não se concretizou de fato. O sistema tinha um filtro para excluir esses casos.

O problema: o filtro era aplicado depois de o sistema ter cruzado leads com vendas e marcado quem comprou. Então esses compradores inadimplentes já estavam marcados como "comprou = sim" antes de serem filtrados, e ao sair do dataset simplesmente desapareciam — deixando o sinal positivo com menos exemplos do que deveria, mas sem remover os casos contaminados que já haviam influenciado a distribuição. A correção foi aplicar o filtro antes do cruzamento com vendas.

---

### 13. Relatório de validação com contagens e receitas imprecisas

O relatório de validação compara o desempenho de campanhas com e sem ML — é o principal documento para provar que o sistema gera resultado. Ele acumulou erros de cálculo ao longo de meses, todos descobertos de forma reativa ao comparar os números com os dados reais do lançamento:

- **28–30/12/2025:** a contagem de leads usava os dados já processados pelo sistema em vez da fonte original do Meta — em alguns casos com deduplicações aplicadas de forma diferente, fazendo os totais não baterem. Além disso, a lógica de atribuição de qual campanha gerou qual lead estava identificando a campanha pelo seu ID numérico sozinho, quando o correto era usar a combinação de ID + conta anunciante — em contas com múltiplas campanhas, leads eram às vezes atribuídos à campanha errada. Por fim, vendas com status "não aprovado" no Guru (pagamentos recusados, estornados) estavam sendo contadas como conversões reais.
- **17/01/2026:** ao cruzar os relatórios exportados manualmente da Meta com os dados puxados via API, o mapeamento de qual conta correspondia a qual anunciante estava errado — os números de campanhas diferentes se misturavam.
- **01/04/2026:** a consulta ao banco que contava os leads da pesquisa tinha um limite interno de 10.000 registros. Lançamentos maiores eram truncados silenciosamente — o relatório mostrava 10.000 leads quando havia 15.000, sem nenhum aviso.
- **02/04/2026:** a receita da Asaas (plataforma de pagamentos) estava sendo somada com duplicatas em alguns cenários; e a tabela de evolução histórica entre lançamentos estava calculando variação percentual a partir de bases diferentes.
- **03/04/2026:** fórmula de faturamento usando ticket médio em vez do ticket real — ver item 1.
- **08/04/2026:** ajustes adicionais nos filtros de valor de venda mínimo e no tratamento de vendas parcialmente pagas via Asaas.

O padrão: o relatório foi construído adicionando uma fonte de dados por vez (Guru, depois TMB, depois Asaas, depois Meta API) sem criar um teste de consistência que comparasse o total calculado com os números reais a cada adição. Os erros só apareciam quando alguém comparava o relatório com o número real do lançamento manualmente.
