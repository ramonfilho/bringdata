"""
core/startup_checks.py — validações loud no startup da API.

Cobre dois itens de safeguard que protegem contra "API zumbi" (startup OK
mas modelo errado/incompleto):

T3-6 (Validação MODEL_PATH): confirma que o caminho do modelo existe e
contém os artefatos esperados (model serializado + feature_names). Se
algum estiver ausente, aborta a inicialização em vez de continuar.

T3-7 (Reconciliação run_id): confirma que o run_id efetivamente carregado
em runtime pelo predictor bate com o run_id declarado em
configs/active_models/{client}.yaml. Detecta cenários onde a imagem
Docker foi baked com um run_id mas o YAML em runtime aponta para outro
(deploy desalinhado).

Falha em qualquer check ⇒ logger.error + raise RuntimeError. A API não
deve aceitar tráfego se essa validação não passou.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def validate_model_loaded(predictor, expected_run_id: Optional[str], client_id: str = "unknown") -> None:
    """Valida que o predictor está corretamente inicializado.

    Args:
        predictor: instância de LeadScoringPredictor após load_model()
        expected_run_id: run_id esperado, lido de active_models/{client}.yaml.
            Se None (modo de fallback ou modo local), apenas T3-6 é avaliado.
        client_id: para identificar o cliente no log (multi-cliente).

    Raises:
        RuntimeError: se T3-6 ou T3-7 falharem.
    """
    failures = []

    # T3-6: artefatos do modelo carregaram
    if predictor.model is None:
        failures.append("[T3-6] predictor.model é None — modelo não foi carregado em load_model()")

    if not getattr(predictor, "feature_names", None):
        failures.append("[T3-6] predictor.feature_names vazio ou None — feature_registry não foi lido")

    # T3-7: run_id em runtime bate com YAML
    if expected_run_id is not None:
        runtime_run_id = getattr(predictor, "mlflow_run_id", None)
        if runtime_run_id is None:
            failures.append(
                f"[T3-7] YAML pede run_id={expected_run_id} mas predictor.mlflow_run_id é None "
                f"(predictor caiu em modo de arquivos locais — deploy possivelmente desalinhado)"
            )
        elif runtime_run_id != expected_run_id:
            failures.append(
                f"[T3-7] divergência de run_id: YAML={expected_run_id}, "
                f"predictor.mlflow_run_id={runtime_run_id}. "
                f"Imagem Docker pode estar baked com run_id diferente do YAML."
            )

    if failures:
        msg = (
            f"❌ Startup checks falharam para client_id={client_id}:\n  - "
            + "\n  - ".join(failures)
            + "\n\nA API não deve aceitar tráfego com modelo inválido. Investigue e re-deploy."
        )
        logger.error(msg)
        raise RuntimeError(msg)

    n_features = len(predictor.feature_names)
    run_id_short = (expected_run_id or "(local)")[:8]
    logger.info(
        f"✓ Startup checks OK | client={client_id} | run_id={run_id_short}... | "
        f"features={n_features} | model={type(predictor.model).__name__}"
    )
