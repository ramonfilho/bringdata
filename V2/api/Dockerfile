# Dockerfile para API V2 Lead Scoring
# Base: Debian 12 (bookworm). O bullseye saiu de suporte em 31/08/2026 e o apt-get do
# build passou a dar 404 em maquina limpa (primeiro deploy pelo Actions, 14/09/2026).
# tests/test_dockerfile_base.py trava a volta para distro fora de suporte.
FROM python:3.10-slim-bookworm

# Metadados
LABEL maintainer="Smart Ads Team"
LABEL version="2.0"
LABEL description="API V2 para Lead Scoring com Random Forest"

# Criar usuário não-root para segurança
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Criar home directory para appuser (useradd -r não cria)
# Necessário para matplotlib e outras libs que precisam de cache
RUN mkdir -p /home/appuser/.config && \
    chown -R appuser:appuser /home/appuser

# Definir diretório de trabalho
WORKDIR /app

# Instalar dependências do sistema necessárias
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copiar arquivo de dependências primeiro (para cache do Docker)
COPY ./api/requirements.txt .

# Instalar dependências Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar estrutura do projeto V2
# Copiar a API
COPY ./api/ ./api/

# Copiar módulos src necessários
COPY ./src/ ./src/

# Copiar entrypoints de scripts/ (ex.: scripts/meta_audiences_sync.py, rodado pelo
# Cloud Run Job meta-audiences-daily). Sem isto, /app/scripts/ não existe na imagem.
COPY ./scripts/ ./scripts/

# Copiar configurações
COPY ./configs/ ./configs/

# ARG para path do modelo (lido do active_model.yaml pelo deploy.sh)
# Valor padrão para desenvolvimento local
ARG MODEL_PATH=mlruns_build

# Copiar artifacts dos modelos necessários (champion + variantes A/B se ativo).
# deploy_capi.sh monta mlruns_build/1/{run_id}/artifacts/ com apenas os runs
# necessários antes do build — mantém a imagem enxuta e suporta A/B out-of-the-box.
COPY ./${MODEL_PATH}/ ./mlruns/

# DESABILITADO: Copiar relatórios Meta CSV (será descontinuado)
# COPY ./files/validation/meta_reports/ ./files/validation/meta_reports/

# DESABILITADO: Copiar vendas (Guru Excel + TMB para fallback - será descontinuado)
# COPY ./files/validation/vendas/ ./files/validation/vendas/

# Definir variáveis de ambiente
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# DE QUAL COMMIT ESTA IMAGEM SAIU.
#
# O `.dockerignore` exclui `.git/`, e com razão: a pasta não serve pra nada em
# execução. O efeito colateral é que `core/git_info` devolvia None em produção — sem
# repositório não há a quem perguntar. Então o build ASSA a resposta aqui.
#
# Por que importa: em 14/08/2026 o job da referência rodava imagem de 31/07 enquanto a
# `main` estava duas versões à frente, e a única forma de descobrir foi conferir o
# digest da imagem à mão. Número que sai de código velho não tem como se denunciar;
# com o carimbo, toda linha gravada diz de onde veio.
#
# Vazio se o build não passar o argumento — e aí `versao_do_codigo()` devolve
# origem='desconhecida', que é honesto, em vez de fingir que sabe.
ARG APP_COMMIT=""
ARG APP_COMMIT_DIRTY=""
ENV APP_COMMIT=${APP_COMMIT}
ENV APP_COMMIT_DIRTY=${APP_COMMIT_DIRTY}
# Fix para matplotlib - usar diretório writable para cache
ENV MPLCONFIGDIR=/home/appuser/.config/matplotlib

# Criar diretório para relatórios de validação
RUN mkdir -p /app/vendas

# Dar permissões para o usuário appuser
RUN chown -R appuser:appuser /app

# Trocar para usuário não-root
USER appuser

# Expor a porta que a API usará
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health')" || exit 1

# Comando para iniciar o servidor
# Usar gunicorn com workers uvicorn para produção
CMD ["gunicorn", "api.app:app", \
     "--workers", "2", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8080", \
     "--timeout", "1200", \
     "--graceful-timeout", "1200", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]