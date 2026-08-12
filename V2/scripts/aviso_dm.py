"""Aviso no DM do operador. Um lugar só, usado por qualquer job desta entrega.

POR QUE ISTO EXISTE COMO MÓDULO PRÓPRIO
=======================================
A função nasceu dentro do `push_supabase_zanelato.py` em 10/08/2026, para a auditoria da
entrega. O motivo dela era este: a auditoria DETECTAVA a divergência, saía com erro, e o
erro morria no log do Cloud Run. Ninguém olha log por hábito. Verificado no dia: das 3
políticas de alerta do projeto, nenhuma cobre estes jobs — a de `Cron falhou` dispara quando
o Scheduler não consegue DISPARAR o job (403/500), não quando o job roda e falha por dentro.
Uma defesa que ninguém vê não é defesa.

A ingestão tem o mesmo problema com o aviso de teto de tempo por rodada, e é o segundo
consumidor. Duas escolhas ruins existiam: duplicar (duas versões divergem na primeira
mudança) ou a ingestão importar da entrega (dependência ao contrário — a entrega LÊ o que a
ingestão escreve, então a ingestão não pode depender dela). O módulo separado é a terceira:
os dois dependem de uma folha, e nada depende dos dois.

CONTRATO: NUNCA LEVANTA EXCEÇÃO
===============================
Aviso que derruba o job que ele deveria vigiar é pior que aviso nenhum: transformaria um
problema pequeno ("a rodada está lenta") em um grande ("a ingestão parou"). Toda falha aqui
volta como `{"ok": False, "erro": ...}` e quem chamou segue o seu caminho.
"""
from __future__ import annotations

import os


def avisa_no_dm(linhas_texto: list | None, resumo: str,
                poster=None, canal: str = "") -> dict:
    """Manda `resumo` (e opcionalmente um bloco de código com `linhas_texto`) para o DM.

    `poster` e `canal` são injetáveis para o teste rodar sem Slack.
    """
    if poster is None:
        try:
            from src.monitoring.slack_client import post_blocks as poster
        except Exception as e:                            # sem o pacote, segue a vida
            return {"ok": False, "erro": f"import: {e}"}
    # Mesma cadeia de resolução do resto do projeto (`cost_alert`, `app.py`), incluindo o
    # mesmo último recurso fixo. O ID do DM não é segredo, e deixá-lo aqui evita o pior
    # caso: variável esquecida no job faz o aviso virar um no-op silencioso, que é
    # exatamente o defeito que esta função existe para consertar.
    canal = canal or os.getenv("SLACK_USER_DM") or os.getenv(
        "SLACK_VALIDATION_DM_CHANNEL") or "D0A9USV3XEX"
    blocos = [{"type": "section",
               "text": {"type": "mrkdwn", "text": resumo}}]
    if linhas_texto:
        blocos.append({"type": "section",
                       "text": {"type": "mrkdwn",
                                "text": "```\n" + "\n".join(linhas_texto) + "\n```"}})
    try:
        return poster(canal, blocos, resumo)
    except Exception as e:                                # contrato: nunca derruba
        return {"ok": False, "erro": str(e)}
