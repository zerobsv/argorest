FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/document-server
ENV PYTHONPATH=/srv/document-server

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 app \
    && mkdir /data \
    && chown app:app /data

COPY --chown=app:app app/ ./app/

USER app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--app-dir", "/srv/document-server", "--host", "0.0.0.0", "--port", "8000"]
