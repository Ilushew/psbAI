"""
embed.py — расчёт эмбеддингов для чанков из index/kb.db.
Читает чанки, у которых dense_vec IS NULL, считает батчами и обновляет таблицу.
Если процесс прервётся — следующий запуск продолжит с того места, где остановился.

Запуск:
    python rag/embed.py              # рассчитать эмбеддинги для всех чанков без векторов
    python rag/embed.py --force      # пересчитать ВСЕ векторы заново
"""
import argparse, json, os, re, sqlite3, sys, time
from openai import OpenAI

INDEX_DIR = "index"
DB_PATH = os.path.join(INDEX_DIR, "kb.db")
EMB_MODEL = os.getenv("EMB_MODEL", "BAAI/bge-m3")
BATCH = 16


def tokens(s: str):
    """Простейший «стемминг» для русского: обрезка до 6 символов."""
    return [w[:6] for w in re.findall(r"[а-яёa-z0-9]+", s.lower())]


def get_llm_client():
    return OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])


def embed_batch(cl, texts):
    for attempt in range(5):
        try:
            r = cl.embeddings.create(model=EMB_MODEL, input=texts)
            return [d.embedding for d in sorted(r.data, key=lambda d: d.index)]
        except Exception as e:
            wait = 2 ** attempt
            print(f"[retry {attempt + 1}] {e!r}; жду {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("не удалось получить эмбеддинги")


def prepare_text(row):
    """Восстанавливаем текст для эмбеддинга из колонок таблицы."""
    c_id, doc, section, clause, text = row[0], row[3], row[4], row[5], row[9]
    head = f"{doc} | {section}"
    if clause:
        head += f" | п.{clause}"
    return f"{head}\n{text}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="пересчитать ВСЕ векторы заново")
    args = ap.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"❌ База данных не найдена: {DB_PATH}", file=sys.stderr)
        print("Сначала запустите: python rag/chunk.py", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Выбираем чанки без векторов (или все, если --force)
    if args.force:
        cur.execute("SELECT id, type, file, doc, section, clause, doc_date, is_amendment, lost, text FROM chunks")
    else:
        cur.execute("SELECT id, type, file, doc, section, clause, doc_date, is_amendment, lost, text FROM chunks WHERE dense_vec IS NULL")

    rows = cur.fetchall()
    if not rows:
        print("✅ Все чанки уже имеют векторы. Нечего считать.")
        conn.close()
        return

    print(f"Нужно рассчитать эмбеддинги для {len(rows)} чанков...", file=sys.stderr)
    llm = get_llm_client()

    for i in range(0, len(rows), BATCH):
        part = rows[i:i + BATCH]
        texts = [prepare_text(r) for r in part]
        dense_vectors = embed_batch(llm, texts)

        updates = []
        for j, r in enumerate(part):
            vec_json = json.dumps(dense_vectors[j])
            sparse_str = " ".join(tokens(texts[j]))
            updates.append((vec_json, sparse_str, r[0]))  # dense_vec, sparse_tokens, id

        cur.executemany("UPDATE chunks SET dense_vec=?, sparse_tokens=? WHERE id=?", updates)
        conn.commit()
        print(f"\r{min(i + BATCH, len(rows))}/{len(rows)}", end="", file=sys.stderr)

    conn.close()
    print(f"\n✅ Готово! Векторы сохранены в {DB_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()