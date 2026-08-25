# -*- coding: utf-8 -*-
"""O segundo teto (meta de ROAS 1,5) derivado da linha publicada.

A meta só entra na fórmula como divisor, então o teto a 1,5 é o teto final da
linha (já na moeda dela) vezes alvo/1,5. O teste trava as três garantias:
a conta, o None de linha sem teto (nunca 0), e o contrato antigo intacto.
"""
import scripts.push_scores_zanelato as p


def _linha(teto, alvo=2.0, selo="ref·f1.23"):
    return ["criativo_7dias", "AD-X", 500, 31.2, 28.4, 2.8, teto, alvo, selo]


def test_escala_pelo_alvo_da_linha():
    out = p._com_teto_secundario([_linha("6.00")])
    # 6,00 a ROAS 2 → 8,00 a ROAS 1,5 (× 2/1,5)
    assert out[0][9] == "8.00"


def test_linha_sem_teto_leva_none_nunca_zero():
    out = p._com_teto_secundario([_linha(None, alvo=None, selo="sem_teto:x")])
    assert out[0][9] is None


def test_moeda_do_gerenciador_atravessa_intacta():
    # a derivação age sobre o teto PUBLICADO: se a moeda converteu 6,00 → 4,80
    # (razão 0,8), o secundário é 4,80 × 4/3 = 6,40 — nunca o real reescalado.
    out = p._com_teto_secundario([_linha("4.80", selo="ref·ger0.80")])
    assert out[0][9] == "6.40"


def test_contrato_antigo_intacto():
    # a coluna nova NÃO entra em COLUNAS: quem publica decide pelo destino
    # (gravar corta a 10ª posição enquanto a agência não criar a coluna).
    assert p.COLUNA_SECUNDARIA not in p.COLUNAS
    assert len(p.COLUNAS) == 9
    out = p._com_teto_secundario([_linha("6.00")])
    assert len(out[0]) == len(p.COLUNAS) + 1


def test_derivacao_preserva_todas_as_posicoes():
    linha = _linha("6.00")
    out = p._com_teto_secundario([linha])
    assert out[0][:9] == linha


def test_homonimo_fundido_mantem_a_coluna():
    # a fusão ponderada de coletar() reconstrói a linha em 9 posições; por isso a
    # derivação é o ÚLTIMO passo, depois da fusão (bug pego na prova real de
    # 23/08: IndexError na linha fundida). Aqui: linhas de 9 posições, como a
    # fusão as deixa, saem todas com 10.
    out = p._com_teto_secundario([_linha("6.00")[:9], _linha("8.00")[:9]])
    assert all(len(x) == 10 for x in out)
    assert out[0][9] == "8.00" and out[1][9] == "10.67"
