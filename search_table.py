"""
search_table.py — гибридный поиск: Dense (cosine) + Sparse (BM25) + RRF + Reranker.
"""
import json, math, os, re, sqlite3
import numpy as np
from openai import OpenAI

INDEX_DIR = "index"
DB_PATH = os.path.join(INDEX_DIR, "kb.db")
EMB_MODEL = os.getenv("EMB_MODEL", "BAAI/bge-m3")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "Qwen3-Reranker-8B")


def _llm():
    return OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])


def _tokens(s: str):
    return [w[:6] for w in re.findall(r"[а-яёa-z0-9]+", s.lower())]


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """3.1: cosine similarity с явной нормализацией."""
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _bm25_score(query_tokens: list[str], doc_tokens: list[str], avg_dl: float, idf: dict, k1=1.5, b=0.75) -> float:
    """3.2: BM25 с IDF и нормализацией по длине документа."""
    dl = len(doc_tokens)
    from collections import Counter
    tf = Counter(doc_tokens)
    score = 0.0
    for t in query_tokens:
        if t not in tf or t not in idf:
            continue
        f = tf[t]
        num = f * (k1 + 1)
        den = f + k1 * (1 - b + b * dl / avg_dl)
        score += idf[t] * num / den
    return score


def _compute_idf(all_docs_tokens: list[list[str]]) -> tuple[dict[str, float], float]:
    """Считает IDF для BM25."""
    N = len(all_docs_tokens)
    df = {}
    total_dl = 0
    for doc in all_docs_tokens:
        total_dl += len(doc)
        for t in set(doc):
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log((N - n + 0.5) / (n + 0.5) + 1) for t, n in df.items()}
    avg_dl = total_dl / N if N > 0 else 1.0
    return idf, avg_dl


def _deduplicate(items: list[dict], threshold=0.7) -> list[dict]:
    """3.7: убираем чанки из одного файла с перекрытием текста > threshold."""
    if not items:
        return items
    kept = []
    for c in items:
        is_dup = False
        for k in kept:
            if c["file"] == k["file"]:
                # простое перекрытие по токенам
                t1 = set(_tokens(c["text"]))
                t2 = set(_tokens(k["text"]))
                if not t1 or not t2:
                    continue
                overlap = len(t1 & t2) / min(len(t1), len(t2))
                if overlap > threshold:
                    is_dup = True
                    break
        if not is_dup:
            kept.append(c)
    return kept


def search(query: str, k: int | None = None, rerank: bool = False) -> list[dict]:
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"База не найдена: {DB_PATH}")

    if k is None:
        k = int(os.getenv("TOP_K", 8))

    llm = _llm()

    # 1. Эмбеддинг запроса
    q_emb = llm.embeddings.create(model=EMB_MODEL, input=[query]).data[0].embedding
    q_vec = np.array(q_emb, dtype=np.float32)
    q_tokens = _tokens(query)

    # 2. Читаем все чанки
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, type, file, doc, section, clause, doc_date, is_amendment, lost, amends_doc, part, context, text, dense_vec, sparse_tokens "
        "FROM chunks WHERE dense_vec IS NOT NULL"
    ).fetchall()
    conn.close()

    if not rows:
        return []

    # 3. Готовим данные для BM25
    all_docs_tokens = [r[14].split() if r[14] else [] for r in rows]
    idf, avg_dl = _compute_idf(all_docs_tokens)

    # 4. Считаем гибридный скор
    scored = []
    for r in rows:
        c_id, typ, file, doc, section, clause, doc_date, is_amend, lost, amends_doc, part, context, text, vec_json, sparse_str = r
        c_vec = np.array(json.loads(vec_json), dtype=np.float32)

        # 3.1: cosine similarity
        dense = _cosine(q_vec, c_vec)

        # 3.2: BM25
        doc_tokens = sparse_str.split() if sparse_str else []
        sparse = _bm25_score(q_tokens, doc_tokens, avg_dl, idf)

        # 3.3: RRF будет применён после сортировки по каждому из скоров
        scored.append({
            "id": c_id, "type": typ, "file": file, "doc": doc, "section": section,
            "clause": clause, "doc_date": doc_date,
            "is_amendment": bool(is_amend), "lost": bool(lost), "amends_doc": amends_doc,
            "part": part, "context": context,
            "text": text, "dense": dense, "sparse": sparse,
        })

    # 3.3: RRF
    scored.sort(key=lambda x: -x["dense"])
    for rank, c in enumerate(scored):
        c["rrf_dense"] = 1.0 / (60 + rank + 1)
    scored.sort(key=lambda x: -x["sparse"])
    for rank, c in enumerate(scored):
        c["rrf_sparse"] = 1.0 / (60 + rank + 1)
    for c in scored:
        c["score"] = c["rrf_dense"] + c["rrf_sparse"]

    # 3.6: штраф за устаревшие документы
    for c in scored:
        if c["lost"]:
            c["score"] *= 0.3

    scored.sort(key=lambda x: -x["score"])
    top = scored[: k * 3]  # запас для реранкера

    # 3.7: дедупликация
    top = _deduplicate(top)

    # 3.4: реранкер
    if rerank:
        top_n = int(os.getenv("RERANKER_TOP_N", k))
        top = _rerank(llm, query, top, top_n)

    return top[:k]


def _rerank(llm, query: str, items: list[dict], top_n: int) -> list[dict]:
    try:
        docs = [f"{c['doc']} | {c['section']}\n{c['text']}" for c in items]
        r = llm.post(
            "/rerank",
            cast_to=object,
            body={"model": RERANKER_MODEL, "query": query, "documents": docs},
        )
        order = sorted(r["results"], key=lambda x: -x["relevance_score"])
        return [items[o["index"]] for o in order][:top_n]
    except Exception as e:
        print(f"[rerank недоступен: {e!r}]")
        return items[:top_n]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--rerank", action="store_true")
    a = ap.parse_args()

    for c in search(a.query, k=a.k, rerank=a.rerank):
        amend = " [ИЗМ]" if c["is_amendment"] else ""
        lost = " [УТРАТ]" if c["lost"] else ""
        print(f"\n[{c['id']}] {c['doc']} | {c['section']} | п.{c['clause']}{amend}{lost}  score={c['score']:.4f}")
        print("   ", c["text"][:300].replace("\n", " ⏎ "))