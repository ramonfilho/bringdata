# Dockerfile para API V2 Lead Scoring
FROM python:3.10-slim-bullseye

# Metadados
LABEL maintainer="Smart Ads Team"
LABEL version="2.0"
LABEL description="API V2 para Lead Scoring com Random Forest"

# Criar usuário não-root para segurança
RUN groupadd -r appuser && useradd -r -g appuser appuser

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

# Copiar configurações
COPY ./configs/ ./configs/

# ARG para path do modelo (lido do active_model.yaml pelo deploy.sh)
# Valor padrão para desenvolvimento local
ARG MODEL_PATH=files/20260115_080140

# Copiar APENAS o modelo ativo (não todos os modelos antigos)
# Isso reduz o tamanho da imagem de ~47MB para ~11MB
# O path é dinâmico - deploy.sh passa via --build-arg MODEL_PATH=...
COPY ./${MODEL_PATH}/ ./${MODEL_PATH}/

# Definir variáveis de ambiente
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

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
     "--timeout", "600", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]