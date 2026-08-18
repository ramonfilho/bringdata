"""✅ da tabela de Drift por A/B: regra canônica + render, sem duas verdades.

Contexto: até 02/08/2026 existiam DUAS regras de vencedor. O renderizador do
Slack tinha a sua (quem empurra o público mais forte na direção boa, ignorando a
distância até o Top%) e o `data_quality` gravava um campo `winner` com outra
(mais perto do Top%) que ninguém lia. Como o Champion desloca o público muito
mais que o Challenger, a regra do renderizador dava o ✅ ao braço mais agressivo
por construção: 9 das 10 linhas marcadas em 01/08/2026.

Este teste tranca as duas pontas: a regra em si e o fato de o renderizador só
LER o campo, nunca recalcular.

Rodável:  PYTHONPATH=. python tests/test_variant_winner_checkmark.py
"""
from src.monitoring.data_quality import pick_variant_winner
from src.monitoring.digest import _slack_alert_audience_by_variant


# ---------------------------------------------------------------- regra pura

def test_vence_quem_esta_mais_perto_do_topo():
    # Caso real de 01/08: Idade 25-34, Top%=30.9. Champion foi a 48.2% (+17.3),
    # Challenger a 31.8% (+0.9). A regra antiga premiava o +17.3 por ser o maior
    # avanço numa categoria 'positive'; a canônica dá ao que ficou em cima do Top%.
    assert pick_variant_winner('positive', 17.3, 0.9) == 'challenger'


def test_direcao_negativa_tambem_e_por_distancia():
    # Idade 18-24 (negative), Top%=22.6: Champion -11.3, Challenger -4.4.
    # A regra antiga elegia o Δ mais negativo (Champion). Distância elege o outro.
    assert pick_variant_winner('negative', -11.3, -4.4) == 'challenger'


def test_champion_vence_quando_realmente_esta_mais_perto():
    # Tem Computador: Não (very_negative), Top%=13.4: Champion +4.2, Challenger +7.1.
    assert pick_variant_winner('very_negative', 4.2, 7.1) == 'champion'


def test_direcao_desconhecida_nao_elege_ninguem():
    for direcao in (None, 'neutral', 'uncertain', 'insufficient_data'):
        assert pick_variant_winner(direcao, 0.1, 9.9) is None, direcao


def test_braco_sem_medicao_nao_elege_ninguem():
    assert pick_variant_winner('positive', None, 2.0) is None
    assert pick_variant_winner('positive', 2.0, None) is None


def test_empate_de_distancia_nao_elege_ninguem():
    assert pick_variant_winner('positive', 3.0, -3.0) is None


# ---------------------------------------------------------------- render

def _alert(rows, *, champion_n=500, challenger_n=500):
    return {
        'type': 'audience_profile_drift_by_variant',
        'details': {
            'window': 'previous_day', 'window_label': 'Ontem',
            'lead_n': 0, 'champion_n': champion_n, 'challenger_n': challenger_n,
            'google_n': 0, 'outros_n': 0,
            'top_list': rows,
        },
    }


def _row(winner, *, ch=(48.2, 17.3), cl=(31.8, 0.9)):
    return {
        'feature_label': 'Idade', 'category': '25-34', 'reference_pct': 30.9,
        'rolling_reference_pct': None,
        'lead_pct': None, 'lead_delta_pp': None, 'lead_quality': None,
        'champion_pct': ch[0], 'champion_delta_pp': ch[1], 'champion_quality': 'bom',
        'challenger_pct': cl[0], 'challenger_delta_pp': cl[1], 'challenger_quality': 'bom',
        'direction': 'positive', 'winner': winner,
    }


def _render(alert):
    blocks = []
    _slack_alert_audience_by_variant(alert, blocks)
    return "\n".join(b.get('text', {}).get('text', '')
                     for b in blocks if b.get('type') == 'section')


def _linha_dados(texto):
    return [ln for ln in texto.splitlines() if 'Idade' in ln][0]


def test_render_marca_o_braco_que_o_payload_elegeu():
    linha = _linha_dados(_render(_alert([_row('challenger')])))
    # ✅ colado no 31.8%(+0.9) do Challenger, e nada depois do 48.2%(+17.3).
    # Sem espaço antes do ✅ desde 02/08/2026: era ele que estourava a largura
    # da coluna (_AW), e a linha inteira passava de 120 caracteres no Slack.
    assert '31.8%(+0.9)✅' in linha, linha
    assert '48.2%(+17.3)✅' not in linha, linha


def test_render_nao_recalcula_o_vencedor():
    # Payload manda 'challenger' numa linha onde a regra ANTIGA diria 'champion'
    # (+17.3 é o maior avanço numa categoria positive). Se o ✅ cair no Champion,
    # alguém voltou a recalcular no renderizador.
    linha = _linha_dados(_render(_alert([_row('challenger')])))
    assert linha.index('✅') > linha.index('31.8%'), linha


def test_render_sem_vencedor_nao_marca_ninguem():
    assert '✅' not in _render(_alert([_row(None)]))


def test_sem_os_dois_bracos_nao_marca_ninguem():
    # Challenger abaixo do corte de N some da tabela → ✅ perde sentido.
    assert '✅' not in _render(_alert([_row('challenger')], challenger_n=3))


# ------------------------------------------- largura e colunas (18/08/2026)

# Teto de largura da linha. O limite REAL é visual (o Slack quebra pela largura da
# janela de quem lê), não um número do protocolo — então o teto aqui é ancorado no
# que comprovadamente circula: a tabela `Drift por Fonte` vai pro grupo todo dia com
# 92 chars / 94 colunas visuais sem quebrar. A de A/B com as 3 colunas mede 96 chars
# / 100 visuais, validado na tela do leitor em 18/08/2026 antes de entrar. O teto
# existe pra travar CRESCIMENTO: quem adicionar uma 4ª coluna ou alargar célula
# quebra aqui, não no Slack do operador.
MAX_LINHA_CHARS = 100


def test_lead_tem_coluna_e_a_linha_nao_cresce_sem_medir():
    """Lead de volta às colunas (18/08/2026) sem estourar a largura validada.

    Ele saiu em 02/08 porque a linha dava 120 chars (130+ quando o rótulo ainda
    levava o run do modelo) e o Slack quebrava a coluna do Challenger pra uma
    segunda linha. No MESMO dia entrou o rótulo curto (Champ/Chall), que resolveu a
    largura — mas a coluna nunca voltou. Ela importa porque o Lead é o único grupo
    SEM modelo: o único controle do mesmo dia e do mesmo leilão. Sem ele os braços de
    ML só tinham como referência o Top5, congelado em maio de 2026.
    """
    rows = [_row('challenger')]
    for it in rows:
        it['rolling_reference_pct'] = 29.4          # liga a coluna Compr%
        it['lead_pct'], it['lead_delta_pp'], it['lead_quality'] = 21.0, -8.4, 'ruim'
    alerta = _alert(rows)
    alerta['details']['lead_n'] = 88                # Lead acima do corte de N
    txt = _render(alerta)
    tabela = [ln for ln in txt.splitlines() if ln.startswith('`')]
    assert tabela, txt
    assert max(len(ln) for ln in tabela) <= MAX_LINHA_CHARS, max(len(ln) for ln in tabela)
    # Lead tem coluna própria...
    assert 'Lead(' in txt, txt
    # ...e passa a contar DENTRO da tabela, não mais no "fora da tabela".
    assert 'Lead=88' in txt, txt
    assert 'fora da tabela: Google' in txt, txt


def test_lead_nao_disputa_o_check_de_vencedor():
    """O ✅ continua só entre os 2 braços de ML. O Lead entra como leitura, não como
    competidor (`compete=False`) — era a razão de tirá-lo em 02/08 sem prejuízo pra
    essa marcação. Se um dia o ✅ aparecer na coluna dele, alguém mexeu no `_arms`
    sem entender o papel do balde."""
    rows = [_row('challenger')]
    for it in rows:
        it['lead_pct'], it['lead_delta_pp'], it['lead_quality'] = 99.9, 99.9, 'bom'
    alerta = _alert(rows)
    alerta['details']['lead_n'] = 500
    txt = _render(alerta)
    linha = _linha_dados(txt)
    assert linha.count('✅') == 1, linha
    assert linha.index('✅') > linha.index('99.9%'), linha


def test_lead_abaixo_do_corte_vira_nota_como_qualquer_braco():
    """Corte de N vale igual pros três: pouco lead = ruído de Δ, sai da tabela e
    vira nota — nunca some em silêncio."""
    alerta = _alert([_row('challenger')])
    alerta['details']['lead_n'] = 3
    txt = _render(alerta)
    assert 'Lead(' not in txt, txt
    assert 'Omitidos' in txt and 'Lead=3' in txt, txt


if __name__ == '__main__':
    import sys
    falhas = 0
    for nome, fn in sorted(list(globals().items())):
        if nome.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'  ✓ {nome}')
            except AssertionError as e:
                falhas += 1
                print(f'  ✗ {nome}: {e}')
    print(f'\n{"FALHOU" if falhas else "OK"}: {falhas} falha(s)')
    sys.exit(1 if falhas else 0)
