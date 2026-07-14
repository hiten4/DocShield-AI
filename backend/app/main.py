import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.admin.router import router as admin_router
from app.auth.router import router as auth_router
from app.db.qdrant import ensure_collection
from app.eval.router import router as eval_router
from app.ingestion.router import router as ingest_router
from app.query.router import router as query_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("befree")

app = FastAPI(title="BeFree RAG", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_mw(request: Request, call_next):
    rid = request.headers.get("x-request-id", str(uuid.uuid4()))
    request.state.request_id = rid
    response = await call_next(request)
    response.headers["x-request-id"] = rid
    return response


@app.exception_handler(Exception)
async def unhandled_exc(request: Request, exc: Exception):
    rid = getattr(request.state, "request_id", "-")
    log.exception("unhandled error rid=%s: %s", rid, exc)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "Internal server error", "request_id": rid}},
    )


@app.on_event("startup")
def startup():
    ensure_collection()


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(ingest_router, prefix="/documents", tags=["documents"])
app.include_router(query_router, prefix="/query", tags=["query"])
app.include_router(admin_router, prefix="/admin", tags=["admin"])
app.include_router(eval_router, prefix="/eval", tags=["eval"])
