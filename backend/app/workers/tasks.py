from app.ingestion.pipeline import process_document


def ingest_task(document_id: str, tenant_id: str, content_type: str, data: bytes) -> None:
    process_document(document_id, tenant_id, content_type, data)
