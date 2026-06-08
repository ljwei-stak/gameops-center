FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GAMEOPS_DRY_RUN=true \
    GAMEOPS_TRUSTED_RUNTIME=false \
    GAMEOPS_LOCAL_LOGIN_ENABLED=true

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -r requirements.txt \
    && useradd -r -u 10001 gameops \
    && mkdir -p /app/data \
    && chown -R gameops:gameops /app

USER gameops
EXPOSE 8018

CMD ["python", "app.py", "8018"]
