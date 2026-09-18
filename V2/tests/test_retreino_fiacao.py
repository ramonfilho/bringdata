"""A fiação das etapas 3, 4 e 5 do treino contínuo está no lugar (18/09/2026): o treino
tem a flag --pos-treino, o orquestrador de alertas chama o gatilho no score_drift, o deploy
troca a imagem do job em lockstep e o setup do job cria o cron mensal."""
from pathlib import Path

V2 = Path(__file__).resolve().parents[1]
RAIZ = V2.parent


def _t(p):
    return p.read_text(encoding="utf-8")


def test_treino_tem_a_flag_e_chama_o_pos_treino():
    s = _t(V2 / "src" / "train_pipeline.py")
    assert "'--pos-treino'" in s and "from src.retreino.pos_treino import executar" in s


def test_score_drift_chama_o_gatilho_sem_derrubar_o_ciclo():
    s = _t(V2 / "src" / "monitoring" / "critical_alerts.py")
    assert "disparar_retreino" in s and "rule_name == 'score_drift'" in s


def test_deploy_atualiza_a_imagem_do_job_de_retreino():
    s = _t(RAIZ / ".github" / "workflows" / "deploy.yml")
    assert 'gcloud run jobs update retreino-mensal --image="$IMG"' in s


def test_setup_do_job_tem_cron_mensal_slack_e_pos_treino():
    s = _t(RAIZ / "scripts" / "setup_retreino_job.sh")
    assert "retreino-mensal-cron" in s and '"0 6 1 * *"' in s
    assert "--pos-treino" in s and "SLACK_BOT_TOKEN=slack-bot-token:latest" in s and "github-pr-token" in s
