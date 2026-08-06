"""
Checkup de produção: as operações do dia a dia ainda estão de pé?

Responde, com número medido, a pergunta que a gente faz depois de mexer em
qualquer coisa: **o lead ainda chega, é scoreado, é enviado ao Meta e é guardado?
E os relatórios e a ingestão ainda rodam?**

A armadilha que este script existe para evitar
----------------------------------------------
Quando a captação está pausada, o volume despenca e **quase toda métrica absoluta
fica parecida com pane**. Em 06/08/2026 o envio ao Meta caiu de ~2.100 leads/dia
para 3, e o primeiro olhar sugeriu que algo tinha quebrado no deploy da véspera.
Não tinha: dos leads que chegaram nas 48h anteriores, **todos os 9 de
`facebook-ads` foram enviados**, e os outros (manychat, google-ads, orgânico) não
são enviados por regra, porque o CAPI do Meta só recebe lead de origem Meta.

Daí a regra deste checkup: **medir TAXA sobre o universo elegível, nunca contagem
absoluta.** "3 envios hoje" não diz nada; "100% dos leads elegíveis enviados" diz
tudo. Onde a taxa não faz sentido (fila, cron), o sinal é frescor, não volume.

Uso:
    python -m scripts.checkup_producao              # tudo
    python -m scripts.checkup_producao --breve      # só o veredito de cada bloco
    python -m scripts.checkup_producao --horas 48   # muda a janela de análise

Saída: 0 se tudo passou, 1 se algum bloco falhou. Serve em cron.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_V2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_V2))

PROJETO = "smart-ads-451319"
REGIAO = "us-central1"
SERVICO = "smart-ads-api"

# Origens cujo lead É elegível ao CAPI do Meta. O resto não é falha, é regra: o
# Meta só recebe lead que veio do Meta.
FONTES_META = ("facebook-ads", "facebook-ads-sitelink", "facebook", "fb", "ig",
               "instagram", "meta")

# Cron que roda semanalmente não pode ser cobrado com a régua do diário.
PERIODO_ESPERADO_H = {
    "railway-polling": 1,
    "pubsub-process-pending": 1,
    "hotleads-submit": 26,
    "slack-digest-daily": 26,
    "slack-digest-daily-dm": 26,
    "utm-quality-daily-trafego": 26,
    "utm-quality-daily-trafego-tarde": 26,
    "cpl-refresh-daily": 26,
    "deploy-gate-sync-monitoring-daily": 26,
    "ingestion-sales-daily-cron": 26,
    "ingestion-cadastros-daily-cron": 26,
    "ingestion-leads-incremental-cron": 26,
    "ingestion-ad-spend-cron": 26,
    "ingestion-launch-calendar-cron": 26,
    "meta-audiences-daily-cron": 26,
    "model-performance-weekly": 24 * 8,
    "refresh-rolling-reference-weekly": 24 * 8,
}

OK, ALERTA, FALHA = "OK", "ATENÇÃO", "FALHA"
_placar: list[tuple[str, str, str]] = []


def _reg(bloco: str, veredito: str, detalhe: str) -> None:
    _placar.append((bloco, veredito, detalhe))
    marca = {OK: "  ok  ", ALERTA: " aten ", FALHA: " FALHA"}[veredito]
    print(f"[{marca}] {bloco}: {detalhe}")


def _gcloud(args: list[str], timeout: int = 120) -> str:
    try:
        r = subprocess.run(["gcloud", *args, f"--project={PROJETO}"],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _conn(timeout: int = 300):
    import ssl

    import pg8000.native
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return pg8000.native.Connection(
        host=os.environ["LEDGER_DB_HOST"], port=int(os.environ.get("LEDGER_DB_PORT", "5432")),
        database="ledger", user=os.environ.get("LEDGER_DB_USER", "ledger_app"),
        password=os.environ["LEDGER_DB_PASSWORD"], ssl_context=ctx, timeout=timeout)


# ── 1. o lead chega, é scoreado, é enviado e é guardado ──────────────────────

def fluxo_do_lead(horas: int, breve: bool) -> None:
    c = _conn()
    try:
        fontes = ",".join(f"'{f}'" for f in FONTES_META)
        r = c.run(f"""
            SELECT count(*) recebidos,
                   count(lead_score) scoreados,
                   count(*) FILTER (WHERE lower(coalesce(utm_source,'')) IN ({fontes})) elegiveis,
                   count(*) FILTER (WHERE lower(coalesce(utm_source,'')) IN ({fontes})
                                      AND capi_sent_at IS NOT NULL) enviados,
                   max(created_at) ult_lead
              FROM public.registros_ml
             WHERE created_at >= now() - interval '{int(horas)} hours'""")[0]
        recebidos, scoreados, elegiveis, enviados, ult = r

        if not recebidos:
            _reg("chegada de lead", ALERTA,
                 f"NENHUM lead em {horas}h. Normal com captação pausada; pane se houver "
                 f"campanha no ar. Último lead: {ult or 'nunca'}")
        else:
            idade = (datetime.now(timezone.utc) - ult.replace(tzinfo=timezone.utc)
                     ).total_seconds() / 3600 if ult else 999
            _reg("chegada de lead", OK if idade < horas else ALERTA,
                 f"{recebidos} leads em {horas}h, último há {idade:.1f}h")

        # Scoring: taxa tem que ser 100%. Lead sem score é buraco, sempre.
        if recebidos:
            pct = 100.0 * scoreados / recebidos
            _reg("scoring", OK if scoreados == recebidos else FALHA,
                 f"{scoreados}/{recebidos} leads scoreados ({pct:.1f}%)"
                 + ("" if scoreados == recebidos else "  <- lead sem score é buraco no fluxo"))

        # Envio ao Meta: SÓ sobre o universo elegível. Contar o total esconde a
        # verdade nos dois sentidos.
        if elegiveis:
            pct = 100.0 * enviados / elegiveis
            v = OK if pct >= 95 else (ALERTA if pct >= 80 else FALHA)
            _reg("envio ao Meta", v,
                 f"{enviados}/{elegiveis} leads ELEGÍVEIS enviados ({pct:.1f}%). "
                 f"Os {recebidos - elegiveis} de outras origens não são enviados por regra")
        else:
            _reg("envio ao Meta", ALERTA,
                 f"nenhum lead de origem Meta em {horas}h, então não dá para medir a taxa. "
                 f"({recebidos} leads de outras origens)")

        if not breve and recebidos:
            print("        por origem:")
            for s, n, e in c.run(f"""
                SELECT coalesce(utm_source,'(nulo)'), count(*), count(capi_sent_at)
                  FROM public.registros_ml
                 WHERE created_at >= now() - interval '{int(horas)} hours'
                 GROUP BY 1 ORDER BY 2 DESC LIMIT 8"""):
                eleg = str(s).lower() in FONTES_META
                print(f"          {str(s)[:24]:<24} {n:>4} recebidos, {e:>4} enviados"
                      f"{'' if eleg else '   (não elegível ao CAPI)'}")
    finally:
        c.close()


# ── 2. a fila não está represada ─────────────────────────────────────────────

def fila(breve: bool) -> None:
    saida = _gcloud(["pubsub", "subscriptions", "list", "--format=value(name)"])
    subs = [l.strip().split("/")[-1] for l in saida.splitlines() if l.strip()]
    if not subs:
        _reg("fila Pub/Sub", ALERTA, "não consegui listar as subscriptions")
        return
    # A profundidade da fila vem do Monitoring, não do describe. Sem ela, o sinal
    # de reserva é o próprio ledger: se o lead está entrando, a fila está drenando.
    for s in subs:
        if "dlq" not in s:
            continue
        _reg("fila Pub/Sub (DLQ)", OK,
             f"{s} existe; mensagem morta aqui significa lead que falhou N vezes")
    if not breve:
        print(f"        subscriptions: {', '.join(subs)}")


# ── 3. os crons e jobs rodaram ───────────────────────────────────────────────

def crons() -> None:
    saida = _gcloud(["scheduler", "jobs", "list", f"--location={REGIAO}",
                     "--format=value(name,state,lastAttemptTime)"])
    if not saida.strip():
        _reg("crons", ALERTA, "não consegui listar")
        return
    agora = datetime.now(timezone.utc)
    atrasados, pausados, ok = [], [], 0
    for linha in saida.splitlines():
        p = linha.split("\t")
        nome = p[0].split("/")[-1]
        estado = p[1] if len(p) > 1 else ""
        ult = p[2] if len(p) > 2 else ""
        if estado != "ENABLED":
            pausados.append(nome)
            continue
        limite = PERIODO_ESPERADO_H.get(nome, 26)
        if not ult:
            atrasados.append(f"{nome} (nunca rodou)")
            continue
        try:
            t = datetime.fromisoformat(ult.replace("Z", "+00:00"))
        except ValueError:
            continue
        h = (agora - t).total_seconds() / 3600
        if h > limite:
            atrasados.append(f"{nome} ({h:.0f}h, esperado <{limite}h)")
        else:
            ok += 1
    _reg("crons", FALHA if atrasados else OK,
         f"{ok} em dia" + (f"; ATRASADOS: {', '.join(atrasados)}" if atrasados else "")
         + (f"; pausados de propósito: {', '.join(pausados)}" if pausados else ""))


def jobs(breve: bool) -> None:
    saida = _gcloud(["run", "jobs", "list", f"--region={REGIAO}",
                     "--format=value(metadata.name)"])
    nomes = [l.strip() for l in saida.splitlines() if l.strip()]
    falhos, ok = [], 0
    for j in nomes:
        s = _gcloud(["run", "jobs", "executions", "list", f"--job={j}",
                     f"--region={REGIAO}", "--limit=1",
                     "--format=value(status.succeededCount,status.failedCount)"])
        if not s.strip():
            continue
        partes = s.split("\t")
        sucesso = (partes[0] or "").strip()
        falhou = (partes[1] or "").strip() if len(partes) > 1 else ""
        if falhou and falhou != "0":
            falhos.append(j)
        elif sucesso and sucesso != "0":
            ok += 1
    _reg("jobs Cloud Run", FALHA if falhos else OK,
         f"{ok}/{len(nomes)} com última execução bem-sucedida"
         + (f"; FALHARAM: {', '.join(falhos)}" if falhos else ""))


# ── 4. o serviço continua fechado ────────────────────────────────────────────

def servico_fechado() -> None:
    """Regressão de segurança: o serviço tem que recusar chamada anônima.

    Está aqui porque já aconteceu de reabrir sozinho: em 06/08/2026 o binding foi
    removido à mão e o deploy seguinte reabriu tudo pela flag
    `--allow-unauthenticated`. Ninguém percebeu na hora.
    """
    url = _gcloud(["run", "services", "describe", SERVICO, f"--region={REGIAO}",
                   "--format=value(status.url)"]).strip()
    if not url:
        _reg("serviço fechado", ALERTA, "não consegui descobrir a URL")
        return
    import urllib.error
    import urllib.request
    try:
        # Opener limpo: sem o handler de identidade, para testar como um estranho.
        opener = urllib.request.build_opener()
        opener.open(f"{url}/health", timeout=30)
        _reg("serviço fechado", FALHA,
             "ANÔNIMO CONSEGUIU CHAMAR /health. O serviço reabriu.")
    except urllib.error.HTTPError as e:
        v = OK if e.code in (401, 403) else ALERTA
        _reg("serviço fechado", v, f"anônimo levou HTTP {e.code} (esperado 403)")
    except Exception as e:  # noqa: BLE001
        _reg("serviço fechado", ALERTA, f"não consegui testar: {str(e)[:60]}")


# ── 5. os relatórios ─────────────────────────────────────────────────────────

def relatorios(horas: int) -> None:
    """Relatório não enviado pode ser saúde, não pane: desde 04/08/2026 existe uma
    trava que segura o relatório quando não houve tráfego pago na janela. Então o
    que se verifica aqui é se o CRON rodou e devolveu 200, não se a mensagem saiu.
    """
    filtro = (f'resource.type=cloud_run_revision AND '
              f'resource.labels.service_name="{SERVICO}" AND '
              f'httpRequest.requestUrl:"slack-digest"')
    saida = _gcloud(["logging", "read", filtro, "--limit=5",
                     f"--freshness={int(horas)}h",
                     "--format=value(timestamp,httpRequest.status)"], timeout=180)
    linhas = [l for l in saida.splitlines() if l.strip()]
    if not linhas:
        _reg("relatórios", ALERTA,
             f"nenhuma chamada ao digest em {horas}h no smart-ads-api "
             f"(ele pode estar sendo servido pelo smart-ads-monitoring)")
        return
    ruins = [l for l in linhas if "\t200" not in l]
    _reg("relatórios", FALHA if ruins else OK,
         f"{len(linhas)} chamadas ao digest, {len(linhas) - len(ruins)} com 200"
         + ("; a trava de tráfego pode ter segurado o envio, e isso é esperado" if not ruins else ""))


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(_V2 / ".env")

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--horas", type=int, default=24, help="janela de análise (default 24)")
    ap.add_argument("--breve", action="store_true", help="só o veredito de cada bloco")
    a = ap.parse_args()

    print(f"Checkup de produção, janela de {a.horas}h\n")
    fluxo_do_lead(a.horas, a.breve)
    fila(a.breve)
    crons()
    jobs(a.breve)
    servico_fechado()
    relatorios(a.horas)

    falhas = [b for b, v, _ in _placar if v == FALHA]
    alertas = [b for b, v, _ in _placar if v == ALERTA]
    print(f"\n{len(_placar) - len(falhas) - len(alertas)} ok, {len(alertas)} em atenção, "
          f"{len(falhas)} falhando")
    if falhas:
        print(f"FALHANDO: {', '.join(falhas)}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
