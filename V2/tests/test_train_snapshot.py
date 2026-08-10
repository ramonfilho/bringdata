"""Trava o retrato do conjunto de treino.

O que estes testes protegem, em uma frase: que todo modelo treinado leve junto o
conjunto que o gerou, e que tentar guardar esse conjunto NUNCA derrube um treino.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core import train_snapshot as ts


@pytest.fixture(autouse=True)
def _limpa():
    """Sem isto, o retrato de um teste vaza para o seguinte.

    Não é zelo teórico: nesta mesma suíte, em 08/08/2026, um arquivo que trocava
    atributos de módulo sem restaurar fez três testes de outro arquivo quebrarem só
    quando a suíte rodava inteira — e passarem sozinhos, que é o pior sintoma
    possível, porque parece instabilidade e não vazamento.
    """
    ts.limpar()
    yield
    ts.limpar()


def _df(n=5, alvo=(1, 0, 0, 1, 0)):
    return pd.DataFrame({
        "E-mail": [f"p{i}@x.com" for i in range(n)],
        "Data": pd.date_range("2026-01-01", periods=n, freq="D"),
        "idade": ["25 34 anos"] * n,
        "target": list(alvo)[:n],
    })


class _MLflowFalso:
    """Dublê do MLflow. Guarda o que foi registrado para o teste conferir."""
    def __init__(self, com_run=True):
        self._run = object() if com_run else None
        self.dicts, self.artifacts, self.params = {}, [], {}

    def active_run(self):
        return self._run

    def log_dict(self, d, nome):
        self.dicts[nome] = d

    def log_artifact(self, caminho):
        self.artifacts.append(caminho)

    def log_param(self, k, v):
        self.params[k] = v


def test_o_conjunto_de_treino_vai_junto_com_o_modelo():
    """É a razão de existir do módulo: sem o conjunto anexo, um modelo que se comporta
    mal não pode ser diagnosticado — a tabela de origem é viva e já mudou."""
    ts.guardar(_df())
    fake = _MLflowFalso()
    assert ts.registrar_no_mlflow(fake) is True
    assert ts.ARQUIVO_MANIFESTO in fake.dicts, 'o manifesto não foi anexado ao run'
    assert any(a.endswith(ts.ARQUIVO_PARQUET) for a in fake.artifacts), (
        'o parquet não foi anexado: sem ele dá para DETECTAR que o conjunto mudou, '
        'mas não para reproduzir o treino')


def test_o_hash_e_parametro_para_dar_para_BUSCAR():
    """Artefato não é filtrável na busca do MLflow; parâmetro é. Sem o hash como
    parâmetro não dá para responder 'quais runs usaram o mesmo conjunto?'."""
    ts.guardar(_df())
    fake = _MLflowFalso()
    ts.registrar_no_mlflow(fake)
    assert 'dataset_hash' in fake.params and 'dataset_linhas' in fake.params
    assert fake.params['dataset_linhas'] == 5


def test_o_hash_muda_quando_o_dado_muda_e_so_quando_muda():
    """A pergunta que o hash responde é 'o conjunto mudou entre dois treinos?'. Se ele
    mudasse à toa, a resposta seria sempre 'sim' e o manifesto viraria ruído."""
    a = ts.manifesto(_df())["hash_conteudo"]
    b = ts.manifesto(_df())["hash_conteudo"]
    assert a == b, 'mesmo conjunto deu hashes diferentes: o hash não serve para nada'

    embaralhado = _df().sample(frac=1, random_state=7)
    assert ts.manifesto(embaralhado)["hash_conteudo"] == a, (
        'a ORDEM das linhas mudou o hash; o mesmo conjunto embaralhado é o mesmo '
        'conjunto, e isto daria falso alarme a cada treino')

    outro = _df()
    outro.loc[0, "idade"] = "35 44 anos"
    assert ts.manifesto(outro)["hash_conteudo"] != a, 'mudou o dado e o hash não mudou'

    coluna_a_mais = _df()
    coluna_a_mais["nova"] = 1
    assert ts.manifesto(coluna_a_mais)["hash_conteudo"] != a, (
        'entrou coluna nova e o hash não mudou — mudança de esquema é exatamente o '
        'que quebra um modelo em produção')


def test_o_manifesto_diz_o_periodo_e_os_positivos():
    """São as duas perguntas que se faz primeiro quando um modelo piora: mudou a
    janela de dados? mudou a proporção de compradores?"""
    m = ts.manifesto(_df())
    assert m["linhas"] == 5 and m["positivos"] == 2
    assert m["data_min"].startswith("2026-01-01") and m["data_max"].startswith("2026-01-05")
    assert "target" in m["nomes_das_colunas"]


def test_falha_ao_fotografar_NAO_derruba_o_treino():
    """Um retrato é registro, não pré-requisito. Perder um treino de horas porque o
    dump falhou seria uma troca ruim."""
    class Quebrado:
        columns = ["x"]
        def copy(self):
            raise RuntimeError("disco cheio")
        def __len__(self):
            return 1
    m = ts.guardar(Quebrado())
    assert m == {}, 'deveria devolver vazio em vez de estourar'


def test_sem_run_aberto_nao_estoura():
    ts.guardar(_df())
    assert ts.registrar_no_mlflow(_MLflowFalso(com_run=False)) is False


def test_sem_retrato_guardado_e_inofensivo():
    """Quem chama o treino por outro caminho (testes, por exemplo) não pode quebrar."""
    fake = _MLflowFalso()
    assert ts.registrar_no_mlflow(fake) is False
    assert not fake.dicts and not fake.artifacts


def test_o_retrato_e_gravado_SEM_flag_no_pipeline():
    """A lição do `--export-matched-dataset`: ele faz um dump parecido, mas é opcional
    E encerra o treino, então nunca rodou num treino de verdade. Foi por isso que os
    modelos antigos ficaram sem conjunto. Se alguém tornar este aqui opcional, o
    problema volta inteiro e em silêncio."""
    fonte = (Path(__file__).resolve().parents[1] / "src" / "train_pipeline.py").read_text()
    i_guardar = fonte.find("_retrato.guardar(")
    assert i_guardar > 0, 'o pipeline deixou de fotografar o conjunto de treino'
    i_export = fonte.find("if export_matched_dataset:")
    assert i_export > i_guardar, (
        'a fotografia caiu para DEPOIS do `--export-matched-dataset`, que dá return; '
        'assim ela nunca roda num treino de verdade')
    trecho = fonte[max(0, i_guardar - 400):i_guardar]
    assert "    if " not in trecho.split("\n")[-1], (
        'a fotografia virou condicional — ela tem que ser incondicional')
