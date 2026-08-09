"""Repesca a URL de captura que ficou para trás em backups e recarrega no banco.

O PROBLEMA
==========
A entrega para a agência tinha 303 URLs em janeiro de 2026, de 34.903 leads (0,9%).
A conclusão inicial, registrada em 06/08/2026, foi de que aquele mês simplesmente não
tinha registrado a URL. Estava ERRADA, e o erro é instrutivo: foi tirada de duas
fontes ("a planilha de produção tem só 4,1%" e "a pasta do Drive não tem os
lançamentos de janeiro"), as duas verdadeiras, mas "não achei onde procurei" não é
"não existe". Uma varredura pelo CATÁLOGO, em 09/08/2026, achou o dado em minutos.

POR QUE ESTAVA ESCONDIDO
========================
A URL de janeiro morava em `leads_capi.event_source_url`. Aquela tabela morreu em
30/04/2026 e hoje a coluna está vazia, então quem olha a tabela viva conclui que ela
nunca teve o dado. Em fevereiro ela estava cheia. **O dado não se perdeu: ele deixou
de ser copiado adiante quando o schema mudou.** É um padrão a procurar em qualquer
coluna que "sempre foi vazia": conferir um backup ANTES da migração que a aposentou.

AS FONTES, e o que cada uma rende (medido em 09/08/2026, alvo = 34.600 leads de
janeiro sem URL):

  1. `cloud-sql-final-export-20260225.sql.gz` — dump do Cloud SQL `bring-data-db`,
     descomissionado em 25/02/2026. Tem 47.494 linhas de janeiro com URL em 100%.
     Cobre 33.772 do alvo (97,6%).
  2. Cópia da planilha de produção tirada em 08/02/2026 (aba `[LF] Pesquisa v2`).
     Cobre 14.606, dos quais só 341 são NOVOS sobre o dump. Entra mesmo assim: 341
     leads é mais do que os 303 que a entrega inteira tinha em janeiro.

E as duas que NÃO rendem nada, registradas para ninguém refazer o caminho:

  - `lead.parquet` (retrato da tabela `Lead` em 23/06): 130.198 URLs, ZERO novas. É
    a mesma tabela que já virou `lead_legado` e já é fonte de prioridade 2.
  - `leads_arquivo_pre_elim_20260721.csv` (474 MB): não tem coluna de URL nenhuma.

RESULTADO: 34.113 de 34.600 em janeiro (98,6%) e 56.481 no ano de 2026 (59,3%).

SOBRE O CONTEÚDO DAS URLs
=========================
Auditado antes de carregar, porque isto vai para uma agência externa. Os domínios são
só landing pages do cliente. Os parâmetros são UTM e identificadores de clique. Há
`nome`, `email` e `telefone` no query string de ~35 mil delas — os três dados que o
cliente autorizou expressamente a compartilhar, e que já são colunas próprias da
entrega. NÃO há CPF, documento, endereço nem data de nascimento. O `mcp_token`
presente em 1.200 URLs é identificador de clique de rede de anúncio (mesma categoria
do `fbclid`) e expirou em 05/01/2026.

A URL é gravada CRUA, sem limpar parâmetro. Reescrever o endereço faria dele um
endereço que nunca existiu, e o valor dele aqui é justamente ser a prova de qual
página capturou o lead.

USO
===
    python -m scripts.recupera_url_legado            # carrega
    python -m scripts.recupera_url_legado --dry-run  # só mede, não escreve
"""
from __future__ import annotations

import argparse
import base64
import gzip
import io
import json
import os
import sys
import urllib.parse
import urllib.request

TABELA = "analytics.url_captura_legado"

BUCKET = "smart-ads-validation-reports"
OBJ_DUMP = "backups/cloud-sql-final-export-20260225.sql.gz"
# Cópia da planilha de produção congelada em 08/02/2026. O nome real do arquivo é
# `copia_de_analise_ [LF] Pesquisa - Mai25 - February 8, 12:13 PM`; ela aparece no
# `docs/acesso_sheets.md` como "planilha de backup".
SHEET_COPIA = "1OqNYA5zU9ix1uf52ovRYIdLhcugzwgfKOheKxE_zgvE"
# Só a aba v2 tem a coluna preenchida: na aba `[LF] Pesquisa` a `Page URL` existe mas
# está inteiramente vazia (medido: 68.348 linhas, zero URLs).
SHEET_ABA = "[LF] Pesquisa v2"
SHEET_COL_EMAIL = "C"
SHEET_COL_URL = "W"


# Conta de serviço usada para ler o Drive. O ADC de usuário NÃO consegue emitir token
# com escopo de Drive (o gcloud recusa: "Invalid scopes value"), então o caminho é
# personificar uma conta de serviço — e é ela, não o usuário, que tem as planilhas
# compartilhadas. Requer `roles/iam.serviceAccountTokenCreator` sobre a SA.
SA_DRIVE = os.environ.get("SA_DRIVE", "smart-ads-451319@appspot.gserviceaccount.com")


def _token(escopos: str = "") -> str:
    """Token de acesso do gcloud. Com escopo de Drive, via personificação da SA."""
    import subprocess
    cmd = ["gcloud", "auth", "print-access-token"]
    if escopos:
        cmd += [f"--scopes={escopos}", f"--impersonate-service-account={SA_DRIVE}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    t = r.stdout.strip()
    if not t:
        raise RuntimeError(f"sem token do gcloud: {r.stderr.strip()[:300]}")
    return t


def _http(url: str, token: str, timeout: int = 900) -> bytes:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def do_dump() -> dict[str, str]:
    """email -> URL, extraídos do COPY de `leads_capi` no dump de 25/02/2026.

    Lê o .sql.gz direto do GCS e varre só o bloco COPY da tabela, sem restaurar o
    dump em lugar nenhum. As posições das colunas saem do cabeçalho do próprio COPY,
    e não de índice fixo: dump de outra data pode ter outra ordem.
    """
    url = (f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o/"
           + urllib.parse.quote(OBJ_DUMP, safe="") + "?alt=media")
    bruto = _http(url, _token(""))
    pares: dict[str, str] = {}
    dentro = False
    i_email = i_url = -1
    with gzip.open(io.BytesIO(bruto), "rt", errors="replace") as f:
        for linha in f:
            if not dentro:
                if linha.startswith("COPY public.leads_capi ("):
                    cols = [c.strip().strip('"') for c in
                            linha[linha.index("(") + 1:linha.rindex(")")].split(",")]
                    i_email = cols.index("email")
                    i_url = cols.index("event_source_url")
                    dentro = True
                continue
            if linha.startswith("\\."):
                break
            p = linha.rstrip("\n").split("\t")
            if len(p) <= max(i_email, i_url):
                continue
            u = p[i_url]
            if u.startswith("http") and p[i_email]:
                pares.setdefault(p[i_email].strip().lower(), u)
    return pares


def do_sheet() -> dict[str, str]:
    """email -> URL, da cópia congelada da planilha de produção.

    Por que a API de valores e não exportar como xlsx: o arquivo passa do limite de
    exportação do Drive e o /export devolve 403 `exportSizeLimitExceeded`.
    """
    tok = _token("https://www.googleapis.com/auth/drive.readonly,"
                 "https://www.googleapis.com/auth/spreadsheets.readonly")

    def coluna(letra: str) -> list[str]:
        rng = urllib.parse.quote(f"{SHEET_ABA}!{letra}2:{letra}70000")
        u = (f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_COPIA}/values/"
             f"{rng}?majorDimension=COLUMNS")
        v = json.loads(_http(u, tok)).get("values", [])
        return v[0] if v else []

    mails, urls = coluna(SHEET_COL_EMAIL), coluna(SHEET_COL_URL)
    pares: dict[str, str] = {}
    for i in range(max(len(mails), len(urls))):
        m = (mails[i] if i < len(mails) else "").strip().lower()
        u = urls[i] if i < len(urls) else ""
        if m and str(u).startswith("http"):
            pares.setdefault(m, u)
    return pares


def grava(conn, pares_por_fonte: dict[str, dict[str, str]]) -> int:
    """Recria a tabela inteira, dentro de uma transação.

    Substituição total em vez de merge: as fontes são arquivos IMÓVEIS (um dump de
    fevereiro não muda), então recarregar dá sempre o mesmo resultado e não existe
    estado incremental para dar errado. São ~100 mil linhas, custa segundos.

    A coluna `fonte` não é enfeite: quando um número não bater lá na frente, ela é o
    que separa "URL capturada ao vivo" de "URL repescada de backup em 09/08/2026".
    Sem ela, daqui a três meses ninguém distingue as duas coisas.
    """
    conn.run("BEGIN")
    conn.run(f"DROP TABLE IF EXISTS {TABELA}")
    conn.run(f"""CREATE TABLE {TABELA} (
        email        text PRIMARY KEY,
        utm_url      text NOT NULL,
        fonte        text NOT NULL,
        recuperado_em timestamptz NOT NULL DEFAULT now()
    )""")
    # Ordem importa: a primeira fonte a reivindicar um e-mail fica com ele. O dump
    # vem antes da planilha por ser maior e por ser o registro do próprio sistema,
    # não uma cópia manual.
    visto: set[str] = set()
    total = 0
    for fonte, pares in pares_por_fonte.items():
        lote = [(e, u, fonte) for e, u in pares.items() if e not in visto]
        visto |= {e for e, _, _ in lote}
        for i in range(0, len(lote), 500):
            bloco = lote[i:i + 500]
            vals = ",".join(
                f"(:e{j}, :u{j}, :f{j})" for j in range(len(bloco)))
            params = {}
            for j, (e, u, f) in enumerate(bloco):
                params[f"e{j}"], params[f"u{j}"], params[f"f{j}"] = e, u, f
            conn.run(f"INSERT INTO {TABELA} (email, utm_url, fonte) VALUES {vals}", **params)
        total += len(lote)
    conn.run(f"CREATE INDEX ON {TABELA} (fonte)")
    conn.run("COMMIT")
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="mede as fontes e não escreve nada no banco")
    a = ap.parse_args()

    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, raiz)
    # `load_dotenv` e não `source .env`: o `source` mutila credencial que tem espaço
    # ou barra vertical no valor, e já quebrou aqui antes.
    from dotenv import load_dotenv
    load_dotenv(os.path.join(raiz, ".env"))
    from scripts.provisiona_dash_zanelato import origem_leitura

    print("lendo o dump de 25/02 do GCS…", flush=True)
    dump = do_dump()
    print(f"  {len(dump):,} pares email->URL", flush=True)
    # A planilha é OPCIONAL de propósito. Ela acrescenta 341 leads sobre o dump (que
    # sozinho já dá 97,6% de janeiro), e depende de uma permissão de personificação
    # que pode não estar concedida na hora. Derrubar a carga inteira por causa de 1%
    # seria pior do que carregar 99% e dizer em voz alta o que faltou. O que NÃO pode
    # é falhar em silêncio: por isso o aviso é gritado, não engolido.
    print("lendo a cópia da planilha de 08/02…", flush=True)
    try:
        sheet = do_sheet()
        print(f"  {len(sheet):,} pares email->URL", flush=True)
    except Exception as e:
        sheet = {}
        print(f"  !! NÃO LI A PLANILHA: {str(e)[:200]}", flush=True)
        print(f"  !! seguindo só com o dump. Faltarão ~341 URLs de janeiro.", flush=True)
        print(f"  !! para incluí-la, conceda serviceAccountTokenCreator sobre "
              f"{SA_DRIVE} e rode de novo.", flush=True)

    fontes = {"dump_cloudsql_20260225": dump, "copia_planilha_20260208": sheet}
    if a.dry_run:
        print(f"\n[dry-run] gravaria ~{len(set(dump) | set(sheet)):,} linhas em {TABELA}")
        return 0

    conn = origem_leitura(timeout=900)
    try:
        n = grava(conn, fontes)
        print(f"\n{TABELA}: {n:,} linhas")
        for r in conn.run(f"SELECT fonte, count(*) FROM {TABELA} GROUP BY 1 ORDER BY 2 DESC"):
            print(f"   {r[0]:<26} {r[1]:>7,}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
