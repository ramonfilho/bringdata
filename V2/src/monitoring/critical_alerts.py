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
  1. variant_no_capi      — leads scored ≥ N mas 0 CAPI enviado em 60min
  4. no_leads_arriving    — 0 leads inseridos em Lead em 60min
  5. capi_success_low     — capi_success_rate < 95% em 60min (N≥10 enviados)
  6. fbp_fbc_low          — fbp<95% ou fbc<80% em 60min (N≥50)
  9. polling_500          — /railway/process-pending falhou em ≥2 pollings seguidos
  +  score_drift          — score médio 1σ off (A) OU KS p<0.01 / ΔD10≥5pp (B)
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


def rule_no_leads_arriving(conn) -> RuleResult:
    """Regra 4: 0 respostas de pesquisa novas nos últimos 60min.

    Fonte: `lead_surveys.submittedAt` (verdade nova do inflow desde 12/05/2026 —
    o front migrou a gravação do formulário pra essa tabela; `Lead` deixou de
    receber a maioria dos leads). 24/7 sem quiet hours: surveys entram de
    madrugada também (decisão B revertida em 17/05 — o ruído noturno era
    artefato de consultar `Lead`, que estava faminto, não falta de tráfego).

    `submittedAt` é `timestamp without time zone` em UTC → cutoff UTC naive.
    """
    cutoff = _window_start_utc_naive()
    rows = conn.run(
        'SELECT COUNT(*) AS n, MAX("submittedAt") AS last_at FROM lead_surveys '
        'WHERE "submittedAt" >= :cutoff',
        cutoff=cutoff,
    )
    n, last_at = rows[0]
    n = n or 0
    if n > 0:
        return RuleResult('no_leads_arriving', fired=False)
    last_rows = conn.run('SELECT MAX("submittedAt") FROM lead_surveys')
    last_global = last_rows[0][0] if last_rows else None
    msg = (
        f"Zero respostas de pesquisa em {WINDOW_MIN}min (lead_surveys). "
        f"Último insert: {last_global.isoformat() if last_global else 'desconhecido'}. "
        f"LP/Prisma pode estar travado."
    )
    return RuleResult('no_leads_arriving', fired=True, message=msg,
                      details={'last_lead_at': last_global.isoformat() if last_global else None})


def rule_capi_success_low(conn) -> RuleResult:
    """Regra 5: ≥10 enviados em 60min mas success rate < 95%."""
    cutoff = _window_start_utc()
    rows = conn.run(
        'SELECT '
        '  COUNT(*) FILTER (WHERE "capiSentAt" IS NOT NULL AND "capiStatus" NOT IN (\'blocked\',\'skipped\')) AS sent, '
        '  COUNT(*) FILTER (WHERE "capiStatus" = \'success\') AS ok, '
        '  COUNT(*) FILTER (WHERE "capiStatus" = \'error\') AS err '
        'FROM "Lead" WHERE "createdAt" >= :cutoff',
        cutoff=cutoff,
    )
    sent, ok, err = (rows[0][0] or 0, rows[0][1] or 0, rows[0][2] or 0)
    if sent < 10:
        return RuleResult('capi_success_low', fired=False,
                          skipped_reason=f'amostra insuficiente (sent={sent})')
    rate = (ok / sent) * 100 if sent else 0
    if rate >= 95:
        return RuleResult('capi_success_low', fired=False)
    msg = (
        f"capi_success_rate = {rate:.1f}% em {WINDOW_MIN}min (limite 95%). "
        f"sent={sent}, ok={ok}, err={err}."
    )
    return RuleResult('capi_success_low', fired=True, message=msg,
                      details={'sent': sent, 'ok': ok, 'err': err, 'rate_pct': round(rate, 1)})


def rule_variant_no_capi(conn) -> RuleResult:
    """Regra 1 (versão MVP global): ≥10 leads scored em 60min mas 0 CAPI enviado.

    Versão por-variant (Champion vs Challenger) pendente — não há coluna `variant`
    em Lead pra atribuição direta. MVP usa total agregado, que pega o caso
    "pipeline CAPI completamente parado".
    """
    cutoff = _window_start_utc()
    rows = conn.run(
        'SELECT '
        '  COUNT(*) FILTER (WHERE "leadScore" IS NOT NULL) AS scored, '
        '  COUNT(*) FILTER (WHERE "capiSentAt" IS NOT NULL AND "capiStatus" NOT IN (\'blocked\',\'skipped\')) AS sent '
        'FROM "Lead" WHERE "createdAt" >= :cutoff',
        cutoff=cutoff,
    )
    scored, sent = (rows[0][0] or 0, rows[0][1] or 0)
    if scored < 10:
        return RuleResult('variant_no_capi', fired=False,
                          skipped_reason=f'amostra insuficiente (scored={scored})')
    if sent > 0:
        return RuleResult('variant_no_capi', fired=False)
    msg = (
        f"{scored} leads scoreados em {WINDOW_MIN}min, mas 0 eventos CAPI enviados. "
        f"Possível quebra no envio."
    )
    return RuleResult('variant_no_capi', fired=True, message=msg,
                      details={'scored': scored, 'sent': sent})


def rule_fbp_fbc_low(conn) -> RuleResult:
    """Regra 6: fbp<95% OU fbc<80% em 60min (N≥50). JOIN Lead × leads_capi por email."""
    cutoff = _window_start_utc()
    rows = conn.run(
        'SELECT '
        '  COUNT(DISTINCT l.email) AS n, '
        '  COUNT(DISTINCT CASE WHEN lc.fbp IS NOT NULL AND lc.fbp <> \'\' THEN l.email END) AS with_fbp, '
        '  COUNT(DISTINCT CASE WHEN lc.fbc IS NOT NULL AND lc.fbc <> \'\' THEN l.email END) AS with_fbc '
        'FROM "Lead" l LEFT JOIN leads_capi lc ON LOWER(l.email) = LOWER(lc.email) '
        'WHERE l."createdAt" >= :cutoff',
        cutoff=cutoff,
    )
    n, with_fbp, with_fbc = (rows[0][0] or 0, rows[0][1] or 0, rows[0][2] or 0)
    if n < 50:
        return RuleResult('fbp_fbc_low', fired=False,
                          skipped_reason=f'amostra insuficiente (n={n})')
    fbp_pct = (with_fbp / n) * 100
    fbc_pct = (with_fbc / n) * 100
    if fbp_pct >= 95 and fbc_pct >= 80:
        return RuleResult('fbp_fbc_low', fired=False)
    severity = 'HIGH'
    msg = (
        f"FBP={fbp_pct:.1f}%  FBC={fbc_pct:.1f}%  em {WINDOW_MIN}min (limite HIGH 95/80). "
        f"N={n}."
    )
    return RuleResult('fbp_fbc_low', fired=True, severity=severity, message=msg,
                      details={'n': n, 'fbp_pct': round(fbp_pct, 1), 'fbc_pct': round(fbc_pct, 1)})


def rule_utm_source_missing(conn) -> RuleResult:
    """Regra +: % de leads chegando SEM `source` no Lead em 60min acima do
    limiar (N≥50). Pega regressão de captura/tracking — leads de campanha
    perdendo a origem (não vão pro Meta e o modelo scoreia cego de origem).
    O pico de 21-22/04/2026 (até 20%) passou sem nenhum alarme; orgânico
    legítimo é ~1,5% e a base normal <1%, então o limiar HIGH de 5% separa
    regressão de orgânico normal sem spammar entre lançamentos. Contexto:
    registro_erros_ml.md Erro 18 (tracking perdendo source) e § V.6."""
    cutoff = _window_start_utc()
    rows = conn.run(
        'SELECT COUNT(*) AS n, '
        "COUNT(*) FILTER (WHERE source IS NULL OR TRIM(source) = '') AS sem_source "
        'FROM "Lead" WHERE "createdAt" >= :cutoff AND pesquisa IS NOT NULL',
        cutoff=cutoff,
    )
    n, sem = (rows[0][0] or 0, rows[0][1] or 0)
    if n < 50:
        return RuleResult('utm_source_missing', fired=False,
                          skipped_reason=f'amostra insuficiente (n={n})')
    pct = (sem / n) * 100
    if pct < 5.0:
        return RuleResult('utm_source_missing', fired=False)
    msg = (
        f"{pct:.1f}% dos leads chegaram SEM `source` em {WINDOW_MIN}min "
        f"(limite HIGH 5%, N={n}, {int(sem)} sem source). Possível regressão "
        f"de captura/tracking: leads de campanha perdendo a origem — não vão "
        f"pro Meta (allowlist barra) e o modelo scoreia cego de origem. "
        f"Investigar front-end / webhook de captura."
    )
    return RuleResult('utm_source_missing', fired=True, severity='HIGH', message=msg,
                      details={'n': n, 'sem_source': int(sem), 'pct': round(pct, 1)})


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


def rule_score_drift(conn, expected_decil_dist: Optional[dict]) -> RuleResult:
    """
    Regra +: drift de score em 60min vs baseline rolling 30d (expected_decil_dist).
    Dispara se (A) score médio > 1σ off OU (B) KS p<0.01 ou ΔD10 ≥ 5pp.
    """
    import statistics
    cutoff = _window_start_utc()
    rows = conn.run(
        'SELECT "leadScore"::float, decil::int FROM "Lead" '
        'WHERE "createdAt" >= :cutoff AND "leadScore" IS NOT NULL',
        cutoff=cutoff,
    )
    scores = [r[0] for r in rows if r[0] is not None]
    decis  = [r[1] for r in rows if r[1] is not None]
    n_score = len(scores)
    n_decil = len(decis)

    if n_score < 50:
        return RuleResult('score_drift', fired=False,
                          skipped_reason=f'amostra de scores insuficiente (n={n_score})')

    # Baseline rolling 30d: queremos média e σ de leadScore.
    base_rows = conn.run(
        'SELECT AVG("leadScore"::float), STDDEV_POP("leadScore"::float), COUNT(*) '
        'FROM "Lead" '
        'WHERE "createdAt" >= NOW() - INTERVAL \'31 days\' '
        '  AND "createdAt" <  NOW() - INTERVAL \'1 day\' '
        '  AND "leadScore" IS NOT NULL'
    )
    base_mean, base_sd, base_n = base_rows[0]
    if not base_mean or not base_sd or (base_n or 0) < 1000:
        return RuleResult('score_drift', fired=False,
                          skipped_reason='baseline rolling 30d insuficiente')
    base_mean = float(base_mean); base_sd = float(base_sd)

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
    Avalia as 6 regras + dispara DM se necessário. Retorna sumário.

    Args:
        railway_conn: conexão pg8000.native já aberta para a tabela Lead.
        expected_decil_dist: baseline rolling 30d para a regra de drift (opcional).
        dry_run: força modo. Default lê CRITICAL_ALERTS_DRY_RUN=true (seguro).
    """
    if dry_run is None:
        dry_run = os.environ.get('CRITICAL_ALERTS_DRY_RUN', 'true').lower() == 'true'

    store = GcsStateStore()
    dispatcher = SlackDispatcher(store, dry_run=dry_run)

    rules: list[Callable[[], RuleResult]] = [
        lambda: rule_no_leads_arriving(railway_conn),
        lambda: rule_capi_success_low(railway_conn),
        lambda: rule_variant_no_capi(railway_conn),
        lambda: rule_fbp_fbc_low(railway_conn),
        lambda: rule_utm_source_missing(railway_conn),
        lambda: rule_polling_500(store),
        lambda: rule_score_drift(railway_conn, expected_decil_dist),
    ]

    summary = {'evaluated': 0, 'fired': 0, 'sent': 0, 'cooldown': 0,
               'dry_run': 0, 'error': 0, 'skipped': 0, 'no_change': 0,
               'state_unavailable': 0,
               'mode': 'dry_run' if dry_run else 'live'}
    fired_details: list[dict] = []

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

    store.flush()
    summary['fired_rules'] = fired_details
    return summary
