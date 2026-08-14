"""
Trava a reincidência do bug de nomenclatura de campanha de 10/08/2026.

O QUE ACONTECEU. A Meta passou a mandar "[<conjunto>]<nome do anúncio>" no
`utm_medium` em vez do rótulo de público. Com isso a categoria `Aberto` — 49,9%
do dataset de treino — sumiu da produção, e o modelo deixou de aplicar a
penalidade que aprendeu para o público frio. Efeito medido em 2.031 leads
reescoreados pelo pipeline de produção: 54,7% deles ficaram no decil errado,
quase todos INFLADOS; o %D9-D10 reportado foi 22,01% contra 17,77% real; e o
teto de CPL saiu ~13,4% acima do devido durante 4 dias.

POR QUE O TESTE NÃO DEPENDE DE `mlruns/`. `tests/test_medium_artifacts.py` pula
2 dos 4 casos quando o diretório do run não está presente (é o que acontece numa
worktree recém-criada), e um teste que pula é cobertura verde-mas-inerte. Aqui a
whitelist entra explícita por parâmetro, então o teste vale em qualquer máquina.
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

from src.core.client_config import ClientConfig, MediumConfig  # noqa: E402
from src.core.medium import unify_medium  # noqa: E402

# Whitelist do Champion abr_28 (feature_registry.json). Explícita de propósito:
# ver o docstring sobre não depender de mlruns/.
WHITELIST_ABR28 = [
    'Aberto',
    'Linguagem_programacao',
    'Lookalike_1_Cadastrados_DEV_2_0_Interesse_Ci_ncia_da_Computa_o',
    'Lookalike_2pct_Cadastrados',
    'dgen',
]

# Strings REAIS medidas no ledger entre 10/08 e 13/08/2026, com a contagem de
# leads de cada uma. Se o cliente mudar a nomenclatura de novo, é aqui que a
# lista cresce.
MEDIUMS_DE_HOJE = [
    '[ADVTG_ABERTO]',
    '[ADVTG_ABERTO]DEV-AD0160 - VID - CAPTAÇÃO',
    '[ADVTG_ABERTO]DEV-AD0150-vid-captação-V0-estão pagando para você aprender',
    '[ADVTG_ABERTO]DEV-AD0027-vid-captação-V0-DEV',
    '[ADVTG_ABERTO]DEV-AD0156 - VID - CAPTAÇÃO',
    '[ADVTG_ABERTO]DEV-AD0154-vid-captação-V0-sem luz',
    '[ADVTG_ABERTO]DEV-AD0128-vid-captação-V0-papel',
    '[ADVTG_ABERTO]DEV-AD01--VID-Captação-Saiu-na-band ontem-urgente',
    '[ADVTG_ABERTO]DEV-AD0138-vid-captação-V0-PODCAST',
]


def _config_vivo() -> MediumConfig:
    """MediumConfig REAL do devclub, com a whitelist do modelo ativo fixada.

    Lê o yaml de verdade porque o valor do mapeamento mora lá — um teste com
    config sintético passaria mesmo se alguém apagasse a linha do yaml.
    """
    cfg = ClientConfig.from_yaml(str(ROOT / 'configs' / 'clients' / 'devclub.yaml'))
    medium = deepcopy(cfg.medium)
    medium.valid_categories = WHITELIST_ABR28
    return medium


def test_config_vivo_mapeia_as_strings_de_hoje():
    """As 9 formas medidas em produção têm que virar 'Aberto'."""
    medium = _config_vivo()
    assert medium.pattern_mappings, (
        "configs/clients/devclub.yaml perdeu medium.pattern_mappings — "
        "sem ele o público frio volta a ser invisível para o modelo"
    )
    out = unify_medium(pd.DataFrame({'Medium': MEDIUMS_DE_HOJE}), medium)
    assert list(out['Medium']) == ['Aberto'] * len(MEDIUMS_DE_HOJE)


def test_pattern_ancorado_nao_pega_publico_vizinho():
    """'[ADVTG_ABERTO_QUENTE]' é OUTRO público e não pode virar 'Aberto'.

    Sem a âncora `^` e sem o `]` escapado, o padrão pegaria o quente junto e o
    modelo passaria a tratar dois públicos de conversão bem diferente como um só.
    """
    medium = _config_vivo()
    out = unify_medium(
        pd.DataFrame({'Medium': ['[ADVTG_ABERTO_QUENTE]DEV-AD0999', '[ADVTG_ABERTO]x']}),
        medium,
    )
    assert list(out['Medium']) == ['Outros', 'Aberto']


def test_destino_fora_da_whitelist_levanta():
    """Mapear para categoria que o modelo não conhece é PIOR que não mapear.

    O destino inválido vira coluna OHE fora do registry, o alinhamento final a
    descarta, e o lead termina com o grupo Medium todo-zerado — estado que o
    modelo nunca viu no treino. Tem que quebrar alto, não passar batido.
    """
    medium = _config_vivo()
    medium.pattern_mappings = {r'^\[X\]': 'PublicoQueNaoExiste'}
    with pytest.raises(ValueError, match='PublicoQueNaoExiste'):
        unify_medium(pd.DataFrame({'Medium': ['[X]qualquer']}), medium)


def test_igualdade_exata_tem_precedencia_sobre_padrao():
    """`category_mappings` (passo 3) roda ANTES de `pattern_mappings` (passo 3b).

    Garante que dar entrada própria a um valor continua sendo a forma de abrir
    exceção a um padrão genérico.
    """
    medium = _config_vivo()
    medium.category_mappings = {'[ADVTG_ABERTO]caso especial': 'dgen'}
    out = unify_medium(
        pd.DataFrame({'Medium': ['[ADVTG_ABERTO]caso especial', '[ADVTG_ABERTO]outro']}),
        medium,
    )
    assert list(out['Medium']) == ['dgen', 'Aberto']


def test_primeiro_padrao_que_casa_vence():
    """Ordem de declaração define precedência — padrão largo depois do estreito."""
    medium = _config_vivo()
    medium.pattern_mappings = {
        r'^\[ADVTG_ABERTO\]DEV-AD0160': 'dgen',   # estreito primeiro
        r'^\[ADVTG_ABERTO\]': 'Aberto',           # largo depois
    }
    out = unify_medium(
        pd.DataFrame({'Medium': ['[ADVTG_ABERTO]DEV-AD0160 - VID', '[ADVTG_ABERTO]DEV-AD0027']}),
        medium,
    )
    assert list(out['Medium']) == ['dgen', 'Aberto']


def test_sem_pattern_mappings_comportamento_inalterado():
    """Cliente que não declara o campo não sente nada — o bloco fica inerte.

    É o critério de rollback: apagar a linha do yaml devolve o comportamento
    anterior sem redeploy de código.
    """
    medium = _config_vivo()
    medium.pattern_mappings = None
    out = unify_medium(pd.DataFrame({'Medium': ['[ADVTG_ABERTO]x', 'dgen']}), medium)
    assert list(out['Medium']) == ['Outros', 'dgen']
