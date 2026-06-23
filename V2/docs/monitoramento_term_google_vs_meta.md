# Monitoramento do `utm_term`: separar Google legítimo do macro Meta quebrado

**Criado:** 2026-06-23
**Frente:** `feat/monitoring-term-source-aware` (só monitoramento — sem retreino)
**Relacionado:** [analise_valor_decil_por_canal_google_vs_meta.md](analise_valor_decil_por_canal_google_vs_meta.md)

> **Em uma frase:** o bucket "outros" do `utm_term` estava inflado por dois motivos que o alerta confundia — placeholder do Meta que não renderizou (problema real, pequeno) e ID de campanha do Google Ads (legítimo, crescente) — e esta frente ensina o monitoramento a separar os dois; no próximo retreino, a decisão a tomar não é "criar categoria pro Google", e sim **testar por ablação se o `Term`/UTM deve seguir no scoring**, porque é redundante com a feature de fonte (`Source`) e quase não move a métrica.

---

## 1. O problema

O campo `utm_term` deveria conter só o sub-source do Meta — `ig` (Instagram) ou `fb` (Facebook). Qualquer outra coisa cai no balde **"outros"** depois da unificação (`core/utm.py`). Dois conteúdos muito diferentes estavam caindo nesse mesmo balde e sendo somados como se fossem o mesmo problema:

| Conteúdo no `utm_term` | O que é | Volume | É problema? |
|---|---|---|---|
| `{{site_source_name}}`, `{{ad.name}}` etc. (literal) | **Macro do Meta não-substituído** — o anúncio manda o placeholder cru porque os parâmetros de URL estão URL-encoded no destino e o Meta não troca por `ig`/`fb`. Tráfego in-app. | ~1-3% dos leads de Meta | Sim, mas **operacional** (descodificar o macro no anúncio), não de modelo. Cai em `Term_outros`, que é categoria treinada — o modelo não quebra. |
| `23731741326--203657325788--8043819` (IDs com `--`) | **ID de campanha/conjunto/anúncio do Google Ads.** O Google põe isso no `utm_term` por padrão — ele **não tem** sub-source IG/FB. | ~23% do volume total (e crescendo) | **Não.** É legítimo. Cai em "outros" por design. |

### Por que aparecia "32% de drift" assustador

O alerta de **drift de distribuição** (`check_distribution_drift`, o que compara a proporção de cada categoria hoje contra a proporção no treino) media a população de produção **inteira, todas as fontes**, contra um baseline de treino que era **predominantemente Meta** (quando o Google era ~10% do mix). Como o Google cresceu para ~23%, a proporção de "outros" subiu de ~10,7% (treino) para ~32% (hoje) — **um artefato de mudança de mix de canal, não corrupção de dado.** A pista que entrega isso: Champion e Challenger mostravam o **mesmo** 32%, porque é um único número global comparado contra dois baselines diferentes.

Enquanto isso, o alerta-irmão de **bucket inflado** (`_check_outros_buckets`) já restringe o `utm_term` a `facebook-ads` e mostrava o número honesto (~1,7%) — o macro Meta de verdade.

---

## 2. O que mudou no monitoramento (esta frente, sem retreino)

### Item A — separar "categoria-nova" de "macro Meta" no alerta de bucket inflado

`_check_outros_buckets` (em `src/monitoring/data_quality.py`) agora classifica o conteúdo de "outros" em dois sub-tipos e aplica **gatilhos diferentes**:

- **categoria-nova** (valor de UTM nunca visto no treino — o sinal valioso, porque o modelo não tem feature pra ele): alerta no nível normal, **>2%**.
- **macro Meta não-resolvido** (`{{...}}` — artefato de tracking conhecido): **só alerta se estourar, >10%**. No nível normal de ~1-3% fica silencioso.

A separação vive na função de breakdown (`_query_railway_outros_breakdown_enriched`, que agora devolve `macro_count`/`novel_count` além de `outros_count`). Os thresholds e os marcadores de macro (`['{', '%7b']`) ficam em `src/monitoring/config.py` → `THRESHOLDS['outros_buckets']` (`min_pct_threshold`, `macro_spike_threshold`, `macro_markers`).

### Item B — silenciar o drift (Term, outros), porque o Google o domina

A medida de drift de "outros" no `utm_term` é cega de fonte (mistura Google), então foi **silenciada** via o mecanismo que já existia para isso: `silenced_drift_changes` no `configs/clients/devclub.yaml` (a mesma lista que já silencia `Term/facebook` e públicos do Medium). Com isso o alerta de **bucket inflado** (restrito a `facebook-ads`) passa a ser a **autoridade única** de "Term outros inflado" — eliminando a medida duplicada e cega-de-fonte, e resolvendo a inconsistência "produção all-sources × baseline Meta" sem precisar recomputar artefato nem retreinar.

**Cobertura preservada:** se o macro Meta realmente estourar, o Item A dispara (>10%, restrito a Meta). O silêncio do Item B só apaga o ruído do Google, não o sinal acionável do Meta.

---

## 3. Nota de retreino (frente futura — NÃO feita aqui)

**Recomendação principal: rodar uma ablação do `Term`/UTM antes de mexer nas categorias.** A intuição que motiva isso (registrada em conversa de 2026-06-23): a feature `Term` é em boa parte **redundante** com a feature de fonte (`Source`). O eixo "Meta vs Google" está nos dois — `Source_google-ads` ≈ `Term_outros`, já que o Google cai em "outros" por design. O **único** pedaço exclusivo do `Term` é o sub-source **Instagram vs Facebook** (que o `Source` não vê, porque o `utm_source` chega cravado como `facebook-ads`).

Isso importa porque:

1. **O modelo é uma RandomForest** — colinearidade não quebra a predição (quem sofre com isso é modelo linear), mas **reparte a importância** entre as features correlacionadas. É parte do motivo de o `Term` aparecer no meio-baixo do ranking: o `Source` já carrega o sinal compartilhado.
2. **O experimento de moat** ([EXPERIMENTO_MOAT_MODELO.md](EXPERIMENTO_MOAT_MODELO.md)) mediu que as features de UTM **diluíram a AUC em −0,0024 vs usar só a pesquisa** — ou seja, no dataset atual o `Term`/UTM provavelmente não está pagando o próprio lugar no scoring.

**Decisão a tomar no retreino (não antes):**

- **Treinar com e sem `Term`/UTM e comparar** (AUC, calibração, distribuição de decis). 
- Se o `Term`/UTM **não ajuda** (ou atrapalha): **tirar do scoring** e manter UTM só pra atribuição. Isso dissolve o problema do "outros" na raiz — sem feature de `Term`, não há bucket pra inflar.
- Se o `Term`/UTM **ajuda mesmo assim**: aí sim **dar ao Google uma categoria própria** (ex.: `Term_google`) em vez de empilhar em `Term_outros`, pra a feature mantida ficar limpa — e recomputar o baseline de drift (`capture_training_distributions`) consistente com o novo rótulo.

Em qualquer dos caminhos:

- **O valor do lead Google já foi analisado** (ver [analise_valor_decil_por_canal_google_vs_meta.md](analise_valor_decil_por_canal_google_vs_meta.md)): o ranqueamento de decil do Challenger transfere pro Google e o valor (componente de conversão) é ≈ igual ao do Meta. O Google não é público "pior" — só é canal sem sub-source IG/FB.
- **Quando o retreino entrar, o silêncio do Item B sai:** remover a entrada `Term/outros` de `silenced_drift_changes` e reavaliar o drift com o espaço de feature decidido.

---

## 4. Como reverter / quando reavaliar

- **Item A:** ajustar/zerar `macro_spike_threshold` em `THRESHOLDS['outros_buckets']`; voltar a `min_pct_threshold` sozinho replica o comportamento antigo (todo "outros" conta junto).
- **Item B:** remover a entrada `Term/outros` de `silenced_drift_changes` no `devclub.yaml` reativa o drift cego-de-fonte.
- **Gatilho de reavaliação:** próximo retreino (item 3 acima), ou se a fatia de Google mudar bruscamente o suficiente pra distorcer também as proporções de `ig`/`fb` no drift (dilui​ção de Meta) — nesse caso o ideal passa a ser baseline Meta-only nos dois lados, não só silêncio.
