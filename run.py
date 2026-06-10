#!/usr/bin/env python3
import os
import argparse
import sys
import uvicorn
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("aura-rag")

def start_server(host: str, port: int):
    logger.info(f"Starting FastAPI Web Server on http://{host}:{port} ...")
    uvicorn.run("app.main:app", host=host, port=port, reload=True)


def handle_cli_ingest(path: str):
    """
    Ingests files from a single file path or a directory of files.
    """
    from app.config import settings
    from app.core.parser import DocumentParser
    from app.core.splitter import RecursiveTextSplitter
    from app.core.embedder import get_embedding_client
    from app.core.vector_store import get_vector_store

    if not os.path.exists(path):
        logger.error(f"Target path does not exist: {path}")
        sys.exit(1)

    # Resolve files
    files_to_process = []
    if os.path.isdir(path):
        for root, _, files in os.walk(path):
            for file in files:
                files_to_process.append(os.path.join(root, file))
    else:
        files_to_process.append(path)

    if not files_to_process:
        logger.warning(f"No files found at target path: {path}")
        return

    logger.info(f"Found {len(files_to_process)} files to ingest.")
    
    # Initialize components
    try:
        embedder = get_embedding_client()
        vector_store = get_vector_store(settings.vector_store_path)
    except Exception as e:
        logger.error(f"Failed to initialize embedding client or vector store. Make sure API keys are configured: {e}")
        sys.exit(1)
        
    splitter = RecursiveTextSplitter(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    
    success_count = 0
    total_chunks = 0

    for file_path in files_to_process:
        filename = os.path.basename(file_path)
        logger.info(f"Ingesting: {filename}")
        
        parsed_doc = DocumentParser.parse(file_path, filename)
        
        if not parsed_doc.success:
            logger.error(f"  [SKIPPED] Ingestion failed: {parsed_doc.error_message}")
            continue

        chunks = splitter.split_document(parsed_doc)
        if not chunks:
            logger.warning(f"  [SKIPPED] Parsed document yielded empty text contents.")
            continue

        try:
            chunk_texts = [c.text for c in chunks]
            embeddings = embedder.embed_documents(chunk_texts)
            vector_store.add_chunks(chunks, embeddings)
            
            logger.info(f"  [SUCCESS] Split into {len(chunks)} chunks.")
            success_count += 1
            total_chunks += len(chunks)
        except Exception as e:
            logger.error(f"  [FAILED] Error during embedding generation: {e}")

    if success_count > 0:
        vector_store.save(settings.vector_store_path)
        logger.info(f"Ingestion complete. Successfully processed {success_count}/{len(files_to_process)} files. Added {total_chunks} chunks.")
    else:
        logger.warning("No files were successfully ingested.")


def handle_cli_query(question: str):
    """
    Runs a single query in the command line interface, printing answers and citations.
    """
    from app.config import settings
    from app.core.embedder import get_embedding_client
    from app.core.vector_store import get_vector_store
    from app.core.llm import get_llm_client

    vector_store = get_vector_store(settings.vector_store_path)
    if not vector_store.chunks:
        logger.error("Vector store is empty! Please ingest documents first: python run.py --ingest <path>")
        sys.exit(1)

    try:
        embedder = get_embedding_client()
        llm = get_llm_client()
    except Exception as e:
        logger.error(f"Failed to initialize API clients. Check your environment keys: {e}")
        sys.exit(1)

    logger.info(f"Searching index...")
    try:
        # 1. Embed query
        query_emb = embedder.embed_query(question)
        
        # 2. Search
        search_results = vector_store.similarity_search(query_emb, k=5)
        if not search_results:
            print("\nAnswer: I cannot find the answer to this question in the provided documents.")
            return

        # 3. Generate answer
        chunks = [chunk for chunk, score in search_results]
        logger.info(f"Generating grounded answer...")
        response = llm.generate_answer(question, chunks)
        
        # 4. Print Answer
        print("\n" + "=" * 60)
        print("ANSWER:")
        print("=" * 60)
        print(response["answer"])
        print("\n" + "=" * 60)
        print("CITATIONS & SOURCES:")
        print("=" * 60)
        if response["citations"]:
            for cit in response["citations"]:
                loc_detail = f"({cit['detail'].lstrip(', ')})" if cit['detail'] else ""
                print(f"[{cit['chunk_id']}] File: {cit['source']} {loc_detail}")
                print(f"    Snippet: \"{cit['snippet'].strip()}\"\n")
        else:
            print("No citations matched (null response).")
        print("=" * 60)
        
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        sys.exit(1)


def handle_cli_clear():
    """
    Clears the local vector store index.
    """
    from app.config import settings
    from app.core.vector_store import get_vector_store
    
    vector_store = get_vector_store(settings.vector_store_path)
    vector_store.clear()
    vector_store.save(settings.vector_store_path)
    logger.info("Cleared vector store index successfully.")


def handle_cli_eval(k: int):
    """
    Triggers the standalone evaluation script.
    """
    from app.eval.run_eval import main as run_eval_main
    # Update settings config programmatically if needed
    run_eval_main()


def main():
    parser = argparse.ArgumentParser(
        description="AURA RAG - Document-Agnostic Retrieval-Augmented Generation System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start the Web API Server & UI dashboard
  python run.py --serve --port 8000
  
  # Ingest a directory of files (PDFs, Docx, CSVs, etc.)
  python run.py --ingest test_files/
  
  # Query the RAG system directly in the terminal
  python run.py --query "What is the naming convention for git branches?"
  
  # Run RAG evaluation suite
  python run.py --eval
  
  # Clear the vector store index
  python run.py --clear
"""
    )
    
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--serve", action="store_true", help="Start the FastAPI web server.")
    group.add_argument("--ingest", type=str, metavar="PATH", help="Ingest a single file or folder of mixed documents.")
    group.add_argument("--query", type=str, metavar="QUESTION", help="Submit a grounded question to the RAG system via CLI.")
    group.add_argument("--eval", action="store_true", help="Run the automated RAG evaluation suite.")
    group.add_argument("--clear", action="store_true", help="Clear all documents from the vector store.")
    
    parser.add_argument("--port", type=int, default=8000, help="Port to run the FastAPI server on (default: 8000).")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host address for the FastAPI server (default: 0.0.0.0).")
    parser.add_argument("--k", type=int, default=5, help="Retrieval top-k for evaluation or query.")

    args = parser.parse_args()

    # Default action is --serve if no arguments provided
    if not (args.serve or args.ingest or args.query or args.eval or args.clear):
        args.serve = True

    if args.serve:
        start_server(args.host, args.port)
    elif args.ingest:
        handle_cli_ingest(args.ingest)
    elif args.query:
        handle_cli_query(args.query)
    elif args.clear:
        handle_cli_clear()
    elif args.eval:
        handle_cli_eval(args.k)


if __name__ == "__main__":
    main()
