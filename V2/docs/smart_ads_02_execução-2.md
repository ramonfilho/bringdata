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

### Nadella argumenta que a complexidade e o valor surgem quando você usa o modelo de IA não apenas para responder perguntas, mas para orquestrar um fluxo de trabalho complexo. Essa capacidade de orquestrar múltiplas ferramentas de forma inteligente para completar um objetivo de negócio é onde a "mágica" acontece.

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
         - [ ] Data: 09/03(segunda)  
               - [ ] Rodar a validação do lançamento atípico manualmente com datas explícitas: \--start-date 2026-02-02 \--end-date 2026-02-22 \--sales-start-date 2026-03-02 \--sales-end-date 2026-03-08  
         - [ ] Data: 16/03(segunda)  
               - [ ] Reativar o Cloud Scheduler — a partir daqui os lançamentos voltam ao padrão e o auto-cálculo funciona corretamente

10. # Monitoramento

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
          - [ ] Proposta Guilherme  
          - [ ] Resposta Luciano  \- devo dar alguma agora?  
          - [ ] Claude code gerando leads?  
          - [ ] Servir modelo retreinado  
                - [x] ~~Cutoff por missing~~  
                - [x] ~~Checar número de registros removidos na janela de conversão célula 17~~  
                - [x] ~~Resolver filtro de risco tmb e testar os 4~~  
                - [x] ~~Remover ou agrupar categorias novas com alto missing combinando representatividade \+ feature importance~~  
                - [x] ~~Remover binary TOP3 do encoding~~  
                - [x] ~~Incluir mês e semana (Se tiver 12m)~~  
                - [x] ~~Quantidade de lançamentos que já participou~~  
                - [x] ~~Rodar teste de hyperparametros~~  
                - [x] ~~Com pesos vs sem pesos~~  
                - [ ] Atualizar pipeline de produção  
                - [ ] Atualizar decis e valores (verificar valores)  
                - [ ] Atualizar plano de refactor  
                - [ ] Programar data para retreino  
                      - [ ] 30D  
          - [ ] Automatizar retreino  
          - [x] ~~Testar múltiplos algoritmos no treino.~~

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

    - [ ] Impacto imediato RM:  
          - [ ] Enviar evento de compra (pesquisa)  
          - [ ] Integrar claude code para otimizar?  
          - [ ] Usar GTM no checkout para melhorar o matching (pesquisa)  
    - [ ] Outros:  
          - [ ] Olhar API sendflow  
          - [ ] Pergunta aberta  
          - [ ] Pesquisa: enviar evento para Google  
          - [ ] Automatizar a criação e atualização de públicos D10 ou D10+D9  
          - [ ] Testar features:   
                - [ ] User agent  
                - [ ] similar\_leads\_converteram\_taxa  
                - [ ] Teste com features tráfego  
                      - [ ] Feature store para não precisar chamar api meta múltiplas vezes?  
                      - [ ] Posicionamento  
                      - [ ] CPC, CTR, CPM, etc.  
                      - [ ] Outros dados disponíveis?  
                - [ ] LTV (se renovou)  
                - [ ] Interação na página  
                - [ ] Lead\_score\_de\_modelos\_anteriores  
          - [ ] Enriquecimento de dados

15. # Escala:

    - [ ] **FASE 1 (Agora):** Validação \+ MVP Monitoramento  
          - [x] ~~Cliente usando~~  
          - [x] ~~Script simples de monitoramento (performance, drift simples)~~  
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

    - [ ] “Machine Learning” do VK metrics:  
          - [ ] Lead scoring é individual, e características preditivas para um nicho podem não ser para outro. Inclusive os leads podem mentir atributos.   
    - [ ] Custom Data dos alunos:  
          - [ ] Velocidade do Sinal (Feedback Loop Acelerado)  
                - [ ] Com ML: Sinal de qualidade enviado em 3 horas após o lead chegar  
                - [ ] Sem ML: Sinal só após compra real em 7-21 dias  
                - [ ] Impacto: Meta otimiza 56x mais rápido (21 dias vs 3 horas)  
          - [ ] Volume de Eventos  
                - [ ] Com ML: 100 leads → 30-40 eventos LeadQualified em 1 dia  
                - [ ] Sem ML: 100 leads → 10 eventos Purchase em 21 dias  
                - [ ] Impacto: Meta recebe 3-4x mais sinais \+ 21x mais rápido \= 63-84x mais aprendizado  
          - [ ] Eliminação do Cold Start  
                - [ ] Com ML: 50-100 conversões na primeira semana (meta mínima para otimização)  
                - [ ] Sem ML: 50-100 conversões só após 3-4 semanas  
                - [ ] Impacto: Campanhas novas saem do "modo exploração" em 7 dias vs 35-70 dias  
          - [ ] Controle e Transparência  
                - [ ] Você sabe EXATAMENTE qual feature está influenciando o score  
                - [ ] Meta é uma "caixa preta" (não explica por que priorizou um lead)  
          - [ ] 4\. Inteligência Avançada (Features Engineered)  
                - [ ] ML gera características que custom data puro não possui:  
                      - [ ] Interações entre campos: tem\_cnpj=true × faixa\_etaria="25-34" pode ter padrão específico  
                      - [ ] Análise semântica de campos abertos: Sentimento, intenção, nível de maturidade em respostas textuais  
                      - [ ] Features de tráfego: utm\_source, utm\_campaign, device\_type, hora\_do\_dia  
                      - [ ] Behavioral features: Tempo para preencher formulário, taxa de engajamento com conteúdo  
                      - [ ] Temporal features: Dia da semana, sazonalidade, tendências  
          - [ ] Calibração Contínua  
                - [ ] ML é re-treinado com novos dados de conversão reais  
          - [ ] Portabilidade Multi-Plataforma  
                - [ ] Mesmo ML pode alimentar Google Ads, TikTok, LinkedIn  
                - [ ] Custom data precisa ser reconfigurado em cada plataforma  
                - [ ] Impacto: 1 modelo → N plataformas (escalabilidade)  
                - [ ] Meta \+ Google \+ Tik Tok. Vamos não só dizer como otimizar dentro da meta, mas também entre os canais.  
    - [ ] ADV+:  
          - [ ] Por que quando um cliente quer ter um controle real e absoluto do público, ele não usa ADV+.  
    - [ ] Data Flywheel:   
          - [ ] com o passar do tempo, vamos ter algoritmos com aprendizado multinicho, e saberemos as features mais preditivas (transfer learning multi clientes e multinicho). O cliente além de ter mais inteligência, não terá problemas com cold start.  
          - [ ] Transfer learning sobre o histórico de otimizações da meta.  
    - [ ] Outros possíveis diferenciais:  
          - [ ] Integrar ferramenta via API para criar novos criativos com base nos que estão dando certo.  
          - [ ] Alocação preditiva (detecta tendência intradia e otimiza para isso)  
          - [ ] Personalizar llm (chatbot) de atendimento / vendas com base nas respostas da pesquisa  
    - [ ] Perpétuo:  
          - [ ] Geralmente os produtos perpétuo são low ticket com a intenção de converter para um produto de ticket maior, então o enriquecimento do CAPI \+ otimização será feito com base nos leads que geram maior LTV, em vez de maior probabilidade de comprar o produto único.