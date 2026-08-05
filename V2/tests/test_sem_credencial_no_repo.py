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
PADROES_PROIBIDOS = [
    (re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^\s:/{]+:(?![<${])[^\s@/{}]{6,}@"),
     "URI de banco com senha embutida (use env var / Secret Manager)"),
    (re.compile(r"""[A-Z_]*PASSWORD[A-Z_]*\s*=\s*["']?(?![<${\s"'])"""
                r"""(?![^\s"',)]*\()[^\s"',)]{6,}"""),
     "senha atribuída em texto claro"),
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
