"""
Nenhum arquivo VERSIONADO carrega credencial literal.

Este repositório é PÚBLICO. Até 05/08/2026 a senha do usuário `postgres` do nosso
Cloud SQL estava escrita em texto claro em 11 arquivos versionados, junto com o IP
público da instância. Como a instância aceita conexão de qualquer IP, qualquer
pessoa que lesse o GitHub tinha acesso de DONO a `analytics.leads` (366 mil leads
com e-mail, telefone e nome) e a `analytics.sales`.

O vazamento não foi um descuido pontual: a senha entrou como default "prático" num
arquivo de código, e daí foi copiada pra doc, pra script e pra checklist ao longo de
meses. Nenhum teste olhava pra isso, então cada cópia nova passava batido. Este teste
é a trava: varre o que o git rastreia e falha se credencial literal aparecer, em
qualquer arquivo, não só nos que já vazaram.

Casa por FORMA, não por valor: listar a senha antiga aqui pra testar que ela não está
no repositório seria reintroduzir o problema. As duas formas que importam são URI de
banco com senha inline e atribuição direta a variável de senha, que juntas cobrem as
11 cópias que existiam.

Escopo de propósito: só o que está VERSIONADO (`git ls-files`). O `V2/.env` é onde a
credencial deve morar e está no `.gitignore`: este teste não olha pra ele, e é assim
que tem que ser.
"""

import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

# Formas de credencial que não podem existir em arquivo versionado, seja qual for o
# valor. Dois lookaheads separam segredo de código legítimo:
#   `(?![<${])`          deixa passar placeholder (`<senha…>`), env var (`$VAR`,
#                          `${VAR:-…}`) e f-string do Python (`{password}`);
#   `(?![^\s"',)]*\()`   deixa passar leitura de ambiente (`os.environ.get(…)`),
#                          que é chamada de função, não valor literal.
#
# O BURACO QUE ESTES LOOKAHEADS ABRIRAM, E QUE CUSTOU UMA SEGUNDA CREDENCIAL
# ==========================================================================
# Liberar `${` era necessário e não era suficiente. Em bash, `${VAR:-valor}` é o idioma de
# "env var com fallback", e o FALLBACK é um valor literal. Ou seja, o lookahead que ignorava
# `${` para não acusar leitura de ambiente estava ignorando também tudo o que vinha depois —
# inclusive um segredo.
#
# Foi exatamente onde a senha do Railway ficou, em `V2/api/lib/config.sh`, até 12/08/2026:
#
#     RAILWAY_DB_PASSWORD="${RAILWAY_DB_PASSWORD:-<a senha de verdade>}"
#
# O teste passava. A senha estava num repositório público. Este arquivo foi escrito em
# 05/08/2026 justamente para travar a reincidência, e a reincidência estava dentro dele, na
# forma que ele decidiu não olhar.
#
# A lição é sobre a forma da trava, não sobre esta credencial: um guard que precisa abrir
# exceção sintática tem que checar o que está DENTRO da exceção. Por isso o padrão novo
# abaixo é separado, e não um remendo no lookahead do padrão antigo — o antigo continua
# fazendo o trabalho dele, e o novo cobre o que ele estruturalmente não vê.
PADROES_PROIBIDOS = [
    (re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^\s:/{]+:(?![<${])[^\s@/{}]{6,}@"),
     "URI de banco com senha embutida (use env var / Secret Manager)"),
    (re.compile(r"""[A-Z_]*PASSWORD[A-Z_]*\s*=\s*["']?(?![<${\s"'])"""
                r"""(?![^\s"',)]*\()[^\s"',)]{6,}"""),
     "senha atribuída em texto claro"),
    # Segredo escondido no fallback de uma env var do shell: `${VAR:-segredo}`.
    #
    # Três condições, e cada uma existe para calibrar um falso positivo REAL do projeto:
    #   1. o nome da variável tem que sugerir credencial — senão pegaria `${PORT:-5432}`,
    #      `${LEDGER_DB_HOST:-104.197.138.129}` e todo default legítimo;
    #   2. o fallback tem que ser LITERAL — `$(gcloud secrets …)`, `<placeholder>`,
    #      `${outra}` e string vazia passam, que é exatamente o jeito certo de escrever;
    #   3. o fallback NÃO pode ser kebab-case (`meta-audiences-token`), porque essa é a
    #      convenção de NOME de recurso no GCP, e `TOKEN_SECRET="${…:-meta-audiences-token}"`
    #      guarda o nome de um secret, não o valor dele.
    #
    # O preço da condição 3, dito às claras: uma senha que fosse toda minúscula com hífen
    # (uma passphrase tipo `cavalo-bateria-grampo`) passaria batido. É um buraco estreito e
    # conhecido, e o alternativa era acusar todo nome de secret do projeto — guard que grita
    # em código correto é desligado, e desligado não protege nada.
    (re.compile(r"""(?:PASSWORD|SENHA|SECRET|TOKEN|APIKEY|API_KEY|_KEY|CREDENTIAL)"""
                r"""[A-Z_]*\s*=\s*["']?\$\{[A-Za-z_][A-Za-z0-9_]*:-"""
                r"""(?![<$\s"'}])(?![a-z0-9]+(?:-[a-z0-9]+)+\})[^}\s"']{6,}\}"""),
     "segredo no fallback de env var do shell (${VAR:-segredo}) — use "
     "$(gcloud secrets versions access …)"),
    # O MESMO buraco, na forma do Python: `os.environ.get("X_PASSWORD", "segredo")`.
    #
    # Encontrado em 12/08/2026, HORAS depois de fechar a versão shell logo acima, e em dois
    # arquivos que estavam vivos no repositório público (`dt12_impact_analysis.py` e
    # `test_encoding_overrides.py`). A causa é a mesma de sempre: o lookahead
    # `(?![^\s"',)]*\()` do padrão de "senha em texto claro" existe para deixar passar
    # leitura de ambiente, que é uma chamada de função — e o segredo estava no ARGUMENTO
    # DEFAULT dessa chamada, do lado de dentro do que o guard ignorava.
    #
    # A lição vale mais que os dois padrões: TODA construção "usa o ambiente, senão usa
    # isto" é um esconderijo de segredo, porque a metade "usa o ambiente" é exatamente o que
    # faz o guard olhar para o outro lado. Se aparecer uma terceira forma (`config.get(…)`,
    # `?? "…"` em JS, `or "…"` em Python), o padrão novo vem PARA CÁ — nunca como remendo
    # nos lookaheads dos outros, que foi o que deixou este passar duas vezes.
    #
    # O nome da chave tem que sugerir credencial e o default tem que ser literal não-vazio:
    # `os.getenv("X_PASSWORD")` sem default passa, e é justamente o jeito certo.
    #
    # E vale a MESMA exclusão de kebab-case do padrão do shell, pelo mesmo motivo:
    # `os.getenv("SECRET_NAME", "railway-db-password")` guarda o NOME de um secret, não o
    # valor. Sem essa exclusão o guard acusaria código correto — e guard que grita em código
    # correto é desligado, e desligado não protege nada.
    #
    # O preço, medido e não suposto: um segredo com hífens passa por aqui. Testado com
    # `os.getenv("SLACK_TOKEN", "xoxb-abc-def-ghi")` — este padrão NÃO pega, mas o padrão
    # `xoxb-…` logo abaixo pega, então o caso concreto está coberto por outra via. Não há
    # separação limpa por regex entre `railway-db-password` (nome) e `xoxb-abc-def-ghi`
    # (valor): as duas têm a mesma forma. Quem quiser fechar isto de vez precisa de uma
    # lista dos nomes de secret válidos, não de mais um lookahead.
    (re.compile(r"""os\.(?:environ\.get|getenv)\(\s*["'][A-Za-z_]*"""
                r"""(?:PASSWORD|SENHA|SECRET|TOKEN|APIKEY|API_KEY|CREDENTIAL)"""
                r"""[A-Za-z_]*["']\s*,\s*["']"""
                r"""(?![a-z0-9]+(?:-[a-z0-9]+)+["'])[^"']{6,}["']"""),
     "segredo no default de os.environ.get / os.getenv — tire o default e deixe "
     "estourar, ou leia do Secret Manager"),
    (re.compile(r"xoxb-[A-Za-z0-9]{8,}-[A-Za-z0-9-]{8,}"), "token de bot do Slack"),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"), "token pessoal do GitHub"),
    (re.compile(r"\bAIza[A-Za-z0-9_\-]{30,}\b"), "chave de API do Google"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "chave privada"),
]

# Binários e artefatos onde varrer texto não faz sentido.
EXT_IGNORADAS = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".xlsx", ".xls", ".zip",
                 ".gz", ".pkl", ".joblib", ".parquet", ".db", ".ico", ".woff",
                 ".woff2", ".ttf", ".mp4", ".svg"}

# Este próprio arquivo descreve os padrões, então casaria com eles.
_ESTE = f"V2/tests/{Path(__file__).name}"


def _arquivos_versionados():
    out = subprocess.run(["git", "-C", str(_REPO), "ls-files", "-z"],
                         capture_output=True, text=True, check=True).stdout
    for nome in out.split("\0"):
        if not nome or nome == _ESTE:
            continue
        p = _REPO / nome
        if p.suffix.lower() in EXT_IGNORADAS or not p.is_file():
            continue
        try:
            yield nome, p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue


def test_nenhuma_credencial_literal_em_arquivo_versionado():
    achados = []
    for nome, conteudo in _arquivos_versionados():
        for padrao, oque in PADROES_PROIBIDOS:
            for m in padrao.finditer(conteudo):
                linha = conteudo[:m.start()].count("\n") + 1
                achados.append(f"{nome}:{linha}: {oque}")
    assert not achados, (
        "credencial literal em arquivo versionado, e o repositório é PÚBLICO:\n  "
        + "\n  ".join(sorted(set(achados))))


def test_uri_do_mlflow_nao_tem_default_com_senha():
    """A URI de tracking tem que vir do ambiente, sem fallback embutido, e a falta
    dela precisa falhar alto, não cair calada num MLflow local vazio (o run do treino
    iria pra lugar nenhum e ninguém perceberia)."""
    import importlib
    import os

    mod = importlib.import_module("src.core.mlflow_setup")
    assert not hasattr(mod, "DEFAULT_TRACKING_URI"), (
        "DEFAULT_TRACKING_URI voltou, era ela que carregava a senha em claro")

    salvo = os.environ.pop("MLFLOW_TRACKING_URI", None)
    original = mod._V2_ROOT
    try:
        # Aponta o carregador do .env pra um diretório sem .env, senão o teste passa
        # por acidente na máquina de quem já tem a env configurada.
        mod._V2_ROOT = Path("/nao/existe")
        with pytest.raises(RuntimeError, match="MLFLOW_TRACKING_URI"):
            mod.resolve_tracking_uri()
    finally:
        mod._V2_ROOT = original
        if salvo is not None:
            os.environ["MLFLOW_TRACKING_URI"] = salvo
