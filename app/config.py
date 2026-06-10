import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # API Keys
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")

    # LLM Settings
    llm_provider: str = Field(default="gemini", validation_alias="LLM_PROVIDER") # 'openai' or 'gemini'
    openai_model: str = Field(default="gpt-4o-mini", validation_alias="OPENAI_MODEL")
    gemini_model: str = Field(default="gemini-2.0-flash", validation_alias="GEMINI_MODEL")

    # Embedding Settings
    openai_embedding_model: str = Field(default="text-embedding-3-small", validation_alias="OPENAI_EMBEDDING_MODEL")
    gemini_embedding_model: str = Field(default="models/gemini-embedding-001", validation_alias="GEMINI_EMBEDDING_MODEL")

    # RAG Settings
    chunk_size: int = Field(default=1000, validation_alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=200, validation_alias="CHUNK_OVERLAP")
    vector_store_path: str = Field(default="vector_store.json", validation_alias="VECTOR_STORE_PATH")

    # Server Settings
    host: str = Field(default="0.0.0.0", validation_alias="HOST")
    port: int = Field(default=8000, validation_alias="PORT")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
