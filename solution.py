"""
solution.py — точка входа для платформы.
Читает DATA_DIR, распаковывает базу в /tmp, строит индекс (если нужно),
параллельно отвечает на вопросы в рамках глобального бюджета времени,
ВСЕГДА пишет полный submission.csv (id,answer).
"""
import csv, os, sqlite3, subprocess, sys, time, zipfile
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path

T0 = time.monotonic()

HERE = Path(__file__).resolve().parent
DATA_DIR = os.getenv("DATA_DIR", "data")
KB_DIR = "/tmp/kb"
DB_PATH = os.path.join("index", "kb.db")

# Лимит платформы 20 мин. Мягкий бюджет — после него новые вопросы не стартуют,
# жёсткий — после него не ждём зависшие запросы и пишем файл.
BUDGET_SEC = float(os.getenv("TIME_BUDGET_SEC", 17 * 60))
HARD_EXTRA_SEC = float(os.getenv("HARD_EXTRA_SEC", 90))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", 8))
MAX_ANSWER_LEN = 10_000

FALLBACK = ("Не удалось сформировать ответ в отведённое время. "
            "Достоверный ответ на основе базы знаний не подготовлен.")


def log(*a):
    print(f"[{time.monotonic() - T0:6.1f}s]", *a, file=sys.stderr, flush=True)


# ───────────────────────── подготовка индекса ─────────────────────────
def _has_null_vectors(db_path: str) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT 1 FROM chunks WHERE dense_vec IS NULL LIMIT 1").fetchone() is not None
    finally:
        conn.close()


def ensure_index():
    zip_path = os.path.join(DATA_DIR, "knowledge-base.zip")
    if os.path.exists(zip_path):
        os.makedirs(KB_DIR, exist_ok=True)
        log(f"распаковываю {zip_path} -> {KB_DIR}")
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(KB_DIR)
    else:
        log(f"⚠ нет {zip_path}, индексирую {DATA_DIR}")

    # chunk.py / embed.py читают DATA_DIR из окружения -> отдаём им только папку с базой,
    # чтобы questions.csv не попал в индекс
    env = dict(os.environ, DATA_DIR=KB_DIR if os.path.isdir(KB_DIR) else DATA_DIR)

    if not os.path.exists(DB_PATH):
        log("чанкинг...")
        subprocess.run([sys.executable, str(HERE / "chunk.py")], check=True, env=env)
    if _has_null_vectors(DB_PATH):
        log("эмбеддинги...")
        subprocess.run([sys.executable, str(HERE / "embed.py")], check=True, env=env)
        if _has_null_vectors(DB_PATH):
            log("⚠ часть чанков осталась без векторов (будут искаться через BM25)")


# ───────────────────────── вопросы ─────────────────────────
def read_questions() -> list[dict]:
    path = os.path.join(DATA_DIR, "questions.csv")
    if not os.path.exists(path):
        log(f"❌ нет файла вопросов: {path}")
        sys.exit(1)
    out = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            q_id = (row.get("id") or row.get("ID") or "").strip()
            if not q_id:
                continue
            out.append({"id": q_id, "question": row.get("question") or row.get("text") or ""})
    return out


def answer_one(q: dict, deadline: float) -> str:
    """Один вопрос; если бюджет уже исчерпан — сразу запасной ответ."""
    if time.monotonic() > deadline:
        return FALLBACK
    if not q["question"].strip():
        return "Вопрос пустой: уточните, что именно нужно найти в базе нормативных документов."
    from generate import generate  # импорт тут, чтобы ошибка импорта не роняла весь скрипт
    ans = generate(q["question"])
    return (ans or "").strip() or FALLBACK


def write_submission(questions: list[dict], answers: dict):
    with open("submission.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "answer"])
        for q in questions:
            a = (answers.get(q["id"]) or "").strip() or FALLBACK
            w.writerow([q["id"], a[:MAX_ANSWER_LEN]])


# ───────────────────────── main ─────────────────────────
def main():
    questions = read_questions()
    log(f"вопросов: {len(questions)}")
    answers: dict[str, str] = {}

    try:
        ensure_index()
        from search_table import get_index
        get_index()  # прогрев: индекс в память один раз, до старта потоков
    except Exception as e:
        # даже если индекс не собрался, файл с полным набором ID должен появиться
        log(f"❌ индекс: {e!r}")
        write_submission(questions, answers)
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(0)

    deadline = T0 + BUDGET_SEC
    hard_deadline = deadline + HARD_EXTRA_SEC

    ex = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    futs = {ex.submit(answer_one, q, deadline): q["id"] for q in questions}
    pending = set(futs)
    done_cnt = 0

    while pending and time.monotonic() < hard_deadline:
        done, pending = wait(pending, timeout=5, return_when=FIRST_COMPLETED)
        for fu in done:
            qid = futs[fu]
            try:
                answers[qid] = fu.result()
            except Exception as e:
                log(f"❌ вопрос {qid}: {e!r}")
                answers[qid] = FALLBACK
            done_cnt += 1
            if done_cnt % 10 == 0:
                log(f"готово {done_cnt}/{len(questions)}")

    if pending:
        log(f"⏱ не успели {len(pending)} вопросов -> запасной ответ")
        for fu in pending:
            fu.cancel()
    ex.shutdown(wait=False, cancel_futures=True)

    write_submission(questions, answers)
    log(f"✅ submission.csv записан, ответов: {len(answers)}/{len(questions)}")
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(0)  # не ждём зависшие потоки


if __name__ == "__main__":
    main()