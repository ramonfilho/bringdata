"""
Resolução canônica do "lançamento atual" BRT.

Substitui as heurísticas dispersas em api/app.py (última segunda BRT) e em
src/monitoring/data_quality.py (`_resolve_*_launch_brt`). Regra única:

  1. LF do `configs/launches.yaml` cuja janela `cap_start ≤ hoje_BRT ≤ cap_end`.
  2. Fallback explícito: heurística "desde a última segunda BRT até agora", com
     `source='monday_heuristic'`, sem nome de LF e com warning no log.
  3. NUNCA cai no último LF encerrado — esse fallback escondia o gap quando o
     YAML está desatualizado (vide bug detectado em 13/05/2026: LF54 aparecia
     como "atual" porque LF55 não estava cadastrado).

API:
  - `load_launches(path=None) -> dict`
  - `resolve_active_launch_brt(today=None) -> Optional[ActiveLaunch]`
  - `resolve_launch_window_brt(today=None) -> LaunchWindow`
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

BRT = timezone(timedelta(hours=-3))

# Paths candidatos pra launches.yaml — primeiro existente vence.
_CANDIDATE_PATHS = [
    Path(__file__).resolve().parents[2] / 'configs' / 'launches.yaml',
    Path('/app/V2/configs/launches.yaml'),
    Path('/app/configs/launches.yaml'),
    Path.cwd() / 'configs' / 'launches.yaml',
]


@dataclass(frozen=True)
class ActiveLaunch:
    """LF ativo no YAML (`cap_start ≤ hoje ≤ cap_end`)."""
    name: str          # ex: 'LF55'
    cap_start: date
    cap_end: date


@dataclass(frozen=True)
class LaunchWindow:
    """Janela canônica do lançamento atual pra qualquer relatório."""
    cap_start: date
    cap_end: Optional[date]            # None quando source=monday_heuristic
    source: str                        # 'launches_yaml' | 'monday_heuristic'
    lf_name: Optional[str] = None      # nome confirmado do YAML, ou inferido (LFnn+1) no fallback
    inferred: bool = False             # True quando lf_name foi inferido pelo fallback
    label: str = ''                    # texto pronto pra exibição

    @property
    def cap_start_utc(self) -> datetime:
        """cap_start 00:00 BRT → UTC."""
        return datetime(self.cap_start.year, self.cap_start.month, self.cap_start.day,
                        0, 0, 0, tzinfo=BRT).astimezone(timezone.utc)


def load_launches(path: Optional[Path] = None) -> dict:
    """Lê launches.yaml. Retorna `{}` se arquivo ausente ou inválido."""
    import yaml
    candidates = [path] if path else _CANDIDATE_PATHS
    for p in candidates:
        if p and p.exists():
            try:
                with open(p) as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning(f"[launches.yaml] erro lendo {p}: {e}")
                return {}
    logger.warning(f"[launches.yaml] arquivo não encontrado em {[str(p) for p in candidates]}")
    return {}


def _today_brt() -> date:
    return datetime.now(BRT).date()


def resolve_active_launch_brt(today: Optional[date] = None,
                              launches: Optional[dict] = None) -> Optional[ActiveLaunch]:
    """
    Retorna o LF cujo `cap_start ≤ today_brt ≤ cap_end`, ou None se nenhum bate.

    Sem fallback ao último encerrado por design — quem precisa de fallback usa
    `resolve_launch_window_brt`.
    """
    today = today or _today_brt()
    launches = launches if launches is not None else load_launches()
    for name, cfg in launches.items():
        cs_str = cfg.get('cap_start')
        ce_str = cfg.get('cap_end')
        if not (cs_str and ce_str):
            continue
        try:
            cs = datetime.strptime(cs_str, '%Y-%m-%d').date()
            ce = datetime.strptime(ce_str, '%Y-%m-%d').date()
        except ValueError:
            continue
        if cs <= today <= ce:
            return ActiveLaunch(name=name, cap_start=cs, cap_end=ce)
    return None


def _last_monday(today: date) -> date:
    """Última segunda-feira BRT (inclusivo). Python weekday: segunda=0."""
    days_since_monday = today.weekday()
    return today - timedelta(days=days_since_monday)


def _infer_next_lf_name(launches: dict) -> Optional[str]:
    """
    Olha as chaves do launches.yaml, pega o maior LFnn cadastrado e retorna
    LF(nn+1). Ignora DEVxx e outros nomes não-padrão. Retorna None se não
    achar nenhum LFnn.
    """
    max_n = 0
    pat = re.compile(r'^LF(\d+)$')
    for name in launches.keys():
        m = pat.match(name)
        if m:
            n = int(m.group(1))
            if n > max_n:
                max_n = n
    return f'LF{max_n + 1}' if max_n > 0 else None


def resolve_launch_window_brt(today: Optional[date] = None,
                              launches: Optional[dict] = None) -> LaunchWindow:
    """
    Janela canônica do lançamento atual:
      1) Se há LF ativo no YAML (`cap_start ≤ today ≤ cap_end`) → usa.
      2) Senão → "desde a última segunda BRT até hoje", com warning.

    Garante que `cap_start` sempre existe (sempre tem janela). Quando vier do
    fallback de segunda, `lf_name=None` e `cap_end=None`.
    """
    today = today or _today_brt()
    launches = launches if launches is not None else load_launches()

    active = resolve_active_launch_brt(today=today, launches=launches)
    if active is not None:
        is_open = today <= active.cap_end
        phase = ' (em captação)' if is_open else ' (captação encerrada)'
        return LaunchWindow(
            cap_start=active.cap_start,
            cap_end=active.cap_end,
            source='launches_yaml',
            lf_name=active.name,
            inferred=False,
            label=f"{active.name} {active.cap_start}→{active.cap_end}{phase}",
        )

    # Fallback explícito. Tenta inferir o nome (LF + maior nn cadastrado + 1)
    # pra dar nome ao lançamento em logs/exports, mas marca inferred=True
    # pra que o digest/Slack consiga sinalizar visualmente.
    cs = _last_monday(today)
    inferred_name = _infer_next_lf_name(launches)
    logger.warning(
        f"[launches] sem LF ativo em {today.isoformat()} no launches.yaml — "
        f"usando fallback 'última segunda BRT' ({cs.isoformat()})"
        + (f"; nome inferido: {inferred_name}" if inferred_name else '')
        + ". Cadastre o LF atual em configs/launches.yaml para rotular corretamente."
    )
    if inferred_name:
        label = (
            f"{inferred_name} (inferido) · captação iniciada {cs.strftime('%d/%m/%Y')} "
            f"· confirmar em launches.yaml"
        )
    else:
        label = (
            f"Captação iniciada em {cs.strftime('%d/%m/%Y')} "
            f"(LF ainda não cadastrado em launches.yaml)"
        )
    return LaunchWindow(
        cap_start=cs,
        cap_end=None,
        source='monday_heuristic',
        lf_name=inferred_name,
        inferred=bool(inferred_name),
        label=label,
    )
