"""
Provisiona a entrega de dados para o time da Zanelato (agência de tráfego do
DevClub): banco separado, tabela única, usuário somente-leitura.

Por que BANCO SEPARADO e não uma view no `ledger`:

  1. Todo banco Postgres carrega um catálogo de si mesmo (`information_schema`,
     `pg_class`), legível por QUALQUER role que consiga conectar nele. O catálogo
     mostra nome de tabela e de coluna, nunca conteúdo. Uma view no `ledger`
     protegeria os dados mas deixaria o usuário ver que existem colunas chamadas
     `lead_score` e `decil`. Como o catálogo é POR BANCO, um banco que só contém a
     tabela da entrega tem um catálogo que só menciona a tabela da entrega. O
     problema desaparece por construção em vez de ser mitigado.
  2. Isolamento de carga. A instância é uma `db-f1-micro`, a menor que existe. Uma
     consulta mal escrita do dashboard deles disputaria CPU com o scoring de
     produção.

REGRA INEGOCIÁVEL: score e decil NÃO saem, em nenhuma forma, nem agrupados. Vale
para `lead_score`, `score_champion`, `score_challenger`, `decil*`,
`decile_propensity`, `decile_roas_v1`, `hotleads_hot` e qualquer nota derivada
(A/B/C/D, quartil, quente/frio). Trocar 10 decis por 4 letras não protege nada: com
volume, a ordenação é recuperável, e a ordenação É o método.

Sobre dado pessoal: a tabela sai SEM nome, e-mail e telefone. O identificador é um
hash do e-mail, estável, que serve para contar e cruzar dentro da própria tabela mas
não identifica ninguém sozinho. Eles são gestores de tráfego montando painel de
criativo, e para isso não precisam saber quem é a pessoa. Se um caso de uso concreto
exigir, é decisão consciente de quem opera, não default.

Uso:
    python -m scripts.provisiona_dash_zanelato --dry-run     # conta, não grava
    python -m scripts.provisiona_dash_zanelato --provisionar # cria banco/role/tabela
    python -m scripts.provisiona_dash_zanelato --refresh     # só recarrega os dados
    python -m scripts.provisiona_dash_zanelato --aceitacao   # prova o isolamento
"""

from __future__ import annotations

import argparse
import os
import ssl
import sys
from pathlib import Path

_V2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_V2))

BANCO = "dash"
SCHEMA = "dash"
TABELA = "leads_2026"
ROLE = "dash_zanelato"
ANO = 2026

# Tabelas que o usuário da entrega NÃO pode alcançar. O teste de aceitação exige
# `permission denied` em todas, e ele roda antes de qualquer credencial sair daqui.
PROIBIDAS = [
    ("ledger", "public.registros_ml"),
    ("ledger", "public.scores_historicos"),
    ("ledger", "public.lead_legado"),
    ("ledger", "analytics.leads"),
    ("ledger", "analytics.cadastros"),
    ("ledger", "analytics.captacoes"),
    ("ledger", "analytics.sales"),
]

# Perguntas da pesquisa, na chave canônica do jsonb -> nome da coluna na entrega.
# Nome de coluna em snake_case sem acento porque é o que ferramenta de BI aceita
# sem reclamar.
PESQUISA = [
    ("O seu gênero:", "genero"),
    ("Qual a sua idade?", "idade"),
    ("O que você faz atualmente?", "ocupacao"),
    ("Atualmente, qual a sua faixa salarial?", "faixa_salarial"),
    ("Você possui cartão de crédito?", "cartao_credito"),
    ("Tem computador/notebook?", "tem_computador"),
    ("Já estudou programação?", "estudou_programacao"),
    ("Você já fez/faz/pretende fazer faculdade?", "faculdade"),
    ("O que mais você quer ver no evento?", "interesse_evento"),
]


def _ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def conectar(user: str, senha: str, banco: str, timeout: int = 600):
    import pg8000.native
    return pg8000.native.Connection(
        host=os.environ["LEDGER_DB_HOST"],
        port=int(os.environ.get("LEDGER_DB_PORT", "5432")),
        database=banco, user=user, password=senha,
        ssl_context=_ctx(), timeout=timeout,
    )


def sal() -> str:
    """Sal do pseudônimo. SEM ele, `sha256(email)` é reversível por quem já tem a
    lista de e-mails, que é justamente o caso de uma agência de tráfego: bastaria
    hashear a própria base e cruzar. Com sal, o `lead_id` vira pseudônimo de
    verdade, estável entre cargas e inútil fora desta tabela.

    Fail-loud de propósito: sem o sal, o script para em vez de gerar um
    identificador que parece protegido e não é.
    """
    s = os.environ.get("DASH_LEAD_ID_SALT")
    if not s:
        import subprocess
        s = subprocess.run(
            ["gcloud", "secrets", "versions", "access", "latest",
             "--secret=dash-lead-id-salt", "--project=smart-ads-451319"],
            capture_output=True, text=True, timeout=60).stdout.strip()
    if not s:
        raise RuntimeError(
            "sem DASH_LEAD_ID_SALT (nem no ambiente nem no Secret Manager "
            "`dash-lead-id-salt`). Sem sal o lead_id não protege nada.")
    return s


def origem_leitura(timeout: int = 900):
    """Leitura do `ledger` com timeout folgado. O conector de produção usa 30s, que
    é curto para varrer 250 mil linhas com ordenação numa `db-f1-micro`."""
    return conectar(
        os.environ.get("LEDGER_DB_USER", "ledger_app"),
        os.environ["LEDGER_DB_PASSWORD"], "ledger", timeout=timeout)


def _admin():
    """Conexão com o usuário que pode criar banco e role."""
    senha = os.environ.get("POSTGRES_ADMIN_PASSWORD")
    if not senha:
        import subprocess
        senha = subprocess.run(
            ["gcloud", "secrets", "versions", "access", "latest",
             "--secret=mlflow-db-password", "--project=smart-ads-451319"],
            capture_output=True, text=True, timeout=60).stdout.strip()
    if not senha:
        raise RuntimeError(
            "sem senha de admin. Exporte POSTGRES_ADMIN_PASSWORD ou autentique o gcloud.")
    return senha


# ── consulta que monta a entrega ─────────────────────────────────────────────

def sql_fonte() -> str:
    """Uma linha por lead de 2026, com UTM, pesquisa, LF e marcador de compra.

    Decisões que valem a leitura:

    - **canal** sai de `COALESCE(utm_source, survey_responses->>'Source')`. A coluna
      sozinha é 0% em janeiro (aquele mês veio de planilha do Google Sheets, que só
      trazia a campanha) e o mesmo dado está no jsonb. Com o COALESCE a cobertura
      vai de 0% para 99,8% em janeiro, e fica entre 90% e 100% no ano.
    - **capturado_em** é a coluna promovida pelo escritor canônico. A chave inglesa
      `submittedAt` do jsonb é 0% aqui porque ele RENOMEIA o campo; a informação está
      em `capturado_em` e na chave `'Data'`, com 100% de cobertura e hora cheia em
      2026.
    - **lf** vem do calendário canônico por data de captação, não de rótulo no lead.
      Três pares de janelas se sobrepõem em 2026 (DEV19 x LF43, LF44 x LF45,
      LF60 x LF61), e sem tratamento o lead do dia de emenda apareceria DUAS vezes,
      inflando a contagem do painel deles em ~3.100 linhas. Convenção adotada: o dia
      de emenda pertence ao lançamento que COMEÇA nele, que é o mesmo critério do
      relatório de criativo. Daí o `DISTINCT ON` com `cap_start DESC`.
    - **comprou** é marcador, sem valor nem data: quanto entrou é informação de
      receita e não faz parte desta entrega.
    """
    cols_pesquisa = ",\n           ".join(
        f"nullif(l.survey_responses->>'{chave}', '') AS {alias}"
        for chave, alias in PESQUISA
    )
    return f"""
    SELECT DISTINCT ON (l.event_id)
           encode(sha256((:sal || lower(l.email))::bytea), 'hex') AS lead_id,
           l.capturado_em,
           cal.lf_name AS lf,
           CASE
             WHEN lower(coalesce(nullif(l.utm_source,''),
                                 nullif(l.survey_responses->>'Source',''), '')) IN
                  ('facebook-ads','facebook-ads-sitelink','facebook','fb','ig',
                   'instagram','meta') THEN 'meta'
             WHEN lower(coalesce(nullif(l.utm_source,''),
                                 nullif(l.survey_responses->>'Source',''), '')) IN
                  ('google-ads','google','googleads','gclid','youtube','youtube-bio')
                  THEN 'google'
             WHEN coalesce(nullif(l.utm_source,''),
                           nullif(l.survey_responses->>'Source',''), '') = '' THEN NULL
             ELSE 'outros'
           END AS canal,
           lower(coalesce(nullif(l.utm_source,''),
                          nullif(l.survey_responses->>'Source',''))) AS utm_source,
           nullif(l.utm_campaign,'') AS utm_campaign,
           nullif(l.utm_content,'')  AS utm_content,
           nullif(l.utm_term,'')     AS utm_term,
           {cols_pesquisa},
           (comp.email IS NOT NULL) AS comprou
      FROM analytics.leads l
      LEFT JOIN (SELECT DISTINCT lower(email) AS email FROM analytics.sales
                  WHERE email IS NOT NULL) comp
             ON comp.email = lower(l.email)
      LEFT JOIN analytics.launch_calendar cal
             ON cal.client_id = l.client_id
            AND l.capturado_em::date BETWEEN cal.cap_start AND cal.cap_end
     WHERE l.source = 'leads_treino_prod'
       AND l.capturado_em >= '{ANO}-01-01'
       AND l.capturado_em <  '{ANO + 1}-01-01'
       AND l.email IS NOT NULL AND l.email <> ''
     ORDER BY l.event_id, cal.cap_start DESC
    """


def colunas_da_tabela():
    base = [("lead_id", "text"), ("capturado_em", "timestamp"), ("lf", "text"),
            ("canal", "text"), ("utm_source", "text"), ("utm_campaign", "text"),
            ("utm_content", "text"), ("utm_term", "text")]
    base += [(alias, "text") for _, alias in PESQUISA]
    base += [("comprou", "boolean")]
    return base


def ddl_tabela() -> str:
    cols = ",\n      ".join(f"{n} {t}" for n, t in colunas_da_tabela())
    return f"CREATE TABLE {SCHEMA}.{TABELA} (\n      {cols}\n    )"


# ── ações ────────────────────────────────────────────────────────────────────

def dry_run():
    c = origem_leitura()
    try:
        n = c.run(f"SELECT count(*) FROM ({sql_fonte()}) q", sal=sal())[0][0]
        print(f"  linhas que a entrega teria: {n:,}")
        for r in c.run(f"""SELECT to_char(capturado_em,'YYYY-MM') m, count(*),
                           round(100.0*count(canal)/count(*),1) canal_pct,
                           round(100.0*count(lf)/count(*),1) lf_pct,
                           sum(CASE WHEN comprou THEN 1 ELSE 0 END) compradores
                           FROM ({sql_fonte()}) q GROUP BY 1 ORDER BY 1""", sal=sal()):
            print(f"    {r[0]}  n={r[1]:>6,}  canal={r[2]:>5}%  lf={r[3]:>5}%  compradores={r[4]:>4}")
        print(f"\n  colunas da entrega ({len(colunas_da_tabela())}):")
        print("   ", ", ".join(n for n, _ in colunas_da_tabela()))
    finally:
        c.close()


def provisionar(senha_role: str):
    adm = _admin()
    # 1) banco separado
    c = conectar("postgres", adm, "postgres")
    try:
        existe = c.run(f"SELECT 1 FROM pg_database WHERE datname='{BANCO}'")
        if existe:
            print(f"  banco {BANCO}: já existe")
        else:
            c.run(f"CREATE DATABASE {BANCO}")
            print(f"  banco {BANCO}: criado")
        # role sem poder nenhum. NOINHERIT para não herdar de grupo por acidente.
        # DDL do Postgres não aceita parâmetro ligado, então a senha entra no texto
        # do comando. Escapada dobrando a aspa simples, que é a regra do literal SQL.
        lit = "'" + senha_role.replace("'", "''") + "'"
        atributos = ("LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
                     f"NOREPLICATION PASSWORD {lit}")
        tem = c.run(f"SELECT 1 FROM pg_roles WHERE rolname='{ROLE}'")
        if tem:
            c.run(f"ALTER ROLE {ROLE} WITH {atributos}")
            print(f"  role {ROLE}: já existia, atributos e senha reaplicados")
        else:
            c.run(f"CREATE ROLE {ROLE} WITH {atributos}")
            print(f"  role {ROLE}: criada")
        # Por ACL default, PUBLIC conecta em banco novo. Fecha antes de povoar.
        c.run(f"REVOKE ALL ON DATABASE {BANCO} FROM PUBLIC")
        c.run(f"GRANT CONNECT ON DATABASE {BANCO} TO {ROLE}")
        print(f"  banco {BANCO}: PUBLIC revogado, CONNECT só para {ROLE}")
    finally:
        c.close()

    # 2) dentro do banco novo
    c = conectar("postgres", adm, BANCO)
    try:
        c.run(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        # O schema `public` do banco novo também aceita CREATE por default no PG15
        # em bancos criados a partir do template1 antigo. Fecha.
        c.run("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        c.run(f"DROP TABLE IF EXISTS {SCHEMA}.{TABELA}")
        c.run(ddl_tabela())
        c.run(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {ROLE}")
        c.run(f"GRANT SELECT ON {SCHEMA}.{TABELA} TO {ROLE}")
        # Sem DEFAULT PRIVILEGES: tabela nova neste schema NÃO fica visível
        # automaticamente. Conceder é ato consciente, um por um.
        print(f"  {SCHEMA}.{TABELA}: criada, SELECT concedido só a {ROLE}")
    finally:
        c.close()


def refresh():
    """Recarrega a tabela da entrega. Troca em transação: quem estiver lendo
    durante a carga vê a versão anterior inteira, nunca um estado pela metade."""
    origem = origem_leitura()
    try:
        linhas = origem.run(sql_fonte(), sal=sal())
    finally:
        origem.close()
    print(f"  lidas {len(linhas):,} linhas da origem")

    adm = _admin()
    destino = conectar("postgres", adm, BANCO)
    try:
        cols = [n for n, _ in colunas_da_tabela()]
        destino.run("BEGIN")
        destino.run(f"DROP TABLE IF EXISTS {SCHEMA}.{TABELA}_novo")
        destino.run(ddl_tabela().replace(f"{SCHEMA}.{TABELA}", f"{SCHEMA}.{TABELA}_novo"))
        lote = 500
        for i in range(0, len(linhas), lote):
            pedaco = linhas[i:i + lote]
            vals, params = [], {}
            for j, linha in enumerate(pedaco):
                marcas = []
                for k, v in enumerate(linha):
                    nome = f"p{j}_{k}"
                    params[nome] = v
                    marcas.append(f":{nome}")
                vals.append("(" + ",".join(marcas) + ")")
            destino.run(
                f"INSERT INTO {SCHEMA}.{TABELA}_novo ({','.join(cols)}) VALUES "
                + ",".join(vals), **params)
        destino.run(f"DROP TABLE IF EXISTS {SCHEMA}.{TABELA}")
        destino.run(f"ALTER TABLE {SCHEMA}.{TABELA}_novo RENAME TO {TABELA}")
        destino.run(f"GRANT SELECT ON {SCHEMA}.{TABELA} TO {ROLE}")
        destino.run(f"CREATE INDEX ON {SCHEMA}.{TABELA} (capturado_em)")
        destino.run(f"CREATE INDEX ON {SCHEMA}.{TABELA} (lf)")
        destino.run("COMMIT")
        n = destino.run(f"SELECT count(*) FROM {SCHEMA}.{TABELA}")[0][0]
        print(f"  {SCHEMA}.{TABELA}: {n:,} linhas, índices criados, SELECT reconcedido")
    except Exception:
        destino.run("ROLLBACK")
        raise
    finally:
        destino.close()


def aceitacao(senha_role: str) -> bool:
    """Prova, conectando COMO o usuário da entrega, que ele não alcança mais nada.

    Este teste é a condição de saída: nenhuma credencial sai daqui antes de ele
    passar. Verificar depois de entregar não é verificar.
    """
    ok = True
    print("  1. lê a tabela da entrega?")
    c = conectar(ROLE, senha_role, BANCO)
    try:
        n = c.run(f"SELECT count(*) FROM {SCHEMA}.{TABELA}")[0][0]
        print(f"     sim, {n:,} linhas. (esperado)")
    finally:
        c.close()

    print("  2. consegue ESCREVER na tabela da entrega?")
    c = conectar(ROLE, senha_role, BANCO)
    try:
        c.run(f"DELETE FROM {SCHEMA}.{TABELA} WHERE false")
        print("     CONSEGUIU. FALHA.")
        ok = False
    except Exception as e:
        print(f"     não: {'permission denied' if 'permission denied' in str(e) else str(e)[:60]}")
    finally:
        c.close()

    print("  3. alcança as tabelas sensíveis?")
    for banco, tab in PROIBIDAS:
        try:
            c = conectar(ROLE, senha_role, banco, timeout=30)
            try:
                c.run(f"SELECT 1 FROM {tab} LIMIT 1")
                print(f"     {banco}.{tab}: LEU. FALHA GRAVE.")
                ok = False
            except Exception as e:
                m = str(e)
                motivo = "permission denied" if "permission denied" in m else m[:50]
                print(f"     {banco}.{tab}: bloqueado ({motivo})")
            finally:
                c.close()
        except Exception as e:
            m = str(e)
            motivo = "não conecta no banco" if "permission denied" in m or "28000" in m else m[:50]
            print(f"     {banco}.{tab}: bloqueado ({motivo})")

    print("  4. o catálogo do banco da entrega menciona score ou decil?")
    c = conectar(ROLE, senha_role, BANCO)
    try:
        r = c.run("""SELECT count(*) FROM information_schema.columns
                     WHERE column_name ~* '(score|decil|decile)'""")[0][0]
        print(f"     {r} colunas. {'(esperado: 0)' if r == 0 else 'FALHA'}")
        ok = ok and r == 0
        t = c.run("""SELECT table_schema||'.'||table_name FROM information_schema.tables
                     WHERE table_schema NOT IN ('pg_catalog','information_schema')""")
        print(f"     tabelas visíveis no catálogo: {[x[0] for x in t]}")
    finally:
        c.close()
    return ok


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(_V2 / ".env")

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--provisionar", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--aceitacao", action="store_true")
    a = ap.parse_args()

    senha_role = os.environ.get("DASH_ZANELATO_PASSWORD", "")
    if (a.provisionar or a.aceitacao) and not senha_role:
        print("ERRO: exporte DASH_ZANELATO_PASSWORD.", file=sys.stderr)
        return 2

    if a.dry_run:
        dry_run()
    if a.provisionar:
        provisionar(senha_role)
    if a.refresh:
        refresh()
    if a.aceitacao:
        return 0 if aceitacao(senha_role) else 1
    if not any(vars(a).values()):
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
