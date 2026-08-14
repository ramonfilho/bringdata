"""Nenhum arquivo de DADO TABULAR entra versionado. Este repositório é PÚBLICO.

IRMÃO do `test_sem_credencial_no_repo.py`, e existe porque aquele não pegava isto.

Em 14/08/2026 foi encontrado `V2/compare_encoded.parquet` commitado desde 08/03/2026:
202.489 linhas, **202.219 e-mails reais distintos**, 63 colunas de característica e
2.636 compradores identificáveis. Cinco meses público. Passou por DOIS incidentes de
segurança sem ninguém abrir.

POR QUE O TESTE ANTERIOR NÃO PEGOU: ele procura CREDENCIAL, e por texto. Um parquet é
binário e comprimido, não tem `senha=` dentro, e 6 MB não parecem um segredo. A busca
por conteúdo é cega para o formato errado.

POR QUE ESTE CASA POR FORMATO E NÃO POR CONTEÚDO: abrir cada arquivo e procurar e-mail
falharia pelo mesmo motivo — em parquet os e-mails estão comprimidos, e uma varredura
dos bytes crus deste arquivo achava 318 dos 202.219. **Um teste que erra por 99,8% dá
falsa tranquilidade, que é pior que teste nenhum.** A regra segura é: arquivo de dado
tabular não entra, independente do que se acredite que tem dentro.

Credencial se rotaciona. E-mail de 202 mil pessoas, não.
"""
from pathlib import Path
import subprocess

_REPO = Path(__file__).resolve().parents[2]
_ESTE = f"V2/tests/{Path(__file__).name}"

# Formatos que carregam dado tabular. Não é lista de "o que já vazou": é lista de
# "o que é feito para guardar linhas", que é a categoria inteira do risco.
EXT_DE_DADO = {".parquet", ".csv", ".tsv", ".xlsx", ".xls", ".feather", ".arrow", ".dta"}

# Exceções por CAMINHO EXPLÍCITO, nunca por padrão amplo. Cada uma é uma decisão, e
# quem acrescentar uma linha aqui está afirmando que olhou dentro do arquivo.
PERMITIDOS = (
    "V2/configs/",          # configuração de cliente, sem linha de pessoa
    "V2/tests/fixtures/",   # fixture pequena de teste, escrita à mão
)

# Modelo serializado (.pkl) fica FORA desta lista de propósito: ele guarda parâmetro
# aprendido, não linha de pessoa, e os 4 que existem versionados foram varridos em
# 14/08/2026 com zero e-mail. Se algum dia um .pkl passar a carregar dado bruto, o
# lugar de barrar é aqui.


def _versionados_de_dado():
    out = subprocess.run(["git", "-C", str(_REPO), "ls-files", "-z"],
                         capture_output=True, text=True, check=True).stdout
    for nome in out.split("\0"):
        if not nome or nome == _ESTE:
            continue
        if Path(nome).suffix.lower() not in EXT_DE_DADO:
            continue
        if any(nome.startswith(p) for p in PERMITIDOS):
            continue
        yield nome


def test_nenhum_arquivo_de_dado_tabular_versionado():
    achados = sorted(_versionados_de_dado())
    assert not achados, (
        "Arquivo de dado tabular VERSIONADO num repositório PÚBLICO:\n  "
        + "\n  ".join(achados)
        + "\n\nDado não entra no repositório. Quem precisar de dado versionado usa o "
          "bucket (gs://smart-ads-mlflow/). Se este arquivo for realmente inofensivo, "
          "a exceção vai em PERMITIDOS, por caminho explícito, e quem a acrescentar "
          "está afirmando que abriu e conferiu."
    )


def test_a_lista_de_permitidos_e_estreita():
    """Exceção larga (ex.: 'V2/') anularia o teste sem que ninguém percebesse."""
    for p in PERMITIDOS:
        assert p.count("/") >= 2, f"exceção larga demais: {p!r}"
