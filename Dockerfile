FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

VOLUME ["/app/data"]

RUN mkdir -p /app/data && touch /app/data/documents.db
RUN chmod -R 750 /app/data && chown -R 10001:10001 /app/data

USER 10001:10001
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--app-dir", "/app", "--host", "0.0.0.0", "--port", "8000"]
