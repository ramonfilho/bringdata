"""Retrato do conjunto de treino, preso ao run do MLflow que ele gerou.

POR QUE ISTO EXISTE
===================
Até hoje, quando um modelo se comportava mal, não dava para saber COM O QUE ele foi
treinado. O universo de treino (`analytics.leads`) é uma tabela VIVA: o job diário
reescreve os leads dos últimos 7 dias, e a reconstrução total já rodou pelo menos uma
vez (30/06/2026). Nada disso é errado — é o comportamento certo para uma tabela
operacional. O problema é que ela não serve de memória.

O que existia antes e por que não bastava:

- `leads_provenance.first_seen_at` diz QUAIS linhas existiam numa data. Não diz o que
  elas continham. Uma linha reescrita hoje carrega os valores de hoje.
- Backup do Cloud SQL: foto diária, 30 dias de retenção. Resolve o mês corrente, não
  um modelo de três meses atrás.
- `--export-matched-dataset`: exporta e ENCERRA o treino. É ferramenta de análise, não
  de registro — quem treina de verdade nunca passa essa flag.

Resultado prático: `jul_24` tem `git_dirty=true` no run e conjunto irrecuperável. Não
dá para responder "o modelo piorou porque o dado mudou ou porque o código mudou?".

O QUE ESTE MÓDULO GRAVA
=======================
Duas coisas, com propósitos diferentes:

1. **manifesto** (KB) — contagem de linhas e colunas, intervalo de datas, positivos,
   lista de colunas e um hash determinístico do conteúdo. Barato, sempre. Serve para
   responder RÁPIDO "o conjunto mudou entre dois treinos?" sem baixar nada.
2. **parquet** (dezenas de MB) — o conjunto inteiro, antes de feature engineering e
   encoding. É o que permite REPRODUZIR, não só detectar mudança.

Por que o conjunto PRÉ feature engineering, e não a matriz final: a matriz final é
ilegível (colunas encodadas) e depende da versão do código de encoding, que o
`git_commit` do run já registra. O pré-FE é o dado como veio do mundo, e com ele mais
o commit dá para refazer o resto. Guardar os dois seria duplicar informação.

O hash é do CONTEÚDO, não do arquivo: parquet não é byte-a-byte determinístico
(metadados, ordem de row groups), então dois dumps do mesmo dado dariam hashes
diferentes e o manifesto viraria ruído.

POR QUE UM DEPÓSITO DE MÓDULO
=============================
O conjunto fica pronto em `train_pipeline`, mas o run do MLflow só abre depois, lá
dentro de `training_model`. As duas alternativas eram piores: passar o dataset por
parâmetro obrigaria a atravessar uma função que já tem mais de 40 argumentos, e abrir
o run mais cedo mudaria o ciclo de vida do run por um motivo acessório. O depósito
aqui é explícito, tem um nome, e quem lê `guardar()` acha `registrar_no_mlflow()`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

# Depósito entre a montagem do conjunto e a abertura do run. Ver o docstring.
_PENDENTE: dict | None = None

ARQUIVO_PARQUET = "conjunto_de_treino.parquet"
ARQUIVO_MANIFESTO = "conjunto_de_treino.json"


def _hash_conteudo(df) -> str:
    """Hash determinístico do CONTEÚDO, estável entre execuções.

    `pd.util.hash_pandas_object` é estável para os mesmos valores; somo os hashes por
    linha de forma comutativa para que a ORDEM das linhas não mude o resultado. Ordem
    de linha não é informação aqui: o mesmo conjunto embaralhado é o mesmo conjunto.
    A lista de colunas entra à parte, essa sim ordenada, porque ordem de coluna é
    contrato com o encoding.
    """
    import pandas as pd
    try:
        h = pd.util.hash_pandas_object(df, index=False)
        corpo = int(h.astype("uint64").sum() % (2 ** 64))
    except Exception as e:  # dtypes exóticos não devem derrubar o treino
        logger.warning(f"[retrato] hash do conteúdo falhou ({str(e)[:80]}); usando shape")
        corpo = 0
    cols = "|".join(map(str, df.columns))
    return hashlib.sha256(f"{corpo}:{cols}".encode()).hexdigest()[:32]


def manifesto(df, *, coluna_data: str = "Data", coluna_alvo: str = "target",
              extra: dict | None = None) -> dict:
    """Ficha do conjunto: barata, sempre gravada, legível sem baixar o parquet."""
    import pandas as pd
    m: dict = {
        "linhas": int(len(df)),
        "colunas": int(df.shape[1]),
        "hash_conteudo": _hash_conteudo(df),
        "nomes_das_colunas": [str(c) for c in df.columns],
    }
    if coluna_alvo in df.columns:
        try:
            m["positivos"] = int(pd.to_numeric(df[coluna_alvo], errors="coerce").fillna(0).sum())
            m["taxa_de_positivos"] = round(m["positivos"] / max(len(df), 1), 6)
        except Exception:
            pass
    if coluna_data in df.columns:
        try:
            d = pd.to_datetime(df[coluna_data], errors="coerce").dropna()
            if len(d):
                m["data_min"] = str(d.min())
                m["data_max"] = str(d.max())
        except Exception:
            pass
    if extra:
        m.update(extra)
    return m


def guardar(df, *, extra: dict | None = None) -> dict:
    """Fotografa o conjunto e deixa pronto para o run que ainda vai abrir.

    Escreve o parquet num temporário AGORA, e não no momento de logar, porque o
    DataFrame pode ser mutado (ou liberado) entre este ponto e a abertura do run —
    fotografar tarde fotografaria outra coisa.

    Nunca derruba o treino: um retrato é registro, não pré-requisito. Se falhar,
    reclama alto no log e o treino segue. O contrário (perder um treino de horas
    porque o dump falhou) seria uma troca ruim.
    """
    global _PENDENTE
    try:
        m = manifesto(df, extra=extra)
        caminho = os.path.join(tempfile.mkdtemp(prefix="retrato_treino_"), ARQUIVO_PARQUET)
        copia = df.copy()
        # Coluna `object` em pandas aceita tipos misturados (str + int + None) que o
        # parquet recusa. Virar string preserva o valor para leitura e análise.
        for c in copia.select_dtypes(include="object").columns:
            copia[c] = copia[c].astype("string")
        copia.to_parquet(caminho, index=False)
        m["parquet_bytes"] = os.path.getsize(caminho)
        _PENDENTE = {"manifesto": m, "parquet": caminho}
        logger.info(f"[retrato] conjunto fotografado: {m['linhas']:,} linhas x "
                    f"{m['colunas']} colunas, hash {m['hash_conteudo'][:12]}")
        return m
    except Exception as e:
        logger.warning(f"[retrato] NÃO consegui fotografar o conjunto: {str(e)[:200]}")
        logger.warning("[retrato] o treino segue, mas este modelo ficará sem conjunto "
                       "guardado — não será reproduzível.")
        _PENDENTE = None
        return {}


def registrar_no_mlflow(mlflow_mod=None) -> bool:
    """Anexa o retrato ao run ABERTO. Chamar de dentro do `with mlflow.start_run()`.

    Devolve True se anexou. Silencioso e inofensivo se não houver retrato guardado
    (é o caso de quem chama o pipeline sem passar pela montagem do conjunto, como
    alguns testes).
    """
    global _PENDENTE
    if not _PENDENTE:
        return False
    try:
        if mlflow_mod is None:
            import mlflow as mlflow_mod
        if mlflow_mod.active_run() is None:
            logger.warning("[retrato] nenhum run aberto; o retrato não foi anexado.")
            return False
        mlflow_mod.log_dict(_PENDENTE["manifesto"], ARQUIVO_MANIFESTO)
        mlflow_mod.log_artifact(_PENDENTE["parquet"])
        # Como PARÂMETRO também: parâmetro é filtrável na busca do MLflow, artefato
        # não. É assim que se acha "todos os runs treinados no mesmo conjunto".
        mlflow_mod.log_param("dataset_hash", _PENDENTE["manifesto"]["hash_conteudo"])
        mlflow_mod.log_param("dataset_linhas", _PENDENTE["manifesto"]["linhas"])
        logger.info(f"[retrato] anexado ao run: {ARQUIVO_PARQUET} "
                    f"({_PENDENTE['manifesto'].get('parquet_bytes', 0) / 1e6:.1f} MB) "
                    f"+ {ARQUIVO_MANIFESTO}")
        return True
    except Exception as e:
        logger.warning(f"[retrato] falhei ao anexar ao MLflow: {str(e)[:200]}")
        return False
    finally:
        _PENDENTE = None


def limpar() -> None:
    """Descarta o retrato pendente. Existe para os testes não vazarem estado entre si."""
    global _PENDENTE
    _PENDENTE = None
