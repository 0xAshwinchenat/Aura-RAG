import os
import json
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple
import numpy as np
from app.core.splitter import DocumentChunk

logger = logging.getLogger(__name__)

class VectorStore(ABC):
    @abstractmethod
    def add_chunks(self, chunks: List[DocumentChunk], embeddings: List[List[float]]) -> None:
        """Add chunks and their corresponding embeddings to the store."""
        pass

    @abstractmethod
    def similarity_search(self, query_embedding: List[float], k: int = 5) -> List[Tuple[DocumentChunk, float]]:
        """Return top-k chunks matching the query embedding, with similarity scores."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all entries in the vector store."""
        pass

    @abstractmethod
    def save(self, filepath: str) -> None:
        """Save vector store to disk."""
        pass

    @abstractmethod
    def load(self, filepath: str) -> None:
        """Load vector store from disk."""
        pass


class InMemoryVectorStore(VectorStore):
    """
    A lightweight, robust, and dependency-free Vector Store that uses numpy
    for cosine similarity search and JSON for disk persistence.
    Highly portable and perfectly suited for cloud deployment.
    """
    def __init__(self):
        self.chunks: List[DocumentChunk] = []
        self.embeddings: List[np.ndarray] = []  # Normalized embeddings for quick dot product

    def add_chunks(self, chunks: List[DocumentChunk], embeddings: List[List[float]]) -> None:
        if not chunks:
            return
        
        if len(chunks) != len(embeddings):
            raise ValueError("Number of chunks must match number of embeddings.")

        for chunk, emb in zip(chunks, embeddings):
            # L2 Normalize the embedding for fast cosine similarity via dot product
            arr = np.array(emb, dtype=np.float32)
            norm = np.linalg.norm(arr)
            normalized_emb = arr / norm if norm > 0 else arr
            
            self.chunks.append(chunk)
            self.embeddings.append(normalized_emb)
            
        logger.info(f"Added {len(chunks)} chunks to Vector Store (Total: {len(self.chunks)} chunks)")

    def similarity_search(self, query_embedding: List[float], k: int = 5) -> List[Tuple[DocumentChunk, float]]:
        if not self.chunks or not self.embeddings:
            return []

        # Convert query and L2 normalize
        q_arr = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q_arr)
        q_normalized = q_arr / q_norm if q_norm > 0 else q_arr

        # Stack stored embeddings for batch dot product
        matrix = np.vstack(self.embeddings)  # Shape: (num_chunks, emb_dim)
        
        # Compute cosine similarity (dot product of normalized vectors)
        similarities = np.dot(matrix, q_normalized)  # Shape: (num_chunks,)

        # Get top-k indices sorted in descending order
        top_k_indices = np.argsort(similarities)[::-1][:k]
        
        results = []
        for idx in top_k_indices:
            score = float(similarities[idx])
            results.append((self.chunks[idx], score))
            
        return results

    def clear(self) -> None:
        self.chunks = []
        self.embeddings = []
        logger.info("Cleared Vector Store")

    def save(self, filepath: str) -> None:
        """Saves embeddings and chunks as a JSON-serializable dictionary."""
        # Convert embeddings back to standard python list of lists
        serialized_embeddings = [emb.tolist() for emb in self.embeddings]
        serialized_chunks = [chunk.model_dump() for chunk in self.chunks]
        
        data = {
            "chunks": serialized_chunks,
            "embeddings": serialized_embeddings
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(self.chunks)} chunks to {filepath}")

    def load(self, filepath: str) -> None:
        if not os.path.exists(filepath):
            logger.warning(f"Vector store file {filepath} not found. Starting fresh.")
            return

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            self.chunks = [DocumentChunk(**chunk_data) for chunk_data in data.get("chunks", [])]
            self.embeddings = [np.array(emb, dtype=np.float32) for emb in data.get("embeddings", [])]
            logger.info(f"Loaded {len(self.chunks)} chunks from {filepath}")
        except Exception as e:
            logger.error(f"Failed to load vector store from {filepath}: {e}. Starting fresh.")
            self.chunks = []
            self.embeddings = []


_global_store: InMemoryVectorStore | None = None

def get_vector_store(store_path: str) -> VectorStore:
    """
    Returns a singleton instance of the vector store, loading it from disk if available.
    """
    global _global_store
    if _global_store is None:
        _global_store = InMemoryVectorStore()
        if os.path.exists(store_path):
            _global_store.load(store_path)
    return _global_store
