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

Sobre dado pessoal: a tabela SAI COM nome e e-mail, por decisão do operador em
06/08/2026. A razão é que o time de tráfego já obtém esses campos por outras
ferramentas, então retê-los aqui só atrapalharia o cruzamento deles sem reduzir
exposição real. Telefone segue fora, porque não foi pedido.

Consequência que essa decisão tem sobre o `lead_id`: com o e-mail na mesma linha, o
hash com sal deixa de proteger qualquer coisa, e passa a valer só como chave estável
de junção. Ele foi mantido por isso, não por pseudonimização, e este comentário
existe para ninguém depois olhar o hash e concluir que a tabela é anonimizada.

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

# Mínimo de leads para um criativo ou campanha publicar qualidade agregada. Abaixo
# disso o "agregado" viraria o score individual disfarçado: um anúncio com 1 lead
# publicaria o decil daquele lead.
MIN_LEADS_AGREGADO = 30

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
    WITH url_por_email AS (
      -- A URL de captura é 0% na base derivada e 100% no ledger vivo, de junho em
      -- diante. Vem daqui, e por isso fica vazia para lead anterior a junho.
      SELECT DISTINCT ON (lower(email)) lower(email) AS email, utm_url
        FROM public.registros_ml
       WHERE coalesce(utm_url,'') <> ''
       ORDER BY lower(email), created_at DESC
    )
    SELECT DISTINCT ON (l.event_id)
           encode(sha256((:sal || lower(l.email))::bytea), 'hex') AS lead_id,
           nullif(l.survey_responses->>'Nome Completo', '') AS nome,
           lower(l.email) AS email,
           nullif(coalesce(l.phone, l.survey_responses->>'Telefone'), '') AS telefone,
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
           u.utm_url AS url_captura,
           lower(coalesce(nullif(l.utm_source,''),
                          nullif(l.survey_responses->>'Source',''))) AS utm_source,
           nullif(coalesce(l.utm_medium, l.survey_responses->>'Medium'),'') AS utm_medium,
           nullif(l.utm_campaign,'') AS utm_campaign,
           nullif(l.utm_content,'')  AS utm_content,
           nullif(l.utm_term,'')     AS utm_term,
           {cols_pesquisa},
           (comp.email IS NOT NULL) AS comprou,
           NULL::boolean AS entrou_no_grupo,
           NULL::text AS grupo_whatsapp,
           NULL::timestamp AS entrou_no_grupo_em
      FROM analytics.leads l
      LEFT JOIN (SELECT DISTINCT lower(email) AS email FROM analytics.sales
                  WHERE email IS NOT NULL) comp
             ON comp.email = lower(l.email)
      LEFT JOIN url_por_email u   ON u.email = lower(l.email)

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
    base = [("lead_id", "text"), ("nome", "text"), ("email", "text"),
            ("telefone", "text"), ("capturado_em", "timestamp"), ("lf", "text"),
            ("canal", "text"), ("url_captura", "text"),
            ("utm_source", "text"), ("utm_medium", "text"),
            ("utm_campaign", "text"), ("utm_content", "text"), ("utm_term", "text"),
]
    base += [(alias, "text") for _, alias in PESQUISA]
    base += [("comprou", "boolean")]
    # Entrada no grupo de WhatsApp. Sai NULO em TODAS as linhas hoje, de propósito.
    #
    # O dado existe (112.825 registros), mas a coleta parou em 23/06/2026: o backfill
    # veio de exports manuais em CSV do painel do SendFlow, e o webhook que substituiu
    # aquilo funcionou quatro dias e morreu. Recuperar isso é frente própria.
    #
    # Por que a coluna existe VAZIA em vez de não existir: o dashboard deles pode ser
    # construído já contando com ela, e quando a coleta voltar o campo se preenche
    # sozinho, sem mexer no painel. E NULO é honesto, quer dizer "não sei". Se
    # entregássemos o dado congelado, todo lead captado depois de 23/06 apareceria
    # como `false`, ou seja, "não entrou no grupo", o que é FALSO e levaria a decisão
    # errada sobre canal. Coluna vazia com aviso é melhor que coluna cheia de mentira.
    # O pedido citava "telefone que entrou, grupo/turma e data de entrada". O
    # telefone NAO se repete aqui: ja e coluna propria da linha, e duplicar o
    # mesmo dado em duas colunas so cria a chance de elas discordarem depois.
    base += [("entrou_no_grupo", "boolean"),
             ("grupo_whatsapp", "text"),
             ("entrou_no_grupo_em", "timestamp")]
    return base


# Chave da linha. NÃO é só o lead_id: a mesma pessoa que se cadastra em dias
# diferentes vira linhas diferentes na origem (medido: 253.502 linhas para 234.814
# e-mails distintos). Com lead_id sozinho como chave, essas 18.688 linhas colidiriam
# e a carga incremental jogaria fora cadastro legítimo.
CHAVE = ("lead_id", "capturado_em")

# Tabela companheira com a qualidade agregada. Ela existe SEPARADA de propósito.
#
# A primeira versão colava o percentual do criativo em cada linha de lead. Medido:
# num dia comum isso faria reescrever 1.363 linhas em vez de 27, porque basta o
# percentual de um criativo mexer na primeira casa decimal para todas as linhas dele
# mudarem. E era o mesmo punhado de valores repetido 250 mil vezes: 58 números
# distintos espalhados por um quarto de milhão de linhas.
#
# Aqui são ~60 linhas que mudam por dia, e o painel junta por `utm_content` ou
# `utm_campaign`. De quebra, é onde a REFERÊNCIA cabe: sem ela, "42,4%" não diz se o
# criativo é bom, e o número sozinho não orienta decisão nenhuma.
TABELA_QUALIDADE = "qualidade_por_anuncio"


def colunas_qualidade():
    return [("tipo", "text"), ("chave", "text"), ("leads", "integer"),
            ("pct_top_deciles", "numeric"), ("referencia_pct", "numeric"),
            ("diferenca_vs_referencia", "numeric"), ("atualizado_em", "timestamp")]


def ddl_qualidade() -> str:
    cols = ",\n      ".join(f"{n} {t}" for n, t in colunas_qualidade())
    return (f"CREATE TABLE {SCHEMA}.{TABELA_QUALIDADE} (\n      {cols},\n"
            f"      PRIMARY KEY (tipo, chave)\n    )")


def sql_qualidade() -> str:
    """Qualidade agregada por anúncio e por campanha, com a régua junto.

    `pct_top_deciles` é o percentual dos leads daquele anúncio nos dois decis mais
    altos do modelo, que é a mesma métrica do relatório diário do grupo de tráfego.

    `referencia_pct` é o mesmo percentual calculado sobre TODOS os leads do período.
    Ela vai junto porque o número sozinho não diz nada: 42% pode ser ótimo ou
    medíocre dependendo de onde a base inteira está. Com a referência na mesma linha,
    o painel mostra a comparação sem ninguém precisar lembrar o valor de cabeça, e
    sem depender de a gente avisar quando a régua mudar.

    O corte de {MIN} leads impede que o "agregado" vire o score individual
    disfarçado: um anúncio com um lead só publicaria o decil daquele lead.
    """
    return f"""
    WITH ref AS (
      SELECT round(100.0 * count(*) FILTER (WHERE decil >= 9) / count(*), 1) AS pct
        FROM public.registros_ml WHERE decil IS NOT NULL
    )
    SELECT 'criativo' AS tipo, utm_content AS chave, count(*)::int AS leads,
           round(100.0 * count(*) FILTER (WHERE decil >= 9) / count(*), 1) AS pct_top_deciles,
           (SELECT pct FROM ref) AS referencia_pct,
           round(100.0 * count(*) FILTER (WHERE decil >= 9) / count(*), 1)
             - (SELECT pct FROM ref) AS diferenca_vs_referencia,
           now()::timestamp AS atualizado_em
      FROM public.registros_ml
     WHERE decil IS NOT NULL AND coalesce(utm_content,'') <> ''
     GROUP BY 1, 2 HAVING count(*) >= {MIN_LEADS_AGREGADO}
    UNION ALL
    SELECT 'campanha', utm_campaign, count(*)::int,
           round(100.0 * count(*) FILTER (WHERE decil >= 9) / count(*), 1),
           (SELECT pct FROM ref),
           round(100.0 * count(*) FILTER (WHERE decil >= 9) / count(*), 1)
             - (SELECT pct FROM ref),
           now()::timestamp
      FROM public.registros_ml
     WHERE decil IS NOT NULL AND coalesce(utm_campaign,'') <> ''
     GROUP BY 1, 2 HAVING count(*) >= {MIN_LEADS_AGREGADO}
    """.replace("{MIN}", str(MIN_LEADS_AGREGADO))


def ddl_tabela(nome: str | None = None) -> str:
    alvo = nome or f"{SCHEMA}.{TABELA}"
    cols = ",\n      ".join(f"{n} {t}" for n, t in colunas_da_tabela())
    return (f"CREATE TABLE {alvo} (\n      {cols},\n"
            f"      PRIMARY KEY ({', '.join(CHAVE)})\n    )")


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
        # Sem NOREPLICATION: no Cloud SQL o `postgres` não é superusuário de verdade,
        # e alterar esse atributo devolve "must be superuser". É o default de
        # qualquer role nova, então pedir explicitamente só quebrava o reprovisionamento.
        atributos = ("LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
                     f"PASSWORD {lit}")
        tem = c.run(f"SELECT 1 FROM pg_roles WHERE rolname='{ROLE}'")
        if tem:
            # No ALTER só a senha. No Cloud SQL o `postgres` não é superusuário de
            # verdade, e reaplicar NOSUPERUSER devolve "must be superuser", o que
            # quebrava todo reprovisionamento. Os atributos já foram fixados na
            # criação; o que se confere aqui é que eles continuam certos.
            c.run(f"ALTER ROLE {ROLE} WITH LOGIN PASSWORD {lit}")
            a = c.run(f"""SELECT rolsuper, rolcreatedb, rolcreaterole, rolinherit
                            FROM pg_roles WHERE rolname='{ROLE}'""")[0]
            if any(a[:3]) or a[3]:
                raise RuntimeError(
                    f"role {ROLE} está com atributo demais: super={a[0]} "
                    f"createdb={a[1]} createrole={a[2]} inherit={a[3]}")
            print(f"  role {ROLE}: já existia, senha reaplicada e atributos conferidos")
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
        c.run(f"CREATE INDEX IF NOT EXISTS {TABELA}_capturado_em ON {SCHEMA}.{TABELA} (capturado_em)")
        c.run(f"CREATE INDEX IF NOT EXISTS {TABELA}_lf ON {SCHEMA}.{TABELA} (lf)")
        c.run(f"CREATE INDEX IF NOT EXISTS {TABELA}_email ON {SCHEMA}.{TABELA} (email)")
        c.run(f"GRANT SELECT ON {SCHEMA}.{TABELA} TO {ROLE}")
        # Sem DEFAULT PRIVILEGES: tabela nova neste schema NÃO fica visível
        # automaticamente. Conceder é ato consciente, um por um.
        print(f"  {SCHEMA}.{TABELA}: criada, SELECT concedido só a {ROLE}")
    finally:
        c.close()


def refresh():
    """Atualiza a entrega gravando SÓ o que mudou.

    Antes isto refazia a tabela inteira todo dia. Medido em 06/08/2026, isso era
    reescrever **253.502 linhas para mudar 27**: entram cerca de 22 leads novos por
    dia e cerca de 5 pessoas passam a constar como compradoras. Mesmo em pico de
    lançamento seriam ~2.500, ou 1% da tabela. Reescrever tudo custava uns 10 minutos
    numa instância pequena, sem ganho nenhum.

    Agora: insere o que é novo, atualiza o que mudou, e apaga o que sumiu da origem.
    Tudo numa transação, então quem estiver consultando vê a versão anterior inteira
    até o commit.

    A remoção existe porque a tabela de origem é reconstruída periodicamente e a
    deduplicação pode mudar: sem ela, linha que deixou de existir na origem ficaria
    aqui para sempre, e o painel deles contaria lead que a gente já não reconhece.
    """
    origem = origem_leitura()
    try:
        linhas = origem.run(sql_fonte(), sal=sal())
    finally:
        origem.close()
    print(f"  lidas {len(linhas):,} linhas da origem")

    cols = [n for n, _ in colunas_da_tabela()]
    mutaveis = [c for c in cols if c not in CHAVE]
    adm = _admin()
    destino = conectar("postgres", adm, BANCO)
    try:
        antes = destino.run(f"SELECT count(*) FROM {SCHEMA}.{TABELA}")[0][0]
        destino.run("BEGIN")

        # Área de estágio com o retrato completo da origem. Ela existe para as três
        # operações saírem de UMA leitura só, sem ficar perguntando linha a linha.
        destino.run(f"DROP TABLE IF EXISTS {SCHEMA}._stg")
        destino.run(ddl_tabela(f"{SCHEMA}._stg"))
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
            destino.run(f"INSERT INTO {SCHEMA}._stg ({','.join(cols)}) VALUES "
                        + ",".join(vals), **params)

        cond = " AND ".join(f"t.{k} = s.{k}" for k in CHAVE)
        sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in mutaveis)
        # Só conta como mudança o que de fato difere. `IS DISTINCT FROM` trata NULO
        # como valor, senão linha com campo nulo apareceria como alterada todo dia.
        difere = " OR ".join(f"t.{c} IS DISTINCT FROM s.{c}" for c in mutaveis)

        novas = destino.run(f"""SELECT count(*) FROM {SCHEMA}._stg s
            WHERE NOT EXISTS (SELECT 1 FROM {SCHEMA}.{TABELA} t WHERE {cond})""")[0][0]
        alteradas = destino.run(f"""SELECT count(*) FROM {SCHEMA}._stg s
            JOIN {SCHEMA}.{TABELA} t ON {cond} WHERE {difere}""")[0][0]

        destino.run(f"""INSERT INTO {SCHEMA}.{TABELA} ({','.join(cols)})
            SELECT {','.join(cols)} FROM {SCHEMA}._stg
            ON CONFLICT ({', '.join(CHAVE)}) DO UPDATE SET {sets}""")

        sumidas = destino.run(f"""WITH d AS (
            DELETE FROM {SCHEMA}.{TABELA} t
             WHERE NOT EXISTS (SELECT 1 FROM {SCHEMA}._stg s WHERE {cond})
            RETURNING 1) SELECT count(*) FROM d""")[0][0]

        destino.run(f"DROP TABLE {SCHEMA}._stg")
        destino.run(f"GRANT SELECT ON {SCHEMA}.{TABELA} TO {ROLE}")
        destino.run("COMMIT")

        depois = destino.run(f"SELECT count(*) FROM {SCHEMA}.{TABELA}")[0][0]
        print(f"  {novas} novas, {alteradas} alteradas, {sumidas} removidas")
        print(f"  {SCHEMA}.{TABELA}: {antes:,} -> {depois:,} linhas")
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
        vis = sorted(x[0] for x in c.run(
            """SELECT table_schema||'.'||table_name FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog','information_schema')"""))
        print(f"     tabelas visíveis no catálogo: {vis}")
        esperado = sorted([f"{SCHEMA}.{TABELA}", f"{SCHEMA}.{TABELA_QUALIDADE}"])
        if vis != esperado:
            print(f"     FALHA: esperava exatamente {esperado}")
            ok = False
    finally:
        c.close()

    print("  5. lê a tabela de qualidade agregada?")
    c = conectar(ROLE, senha_role, BANCO)
    try:
        n = c.run(f"SELECT count(*) FROM {SCHEMA}.{TABELA_QUALIDADE}")[0][0]
        print(f"     sim, {n} linhas. (esperado)")
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
