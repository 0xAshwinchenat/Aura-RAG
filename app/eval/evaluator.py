import os
import json
import logging
import time
from typing import List, Dict, Any, Tuple
from app.config import settings
from app.core.vector_store import get_vector_store
from app.core.embedder import get_embedding_client
from app.core.llm import get_llm_client, build_user_prompt

logger = logging.getLogger(__name__)

EVAL_JUDGE_PROMPT = """You are an expert RAG Evaluation System.
Your task is to evaluate a generated answer based on the retrieved context chunks and the user's question.

Retrieved Context Chunks:
<context>
{context}
</context>

User Question: {question}
Generated Answer: {answer}

You must evaluate two aspects:
1. GROUNDEDNESS: Is the generated answer fully grounded in the retrieved context? Are there any claims made that are not supported by the context?
   - 5: Entirely grounded. Every statement is directly supported by the context.
   - 4: Mostly grounded. Minor extrapolation, but no major hallucinations.
   - 3: Partially grounded. Some facts are supported, but there are unverified claims.
   - 2: Poorly grounded. Multiple hallucinations or unsupported claims.
   - 1: Fully hallucinated. The answer is not supported by the context at all or uses external facts.

2. CITATION CORRECTNESS: Are the citations correct and accurate?
   - 5: Perfect citations. Every cited claim matches the content of the cited chunk. All major claims are cited.
   - 4: Good citations. Most claims are cited correctly, minor errors.
   - 3: Mediocre citations. Some incorrect citations or missing citations.
   - 2: Bad citations. Citations point to irrelevant chunks.
   - 1: No citations or completely incorrect citations.

Respond ONLY with a valid JSON object. Do not include any markdown code blocks, backticks, or prefix text.
Format your response exactly as follows:
{{
  "groundedness_score": <int 1-5>,
  "groundedness_reason": "<string explanation>",
  "citation_score": <int 1-5>,
  "citation_reason": "<string explanation>"
}}
"""

class RAGEvaluator:
    def __init__(self, dataset_path: str = "app/eval/dataset.json"):
        self.dataset_path = dataset_path
        self.dataset = self.load_dataset()

    def load_dataset(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.dataset_path):
            logger.error(f"Evaluation dataset not found at {self.dataset_path}")
            return []
        with open(self.dataset_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def evaluate_retrieval(self, retrieved_chunks: List[Dict[str, Any]], expected_sources: List[str]) -> float:
        """
        Calculates Recall@K: What fraction of the expected sources are present in the retrieved chunks.
        """
        if not expected_sources:
            return 1.0
        
        retrieved_sources = set()
        for chunk in retrieved_chunks:
            # retrieved chunks metadata has 'source' key
            src = chunk.get("metadata", {}).get("source")
            if src:
                retrieved_sources.add(src.lower())

        matched_sources = 0
        for src in expected_sources:
            if src.lower() in retrieved_sources:
                matched_sources += 1

        return float(matched_sources / len(expected_sources))

    def get_llm_judge_score(self, question: str, answer: str, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Uses the LLM-as-a-judge to evaluate Groundedness and Citation Correctness.
        """
        if "I cannot find the answer" in answer:
            # If the system correctly says it can't find the answer, groundedness is 5, citations not applicable
            return {
                "groundedness_score": 5,
                "groundedness_reason": "Correctly identified that answer is not in the documents.",
                "citation_score": 5,
                "citation_reason": "No citations required for null response."
            }

        # Formulate context block for the judge
        context_blocks = []
        for c in chunks:
            cid = c.get("chunk_id")
            meta = c.get("metadata", {})
            src = meta.get("source", "unknown")
            text = c.get("text", "")
            context_blocks.append(f"[Chunk {cid}] (Source: {src})\nContent: {text}\n")
            
        context_str = "\n".join(context_blocks)
        prompt = EVAL_JUDGE_PROMPT.format(
            context=context_str,
            question=question,
            answer=answer
        )

        try:
            # We call the active LLM API to act as a judge
            provider = settings.llm_provider
            
            if provider == "openai":
                if not settings.openai_api_key:
                    raise ValueError("OpenAI key missing")
                from openai import OpenAI
                client = OpenAI(api_key=settings.openai_api_key)
                response = client.chat.completions.create(
                    model=settings.openai_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0
                )
                raw_text = response.choices[0].message.content.strip()
            elif provider == "gemini":
                if not settings.gemini_api_key:
                    raise ValueError("Gemini key missing")
                import google.generativeai as genai
                genai.configure(api_key=settings.gemini_api_key)
                model = genai.GenerativeModel(settings.gemini_model)
                response = model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(temperature=0.0)
                )
                raw_text = response.text.strip()
            else:
                raise ValueError(f"Unknown provider: {provider}")

            # Clean JSON from potential markdown markers (e.g. ```json ... ```)
            raw_text = re.sub(r'^```json\s*|```$', '', raw_text, flags=re.MULTILINE).strip()
            
            # Parse JSON
            eval_results = json.loads(raw_text)
            return eval_results
        except Exception as e:
            logger.error(f"Failed to get LLM judge evaluation: {e}")
            return {
                "groundedness_score": 0,
                "groundedness_reason": f"Judge error: {str(e)}",
                "citation_score": 0,
                "citation_reason": f"Judge error: {str(e)}"
            }

    def run_eval(self, k: int = 5) -> Dict[str, Any]:
        """
        Runs the full evaluation set, computes metrics, and aggregates results.
        """
        vector_store = get_vector_store(settings.vector_store_path)
        if not vector_store.chunks:
            return {
                "success": False,
                "error": "Vector store is empty. Ingest documents before running evaluation."
            }

        embedder = get_embedding_client()
        llm = get_llm_client()
        
        results = []
        total_recall = 0.0
        total_groundedness = 0.0
        total_citation = 0.0
        valid_judge_runs = 0
        
        logger.info(f"Starting evaluation of {len(self.dataset)} cases...")
        
        for case in self.dataset:
            case_id = case["id"]
            question = case["question"]
            expected_sources = case["expected_sources"]
            
            logger.info(f"Evaluating Case {case_id}: '{question}'")
            start_time = time.time()
            
            # 1. Embed and retrieve
            try:
                query_emb = embedder.embed_query(question)
                search_results = vector_store.similarity_search(query_emb, k=k)
                retrieved_chunks_formatted = []
                for idx, (chunk, score) in enumerate(search_results):
                    retrieved_chunks_formatted.append({
                        "chunk_id": idx,
                        "text": chunk.text,
                        "score": score,
                        "metadata": chunk.metadata
                    })
            except Exception as e:
                logger.error(f"Retrieval failed for Case {case_id}: {e}")
                continue
                
            # 2. Compute recall
            recall = self.evaluate_retrieval(retrieved_chunks_formatted, expected_sources)
            total_recall += recall
            
            # 3. Generate answer
            answer = ""
            citations = []
            latency = 0.0
            try:
                chunks = [chunk for chunk, score in search_results]
                llm_response = llm.generate_answer(question, chunks)
                answer = llm_response["answer"]
                citations = llm_response["citations"]
                latency = time.time() - start_time
            except Exception as e:
                logger.error(f"Answer generation failed for Case {case_id}: {e}")
                continue
                
            # 4. LLM judge grades
            judge_metrics = self.get_llm_judge_score(question, answer, retrieved_chunks_formatted)
            
            g_score = judge_metrics.get("groundedness_score", 0)
            c_score = judge_metrics.get("citation_score", 0)
            
            if g_score > 0 and c_score > 0:
                total_groundedness += g_score
                total_citation += c_score
                valid_judge_runs += 1
                
            results.append({
                "case_id": case_id,
                "question": question,
                "expected_sources": expected_sources,
                "recall": recall,
                "answer": answer,
                "citations": citations,
                "groundedness_score": g_score,
                "groundedness_reason": judge_metrics.get("groundedness_reason", ""),
                "citation_score": c_score,
                "citation_reason": judge_metrics.get("citation_reason", ""),
                "latency_sec": round(latency, 2)
            })
            
            # Be friendly to API rate limits
            time.sleep(0.5)

        # Compute averages
        avg_recall = total_recall / len(self.dataset) if self.dataset else 0.0
        avg_groundedness = total_groundedness / valid_judge_runs if valid_judge_runs > 0 else 0.0
        avg_citation = total_citation / valid_judge_runs if valid_judge_runs > 0 else 0.0
        
        summary = {
            "success": True,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_cases": len(self.dataset),
            "retrieval_k": k,
            "metrics": {
                "average_recall": round(avg_recall, 4),
                "average_groundedness": round(avg_groundedness, 2),
                "average_citation_accuracy": round(avg_citation, 2)
            },
            "cases": results
        }
        
        # Save results to disk
        eval_dir = "data"
        try:
            os.makedirs(eval_dir, exist_ok=True)
        except OSError:
            eval_dir = "/tmp/data"
            os.makedirs(eval_dir, exist_ok=True)
        with open(os.path.join(eval_dir, "eval_results.json"), 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
            
        logger.info("Evaluation completed successfully.")
        return summary
