"""
Guarda de autenticação das rotas da API.

Em 05/08/2026 medimos que o serviço `smart-ads-api` aceita chamada de qualquer
pessoa na internet (`allUsers` em `roles/run.invoker`) e que 33 das 36 rotas não
tinham guarda nenhuma. Com uma requisição anônima dava para ler lead com e-mail,
telefone, `lead_score` e `decil` (limite de até 10.000 por chamada e filtro de
data), ler a importância das 60 features do modelo, e executar escrita em `/admin/`.

Esta suíte trava as duas metades da correção:

  1. **A guarda nega.** Sem token, as rotas fechadas devolvem 401. Inclui o caso
     mais fácil de errar: variável de ambiente ausente tem que FECHAR a porta, não
     abrir.
  2. **A guarda não estorva quem não deve.** As rotas que têm chamador legítimo
     medido continuam abertas, e nenhuma guarda lê o cabeçalho `Authorization`, que
     é onde o Cloud Scheduler põe o token OIDC do Google. Ler ali rejeitaria os
     nossos próprios crons, que é o jeito mais provável de esta mudança derrubar
     produção.

O critério de "rota fechada" não foi opinião: só entrou rota com tráfego legítimo
medido em ZERO nos logs do Cloud Run, em janela de 20 a 60 dias, conferida uma a uma.
"""

import os

import pytest

from api import auth


# ── 1. A guarda nega ─────────────────────────────────────────────────────────

class _Req:
    """Requisição mínima: só o que a guarda olha."""

    def __init__(self, headers=None, query=None, path='/x'):
        self.headers = headers or {}
        self.query_params = query or {}
        self.url = type('U', (), {'path': path})()


def _rodar(guarda, req):
    import asyncio
    return asyncio.run(guarda(req))


def _nega(guarda, req):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        _rodar(guarda, req)
    assert e.value.status_code == 401
    return e.value


def _passa(guarda, req):
    _rodar(guarda, req)


@pytest.fixture
def env_limpo(monkeypatch):
    for v in ('API_INTERNAL_TOKEN', 'TOK_TESTE'):
        monkeypatch.delenv(v, raising=False)
    return monkeypatch


def test_sem_token_nega(env_limpo):
    env_limpo.setenv('TOK_TESTE', 'segredo-certo')
    g = auth.exigir_token('TOK_TESTE', header='x-tok')
    _nega(g, _Req())


def test_token_errado_nega(env_limpo):
    env_limpo.setenv('TOK_TESTE', 'segredo-certo')
    g = auth.exigir_token('TOK_TESTE', header='x-tok')
    _nega(g, _Req(headers={'x-tok': 'segredo-errado'}))


def test_token_certo_passa(env_limpo):
    env_limpo.setenv('TOK_TESTE', 'segredo-certo')
    g = auth.exigir_token('TOK_TESTE', header='x-tok')
    _passa(g, _Req(headers={'x-tok': 'segredo-certo'}))


def test_variavel_ausente_FECHA_a_porta(env_limpo):
    """O erro clássico é o contrário: "se não configurou, deixa passar". Segredo
    ausente tem que negar, senão um deploy sem a env abre tudo em silêncio."""
    g = auth.exigir_token('TOK_TESTE', header='x-tok')
    _nega(g, _Req(headers={'x-tok': 'qualquer-coisa'}))
    _nega(g, _Req())


def test_query_so_vale_quando_permitido(env_limpo):
    """A Hotmart manda na query porque não consegue header. Quem não precisa disso
    não deve aceitar token em query, que vaza em log de acesso e em Referer."""
    env_limpo.setenv('TOK_TESTE', 'segredo-certo')
    so_header = auth.exigir_token('TOK_TESTE', header='x-tok')
    _nega(so_header, _Req(query={'token': 'segredo-certo'}))

    aceita_query = auth.exigir_token('TOK_TESTE', header='x-tok', aceita_query=True)
    _passa(aceita_query, _Req(query={'token': 'segredo-certo'}))


def test_resposta_nao_conta_em_que_etapa_o_atacante_esta(env_limpo):
    """Mensagem igual para "não configurado" e "token errado". Diferenciar entrega
    informação de graça a quem está sondando."""
    from fastapi import HTTPException  # noqa: F401
    env_limpo.setenv('TOK_TESTE', 'segredo-certo')
    com_env = _nega(auth.exigir_token('TOK_TESTE', header='x-tok'), _Req())
    env_limpo.delenv('TOK_TESTE')
    sem_env = _nega(auth.exigir_token('TOK_TESTE', header='x-tok'), _Req())
    assert com_env.detail == sem_env.detail


# ── 2. A guarda não estorva quem não deve ────────────────────────────────────

ROTAS_QUE_DEVEM_FICAR_FECHADAS = [
    ('get', '/model/info'),
    ('get', '/webhook/lead_capture/recent'),
    ('get', '/webhook/lead_capture/stats'),
    ('post', '/webhook/lead_capture/by_emails'),
    ('post', '/webhook/update_survey'),
    ('post', '/predict/csv'),
    ('post', '/predict/explain'),
    ('post', '/calculate_decils'),
    ('post', '/admin/migrate_capi_sent_at'),
    ('post', '/admin/cleanup_duplicates'),
    ('post', '/admin/cleanup-canary-tags'),
    ('post', '/capi/check_sent'),
    ('post', '/capi/send_purchase_events'),
    ('get', '/validation/test'),
    ('post', '/validation/weekly'),
    # As três que já tinham guarda antes, agora consumindo a base compartilhada.
    ('post', '/webhook/sendflow_group_join'),
    ('post', '/hotleads/submit-batch'),
    ('post', '/hotleads/webhook'),
]

# Rotas com chamador legítimo MEDIDO nos logs. Fechar qualquer uma destas quebra
# produção, e o nome de quem chama está aqui para a próxima pessoa não fechar sem
# querer.
ROTAS_QUE_DEVEM_FICAR_ABERTAS = {
    '/health': 'health check e smoke test do deploy',
    '/webhook/lead_capture': 'páginas antigas do cliente (resíduo, mas responde 200)',
    '/predict/batch': 'smoke test do deploy_capi.sh, com curl sem autenticação',
    '/capi/process_daily_batch': '78 chamadas em 45 dias',
    '/admin/refresh-cpl': 'cron cpl-refresh-daily (OIDC)',
    '/railway/process-pending': 'cron railway-polling (OIDC), 1.157 chamadas em 20 dias',
    '/pubsub/process-pending': 'cron pubsub-process-pending (OIDC), 1.152 em 20 dias',
    '/monitoring/utm-quality': 'front do cliente, ver docs/integracao_front_relatorio_criativo.md',
    '/monitoring/audience-quality': 'front do cliente, ver docs/integracao_front_qualidade_publico.md',
    '/monitoring/utm-quality/daily-trafego': 'cron do relatório de criativo (OIDC)',
    '/monitoring/feature-report': 'gate de deploy',
    '/monitoring/daily-check/railway': 'monitoramento',
    '/smoke/run-variants': 'gate de deploy',
}


import ast
import functools
from pathlib import Path

_APP_PY = Path(auth.__file__).parent / 'app.py'


@functools.lru_cache(maxsize=1)
def _rotas_do_app():
    """(método, caminho, tem_guarda) de cada rota, lida do CÓDIGO-FONTE.

    Não importa `api.app` de propósito: o import exige credencial de banco e sobe o
    pipeline inteiro. A pergunta aqui é sobre o que está DECLARADO no decorador, e
    isso o arquivo responde, em qualquer máquina, sem segredo nenhum.
    """
    arvore = ast.parse(_APP_PY.read_text())
    fora = []
    for no in ast.walk(arvore):
        if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in no.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            f = dec.func
            if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                    and f.value.id == 'app'
                    and f.attr in ('get', 'post', 'put', 'delete')):
                continue
            if not (dec.args and isinstance(dec.args[0], ast.Constant)):
                continue
            caminho = dec.args[0].value
            fonte_dec = ast.unparse(dec)
            tem = 'exigir_token' in fonte_dec
            fora.append((f.attr, caminho, tem))
    return fora


@pytest.mark.parametrize('metodo,caminho', ROTAS_QUE_DEVEM_FICAR_FECHADAS)
def test_rota_sensivel_tem_guarda(metodo, caminho):
    achadas = [r for r in _rotas_do_app() if r[0] == metodo and r[1] == caminho]
    assert achadas, f'rota {metodo.upper()} {caminho} sumiu do app'
    assert all(r[2] for r in achadas), (
        f'{metodo.upper()} {caminho} está SEM guarda de token e é rota sensível')


@pytest.mark.parametrize('caminho', sorted(ROTAS_QUE_DEVEM_FICAR_ABERTAS))
def test_rota_com_chamador_real_nao_foi_fechada(caminho):
    """Se este teste falhar, alguém fechou uma rota que tem chamador medido em
    produção. O dicionário acima diz quem é. Fechar exige migrar o chamador junto,
    no mesmo movimento."""
    achadas = [r for r in _rotas_do_app() if r[1] == caminho]
    if not achadas:
        pytest.skip(f'{caminho} não existe mais no app')
    quem = ROTAS_QUE_DEVEM_FICAR_ABERTAS[caminho]
    assert not any(r[2] for r in achadas), (
        f'{caminho} foi fechada, mas tem chamador real: {quem}')


def test_nenhuma_guarda_le_o_cabecalho_Authorization():
    """`Authorization: Bearer <id-token>` é do OIDC do Google, que o Cloud Scheduler
    manda. Se alguma guarda nossa passar a ler esse cabeçalho, ela rejeita os nossos
    próprios crons, que é o jeito mais provável de esta mudança derrubar produção."""
    # Nenhuma guarda declarada no app pode se apoiar no cabeçalho Authorization.
    for linha in _APP_PY.read_text().splitlines():
        if 'exigir_token(' in linha:
            assert 'authorization' not in linha.lower(), linha
    # E o módulo da guarda não pode usar esse nome de cabeçalho em CÓDIGO. Docstring
    # explicando por que não pode é justamente o que queremos manter, então a checagem
    # é sobre literais de string do código, não sobre o texto do arquivo.
    import ast as _ast
    arvore = _ast.parse(Path(auth.__file__).read_text())
    docstrings = set()
    for no in _ast.walk(arvore):
        if isinstance(no, (_ast.Module, _ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
            d = _ast.get_docstring(no, clean=False)
            if d:
                docstrings.add(d)
    for no in _ast.walk(arvore):
        if isinstance(no, _ast.Constant) and isinstance(no.value, str):
            if no.value in docstrings:
                continue
            assert 'authorization' not in no.value.lower(), no.value


# ── 3. Exposição por papel do serviço ────────────────────────────────────────

def test_papel_default_nao_muda_nada(monkeypatch):
    """A camada nasce inerte: sem `SERVICE_ROLE`, tudo responde como hoje."""
    monkeypatch.delenv(auth.ENV_PAPEL, raising=False)
    assert auth.papel_do_servico() == 'full'
    for _, caminho, _ in _rotas_do_app():
        assert auth.rota_exposta(caminho)


def test_papel_webhook_expoe_so_o_webhook(monkeypatch):
    monkeypatch.setenv(auth.ENV_PAPEL, 'webhook')
    assert auth.papel_do_servico() == 'webhook'
    assert auth.rota_exposta('/hotleads/webhook')
    assert auth.rota_exposta('/health')
    # As que vazavam não podem existir no serviço público.
    for fechada in ('/webhook/lead_capture/recent', '/model/info', '/predict/batch',
                    '/admin/cleanup_duplicates', '/monitoring/utm-quality'):
        assert not auth.rota_exposta(fechada), f'{fechada} exposta no serviço público'


def test_papel_invalido_cai_no_default_seguro(monkeypatch):
    """Valor digitado errado não pode deixar o serviço num terceiro estado. Cai em
    `full`, que é o comportamento conhecido, e não em "nada responde"."""
    monkeypatch.setenv(auth.ENV_PAPEL, 'wehbook')
    assert auth.papel_do_servico() == 'full'
    assert auth.rota_exposta('/monitoring/utm-quality')
