"""
embed.py — расчёт эмбеддингов с возобновлением и обработкой ошибок.
"""
import argparse, json, os, re, sqlite3, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

INDEX_DIR = "index"
DB_PATH = os.path.join(INDEX_DIR, "kb.db")
EMB_MODEL = os.getenv("EMB_MODEL", "BAAI/bge-m3")
BATCH = 16
DIM = 1024  # bge-m3


def _tokens(s: str):
    return [w[:6] for w in re.findall(r"[а-яёa-z0-9]+", s.lower())]


def _llm():
    return OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])


def _embed_batch(cl, texts):
    """2.3: retry с экспоненциальной задержкой."""
    for attempt in range(5):
        try:
            r = cl.embeddings.create(model=EMB_MODEL, input=texts)
            vecs = [d.embedding for d in sorted(r.data, key=lambda d: d.index)]
            # 2.4: проверка размерности
            for v in vecs:
                if len(v) != DIM:
                    raise ValueError(f"Ожидалась размерность {DIM}, получено {len(v)}")
            return vecs
        except Exception as e:
            wait = 2 ** attempt
            print(f"[retry {attempt + 1}] {e!r}; жду {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("не удалось получить эмбеддинги")


def _prepare_text(row):
    """2.1: восстанавливаем текст с part и context."""
    # row: (id, type, file, doc, section, clause, doc_date, is_amendment, lost, amends_doc, part, context, text)
    c_id, _, _, doc, section, clause, _, _, _, _, part, context, text = row
    head = f"{doc} | {section}"
    if part:
        head += f" | ч.{part}"
    if context:
        head += f" | {context}"
    if clause:
        head += f" | п.{clause}"
    return f"{head}\n{text}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="пересчитать ВСЕ векторы")
    args = ap.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"❌ База не найдена: {DB_PATH}. Сначала: python rag/chunk.py", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    if args.force:
        rows = conn.execute(
            "SELECT id, type, file, doc, section, clause, doc_date, is_amendment, lost, amends_doc, part, context, text FROM chunks"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, type, file, doc, section, clause, doc_date, is_amendment, lost, amends_doc, part, context, text "
            "FROM chunks WHERE dense_vec IS NULL"
        ).fetchall()
    conn.close()

    if not rows:
        print("✅ Все чанки уже имеют векторы.")
        return

    batches = [(i, rows[i:i + BATCH]) for i in range(0, len(rows), BATCH)]
    workers = int(os.getenv("MAX_WORKERS", 4))
    print(f"Чанков без векторов: {len(rows)}, батчей: {len(batches)}, воркеров: {workers}", file=sys.stderr)

    llm = _llm()
    done = 0
    failed = 0

    def process_batch(start_idx, part):
        try:
            texts = [_prepare_text(r) for r in part]
            vecs = _embed_batch(llm, texts)
            updates = []
            for j, r in enumerate(part):
                vec_json = json.dumps(vecs[j])
                sparse_str = " ".join(_tokens(texts[j]))
                updates.append((vec_json, sparse_str, r[0]))
            return updates
        except Exception as e:
            print(f"\n[batch {start_idx} failed: {e!r}]", file=sys.stderr)
            return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(process_batch, s, p) for s, p in batches]
        conn = sqlite3.connect(DB_PATH)
        for f in as_completed(futures):
            updates = f.result()
            if updates is None:
                failed += BATCH
            else:
                conn.executemany("UPDATE chunks SET dense_vec=?, sparse_tokens=? WHERE id=?", updates)
                conn.commit()
                done += len(updates)
            print(f"\r{done}/{len(rows)} (failed: {failed})", end="", file=sys.stderr)
        conn.close()

    print(f"\n✅ Готово: {done} векторов сохранено, {failed} ошибок", file=sys.stderr)


if __name__ == "__main__":
    main()