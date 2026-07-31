# /limpar-worktrees — faxineiro de worktrees e branches

Fecha worktrees e poda branches de feature cujo trabalho **já está na main**, mantendo a main como fonte única de execução do projeto. O motor é `scripts/worktree-janitor.sh`.

## Como agir quando esta skill for invocada
1. **SEMPRE** rode o dry-run primeiro e mostre a saída ao usuário:
   `bash scripts/worktree-janitor.sh`
2. Só com o **OK explícito**, aplique:
   - Local (worktrees + branches locais): `bash scripts/worktree-janitor.sh --apply`
   - Incluindo remotos (branches no GitHub cujo PR foi mergeado): `bash scripts/worktree-janitor.sh --apply --prune-remote`
3. `--stale-days=N` ajusta a idade mínima sem commit (default 14).

## Regra de segurança (o script garante; nunca burlar)
Uma sala/branch só é fechável se **todas** valerem:
1. o trabalho está na main — comprovado por ancestralidade de `origin/main`, OU `git cherry` sem `+` (patch-equivalente), OU PR mergeado (pega squash);
2. [worktree] working tree 100% limpo (nada não-commitado nem não-rastreado);
3. não é `main` nem a worktree/branch atual de onde roda.

Qualquer dúvida → **POUPA e reporta**. NUNCA toca produção (Cloud Run / Cloud SQL / schedulers / dados). NUNCA apaga `main`. NUNCA usa `-D`/`--force` cego sem a comprovação acima.

## Ciclo de vida de uma sala (o padrão do projeto)
abrir (`scripts/feature-start.sh <nome>`, base sempre `origin/main`) → trabalhar → PR (`scripts/feature-finish.sh`) → merge → **fechar (este faxineiro)**. O passo de fechar era o que faltava e fazia as salas e branches acumularem.

## O que o faxineiro POUPA de propósito
- `backup/*`, `rollback/*`: pontos de segurança deliberados.
- Branch com commits fora da main (trabalho não mergeado).
- Worktree com arquivo não-commitado (trabalho não salvo).
Esses ficam para decisão humana — nunca são apagados automaticamente.

## Futuro (opcional)
Para fechar 100% na fonte, uma GitHub Action `on: pull_request (closed, merged)` pode apagar o branch remoto no merge; o faxineiro cobre o resto (worktrees locais + branches órfãos).
