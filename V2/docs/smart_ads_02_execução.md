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

6. # Validação no negócio

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
         - [ ] 16/02 (Segunda):  
               - [ ] Remover comparação e deixar apenas relatório de ML  
         - [ ] 16/02 (Segunda), pós devoluções:   
               - [ ] Captação: 13/01 \- 26/01  
               - [ ] Vendas 02/02 \- 08/02  
         - [ ] 16/02 (Segunda), fechamento:  
               - [ ] Captação: 27/01 \- 02/02  
               - [ ] Vendas 09/02 \- 15/02  
         - [ ] Reativar schedulers

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
         - [ ] Enviar API para o Henrique  
               - [x] ~~Deixar configurável de data no payload, em vez de 12h. Colocar data. Dia mês e ano. Start date e end date.~~  
               - [x] ~~Colocar o detalhe do medium no payload no get, não está aparecendo o medium que mudou.~~   
               - [ ] Testar o get antes de enviar.  
         - [ ] Desligar DB existente.  
         - [ ] Estudar SQL data base and sql with python for data science

10. # Retreino

    - [x] ~~Aplicar as funções de monitoramento~~  
          - [x] ~~[Limpar output](https://docs.google.com/document/d/1tUKm46-XxCZV8OzWpGKWslMV3Q-uOic5GKgGQ4T533E/edit?usp=sharing) do pipeline de treino~~  
          - [x] ~~Testar telefone ultimos 6~~  
          - [x] ~~Verificar se todas as funções são comuns para treino e retreino~~  
          - [x] ~~Testar usar TMB risco médio e baixo~~  
          - [ ] Remover ou agrupar categorias novas com alto missing  
          - [ ] Retreinar modelo  
          - [ ] Refactor:  
                Refactor estrutural com arquitetura de MLOps: tivemos um problema recentemente em que mundanos algo no pipeline de treino e esquecemos de propagar a mudança para o pipeline de produção e o de monitoramento. Precisamos fazer com que os pipelines de treino, produção, monitoramento e retreino utilizem os mesmos componentes, alterando apenas os periféricos. Com isso, uma mudança será diretamente propaganda para todos os pipelines.   
                E como planejamos ter outros clientes, e não podemos ter que criar um pipeline diferente para cada cliente, visto que os clientes possuem o mesmo workflow (integramos dados de pesquisa e dados dos alunos para criar um modelo e depois servir), poderíamos pensar em componentes que são “colocáveis” dentro de pacotes como é feito no dataflow \+ apache beam, ou qualquer outros sistema, mesmo que local, que seja reutilizável. Estou aberto a avaliar os pros e cons de cada alternativa para esta solução. Se a hora de fazer essa mudança de constantes para configs for agora, já vamos planejar como fazer. Se não, primeiro o refactor e depois planejamos a alteração das constantes.   
                Considerar em uma evolução futura do monitoring — verificar os valores das features pós-encoding, não só pré-encoding.  
                Fazer arquitetura que usa também os dados do novo db sql, e não somente do google sheets.   
                Existe também uma issue CRÍTICA de normalização. Muitos problemas em produção por pequenas diferenças na forma com que treino e produção normalizam ou não os dados. Houve uma quebra em produção por ter mechido em um detalhe na normalização no treino e não ter aplicado corretamente em produção.   
          - [ ] Incluir mês e semana  
          - [ ] Automatizar retreino  
          - [ ] Testar múltiplos algoritmos no treino.

11. # Onboarding

    - [ ] Mover constantes para config  
    - [ ] Checklist:  
          - [ ] Pesquisas  
          - [ ] Alunos  
          - [ ] Alterações no formulário da página  
          - [ ] Acesso ao BM  
          - [ ] Acesso ao GTM  
          - [ ] Acesso de editor na pesquisa  
          - [ ] Modelo: 

12. # Backlog:

    - [ ] Impacto imediato RM:  
          - [ ] Usar GTM no checkout para melhorar o matching  
          - [ ] Pergunta aberta  
    - [ ] Mostrar o % de D10 dos top X criativos.  
    - [ ] Iniciar a fase 2 do ponto Escala  
    - [ ] Pesquisa / Business:  
          - [ ] Pesquisar Multi armed bandit  
          - [ ] Enviar evento de compra?  
          - [ ] Automatizar a criação e atualização de públicos D10 ou D10+D9  
          - [ ] Gerar visualização (Looker studio)  
          - [ ] Testar features:   
                - [ ] User agent  
                - [ ] similar\_leads\_converteram\_taxa  
                - [ ] Teste com features tráfego  
                      1. Feature store para não precisar chamar api meta múltiplas vezes?  
                      2. Usar posicionamento  
                      3. Métricas: CPC, CTR, CPM, etc.  
                      4. Outros dados disponíveis?  
                - [ ] Interação na página  
                - [ ] Lead\_score\_de\_modelos\_anteriores  
                - [ ] Quantidade de lançamentos que já participou

13. # Escala:

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
          - [ ] Kubeflow/Vertex AI Pipelines  
          - [ ] Feature Store  
          - [ ] CI/CD para modelos  
          - [ ] Stack completo GCP

14. # Moat / Valor do negócio:

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
                      1. Interações entre campos: tem\_cnpj=true × faixa\_etaria="25-34" pode ter padrão específico  
                      2. Análise semântica de campos abertos: Sentimento, intenção, nível de maturidade em respostas textuais  
                      3. Features de tráfego: utm\_source, utm\_campaign, device\_type, hora\_do\_dia  
                      4. Behavioral features: Tempo para preencher formulário, taxa de engajamento com conteúdo  
                      5. Temporal features: Dia da semana, sazonalidade, tendências  
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