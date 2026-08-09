"""Testes do alerta de custo do Cloud Run.

Rodável sem pytest:  python tests/test_cost_alert.py

Cobre a REGRA e a MENSAGEM, com o leitor de faturamento e o envio ao Slack
injetados (dublês). Não toca BigQuery nem Slack - a query real é validada à mão
contra o export, este teste garante que a decisão de avisar/calar não muda sem
alguém perceber.

O caso mais importante aqui é o `sem_dados`: um export de faturamento quebrado
devolveria zero linhas, zero seria lido como "dia baratíssimo" e o alerta ficaria
mudo justamente quando parou de enxergar a conta. Por isso zero linhas TEM que
gerar mensagem.
"""
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.monitoring.cost_alert import avaliar, executar, render_blocks
from src.monitoring.gcp_cost import BRT, CustoDiario, janela_do_dia_brt

DIA = date(2026, 8, 8)


def _custo(bruto=3.0, liquido=0.0, linhas=42, recursos=None) -> CustoDiario:
    return CustoDiario(
        dia=DIA, servico='Cloud Run', bruto=bruto, liquido=liquido, moeda='BRL',
        por_recurso=recursos if recursos is not None else [('smart-ads-api', bruto)],
        linhas=linhas,
        export_time=datetime(2026, 8, 9, 9, 21, tzinfo=timezone.utc),
    )


def test_dia_calmo_nao_avisa():
    av = avaliar(_custo(bruto=3.02), limite=10.0)
    assert av.status == 'dentro_do_limite', av.status
    assert not av.deve_avisar
    print("✅ dia dentro do teto não vira DM")


def test_estouro_avisa():
    av = avaliar(_custo(bruto=12.21), limite=10.0)
    assert av.status == 'acima_do_limite', av.status
    assert av.deve_avisar
    print("✅ uso acima do teto dispara")


def test_limite_e_estrito_maior_que():
    """Bater exatamente no teto não é estouro - evita alerta em quem calibrou o
    teto com o valor exato de um dia normal."""
    av = avaliar(_custo(bruto=10.0), limite=10.0)
    assert av.status == 'dentro_do_limite', av.status
    print("✅ igual ao teto não dispara; só acima")


def test_export_vazio_avisa_em_vez_de_calar():
    av = avaliar(_custo(bruto=0.0, linhas=0, recursos=[]), limite=10.0)
    assert av.status == 'sem_dados', av.status
    assert av.deve_avisar, "export vazio TEM que gerar aviso, senão vira silêncio falso"
    texto = str(render_blocks(av))
    assert 'não consegui medir' in texto.lower()
    print("✅ faturamento sem linhas vira aviso, não silêncio")


def test_mensagem_traz_o_culpado_e_os_dois_numeros():
    av = avaliar(_custo(bruto=12.21, liquido=11.07,
                        recursos=[('smart-ads-api', 11.9), ('dash-zanelato-refresh', 0.31)]),
                 limite=10.0)
    texto = str(render_blocks(av))
    assert 'smart-ads-api' in texto, "a mensagem precisa dizer QUEM gastou"
    assert 'R$ 12,21' in texto, "uso bruto formatado em reais"
    assert 'R$ 11,07' in texto, "valor cobrado de fato também aparece"
    print("✅ mensagem nomeia o culpado e mostra uso e cobrança")


def test_top5_agrupa_a_cauda():
    recursos = [(f'servico-{i}', float(10 - i)) for i in range(8)]
    av = avaliar(_custo(bruto=52.0, recursos=recursos), limite=10.0)
    texto = str(render_blocks(av))
    assert 'outros 3' in texto, "cauda além do top 5 vira uma linha só"
    print("✅ ranking corta no top 5 e soma o resto")


def test_executar_posta_so_quando_ha_o_que_dizer():
    enviados = []

    def poster(canal, blocks, fallback):
        enviados.append((canal, fallback))
        return {'ok': True, 'channel': canal, 'ts': '1'}

    calmo = executar(dia=DIA, limite=10.0, canal='D123',
                     leitor=lambda d, servico=None: _custo(bruto=3.0), poster=poster)
    assert calmo['postado'] is False and calmo['ok'] is True
    assert enviados == [], "dia calmo não pode gerar DM"

    estouro = executar(dia=DIA, limite=10.0, canal='D123',
                       leitor=lambda d, servico=None: _custo(bruto=15.0), poster=poster)
    assert estouro['postado'] is True
    assert len(enviados) == 1 and enviados[0][0] == 'D123'
    print("✅ executar só manda DM quando estoura")


def test_force_posta_dia_calmo():
    enviados = []
    r = executar(dia=DIA, limite=10.0, canal='D123', force=True,
                 leitor=lambda d, servico=None: _custo(bruto=3.0),
                 poster=lambda c, b, f: (enviados.append(c), {'ok': True, 'channel': c})[1])
    assert r['postado'] is True and enviados == ['D123']
    print("✅ force posta mesmo dentro do teto (validação de formatação)")


def test_slack_fora_do_ar_nao_finge_sucesso():
    r = executar(dia=DIA, limite=10.0, canal='D123',
                 leitor=lambda d, servico=None: _custo(bruto=15.0),
                 poster=lambda c, b, f: {'ok': False, 'channel': c, 'error': 'channel_not_found'})
    assert r['ok'] is False and r['postado'] is False
    assert r['erro'] == 'channel_not_found'
    print("✅ falha do Slack não vira sucesso silencioso")


def test_janela_do_dia_e_calendario_brt():
    """O faturamento carimba em UTC; o alerta fala em BRT. 08/08 BRT começa às
    03:00 UTC do dia 08 e termina às 03:00 UTC do dia 09."""
    inicio, fim = janela_do_dia_brt(DIA)
    assert inicio.isoformat() == '2026-08-08T03:00:00+00:00', inicio.isoformat()
    assert fim.isoformat() == '2026-08-09T03:00:00+00:00', fim.isoformat()
    assert inicio.astimezone(BRT).hour == 0
    print("✅ janela do dia respeita o horário de Brasília")


if __name__ == '__main__':
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith('test_') and callable(fn):
            try:
                fn()
            except AssertionError as e:
                falhas += 1
                print(f"❌ {nome}: {e}")
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    sys.exit(1 if falhas else 0)
