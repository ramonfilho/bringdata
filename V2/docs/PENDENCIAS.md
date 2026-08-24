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
