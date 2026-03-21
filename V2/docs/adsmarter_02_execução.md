# Notas:

* [Google offers $350,000 in credits for startups that use AI and already had investment to use it’s tools](https://cloud.google.com/startup/ai?hl=pt_br)  
* Projeto Smart Ads: Sistema de Otimização de Anúncios  
  * Objetivo Principal: Criar um sistema de machine learning para otimizar campanhas de anúncios com lead scoring avançado. O sistema identifica leads qualificados e envia um evento conversions API para as campanhas.  
  * Problema de Negócio: Anunciantes tomam decisões baseadas em métricas incompletas, o que leva a alocação ineficiente de recursos, ROAS (Retorno sobre o Investimento em Publicidade) subótimo e desconexão entre custo e valor do lead.  
  * Fontes e Características dos Dados  
    * Dados de tráfego (Meta/Google Ads), respostas de pesquisas (muitos dados), UTMs, dados de páginas da web (cliques, tempo gasto) e e-mails de compradores (variável target).  
  * Resultados: ROAS até 300% maior com a aplicação do sistema.

# ---

### *“Quais são os dados mais estratégicos que permitirão diferenciação para a estratégia de AI e como podemos gerar ou aproveitar esses dados dentro da empresa para desenvolvê-los?”*

### Nadella argumenta o valor surge quando você usa o modelo para orquestrar um fluxo de trabalho complexo. Essa capacidade de orquestrar múltiplas ferramentas de forma inteligente para completar um objetivo de negócio é onde a "mágica" acontece.

### Quanto mais você aprofunda a integração com as fontes de dados do cliente (pesquisa, TMB, Guru, WhatsApp), mais insubstituível você fica.

# V2:

1. # [Continuar estudando ML](https://docs.google.com/document/d/1JtkLNrDEHFsAmRdNYLoljGvWVfuNBwhill2pqpWKXmo/edit?usp=sharing)

2. # [Definir arquitetura da solução](https://docs.google.com/document/d/1RKeQYMk84kF5W5PLAc7jmHl7ppzI7LS0HTeg66vyKLs/edit?usp=sharing)

3. # EDA

   - [ ] Registrar a fonte dos dados do cliente:  
         - [ ] Devclub:  
* [Planilhas de leadscore](https://docs.google.com/spreadsheets/d/1kLgVsNcc8OmPMvxaTN7KM0cTB5hC0KtL02lSZMYRHBw/edit?usp=sharing) (só LF)  
* [Pasta com planilhas de leads e outros lançamentos](https://drive.google.com/drive/folders/11mdfA1BLFxfu39H75dx0G5r-TWoNSYx8?usp=share_link)

4. # Limpeza e tratamento de dados:

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

5. # Modelagem

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

6. # Produção:

   - [x] ~~Garantir o workflow completo e exato dos dados para o modelo.~~   
         - [x] ~~Remover as categorias descontinuadas~~  
         - [x] ~~Lidar com categorias não vistas.~~  
         - [x] ~~Montar parte de predições~~

7. # Validação no negócio

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

8. # Fechamento

9. # Validação

   - [ ] Validar os resultados de janeiro.  
         - [ ] Monitorar AUC e conversão por decil  
         - [ ] Fazer a de validação ficar no automático  
         - [ ] Output no slack  
         - [ ] 02/02 (Segunda), enviar fechamento e pós devoluções  
               - [ ] Captação: 16/12 \- 12/01   
               - [ ] Vendas: 19/01 \- 25/01  
         - [ ] 09/02 (Segunda), enviar fechamento:  
               - [ ] Captação 13/01 \- 26/01  
               - [ ] Vendas 02/02 \- 08/02  
         - [ ] Data: 09/03(segunda)  
               - [ ] Rodar a validação do lançamento atípico manualmente com datas explícitas: \--start-date 2026-02-02 \--end-date 2026-02-22 \--sales-start-date 2026-03-02 \--sales-end-date 2026-03-08  
         - [ ] Data: 16/03(segunda)  
               - [ ] Reativar o Cloud Scheduler — a partir daqui os lançamentos voltam ao padrão e o auto-cálculo funciona corretamente

10. # Monitoramento

    - [ ] Novas categorias não vistas no treino  
          - [ ] Mudanças drásticas nas proporções colunas (categóricas e numéricas)  
          - [ ] Missing rate alto de qualquer coluna  
          - [ ] Missing features  
          - [ ] Mudança significativa nas proporções de score e decil  
          - [ ] Missing rate algo de dados de capi \> 50%  
          - [ ] Mais de 6 horas sem receber leads  
          - [ ] Mais de 6 horas sem enviar evento CAPI  
          - [ ] Taxa de resposta, etc. (planilha de monitoramento 30d)  
          - [ ] Testar monitoramento na planilha app script.  
          - [ ] Output: slack  
          - [ ] Criar novo webbook e trocar url no app scripts  
          - [ ] Criar if else com alerta no head em caso crítico  
          - [ ] Incluir score médio do lançamento atual  
          - [ ] Enviar API para o Henrique  
                - [ ] Deixar configurável de data no payload, em vez de 12h. Colocar data. Dia mês e ano. Start date e end date.  
                - [ ] Colocar o detalhe do medium no payload no get, não está aparecendo o medium que mudou.   
                - [ ] Testar o get antes de enviar.  
          - [ ] Ver feature alerta source inexistente  
          - [ ] Desligar DB existente  
          - [ ] Duplicação de eventos?   
          - [ ] Receber colunas fbc e fbp  
          - [ ] Solicitar coluna de user agent  
          - [ ] Colocar métricas de tráfego:  
                - [ ] Conversion rate LP  
                - [ ] CPL

11. # Retreino

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
    - [x] ~~Fazer o ROAS devclub ao longo do tempo e concluir se sistema de fato aumentou ROAS ou margem de contrib?~~  
          - [x] ~~Dar último check na consistência dos dados~~  
          - [x] ~~Tirar relatório da semana~~  
                - [x] ~~Atualizar com vendas Asaas~~  
                - [x] ~~Garantir que as campanhas de um lançamento só tenham o gasto daquela data.~~  
          - [x] ~~Gerar pdf comercial mais enxuto e numericamente mais preciso.~~  
          - [ ] Margem contrib devclub hoje é maior que antes do ML? Escalaram? Estão ganhando mais dinheiro ?  
          - [ ] Refactor de smart\_ads para AdSmarter  
                - [ ] [Registrar domínio](https://checkout.hostgator.com.br)  
    - [ ] Teste AB de modelos:  
          - [ ] Discutir arquitetura  
          - [ ] Criar eventos  
          - [ ] Criar valores de UTM que cada evento vai reconhecer  
          - [ ] Criar lógica para, de acordo com a UTM, enviar score para cada evento  
    - [ ] Entender de fato o open claw e o que o ceo da nvidia disse. Fora do uso pra telefone no WhatsApp, o que mais dá pra fazer?  
    - [ ] Automatizar retreino

12. # Refactor 

    - [ ] Refatorar projeto para ter componentes reutilizáveis e configuráveis com pipelines chamadas por orquestradores.

13. # Onboarding

    - [ ] Checklist:  
          - [ ] Pesquisas  
          - [ ] Alunos  
          - [ ] Alterações no formulário da página  
                - [ ] Envio SQL  
                - [ ] Código GTM  
          - [ ] Acesso ao BM  
          - [ ] Acesso ao GTM  
          - [ ] Banco de dados SQL  
          - [ ] Acesso de editor na pesquisa  
          - [ ] Modelo: 

14. # Backlog:

    - [ ] Enviar evento de compra  
    - [ ] Usar GTM no checkout para melhorar o matching (pesquisa)  
    - [ ] Outros:  
          - [ ] Olhar API sendflow para criar featues “entrou no grupo de whatsapp”.  
          - [ ] Integrar claude code para otimizar campanhas de tráfego?  
          - [ ] Otimização do formulário da pesquisa como produto (sugerir remoção e adição de features)  
          - [ ] Integração com CRM/time de vendas para que o time de vendas ligue primeiro para os D9-D10. Isso transforma o Smart Ads em ferramenta de sales ops, não só de marketing.  
          - [ ] Forecasting pré-lançamento: Baseado nos primeiros 300-500 leads da captação, prever: "esperamos 40-55 vendas nesse lançamento com base na qualidade dos leads até agora." Um dashboard que o cliente olha todo dia durante a captação.   
          - [ ] Pergunta aberta  
          - [ ] Pesquisa: enviar evento para Google  
          - [ ] Automatizar a criação e atualização de públicos D10 ou D10+D9  
          - [ ] Testar features:   
                - [ ] User agent  
                - [ ] similar\_leads\_converteram\_taxa  
                - [ ] Teste com features tráfego  
                      1. Feature store para não precisar chamar api meta múltiplas vezes?  
                      2. Posicionamento  
                      3. CPC, CTR, CPM, etc.  
                      4. Outros dados disponíveis?  
                - [ ] LTV (se renovou)  
                - [ ] Interação na página  
                - [ ] Lead\_score\_de\_modelos\_anteriores  
          - [ ] Enriquecimento de dados

15. # Escala:

    - [ ] **FASE 1 (Agora):** Validação \+ MVP Monitoramento  
          - [ ] Cliente usando  
          - [ ] Script simples de monitoramento (performance, drift simples)  
          - [ ] Script simples de retreino  
    - [ ] **FASE 2:** Profissionalização  
          - [ ] Cria os componentes de unificação de dados e EDA que geram os dados para as configurações de treino  
          - [ ] Cria os componentes configuráveis de treino  
          - [ ] Treina modelo pelo script configurável e compara com pipeline de treino atual  
          - [ ] Cria os componentes configuráveis de produção necessários, monitoramento e retreino  
          - [ ] Cria os pipelines configuráveis e compara com anteriores  
          - [ ] Verifica se está tudo OK  
          - [ ] Cria checklist de onboarding  
          - [ ] Usa para o segundo cliente  
    - [ ] **FASE 3:** MLOps completo  
          - [ ] Gerar visualização (Looker studio)  
          - [ ] Kubeflow/Vertex AI Pipelines  
          - [ ] Feature Store  
          - [ ] CI/CD para modelos  
          - [ ] Stack completo GCP  
          - [ ] Multi armed bandit?

16. # Moat / Valor do negócio:

    - [ ] Funciona para perpétuo desde que tenha um produto médio ou alto ticket no funil e queiramos otimizar para clientes que compram esse produto.  
    - [ ] É diferente de análise de dados feita por LLM  
    - [ ] Diferentes features utilizadas  
    - [ ] Barreira técnica  
    - [ ] Barreira de contexto de negócio  
    - [ ] Mesmo com agentes criando pipelines de processamento de dados e modelos de ML, precisa entender MLOps para servir, monitorar e retreinar, gerenciando as ferramentas para tal. Um errinho aqui custa caro, e estamos falando de investimento.  
    - [ ] É contexto demais hoje, e mesmo quando não for, vamos ter um moat Data flywheel com transfer learning.  
    - [ ] Inadimplência como sinal negativo.   
          - [ ] Você já integra TMB com dados de risco/inadimplência. Isso significa que seu modelo pode otimizar não só por "vai comprar?" mas por "vai  
          - [ ]   comprar E não cancelar/inadimplir?".  
    - [ ] Sobre custom Data dos alunos (enviar dados dos leads com pesquisa para a meta aprender features preditivas à medida que enviamos os eventos de conversão, mesmo com delay de 21 dias):  
          - [ ] Velocidade do Sinal (Feedback Loop Acelerado)  
                - [ ] Com ML: Sinal de qualidade enviado em 5 min após o lead chegar  
                - [ ] Sem ML: Sinal só após compra real em 7-21 dias  
          - [ ] Volume de Eventos  
                - [ ] Com ML: milhares ou dezenas de milhares de eventos por dia  
                - [ ] Sem ML: dezenas ou centenas de eventos Purchase em 21 dias  
          - [ ] Eliminação do Cold Start  
                - [ ] Com ML: milhares de conversões na primeira semana (meta mínima para otimização)  
                - [ ] Sem ML: algumas conversões após 3-4 semanas  
          - [ ] Features utilizadas:  
                - [ ] Usamos mais do que as respostas da pesquisa, com contexto maior, selecionando exatamente os dados que treinamos com quais pesos e garantimos que estamos enviando o melhor sinal, com menos ruído, enquanto a meta só pega tudo e joga num bolo.  
                - [ ] Extraímos significado semântico.  
          - [ ] Controle e Transparência  
                - [ ] Você sabe EXATAMENTE qual feature está influenciando o score  
                - [ ] Meta é uma "caixa preta" (não explica por que priorizou um lead)  
          - [ ] Calibração Contínua  
                - [ ] ML é re-treinado com novos dados de conversão reais  
          - [ ] Portabilidade Multi-Plataforma  
                - [ ] Mesmo ML pode alimentar Google Ads, TikTok, LinkedIn  
                - [ ] Custom data precisa ser reconfigurado em cada plataforma  
                - [ ] Impacto: 1 modelo → N plataformas (escalabilidade)  
                - [ ] Meta \+ Google \+ Tik Tok. Vamos não só dizer como otimizar dentro da meta, mas também entre os canais.