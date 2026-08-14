"""
Trava as DUAS metades do conserto de paridade do monitoramento (13/08/2026).

O QUE ACONTECIA. `unify_medium` tem dois modos e escolhe entre eles olhando se o
chamador passou `artifacts`. A produção passava; o monitoramento não. Resultado:
o mesmo lead recebia tratamento diferente conforme o serviço, e o daily-check
passou 4 dias reportando "grupo Medium todo-zerado em 81,3%" enquanto o scoring
mandava tudo para 'Outros'. Diagnóstico errado entregue ao operador.

A ARMADILHA. Consertar só isso APAGA o alarme que pegou o bug. Com a whitelist do
modelo, valor desconhecido vira 'Outros', que é categoria de treino — então o
detector de vocabulário fica mudo justamente quando o cliente muda a
nomenclatura. Por isso a detecção passou a ler o valor CRU, guardado antes da
tradução.

Os dois testes abaixo são irmãos de propósito: um garante a fidelidade, o outro
garante que a fidelidade não cegou o alarme.
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

from src.core.client_config import (  # noqa: E402
    ClientConfig,
    active_model_run_id,
    active_model_yaml_path,
    medium_artifacts,
)
from src.core.medium import unify_medium  # noqa: E402
from src.monitoring.data_quality import check_category_drift  # noqa: E402

WHITELIST_ABR28 = [
    'Aberto',
    'Linguagem_programacao',
    'Lookalike_1_Cadastrados_DEV_2_0_Interesse_Ci_ncia_da_Computa_o',
    'Lookalike_2pct_Cadastrados',
    'dgen',
]

# Vocabulário do treino inclui 'Outros' — é exatamente por isso que traduzir
# antes de detectar apaga o alarme.
CATEGORIAS_TREINO = {'Medium': WHITELIST_ABR28 + ['Outros']}

# Um valor que o cliente inventou depois do treino, no formato que a Meta passou
# a mandar em 10/08/2026.
VOCABULARIO_NOVO = '[ADVTG_PUBLICO_INEDITO]DEV-AD9999-vid'


def _medium_com_whitelist():
    cfg = ClientConfig.from_yaml(str(ROOT / 'configs' / 'clients' / 'devclub.yaml'))
    medium = deepcopy(cfg.medium)
    medium.valid_categories = WHITELIST_ABR28
    # Sem pattern_mappings: aqui o assunto é vocabulário DESCONHECIDO, não o
    # mapeamento já ensinado.
    medium.pattern_mappings = None
    return medium


def test_traducao_apaga_a_evidencia_de_vocabulario_novo():
    """Documenta o ponto cego: sem valor cru, o detector não tem o que ver.

    Este teste não descreve um comportamento desejado — ele fixa a razão de o
    parâmetro `valores_crus` existir. Se um dia ele passar a falhar, é porque
    alguém mudou o clamp e a proteção pode ser revista.
    """
    df = pd.DataFrame({'Medium': [VOCABULARIO_NOVO] * 10})
    unificado = unify_medium(df.copy(), _medium_com_whitelist())

    assert list(unificado['Medium'].unique()) == ['Outros']
    # 'Outros' é categoria de treino → nenhum alerta.
    assert check_category_drift(unificado, CATEGORIAS_TREINO) == []


def test_valor_cru_preserva_o_alarme_de_vocabulario():
    """Com o valor cru, a mudança de nomenclatura continua gritando."""
    df = pd.DataFrame({'Medium': [VOCABULARIO_NOVO] * 10})
    cru = df['Medium'].copy()
    unificado = unify_medium(df.copy(), _medium_com_whitelist())

    alertas = check_category_drift(unificado, CATEGORIAS_TREINO,
                                   valores_crus={'Medium': cru})

    assert len(alertas) == 1, "a mudança de vocabulário do cliente tem que gerar alerta"
    assert alertas[0]['column'] == 'Medium'
    assert VOCABULARIO_NOVO in alertas[0].get('new_categories', [])
    assert alertas[0].get('percentage') == 100.0


def test_valor_cru_nao_inventa_alerta_quando_vocabulario_e_conhecido():
    """Guard contra falso positivo: valor cru já conhecido não vira alerta."""
    df = pd.DataFrame({'Medium': ['Aberto'] * 5 + ['dgen'] * 5})
    cru = df['Medium'].copy()
    unificado = unify_medium(df.copy(), _medium_com_whitelist())

    assert check_category_drift(unificado, CATEGORIAS_TREINO,
                                valores_crus={'Medium': cru}) == []


def test_resolvedor_do_modelo_ativo_aponta_pro_yaml_real():
    """`medium_artifacts` é o que faz o monitoramento entrar no modo da produção.

    Se ele devolver None, o `unify_medium` cai calado no modo de frequência e a
    divergência de 10/08/2026 volta — por isso o teste exige o dict montado.
    """
    assert active_model_yaml_path('devclub') is not None
    run_id = active_model_run_id('devclub')
    assert run_id, "sem run_id o monitoramento não consegue pedir a whitelist"
    assert medium_artifacts('devclub') == {'mlflow_run_id': run_id}


def test_resolvedor_devolve_none_para_cliente_inexistente():
    """Cliente sem yaml devolve None em vez de explodir — o chamador decide."""
    assert active_model_yaml_path('cliente-que-nao-existe') is None
    assert active_model_run_id('cliente-que-nao-existe') is None
    assert medium_artifacts('cliente-que-nao-existe') is None
