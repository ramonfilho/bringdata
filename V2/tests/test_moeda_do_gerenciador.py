"""Trava a conversão do teto para a MOEDA DO GERENCIADOR (Decisão 10).

O que estes testes protegem, em uma frase: que só linha da META seja convertida
pela razão do gerenciador, e que anúncio do Google saia sempre na moeda real —
mesmo quando a campanha dele tem barra vertical no nome, que é o caractere que
o código usa para reconhecer campanha da Meta.

O caso que os criou (19/08/2026): as campanhas do Google se chamam
`DEVLF | CAP | Dgen | Cold | ...` (18 das 35 têm `|`). A linha do Google passava
por linha da Meta, não achava par no gerenciador e caía na razão AGREGADA de lá:
37 linhas publicadas a 0,77 do valor devido, o teto do Google 23% mais apertado
do que a régua manda — no sentido contrário ao lift de plataforma, que existe
justamente porque o lead do Google converte ACIMA do que os decis preveem.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.push_scores_zanelato import _moeda_do_gerenciador  # noqa: E402
from src.data.criativo_historico import tem_carimbo_google      # noqa: E402


def _linha(tipo, chave, leads, teto):
    """Uma linha do push: as 9 posições que vão para a tabela da agência."""
    return [tipo, chave, leads, 50.0, 28.4, 21.6, teto, 2.0, "carimbo"]


def _gerenciador(**cestas):
    base = {"fino": {}, "cn": {}, "campanha": {}, "nome": {}, "cobertura": 1.0}
    base.update(cestas)
    return base


CAMPANHA_GOOGLE = "DEVLF | CAP | Dgen | Cold | AD0136 a AD0140 | CPA | Mercado"
CAMPANHA_META = "[22] CAP - FRIO|120233445566"


def test_carimbo_google_e_reconhecido_na_chave():
    assert tem_carimbo_google("[G] DEV-AD0140-vid-captação-V0-PODCAST")
    assert tem_carimbo_google(f"[G] DEV-AD0140 @ {CAMPANHA_GOOGLE}")
    assert not tem_carimbo_google("DEV-AD0160 - VID - CAPTAÇÃO")
    assert not tem_carimbo_google(f"DEV-AD0160 @ {CAMPANHA_META}")


def test_google_com_pipe_na_campanha_nao_e_convertido():
    """O caso do incidente: campanha do Google tem `|` e passava por Meta.

    O cenário precisa ter uma linha da META que CASE no gerenciador, senão a razão
    agregada nem existe e a linha do Google escapa por acidente — foi assim que a
    primeira versão deste teste passou mesmo com a guarda desligada.
    """
    meta = _linha("criativo_campanha", f"DEV-AD0160 @ {CAMPANHA_META}", 1000, "10.00")
    linhas = [
        meta,
        _linha("criativo_campanha_historico", f"[G] DEV-AD0140 @ {CAMPANHA_GOOGLE}",
               2980, "13.22"),
        _linha("criativo_historico", "[G] DEV-AD0140", 6013, "13.22"),
    ]
    ger = _gerenciador(cn={("120233445566", "dev-ad0160"): 1250})  # razão agregada 0,80
    out = _moeda_do_gerenciador(linhas, ger)
    for x in out:
        if not tem_carimbo_google(x[1]):
            continue
        assert x[6] == "13.22", (
            f"teto do Google saiu convertido ({x[6]}) — apanhou a razão da Meta")
        assert x[8].endswith("moeda_real"), f"selo errado no Google: {x[8]}"


def test_meta_continua_sendo_convertida():
    """A guarda do Google não pode desligar a moeda de quem é da Meta."""
    linhas = [_linha("criativo_campanha", f"DEV-AD0160 @ {CAMPANHA_META}", 1000, "10.00")]
    ger = _gerenciador(cn={("120233445566", "dev-ad0160"): 1250})
    out = _moeda_do_gerenciador(linhas, ger)
    assert out[0][6] == "8.00", "1000/1250 = 0,80 → 10,00 vira 8,00"
    assert "ger0.80" in out[0][8]


def test_google_nao_contamina_a_razao_agregada():
    """A razão agregada do corte é a média dos casamentos da META, e é ela que
    socorre a linha da Meta que não achou par próprio. Linha do Google entrando
    nessa média move o teto de OUTROS anúncios, que nem são do Google.

    Por isso o alvo do assert é `orfa` (uma linha da Meta SEM par, que depende do
    agregado) e não a linha que casa sozinha: essa usa a razão dela e não sentiria
    a contaminação.
    """
    casa = _linha("criativo_campanha", f"DEV-AD0160 @ {CAMPANHA_META}", 1000, "10.00")
    orfa = _linha("criativo_campanha", f"DEV-AD0161 @ {CAMPANHA_META}", 500, "10.00")
    google = _linha("criativo_campanha", f"[G] DEV-AD0140 @ {CAMPANHA_GOOGLE}",
                    9000, "13.22")
    # A cesta usa o último pedaço da campanha depois do `|` e o nome em minúsculas —
    # com o carimbo, que é como a chave do Google chega. Assim a linha do Google
    # CASA de verdade se a guarda não existir, e arrasta a razão agregada com ela.
    ger = _gerenciador(cn={("120233445566", "dev-ad0160"): 1250,
                           ("Mercado", "[g] dev-ad0140"): 100})
    sem_google = _moeda_do_gerenciador([casa, orfa], ger)
    com_google = _moeda_do_gerenciador([casa, orfa, google], ger)
    assert sem_google[1][6] == "8.00", "sem contaminação a órfã usa o agregado 0,80"
    assert sem_google[1][6] == com_google[1][6], (
        f"a linha do Google mudou o teto de um anúncio da META: "
        f"{sem_google[1][6]} → {com_google[1][6]}")
