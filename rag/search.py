"""
search.py — гибридный поиск по Qdrant (dense bge-m3 + sparse/IDF, слияние RRF) + опциональный реранкер.

    python rag/search.py "какая ставка НДС по договору с ООО Ромашка"
    python rag/search.py --k 5 --rerank "вопрос"
"""
import argparse, os
from openai import OpenAI
from qdrant_client import models as m
from ingest import COLLECTION, EMB_MODEL, qdrant_client, sparse_vec

RERANK_MODEL = os.getenv("RERANK_MODEL", "Qwen3-Reranker-8B")


def get_llm():
    return OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])


def hybrid_search(qc, llm, queries, k=8, per_branch=30):
    """queries — список подзапросов (для multi-hop). Результаты сливаются по максимальному RRF-скору."""
    best = {}
    for q in queries:
        dense = llm.embeddings.create(model=EMB_MODEL, input=[q]).data[0].embedding
        idx, val = sparse_vec(q)
        res = qc.query_points(
            COLLECTION,
            prefetch=[
                m.Prefetch(query=dense, using="dense", limit=per_branch),
                m.Prefetch(query=m.SparseVector(indices=idx, values=val), using="sparse", limit=per_branch),
            ],
            query=m.FusionQuery(fusion=m.Fusion.RRF),
            limit=k * 2, with_payload=True).points
        for p in res:
            if p.id not in best or p.score > best[p.id].score:
                best[p.id] = p
    return sorted(best.values(), key=lambda p: -p.score)[:k * 2]


def rerank(llm, query, points, k):
    """Формат /rerank у прокси может отличаться — при ошибке возвращаем порядок гибридного поиска."""
    try:
        r = llm.post("/rerank", cast_to=object, body={
            "model": RERANK_MODEL, "query": query,
            "documents": [f"{p.payload['doc']} | {p.payload['section']}\n{p.payload['text']}" for p in points]})
        order = sorted(r["results"], key=lambda x: -x["relevance_score"])
        return [points[o["index"]] for o in order][:k]
    except Exception as e:
        print(f"[rerank недоступен: {e!r}] — без реранка")
        return points[:k]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--rerank", action="store_true")
    a = ap.parse_args()
    qc, llm = qdrant_client(), get_llm()
    pts = hybrid_search(qc, llm, [a.query], a.k)
    if a.rerank:
        pts = rerank(llm, a.query, pts, a.k)
    for p in pts[:a.k]:
        pl = p.payload
        print(f"\n[{pl['id']}] {pl['doc']} | {pl['section']} | п.{pl['clause']}  (score={p.score:.3f})")
        print("   ", pl["text"][:300].replace("\n", " ⏎ "))