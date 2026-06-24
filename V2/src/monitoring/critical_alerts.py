"""
Alertas críticos — disparos imediatos no Slack, independentes do digest diário.

Hookado dentro do polling /railway/process-pending que já roda a cada 5min via
Cloud Scheduler existente. Custo zero adicional (sem novo scheduler, sem novo
endpoint, sem novo banco). Estado persistido em JSON no GCS.

Spec: docs/CRITICAL_ALERTS_SPEC.md

Princípios:
  - DM pessoal (SLACK_USER_DM), nunca canal do cliente.
  - 24/7, sem quiet hours.
  - Janela rolling de 60min por regra.
  - Cooldown de 15min por regra (estado em GCS).
  - GCS write SÓ em transição de estado (OK↔FIRED) — mantém free tier.
  - Dry-run controlado por CRITICAL_ALERTS_DRY_RUN=true (default seguro).

Regras:
  1. variant_no_capi              — leads scored ≥ N mas 0 CAPI enviado em 60min
  4. no_leads_arriving            — 0 leads inseridos em Lead em 60min
  5. capi_success_low             — capi_success_rate < 95% em 60min (N≥10 enviados)
  9. polling_500                  — /railway/process-pending falhou em ≥2 pollings seguidos
  +  score_drift                  — score médio 1σ off (A) OU KS p<0.01 / ΔD10≥5pp (B)
  +  pubsub_consumer_stalled      — PUBSUB_CAPI_ENABLED=true e zero linhas novas em
                                    registros_ml em 60min (consumer parado)
  +  pubsub_error_rate_high       — base_status='error' / total > 10% em 24h (N≥20)
  +  pubsub_skipped_missing_data  — skipped_missing_data / Meta-elegíveis > 30% em
                                    24h (N≥20) — substitui o fbp_fbc_low antigo
                                    (que lia Lead × leads_capi, ambas mortas)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────

GCS_BUCKET     = 'smart-ads-validation-reports'
GCS_STATE_PATH = 'monitoring/critical_alerts/state.json'
COOLDOWN_MIN   = 15
RESOLVE_MIN    = 30
WINDOW_MIN     = 60

BRT = timezone(timedelta(hours=-3))


# ──────────────────────────────────────────────────────────────────────────
# Types
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class RuleResult:
    """Resultado de uma avaliação de regra."""
    rule_name: str
    fired: bool
    severity: str = 'HIGH'                 # 'HIGH' | 'MEDIUM' | (informativo)
    message: str = ''
    skipped_reason: Optional[str] = None   # quando fired=False por skip semântico
    details: dict = field(default_factory=dict)


@dataclass
class RuleState:
    """Estado persistido por regra no GCS."""
    last_fired_at: Optional[str] = None        # ISO UTC — última vez que a condição esteve ON
    last_resolved_at: Optional[str] = None     # ISO UTC
    consecutive_fires: int = 0
    last_message: Optional[str] = None
    # Piso de envio independente do ciclo fire/resolve. Garante no máx. 1 DM por
    # regra a cada COOLDOWN_MIN, mesmo que a regra resolva e re-dispare rápido
    # (bug do spam de 5/5min observado em 15/05/2026 na madrugada).
    last_sent_at: Optional[str] = None         # ISO UTC


# ──────────────────────────────────────────────────────────────────────────
# State store (GCS)
# ──────────────────────────────────────────────────────────────────────────

class GcsStateStore:
    """
    Lê/escreve JSON com estado das regras em GCS. Escreve SÓ quando muda
    pra evitar Class A ops desnecessárias (mantém zero custo).
    """

    def __init__(self, bucket: str = GCS_BUCKET, path: str = GCS_STATE_PATH):
        self.bucket_name = bucket
        self.path = path
        self._states: dict[str, RuleState] = {}
        self._loaded = False
        self._dirty = False
        # True quando a leitura do GCS FALHOU (≠ arquivo ausente). Nesse caso
        # não sabemos o cooldown → dispatcher NÃO envia (fail-closed) pra não
        # spammar 12×/h quando o estado está indisponível.
        self._load_failed = False

    def _client(self):
        from google.cloud import storage
        return storage.Client()

    def load(self) -> None:
        if self._loaded:
            return
        try:
            blob = self._client().bucket(self.bucket_name).blob(self.path)
            if blob.exists():
                raw = json.loads(blob.download_as_text())
                self._states = {
                    name: RuleState(**data) for name, data in raw.items()
                }
                logger.debug(f"[critical_alerts] state loaded: {len(self._states)} regras")
            else:
                self._states = {}
                logger.info(f"[critical_alerts] state ausente em gs://{self.bucket_name}/{self.path} — inicializando vazio")
        except Exception as e:
            logger.warning(f"[critical_alerts] falha lendo state GCS — fail-closed (não envia): {e}")
            self._states = {}
            self._load_failed = True
        self._loaded = True

    def get(self, rule_name: str) -> RuleState:
        self.load()
        return self._states.setdefault(rule_name, RuleState())

    def set(self, rule_name: str, state: RuleState) -> None:
        self.load()
        old = self._states.get(rule_name)
        if old != state:
            self._states[rule_name] = state
            self._dirty = True

    def flush(self) -> None:
        """Persiste no GCS se houve mudança. No-op caso contrário."""
        if not self._dirty:
            return
        try:
            payload = {name: asdict(s) for name, s in self._states.items()}
            blob = self._client().bucket(self.bucket_name).blob(self.path)
            blob.upload_from_string(json.dumps(payload, indent=2), content_type='application/json')
            self._dirty = False
            logger.info(f"[critical_alerts] state flushed para gs://{self.bucket_name}/{self.path}")
        except Exception as e:
            logger.error(f"[critical_alerts] falha gravando state GCS: {e}")


# ──────────────────────────────────────────────────────────────────────────
# Slack dispatcher
# ──────────────────────────────────────────────────────────────────────────

class SlackDispatcher:
    """Posta DM via chat.postMessage para SLACK_USER_DM. Respeita cooldown."""

    def __init__(self, store: GcsStateStore, dry_run: bool):
        self.store = store
        self.dry_run = dry_run
        self.user_id = os.environ.get('SLACK_USER_DM')
        self.token = os.environ.get('SLACK_BOT_TOKEN')

    def maybe_send(self, result: RuleResult) -> str:
        """
        Decide se envia o DM. Retorna o status:
          'sent'        — postou no Slack
          'dry_run'     — dry_run on, logou apenas
          'cooldown'    — dentro do cooldown da regra
          'no_change'   — regra resolveu, nada a fazer
          'error'       — falha enviando
        """
        now = datetime.now(timezone.utc)

        # Fail-closed: se a leitura do estado falhou, não sabemos o cooldown.
        # Preferir perder 1 alerta a spammar 12×/h. (Vide GcsStateStore.load.)
        if getattr(self.store, '_load_failed', False):
            logger.warning(
                f"[critical_alerts] {result.rule_name}: estado GCS indisponível — "
                f"suprimindo envio (fail-closed)"
            )
            return 'state_unavailable'

        state = self.store.get(result.rule_name)

        if not result.fired:
            if state.last_fired_at:
                last_fired = datetime.fromisoformat(state.last_fired_at)
                if (now - last_fired) >= timedelta(minutes=RESOLVE_MIN):
                    # Resolve zera o ciclo fire, mas PRESERVA last_sent_at — o
                    # piso de envio não pode ser burlado por resolve→refire.
                    state = RuleState(
                        last_fired_at=None,
                        last_resolved_at=now.isoformat(),
                        consecutive_fires=0,
                        last_message=None,
                        last_sent_at=state.last_sent_at,
                    )
                    self.store.set(result.rule_name, state)
                    logger.info(f"[critical_alerts] {result.rule_name}: resolvido")
                    return 'no_change'
            return 'no_change'

        # fired=True — piso de envio é last_sent_at (independe de fire/resolve).
        if state.last_sent_at:
            last_sent = datetime.fromisoformat(state.last_sent_at)
            if (now - last_sent) < timedelta(minutes=COOLDOWN_MIN):
                state.last_fired_at = state.last_fired_at or now.isoformat()
                state.consecutive_fires += 1
                state.last_message = result.message
                self.store.set(result.rule_name, state)
                logger.info(
                    f"[critical_alerts] {result.rule_name}: cooldown "
                    f"({state.consecutive_fires}× consecutivos desde último envio)"
                )
                return 'cooldown'

        # Vamos enviar.
        ts_brt = now.astimezone(BRT).strftime('%H:%M BRT')
        text = (
            f"🚨 *[CRÍTICO]* {result.rule_name}\n"
            f"_Detectado às {ts_brt}_  ·  Janela: últimos {WINDOW_MIN}min\n"
            f"{result.message}"
        )

        if self.dry_run:
            logger.warning(f"[critical_alerts][DRY-RUN] enviaria DM:\n{text}")
            status = 'dry_run'
        else:
            status = self._post_dm(text)

        new_state = RuleState(
            last_fired_at=now.isoformat(),
            last_resolved_at=state.last_resolved_at,
            consecutive_fires=(state.consecutive_fires or 0) + 1,
            last_message=result.message,
            # Só atualiza o piso quando de fato saiu DM (sent/dry_run contam;
            # error não conta, pra permitir retry no próximo polling).
            last_sent_at=(now.isoformat()
                          if status in ('sent', 'dry_run')
                          else state.last_sent_at),
        )
        self.store.set(result.rule_name, new_state)
        return status

    def _post_dm(self, text: str) -> str:
        if not (self.user_id and self.token):
            logger.error("[critical_alerts] SLACK_USER_DM ou SLACK_BOT_TOKEN ausente — não enviei")
            return 'error'
        try:
            import urllib.request
            body = json.dumps({'channel': self.user_id, 'text': text}).encode('utf-8')
            req = urllib.request.Request(
                'https://slack.com/api/chat.postMessage',
                data=body,
                headers={
                    'Content-Type': 'application/json; charset=utf-8',
                    'Authorization': f'Bearer {self.token}',
                },
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = json.load(r)
            if not resp.get('ok'):
                logger.error(f"[critical_alerts] Slack rejeitou: {resp}")
                return 'error'
            return 'sent'
        except Exception as e:
            logger.error(f"[critical_alerts] erro postando Slack: {e}")
            return 'error'


# ──────────────────────────────────────────────────────────────────────────
# Regras
# ──────────────────────────────────────────────────────────────────────────

def _window_start_utc() -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=WINDOW_MIN)


def _window_start_utc_naive() -> datetime:
    """Janela de 60min como datetime UTC NAIVE — pra colunas `timestamp without
    time zone` (ex.: lead_surveys.submittedAt, gravado em UTC sem tz)."""
    return datetime.utcnow() - timedelta(minutes=WINDOW_MIN)


def rule_no_leads_arriving(repo) -> RuleResult:
    """Regra 4: 0 leads novos nos últimos 60min.

    Fonte: `registros_ml` (ledger no Cloud SQL, populado pelo consumer Pub/Sub),
    lido pela camada `LeadRepository` — mesma fonte das demais regras Pub/Sub.
    Substitui a `lead_surveys` (morta em 21/05 — o front parou de gravar nela;
    a regra antiga dava falso positivo com inflow real saudável). 24/7, sem
    quiet hours.
    """
    leads = repo.recent_leads(window_minutes=WINDOW_MIN)
    if len(leads) > 0:
        return RuleResult('no_leads_arriving', fired=False)
    msg = (
        f"Zero leads novos em {WINDOW_MIN}min (registros_ml). "
        f"O inflow do Pub/Sub (LP/Prisma → consumer) pode estar travado."
    )
    return RuleResult('no_leads_arriving', fired=True, message=msg)


def rule_capi_success_low(repo) -> RuleResult:
    """Regra 5: ≥10 enviados em 60min mas success rate < 95%.

    "Enviado" = lead que passou pelo envio CAPI ao Meta (status `success` ou
    `error`). Status `skipped_*` não contam — são leads que nem tentaram
    enviar (allowlist barrou ou faltou fbp/fbc/computador).

    Migrada para o `LeadRepository` em 2026-05-24 (Etapa 2 do refator do
    monitoramento). Fonte hoje: ledger novo `registros_ml`.
    """
    leads = repo.recent_leads(window_minutes=WINDOW_MIN)
    ok  = sum(1 for r in leads if r.status_envio == 'success')
    err = sum(1 for r in leads if r.status_envio == 'error')
    sent = ok + err
    if sent < 10:
        return RuleResult('capi_success_low', fired=False,
                          skipped_reason=f'amostra insuficiente (sent={sent})')
    rate = (ok / sent) * 100
    if rate >= 95:
        return RuleResult('capi_success_low', fired=False)
    msg = (
        f"capi_success_rate = {rate:.1f}% em {WINDOW_MIN}min (limite 95%). "
        f"sent={sent}, ok={ok}, err={err}."
    )
    return RuleResult('capi_success_low', fired=True, message=msg,
                      details={'sent': sent, 'ok': ok, 'err': err, 'rate_pct': round(rate, 1)})


def rule_variant_no_capi(repo) -> RuleResult:
    """Regra 1: variante do A/B com pipeline CAPI quebrado.

    Para cada variante {champion, challenger}: se ≥10 leads passaram pelo
    pipeline (status_envio in {success, error}) mas 0 chegaram a `success`,
    dispara — sinal de que **todas** as chamadas CAPI dessa variante falharam.

    Migrada para `LeadRepository` em 2026-05-24 (Etapa 3 do refator do
    monitoramento). A versão antiga era agregada porque a tabela `Lead` não
    tinha coluna `variant`; o ledger novo (`registros_ml`) tem, então agora
    detecta quebra isolada de uma das variantes.
    """
    leads = repo.recent_leads(window_minutes=WINDOW_MIN)
    # "Passou pelo pipeline" = não foi pulado por allowlist nem missing data.
    # status_envio in (success, error) significa que houve chamada CAPI.
    scoreados = [l for l in leads if l.status_envio in ('success', 'error')]

    fired_variants: list[tuple[str, int, int]] = []  # (variant, scored, err)
    for v in ('champion', 'challenger'):
        v_scored = [l for l in scoreados if l.variant == v]
        v_ok = sum(1 for l in v_scored if l.status_envio == 'success')
        if len(v_scored) >= 10 and v_ok == 0:
            v_err = sum(1 for l in v_scored if l.status_envio == 'error')
            fired_variants.append((v, len(v_scored), v_err))

    if not fired_variants:
        if len(scoreados) < 10:
            return RuleResult('variant_no_capi', fired=False,
                              skipped_reason=f'amostra insuficiente (scored={len(scoreados)})')
        return RuleResult('variant_no_capi', fired=False)

    partes = [f"{v}: {n} scoreados, {e} erros, 0 sucessos"
              for v, n, e in fired_variants]
    msg = (
        f"{len(fired_variants)} variante(s) do A/B com 100% de falha CAPI em "
        f"{WINDOW_MIN}min — " + "; ".join(partes) + ". Possível quebra no envio."
    )
    return RuleResult(
        'variant_no_capi', fired=True, message=msg,
        details={
            'variantes_afetadas': [v for v, _, _ in fired_variants],
            'detalhes_por_variante': {
                v: {'scoreados': n, 'erros': e} for v, n, e in fired_variants
            },
        },
    )


def rule_pubsub_consumer_stalled(conn) -> RuleResult:
    """R1: Consumer Pub/Sub parado.

    Dispara se `PUBSUB_CAPI_ENABLED=true` e zero linhas novas em `registros_ml`
    nos últimos 60min. Pulada (skipped) se a flag está desligada (consumer não
    deveria processar) ou se o ledger está completamente vazio — provavelmente
    primeira hora pós-deploy, vai populando.

    `registros_ml.created_at` é `TIMESTAMP` sem tz, gravado em UTC pelo default
    `now()` do PostgreSQL → cutoff UTC naive (mesma convenção do
    `rule_no_leads_arriving` lendo `lead_surveys.submittedAt`).
    """
    if os.environ.get('PUBSUB_CAPI_ENABLED', 'false').lower() != 'true':
        return RuleResult('pubsub_consumer_stalled', fired=False,
                          skipped_reason='PUBSUB_CAPI_ENABLED desligado')
    cutoff = _window_start_utc_naive()
    rows = conn.run(
        'SELECT '
        '  COUNT(*) FILTER (WHERE created_at >= :cutoff) AS recent, '
        '  COUNT(*) AS total, '
        '  MAX(created_at) AS last_at '
        'FROM registros_ml',
        cutoff=cutoff,
    )
    recent, total, last_at = (rows[0][0] or 0, rows[0][1] or 0, rows[0][2])
    if total == 0:
        return RuleResult('pubsub_consumer_stalled', fired=False,
                          skipped_reason='ledger vazio (consumer nunca rodou)')
    if recent > 0:
        return RuleResult('pubsub_consumer_stalled', fired=False)
    last_iso = last_at.isoformat() if last_at else 'desconhecido'
    msg = (
        f"Consumer Pub/Sub parado: zero linhas novas em `registros_ml` em "
        f"{WINDOW_MIN}min. Última gravação: {last_iso}. Verificar "
        f"/pubsub/process-pending, IAM da subscription e Cloud Scheduler."
    )
    return RuleResult(
        'pubsub_consumer_stalled', fired=True, severity='HIGH', message=msg,
        details={'recent_60min': recent, 'total': total,
                 'last_at': last_iso if last_at else None},
    )


def rule_pubsub_error_rate_high(conn) -> RuleResult:
    """R2: Taxa de erro do consumer Pub/Sub.

    Dispara se `count(base_status='error') / count(*) > 10%` nas últimas 24h.
    N≥20 pra evitar falso positivo com pouca amostra. Janela é 24h
    (não 60min) — erros podem ser bursty; janela larga capta tendência.

    Investigação: `SELECT error_message, COUNT(*) FROM registros_ml WHERE
    base_status='error' AND created_at >= NOW() - INTERVAL '24 hours' GROUP BY
    1 ORDER BY 2 DESC LIMIT 10;`
    """
    cutoff = datetime.utcnow() - timedelta(hours=24)
    rows = conn.run(
        'SELECT '
        '  COUNT(*) AS n, '
        "  COUNT(*) FILTER (WHERE base_status = 'error') AS err "
        'FROM registros_ml WHERE created_at >= :cutoff',
        cutoff=cutoff,
    )
    n, err = (rows[0][0] or 0, rows[0][1] or 0)
    if n < 20:
        return RuleResult('pubsub_error_rate_high', fired=False,
                          skipped_reason=f'amostra insuficiente (n={n})')
    rate = (err / n) * 100
    if rate < 10:
        return RuleResult('pubsub_error_rate_high', fired=False)
    msg = (
        f"Taxa de erro do consumer Pub/Sub = {rate:.1f}% em 24h "
        f"(limite 10%). N={n}, errors={int(err)}. "
        f"Investigar `registros_ml.error_message` para padrões."
    )
    return RuleResult(
        'pubsub_error_rate_high', fired=True, severity='HIGH', message=msg,
        details={'n': n, 'err': int(err), 'rate_pct': round(rate, 1)},
    )


def rule_pubsub_skipped_missing_data_high(conn) -> RuleResult:
    """R3: Skipped por missing data alto entre Meta-elegíveis.

    Dispara se `count(skipped_missing_data) / count(Meta-elegíveis) > 30%` em
    24h. "Meta-elegível" = qualquer status EXCETO `skipped_allowlist` (que é
    a categoria de leads que nem deveriam ir pro Meta por allowlist de utm).

    Substitui `rule_fbp_fbc_low` da arquitetura SQL/Railway antiga — que
    cruzava `Lead × leads_capi` (ambas mortas desde 17/05/2026) e media o
    mesmo sinal: leads Meta-elegíveis perdendo `fbp`/`fbc`/`computador`.
    Agora a classificação acontece dentro do consumer Pub/Sub
    ([api/pubsub_branch.py:classify]) e marca o lead direto no ledger.
    """
    cutoff = datetime.utcnow() - timedelta(hours=24)
    rows = conn.run(
        'SELECT '
        "  COUNT(*) FILTER (WHERE base_status <> 'skipped_allowlist') AS eligible, "
        "  COUNT(*) FILTER (WHERE base_status = 'skipped_missing_data') AS missing "
        'FROM registros_ml WHERE created_at >= :cutoff',
        cutoff=cutoff,
    )
    eligible, missing = (rows[0][0] or 0, rows[0][1] or 0)
    if eligible < 20:
        return RuleResult('pubsub_skipped_missing_data_high', fired=False,
                          skipped_reason=f'amostra insuficiente (eligible={eligible})')
    pct = (missing / eligible) * 100
    if pct < 30:
        return RuleResult('pubsub_skipped_missing_data_high', fired=False)
    msg = (
        f"{pct:.1f}% dos leads Meta-elegíveis foram pulados por missing data "
        f"em 24h (limite 30%). N_elegíveis={eligible}, missing={int(missing)}. "
        f"Provável regressão na captura de `computador`, `fbp` ou `fbc` no "
        f"sistema novo — investigar payload Pub/Sub recente."
    )
    return RuleResult(
        'pubsub_skipped_missing_data_high', fired=True, severity='HIGH', message=msg,
        details={'eligible': eligible, 'missing': int(missing),
                 'pct': round(pct, 1)},
    )


def rule_utm_source_missing(repo) -> RuleResult:
    """Regra +: % de leads chegando SEM `utm_source` em 60min acima do limiar.

    Pega regressão de captura/tracking — leads de campanha perdendo a origem
    (não vão pro Meta porque a allowlist barra, e o modelo scoreia cego de
    origem). O pico de 21-22/04/2026 (até 20%) passou sem nenhum alarme;
    orgânico legítimo é ~1,5% e a base normal <1%, então o limiar HIGH de 5%
    separa regressão de orgânico normal sem spammar entre lançamentos.

    Contexto histórico: `registro_erros_ml.md` Erro 18 (tracking perdendo
    source) e § V.6.

    Migrada para `LeadRepository` em 2026-05-24 (Etapa 3 do refator do
    monitoramento). Fonte hoje: ledger novo `registros_ml.utm_source`.
    """
    leads = repo.recent_leads(window_minutes=WINDOW_MIN)
    n = len(leads)
    sem = sum(1 for l in leads
              if l.utm_source is None or (l.utm_source or '').strip() == '')
    if n < 50:
        return RuleResult('utm_source_missing', fired=False,
                          skipped_reason=f'amostra insuficiente (n={n})')
    pct = (sem / n) * 100
    if pct < 5.0:
        return RuleResult('utm_source_missing', fired=False)
    msg = (
        f"{pct:.1f}% dos leads chegaram SEM `utm_source` em {WINDOW_MIN}min "
        f"(limite HIGH 5%, N={n}, {sem} sem source). Possível regressão de "
        f"captura/tracking: leads de campanha perdendo a origem — não vão "
        f"pro Meta (allowlist barra) e o modelo scoreia cego de origem. "
        f"Investigar front-end / webhook de captura."
    )
    return RuleResult('utm_source_missing', fired=True, severity='HIGH', message=msg,
                      details={'n': n, 'sem_source': sem, 'pct': round(pct, 1)})


def rule_polling_500(store: GcsStateStore) -> RuleResult:
    """
    Regra 9: /railway/process-pending falhou em ≥2 pollings consecutivos.

    Estado adicional no mesmo state.json: chave especial `_polling_status` com
    lista das últimas N execuções (status, timestamp). Atualizada pelo próprio
    hook em api/app.py (start e fim do endpoint).
    """
    state = store.get('_polling_status_tracker')
    # Reusamos last_message pra guardar a lista das últimas exec (CSV simples):
    # "ok,error,ok,..." — mais leve que estrutura aninhada.
    history = (state.last_message or '').split(',')
    history = [s for s in history if s in ('ok', 'error')]
    if len(history) < 2:
        return RuleResult('polling_500', fired=False,
                          skipped_reason=f'amostra insuficiente (len={len(history)})')
    last_two = history[-2:]
    if not all(s == 'error' for s in last_two):
        return RuleResult('polling_500', fired=False)
    msg = f"/railway/process-pending falhou nos últimos 2 pollings. Leads pendentes podem estar acumulando."
    return RuleResult('polling_500', fired=True, message=msg,
                      details={'recent_history': ','.join(history[-10:])})


def rule_score_drift(repo, baseline_repo, expected_decil_dist: Optional[dict]) -> RuleResult:
    """Regra +: drift de score em 60min vs baseline rolling 30d.

    Dispara se (A) score médio da janela > 1σ off do baseline OU (B) ΔD10 ≥ 5pp
    vs `expected_decil_dist`.

    Migrada para `LeadRepository` em 2026-05-24 (Etapa 3 do refator do
    monitoramento). Fonte dividida durante a transição:
      - janela curta (60min) → `repo` (ledger novo `registros_ml`, populado
        pelo consumer Pub/Sub desde 2026-05-23).
      - baseline 30d → `baseline_repo` (tabela `Lead` antiga, morta em
        17/05/2026) com FALLBACK pro próprio `repo` (ledger) quando o legado
        não tiver amostra — sem o fallback a regra ficaria cega entre ~18/06
        (janela de 31d esvazia a `Lead`) e ~22/06 (ledger completa 30d).
        Pós-22/06 o fallback vira o caminho permanente e `baseline_repo`
        pode ser removido (PLANO_LEDGER_CLOUDSQL.md §3.3 e §5).
    """
    import statistics
    leads_window = repo.recent_leads(window_minutes=WINDOW_MIN)
    scores = [l.score for l in leads_window if l.score is not None]
    decis  = [l.decil for l in leads_window if l.decil is not None]
    n_score = len(scores)
    n_decil = len(decis)

    if n_score < 50:
        return RuleResult('score_drift', fired=False,
                          skipped_reason=f'amostra de scores insuficiente (n={n_score})')

    # Baseline rolling 30d: ignora as últimas 24h pra evitar contaminar a
    # referência com o presente em movimento.
    now = datetime.utcnow()
    base_start = now - timedelta(days=31)
    base_end   = now - timedelta(days=1)
    base_leads = baseline_repo.leads_in_range(base_start, base_end)
    base_scores = [l.score for l in base_leads if l.score is not None]
    baseline_source = 'legacy'
    if len(base_scores) < 1000:
        # Tabela "Lead" morta (17/05) esvazia a janela de 31d em ~18/06.
        # Fallback: o ledger usa o que tiver desde 23/05 — mesma fonte da
        # janela curta, então a comparação segue maçã-com-maçã.
        base_leads = repo.leads_in_range(base_start, base_end)
        base_scores = [l.score for l in base_leads if l.score is not None]
        baseline_source = 'registros_ml'
    if len(base_scores) < 1000:
        return RuleResult('score_drift', fired=False,
                          skipped_reason='baseline rolling 30d insuficiente (legacy e ledger)')
    base_mean = statistics.fmean(base_scores)
    base_sd = statistics.pstdev(base_scores)
    if base_sd == 0:
        return RuleResult('score_drift', fired=False,
                          skipped_reason='baseline com desvio padrão zero')

    window_mean = statistics.fmean(scores)
    z = (window_mean - base_mean) / base_sd if base_sd > 0 else 0.0

    # (A) shift de média
    fired_a = abs(z) >= 1.0

    # (B) decis: ΔD10 ≥ 5pp (KS opcional — usamos só ΔD10 pra simplificar e evitar scipy aqui)
    fired_b = False
    d10_pct_window = None
    d10_pct_base = None
    if n_decil >= 100 and expected_decil_dist:
        d10_w = sum(1 for d in decis if d == 10) / n_decil
        d10_b = float(expected_decil_dist.get('D10', expected_decil_dist.get('D10', 0)) or 0)
        d10_pct_window = round(d10_w * 100, 1)
        d10_pct_base   = round(d10_b * 100, 1)
        fired_b = abs(d10_w - d10_b) >= 0.05

    if not (fired_a or fired_b):
        return RuleResult('score_drift', fired=False)

    parts = []
    if fired_a:
        parts.append(
            f"score médio={window_mean:.4f} (baseline {base_mean:.4f}, "
            f"σ={base_sd:.4f}, z={z:+.2f})"
        )
    if fired_b:
        parts.append(f"D10={d10_pct_window}% (esperado {d10_pct_base}%)")
    msg = "Drift de score em 60min: " + " · ".join(parts) + ". Possível mudança de público ou bug."
    return RuleResult(
        'score_drift', fired=True, message=msg,
        details={
            'n_score': n_score, 'n_decil': n_decil,
            'window_mean': round(window_mean, 4), 'base_mean': round(base_mean, 4),
            'base_sd': round(base_sd, 4), 'z': round(z, 2),
            'd10_pct_window': d10_pct_window, 'd10_pct_base': d10_pct_base,
            'fired_a_mean': fired_a, 'fired_b_decil': fired_b,
            'baseline_source': baseline_source,
        },
    )


# ──────────────────────────────────────────────────────────────────────────
# Polling status tracker (para regra 9)
# ──────────────────────────────────────────────────────────────────────────

def record_polling_status(store: GcsStateStore, status: str, history_len: int = 10) -> None:
    """Append-status no histórico do polling. Chamado por api/app.py.

    Constrói um RuleState NOVO (não muta o retornado por get) — senão
    GcsStateStore.set compara o objeto com ele mesmo, `old != state` dá False
    e o flush nunca acontece (regra 9 ficaria cega). Bug corrigido 15/05/2026.
    """
    assert status in ('ok', 'error'), f"status inválido: {status}"
    cur = store.get('_polling_status_tracker')
    history = (cur.last_message or '').split(',')
    history = [s for s in history if s in ('ok', 'error')]
    history.append(status)
    history = history[-history_len:]
    new_state = RuleState(
        last_fired_at=cur.last_fired_at,
        last_resolved_at=cur.last_resolved_at,
        consecutive_fires=cur.consecutive_fires,
        last_message=','.join(history),
        last_sent_at=cur.last_sent_at,
    )
    store.set('_polling_status_tracker', new_state)


# ──────────────────────────────────────────────────────────────────────────
# Alerta dedicado (push) — feature quebrada no encoding bloqueou o batch
# ──────────────────────────────────────────────────────────────────────────

def alert_feature_encoding_blocked(
    feature_names: list[str],
    n_leads: int,
    model_run_id: str = '',
    store: Optional[GcsStateStore] = None,
    dry_run: Optional[bool] = None,
) -> str:
    """Alerta fail-loud: o validador pós-encoding bloqueou um batch em produção.

    Diferente das regras de `run_critical_checks` (que pollam o banco/estado),
    este é um alerta de evento — chamado direto pelo handler do polling Railway
    no instante em que o validador estoura, porque os leads NÃO foram scoreados
    e NÃO foram enviados ao Meta. Sem este aviso o estrago é silencioso: antes
    desta correção a exceção derrubava o ciclo inteiro e o hook de alertas nem
    rodava (vide registro_erros_ml.md § V.5 e PLANO_SAFEGUARD "Validador
    pós-encoding").

    Self-contained: cria/usa um `GcsStateStore`, dispara via `SlackDispatcher`
    (respeita cooldown como qualquer regra) e dá flush. Retorna o status do
    dispatcher ('sent' | 'dry_run' | 'cooldown' | 'error' | ...).
    """
    if dry_run is None:
        dry_run = os.environ.get('CRITICAL_ALERTS_DRY_RUN', 'true').lower() == 'true'
    own_store = store is None
    if store is None:
        store = GcsStateStore()

    feats = ', '.join(feature_names[:5]) if feature_names else '(não especificada)'
    if feature_names and len(feature_names) > 5:
        feats += f" (+{len(feature_names) - 5})"
    rid = f" · modelo {model_run_id[:8]}" if model_run_id else ''
    message = (
        f"Feature(s) quebrada(s) no encoding: *{feats}*{rid}.\n"
        f"*{n_leads} lead(s) NÃO foram scoreados nem enviados ao Meta* neste ciclo.\n"
        f"Os leads ficaram segurados (capiStatus=blocked_feature) pra não entrar "
        f"em loop de re-tentativa a cada 5min. Investigar a feature pré-OHE "
        f"(parsing/casing/categoria sumindo) antes de liberar."
    )
    result = RuleResult(
        rule_name='feature_encoding_blocked',
        fired=True,
        severity='HIGH',
        message=message,
        details={'features': feature_names, 'n_leads': n_leads,
                 'model_run_id': model_run_id},
    )
    dispatcher = SlackDispatcher(store, dry_run=dry_run)
    status = dispatcher.maybe_send(result)
    if own_store:
        store.flush()
    logger.info(
        f"[critical_alerts] feature_encoding_blocked: dispatch={status} "
        f"n_leads={n_leads} feats={feats}"
    )
    return status


# ──────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────

def run_critical_checks(
    railway_conn,
    expected_decil_dist: Optional[dict] = None,
    dry_run: Optional[bool] = None,
) -> dict:
    """
    Avalia as 9 regras + dispara DM se necessário. Retorna sumário.

    Args:
        railway_conn: conexão pg8000.native já aberta para a tabela Lead.
        expected_decil_dist: baseline rolling 30d para a regra de drift (opcional).
        dry_run: força modo. Default lê CRITICAL_ALERTS_DRY_RUN=true (seguro).
    """
    if dry_run is None:
        dry_run = os.environ.get('CRITICAL_ALERTS_DRY_RUN', 'true').lower() == 'true'

    store = GcsStateStore()
    dispatcher = SlackDispatcher(store, dry_run=dry_run)

    # Ponto único de composição dos repositórios de leads — quem entra em
    # produção (esta função) decide as fontes; cada regra migrada recebe o
    # repositório por injeção.
    #
    # Fonte do LEDGER (registros_ml) via `open_ledger_read_connection()`:
    # Railway ou Cloud SQL conforme LEDGER_READ_SOURCE (PLANO_LEDGER_CLOUDSQL.md
    # Etapa 3). registros_ml é idêntico nos dois bancos. `railway_conn` segue
    # servindo o que SÓ existe no Railway: baseline `Lead` (legacy) e a
    # `lead_surveys` da regra rule_no_leads_arriving.
    from src.data import compose_repository
    from src.data.ledger_connection import open_ledger_read_connection

    ledger_conn = open_ledger_read_connection()
    summary = {'evaluated': 0, 'fired': 0, 'sent': 0, 'cooldown': 0,
               'dry_run': 0, 'error': 0, 'skipped': 0, 'no_change': 0,
               'state_unavailable': 0,
               'mode': 'dry_run' if dry_run else 'live'}
    fired_details: list[dict] = []
    try:
        repo = compose_repository('registros_ml', railway_conn=ledger_conn)
        # baseline_repo (legacy/Lead) APOSENTADO — a Etapa 5 anulou Lead.leadScore/decil
        # e o ledger já passou de 30d (>22/06). O drift usa `repo` (registros_ml,
        # Cloud SQL) como baseline também. Monitoramento agora 100% Cloud SQL,
        # sem nenhuma leitura no Railway (lead_surveys/Lead).
        rules: list[Callable[[], RuleResult]] = [
            lambda: rule_no_leads_arriving(repo),
            lambda: rule_capi_success_low(repo),
            lambda: rule_variant_no_capi(repo),
            lambda: rule_utm_source_missing(repo),
            lambda: rule_polling_500(store),
            lambda: rule_score_drift(repo, repo, expected_decil_dist),
            lambda: rule_pubsub_consumer_stalled(ledger_conn),
            lambda: rule_pubsub_error_rate_high(ledger_conn),
            lambda: rule_pubsub_skipped_missing_data_high(ledger_conn),
        ]

        for r in rules:
            try:
                result = r()
            except Exception as e:
                logger.error(f"[critical_alerts] regra falhou ao avaliar: {e}", exc_info=True)
                summary['error'] += 1
                continue
            summary['evaluated'] += 1
            status = dispatcher.maybe_send(result)
            summary[status] = summary.get(status, 0) + 1
            if result.fired:
                summary['fired'] += 1
                fired_details.append({
                    'rule': result.rule_name, 'severity': result.severity,
                    'message': result.message, 'details': result.details,
                    'dispatch_status': status,
                })
    finally:
        # ledger_conn é sempre uma conexão própria (mesmo quando aponta pro
        # Railway) — fechar pra não vazar conexão a cada ciclo de 5min.
        try:
            ledger_conn.close()
        except Exception:
            pass

    store.flush()
    summary['fired_rules'] = fired_details
    return summary
