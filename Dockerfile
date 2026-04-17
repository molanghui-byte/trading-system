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
COPY start_multi_chain.py .

EXPOSE 8050

CMD ["python", "start_multi_chain.py"]
