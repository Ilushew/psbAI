"""
embed.py — расчёт эмбеддингов для чанков из index/kb.db.
Поддерживает возобновление: считает только строки, у которых dense_vec IS NULL.
Использует MAX_WORKERS для параллельных запросов к API.
"""
import argparse, json, os, re, sqlite3, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

INDEX_DIR = "index"
DB_PATH = os.path.join(INDEX_DIR, "kb.db")
EMB_MODEL = os.getenv("EMB_MODEL", "BAAI/bge-m3")
BATCH = 16


def _tokens(s: str):
    return [w[:6] for w in re.findall(r"[а-яёa-z0-9]+", s.lower())]


def _llm():
    return OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])


def _embed_batch(cl, texts):
    for attempt in range(5):
        try:
            r = cl.embeddings.create(model=EMB_MODEL, input=texts)
            return [d.embedding for d in sorted(r.data, key=lambda d: d.index)]
        except Exception as e:
            wait = 2 ** attempt
            print(f"[retry {attempt + 1}] {e!r}; жду {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("не удалось получить эмбеддинги")


def _prepare_text(row):
    # row: (id, type, file, doc, section, clause, doc_date, is_amendment, lost, text)
    c_id, _, _, doc, section, clause, _, _, _, text = row
    head = f"{doc} | {section}"
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
            "SELECT id, type, file, doc, section, clause, doc_date, is_amendment, lost, text FROM chunks"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, type, file, doc, section, clause, doc_date, is_amendment, lost, text "
            "FROM chunks WHERE dense_vec IS NULL"
        ).fetchall()
    conn.close()

    if not rows:
        print("✅ Все чанки уже имеют векторы.")
        return

    # Разбиваем на батчи
    batches = [(i, rows[i:i + BATCH]) for i in range(0, len(rows), BATCH)]
    workers = int(os.getenv("MAX_WORKERS", 4))
    print(f"Чанков без векторов: {len(rows)}, батчей: {len(batches)}, воркеров: {workers}", file=sys.stderr)

    llm = _llm()
    done = 0

    def process_batch(start_idx, part):
        texts = [_prepare_text(r) for r in part]
        vecs = _embed_batch(llm, texts)
        updates = []
        for j, r in enumerate(part):
            vec_json = json.dumps(vecs[j])
            sparse_str = " ".join(_tokens(texts[j]))
            updates.append((vec_json, sparse_str, r[0]))
        return updates

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(process_batch, s, p) for s, p in batches]
        # Собираем результаты и пишем в БД последовательно (чтобы не держать много коннектов)
        conn = sqlite3.connect(DB_PATH)
        for f in as_completed(futures):
            updates = f.result()
            conn.executemany("UPDATE chunks SET dense_vec=?, sparse_tokens=? WHERE id=?", updates)
            conn.commit()
            done += len(updates)
            print(f"\r{done}/{len(rows)}", end="", file=sys.stderr)
        conn.close()

    print(f"\n✅ Готово: {len(rows)} векторов сохранено в {DB_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()