from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    jwt_secret: str = "dev-secret-change-me"
    jwt_alg: str = "HS256"
    jwt_ttl_min: int = 15
    upload_max_mb: int = 25

    postgres_dsn: str = "postgresql+psycopg://befree:befree@postgres:5432/befree"

    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "chunks"
    vector_dim: int = 1024

    redis_url: str = "redis://redis:6379/0"

    embedding_model: str = "BAAI/bge-large-en-v1.5"
    reranker_model: str = "BAAI/bge-reranker-base"
    device: str = "cpu"

    litellm_model: str = "groq/llama-3.1-70b-versatile"
    groq_api_key: str = ""
    gemini_api_key: str = ""
    llm_max_tokens: int = 1024
    context_token_budget: int = 4000
    top_k_parents: int = 5
    top_k_vector: int = 30

    injection_model: str = "protectai/deberta-v3-base-prompt-injection"
    injection_threshold: float = 0.7

    clamav_host: str = "clamav"
    clamav_port: int = 3310

    para_chunk_tokens: int = 512
    para_chunk_overlap: int = 64
    table_rows_per_chunk: int = 3
    table_small_threshold: int = 4
    list_items_per_chunk: int = 4

    # PII vault (see app/ingestion/pii_vault.py). Fernet key: 32 bytes base64.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    pii_vault_key: str = ""
    # When true, /query unmasks tokens back to originals for authenticated users.
    pii_unmask_on_query: bool = True


settings = Settings()
