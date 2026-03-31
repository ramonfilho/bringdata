# Notas:

1. [Google offers $350,000 in credits for startups that use AI and already had investment to use it’s tools](https://cloud.google.com/startup/ai?hl=pt_br)  
   2. *“Quais são os dados mais estratégicos que permitirão diferenciação para a estratégia de AI e como podemos gerar ou aproveitar esses dados dentro da empresa para desenvolvê-los?”*  
   3. Nadella argumenta o valor surge quando você usa o modelo para orquestrar um fluxo de trabalho complexo. Essa capacidade de orquestrar múltiplas ferramentas de forma inteligente para completar um objetivo de negócio é onde a "mágica" acontece.  
   4. Quanto mais você aprofunda a integração com as fontes de dados do cliente (pesquisa, TMB, Guru, WhatsApp), mais insubstituível você fica.  
   5. Moat / Valor do negócio:  
      1. Objeção perpétuo: funciona para perpétuo com produto médio/alto ticket — não é só lançamento.  
      2. Barreiras de entrada (por que é difícil de copiar)  
         1. É diferente de análise de dados por LLM — LLM não otimiza campanhas em tempo real.  
         2. Barreira técnica: não basta ter o modelo, precisa de MLOps para servir, monitorar e retreinar. Um erro aqui tem custo direto em verba de anúncios.  
         3. Barreira de contexto de negócio: o modelo aprende padrões específicos do nicho, do produto, do público. Não é transferível de um concorrente para outro sem dados.  
         4. Mesmo com agentes de IA criando pipelines de ML, a disciplina de MLOps (drift, retreino, paridade treino/produção) ainda requer julgamento humano especializado.  
      3. Data flywheel com transfer learning: cada lançamento gera dados que melhoram o modelo do próximo. Quanto mais tempo usando, maior a vantagem acumulada.  
      4. O que o sistema envia à Meta (LeadQualified — o coração do produto)  
         1. Este é o ponto central da proposta de valor. Em vez de esperar 21 dias ou mais por uma compra real, enviamos um sinal de qualidade em \~5 minutos após o lead chegar.  
         2. Velocidade do sinal  
            1. Com ML: sinal de qualidade em 5 min após o lead  
            2. Sem ML: sinal real só após compra, 7–21 dias depois  
         3. Volume de eventos  
            1. Com ML: milhares de eventos qualificados por lançamento  
            2. Sem ML: dezenas ou centenas de compras reais em 21 dias  
         4. Eliminação do cold start  
            1. Com ML: Meta atinge mínimo de otimização na primeira semana de captação  
            2. Sem ML: algumas conversões após 3–4 semanas — Meta nunca sai do cold start durante o lançamento  
         5. Qualidade do sinal (o diferencial técnico)  
            1. Nosso modelo usa features que a Meta não tem acesso: respostas da pesquisa de pré-inscrição, sinais de risco/inadimplência da TMB, combinação de UTMs, dados demográficos. O resultado do modelo — o score — é codificado como o valor do evento (D10=R$1.000, D9=R$900...). A Meta recebe um número de qualidade calibrado, não features brutas. Diferente do que a Meta faria sozinha (pegar tudo e jogar num bolo), nosso modelo seleciona as features com pesos otimizados para o produto específico do cliente.  
      5. Controle e transparência  
         1. Você sabe exatamente qual feature está influenciando o score  
         2. Meta é caixa preta: não explica por que priorizou um lead  
      6. Calibração contínua  
         1. O modelo é retreinado com dados reais de conversão de cada lançamento  
         2. O sinal melhora a cada ciclo  
      7. Portabilidade multi-plataforma  
         1. O mesmo modelo alimenta Google Ads, TikTok, LinkedIn com o mesmo score  
         2. Não é necessário reconfigurar em cada plataforma  
         3. Resultado: 1 modelo → N canais → otimização cruzada (não só dentro da Meta, mas entre canais)  
      8. Fechamento do funil: Purchase events  
         1. Após o fechamento do carrinho, enviamos os compradores reais à Meta com seus cookies (FBP/FBC) e o valor real da venda. Isso completa o funil no pixel.  
         2. Melhora a qualidade do evento "Comprar" no pixel (hoje 4.4/10 — sem CAPI server-side)  
         3. Cria lookalike audiences de compradores reais com valor para os próximos lançamentos  
         4. Conecta o loop completo: lead → lead qualificado → compra real — tudo rastreado server-side  
      9. Inadimplência como sinal negativo  
         1. A integração com TMB permite que o modelo otimize não só por "vai comprar?" mas por "vai comprar E não cancelar/inadimplir?". Isso é único — nenhuma plataforma de anúncios tem acesso a dados de inadimplência do produto do cliente.

# ---

# Execução:

1. # [Definir arquitetura da solução](https://docs.google.com/document/d/1RKeQYMk84kF5W5PLAc7jmHl7ppzI7LS0HTeg66vyKLs/edit?usp=sharing)

2. # EDA

   - [ ] Registrar a fonte dos dados do cliente:  
         - [ ] Devclub:  
* [Planilhas de leadscore](https://docs.google.com/spreadsheets/d/1kLgVsNcc8OmPMvxaTN7KM0cTB5hC0KtL02lSZMYRHBw/edit?usp=sharing) (só LF)  
* [Pasta com planilhas de leads e outros lançamentos](https://drive.google.com/drive/folders/11mdfA1BLFxfu39H75dx0G5r-TWoNSYx8?usp=share_link)

3. # Limpeza e tratamento de dados:

   - [ ] Importar os arquivos.  
   - [ ] Remover abas desnecessárias.  
   - [ ] Remover dados duplicados.  
   - [ ] Remover colunas desnecessárias e com dados em branco.  
   - [ ] Unifica datasets de pesquisa em um, e de alunos em outro.  
   - [ ] Resolver inconsistências nos nomes das colunas.  
         - [ ] Unificar colunas separadas mas com mesmo nome / significado  
         - [ ] Limpar nomes sujos  
   - [ ] [Fazer o dicionário de dados](https://docs.google.com/spreadsheets/d/106A9D7Jhv32pxihVWYMJ_RsTXAHYk6pESENqgZIAzPM/edit?usp=sharing)  
   - [ ] Qualidade dos dados:  
         - [ ] Identificadores (nome, telefone, e-mail):  
               - [ ] Min  
               - [ ] Max  
               - [ ] Média  
               - [ ] Outliers  
         - [ ] Colunas categóricas:  
               - [ ] Valores únicos  
               - [ ] Nulos  
               - [ ] Distribuição de categorias (top 10 e gráfico de barras)  
         - [ ] Data:  
               - [ ] Data de início e do fim  
               - [ ] Formato  
         - [ ] Tratar nulos, ausentes e outliers  
         - [ ] Resolver inconsistências nos nomes das categorias  
   - [ ] Remover features desnecessárias restantes  
         - [ ] Campaign: remover. Se trata do lançamento específico.  
         - [ ] Content: remover. São anúncios que carregam características individuais de cada lançamento.  
         - [ ] Coluna em branco.  
   - [ ] Agrupamento de categorias raras e esparsas:  
         - [ ] Term e Source: Manter categorias principais e agrupar menores em “Outros”.  
         - [ ] Medium \- fazer agrupamentos das categorias.  
- [x] ~~Matching por e-mail e telefone~~  
      - [x] ~~Números de respostas na pesquisa para cada aluno: min, max, média e mediana~~  
      - [x] ~~Dias entre a pesquisa e o match: min, max, média, mediana e desvio padrão~~  
      - [x] ~~Dias da semana em que leads se cadastraram que geraram mais matches ordenados do maior para o menor~~  
      - [ ] Remover colunas desnecessárias restantes  
            - [ ] Colunas criadas no processo  
            - [ ] Data, criando features temporais importantes:  
                  - [ ] Dia da semana, época do mês se pertinente, época do ano se pertinente  
            - [ ] Nome:   
                  - [ ] Comprimento  
                  - [ ] Se respondeu nome completo  
            - [ ] E-mail:  
                  - [ ] Se é válido  
            - [ ] Telefone:  
                  - [ ] Se é válido  
            - [ ] Texto  
      - [ ] Encoding  
            - [ ] Nominais: one hot, Ordinais: ordinal ou label  
      - [ ] Split

4. # Modelagem

   - [x] ~~Modelos de árvore (RF, XGB e LGBM) com split temporal, rankeando por decil de probabilidade.~~  
         - [x] ~~Testar diferentes combinações e condições nos dados (incluindo com e sem sistema legado)~~  
         - [x] ~~Testar ensemble~~  
         - [x] ~~Testar Prob Calib (inútil para o ranking utilizado)~~  
         - [x] ~~Testar Hyper Parameter Tuning (usar F2) (não útil)~~  
         - [x] ~~Testar feature importance~~  
         - [x] ~~Testar redes neurais~~  
   - [ ] Análise de erros  
         - [x] ~~Calcule métricas por grupo (com contagens reais): FNR \= FN/(FN+TP), FPR \= FP/(FP+TN), precisão e recall por grupo.~~  
         - [x] ~~Teste estatístico (chi-square / Fisher) para ver se diferença é significativa (especialmente importante para grupos pequenos).~~  
         - [x] ~~Explainability: rode SHAP ou feature-importance apenas nos exemplos de FN e FP para ver quais features empurram o score para baixo/alto nesses casos.~~  
         - [x] ~~Criar novas features com base na análise de erros~~  
   - [x] ~~Comparar com o sistema legado~~

5. # Produção:

   - [x] ~~Garantir o workflow completo e exato dos dados para o modelo.~~   
         - [x] ~~Remover as categorias descontinuadas~~  
         - [x] ~~Lidar com categorias não vistas.~~  
         - [x] ~~Montar parte de predições~~

6. # POC

   - [x] ~~Construir API de predições~~  
   - [x] ~~Implementar no lançamento~~  
         - [x] ~~Decidir regras de negócio~~  
         - [x] ~~Pegar feedback com usuários (Gestores de tráfego)~~  
- [x] ~~Levar em conta o custo~~  
- [x] ~~Usar as janelas temporais (1, 2, 3 e 7 dias)~~  
- [x] ~~Validar estatisticamente quando uma ação é desejada.~~  
- [x] ~~[Definir data, critério de sucesso, tempo de duração, orçamento e uso de CAPI ou não.](https://docs.google.com/document/d/11z9ETapcJKNcJUBMc4MQgiPJsvkdMHQ70tQI-CIpPQo/edit?usp=sharing)~~  
- [x] ~~Acompanhar execução~~  
- [x] ~~Fazer análise comparativa de resultados~~

7. # Fechamento

8. # Validação

   - [x] ~~Validar os resultados de janeiro.~~  
         - [x] ~~Monitorar AUC e conversão por decil~~  
         - [x] ~~Fazer a de validação ficar no automático~~  
         - [x] ~~Output no slack~~  
         - [x] ~~02/02 (Segunda), enviar fechamento e pós devoluções~~  
               - [x] ~~Captação: 16/12 \- 12/01~~   
               - [x] ~~Vendas: 19/01 \- 25/01~~  
         - [x] ~~09/02 (Segunda), enviar fechamento:~~  
               - [x] ~~Captação 13/01 \- 26/01~~  
               - [x] ~~Vendas 02/02 \- 08/02~~  
         - [x] ~~Data: 09/03(segunda)~~  
               - [x] ~~Rodar a validação do lançamento atípico manualmente com datas explícitas: \--start-date 2026-02-02 \--end-date 2026-02-22 \--sales-start-date 2026-03-02 \--sales-end-date 2026-03-08~~  
         - [x] ~~Data: 16/03(segunda)~~  
               - [x] ~~Reativar o Cloud Scheduler — a partir daqui os lançamentos voltam ao padrão e o auto-cálculo funciona corretamente~~  
         - [x] ~~Fazer o ROAS devclub ao longo do tempo e concluir se sistema de fato aumentou ROAS ou margem de contrib?~~  
               - [x] ~~Dar último check na consistência dos dados~~  
               - [x] ~~Tirar relatório da semana~~  
               - [x] ~~Atualizar com vendas Asaas~~  
               - [x] ~~Garantir que as campanhas de um lançamento só tenham o gasto daquela data.~~  
         - [x] ~~Atualizar a tabela de evolução. Adicionar no validação a flag para preencher planilha evolução.~~  
         - [x] ~~Emitir relatório semanal~~  
         - [ ] Investigar degradação da AUC

9. # Monitoramento

   - [x] ~~Novas categorias não vistas no treino~~  
         - [x] ~~Mudanças drásticas nas proporções colunas (categóricas e numéricas)~~  
         - [x] ~~Missing rate alto de qualquer coluna~~  
         - [x] ~~Missing features~~  
         - [x] ~~Mudança significativa nas proporções de score e decil~~  
         - [x] ~~Missing rate algo de dados de capi \> 50%~~  
         - [x] ~~Mais de 6 horas sem receber leads~~  
         - [x] ~~Mais de 6 horas sem enviar evento CAPI~~  
         - [x] ~~Taxa de resposta, etc. (planilha de monitoramento 30d)~~  
         - [x] ~~Testar monitoramento na planilha app script.~~  
         - [x] ~~Output: slack~~  
         - [x] ~~Criar novo webbook e trocar url no app scripts~~  
         - [x] ~~Criar if else com alerta no head em caso crítico~~  
         - [x] ~~Incluir score médio do lançamento atual~~  
         - [x] ~~Enviar API para o Henrique~~  
               - [x] ~~Deixar configurável de data no payload, em vez de 12h. Colocar data. Dia mês e ano. Start date e end date.~~  
               - [x] ~~Colocar o detalhe do medium no payload no get, não está aparecendo o medium que mudou.~~   
               - [x] ~~Testar o get antes de enviar.~~  
         - [x] ~~Ver feature alerta source inexistente~~  
         - [x] ~~Desligar DB existente~~  
         - [x] ~~Duplicação de eventos?~~   
         - [x] ~~Receber colunas fbc e fbp~~  
         - [x] ~~Solicitar coluna de user agent~~  
         - [x] ~~Colocar métricas de tráfego:~~  
               - [x] ~~Conversion rate LP~~  
               - [x] ~~CPL~~  
         - [x] ~~Conferir se endpoint continua ativo~~  
         - [ ] Monitorar métricas

10. # Retreino

    - [x] ~~Aplicar as funções de monitoramento~~  
    - [x] ~~[Limpar output](https://docs.google.com/document/d/1tUKm46-XxCZV8OzWpGKWslMV3Q-uOic5GKgGQ4T533E/edit?usp=sharing) do pipeline de treino~~  
    - [x] ~~Testar telefone ultimos 6~~  
    - [x] ~~Verificar se todas as funções são comuns para treino e retreino~~  
    - [x] ~~Testar usar TMB risco médio e baixo~~  
    - [x] ~~Pegar todos os lançamentos / toda a performance ML~~  
    - [x] ~~Emitir relatórios atualizados~~  
    - [x] ~~Fazer análise comparativa~~  
    - [x] ~~[Testar hipóteses](https://docs.google.com/document/d/12qfzQ5YTxtK26ROb8cAFdOEdzD84rT7SIaj-Zm9zvr0/edit?usp=sharing)~~  
    - [x] ~~Retreinar modelo~~  
          - [x] ~~Cutoff por missing~~  
          - [x] ~~Checar número de registros removidos na janela de conversão célula 17~~  
          - [x] ~~Resolver filtro de risco tmb e testar os 4~~  
          - [x] ~~Remover ou agrupar categorias novas com alto missing combinando representatividade \+ feature importance~~  
          - [x] ~~Remover binary TOP3 do encoding~~  
          - [x] ~~Incluir mês e semana (Se tiver 12m)~~  
          - [x] ~~Quantidade de lançamentos que já participou~~  
          - [x] ~~Rodar teste de hyperparametros~~  
          - [x] ~~Com pesos vs sem pesos~~  
          - [x] ~~Testar múltiplos algoritmos no treino.~~  
    - [x] ~~Servir modelo retreinado~~  
          - [x] ~~Atualizar pipeline de produção~~  
          - [x] ~~Atualizar decis e valores (verificar valores)~~  
          - [x] ~~Atualizar plano de refactor com mudanças feitas \+ necessidade de treino ponderado~~  
          - [x] ~~Isotonic é prioridade? Pra suavizar a curva entre os demais e o D10 em termos de espaço do score (range)?~~  
          - [x] ~~Enviar evento de compra “parcial”~~  
    - [ ] Automatizar retreino com teste AB (plano refac) \- 14/04

11. # Empresa e Commercial

    - [x] ~~Gerar pdf comercial mais enxuto e numericamente mais preciso.~~  
    - [x] ~~Registrar marca~~  
    - [x] ~~[Registrar domínio](https://checkout.hostgator.com.br)~~  
    - [x] ~~Editar [script](https://docs.google.com/document/d/1k7_Xsi-smihI76XSyce8MMAHvp0iVY1DRLPzmw1rm58/edit?usp=sharing)~~  
    - [x] ~~Editar [PPT](https://docs.google.com/presentation/d/1uvmCf3r4D9p7uSEwFHpeq1To4ROW3Xz6/edit?usp=sharing&ouid=108504172440522906536&rtpof=true&sd=true)~~  
    - [ ] Enviar mensagem para:  
          - [x] ~~Brother da Hotmart~~  
          - [x] ~~Contato com a Viver de IA / Rafael Milagre~~  
          - [x] ~~Brunopiscinini~~  
          - [x] ~~Fórmula de lançamento~~  
                - [ ] Chamar granville dia 8  
          - [x] ~~Cadu~~  
          - [x] ~~Ferrari~~  
    - [ ] Refazer SWOT e colocar ela no moat  
          - [ ] Incluindo um claude code mandando leadscore linear ou semi pra meta através do Google sheets   
    - [ ] Chamar a [lista](https://docs.google.com/document/d/1skspxr11zwdH_H_m0bWPjB_x4M_K5aaC7aWKedMciOc/edit?usp=sharing) (15 colegas/contatos que são possíveis clientes, alguns dos quais conhecem / confiam no meu trabalho)  
    - [ ] Fazer Id visual  
    - [ ] Falar com IA sobre educação. Começar com vídeo do bemchimol sobre a XP.  
    - [ ] Refactor para o novo nome  
    - [ ] Com ou sem BlueOcean:  
          - [ ] Fazer página / funil de agendamento  
          - [ ] Rodar tráfego pago  
    - [ ] Postar storie no Instagram  
    - [ ] Pedir vídeo e recomendação p/ Rodolfo  
    - [ ] Sistema de indicação

12. # Backlog:

    - [x] ~~Refatorar projeto para ter componentes reutilizáveis e configuráveis com pipelines chamadas por orquestradores.~~  
    - [x] ~~Teste AB de modelos~~  
          - [x] ~~Rollback imediato com modelo novo Guru sendo o Challenger~~  
          - [x] ~~Explicação no grupo sobre novo LQ e sobre UTM’s~~  
    - [ ] Criar EDA generator   
          - [ ] com fallback para agente   
    - [ ] Criar github actions CI \- testes parametrizados  
    - [ ] Pesquisa: enviar evento para Google  
    - [ ] Forecasting pré-lançamento: montar pipeline que usa dados dos leads, scores/decis, métricas de grupos de whatsapp e de comparecimento \+ semana/mês para prever vendas. Ter um dashboard que o cliente olha todo dia durante a captação.   
    - [ ] Automatizar a criação e atualização de públicos D10 ou D10+D9  
    - [ ] Testar features:   
          - [ ] Features do active campaign? O que tem de dados lá?  
          - [ ] Criar feature “entrou no grupo de whatsapp” (api sendflow)  
          - [x] ~~CPL, CPM a nível de campanha e adset no dia (precisa mesmo dos 2\) frequência \- negativo~~  
          - [ ] User agent: dispositivo, navegador, etc.  
          - [ ] Similar\_leads\_converteram\_taxa  
          - [ ] LTV (se renovou)  
          - [ ] Interação na página (tempo, cliques, rolagem)  
          - [ ] Lead\_score\_de\_modelos\_anteriores  
    - [ ] Usar GTM no checkout para melhorar o matching (pesquisa no cursor)  
    - [ ] Integrar claude code para otimizar campanhas de tráfego?  
    - [ ] Otimização do formulário da pesquisa como produto (sugerir remoção e adição de features)  
    - [ ] Exportação automática da lista de leads ordenadas por score E características (idade, etc.) para equipe comercial.   
    - [ ] Enriquecimento de dados

13. # Onboarding

    - [ ] Pesquisas  
    - [ ] Alunos  
    - [ ] Alterações no formulário da página  
          - [ ] Envio SQL  
          - [ ] Código GTM  
    - [ ] Acesso ao BM  
    - [ ] Acesso ao GTM  
    - [ ] Banco de dados SQL  
    - [ ] Acesso de editor na pesquisa