"""
Trava o endereço de retorno do HotLeads no serviço PÚBLICO.

O QUE ACONTECEU. Em 06/08/2026 o `smart-ads-api` foi fechado de propósito: perdeu
o `allUsers` e passou a exigir identidade Google. A decisão está certa e foi
medida — a única rota que justificava deixar aberto respondia por 0,17% do volume
e gravava numa tabela aposentada. Junto com o fechamento criaram o
`smart-ads-webhook`, público, servindo APENAS rotas de webhook.

O que ficou para trás foi o endereço de RETORNO que mandamos para a Hotmart. Ele
continuou apontando para o serviço fechado, então a Hotmart passou a levar 403 do
IAM antes de chegar na aplicação: 478 tentativas em 30 dias, último selo em
05/08 19:15, primeiro 403 em 06/08 17:30, oito dias sem nenhum retorno.

POR QUE NINGUÉM VIU. O cron de submissão continuou saudável e devolvendo 200 — quem
morreu foi a volta, não a ida. O alerta do relatório vigia a fila de leads ainda
não submetidos, que é justamente o que o cron drena, então no lugar do alarme saía
a linha tranquilizadora "aguardando retorno da Hotmart". Um alerta que mede o lado
errado é pior que não ter alerta.

Este teste é o que impede a reincidência, e ele é de leitura de texto de propósito:
o valor mora num `.sh` que nenhum teste de Python importaria.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
CONFIG_SH = RAIZ / 'api' / 'lib' / 'config.sh'
SCHEDULER_SH = RAIZ / 'api' / 'setup_hotleads_scheduler.sh'

# Serviço fechado desde 06/08/2026 — só entra chamador com identidade Google.
SERVICO_FECHADO = 'smart-ads-api-gazrm25mda-uc.a.run.app'
# Portaria pública: `allUsers`, papel `webhook`, todo o resto dá 404.
SERVICO_PUBLICO = 'smart-ads-webhook-gazrm25mda-uc.a.run.app'


def _default_de(arquivo: Path, variavel: str) -> str:
    """Extrai o valor default de `${VAR:-<default>}` na primeira ocorrência."""
    texto = arquivo.read_text(encoding='utf-8')
    m = re.search(rf'\$\{{{variavel}:-([^}}]+)\}}', texto)
    assert m, f"{variavel} não encontrada em {arquivo.name}"
    return m.group(1)


def test_retorno_da_hotmart_aponta_pro_servico_publico():
    """A Hotmart é terceiro e não assina token do Google — só entra pela portaria."""
    default = _default_de(CONFIG_SH, 'HOTLEADS_PUBLIC_URL')
    assert SERVICO_PUBLICO in default, (
        f"HOTLEADS_PUBLIC_URL aponta para {default!r}. A Hotmart não tem identidade "
        f"Google: qualquer endereço que não seja o serviço público devolve 403 do "
        f"IAM antes de chegar na aplicação, e o selo para de voltar em silêncio."
    )
    assert SERVICO_FECHADO not in default, (
        "HOTLEADS_PUBLIC_URL voltou a apontar para o serviço fechado — é exatamente "
        "a regressão de 06/08/2026, que custou 8 dias de selo sem voltar."
    )


def test_cron_continua_batendo_no_servico_principal():
    """O caminho de IDA é o oposto do de volta, e confundir os dois quebra tudo.

    O Cloud Scheduler assina token OIDC e a conta `scheduler-invoker@` tem
    `roles/run.invoker` própria, então ele entra no serviço fechado normalmente.
    Apontar o cron para o serviço público faria ele bater numa porta que responde
    404 em tudo que não é rota de webhook — e `/hotleads/submit-batch` não é.
    """
    default = _default_de(SCHEDULER_SH, 'HOTLEADS_CRON_TARGET_URL')
    assert SERVICO_FECHADO in default
    assert SERVICO_PUBLICO not in default


def test_o_cron_nao_reusa_a_variavel_do_retorno():
    """Os dois endereços são opostos, então não podem compartilhar variável.

    Enquanto o scheduler lia `HOTLEADS_PUBLIC_URL`, exportar essa variável para
    corrigir o retorno redirecionava o cron junto, para o lugar errado. É armadilha
    de nome, do tipo que só aparece quando alguém usa o escape hatch.
    """
    texto = SCHEDULER_SH.read_text(encoding='utf-8')
    linhas_com_uso = [
        l for l in texto.splitlines()
        if 'HOTLEADS_PUBLIC_URL' in l and not l.lstrip().startswith('#')
    ]
    assert not linhas_com_uso, (
        f"setup_hotleads_scheduler.sh voltou a ler HOTLEADS_PUBLIC_URL: {linhas_com_uso}"
    )


def test_a_rota_de_retorno_e_servida_pelo_papel_webhook():
    """De nada adianta o endereço certo se a rota não estiver na lista do papel.

    O IAM do Cloud Run é por SERVIÇO, não por rota, e os dois serviços rodam a
    MESMA imagem. É `ROTAS_DO_WEBHOOK` que impede o serviço público de reexpor as
    36 rotas do principal — sem ela, fechar o principal não teria adiantado nada,
    o problema voltaria pela porta dos fundos.
    """
    import sys
    sys.path.insert(0, str(RAIZ))
    from api.auth import ROTAS_DO_WEBHOOK, rota_exposta

    assert '/hotleads/webhook' in ROTAS_DO_WEBHOOK, (
        "o serviço público não serviria a rota de retorno — o 403 do IAM viraria "
        "404 da aplicação, com o mesmo efeito: selo não volta."
    )
    assert rota_exposta('/hotleads/webhook', papel='webhook') is True
    # E a contraparte: o serviço público NÃO pode servir o resto da API.
    assert rota_exposta('/hotleads/submit-batch', papel='webhook') is False
