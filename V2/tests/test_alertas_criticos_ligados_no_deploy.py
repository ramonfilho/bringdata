"""
Os 9 alertas críticos não podem depender de env setada na mão.

Contexto (auditoria de 17/08/2026, conferida no ar em 28/08/2026): o card dizia que
os alertas estavam MUDOS em produção. Estavam ligados. A variável
`CRITICAL_ALERTS_DRY_RUN=false` existia no serviço desde ~15/08, setada
manualmente, e sobreviveu a cada deploy porque o deploy usa `--update-env-vars`,
que MESCLA em vez de substituir.

O risco real é o outro lado dessa moeda. O código nasce mudo: os dois pontos que
leem a flag (`src/monitoring/critical_alerts.py`) usam default `'true'`, e em
dry-run o despachante só loga "[DRY-RUN] enviaria DM". Recriar o serviço do zero,
ou um deploy com `--set-env-vars`, devolveria as 9 regras ao silêncio sem ninguém
ver, porque alerta que não dispara não tem como avisar que parou.

O contrato deste arquivo é uma disjunção, e não a forma exata da correção:
**ou o código já nasce ligado, ou o script de deploy pina o valor.** Um dos dois
precisa valer. Enquanto nenhum valer, a garantia mora só na nuvem.
"""

import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
_CONFIG_SH = _RAIZ / "V2" / "api" / "lib" / "config.sh"
_CRITICAL_ALERTS = _RAIZ / "V2" / "src" / "monitoring" / "critical_alerts.py"

_FLAG = "CRITICAL_ALERTS_DRY_RUN"


def _corpo_do_build_env_vars() -> str:
    """Só as linhas EXECUTÁVEIS da função que monta as env vars do deploy.

    Duas exclusões, e as duas já mordiam: menção fora da função não liga alerta
    nenhum, e linha comentada muito menos. A primeira versão deste teste passava
    com a linha comentada, porque o `# ` na frente não atrapalha o regex.
    """
    texto = _CONFIG_SH.read_text(encoding="utf-8")
    inicio = texto.index("build_env_vars() {")
    fim = texto.index("\n}\n", inicio)
    corpo = texto[inicio:fim]
    return "\n".join(
        linha for linha in corpo.splitlines() if not linha.lstrip().startswith("#")
    )


def _pinado_no_deploy() -> bool:
    corpo = _corpo_do_build_env_vars()
    return re.search(
        rf'ENV_VARS="\$ENV_VARS,{_FLAG}=\$\{{{_FLAG}:-false\}}"', corpo
    ) is not None


def _defaults_do_codigo() -> list[str]:
    texto = _CRITICAL_ALERTS.read_text(encoding="utf-8")
    return re.findall(rf"os\.environ\.get\(\s*'{_FLAG}'\s*,\s*'(\w+)'\s*\)", texto)


def test_producao_nao_depende_de_env_setada_na_mao():
    defaults = _defaults_do_codigo()
    assert defaults, (
        f"não achei nenhuma leitura de {_FLAG} em critical_alerts.py — "
        "se a flag mudou de nome, este teste precisa acompanhar"
    )
    codigo_ja_nasce_ligado = all(d == "false" for d in defaults)
    assert _pinado_no_deploy() or codigo_ja_nasce_ligado, (
        f"{_FLAG} não está pinado em build_env_vars e o código nasce em dry-run "
        f"(defaults lidos: {defaults}). Nessa combinação, um serviço recriado do "
        "zero sobe com as 9 regras avaliando e nenhuma DM saindo, em silêncio."
    )


def test_o_pin_vale_para_o_valor_ligado_e_nao_para_qualquer_valor():
    """Pinar `=true` seria pior que não pinar: fixaria o silêncio no deploy."""
    corpo = _corpo_do_build_env_vars()
    if _FLAG not in corpo:
        return
    assert not re.search(rf"{_FLAG}=\$\{{{_FLAG}:-true\}}", corpo), (
        f"build_env_vars está pinando {_FLAG} em 'true' (dry-run) como default "
        "de deploy — isso torna o silêncio dos alertas críticos permanente"
    )


def test_override_por_ambiente_continua_possivel():
    """Rollback consciente tem que existir: trava sem saída vira gambiarra."""
    if not _pinado_no_deploy():
        return
    corpo = _corpo_do_build_env_vars()
    assert f"${{{_FLAG}:-false}}" in corpo, (
        "o pin precisa ser da forma ${VAR:-false}, para que exportar "
        f"{_FLAG}=true no ambiente ainda desligue o envio em emergência"
    )
