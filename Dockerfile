FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config
COPY templates ./templates
COPY data ./data
COPY README.md .

EXPOSE 8050

CMD ["sh", "-c", "uvicorn app.dashboard:app --host 0.0.0.0 --port ${PORT:-8050} --workers 1 --proxy-headers"]
