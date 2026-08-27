# PENDÊNCIAS — itens em aberto do projeto

Arquivo canônico dos pontos em aberto. Protocolo combinado com o Ramon (24/08/2026):
a cada item fechado, listar os que restam e perguntar qual atacar em seguida.
Item fechado sai daqui (o histórico fica no git).

## Aprovados para implementar (quando chegarem na fila)

### 1. Tabela de produtos da régua de lançamento
O que conta como "aluno do lançamento" hoje é uma lista de pedaços de nome no
`configs/clients/devclub.yaml` (`launch_products`), remendada a cada era de produto.
É exatamente o que subcontou o DEV21 (72 vendas + o Google de lá) quando a era mudou.
Solução definitiva aprovada: tabela `analytics.product_labels` (produto × gateway ×
entra-na-régua × rótulo), script de carga semeando do yaml + dos produtos históricos
vistos em `analytics.sales`, e o leitor único (`_load_launch_products`) passa a ler a
tabela com o yaml de reserva. ~1 PR, meia sessão; a parte cara é a auditoria produto
a produto das eras antigas, e mudança de régua muda número publicado (gate de
comparação antes/depois obrigatório).

### 2. Alvo de rollback do deploy pega a revisão errada
O script de deploy do CAPI (`V2/api/deploy_capi.sh`, ~linha 420 e o comando impresso
na progressão do canary) escolhe "para onde voltar se der ruim" com
`gcloud run revisions list --limit=1` — a revisão mais NOVA, não a que está SERVINDO
o tráfego. Qualquer canary abandonada envenena o alvo de rollback. Conserto: ler a
revisão com 100% do tráfego no describe do serviço. ~10 linhas de shell em 2 pontos +
teste estilo escotilha (`--help`, sem deploy real). Exige worktree + PR (api/ é
bloqueado na main). Risco alto por ser a escotilha de emergência: testar sem tocar produção.

### 3. Teto ANTECIPADO para a equipe de tráfego (aprovado 25/08)
Hoje o teto por unidade só aparece depois de 100 leads. Entregar: (a) o QUADRO DE LARGADA
por par criativo×campanha antes do primeiro real (teto de largada = nota histórica do
criativo × conversão esperada do público × valor por venda ÷ meta; razão CPL corrente ÷
teto de largada decide escala/teste/não-sobe); (b) primeira leitura de PREÇO a partir de
~R$ 300 gastos (CPL real vs teto de largada); a nota do PÚBLICO da unidade só entra aos
~100 leads — abaixo disso é ruído (constatação do Ramon, 25/08). QUESTÃO ABERTA a medir
antes de construir: o criativo carrega o próprio público? (se o histórico de %D9-D10 do
CRIATIVO prevê o público realizado da unidade melhor que a média da campanha, o quadro
ganha a metade do público sem esperar os 100 leads). RESOLUÇÕES CANDIDATAS para o
COLD START (criativo estreante, sem histórico nenhum — caso AD0424 do LF64): (a) o
teto de largada acima; (b) verba de teste limitada (R$ 700-1.000 por criativo) até a
primeira leitura; (c) **pontuação do criativo pelo TEXTO** antes de existir histórico
de conversão — o Ramon já tem protótipo com pontuação mais eficiente que a nota cega;
feature ainda não disponível (registrado 26/08). As peças já existem na máquina
(histórico point-in-time, referência, tetos_completos); falta o produto que entrega isso
diariamente à mesa do tráfego.

### 4. Histórico de criativo em DOIS tempos por semana (seg + qui) — pedido 27/08
Hoje o histórico que alimenta o teto vivo atualiza 1x/semana (refresh de segunda
06:30 UTC) e só conta lançamento FECHADO (`vendas_end < hoje - 2`). O Ramon quer
2 tempos (segunda E quinta), porque carrinho abre toda segunda e a maior parte
das vendas é do 1º dia: a captação corrente precisa se beneficiar da performance
do criativo no lançamento de carrinho aberto (ex.: AD0160/AD0424 do LF64).
ATENÇÃO no desenho: frequência sozinha NÃO resolve — a regra de só contar
lançamento fechado é o portão real; incluir lançamento aberto grava compra=0 em
lead que ainda pode comprar (subconta). Precisa de desenho (janela parcial
madura? contar só vendas já ocorridas com esperados da mesma janela?).

## Registrados, sem prioridade (o dono mandou deixar pra lá por enquanto)

- **Cadastros sem UTM desde 03/08** (13,6 mil linhas na `analytics.cadastros`): as 2
  fontes de origem secaram; conserto conhecido = o mesmo join Client × UTMTracking da
  captações. (Ramon: deixa pra lá por enquanto, 24/08.)
- **3 compras de upgrade engolidas parcialmente pela deduplicação** (mesmo comprador,
  mesmo dia, valores que colidem na assinatura pessoa+dia+valor+gateway). Conserto
  definitivo = deduplicar pelo número do pedido (`external_id`). Impacto máximo: 3 vendas.
- **Pendências do pipeline de treino** (6 itens, nº1 crítico): tratadas em OUTRA sessão,
  fora do escopo do relatório de lançamento. Ver memória `projeto_pendencias_pipeline_treino`.

## Agenda natural (não são defeitos)

- **Revisão órfã `smart-ads-api-01133-pob`**: tag de canary removida e 0% de tráfego
  (inerte); o Cloud Run não deleta a revisão mais RECENTE de um serviço, então ela só
  pode ser apagada depois do próximo deploy real (ou esquecida sem custo).

- **Rodada final do LF64** após o carrinho fechar em 30/08 (mesmos 2 comandos).
- **LF65** como prova de reuso da máquina (conferir a cobertura do mapa de criativos
  que o CLI imprime).
