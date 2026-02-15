"""
Orquestrador de Retreino Mensal - Smart Ads ML

Pipeline automatizado de retreino com validação, comparação e deploy condicional.

Arquitetura Hook-Based:
    - Reutiliza 100% do train_pipeline.py (zero duplicação!)
    - Injeta validation hook após feature engineering
    - Orquestrador mínimo: apenas coordenação de alto nível

Fluxo:
    Cloud Scheduler (mensal)
        
    Cloud Run Job: retreino-mensal
        
     STEP 1-3: train_pipeline.py (com validation hook injetado)
        Células 1-17: Extração + Preprocessing
        Célula 18: Feature Engineering
         VALIDATION HOOK (injected)
        Célula 18.5-20: Baseline + Encoding + Treino
        Retorna model_metadata
    
     STEP 4: Comparação Champion vs Challenger
     STEP 5: Decisão de deploy (auto/manual/reject)
     STEP 6: Deploy condicional
     STEP 7: Relatório + Notificações

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
        logger.info(f" Retreino Mensal iniciado - Execution ID: {self.execution_id}")

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
            logger.info(" Arquitetura Hook-Based:")
            logger.info("   - Reutiliza train_pipeline.py completo")
            logger.info("   - Validation hook injetado após feature engineering")
            logger.info("   - Zero duplicação de código!")

            # Criar quality gate hook (validação de dados antes de começar treino)
            def quality_gate_hook(missing_rates, df_pesquisa, df_vendas):
                """
                Hook de quality gate chamado pelo train_pipeline após consolidar dados.

                Valida mudanças em missing rates antes de gastar tempo treinando.

                Args:
                    missing_rates: Dict com taxas de ausência das colunas críticas
                    df_pesquisa: DataFrame consolidado de pesquisa
                    df_vendas: DataFrame consolidado de vendas

                Returns:
                    True para continuar treino, False para abortar
                """
                logger.info("\n" + "-" * 80)
                logger.info(" QUALITY GATE HOOK ATIVADO")
                logger.info("-" * 80)
                logger.info("Validando qualidade de dados antes de iniciar treino...")

                # Obter baseline do champion
                try:
                    model_path = get_active_model_path()
                    logger.info(f"   Champion: {model_path}")

                    # Carregar metadata do champion
                    import json
                    import glob

                    # Buscar arquivo de metadata (pode ter sufixo com nome do modelo)
                    metadata_pattern = str(Path(model_path) / 'model_metadata*.json')
                    metadata_files = glob.glob(metadata_pattern)

                    if not metadata_files:
                        logger.warning(f"     Metadata não encontrado em: {model_path}")
                        logger.info(f"   Continuando sem comparação (primeiro treino?)")
                        return True

                    metadata_path = metadata_files[0]  # Pegar primeiro (deve ser único)
                    logger.info(f"   Metadata encontrado: {Path(metadata_path).name}")

                    with open(metadata_path, 'r') as f:
                        champion_metadata = json.load(f)

                    champion_quality = champion_metadata.get('data_quality_baseline', {})
                    champion_missing = champion_quality.get('missing_rates', {})

                    if not champion_missing:
                        logger.info(f"   Champion não tem baseline - continuando sem comparação")
                        return True

                except Exception as e:
                    logger.warning(f"     Erro ao carregar champion: {e}")
                    logger.info(f"   Continuando sem comparação")
                    return True

                # Comparar missing rates
                THRESHOLD_WARNING = 0.10  # 10pp
                THRESHOLD_CRITICAL = 0.20  # 20pp

                alerts = []
                for col in missing_rates:
                    current_rate = missing_rates[col]
                    baseline_rate = champion_missing.get(col, 0.0)
                    diff = current_rate - baseline_rate

                    if abs(diff) > THRESHOLD_CRITICAL:
                        severity = " CRÍTICO"
                        alerts.append((severity, col, baseline_rate, current_rate, diff, True))
                    elif abs(diff) > THRESHOLD_WARNING:
                        severity = "  ALERTA"
                        alerts.append((severity, col, baseline_rate, current_rate, diff, False))

                if alerts:
                    logger.warning(f"\n{'='*80}")
                    logger.warning("  MUDANÇAS DETECTADAS EM QUALIDADE DE DADOS")
                    logger.warning(f"{'='*80}")
                    logger.warning(f"\n{'SEVERIDADE':<12} {'COLUNA':<45} {'BASELINE':>10} {'ATUAL':>10} {'DIFF':>10}")
                    logger.warning("-"*90)

                    has_critical = False
                    for severity, col, baseline, current, diff, is_critical in alerts:
                        col_display = col[:44] if len(col) > 44 else col
                        logger.warning(f"{severity:<12} {col_display:<45} {baseline:>9.1%} {current:>9.1%} {diff:>+9.1%}")
                        if is_critical:
                            has_critical = True

                    logger.warning("="*80)
                    logger.warning(f"\n POSSÍVEIS CAUSAS:")
                    logger.warning("   - Nova fonte de dados sem perguntas do formulário")
                    logger.warning("   - Mudança no formulário de captura")
                    logger.warning("   - Dados históricos adicionados de períodos anteriores")
                    logger.warning("   - Problema de integração/ETL")

                    if has_critical:
                        logger.error("\n QUALITY GATE FALHOU - Mudança crítica detectada (>20pp)")
                        logger.error("   Abortando treino para investigação")
                        return False
                    else:
                        logger.warning("\n  QUALITY GATE PASSOU COM AVISOS")
                        logger.warning("   Mudanças detectadas mas dentro do threshold crítico")
                        logger.warning("   Continuando com treino")
                        return True
                else:
                    logger.info(" Qualidade de dados estável (sem mudanças significativas)")
                    logger.info("-" * 80)
                    return True

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
                logger.info(" VALIDATION HOOK ATIVADO")
                logger.info("-" * 80)
                logger.info("Validando dados processados antes de encoding e treino...")

                try:
                    # Obter modelo ativo para baseline
                    model_path = get_active_model_path()
                    logger.info(f"   Baseline (champion): {model_path}")
                except Exception as e:
                    logger.warning(f"     Modelo ativo não encontrado: {e}")
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

                # DEBUG: Imprimir TODOS os alertas (não só críticos)
                logger.info(f"\n TODOS OS ALERTAS DETECTADOS ({len(result['validations'])} total):")
                for idx, validation in enumerate(result['validations'], 1):
                    severity_icon = "" if validation['severity'] == 'HIGH' else " " if validation['severity'] == 'MEDIUM' else "ℹ "
                    logger.info(f"\n{idx}. {severity_icon} [{validation['severity']}] {validation['type']}")
                    logger.info(f"   {validation['message']}")

                # Decidir se continua
                if result['has_critical_failures']:
                    logger.error("\n VALIDAÇÃO FALHOU - Abortando retreino")
                    logger.error(f"   Falhas críticas: {result['critical_count']}")
                    for validation in result['validations']:
                        if not validation['passed'] and validation['severity'] in self.config.get('validation', {}).get('critical_failures', ['HIGH']):
                            logger.error(f"    {validation['message']}")
                    return False  # Abortar treino

                logger.info("\n VALIDAÇÃO PASSOU - Prosseguindo com treino")
                logger.info("-" * 80)
                return True  # Continuar treino

            # Executar train_pipeline com validation hook injetado
            logger.info("\n  Executando train_pipeline.py com validation hook...")

            training_config = self.config.get('training', {})

            # Datas da API: calcular dinamicamente baseado no champion
            from datetime import datetime, timedelta

            # Data final: sempre hoje
            api_end_date = training_config.get('api_end_date', datetime.now().strftime('%Y-%m-%d'))

            # Data inicial: calcular dinamicamente
            if 'api_start_date' in training_config:
                # Se especificado no config, usar (útil para testes/debug)
                api_start_date = training_config['api_start_date']
                logger.info(f"    Usando api_start_date do config: {api_start_date}")
            else:
                # DEFAULT: Buscar última venda do champion e usar dia seguinte
                logger.info(f"    Calculando api_start_date dinamicamente...")

                try:
                    import json
                    import glob
                    model_path = get_active_model_path()
                    logger.info(f"      Champion model: {model_path}")

                    metadata_pattern = str(Path(model_path) / 'model_metadata*.json')
                    metadata_files = glob.glob(metadata_pattern)

                    if not metadata_files:
                        logger.error(f"       Metadata não encontrado em: {model_path}")
                        raise FileNotFoundError(
                            f"Metadata do champion não encontrado!\n"
                            f"Path procurado: {metadata_pattern}\n\n"
                            f"AÇÃO: Certifique-se que o modelo champion existe e tem metadata.\n"
                            f"       Se for o primeiro retreino, especifique api_start_date no config."
                        )

                    with open(metadata_files[0], 'r') as f:
                        champion_metadata = json.load(f)

                    # Pegar última venda do champion
                    period_end = champion_metadata.get('training_data', {}).get('temporal_split', {}).get('period_end')

                    if not period_end:
                        logger.error(f"       'period_end' não encontrado no metadata")
                        raise ValueError(
                            f"Metadata inválido: 'period_end' não encontrado!\n"
                            f"Arquivo: {metadata_files[0]}\n\n"
                            f"AÇÃO: O metadata do champion está corrompido ou desatualizado.\n"
                            f"       Re-treine o modelo ou especifique api_start_date no config."
                        )

                    # Usar DIA SEGUINTE à última venda (para não duplicar)
                    last_sale_date = datetime.strptime(period_end, '%Y-%m-%d')
                    api_start_date = (last_sale_date + timedelta(days=1)).strftime('%Y-%m-%d')

                    logger.info(f"      Última venda do champion: {period_end}")
                    logger.info(f"      Buscando dados NOVOS a partir de: {api_start_date}")

                    # Validar se há dados novos para treinar
                    days_since_last_train = (datetime.now() - last_sale_date).days
                    if days_since_last_train < 1:
                        logger.warning(f"\n{'='*80}")
                        logger.warning(f" ALERTA: Nenhum dado novo disponível!")
                        logger.warning(f"{'='*80}")
                        logger.warning(f"Última venda do champion: {period_end}")
                        logger.warning(f"Data atual: {datetime.now().strftime('%Y-%m-%d')}")
                        logger.warning(f"Dias desde último treino: {days_since_last_train}")
                        logger.warning(f"\nO modelo já está treinado com os dados mais recentes.")
                        logger.warning(f"Não há dados novos para retreinar.")
                        logger.warning(f"{'='*80}\n")

                        return {
                            'status': 'SKIPPED',
                            'reason': 'No new data available since last training',
                            'execution_id': self.execution_id,
                            'last_training_date': period_end,
                            'current_date': datetime.now().strftime('%Y-%m-%d')
                        }

                except (FileNotFoundError, ValueError) as e:
                    # Erros esperados: logar e abortar
                    logger.error(f"\n{'='*80}")
                    logger.error(f" ERRO: Não foi possível calcular api_start_date")
                    logger.error(f"{'='*80}")
                    logger.error(f"{str(e)}")
                    logger.error(f"{'='*80}\n")

                    return {
                        'status': 'ABORTED',
                        'reason': 'Cannot calculate api_start_date - no champion metadata',
                        'execution_id': self.execution_id,
                        'error': str(e)
                    }

                except Exception as e:
                    # Erros inesperados: logar com stack trace e abortar
                    logger.error(f"\n{'='*80}")
                    logger.error(f" ERRO INESPERADO ao calcular api_start_date")
                    logger.error(f"{'='*80}")
                    logger.error(f"{str(e)}", exc_info=True)
                    logger.error(f"{'='*80}\n")

                    return {
                        'status': 'ERROR',
                        'reason': 'Unexpected error calculating api_start_date',
                        'execution_id': self.execution_id,
                        'error': str(e)
                    }

            logger.info(f"\n    Período de dados API: {api_start_date} a {api_end_date}")

            # ========================================
            # VALIDAR ARQUIVO TMB ATUALIZADO
            # ========================================
            logger.info(f"\n Verificando arquivo TMB...")

            import glob
            # Buscar arquivo TMB na pasta de treino (um nível acima do V2)
            tmb_pattern = str(Path(__file__).parent.parent.parent.parent / 'data' / 'devclub' / 'treino' / 'tmb.xlsx')
            tmb_files = glob.glob(tmb_pattern)

            if not tmb_files:
                logger.error(f"\n{'='*80}")
                logger.error(f" ERRO CRÍTICO: Arquivo TMB não encontrado!")
                logger.error(f"{'='*80}")
                logger.error(f"Path esperado: {tmb_pattern}")
                logger.error(f"\n AÇÃO NECESSÁRIA:")
                logger.error(f"   1. Baixar arquivo TMB atualizado com vendas de {api_start_date} a {api_end_date}")
                logger.error(f"   2. Colocar arquivo em: data/devclub/treino/tmb.xlsx")
                logger.error(f"   3. Executar retreino novamente")
                logger.error(f"{'='*80}\n")

                return {
                    'status': 'ABORTED',
                    'reason': 'TMB file not found',
                    'execution_id': self.execution_id,
                    'expected_path': tmb_pattern,
                    'api_period': f"{api_start_date} a {api_end_date}"
                }

            # Verificar data de modificação do arquivo TMB
            import os
            from datetime import datetime, timedelta
            tmb_file = tmb_files[0]
            tmb_mod_time = datetime.fromtimestamp(os.path.getmtime(tmb_file))
            days_since_mod = (datetime.now() - tmb_mod_time).days

            logger.info(f"   Arquivo TMB encontrado: {Path(tmb_file).name}")
            logger.info(f"   Última modificação: {tmb_mod_time.strftime('%Y-%m-%d %H:%M:%S')} ({days_since_mod} dias atrás)")

            # Verificar se arquivo é mais antigo que o período de retreino
            api_start_dt = datetime.strptime(api_start_date, '%Y-%m-%d')
            if tmb_mod_time < api_start_dt:
                logger.warning(f"\n{'='*80}")
                logger.warning(f" ALERTA: Arquivo TMB pode estar desatualizado!")
                logger.warning(f"{'='*80}")
                logger.warning(f"Última modificação do arquivo: {tmb_mod_time.strftime('%Y-%m-%d')}")
                logger.warning(f"Período de retreino: {api_start_date} a {api_end_date}")
                logger.warning(f"\nO arquivo TMB foi modificado ANTES do período de retreino.")
                logger.warning(f"Verifique se o arquivo contém vendas até {api_end_date}.")
                logger.warning(f"\n AÇÃO RECOMENDADA:")
                logger.warning(f"   1. Baixar arquivo TMB mais recente (até {api_end_date})")
                logger.warning(f"   2. Substituir: data/devclub/treino/tmb.xlsx")
                logger.warning(f"   3. Executar retreino novamente")
                logger.warning(f"\n Para continuar mesmo assim, pressione Ctrl+C e re-execute.")
                logger.warning(f"{'='*80}\n")

                return {
                    'status': 'ABORTED',
                    'reason': 'TMB file potentially outdated - modified before retraining period',
                    'execution_id': self.execution_id,
                    'tmb_last_modified': tmb_mod_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'api_period': f"{api_start_date} a {api_end_date}",
                    'warning': 'TMB file was last modified before the retraining period starts'
                }

            logger.info(f" Arquivo TMB validado OK\n")

            # Verbosity: config > default (normal)
            verbosity = training_config.get('verbosity', 'normal')
            if hasattr(self, 'verbosity_override'):
                verbosity = self.verbosity_override

            logger.info(f"    Verbosity do pipeline: {verbosity}")

            challenger_metadata = train_main(
                initial_matching=training_config.get('initial_matching', 'email_telefone'),
                save_files=True,  # Sempre salvar no retreino mensal
                split_method=training_config.get('split_method', 'temporal_leads'),
                tune_hyperparams=training_config.get('tune_hyperparams', False),
                grid_size=training_config.get('grid_size', 'small'),
                tmb_risk_filter=training_config.get('tmb_risk_filter', 'all'),  #  FILTRO DE RISCO TMB
                set_active=False,  # NÃO ativar automaticamente (decisão vem depois)
                quality_gate_hook=quality_gate_hook,  #  INJETA QUALITY GATE (antes de treinar)
                validation_hook=validation_hook,  #  INJETA VALIDAÇÃO (após feature engineering)
                include_api_data=True,  #  RETREINO: buscar dados novos da API
                api_start_date=api_start_date,
                api_end_date=api_end_date,
                output_subdir='retraining',  #  LOGS vão para outputs/retraining/
                verbosity=verbosity  #  CONTROLE DE LOGS: configurável via config/CLI
            )

            # Verificar se foi abortado pelo quality gate
            if challenger_metadata.get('status') == 'ABORTED_BY_QUALITY_GATE':
                logger.error(" Treino abortado pelo quality gate (mudanças críticas em missing rates)")
                return {
                    'status': 'ABORTED',
                    'reason': 'Quality gate failed - critical changes in data quality',
                    'execution_id': self.execution_id,
                    'missing_rates': challenger_metadata.get('missing_rates', {})
                }

            # Verificar se foi abortado pela validação
            if challenger_metadata.get('status') == 'ABORTED_BY_VALIDATION':
                logger.error(" Treino abortado pela validação")
                return {
                    'status': 'ABORTED',
                    'reason': 'Data validation failed',
                    'execution_id': self.execution_id,
                    'validation_result': self.validation_result
                }

            # Verificar se treino falhou
            if not challenger_metadata:
                logger.error(" Falha no treinamento do challenger")
                return {
                    'status': 'FAILED',
                    'reason': 'Training failed',
                    'execution_id': self.execution_id
                }

            logger.info(f"\n Challenger treinado com sucesso")
            logger.info(f"   AUC: {challenger_metadata['performance_metrics']['auc']:.4f}")
            logger.info(f"   Monotonia: {challenger_metadata['performance_metrics']['monotonia_percentage']:.1f}%")

            # ========================================
            # STEP 4: COMPARAÇÃO (TODO - Sprint 2)
            # ========================================
            logger.info("\n" + "=" * 80)
            logger.info("STEP 4: COMPARAÇÃO CHAMPION VS CHALLENGER")
            logger.info("=" * 80)

            # TODO: Implementar comparação
            logger.info("  Comparação ainda não implementada")
            logger.info("   Sprint 2: Implementar model_comparison.py")

            # ========================================
            # STEP 5: DECISÃO (TODO - Sprint 2)
            # ========================================
            logger.info("\n" + "=" * 80)
            logger.info("STEP 5: DECISÃO DE DEPLOY")
            logger.info("=" * 80)

            # TODO: Implementar decisão
            logger.info("  Decisão de deploy ainda não implementada")
            logger.info("   Sprint 2: Implementar lógica de auto-approve/manual/reject")

            # ========================================
            # STEP 6: DEPLOY (TODO - Sprint 3)
            # ========================================
            logger.info("\n" + "=" * 80)
            logger.info("STEP 6: DEPLOY DO MODELO")
            logger.info("=" * 80)

            # TODO: Implementar deploy condicional
            logger.info("  Deploy condicional ainda não implementado")
            logger.info("   Sprint 3: Implementar atualização de active_model.yaml")

            # ========================================
            # STEP 7: RELATÓRIO (TODO - Sprint 3)
            # ========================================
            logger.info("\n" + "=" * 80)
            logger.info("STEP 7: RELATÓRIO E NOTIFICAÇÕES")
            logger.info("=" * 80)

            # TODO: Implementar relatório
            logger.info("  Relatório ainda não implementado")
            logger.info("   Sprint 3: Implementar geração de relatório Excel e Slack")

            # ========================================
            # RESULTADO FINAL
            # ========================================
            logger.info("\n" + "=" * 80)
            logger.info(" RETREINO MENSAL CONCLUÍDO (SPRINT 1.1)")
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
            logger.error(f" Erro no retreino mensal: {e}", exc_info=True)
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
    parser.add_argument(
        '--verbosity',
        type=str,
        choices=['silent', 'minimal', 'normal', 'debug'],
        default=None,
        help='Nível de verbosidade dos logs (sobrescreve config): silent, minimal, normal, debug'
    )
    args = parser.parse_args()

    # Banner
    logger.info("SMART ADS - RETREINO MENSAL AUTOMATIZADO")
    logger.info("Arquitetura: Hook-Based (Reutiliza train_pipeline.py)")
    logger.info(f"Config: {args.config}")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")

    # Verificar se config existe
    if not os.path.exists(args.config):
        logger.error(f" Arquivo de configuração não encontrado: {args.config}")
        logger.info(f"   Crie o arquivo configs/retreino_mensal.yaml")
        sys.exit(1)

    # Executar retreino
    orquestrador = RetreinoMensal(args.config)

    # Aplicar verbosity override via CLI se fornecido
    if args.verbosity:
        orquestrador.verbosity_override = args.verbosity
        logger.info(f" Verbosity CLI override: {args.verbosity}")

    resultado = orquestrador.run()

    # Exibir resultado
    logger.info("RESULTADO FINAL")
    logger.info(f"Status: {resultado['status']}")
    logger.info(f"Execution ID: {resultado['execution_id']}")
    if 'notes' in resultado:
        logger.info(f"Notas: {resultado['notes']}")

    # Exit code
    sys.exit(0 if resultado['status'].startswith('SUCCESS') else 1)


if __name__ == "__main__":
    main()
