import os
import shutil
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.core.parser import DocumentParser
from app.core.splitter import RecursiveTextSplitter
from app.core.embedder import get_embedding_client
from app.core.vector_store import get_vector_store
from app.core.llm import get_llm_client

logger = logging.getLogger(__name__)
router = APIRouter()

# --- Schemas ---

class QueryRequest(BaseModel):
    question: str = Field(..., description="The natural language question to ask.")
    llm_provider: Optional[str] = Field(default=None, description="Force override the LLM provider ('openai' or 'gemini').")
    k: int = Field(default=5, ge=1, le=20, description="Number of retrieved chunks to include in context.")

class CitationDetail(BaseModel):
    chunk_id: int
    source: str
    detail: str
    snippet: str
    metadata: Dict[str, Any]

class QueryResponse(BaseModel):
    answer: str
    citations: List[CitationDetail]
    retrieved_chunks: List[Dict[str, Any]]
    success: bool
    error: Optional[str] = None

class SearchResponseItem(BaseModel):
    text: str
    score: float
    metadata: Dict[str, Any]

class SearchResponse(BaseModel):
    results: List[SearchResponseItem]

class ConfigResponse(BaseModel):
    llm_provider: str
    openai_model: str
    gemini_model: str
    openai_embedding_model: str
    gemini_embedding_model: str
    chunk_size: int
    chunk_overlap: int
    vector_store_path: str
    vector_store_loaded_chunks: int

class UpdateConfigPayload(BaseModel):
    llm_provider: Optional[str] = None
    openai_model: Optional[str] = None
    gemini_model: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None

class IngestionResult(BaseModel):
    filename: str
    success: bool
    mime_type: str
    chunk_count: int
    error: Optional[str] = None

class IngestionResponse(BaseModel):
    results: List[IngestionResult]
    total_processed: int
    total_successful: int

# --- Routes ---

@router.post("/ingest", response_model=IngestionResponse)
async def ingest_documents(files: List[UploadFile] = File(...)):
    """
    Ingests multiple files, detects their types, parses them, splits them,
    generates embeddings, and saves them to the vector store.
    """
    temp_dir = "temp_uploads"
    try:
        os.makedirs(temp_dir, exist_ok=True)
    except OSError:
        temp_dir = "/tmp/temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)
    
    results = []
    
    # 1. Get embedding client & vector store
    try:
        embedder = get_embedding_client()
        vector_store = get_vector_store(settings.resolved_vector_store_path)
    except Exception as e:
        logger.error(f"Failed to initialize embedding client or vector store: {e}")
        raise HTTPException(status_code=500, detail=f"Initialization error: {str(e)}")
        
    splitter = RecursiveTextSplitter(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    
    for upload_file in files:
        filename = upload_file.filename or "unknown_file"
        temp_file_path = os.path.join(temp_dir, filename)
        
        # Save file to temp path
        try:
            with open(temp_file_path, "wb") as f:
                shutil.copyfileobj(upload_file.file, f)
        except Exception as e:
            logger.error(f"Failed to save temp file {filename}: {e}")
            results.append(IngestionResult(
                filename=filename,
                success=False,
                mime_type="unknown",
                chunk_count=0,
                error=f"Temp save error: {str(e)}"
            ))
            continue
            
        # Parse file (with error protection)
        parsed_doc = DocumentParser.parse(temp_file_path, filename)
        
        # Clean up temp file immediately after parse
        try:
            os.remove(temp_file_path)
        except Exception as e:
            logger.warning(f"Failed to remove temp file {temp_file_path}: {e}")

        # Handle parsing failures gracefully
        if not parsed_doc.success:
            logger.warning(f"File {filename} parsed with errors: {parsed_doc.error_message}")
            results.append(IngestionResult(
                filename=filename,
                success=False,
                mime_type=parsed_doc.mime_type or "unknown",
                chunk_count=0,
                error=parsed_doc.error_message
            ))
            continue

        # Split document
        chunks = splitter.split_document(parsed_doc)
        if not chunks:
            results.append(IngestionResult(
                filename=filename,
                success=True,
                mime_type=parsed_doc.mime_type,
                chunk_count=0,
                error="Document parsed successfully but yielded no text contents."
            ))
            continue
            
        # Generate embeddings & save to vector store
        try:
            chunk_texts = [c.text for c in chunks]
            embeddings = embedder.embed_documents(chunk_texts)
            vector_store.add_chunks(chunks, embeddings)
            
            results.append(IngestionResult(
                filename=filename,
                success=True,
                mime_type=parsed_doc.mime_type,
                chunk_count=len(chunks)
            ))
        except Exception as e:
            logger.error(f"Error embedding/saving document {filename}: {e}")
            results.append(IngestionResult(
                filename=filename,
                success=False,
                mime_type=parsed_doc.mime_type,
                chunk_count=0,
                error=f"Embedding error: {str(e)}"
            ))
            
    # Persist the vector store to disk
    if any(r.success and r.chunk_count > 0 for r in results):
        try:
            vector_store.save(settings.resolved_vector_store_path)
        except Exception as e:
            logger.error(f"Failed to save vector store: {e}")
            
    total_successful = sum(1 for r in results if r.success)
    
    return IngestionResponse(
        results=results,
        total_processed=len(files),
        total_successful=total_successful
    )

@router.post("/query", response_model=QueryResponse)
async def query_rag(payload: QueryRequest):
    """
    Retrieves relevant document chunks and uses the LLM to generate an answer
    grounded in the retrieved context with citations.
    """
    try:
        # 1. Get components
        vector_store = get_vector_store(settings.resolved_vector_store_path)
        embedder = get_embedding_client(payload.llm_provider)
        llm = get_llm_client(payload.llm_provider)
    except Exception as e:
        logger.error(f"Failed to initialize components: {e}")
        return QueryResponse(
            answer="",
            citations=[],
            retrieved_chunks=[],
            success=False,
            error=f"Config/Init error: {str(e)}"
        )
        
    if not vector_store.chunks:
        return QueryResponse(
            answer="No documents have been ingested yet. Please upload documents first.",
            citations=[],
            retrieved_chunks=[],
            success=True
        )

    try:
        # 2. Embed query
        query_emb = embedder.embed_query(payload.question)
        
        # 3. Retrieve top-k chunks
        search_results = vector_store.similarity_search(query_emb, k=payload.k)
        
        if not search_results:
            return QueryResponse(
                answer="I cannot find the answer to this question in the provided documents.",
                citations=[],
                retrieved_chunks=[],
                success=True
            )
            
        retrieved_chunks = [chunk for chunk, score in search_results]
        
        # 4. Generate answer grounded in context
        llm_response = llm.generate_answer(payload.question, retrieved_chunks)
        
        # Format the retrieved chunks for the response metadata
        chunks_detail = []
        for idx, (chunk, score) in enumerate(search_results):
            chunks_detail.append({
                "chunk_id": idx,
                "text": chunk.text,
                "score": score,
                "metadata": chunk.metadata
            })
            
        return QueryResponse(
            answer=llm_response["answer"],
            citations=[CitationDetail(**c) for c in llm_response["citations"]],
            retrieved_chunks=chunks_detail,
            success=True
        )
    except Exception as e:
        logger.error(f"RAG query execution failed: {e}")
        return QueryResponse(
            answer="An internal error occurred while processing your request.",
            citations=[],
            retrieved_chunks=[],
            success=False,
            error=str(e)
        )

@router.get("/search", response_model=SearchResponse)
async def search_vectors(
    query: str = Query(..., description="Query string to search for"),
    k: int = Query(5, ge=1, le=50, description="Number of results to return")
):
    """
    Performs pure similarity search on vector store and returns matching text and scores.
    Useful for testing retrieval quality directly.
    """
    vector_store = get_vector_store(settings.resolved_vector_store_path)
    if not vector_store.chunks:
        return SearchResponse(results=[])
        
    try:
        embedder = get_embedding_client()
        query_emb = embedder.embed_query(query)
        search_results = vector_store.similarity_search(query_emb, k=k)
        
        results = [
            SearchResponseItem(text=chunk.text, score=score, metadata=chunk.metadata)
            for chunk, score in search_results
        ]
        return SearchResponse(results=results)
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/config", response_model=ConfigResponse)
async def get_config():
    """
    Returns the current configuration settings.
    """
    vector_store = get_vector_store(settings.resolved_vector_store_path)
    return ConfigResponse(
        llm_provider=settings.llm_provider,
        openai_model=settings.openai_model,
        gemini_model=settings.gemini_model,
        openai_embedding_model=settings.openai_embedding_model,
        gemini_embedding_model=settings.gemini_embedding_model,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        vector_store_path=settings.resolved_vector_store_path,
        vector_store_loaded_chunks=len(vector_store.chunks)
    )

@router.post("/config", response_model=ConfigResponse)
async def update_config(payload: UpdateConfigPayload):
    """
    Updates the system configuration settings dynamically at runtime.
    """
    if payload.llm_provider is not None:
        if payload.llm_provider not in ["openai", "gemini"]:
            raise HTTPException(status_code=400, detail="llm_provider must be 'openai' or 'gemini'")
        settings.llm_provider = payload.llm_provider
        
    if payload.openai_model is not None:
        settings.openai_model = payload.openai_model
        
    if payload.gemini_model is not None:
        settings.gemini_model = payload.gemini_model
        
    if payload.chunk_size is not None:
        if payload.chunk_size <= 0:
            raise HTTPException(status_code=400, detail="chunk_size must be positive")
        settings.chunk_size = payload.chunk_size
        
    if payload.chunk_overlap is not None:
        if payload.chunk_overlap < 0:
            raise HTTPException(status_code=400, detail="chunk_overlap cannot be negative")
        if payload.chunk_overlap >= settings.chunk_size:
            raise HTTPException(status_code=400, detail="chunk_overlap must be smaller than chunk_size")
        settings.chunk_overlap = payload.chunk_overlap
        
    vector_store = get_vector_store(settings.resolved_vector_store_path)
    
    return ConfigResponse(
        llm_provider=settings.llm_provider,
        openai_model=settings.openai_model,
        gemini_model=settings.gemini_model,
        openai_embedding_model=settings.openai_embedding_model,
        gemini_embedding_model=settings.gemini_embedding_model,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        vector_store_path=settings.resolved_vector_store_path,
        vector_store_loaded_chunks=len(vector_store.chunks)
    )

@router.post("/clear")
async def clear_store():
    """
    Clears all ingested documents and settings in the vector store.
    """
    try:
        vector_store = get_vector_store(settings.resolved_vector_store_path)
        vector_store.clear()
        try:
            vector_store.save(settings.resolved_vector_store_path)
        except OSError as e:
            logger.warning(f"Could not write cleared vector store to disk (expected in read-only environments like Vercel): {e}")
        return {"status": "success", "message": "Vector store cleared."}
    except Exception as e:
        logger.error(f"Failed to clear store: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/eval/run")
async def run_evaluation(k: int = Query(5, ge=1, le=10, description="K chunks to retrieve during evaluation")):
    """
    Triggers the RAG Evaluation pipeline and returns the summary metrics.
    """
    from app.eval.evaluator import RAGEvaluator
    try:
        evaluator = RAGEvaluator()
        summary = evaluator.run_eval(k=k)
        return summary
    except Exception as e:
        logger.error(f"Failed to run evaluation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/eval/results")
async def get_evaluation_results():
    """
    Retrieves the last run evaluation results from disk.
    """
    import json
    results_path = "data/eval_results.json"
    if not os.path.exists(results_path):
        results_path = "/tmp/data/eval_results.json"
    if not os.path.exists(results_path):
        raise HTTPException(status_code=404, detail="No evaluation results found. Run evaluation first.")
    try:
        with open(results_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read evaluation results: {e}")
        raise HTTPException(status_code=500, detail=str(e))

