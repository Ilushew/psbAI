"""
search_table.py — гибридный поиск по SQLite (dense + sparse) + опциональный реранкер.
Используется как модуль из generate.py, а также как CLI для ручной проверки.

Переменные окружения:
  EMB_MODEL        — модель эмбеддингов (по умолчанию BAAI/bge-m3)
  RERANKER_MODEL   — модель реранкера (по умолчанию Qwen3-Reranker-8B)
  RERANKER_TOP_N   — сколько чанков оставить после реранка
  TOP_K            — сколько чанков вернуть до реранка
"""
import json, os, re, sqlite3
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


def search(query: str, k: int | None = None, rerank: bool = False) -> list[dict]:
    """
    Возвращает список чанков, отсортированных по релевантности.
    k — сколько вернуть (по умолчанию берётся из TOP_K или 8).
    rerank — прогнать результаты через реранкер.
    """
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"База не найдена: {DB_PATH}. Сначала: python rag/chunk.py && python rag/embed.py")

    if k is None:
        k = int(os.getenv("TOP_K", 8))

    llm = _llm()

    # 1. Эмбеддинг запроса
    q_emb = llm.embeddings.create(model=EMB_MODEL, input=[query]).data[0].embedding
    q_vec = np.array(q_emb, dtype=np.float32)
    q_tokens = set(_tokens(query))

    # 2. Читаем все чанки с векторами
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, type, file, doc, section, clause, doc_date, is_amendment, lost, text, dense_vec, sparse_tokens "
        "FROM chunks WHERE dense_vec IS NOT NULL"
    ).fetchall()
    conn.close()

    if not rows:
        return []

    # 3. Считаем гибридный скор
    scored = []
    for r in rows:
        c_id, typ, file, doc, section, clause, doc_date, is_amend, lost, text, vec_json, sparse_str = r
        c_vec = np.array(json.loads(vec_json), dtype=np.float32)
        dense = float(np.dot(q_vec, c_vec))

        c_tokens = set(sparse_str.split()) if sparse_str else set()
        overlap = len(q_tokens & c_tokens)
        sparse = overlap / max(len(q_tokens), 1)

        # RRF-подобное слияние: нормируем dense в [0,1] (для bge-m3 косинус обычно >0),
        # sparse уже в [0,1]. Веса: 70% семантика, 30% лексика.
        score = 0.7 * dense + 0.3 * sparse

        scored.append({
            "id": c_id, "type": typ, "file": file, "doc": doc, "section": section,
            "clause": clause, "doc_date": doc_date,
            "is_amendment": bool(is_amend), "lost": bool(lost),
            "text": text, "score": score,
        })

    scored.sort(key=lambda x: -x["score"])
    top = scored[: k * 3]  # берём с запасом для реранкера

    # 4. Опциональный реранкер
    if rerank:
        top_n = int(os.getenv("RERANKER_TOP_N", k))
        top = _rerank(llm, query, top, top_n)

    return top[:k]


def _rerank(llm, query: str, items: list[dict], top_n: int) -> list[dict]:
    """Вызов /rerank через OpenAI-совместимый прокси. При ошибке — возвращаем как есть."""
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
        print(f"[rerank недоступен: {e!r}] — оставляем порядок гибридного поиска")
        return items[:top_n]


# ────────────────────────── CLI для ручной проверки ─────────────────────────
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
        print(f"\n[{c['id']}] {c['doc']} | {c['section']} | п.{c['clause']}{amend}{lost}  score={c['score']:.3f}")
        print("   ", c["text"][:300].replace("\n", " ⏎ "))