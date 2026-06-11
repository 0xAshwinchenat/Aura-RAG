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
    gemini_model: str = Field(default="gemini-3.1-flash-lite", validation_alias="GEMINI_MODEL")

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

    @property
    def resolved_vector_store_path(self) -> str:
        """Returns a writable path for the vector store.
        On read-only filesystems (e.g. Vercel), falls back to /tmp/.
        """
        base_path = self.vector_store_path
        # Check if the directory of the configured path is writable
        parent_dir = os.path.dirname(os.path.abspath(base_path)) if os.path.dirname(base_path) else os.getcwd()
        if os.access(parent_dir, os.W_OK):
            return base_path
        # Fallback to /tmp/ for read-only environments like Vercel
        tmp_path = os.path.join("/tmp", os.path.basename(base_path))
        return tmp_path

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
