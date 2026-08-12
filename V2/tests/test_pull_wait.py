"""Testes do tempo de espera de cada pergunta à fila do Pub/Sub.

Rodável sem pytest:  python tests/test_pull_wait.py

O que está sendo protegido: esse número é a maior parte da conta do Cloud Run.
Com 3 perguntas de confirmação por invocação e 288 invocações por dia, cada
segundo aqui vale ~R$ 0,30/dia, porque o Cloud Run cobra pelo tempo que a chamada
fica aberta e a máquina tem 2 CPUs. Ele caiu de 10 para 3 segundos em 12/08/2026.

Os testes travam as duas pontas:
  - o default não pode subir sem alguém perceber (custo);
  - valor inválido ou absurdo não pode derrubar o consumo de leads nem estourar
    o prazo do cron (disponibilidade).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api import pubsub_branch as pb

VAR = "PUBSUB_PULL_WAIT_S"


def _com_env(valor):
    """Roda a função com a variável setada (ou removida, se valor=None)."""
    antes = os.environ.get(VAR)
    try:
        if valor is None:
            os.environ.pop(VAR, None)
        else:
            os.environ[VAR] = str(valor)
        return pb.tempo_de_espera_do_pull()
    finally:
        if antes is None:
            os.environ.pop(VAR, None)
        else:
            os.environ[VAR] = antes


def test_default_e_3_segundos():
    """O default é o que roda em produção. Se subir, a conta sobe junto."""
    assert _com_env(None) == 3.0, "default mudou; era 3.0"
    print("✅ default é 3 segundos")


def test_default_nao_pode_regredir_pro_valor_antigo():
    """Trava explícita contra voltar aos 10s sem decisão consciente: era isso que
    custava ~R$ 3/dia mesmo em dia sem lead nenhum."""
    assert pb._PULL_WAIT_SECONDS_DEFAULT < 10.0, "voltou ao valor caro de antes"
    print("✅ default não regrediu para os 10s antigos")


def test_ajustavel_sem_deploy():
    """Rollback em 2 minutos é setar a variável, sem build."""
    assert _com_env(10) == 10.0
    assert _com_env("1.5") == 1.5
    print("✅ ajustável por variável de ambiente")


def test_valor_invalido_nao_derruba_o_consumo():
    """Typo na variável não pode parar o scoring de leads."""
    for lixo in ("abc", "", "3,0"):
        assert _com_env(lixo) == 3.0, f"'{lixo}' devia cair no default"
    print("✅ valor inválido cai no default em vez de explodir")


def test_valor_absurdo_e_recusado():
    """Teto protege o prazo do cron (a rota tem deadline de 180s); piso evita
    alguém zerar a escuta achando que economiza."""
    assert _com_env(999) == 3.0, "acima do teto devia cair no default"
    assert _com_env(0) == 3.0, "abaixo do piso devia cair no default"
    assert _com_env(-5) == 3.0
    print("✅ valor fora da faixa é recusado")


def test_tres_perguntas_cabem_folgado_no_prazo_do_cron():
    """Invariante de disponibilidade: o pior caso de espera tem que caber no teto
    de tempo da drenagem, senão a rota estoura o prazo e o Scheduler reentrega."""
    pior_caso = pb._DRAIN_MAX_ROUNDS * 30.0      # teto da variável × rodadas
    assert pior_caso <= pb._DRAIN_SECONDS * 2.5, "teto da espera perigoso vs teto da drenagem"
    normal = pb._DRAIN_EMPTY_PULLS * pb._PULL_WAIT_SECONDS_DEFAULT
    assert normal <= 15.0, f"confirmação normal custa {normal}s, esperado <=15s"
    print(f"✅ confirmação normal custa {normal:.0f}s (era 30s)")


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
