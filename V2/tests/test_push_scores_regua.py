"""Trava a régua que decide quais linhas do PRODUTO (criativo × campanha) o painel
da agência recebe.

O que estes testes protegem, em uma frase: que a porta do gasto (>= R$ 300, aberta em
01/09/2026) só ACRESCENTE linha, nunca tire uma que o gestor já via, e que ela degrade
pro piso de leads de sempre em toda situação onde o gasto do gerenciador não é sabido.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import push_scores_zanelato as p

CAMPANHA = "[31] LEAD SEGMENTADO|120299887766554433"
CRIATIVO = "AD0160 Video Depoimento"
CHAVE = ("120299887766554433", "ad0160 video depoimento")


def _ger(gasto=None):
    """Cesta do gerenciador com (ou sem) gasto para a dupla de teste."""
    return {"gasto_cn": {} if gasto is None else {CHAVE: gasto}}


def test_o_piso_de_leads_continua_valendo_e_sozinho_ja_publica():
    """Quem cruza 100 leads entra, mesmo sem gasto conhecido. É a garantia de que a
    mudança não TIROU nada do painel: a régua nova é união, não substituição."""
    assert p._publica_unidade(100, 100, _ger(), CRIATIVO, CAMPANHA)
    assert p._publica_unidade(4000, 100, _ger(), CRIATIVO, CAMPANHA)
    # e continua valendo mesmo com gasto ridículo, porque a porta dele é OUTRA
    assert p._publica_unidade(250, 100, _ger(gasto=12.0), CRIATIVO, CAMPANHA)


def test_a_porta_do_gasto_publica_a_dupla_que_o_piso_de_leads_escondia():
    """O caso que motivou a mudança: CPL alto, poucos leads, dinheiro de verdade
    gasto. Media 2,43 de ROAS dentro do teto contra 0,77 fora, em 11 lançamentos."""
    assert p._publica_unidade(40, 100, _ger(gasto=300.0), CRIATIVO, CAMPANHA)
    assert p._publica_unidade(20, 100, _ger(gasto=1500.0), CRIATIVO, CAMPANHA)


def test_a_porta_do_gasto_NAO_publica_agregado_de_meia_duzia_de_pessoas():
    """REGRA INEGOCIÁVEL do topo do arquivo: decil POR LEAD não sai desta entrega.

    Com 3 leads a %D9-D10 só assume 0%, 33%, 67% ou 100%, e cada valor diz o decil
    de um lead com outro nome. Medido em 01/09/2026: uma dupla com 3 leads e R$ 600
    gastos existia de verdade na janela de 90 dias. E o buraco anda junto com o que
    a porta pega: CPL alto é pouco lead pelo mesmo dinheiro."""
    assert not p._publica_unidade(3, 100, _ger(gasto=600.0), CRIATIVO, CAMPANHA)
    assert not p._publica_unidade(1, 100, _ger(gasto=5000.0), CRIATIVO, CAMPANHA)
    assert not p._publica_unidade(19, 100, _ger(gasto=5000.0), CRIATIVO, CAMPANHA)
    # a fronteira exata, para ninguém baixar o piso sem passar por aqui
    assert p.PISO_PRIVACIDADE_UNIDADE == 20
    assert p._publica_unidade(20, 100, _ger(gasto=300.0), CRIATIVO, CAMPANHA)


def test_o_piso_de_privacidade_nao_cobra_pedagio_de_quem_ja_passava():
    """Ele guarda só a porta NOVA. Quem cruza o piso de leads de sempre entra
    igual, porque essa linha já era publicada antes desta mudança existir."""
    assert p._publica_unidade(150, 100, _ger(), CRIATIVO, CAMPANHA)


def test_abaixo_dos_dois_pisos_nao_publica():
    """Cauda: pouco lead E pouco gasto. Continua fora, como antes."""
    assert not p._publica_unidade(40, 100, _ger(gasto=299.99), CRIATIVO, CAMPANHA)
    assert not p._publica_unidade(99, 100, _ger(gasto=0.0), CRIATIVO, CAMPANHA)


def test_o_piso_do_gasto_e_o_MESMO_do_julgamento_interno():
    """Se alguém mexer num lado sem o outro, o painel do gestor e o relatório
    interno passam a julgar duplas diferentes, que é o buraco que esta mudança
    fechou. O número é o do PR #256."""
    assert p.PISO_GASTO_UNIDADE == 300.0


def test_sem_gasto_conhecido_cai_no_piso_de_leads_e_nao_publica():
    """Degradação segura. Anúncio que o gerenciador não casou (grafia, janela sem
    cobertura, ad sem lead contado) não pode entrar pela porta do gasto por engano:
    'não sei o gasto' nunca vira 'gastou o bastante'."""
    assert not p._publica_unidade(40, 100, _ger(), CRIATIVO, CAMPANHA)
    assert not p._publica_unidade(40, 100, {}, CRIATIVO, CAMPANHA)
    assert not p._publica_unidade(40, 100, None, CRIATIVO, CAMPANHA)


def test_anuncio_do_google_nao_entra_pela_porta_do_gasto():
    """O gerenciador da META não conta gasto do Google, então a dupla do Google não
    tem gasto a consultar. A campanha dele chega sem o sufixo `nome|id`, e é essa a
    marca usada. Sem esta guarda a linha do Google cairia numa chave inexistente."""
    assert not p._publica_unidade(40, 100, _ger(gasto=5000.0),
                                  "video_institucional", "DEVLF | CAP | Dgen | Cold")


def test_linha_sem_teto_nao_entra_pela_porta_do_gasto():
    """A porta do gasto existe pra ENTREGAR UM TETO. Sem teto calculável a linha
    seria só uma %D9-D10 de amostra pequena, exatamente o que o piso de N evita."""
    assert not p._publica_unidade(40, 100, _ger(gasto=900.0), CRIATIVO, CAMPANHA,
                                  teto_ok=False)
    # mas quem passa pelo piso de LEADS continua entrando com ou sem teto, porque
    # essa linha já existia antes e some-la seria regressão no painel deles
    assert p._publica_unidade(400, 100, _ger(), CRIATIVO, CAMPANHA, teto_ok=False)


def test_a_chave_do_gasto_normaliza_caixa_e_espaco_igual_a_cesta_de_leads():
    """A cesta do gerenciador é indexada em caixa baixa e espaço único. Se a régua
    consultasse com outra grafia, o lookup falharia em SILÊNCIO e a linha sumiria do
    painel sem ninguém saber por quê. É a armadilha clássica deste arquivo."""
    assert p._publica_unidade(40, 100, _ger(gasto=800.0),
                              "  AD0160   VIDEO   Depoimento ", CAMPANHA)


def test_o_id_da_campanha_sai_do_sufixo_e_nao_do_nome():
    """A cesta é indexada por campaign_id. O rótulo publicado é `nome|id`, e é o id
    depois da barra que casa. Usar o nome inteiro erraria toda dupla."""
    assert p._publica_unidade(40, 100, _ger(gasto=800.0), CRIATIVO,
                              "OUTRO NOME QUALQUER|120299887766554433")
    assert not p._publica_unidade(40, 100, _ger(gasto=800.0), CRIATIVO,
                                  "[31] LEAD SEGMENTADO|999999999999")
