#!/usr/bin/env python3
import sys
import os
import json

# Ensure parent directory is in python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import settings
from app.core.vector_store import get_vector_store
from app.eval.evaluator import RAGEvaluator

def main():
    print("=" * 60)
    print("             AURA RAG EVALUATION RUNNER")
    print("=" * 60)
    
    # 1. Load active config & vector store
    store_path = settings.vector_store_path
    vector_store = get_vector_store(store_path)
    
    if not vector_store.chunks:
        print("\n[WARNING] The Vector Store is currently empty!")
        print("To run the evaluation, you must first ingest the test documents.")
        print("\nPlease run the following command to ingest sample documents:")
        print("  python run.py --ingest test_files/")
        print("\nThen, rerun this evaluation script.")
        print("=" * 60)
        sys.exit(1)
        
    print(f"Index loaded with {len(vector_store.chunks)} chunks.")
    print(f"Using Provider: {settings.llm_provider.upper()}")
    print(f"Models: LLM={settings.gemini_model if settings.llm_provider=='gemini' else settings.openai_model}, "
          f"Embedding={settings.gemini_embedding_model if settings.llm_provider=='gemini' else settings.openai_embedding_model}")
    print("-" * 60)
    
    # 2. Run evaluator
    evaluator = RAGEvaluator()
    print("Running evaluation suite. Processing queries & grading answers with LLM-as-a-judge...")
    summary = evaluator.run_eval()
    
    if not summary.get("success", False):
        print(f"\n[ERROR] Evaluation failed: {summary.get('error')}")
        sys.exit(1)
        
    # 3. Print Results Summary
    print("\n" + "=" * 60)
    print("                     EVALUATION RESULTS")
    print("=" * 60)
    print(f"Timestamp:       {summary['timestamp']}")
    print(f"Total Cases:     {summary['total_cases']}")
    print(f"Retrieval K:     {summary['retrieval_k']}")
    print("-" * 60)
    print("METRICS SUMMARY:")
    print(f"  Retrieval Recall@K:       {summary['metrics']['average_recall'] * 100:.1f}%")
    print(f"  Answer Groundedness:      {summary['metrics']['average_groundedness']:.2f} / 5.0")
    print(f"  Citation Accuracy:        {summary['metrics']['average_citation_accuracy']:.2f} / 5.0")
    print("-" * 60)
    
    # 4. Case breakdown
    print(f"{'ID':<3} | {'Question':<45} | {'Recall':<6} | {'Grounded':<8} | {'Citation':<8} | {'Latency':<7}")
    print("-" * 90)
    for case in summary["cases"]:
        q = case["question"]
        if len(q) > 42:
            q = q[:42] + "..."
            
        recall_str = f"{case['recall'] * 100:.0f}%"
        g_score = f"{case['groundedness_score']}/5" if case['groundedness_score'] > 0 else "N/A"
        c_score = f"{case['citation_score']}/5" if case['citation_score'] > 0 else "N/A"
        lat = f"{case['latency_sec']:.2f}s"
        
        print(f"{case['case_id']:<3} | {q:<45} | {recall_str:<6} | {g_score:<8} | {c_score:<8} | {lat:<7}")
        
    print("=" * 90)
    print("Detailed reports and judges' rationales are saved to 'data/eval_results.json'.")
    print("=" * 90)

if __name__ == "__main__":
    main()
