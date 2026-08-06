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


# ── 4. Superfície pública: o que o serviço nem deve anunciar ─────────────────

def test_documentacao_automatica_desligada_por_default():
    """`/docs`, `/redoc` e `/openapi.json` serviam, anonimamente, 53 KB com o mapa
    completo da API: toda rota, todo parâmetro, todo nome de campo, inclusive
    `lead_score` e `decil`. Era o índice que tornava as outras rotas descobríveis.
    Fechar rota e continuar publicando o mapa é meio serviço."""
    fonte = _APP_PY.read_text()
    assert 'docs_url="/docs" if _DOCS else None' in fonte, (
        'docs_url voltou a ser incondicional')
    assert 'redoc_url="/redoc" if _DOCS else None' in fonte
    assert 'openapi_url="/openapi.json" if _DOCS else None' in fonte, (
        'openapi_url ausente: sem passar None explícito o FastAPI serve /openapi.json')

    import re
    m = re.search(r'_DOCS = os\.environ\.get\("API_DOCS_ENABLED", ""\)', fonte)
    assert m, 'a chave de reativação mudou de nome; atualize este teste junto'


def test_deploy_nao_reafirma_acesso_publico():
    """O `deploy_capi.sh` readicionava `allUsers` a cada deploy, de propósito. Se
    isso voltar, todo deploy desfaz o fechamento do serviço EM SILÊNCIO, e o furo
    reaparece sem ninguém mexer em nada."""
    from pathlib import Path as _P
    sh = (_P(auth.__file__).parent / 'deploy_capi.sh').read_text()

    # Proíbe a EXECUÇÃO, não a menção. Comentário explicando a decisão e `echo` com
    # o comando de reabertura de emergência são desejáveis: quem estiver de plantão
    # precisa saber como voltar atrás. O que não pode é o script conceder sozinho.
    junto = sh.replace('\\\n', ' ')   # o comando é multilinha; junta as continuações

    def _executa(linha: str) -> bool:
        nu = linha.strip()
        if nu.startswith('#') or nu.startswith('echo ') or nu.startswith('print_'):
            return False
        return 'add-iam-policy-binding' in nu and 'allUsers' in nu

    culpadas = [l.strip()[:110] for l in junto.splitlines() if _executa(l)]
    assert not culpadas, f'deploy voltou a conceder allUsers: {culpadas}'

    # E a reabertura de emergência tem que seguir documentada no script: fechar sem
    # dizer como abrir é armadilha para a próxima madrugada.
    assert 'add-iam-policy-binding' in sh and 'allUsers' in sh, (
        'sumiu a instrução de como reabrir o acesso em emergência')


def test_gates_de_deploy_autenticam():
    """Os três gates falavam com o Cloud Run sem credencial. Isso só funcionava
    porque o serviço aceitava anônimo, que é justamente o que estamos removendo.
    Sem isto, fechar o serviço quebra o deploy inteiro, não só o health check."""
    from pathlib import Path as _P
    base = _P(auth.__file__).parent.parent / 'scripts'
    for nome in ('smoke_test_revision.py', 'progression_gate.py',
                 'test_revision_equivalence.py'):
        fonte = (base / nome).read_text()
        assert 'from scripts.gcp_auth import instalar_auth_gcp' in fonte, (
            f'{nome} não importa a camada de identidade')
        assert 'instalar_auth_gcp()' in fonte, f'{nome} importa mas não chama'


def test_audiencia_de_url_de_tag_e_a_url_BASE_do_servico():
    """Para URL de tag do Cloud Run
    (`https://<tag>---<servico>-<hash>-<regiao>.a.run.app`, que é como os gates falam
    com a revisão canário) a audiência do token continua sendo a URL BASE do serviço.

    Foi MEDIDO, e contra a suposição da primeira versão: token com audiência igual à
    URL de tag leva **401** na própria URL de tag; com audiência igual à URL base leva
    **200**. Derivar a audiência da URL literal foi o que fez o gate levar 401 assim
    que o serviço foi fechado."""
    from scripts import gcp_auth
    base = 'https://smart-ads-api-x.a.run.app'
    assert gcp_auth.audiencia_de(
        f'https://canary-123---smart-ads-api-x.a.run.app'
        f'/monitoring/feature-report?h=1') == base
    assert gcp_auth.audiencia_de(f'{base}/health') == base


def test_gate_BLOQUEIA_quando_leva_401_ou_403():
    """Um gate que não consegue autenticar NÃO RODOU, e não pode dizer que passou.

    Em 06/08/2026, logo depois de fechar o serviço, as três checagens do smoke
    levaram 403 e o script ainda assim imprimiu "Todos os gates passaram. Prossegue."
    Gate cego dizendo que está tudo bem é pior que gate nenhum, porque compra
    confiança que ele não tem."""
    import importlib.util
    from pathlib import Path as _P
    caminho = _P(auth.__file__).parent.parent / 'scripts' / 'smoke_test_revision.py'
    spec = importlib.util.spec_from_file_location('_smoke', caminho)
    mod = importlib.util.module_from_spec(spec)
    import sys as _sys
    _sys.path.insert(0, str(caminho.parent))
    spec.loader.exec_module(mod)

    assert mod.falha_de_autenticacao({'http_status': 401})
    assert mod.falha_de_autenticacao({'http_status': 403})
    assert not mod.falha_de_autenticacao({'http_status': 500})
    assert not mod.falha_de_autenticacao({'http_status': 200})
    assert not mod.falha_de_autenticacao(None)
    assert not mod.falha_de_autenticacao('erro de rede')

    # E as três checagens têm que consultar o helper antes de decidir "não bloqueante".
    fonte = caminho.read_text()
    assert fonte.count('falha_de_autenticacao(') >= 4, (
        'alguma checagem do smoke voltou a tratar 401/403 como não bloqueante')


def test_gates_rodam_QUANDO_INVOCADOS_POR_CAMINHO():
    """O `deploy_capi.sh` invoca os gates por caminho
    (`python V2/api/../scripts/smoke_test_revision.py`), não como módulo. Nesse modo
    `scripts` não é pacote importável.

    Este teste existe porque o import da camada de identidade foi escrito na forma
    de módulo e derrubou o Gate B no primeiro deploy depois da mudança: o gate morreu
    com ModuleNotFoundError ANTES de testar qualquer coisa, e a mensagem que apareceu
    foi 'features críticas ausentes no encoding', que não tinha nada a ver.
    """
    import subprocess
    import sys
    from pathlib import Path as _P
    v2 = _P(auth.__file__).parent.parent
    for nome in ('smoke_test_revision.py', 'progression_gate.py',
                 'test_revision_equivalence.py'):
        # Invoca EXATAMENTE como o deploy: `python <caminho>`. A forma importa:
        # em `python arquivo.py` o Python põe o diretório DO ARQUIVO em sys.path[0];
        # em `python -c` ele põe o diretório atual. Reproduzir com `-c` faz o teste
        # passar batido, que foi o que aconteceu na primeira versão deste teste.
        # Sem argumento o script morre no argparse, mas o import roda antes disso.
        r = subprocess.run(
            [sys.executable, str(v2 / 'scripts' / nome)],
            capture_output=True, text=True, timeout=120, cwd=str(v2.parent))
        assert 'ModuleNotFoundError' not in r.stderr, (
            f'{nome} não carrega quando invocado por caminho:\n{r.stderr[-500:]}')


def test_smoke_do_deploy_sobrevive_a_token_ausente():
    """O smoke test do deploy roda sob `set -u`. Se o token de identidade não vier
    (gcloud fora de sessão, por exemplo), o caminho sem cabeçalho tem que funcionar.

    Este teste existe porque a primeira versão usava um array bash vazio e o expandia
    com `"${AUTH_HDR[@]}"`. O bash do macOS é a versão 3.2, e nela expandir array
    VAZIO sob `set -u` é erro de "unbound variable": a substituição morre antes do
    curl rodar, o `|| echo "000"` nem é avaliado, e o deploy falhou com
    "Health check falhou (HTTP )", sem código nenhum. O sintoma não apontava para a
    causa, que é o pior tipo de bug de script.
    """
    import re
    import subprocess
    from pathlib import Path as _P
    sh = (_P(auth.__file__).parent / 'deploy_capi.sh').read_text()

    # 1. O cabeçalho de autenticação não pode voltar a ser array. Arrays que a
    #    lógica pode deixar VAZIOS são o caso perigoso; array de lista fixa (como
    #    AUTHORIZED_BRANCHES, sempre populado) é seguro e fica de fora do critério.
    ativas = [l.strip() for l in sh.splitlines()
              if not l.strip().startswith('#') and 'AUTH_HDR' in l]
    assert not ativas, f'cabeçalho de auth voltou a ser array: {ativas}'

    # 2. A função existe e roda com token vazio sob `set -u`, nas duas versões de
    #    bash que a máquina possa ter. Extrai só a função, não o script inteiro.
    m = re.search(r'    curl_com_identidade\(\) \{.*?\n    \}\n', sh, re.S)
    assert m, 'a função curl_com_identidade sumiu do deploy'
    corpo = m.group(0).replace('curl -s', 'echo CURL')
    prog = f'set -eu\nID_TOKEN=""\n{corpo}\ncurl_com_identidade -o /dev/null x\n'
    r = subprocess.run(['bash', '-c', prog], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f'quebrou com token vazio sob set -u: {r.stderr[-300:]}'
    assert 'CURL' in r.stdout


def test_identidade_personifica_quando_a_conta_e_de_usuario(monkeypatch):
    """`gcloud auth print-identity-token --audiences=X` EXIGE conta de serviço: com
    conta de usuário ele responde "Invalid account type for --audiences". Quem roda os
    gates é uma pessoa, então o caminho é personificar a mesma conta que os crons já
    usam, que tem `roles/run.invoker` no serviço.

    Sem esse fallback o token nunca sai e todo gate leva 401 no serviço fechado."""
    import subprocess as _sp
    from scripts import gcp_auth

    gcp_auth._CACHE.clear()
    chamadas = []

    class _Saida:
        def __init__(self, rc, out, err):
            self.returncode, self.stdout, self.stderr = rc, out, err

    def _falso_run(cmd, **kw):
        chamadas.append(cmd)
        if any(c.startswith('--impersonate-service-account=') for c in cmd):
            return _Saida(0, 'AVISO qualquer\n' + 'T' * 400 + '\n', '')
        return _Saida(1, '', 'ERROR: Invalid account type for `--audiences`.')

    monkeypatch.setattr(_sp, 'run', _falso_run)
    tok = gcp_auth.token_de_identidade('https://x.a.run.app')
    gcp_auth._CACHE.clear()

    assert tok and len(tok) > 100, 'não obteve token pelo caminho de personificação'
    assert len(chamadas) == 2, f'esperava tentar direto e depois personificando: {chamadas}'
    assert any(c.startswith('--impersonate-service-account=') for c in chamadas[1])
    # O token vem na ÚLTIMA linha do stdout: a personificação escreve aviso antes.
    assert 'AVISO' not in tok


def test_deploy_nasce_FECHADO_e_reabrir_e_ato_explicito():
    """`ALLOW_PUBLIC` governa DOIS caminhos que concedem `allUsers`: a flag
    `--allow-unauthenticated` do `gcloud run deploy`, e o bloco que reafirmava o
    binding depois. Fechar só um deixa o outro reabrindo o serviço em silêncio.

    Foi o que aconteceu em 06/08/2026: o binding foi removido à mão, o bloco de
    reafirmação já tinha saído no PR anterior, e mesmo assim o deploy seguinte
    reabriu tudo pela flag. O serviço passou de 403 para 200 anônimo sem ninguém
    pedir, e só apareceu porque eu fui conferir outra coisa."""
    import re
    from pathlib import Path as _P
    sh = (_P(auth.__file__).parent / 'deploy_capi.sh').read_text()

    m = re.search(r'^ALLOW_PUBLIC=(\w+)', sh, re.M)
    assert m, 'ALLOW_PUBLIC sumiu do deploy'
    assert m.group(1) == 'false', (
        f'deploy voltaria a nascer PÚBLICO (ALLOW_PUBLIC={m.group(1)})')

    # Reabrir tem que ser ato explícito de quem roda, com flag própria.
    assert '--publico)' in sh, 'sumiu a flag explícita de reabrir'

    # E a flag do gcloud continua amarrada à variável, nunca solta.
    soltas = [l.strip() for l in sh.splitlines()
              if '--allow-unauthenticated' in l and not l.strip().startswith('#')
              and 'AUTH_FLAG=' not in l]
    assert not soltas, f'--allow-unauthenticated fora do controle de ALLOW_PUBLIC: {soltas}'
