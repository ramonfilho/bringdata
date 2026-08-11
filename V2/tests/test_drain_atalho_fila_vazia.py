"""Testes do atalho de fila vazia na drenagem do Pub/Sub.

Rodável sem pytest:  python tests/test_drain_atalho_fila_vazia.py

O que está sendo protegido: a drenagem passou a poder parar no PRIMEIRO pull
vazio quando a fila do Pub/Sub confirma que não há mensagem parada, em vez de
gastar mais dois pulls de 10 segundos só pra confirmar. A economia é real, mas
a segurança inteira depende de uma assimetria:

    a métrica só pode ENCURTAR a drenagem, nunca prolongar.

Se um dia alguém "melhorar" isso deixando a métrica mandar continuar puxando, o
custo volta pela porta dos fundos (a métrica tem ~26s de atraso e ecoa backlog
já drenado) e estes testes têm que falhar. Por isso o teste do erro e o teste do
backlog são tão importantes quanto o do caminho feliz.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api import pubsub_branch


class FakePipeline:
    pass


def _drenar(respostas, fila_vazia_fn, **kw):
    """Roda a drenagem com um `process_pending_pubsub` de mentira.

    `respostas` é a lista do que cada rodada devolve, em ordem.
    Devolve (resultado, quantas rodadas foram realmente pedidas).
    """
    chamadas = {'n': 0}

    def falso_process(subscriber, conn, pipeline, **_):
        i = chamadas['n']
        chamadas['n'] += 1
        return respostas[i] if i < len(respostas) else {"processed": 0}

    original = pubsub_branch.process_pending_pubsub
    pubsub_branch.process_pending_pubsub = falso_process
    try:
        r = pubsub_branch.drain_pending_pubsub(
            None, None, FakePipeline(), fila_vazia_fn=fila_vazia_fn, **kw)
    finally:
        pubsub_branch.process_pending_pubsub = original
    return r, chamadas['n']


VAZIO = {"processed": 0}
COM_LEAD = {"processed": 3, "sent": 3}


def test_fila_confirmada_vazia_para_no_primeiro_vazio():
    """O caso que economiza: 1 pull vazio + a fila dizendo zero = pode parar."""
    r, rodadas = _drenar([VAZIO], lambda: True)
    assert rodadas == 1, f"gastou {rodadas} pulls; devia ter parado no 1o"
    assert r['drain_stop'] == 'fila_vazia_confirmada', r['drain_stop']
    print("✅ fila confirmada vazia para no 1o pull (economiza 20s)")


def test_processa_e_so_entao_usa_o_atalho():
    """Com lead na primeira rodada, ele é processado normalmente; o atalho só
    entra depois, no primeiro vazio."""
    r, rodadas = _drenar([COM_LEAD, VAZIO], lambda: True)
    assert rodadas == 2, rodadas
    assert r['processed'] == 3, r['processed']
    assert r['drain_stop'] == 'fila_vazia_confirmada'
    print("✅ lead é processado antes do atalho encerrar")


def test_metrica_indisponivel_cai_no_comportamento_antigo():
    """SALVAGUARDA: sem resposta da métrica, nada muda em relação a antes."""
    r, rodadas = _drenar([VAZIO, VAZIO, VAZIO], lambda: False)
    assert rodadas == 3, f"devia ter gasto os 3 pulls antigos, gastou {rodadas}"
    assert r['drain_stop'] == 'sem_resposta', r['drain_stop']
    print("✅ métrica fora do ar = comportamento idêntico ao de antes")


def test_fila_com_backlog_nao_encurta_nem_prolonga():
    """SALVAGUARDA CENTRAL: fila respondendo 'tem mensagem' NÃO pode fazer a
    drenagem continuar além da regra antiga. A métrica atrasa ~26s e ecoa
    backlog já drenado; obedecer esse eco seria voltar a queimar máquina."""
    r, rodadas = _drenar([VAZIO, VAZIO, VAZIO, VAZIO, VAZIO], lambda: False)
    assert rodadas == 3, f"a regra antiga para em 3; gastou {rodadas}"
    assert r['drain_stop'] == 'sem_resposta'
    print("✅ backlog na métrica não prolonga a drenagem")


def test_atalho_nunca_gasta_mais_pulls_que_o_comportamento_antigo():
    """Invariante de custo: para qualquer sequência, com atalho <= sem atalho."""
    casos = [
        [VAZIO],
        [VAZIO, VAZIO],
        [COM_LEAD, VAZIO],
        [COM_LEAD, COM_LEAD, VAZIO, VAZIO],
        [VAZIO, COM_LEAD, VAZIO],
    ]
    for seq in casos:
        _, com = _drenar(seq, lambda: True)
        _, sem = _drenar(seq, lambda: False)
        assert com <= sem, f"atalho gastou mais ({com} > {sem}) em {seq}"
    print("✅ atalho nunca custa mais que o comportamento antigo")


def test_interruptor_desliga_sem_deploy():
    """`DRAIN_USA_METRICA_DE_FILA=false` devolve o comportamento antigo."""
    antes = os.environ.get('DRAIN_USA_METRICA_DE_FILA')
    try:
        os.environ['DRAIN_USA_METRICA_DE_FILA'] = 'false'
        assert pubsub_branch.atalho_de_fila_ligado() is False
        assert pubsub_branch.fila_vazia() is False, "desligado tem que devolver False"
        os.environ['DRAIN_USA_METRICA_DE_FILA'] = 'true'
        assert pubsub_branch.atalho_de_fila_ligado() is True
    finally:
        if antes is None:
            os.environ.pop('DRAIN_USA_METRICA_DE_FILA', None)
        else:
            os.environ['DRAIN_USA_METRICA_DE_FILA'] = antes
    print("✅ interruptor desliga o atalho sem deploy")


def test_erro_na_consulta_nunca_derruba_o_consumo():
    """Se o módulo da métrica explodir, `fila_vazia` devolve False em vez de
    propagar: uma exceção aqui pararia o scoring de leads."""
    import src.monitoring.pubsub_backlog as backlog
    original = backlog.fila_comprovadamente_vazia
    backlog.fila_comprovadamente_vazia = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        assert pubsub_branch.fila_vazia() is False
    finally:
        backlog.fila_comprovadamente_vazia = original
    print("✅ erro na consulta não propaga pro consumo de leads")


def test_leitura_da_metrica_distingue_vazio_de_nao_sei():
    """Zero e 'não consegui perguntar' NÃO podem virar a mesma coisa."""
    from src.monitoring import pubsub_backlog as b
    original = b.mensagens_paradas
    try:
        b.mensagens_paradas = lambda p, a: 0
        assert b.fila_comprovadamente_vazia('p', 'a') is True
        b.mensagens_paradas = lambda p, a: None      # não sei
        assert b.fila_comprovadamente_vazia('p', 'a') is False
        b.mensagens_paradas = lambda p, a: 7         # tem backlog
        assert b.fila_comprovadamente_vazia('p', 'a') is False
    finally:
        b.mensagens_paradas = original
    print("✅ 'não sei' não é confundido com 'vazia'")


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
