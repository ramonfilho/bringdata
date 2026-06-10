# Fan-out de evento CAPI HQ — cópias adicionais em pixels paralelos

**Criado:** 2026-06-07 · **Papel:** especificação arquitetural e operacional do mecanismo que duplica o evento CAPI de alta qualidade em pixels adicionais declarados pelo cliente, sem mexer no roteamento de variantes A/B.

> Linguagem natural primeiro (regra do `CLAUDE.md`). Nomes de arquivo e função aparecem no corpo porque o doc é técnico-operacional; identificadores históricos vão no rodapé.

---

## Sumário em uma frase

Cada vez que sai um evento CAPI de alta qualidade (o `LeadQualifiedHighQuality` do Champion ou o `HQLB` do Challenger), um laço configurável no nosso lado dispara também cópias do mesmo evento em pixels adicionais declarados como regra global do cliente — hoje, exclusivamente, o pixel `241752320666130` (Pixel de BM Rodolfo Mori) recebendo as duas versões em paralelo aos pixels principais (`1937807493703815` Champion, `1513132406527995` Challenger).

---

## 1. O quê e por quê

**O quê:** depois que o evento de alta qualidade primário sai pelo pixel da variante (jan30 ou abr28), um laço dentro de `send_both_lead_events` (em [api/capi_integration.py](../api/capi_integration.py)) consulta a lista `capi.extra_hq_destinations` do `ClientConfig` e, para cada destinação cujo nome de evento case com o evento primário que acabou de sair, dispara uma cópia adicional reusando a mesma função `send_lead_qualified_high_quality` — só que com `pixel_id_override`, `event_name_override` e `high_quality_decils_override` apontando para o destino adicional.

**Por quê (o que forçou esta frente):** o dono pediu, em 2026-06-07, que os eventos de alta qualidade voltassem a chegar no pixel antigo do BM dele (final `…6130`) — eles já existiam lá no passado mas desapareceram. O gestor de tráfego precisa do `LeadQualifiedHighQuality` e do `HQLB` cadastrados nesse pixel para conseguir criar campanhas que otimizam nesses eventos por ali. Como cada variante A/B já manda o seu evento HQ no seu próprio pixel principal, a única coisa que faltava era duplicar a saída.

**Por que não bastou criar uma terceira variante:** uma variante A/B implica novo modelo, nova UTM exclusiva e novo nome de evento. O pixel 6130 não tem nada disso — ele recebe **cópias dos mesmos eventos já existentes**, independente de qual variante pontuou o lead. Isso é fan-out (multiplicar saída em N destinos), não roteamento (escolher entre variantes via UTM). O sistema A/B foi construído inteiro sobre a hipótese "1 lead = 1 variante = 1 evento = 1 pixel" (princípio do [AB_TEST.md](AB_TEST.md): *"cada variante usa seu próprio modelo e envia um evento CAPI com nome diferente"*). Fan-out é outra preocupação.

---

## 2. Decisão arquitetural — nível CLIENTE, não nível VARIANTE

A configuração do fan-out vive na seção `capi` do arquivo do cliente ([configs/clients/devclub.yaml](../configs/clients/devclub.yaml)), que é carregada em runtime no `CAPIConfig`. **Não vive** no `ABTestVariantConfig` do `active_models/devclub.yaml` (onde moram pixel principal, faixa de decis e nome de evento da variante).

**Por quê:**

1. **A regra não depende da variante.** Champion e Challenger vão para pixels diferentes (1937 vs 1513), mas ambos espelham no 6130. Quem decide isso é o cliente DevClub, não o roteamento UTM.
2. **Separação de responsabilidades.** `ABTestVariantConfig` descreve **uma alternativa** do A/B (o pacote primário). `CAPIConfig.extra_hq_destinations` descreve **regras pós-disparo** do cliente. Misturar os dois conceitos no mesmo lugar foi a falha da primeira tentativa.
3. **Custo de propagação.** No desenho "nível variante" (1ª tentativa), o valor "destino extra" precisava viajar grudado no lead desde a leitura da UTM até a saída do evento — o que obriga a tocar `app.py` (3 caminhos), `survey_branch.py`, `pubsub_branch.py` e o consumidor da variante em `capi_integration.py`. **7 arquivos**, porque a informação atravessa toda a cadeia, mas só importa lá no final. No desenho "nível cliente" (versão atual), a informação é lida diretamente onde é usada — **3 arquivos**, nenhuma propagação.

**Retrospectiva — 1ª tentativa (commit `e52469c`, revertido em `06e97ba` em 2026-05-27):** tratou o fan-out como atributo da variante. Resultado: 7 arquivos mexidos, fricção desnecessária na cadeia A/B, deploy quase indo a 100% antes do usuário interromper. Reversão foi imediata, sem dano em produção.

---

## 3. Fluxo do lead — dois exemplos concretos

**Exemplo A — lead que cai no Champion (sem `LEADHQLB` na UTM):**

1. Lead entra pela rota de webhook (HTTP em `app.py`) ou pelo consumer Pub/Sub (`pubsub_branch.py`).
2. `pipeline.get_ab_variant(utm)` não casa → retorna Champion (fallback, conforme `AB_TEST.md`).
3. `pipeline.run` pontua o lead, atribui decil. Suponha D9.
4. `send_both_lead_events` dispara:
   - **Primário 1:** `LeadQualified` no pixel `1937807493703815` (com valor por decil).
   - **Primário 2:** `LeadQualifiedHighQuality` no pixel `1937807493703815` (D9+D10 do Champion, sem valor).
5. **Laço de fan-out** entra: lê `capi_config.extra_hq_destinations`. Encontra entrada cujo `event_name == "LeadQualifiedHighQuality"`.
6. **Cópia:** dispara `LeadQualifiedHighQuality` no pixel `241752320666130` (D9+D10 declarados na entrada).
7. Lead segue. Retorno inclui `extra_hq_results` com o resultado da cópia.

**Exemplo B — lead que cai no Challenger (`LEADHQLB` na UTM):**

1. Idem até o `match_variant`, que casa `LEADHQLB` → variante `challenger_abr28`.
2. `pipeline.run` pontua. Suponha D8.
3. `send_both_lead_events` dispara:
   - **Primário 1:** `HQLB_LQ` no pixel `1513132406527995` (com `value=0` — não está criado no pixel, Meta ignora; mantido por enquanto por compatibilidade).
   - **Primário 2:** `HQLB` no pixel `1513132406527995` (D8+D9+D10 do Challenger).
4. **Laço de fan-out** lê a lista. Encontra entrada cujo `event_name == "HQLB"`.
5. **Cópia:** dispara `HQLB` no pixel `241752320666130` (D8+D9+D10 declarados na entrada).
6. Lead segue.

**Lead em decil baixo (ex.: D3):** o evento HQ primário não dispara (filtrado pela faixa da variante). O laço de fan-out **é executado**, mas a função `send_lead_qualified_high_quality` filtra internamente pelo `high_quality_decils_override` da destinação e também não envia. Resultado: nenhuma cópia sai. Comportamento correto.

---

## 4. Configuração — bloco YAML no cliente

Em [configs/clients/devclub.yaml](../configs/clients/devclub.yaml), dentro de `capi:`:

```yaml
capi:
  # ... (campos existentes do CAPIConfig)
  extra_hq_destinations:
    - event_name: LeadQualifiedHighQuality
      pixel_id: "241752320666130"
      decils: ["D09", "D10"]
    - event_name: HQLB
      pixel_id: "241752320666130"
      decils: ["D08", "D09", "D10"]
```

**Regras de declaração:**
- `event_name` (string, obrigatório) — case-sensitive, casa com o nome do evento primário que efetivamente saiu.
- `pixel_id` (string, obrigatório) — ID do pixel destino. Não precisa ser o mesmo dos primários.
- `decils` (lista, obrigatório) — subconjunto de `D01..D10`. Lead com decil fora dessa faixa não recebe a cópia.
- Cap operacional: **máximo 5 entradas por cliente** (salvaguarda contra runaway).
- Default: ausência do campo → comportamento legado preservado (nenhuma cópia, função idêntica à pré-fan-out).

---

## 5. Implementação — 3 arquivos efetivos

| Arquivo | Mudança |
|---|---|
| [src/core/client_config.py](../src/core/client_config.py) | Adiciona dataclass `ExtraHQDestination` (campos `event_name`, `pixel_id`, `decils`). Adiciona campo `extra_hq_destinations: Optional[List[ExtraHQDestination]]` em `CAPIConfig`. Adiciona helper `_parse_extra_hq_destinations` (fail-loud) e `_load_capi_config`. O `from_yaml` chama `_load_capi_config` no lugar do `_make(CAPIConfig, ...)` padrão. |
| [configs/clients/devclub.yaml](../configs/clients/devclub.yaml) | Adiciona o bloco `extra_hq_destinations` em `capi:` (ver §4). |
| [api/capi_integration.py](../api/capi_integration.py) | Adiciona laço logo após o disparo HQ primário em `send_both_lead_events`. Resolve o nome do evento HQ que efetivamente saiu (`event_name_hq_override` ou `capi_config.event_name_high_quality`). Para cada destinação cujo `event_name` case, chama `send_lead_qualified_high_quality` reusando os 3 overrides já existentes da função. Try/except por destinação — falha isolada não derruba o primário nem as outras cópias. Retorno passa a incluir `extra_hq_results: List[Dict]`. |

Re-export do dataclass em [src/core/\_\_init\_\_.py](../src/core/__init__.py) é apenas higiene (sem efeito comportamental).

**Não tocaram:** `app.py`, `survey_branch.py`, `pubsub_branch.py`, `active_models/devclub.yaml`. O caminho do lead — da leitura da UTM até o disparo primário — permaneceu **idêntico**.

---

## 6. Garantias e proteções

- **Fail-loud no parse** (`_parse_extra_hq_destinations`): `event_name`/`pixel_id` não vazios, `decils` ⊂ `{D01..D10}`, cap de 5 entradas. YAML inválido levanta `ValueError` com mensagem acionável (arquivo + índice + campo).
- **Default vazio = no-op**: cliente sem `extra_hq_destinations` mantém comportamento legado byte-a-byte.
- **Isolamento por try/except**: falha em uma cópia não derruba o primário, não derruba as outras cópias. Loga warning com email + índice + destino.
- **Match estrito por nome**: case-sensitive em `event_name`. Cópia só dispara se o evento primário efetivamente sair com o nome declarado.
- **Filtragem por decil dentro da função reusada**: cada destinação tem sua própria faixa; lead fora dela não recebe a cópia.
- **Princípio do A/B preservado**: cada variante continua disparando o seu evento primário no pixel principal dela — sem alteração no princípio do [AB_TEST.md](AB_TEST.md).

---

## 7. Como estende — 3 cenários

**Cenário 1 — adicionar outro pixel destino para os eventos atuais:**
Uma ou duas linhas a mais no YAML (uma por nome de evento que se quer espelhar). Zero código.

**Cenário 2 — nova variante A/B reusando o mesmo nome de evento HQ (ex.: hipotético "Challenger v2" que também emite `HQLB`):**
Automático. O laço casa por nome, então a cópia no 6130 já passa a sair pra Challenger v2 também, sem mudança nenhuma.

**Cenário 3 — nova variante A/B com nome de evento novo (ex.: estratégia ROAS V1 emitindo `LeadQualifiedHighQuality_ROAS_V1`):**
Adicionar uma terceira entrada na lista (`event_name: LeadQualifiedHighQuality_ROAS_V1`, mesmo pixel, mesma faixa) e o fan-out passa a cobrir a variante nova também. Zero código.

**O que ESTÁ fora do escopo do fan-out atual:**
- Variantes que precisem espelhar em **pixels diferentes pra cada uma** (hoje, o `event_name` é a única chave de match — não dá pra diferenciar fan-out por variante quando os primários têm o mesmo nome).
- Espelhamento do evento base (`LeadQualified` com valor) — apenas o HQ está coberto. Estender pra base é simétrico, mas exige laço análogo em `send_lead_qualified_with_value`.

---

## 8. Pré-deploy obrigatório — cadastro dos eventos no Events Manager do pixel destino

Antes do canary ir pra qualquer tráfego acima de 0%, **os eventos precisam estar criados no pixel destino no Events Manager do Meta**. Se não estiverem, o Meta dropa o evento silenciosamente (não retorna erro distintivo na CAPI).

**Como criar:** disparar evento de teste com o `test_event_code` apropriado em uma chamada CAPI controlada. O Events Manager passa a registrar o evento como "Criado" depois do primeiro disparo de teste. Detalhe operacional fica fora do escopo deste doc — coordenar com o `/mlops-architect` ou seguir o procedimento de cadastro de evento documentado por canal interno.

**Onde está em produção hoje (2026-06-07):**
- Pixel `241752320666130`, evento `LeadQualifiedHighQuality`: **a criar via teste**.
- Pixel `241752320666130`, evento `HQLB`: **a criar via teste**.

---

## 9. Rollback

**Cenário A — desligar fan-out por completo:**
Deletar o bloco `extra_hq_destinations` no [configs/clients/devclub.yaml](../configs/clients/devclub.yaml) e redeployar. Sem o bloco, o parse devolve `None`, o laço fica inerte, comportamento volta a ser exatamente o da revisão anterior (00675-jix). Sem mudança de código.

**Cenário B — desligar fan-out para um evento específico:**
Deletar só a entrada correspondente da lista. Os demais continuam.

**Cenário C — falha em produção da função `send_lead_qualified_high_quality`:**
Já protegido — try/except por destinação. Falha de cópia não derruba primário. Logs ficam em Cloud Logging com prefixo `Fan-out HQ [...] falhou`.

**Cenário D — bug estrutural no laço (ex.: loop infinito hipotético, exception não capturada):**
Reverter o commit `3d950ad` em main e redeployar. Tempo: build Docker + deploy canary + promoção (~15 min total).

---

## 10. Relação com o trabalho paralelo do EventEmitter / RoasDecileStrategy

Há uma frente em andamento em outro worktree implementando um **EventEmitter configurável** com mapping bipartido `(strategy_id, model_variant) → {decile: event_name}`, cuja motivação primária é incorporar a estratégia ROAS V1 (escolha de decil por `(probabilidade × ticket) ÷ custo` em vez de só probabilidade). O plano dessa frente (13 commits) inclui um refator do scoring (commit 7) que injeta uma `DecileStrategy` no caminho de produção.

**Implicação sobre este fan-out:**

- **Compatibilidade conceitual:** o EventEmitter é a generalização natural do fan-out atual. Ambos cobrem "mais eventos em mais lugares"; o EventEmitter cobre ainda "qual decil dispara qual evento".
- **Risco de órfão silencioso:** se o commit 7 do plano paralelo **substituir** a chamada a `send_both_lead_events` pelo EventEmitter genérico, o laço de fan-out **deixa de ser invocado** — o código continua presente no `capi_integration.py`, mas como ninguém chama mais a função onde ele vive, **os eventos atuais param de chegar no pixel 6130 sem ninguém perceber**.
- **Mitigação obrigatória:** antes do commit 7 do plano paralelo entrar em main, alinhar com quem está fazendo o trabalho. O mapping do EventEmitter **precisa cobrir explicitamente** as duas entradas que adicionamos no `devclub.yaml`:
  - `LeadQualifiedHighQuality` (D9+D10) → pixel `241752320666130`
  - `HQLB` (D8+D9+D10) → pixel `241752320666130`
- **Trajetória esperada:** quando o EventEmitter for live, este fan-out vira redundante. A migração é: declarar essas duas entradas no novo mapping → remover `extra_hq_destinations` do YAML → remover o laço do `capi_integration.py`. Vira uma simplificação natural, sem rollback.

---

## 11. Pendências

1. **Testes unitários ausentes** — criar `V2/tests/test_fan_out_hq.py` cobrindo:
   - Lista vazia → nenhuma chamada extra a `send_lead_qualified_high_quality`.
   - Match → cópia disparada com overrides corretos.
   - Mismatch (event_name diferente) → cópia não disparada.
   - Falha em uma destinação não impede as outras (try/except).
   - Parser fail-loud rejeita YAML inválido (cap, decis inválido, campos vazios).
2. **Observabilidade do fan-out** — o retorno tem `extra_hq_results`, mas nenhum consumidor lê isso hoje. Se quisermos métrica de "quantas cópias saíram em produção", precisa log estruturado adicional ou contagem em `registros_ml`. Decisão deferida até primeiro lançamento real pós-fan-out.
3. **Coordenação com EventEmitter (§10)** — abrir issue/Slack quando o commit 7 do plano paralelo for próximo de entrar.

---

## 12. Histórico

- **2026-05-27** — 1ª tentativa: fan-out no nível variante (`ABTestVariantConfig`), 7 arquivos mexidos. Deploy chegou a `00678-vuy` (0% tráfego) mas o usuário interrompeu antes de promover. **Revertido** no commit `06e97ba` no mesmo dia.
- **2026-06-07 manhã** — Discussão arquitetural pós-revert: identificado que fan-out é regra de cliente, não de variante. Redesenho via `/sw-architect` chegou na versão "nível CLIENTE, match por event_name".
- **2026-06-07** — Implementação no commit `3d950ad`, 4 arquivos efetivos (incluindo re-export em `__init__.py`).
- **2026-06-07** — Deploy canary `smart-ads-api-00680-jez` a 0% tráfego. Gates B/D/C.1/C.2 passados (50 leads cada, 0 divergências vs produção). Aguardando autorização para promover.

---

*Artefatos vivos:* [src/core/client_config.py](../src/core/client_config.py) (dataclass + parser), [configs/clients/devclub.yaml](../configs/clients/devclub.yaml) (bloco `extra_hq_destinations`), [api/capi_integration.py](../api/capi_integration.py) (laço dentro de `send_both_lead_events`).

*Documentos relacionados:* [AB_TEST.md](AB_TEST.md) (princípio "uma variante = um evento"), [PROCESSO_CAPI_LEAD_SURVEYS.md](PROCESSO_CAPI_LEAD_SURVEYS.md) (caminhos de entrada do lead — webhook `Lead` e consumer Pub/Sub — que convergem em `send_batch_events` → `send_both_lead_events`).

*Pixels envolvidos:* `1937807493703815` (Champion, primário), `1513132406527995` (Challenger, primário), `241752320666130` (BM Rodolfo Mori, fan-out adicional).

*Cloud Run:* revisão de produção atual `smart-ads-api-00675-jix` (sem fan-out), revisão canary com fan-out `smart-ads-api-00680-jez` (0% tráfego em 2026-06-07).

*Commits relevantes:* `e52469c` (1ª tentativa, revertida), `06e97ba` (revert), `3d950ad` (versão atual).
