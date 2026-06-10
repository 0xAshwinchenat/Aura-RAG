from abc import ABC, abstractmethod
from typing import List, Optional
import logging
from app.config import settings

logger = logging.getLogger(__name__)

class EmbeddingClient(ABC):
    @abstractmethod
    def embed_query(self, text: str) -> List[float]:
        """Generate embedding vector for a single search query."""
        pass

    @abstractmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for a list of document texts."""
        pass


class OpenAIEmbeddingClient(EmbeddingClient):
    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        self.model = model
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)

    def embed_query(self, text: str) -> List[float]:
        try:
            response = self.client.embeddings.create(
                input=[text],
                model=self.model
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"OpenAI Query Embedding failed: {e}")
            raise

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        try:
            # Batch in sets of 100 to avoid OpenAI API size limits
            batch_size = 100
            embeddings = []
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                response = self.client.embeddings.create(
                    input=batch,
                    model=self.model
                )
                embeddings.extend([d.embedding for d in response.data])
            return embeddings
        except Exception as e:
            logger.error(f"OpenAI Documents Embedding failed: {e}")
            raise


class GeminiEmbeddingClient(EmbeddingClient):
    def __init__(self, api_key: str, model: str = "models/text-embedding-004"):
        self.model = model
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self.genai = genai

    def embed_query(self, text: str) -> List[float]:
        try:
            response = self.genai.embed_content(
                model=self.model,
                content=text,
                task_type="retrieval_query"
            )
            return response['embedding']
        except Exception as e:
            logger.error(f"Gemini Query Embedding failed: {e}")
            raise

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        try:
            # Gemini has limits on batch requests. Let's batch in chunks of 50
            batch_size = 50
            embeddings = []
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                response = self.genai.embed_content(
                    model=self.model,
                    content=batch,
                    task_type="retrieval_document"
                )
                embeddings.extend(response['embedding'])
            return embeddings
        except Exception as e:
            logger.error(f"Gemini Documents Embedding failed: {e}")
            raise


def get_embedding_client(provider: Optional[str] = None) -> EmbeddingClient:
    """
    Factory function to get the embedding client based on settings.
    """
    prov = provider or settings.llm_provider
    if prov == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not set in environment.")
        logger.info("Instantiating OpenAI Embedding Client")
        return OpenAIEmbeddingClient(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model
        )
    elif prov == "gemini":
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not set in environment.")
        logger.info("Instantiating Gemini Embedding Client")
        return GeminiEmbeddingClient(
            api_key=settings.gemini_api_key,
            model=settings.gemini_embedding_model
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {prov}")
