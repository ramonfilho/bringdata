#!/usr/bin/env python3
"""Stop hook — ENFORÇA a regra mecânica da V2/CLAUDE.md: toda resposta do
assistente deve terminar com uma linha começando por "**Em uma frase:**".

Lê o JSON do Stop hook no stdin (tem transcript_path), acha a ÚLTIMA mensagem de
texto do assistant no transcript, e se ela NÃO contiver "**Em uma frase:**",
retorna decision=block → o harness não deixa a resposta encerrar e devolve a
reason pro modelo, que precisa reescrever com a linha. Se a linha estiver lá
(ou se não houver texto do assistant / input inválido), sai 0 (permite).

Detecção deliberadamente TOLERANTE (substring "**Em uma frase:**" em qualquer
linha) pra não dar falso-negativo e virar loop — o único risco real de loop é
não detectar a linha quando ela existe.
"""
import json
import sys
import time

MARKER = "**Em uma frase:**"
# O transcript é gravado bloco-a-bloco (thinking/text/tool_use viram entradas
# JSONL separadas) e o Stop hook pode disparar ANTES do bloco de texto final ter
# sido persistido em disco (race de flush) — foi o que causou o 1º falso-positivo
# (a mensagem TINHA a linha, mas o hook leu um texto anterior). Por isso relemos o
# transcript algumas vezes antes de decidir bloquear: numa msg conforme e já
# gravada, a 1ª leitura já acha a linha (sem atraso); só quando falta é que espera.
_RETRIES = 8
_SLEEP = 0.25


def _texts_from_obj(obj):
    """Extrai os blocos de texto de uma entrada de transcript do assistant."""
    if not isinstance(obj, dict):
        return []
    if obj.get("type") != "assistant":
        return []
    msg = obj.get("message", obj)
    content = msg.get("content") if isinstance(msg, dict) else None
    out = []
    if isinstance(content, str):
        out.append(content)
    elif isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                t = b.get("text", "")
                if isinstance(t, str):
                    out.append(t)
    return out


def _last_assistant_text(path):
    """Última mensagem de texto do assistant no transcript (ou None). Cada bloco
    (thinking/text/tool_use) é uma entrada JSONL própria; junta só os blocos de
    texto e devolve o texto da última entrada de assistant que tiver texto."""
    last_text = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                texts = _texts_from_obj(obj)
                joined = "\n".join(t for t in texts if t).strip()
                if joined:
                    last_text = joined
    except Exception:
        return None
    return last_text


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # input ilegível — não bloqueia
    path = data.get("transcript_path")
    if not path:
        return 0
    # Retry-on-miss: numa msg conforme já gravada, a 1ª leitura acha a linha e
    # sai sem atraso; só quando falta (possível race de flush) é que espera e relê.
    last_text = None
    for i in range(_RETRIES):
        last_text = _last_assistant_text(path)
        if last_text is None:
            return 0  # nenhuma mensagem de texto do assistant — nada a checar
        if MARKER in last_text:
            return 0  # conforme
        if i < _RETRIES - 1:
            time.sleep(_SLEEP)
    print(json.dumps({
        "decision": "block",
        "reason": (
            "REGRA MECÂNICA (V2/CLAUDE.md): sua última resposta NÃO terminou com "
            "a linha obrigatória começando por \"**Em uma frase:**\". Reescreva a "
            "resposta e adicione, como ÚLTIMA linha, \"**Em uma frase:**\" seguida "
            "de UMA frase em português corrente traduzindo o que foi feito/o que "
            "significa. Toda resposta da sessão precisa dessa linha, sem exceção."
        ),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
