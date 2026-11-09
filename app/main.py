"""FastAPI application and telemetry instrumentation."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
import uvicorn
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


DB_PATH = Path(os.getenv("DATABASE_PATH", "documents.db"))
OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
RESOURCE = Resource.create({"service.name": "document-server"})

# Send all three signal types to the local collector using OTLP/gRPC.
trace_provider = TracerProvider(resource=RESOURCE)
trace_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)))
trace.set_tracer_provider(trace_provider)

metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint=OTEL_ENDPOINT, insecure=True), export_interval_millis=5000
)
metrics.set_meter_provider(MeterProvider(resource=RESOURCE, metric_readers=[metric_reader]))
meter = metrics.get_meter("document_server")
request_count = meter.create_counter("http.server.requests", description="Endpoint request count")
request_duration = meter.create_histogram("http.server.duration", unit="s", description="Endpoint duration")

logger_provider = LoggerProvider(resource=RESOURCE)
logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=OTEL_ENDPOINT, insecure=True)))
set_logger_provider(logger_provider)
logger = logging.getLogger("document_server")
logger.setLevel(logging.INFO)
logger.addHandler(LoggingHandler(logger_provider=logger_provider))


class DocumentIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {"name": "xyz", "phone_name": ["a", "b", "c"], "location": "abc"}
    })
    name: str = Field(..., examples=["xyz"])
    phone_name: list[str] = Field(..., examples=[["a", "b", "c"]])
    location: str = Field(..., examples=["abc"])


class Document(DocumentIn):
    model_config = ConfigDict(json_schema_extra={
        "example": {"id": 1, "name": "xyz", "phone_name": ["a", "b", "c"], "location": "abc"}
    })
    id: int = Field(..., examples=[1])


@asynccontextmanager
async def lifespan(_: FastAPI):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone_name TEXT NOT NULL,
            location TEXT NOT NULL
        )""")
    yield
    # Flush pending telemetry during graceful shutdown.
    trace_provider.shutdown()
    metrics.get_meter_provider().shutdown()
    logger_provider.shutdown()


app = FastAPI(
    title="Document Server API",
    description="A small SQLite-backed document REST API. Telemetry is exported to the local OpenTelemetry Collector.",
    version="1.0.0",
    lifespan=lifespan,
)
FastAPIInstrumentor.instrument_app(app)


def record_endpoint(request: Request, started: float, status_code: int) -> None:
    attrs = {"http.request.method": request.method, "http.route": request.scope.get("route").path if request.scope.get("route") else request.url.path,
             "http.response.status_code": status_code}
    request_count.add(1, attrs)
    request_duration.record(time.perf_counter() - started, attrs)


@app.post("/documents", response_model=Document, status_code=status.HTTP_201_CREATED,
          summary="Create a document", tags=["documents"])
def create_document(document: DocumentIn, request: Request, response: Response):
    started = time.perf_counter()
    try:
        with sqlite3.connect(DB_PATH) as db:
            cursor = db.execute(
                "INSERT INTO documents (name, phone_name, location) VALUES (?, ?, ?)",
                (document.name, json.dumps(document.phone_name), document.location),
            )
            doc_id = cursor.lastrowid
        response.headers["Location"] = f"/document/{doc_id}"
        result = Document(id=doc_id, **document.model_dump())
        logger.info("Document created", extra={"document.id": doc_id, "http.route": "/documents"})
        record_endpoint(request, started, 201)
        return result
    except Exception:
        record_endpoint(request, started, 500)
        logger.exception("Document creation failed", extra={"http.route": "/documents"})
        raise


@app.get("/document/{id}", response_model=Document, summary="Get a document by ID", tags=["documents"])
def get_document(id: int, request: Request):
    started = time.perf_counter()
    try:
        with sqlite3.connect(DB_PATH) as db:
            row = db.execute("SELECT id, name, phone_name, location FROM documents WHERE id = ?", (id,)).fetchone()
        if row is None:
            logger.info("Document not found", extra={"document.id": id, "http.route": "/document/{id}"})
            record_endpoint(request, started, 404)
            raise HTTPException(status_code=404, detail="Document not found")
        result = Document(id=row[0], name=row[1], phone_name=json.loads(row[2]), location=row[3])
        logger.info("Document retrieved", extra={"document.id": id, "http.route": "/document/{id}"})
        record_endpoint(request, started, 200)
        return result
    except HTTPException:
        raise
    except Exception:
        record_endpoint(request, started, 500)
        logger.exception("Document retrieval failed", extra={"document.id": id, "http.route": "/document/{id}"})
        raise


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
