# Rollback Decision

**Data:** 19/04/2026  
**Contexto:** Organização pós-rename smart_ads → bring_data

---

## Como era antes

O projeto mantinha um **git worktree** chamado `smart_ads_v2_rollback` dentro do diretório principal (`smart_ads/smart_ads_v2_rollback/`), apontando para o branch `rollback/edf23e9-ab-patch`.

Havia também dois worktrees adicionais:
- `smart_ads_refactor/` (Desktop) — branch `refactor/mlops-core`
- `/tmp/smart_ads_pre_pr` — HEAD detached, marcado como prunable

A intenção era ter uma cópia do código pronta para rollback em caso de emergência.

### Problemas identificados

1. **Desatualizado:** o worktree apontava para o commit `c0e09d0`, que nunca foi o estado exato em produção. A revision ativa (`smart-ads-api-00270-q2m`) veio de um commit posterior.

2. **Falsa segurança:** restaurar código do worktree local não reverte produção — exigiria um redeploy completo (~5 min), enquanto o Cloud Run oferece rollback de tráfego em ~10 segundos.

3. **Estrutura confusa:** worktree aninhado dentro do repo principal (`smart_ads/smart_ads_v2_rollback/`) mistura o conceito de "estado de produção" com "repositório de desenvolvimento".

4. **Sem rastreabilidade:** nenhuma convenção ligava commits git às revisions do Cloud Run. Não havia como saber, olhando para o git, qual commit gerou qual revision.

---

## Como ficou depois

### Worktrees removidos

```bash
git worktree remove smart_ads_v2_rollback
git worktree remove /Users/ramonmoreira/Desktop/smart_ads_refactor
git worktree prune
```

Apenas o worktree do Claude (`upbeat-bhabha`) foi preservado por ser gerenciado automaticamente.

### Rollback real: Cloud Run revisions

O Cloud Run mantém **270+ revisions** disponíveis desde Set/2025, todas com `status: True`. O tráfego pode ser redirecionado instantaneamente sem redeploy:

```bash
# Rollback de emergência (exemplo: voltar para a revision anterior)
gcloud run services update-traffic smart-ads-api \
  --to-revisions=smart-ads-api-00269-jjn=100 \
  --region=us-central1

# Ver revisions disponíveis
gcloud run revisions list --service=smart-ads-api --region=us-central1
```

Tempo de rollback: **~10 segundos**. Sem risco de inconsistência entre código local e produção.

### Rastreabilidade: git tags automáticas por deploy

O script `api/deploy_capi.sh` agora cria uma tag git automaticamente após cada deploy bem-sucedido:

```
deploy/YYYY-MM-DD-NNNNN-xxx   →   commit que originou a revision
```

Exemplo: `deploy/2026-04-19-00271-abc` corresponde à revision `smart-ads-api-00271-abc`.

Isso permite saber exatamente qual código está em cada revision sem depender de worktrees locais.

---

## Fonte de verdade

| Necessidade | Onde olhar |
|-------------|------------|
| O que está em produção agora | `gcloud run services describe smart-ads-api --format="yaml(status.traffic)"` |
| Qual commit originou cada revision | `git tag -l "deploy/*"` |
| Rollback de emergência | `gcloud run services update-traffic ... --to-revisions=REVISION=100` |
| Testar antes de ir a 100% | Usar `--no-traffic` no deploy, depois promover manualmente |

---

## Estado atual das revisions (19/04/2026)

| Revision | Data | Tráfego | Papel |
|----------|------|---------|-------|
| `smart-ads-api-00270-q2m` | 14/04 17:09 | 10% | Challenger (A/B test) |
| `smart-ads-api-00269-jjn` | 14/04 13:41 | 90% | Champion (estável) |
| `smart-ads-api-00252-zdh` | 23/03 17:59 | 0% | Tagged `staging` |
