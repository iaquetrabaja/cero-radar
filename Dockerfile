FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt && useradd --create-home --uid 10001 cero
COPY . .
RUN mkdir -p data cero/static/cache && chown -R cero:cero /app
USER cero
CMD ["python", "-m", "uvicorn", "cero.public_api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
