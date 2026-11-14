"""
search_table.py — гибридный поиск: Dense (cosine) + Sparse (BM25) + RRF + Reranker.

Индекс загружается ОДИН раз за процесс:
  * векторы -> нормализованная numpy-матрица (N x DIM), cosine = одно матричное умножение;
  * BM25    -> для каждого терма заранее посчитаны вклады (idf * tf-часть) по документам,
               запрос = сумма нескольких коротких numpy-массивов.
Чанки без вектора (упавший батч эмбеддингов) не пропадают: у них нулевой вектор,
и они находятся через BM25.
"""
import json, math, os, re, sqlite3, sys, threading
from collections import Counter

import numpy as np
from openai import OpenAI

INDEX_DIR = "index"
DB_PATH = os.path.join(INDEX_DIR, "kb.db")
EMB_MODEL = os.getenv("EMB_MODEL", "BAAI/bge-m3")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "Qwen3-Reranker-8B")

K1, B = 1.5, 0.75
RRF_K = 60
DEFAULT_DIM = 1024  # bge-m3


# ───────────────────────── клиент (один на процесс) ─────────────────────────
_client = None
_client_lock = threading.Lock()


def _llm():
    """Общий потокобезопасный клиент: таймаут + несколько ретраев на 429/5xx."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = OpenAI(
                    base_url=os.environ["LLM_BASE_URL"],
                    api_key=os.environ["LLM_API_KEY"],
                    timeout=60,
                    max_retries=2,
                )
    return _client


def _tokens(s: str):
    return [w[:6] for w in re.findall(r"[а-яёa-z0-9]+", s.lower())]


# ───────────────────────── индекс ─────────────────────────
class _Index:
    def __init__(self, db_path: str):
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"База не найдена: {db_path}")

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT id, type, file, doc, section, clause, doc_date, is_amendment, lost, "
            "amends_doc, part, context, text, dense_vec, sparse_tokens FROM chunks"
        ).fetchall()
        conn.close()

        self.n = len(rows)
        self.chunks: list[dict] = []
        tokens_all: list[list[str]] = []
        vec_lists: list = []
        dim = None

        for r in rows:
            (c_id, typ, file, doc, section, clause, doc_date, is_amend, lost,
             amends_doc, part, context, text, vec_json, sparse_str) = r
            self.chunks.append({
                "id": c_id, "type": typ, "file": file, "doc": doc, "section": section,
                "clause": clause, "doc_date": doc_date,
                "is_amendment": bool(is_amend), "lost": bool(lost), "amends_doc": amends_doc,
                "part": part, "context": context, "text": text,
            })
            tokens_all.append(sparse_str.split() if sparse_str else [])
            if vec_json:
                v = json.loads(vec_json)
                dim = dim or len(v)
                vec_lists.append(v)
            else:
                vec_lists.append(None)

        # ---- dense: нормализованная матрица ----
        dim = dim or DEFAULT_DIM
        self.dim = dim
        M = np.zeros((self.n, dim), dtype=np.float32)
        missing = 0
        for i, v in enumerate(vec_lists):
            if v is not None and len(v) == dim:
                M[i] = v
            else:
                missing += 1
        norms = np.linalg.norm(M, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.M = M / norms
        if missing:
            print(f"[index] чанков без вектора: {missing} (ищутся только через BM25)", file=sys.stderr)

        # ---- BM25: предрасчёт вкладов терм -> (doc_idx, score) ----
        dl = np.array([len(t) for t in tokens_all], dtype=np.float32)
        avg_dl = float(dl.mean()) if self.n and dl.mean() > 0 else 1.0

        postings: dict[str, tuple[list, list]] = {}
        for i, toks in enumerate(tokens_all):
            for t, f in Counter(toks).items():
                p = postings.setdefault(t, ([], []))
                p[0].append(i)
                p[1].append(f)

        self.bm25: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for t, (docs, tfs) in postings.items():
            n_t = len(docs)
            idf = math.log((self.n - n_t + 0.5) / (n_t + 0.5) + 1)
            d = np.asarray(docs, dtype=np.int32)
            f = np.asarray(tfs, dtype=np.float32)
            w = idf * f * (K1 + 1) / (f + K1 * (1 - B + B * dl[d] / avg_dl))
            self.bm25[t] = (d, w.astype(np.float32))

        # ---- прочее ----
        self.lost_penalty = np.array([0.3 if c["lost"] else 1.0 for c in self.chunks], dtype=np.float32)
        self._textset_cache: dict[int, set] = {}
        print(f"[index] загружено чанков: {self.n}, термов BM25: {len(self.bm25)}", file=sys.stderr)

    # --- сорсинг ---
    def bm25_scores(self, q_tokens: list[str]) -> np.ndarray:
        s = np.zeros(self.n, dtype=np.float32)
        for t in q_tokens:
            e = self.bm25.get(t)
            if e is not None:
                s[e[0]] += e[1]
        return s

    def textset(self, i: int) -> set:
        s = self._textset_cache.get(i)
        if s is None:
            s = set(_tokens(self.chunks[i]["text"]))
            self._textset_cache[i] = s
        return s


_index: _Index | None = None
_index_lock = threading.Lock()


def get_index() -> _Index:
    """Ленивая загрузка индекса (один раз, потокобезопасно)."""
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                _index = _Index(DB_PATH)
    return _index


def reset_index():
    global _index
    with _index_lock:
        _index = None


# ───────────────────────── вспомогательное ─────────────────────────
def _ranks(scores: np.ndarray) -> np.ndarray:
    order = np.argsort(-scores, kind="stable")
    r = np.empty(len(scores), dtype=np.float32)
    r[order] = np.arange(len(scores), dtype=np.float32)
    return r


def _deduplicate(idx: _Index, cand: list[int], threshold=0.7) -> list[int]:
    """Убираем чанки из одного файла с большим перекрытием текста."""
    kept: list[int] = []
    for i in cand:
        dup = False
        for j in kept:
            if idx.chunks[i]["file"] != idx.chunks[j]["file"]:
                continue
            t1, t2 = idx.textset(i), idx.textset(j)
            if not t1 or not t2:
                continue
            if len(t1 & t2) / min(len(t1), len(t2)) > threshold:
                dup = True
                break
        if not dup:
            kept.append(i)
    return kept


# ───────────────────────── поиск ─────────────────────────
def search(query: str, k: int | None = None, rerank: bool = False) -> list[dict]:
    if k is None:
        k = int(os.getenv("TOP_K", 8))

    idx = get_index()
    if idx.n == 0:
        return []

    llm = _llm()

    # 1. эмбеддинг запроса (единственный сетевой вызов до реранкера)
    q = np.asarray(llm.embeddings.create(model=EMB_MODEL, input=[query]).data[0].embedding,
                   dtype=np.float32)
    qn = np.linalg.norm(q)
    q = q / qn if qn else q

    # 2. dense + sparse — векторизовано
    dense = idx.M @ q
    sparse = idx.bm25_scores(_tokens(query))

    # 3. RRF
    rrf = 1.0 / (RRF_K + _ranks(dense) + 1) + 1.0 / (RRF_K + _ranks(sparse) + 1)

    # 4. штраф за утратившие силу
    final = rrf * idx.lost_penalty

    # 5. кандидаты
    n_cand = min(idx.n, k * 3)
    top = np.argpartition(-final, n_cand - 1)[:n_cand] if n_cand < idx.n else np.arange(idx.n)
    top = top[np.argsort(-final[top], kind="stable")]
    top = _deduplicate(idx, [int(i) for i in top])

    items = []
    for i in top:
        c = dict(idx.chunks[i])
        c["dense"] = float(dense[i])
        c["sparse"] = float(sparse[i])
        c["score"] = float(final[i])
        items.append(c)

    # 6. реранкер
    if rerank:
        items = _rerank(llm, query, items, int(os.getenv("RERANKER_TOP_N", k)))

    return items[:k]


def _rerank(llm, query: str, items: list[dict], top_n: int) -> list[dict]:
    try:
        docs = [f"{c['doc']} | {c['section']}\n{c['text']}" for c in items]
        r = llm.post("/rerank", cast_to=object,
                     body={"model": RERANKER_MODEL, "query": query, "documents": docs})
        order = sorted(r["results"], key=lambda x: -x["relevance_score"])
        out = []
        for o in order[:top_n]:
            c = items[o["index"]]
            c["rerank_score"] = float(o["relevance_score"])  # пригодится для порога отказа
            out.append(c)
        return out
    except Exception as e:
        print(f"[rerank недоступен: {e!r}]", file=sys.stderr)
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