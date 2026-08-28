"""
O papel do serviço público tem que se auto-curar, e nos DOIS caminhos.

Contexto: o `smart-ads-webhook` nasceu em 05/08/2026 para o serviço principal poder
ficar fechado, e é o único público (a Hotmart não assina token do Google). Os dois
rodam a MESMA imagem. O que reduz a superfície do público de 36 rotas para 4 é a
lista `ROTAS_DO_WEBHOOK` em api/auth.py, e ela só vale com `SERVICE_ROLE=webhook`.
`papel_do_servico()` cai em `full` quando a env falta, então o valor ausente ABRE a
superfície em silêncio. Nada, até 28/08/2026, escrevia essa env.

Três contratos aqui, e o terceiro é o que a versão ingênua da correção não daria:

  1. Os dois lugares que criam revisão de espelho reafirmam o papel: o cron diário
     (lib/sync_espelhos_cron.sh) e o lockstep do gate (deploy-gate.sh). Reafirmar só
     num deles deixa o outro caminho recriando revisão sem a env.
  2. As duas tabelas de papel concordam. Elas são duplicadas de propósito, porque o
     cron roda do GCS sem o repositório e não pode sourcear o gate.
  3. O papel é conferido MESMO SEM drift de imagem. O dia em que a env some é
     justamente um dia sem drift de imagem: um serviço recriado do zero nasce na
     imagem certa e sem `SERVICE_ROLE`. Amarrar o conserto ao drift de imagem seria
     escrever "auto-cura" num código que só cura quando o outro problema aparece.
"""

import re
import subprocess
from pathlib import Path

import pytest

from api.auth import ROTAS_DO_WEBHOOK, papel_do_servico

_RAIZ = Path(__file__).resolve().parents[2]
_ARQUIVOS = {
    "deploy-gate.sh": _RAIZ / "V2" / "api" / "deploy-gate.sh",
    "sync_espelhos_cron.sh": _RAIZ / "V2" / "api" / "lib" / "sync_espelhos_cron.sh",
}
_PUBLICO = "smart-ads-webhook"


def _linha_da_funcao(caminho: Path, nome: str) -> str:
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.startswith(f"{nome}()"):
            return linha
    raise AssertionError(f"{caminho.name} não define {nome}()")


def _papel(caminho: Path, servico: str) -> str:
    """Roda a função de verdade no bash, isolada do resto do script."""
    fn = _linha_da_funcao(caminho, "papel_do_espelho")
    r = subprocess.run(
        ["bash", "-c", f'{fn}\npapel_do_espelho "{servico}"'],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.parametrize("nome", sorted(_ARQUIVOS))
def test_servico_publico_recebe_papel_reduzido(nome):
    assert _papel(_ARQUIVOS[nome], _PUBLICO) == "webhook", (
        f"{nome} não declara o papel do {_PUBLICO}: revisão criada por ele sobe "
        "servindo a API inteira num serviço aberto na internet"
    )


@pytest.mark.parametrize("nome", sorted(_ARQUIVOS))
def test_espelho_interno_continua_full(nome):
    """O monitoring precisa das rotas todas. Papel vazio = default `full`."""
    assert _papel(_ARQUIVOS[nome], "smart-ads-monitoring") == ""


def test_as_duas_tabelas_de_papel_concordam():
    gate, cron = _ARQUIVOS["deploy-gate.sh"], _ARQUIVOS["sync_espelhos_cron.sh"]
    for svc in (_PUBLICO, "smart-ads-monitoring", "smart-ads-api", "servico-inventado"):
        assert _papel(gate, svc) == _papel(cron, svc), (
            f"as tabelas divergiram em {svc}: o cron e o gate passariam a escrever "
            "papéis diferentes no mesmo serviço"
        )


def test_papel_declarado_e_aceito_pelo_auth():
    """Um typo aqui não daria erro: `papel_do_servico` cai em `full` calado."""
    declarado = _papel(_ARQUIVOS["deploy-gate.sh"], _PUBLICO)
    assert papel_do_servico({"SERVICE_ROLE": declarado}) == "webhook", (
        f"o papel escrito pelo deploy ({declarado!r}) não é reconhecido por "
        "api/auth.py, então o serviço público serviria a API inteira"
    )
    assert len(ROTAS_DO_WEBHOOK) < 10, (
        "a lista de rotas do papel webhook cresceu demais para ainda ser uma "
        "redução de superfície — confira o que entrou"
    )


@pytest.mark.parametrize("nome", sorted(_ARQUIVOS))
def test_o_papel_entra_no_update_env_vars(nome):
    texto = _ARQUIVOS[nome].read_text(encoding="utf-8")
    assert re.search(r'envs="\$envs,SERVICE_ROLE=\$papel"', texto), (
        f"{nome} não acrescenta SERVICE_ROLE às env vars da revisão nova"
    )
    assert re.search(r'--update-env-vars="\$envs"', texto), (
        f"{nome} monta as env vars mas não as passa para o gcloud"
    )


def _leitores_de_env() -> str:
    """As funções que leem env de uma revisão, recortadas para rodar isoladas."""
    linhas = _ARQUIVOS["sync_espelhos_cron.sh"].read_text(encoding="utf-8").splitlines()
    ini = next(i for i, l in enumerate(linhas) if l.startswith("rev_env()"))
    fim = next(i for i, l in enumerate(linhas) if l.startswith("rev_papel()"))
    return "\n".join(linhas[ini:fim + 1])


def _sem_gcloud(chamada: str) -> str:
    """Roda a chamada com o `gcloud` mudo: simula revisão sem a env, sem rede."""
    script = f'gcloud(){{ return 0; }}\nPROJECT=x; REGION=y\n{_leitores_de_env()}\n{chamada}'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_papel_ausente_volta_vazio_e_nao_unknown():
    """`${3:-unknown}` trocaria a string VAZIA pelo default e mentiria no log.

    A auto-cura sobrevivia ao bug, porque qualquer valor diferente do declarado
    dispara o conserto. O que quebrava era a leitura humana: o log diria papel
    'unknown' onde o certo é 'ausente', e o comentário do código afirmava
    exatamente o contrário do que o código fazia.
    """
    assert _sem_gcloud("rev_papel revisao-qualquer") == ""
    assert _sem_gcloud("rev_sha revisao-qualquer") == "unknown", (
        "o fallback explícito das outras chaves não pode ter sido perdido junto"
    )


@pytest.mark.parametrize("nome", sorted(_ARQUIVOS))
def test_papel_e_conferido_mesmo_sem_drift_de_imagem(nome):
    """O contrato nº 3, o que a versão ingênua da correção não daria."""
    texto = _ARQUIVOS[nome].read_text(encoding="utf-8")
    assert re.search(r'\[ "\$mp" != "\$papel" \]', texto), (
        f"{nome} não compara o papel VIVO com o declarado"
    )
    # A saída antecipada (o "nada a fazer") não pode depender só da imagem.
    # `if [ ... ]; then ... fi` num arquivo e `[ ... ] || { ... }` no outro.
    saidas = re.findall(r'^\s*(?:if\s+)?\[.*\].*(?:return 0|nada a fazer|sem drift).*$',
                        texto, flags=re.MULTILINE)
    assert saidas, f"{nome}: não achei a saída antecipada do alinhamento"
    assert any("precisa" in s for s in saidas), (
        f"{nome} decide 'nada a fazer' sem olhar o papel: um serviço recriado na "
        "imagem certa e sem SERVICE_ROLE ficaria exposto para sempre"
    )
