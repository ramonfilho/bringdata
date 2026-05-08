# /docs — Skill master de documentação

Invoca a skill `docs` definida em [V2/.claude/skills/docs/SKILL.md](../../V2/.claude/skills/docs/SKILL.md). Substitui o antigo `/plan-integrator` (modo `mapear` cobre o mesmo escopo).

## Modos

| Modo | O que faz |
|---|---|
| `mapear` | Estado integrado das frentes, conflitos, prioridade global (= antigo plan-integrator) |
| `unificar` | Funde N docs em um único, com política "versão mais nova vence" |
| `arquivar` | Move doc para `V2/docs/arquivo/` com header de deprecação |
| `indexar` | Atualiza `V2/docs/INDICE_DOCUMENTACAO.md` |
| `auditar` | Detecta redundância e sugere candidatos a unificação |

## Uso

```
/docs mapear
/docs unificar Erros_cometidos.md auditoria_dano_bugs_ml.md
/docs arquivar <nome>.md
/docs indexar
/docs auditar
```

Argumentos: $ARGUMENTS

---

**Ação:** leia [V2/.claude/skills/docs/SKILL.md](../../V2/.claude/skills/docs/SKILL.md) integralmente e execute o modo solicitado em `$ARGUMENTS`. Se nenhum modo for informado, infira do contexto e confirme antes de agir.
