"""
Deploy só entra em produção pelo gatekeeper.

Em 05-06/08/2026 o `deploy_capi.sh` foi chamado DIRETO seis vezes, com promoção de
tráfego na mão. Consequências, todas medidas depois: os seis deploys ficaram fora
do ledger durável, o LOCKSTEP nunca rodou, e o serviço de monitoramento ficou numa
imagem diferente da do scorer sem ninguém notar.

Nada impedia. O hook que existia só olhava `Edit`/`Write`, então comando de shell
passava livre, e o script de deploy não perguntava quem o chamou. As travas
existiam e foram contornadas simplesmente por ser mais rápido.

A correção é em duas camadas, porque uma só não cobre todos os chamadores:
  - no SCRIPT, que vale para qualquer um (pessoa, CI, outro script);
  - no HOOK, que pega o agente antes de executar e explica o caminho certo.

E a escotilha de emergência é explícita: sem saída, trava vira gambiarra pior.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[2]
_V2 = _RAIZ / "V2"
_HOOK = _RAIZ / ".claude" / "hooks" / "block-deploy-fora-do-gate.sh"


# ── camada 1: o script recusa quem não veio do gate ──────────────────────────

def test_deploy_capi_recusa_chamada_direta():
    r = subprocess.run(["bash", str(_V2 / "api" / "deploy_capi.sh"), "--yes"],
                       capture_output=True, text=True, timeout=120, cwd=str(_RAIZ))
    assert r.returncode != 0, "deploy_capi.sh aceitou chamada direta"
    assert "não deve ser chamado direto" in r.stdout


def test_deploy_capi_ensina_o_caminho_certo_e_a_escotilha():
    """Bloquear sem dizer o que fazer só transfere o problema para o próximo."""
    r = subprocess.run(["bash", str(_V2 / "api" / "deploy_capi.sh"), "--yes"],
                       capture_output=True, text=True, timeout=120, cwd=str(_RAIZ))
    assert "deploy-gate.sh deploy" in r.stdout, "não ensina o comando certo"
    assert "DEPLOY_SEM_GATE=1" in r.stdout, "não mostra a saída de emergência"


def test_o_gatekeeper_passa_o_sinal():
    """Se o gate parar de passar o sinal, ele bloqueia a si mesmo e o deploy morre."""
    gate = (_V2 / "api" / "deploy-gate.sh").read_text()
    assert "DEPLOY_VIA_GATE=1" in gate and "$DEPLOY_CAPI" in gate


def test_escotilha_de_emergencia_funciona():
    """Precisa existir e precisa FUNCIONAR: escotilha que não abre é decoração.

    O argumento é `--help` de propósito, e isto NÃO é detalhe cosmético. A trava
    roda antes do `main`, então o aviso da escotilha já saiu quando o parse de
    argumentos começa; `--help` cai no `usage` e sai, sem validar, buildar nem
    deployar. A primeira versão deste teste mandava `--yes`, que é o deploy de
    verdade: em 24/08/2026 uma rodada da suíte estourou o timeout de 180s, o
    Python desistiu de esperar, e o `docker buildx` + `gcloud run deploy` que ele
    tinha começado ficaram órfãos e TERMINARAM — duas revisões novas no Cloud Run
    saídas de um teste. Rodar a suíte não pode mexer em produção.
    """
    import os
    env = {**os.environ, "DEPLOY_SEM_GATE": "1"}
    r = subprocess.run(["bash", str(_V2 / "api" / "deploy_capi.sh"), "--help"],
                       capture_output=True, text=True, timeout=60, cwd=str(_RAIZ), env=env)
    assert "não deve ser chamado direto" not in r.stdout, "escotilha não abriu"
    assert "DEPLOY_SEM_GATE=1" in r.stdout, "escotilha abriu em silêncio; tem que gritar"
    # Trava da reincidência: se alguém trocar o argumento por um que deploya, a
    # etapa de build aparece na saída e o teste morre aqui, antes de subir imagem.
    assert "BUILD DA IMAGEM" not in r.stdout, (
        "o teste voltou a rodar o deploy de verdade; ele só pode PROVAR que a "
        "escotilha abre, nunca executar o deploy")


# ── camada 2: o hook pega antes de executar ──────────────────────────────────

def _hook(cmd: str) -> int:
    entrada = json.dumps({"tool_input": {"command": cmd}})
    return subprocess.run(["bash", str(_HOOK)], input=entrada, capture_output=True,
                          text=True, timeout=60).returncode


@pytest.mark.parametrize("cmd", [
    "bash V2/api/deploy_capi.sh --yes",
    "cd /x && bash V2/api/deploy_capi.sh",
    "gcloud run services update-traffic smart-ads-api --to-revisions=r=100",
])
def test_hook_bloqueia_o_caminho_errado(cmd):
    assert _hook(cmd) == 2, f"hook deixou passar: {cmd}"


@pytest.mark.parametrize("cmd", [
    "bash V2/api/deploy-gate.sh deploy",
    "bash V2/api/deploy-gate.sh promote --revision smart-ads-api-00001-abc",
    "DEPLOY_SEM_GATE=1 bash V2/api/deploy_capi.sh --yes",
    # Olhar nunca é bloqueado; só MUDAR o roteamento.
    "gcloud run services describe smart-ads-api --region us-central1",
    "gcloud run revisions list --service=smart-ads-api",
    # Os outros serviços não passam pelo gate do scorer.
    "gcloud run services update-traffic smart-ads-monitoring --to-revisions=r=100",
    "git status",
])
def test_hook_nao_atrapalha_o_resto(cmd):
    assert _hook(cmd) == 0, f"hook bloqueou indevidamente: {cmd}"


def test_o_hook_esta_registrado_em_arquivo_VERSIONADO():
    """`settings.local.json` é gitignored: hook registrado só lá vale numa máquina
    só, e trava que vale num lugar só não é trava. O registro tem que viajar com o
    repositório."""
    cfg = _RAIZ / ".claude" / "settings.json"
    assert cfg.exists(), "settings.json versionado não existe"
    d = json.loads(cfg.read_text())
    texto = json.dumps(d)
    assert "block-deploy-fora-do-gate" in texto, "o hook não está registrado no versionado"
    matchers = [r.get("matcher") for r in d["hooks"]["PreToolUse"]]
    assert "Bash" in matchers, "o hook precisa casar com Bash, senão não vê comando"


# ── o script de sync agora é rastreável e cobre todos os espelhos ────────────

def test_sync_dos_espelhos_esta_versionado():
    """Ele rodava a partir do GCS e não existia em lugar nenhum versionado: mudança
    nele não tinha revisão, histórico nem como voltar atrás."""
    p = _V2 / "api" / "lib" / "sync_espelhos_cron.sh"
    assert p.exists(), "o script do lockstep voltou a existir só no GCS"
    t = p.read_text()
    assert "gsutil cp" in t, "sumiu a instrução de como publicar depois de editar"


def test_sync_cobre_o_servico_de_webhook():
    """O `smart-ads-webhook` nasceu depois do script e ficou de fora, divergindo em
    silêncio no dia seguinte. Serviço novo que espelhe a imagem entra na lista."""
    import re
    t = (_V2 / "api" / "lib" / "sync_espelhos_cron.sh").read_text()
    # Casa com a ATRIBUIÇÃO, não com a menção: o nome também aparece no comentário
    # que explica por que ele entrou, e a primeira versão deste teste passou batido
    # justamente por isso.
    m = re.search(r'^ESPELHOS=.*$', t, re.M)
    assert m, "sumiu a variável ESPELHOS"
    assert "smart-ads-webhook" in m.group(0), (
        f"o webhook saiu da lista de espelhos: {m.group(0)}")
    assert "for svc in $ESPELHOS" in t, (
        "voltou a tratar um serviço só, em vez de percorrer os espelhos")


def test_sync_nao_engole_mais_o_erro_do_gcloud():
    """A mensagem era só "falha ao criar revisão". O motivo real (falta de
    permissão) ficava em /dev/null, e o job passou verde por dias sem nunca ter
    criado revisão de verdade."""
    t = (_V2 / "api" / "lib" / "sync_espelhos_cron.sh").read_text()
    # O comando é multilinha (continuação com barra invertida), e o redirecionamento
    # fica na ÚLTIMA linha dele. Olhar linha a linha faz o teste inspecionar a linha
    # errada e passar batido, que foi o que aconteceu na primeira versão.
    junto = t.replace("\\\n", " ")
    criacao = [l for l in junto.splitlines() if 'services update "$svc"' in l]
    assert criacao, "sumiu o comando que cria a revisão do espelho"
    assert "2>/dev/null" not in criacao[0], (
        f"o erro do gcloud voltou para /dev/null: {criacao[0][:140]}")
    assert '2>"$err_tmp"' in criacao[0], "o erro deixou de ser capturado"
    assert 'motivo=$(tail' in t, "sumiu a captura do motivo da falha"


# ---------------------------------------------------------------------------
# 14/09/2026: o deploy passa a rodar também no runner do GitHub Actions. Três amarras
# que só existiam porque o script nasceu num laptop, e que num runner viravam ou erro
# ("/Users/ramonmoreira" não existe lá) ou, pior, gate pulado em silêncio.
# ---------------------------------------------------------------------------
_GATE = _V2 / "api" / "deploy-gate.sh"
_DEPLOY = next((_V2 / "api").glob("deploy_ca*.sh"))


def test_gate_nao_depende_de_caminho_de_uma_maquina():
    t = _GATE.read_text()
    assert "/Users/" not in t, "caminho absoluto de laptop no gatekeeper: não roda no runner"
    assert 'REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")' in t, "a raiz do repo tem que ser derivada do próprio arquivo, não de uma constante"


def test_gate_c_nao_e_mais_pulado_sem_env():
    """Um replay de 50 leads que não roda não prova nada. Sem credencial é falha, não aviso."""
    t = _DEPLOY.read_text()
    assert re.search(r"Gate C[^\n]*pulado", t) is None, "Gate C voltou a ser pulável"
    assert "baixar_artefatos_modelo.sh" in t, "o build tem que buscar os artefatos no bucket"


def test_rollback_e_a_revisao_viva_e_sem_default_velho():
    t = _DEPLOY.read_text()
    g = (_V2 / "scripts" / "progression_gate.py").read_text()
    assert "00269-jjn" not in t and "00269-jjn" not in g, "voltou o default de revisão morta"
    assert "percent')==100" in t, "o alvo de rollback tem que ser a revisão que serve 100%"
