"""
Orquestrador de Retreino Mensal - Smart Ads ML

Pipeline automatizado de retreino com validação, comparação e deploy condicional.

Arquitetura Hook-Based:
    - Reutiliza 100% do train_pipeline.py (zero duplicação!)
    - Injeta validation hook após feature engineering
    - Orquestrador mínimo: apenas coordenação de alto nível

Fluxo:
    Cloud Scheduler (mensal)
        ↓
    Cloud Run Job: retreino-mensal
        ↓
    ├─ STEP 1-3: train_pipeline.py (com validation hook injetado)
    │   ├─ Células 1-17: Extração + Preprocessing
    │   ├─ Célula 18: Feature Engineering
    │   ├─ 🔧 VALIDATION HOOK (injected)
    │   ├─ Célula 18.5-20: Baseline + Encoding + Treino
    │   └─ Retorna model_metadata
    │
    ├─ STEP 4: Comparação Champion vs Challenger
    ├─ STEP 5: Decisão de deploy (auto/manual/reject)
    ├─ STEP 6: Deploy condicional
    └─ STEP 7: Relatório + Notificações

Uso:
    # Local (desenvolvimento)
    python src/retrain/retraining_orchestrator.py --config configs/retreino_mensal.yaml

    # Cloud Run (produção)
    gcloud run jobs execute retreino-mensal --region us-central1
"""

import os
import sys
import yaml
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

# Adicionar V2/ ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Imports do projeto
from src.train_pipeline import main as train_main
from src.retrain.data_validation import RetrainingDataValidator, get_active_model_path

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class RetreinoMensal:
    """Orquestrador de retreino mensal automatizado."""

    def __init__(self, config_path: str):
        """
        Inicializa orquestrador.

        Args:
            config_path: Caminho para configs/retreino_mensal.yaml
        """
        self.config = self._load_config(config_path)
        self.execution_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.validation_result = None  # Preenchido pelo hook
        logger.info(f"🚀 Retreino Mensal iniciado - Execution ID: {self.execution_id}")

    def _load_config(self, config_path: str) -> dict:
        """Carrega configuração do retreino."""
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)

    def run(self) -> Dict:
        """
        Executa pipeline completo de retreino.

        Returns:
            Dict com resultado da execução
        """
        try:
            # ========================================
            # STEP 1-3: TREINO COM VALIDAÇÃO (HOOK-BASED)
            # ========================================
            logger.info("\n" + "=" * 80)
            logger.info("STEP 1-3: EXTRAÇÃO + PREPROCESSING + VALIDAÇÃO + TREINO")
            logger.info("=" * 80)
            logger.info("📝 Arquitetura Hook-Based:")
            logger.info("   - Reutiliza train_pipeline.py completo")
            logger.info("   - Validation hook injetado após feature engineering")
            logger.info("   - Zero duplicação de código!")

            # Criar validation hook
            def validation_hook(dataset_fe):
                """
                Hook de validação chamado pelo train_pipeline após feature engineering.

                Args:
                    dataset_fe: DataFrame após feature engineering (célula 18)

                Returns:
                    True para continuar treino, False para abortar
                """
                logger.info("\n" + "-" * 80)
                logger.info("🔧 VALIDATION HOOK ATIVADO")
                logger.info("-" * 80)
                logger.info("Validando dados processados antes de encoding e treino...")

                try:
                    # Obter modelo ativo para baseline
                    model_path = get_active_model_path()
                    logger.info(f"   Baseline (champion): {model_path}")
                except Exception as e:
                    logger.warning(f"   ⚠️  Modelo ativo não encontrado: {e}")
                    logger.warning(f"   Continuando sem drift detection (primeiro treino?)")
                    model_path = None

                # Criar validador
                validator = RetrainingDataValidator(
                    model_path=model_path,
                    config=self.config.get('validation', {})
                )

                # Executar validações
                result = validator.validate(dataset_fe)
                self.validation_result = result

                # Decidir se continua
                if result['has_critical_failures']:
                    logger.error("\n❌ VALIDAÇÃO FALHOU - Abortando retreino")
                    logger.error(f"   Falhas críticas: {result['critical_count']}")
                    for validation in result['validations']:
                        if not validation['passed'] and validation['severity'] in self.config.get('validation', {}).get('critical_failures', ['HIGH']):
                            logger.error(f"   • {validation['message']}")
                    return False  # Abortar treino

                logger.info("\n✅ VALIDAÇÃO PASSOU - Prosseguindo com treino")
                logger.info("-" * 80)
                return True  # Continuar treino

            # Executar train_pipeline com validation hook injetado
            logger.info("\n▶️  Executando train_pipeline.py com validation hook...")

            training_config = self.config.get('training', {})

            # Datas da API: buscar da config ou usar últimos 60 dias
            from datetime import datetime, timedelta
            api_end_date = training_config.get('api_end_date', datetime.now().strftime('%Y-%m-%d'))

            if 'api_start_date' in training_config:
                api_start_date = training_config['api_start_date']
            else:
                # Default: 60 dias atrás
                start_dt = datetime.now() - timedelta(days=60)
                api_start_date = start_dt.strftime('%Y-%m-%d')

            logger.info(f"   📅 Período de dados API: {api_start_date} a {api_end_date}")

            challenger_metadata = train_main(
                initial_matching=training_config.get('initial_matching', 'email_telefone'),
                save_files=True,  # Sempre salvar no retreino mensal
                split_method=training_config.get('split_method', 'temporal_leads'),
                tune_hyperparams=training_config.get('tune_hyperparams', False),
                grid_size=training_config.get('grid_size', 'small'),
                tmb_risk_filter=training_config.get('tmb_risk_filter', 'all'),  # ← FILTRO DE RISCO TMB
                set_active=False,  # NÃO ativar automaticamente (decisão vem depois)
                validation_hook=validation_hook,  # ← INJETA VALIDAÇÃO
                include_api_data=True,  # ← RETREINO: buscar dados novos da API
                api_start_date=api_start_date,
                api_end_date=api_end_date,
                output_subdir='retraining'  # ← LOGS vão para outputs/retraining/
            )

            # Verificar se foi abortado pela validação
            if challenger_metadata.get('status') == 'ABORTED_BY_VALIDATION':
                logger.error("❌ Treino abortado pela validação")
                return {
                    'status': 'ABORTED',
                    'reason': 'Data validation failed',
                    'execution_id': self.execution_id,
                    'validation_result': self.validation_result
                }

            # Verificar se treino falhou
            if not challenger_metadata:
                logger.error("❌ Falha no treinamento do challenger")
                return {
                    'status': 'FAILED',
                    'reason': 'Training failed',
                    'execution_id': self.execution_id
                }

            logger.info(f"\n✅ Challenger treinado com sucesso")
            logger.info(f"   AUC: {challenger_metadata['performance_metrics']['auc']:.4f}")
            logger.info(f"   Monotonia: {challenger_metadata['performance_metrics']['monotonia_percentage']:.1f}%")

            # ========================================
            # STEP 4: COMPARAÇÃO (TODO - Sprint 2)
            # ========================================
            logger.info("\n" + "=" * 80)
            logger.info("STEP 4: COMPARAÇÃO CHAMPION VS CHALLENGER")
            logger.info("=" * 80)

            # TODO: Implementar comparação
            logger.info("⚠️  Comparação ainda não implementada")
            logger.info("   Sprint 2: Implementar model_comparison.py")

            # ========================================
            # STEP 5: DECISÃO (TODO - Sprint 2)
            # ========================================
            logger.info("\n" + "=" * 80)
            logger.info("STEP 5: DECISÃO DE DEPLOY")
            logger.info("=" * 80)

            # TODO: Implementar decisão
            logger.info("⚠️  Decisão de deploy ainda não implementada")
            logger.info("   Sprint 2: Implementar lógica de auto-approve/manual/reject")

            # ========================================
            # STEP 6: DEPLOY (TODO - Sprint 3)
            # ========================================
            logger.info("\n" + "=" * 80)
            logger.info("STEP 6: DEPLOY DO MODELO")
            logger.info("=" * 80)

            # TODO: Implementar deploy condicional
            logger.info("⚠️  Deploy condicional ainda não implementado")
            logger.info("   Sprint 3: Implementar atualização de active_model.yaml")

            # ========================================
            # STEP 7: RELATÓRIO (TODO - Sprint 3)
            # ========================================
            logger.info("\n" + "=" * 80)
            logger.info("STEP 7: RELATÓRIO E NOTIFICAÇÕES")
            logger.info("=" * 80)

            # TODO: Implementar relatório
            logger.info("⚠️  Relatório ainda não implementado")
            logger.info("   Sprint 3: Implementar geração de relatório Excel e Slack")

            # ========================================
            # RESULTADO FINAL
            # ========================================
            logger.info("\n" + "=" * 80)
            logger.info("✅ RETREINO MENSAL CONCLUÍDO (SPRINT 1.1)")
            logger.info("=" * 80)
            logger.info(f"Execution ID: {self.execution_id}")
            logger.info(f"Arquitetura: Hook-Based (zero duplicação!)")
            logger.info(f"Status: Sprint 1.1 - Treino + Validação via Hook")
            logger.info(f"\nPróximos passos:")
            logger.info(f"   - Sprint 2: Implementar comparação e decisão")
            logger.info(f"   - Sprint 3: Implementar deploy condicional")

            return {
                'status': 'SUCCESS_SPRINT1.1',
                'execution_id': self.execution_id,
                'validation_result': self.validation_result,
                'challenger_metadata': challenger_metadata,
                'notes': 'Sprint 1.1: Treino + Validação via hook (arquitetura hook-based implementada!)'
            }

        except Exception as e:
            logger.error(f"❌ Erro no retreino mensal: {e}", exc_info=True)
            return {
                'status': 'ERROR',
                'execution_id': self.execution_id,
                'error': str(e)
            }

    # ========================================
    # MÉTODOS FUTUROS (Sprint 2-3)
    # ========================================

    def _load_champion_metadata(self) -> Dict:
        """TODO Sprint 2: Carregar metadata do modelo champion."""
        raise NotImplementedError("Sprint 2")

    def _compare_models(self, champion_metadata: Dict, challenger_metadata: Dict) -> Dict:
        """TODO Sprint 2: Comparar champion vs challenger."""
        raise NotImplementedError("Sprint 2")

    def _decide_deployment(self, comparison: Dict) -> str:
        """TODO Sprint 2: Decidir se faz deploy (AUTO_APPROVE/HUMAN_APPROVAL/REJECT)."""
        raise NotImplementedError("Sprint 2")

    def _deploy_model(self, challenger_metadata: Dict) -> bool:
        """TODO Sprint 3: Deploy do modelo (atualizar active_model.yaml)."""
        raise NotImplementedError("Sprint 3")

    def _generate_report(self, validation_result: Dict, comparison: Dict) -> Dict:
        """TODO Sprint 3: Gerar relatório Excel."""
        raise NotImplementedError("Sprint 3")

    def _upload_to_gcs(self, report: Dict) -> str:
        """TODO Sprint 3: Upload relatório para Cloud Storage."""
        raise NotImplementedError("Sprint 3")


def main():
    """Entry point do script."""
    parser = argparse.ArgumentParser(
        description='Orquestrador de Retreino Mensal - Smart Ads ML'
    )
    parser.add_argument(
        '--config',
        type=str,
        default='configs/retreino_mensal.yaml',
        help='Caminho para arquivo de configuração (default: configs/retreino_mensal.yaml)'
    )
    args = parser.parse_args()

    # Banner
    print("\n" + "=" * 80)
    print("SMART ADS - RETREINO MENSAL AUTOMATIZADO")
    print("Arquitetura: Hook-Based (Reutiliza train_pipeline.py)")
    print("=" * 80)
    print(f"Config: {args.config}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 80 + "\n")

    # Verificar se config existe
    if not os.path.exists(args.config):
        logger.error(f"❌ Arquivo de configuração não encontrado: {args.config}")
        logger.info(f"   Crie o arquivo configs/retreino_mensal.yaml")
        sys.exit(1)

    # Executar retreino
    orquestrador = RetreinoMensal(args.config)
    resultado = orquestrador.run()

    # Exibir resultado
    print("\n" + "=" * 80)
    print("RESULTADO FINAL")
    print("=" * 80)
    print(f"Status: {resultado['status']}")
    print(f"Execution ID: {resultado['execution_id']}")
    if 'notes' in resultado:
        print(f"Notas: {resultado['notes']}")
    print("=" * 80 + "\n")

    # Exit code
    sys.exit(0 if resultado['status'].startswith('SUCCESS') else 1)


if __name__ == "__main__":
    main()
