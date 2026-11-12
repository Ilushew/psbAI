"""
ingest.py — чанкинг базы знаний и расчёт эмбеддингов (BAAI/bge-m3).
Сохраняет всё в локальную SQLite-таблицу index/kb.db (без Qdrant).

Запуск из корня проекта (psbAI/):
    pip install openai numpy python-docx pypdf beautifulsoup4
    export LLM_BASE_URL=...   LLM_API_KEY=...
    python rag/ingest.py --inspect          # только чанкинг, без API
    python rag/ingest.py --inspect --show 5 # показать 5 случайных чанков каждого типа
    python rag/ingest.py                    # чанкинг + эмбеддинги -> index/kb.db
"""
import argparse, json, os, random, re, sqlite3, statistics, sys, time
from pathlib import Path

# ────────────────────────── константы ─────────────────────────
DATA_DIR = "data"
INDEX_DIR = "index"
DB_PATH = os.path.join(INDEX_DIR, "kb.db")
EMB_MODEL = os.getenv("EMB_MODEL", "BAAI/bge-m3")
DIM = 1024  # bge-m3

DOC_NUM_RE = re.compile(r"№\s*([A-Za-zА-Яа-я0-9-/.]+)")
DATE_RE = re.compile(
    r"(\d{1,2}[.\s]\d{2}[.\s]\d{4}|\d{1,2}\s+"
    r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4})"
)

LAW_MAX = 3500       # статья закона длиннее — режем по частям
COMPANY_MAX = 1800   # пункт/раздел документа компании длиннее — режем по абзацам
OVERLAP = 150
BATCH = 16

# ────────────────────────── чтение файлов ─────────────────────────
def read_file(p: Path) -> str:
    s = p.suffix.lower()
    if s in (".txt", ".md", ".json", ".csv"):
        return p.read_text(encoding="utf-8", errors="ignore")
    if s == ".docx":
        import docx
        d = docx.Document(str(p))
        parts = [x.text for x in d.paragraphs]
        for t in d.tables:
            for r in t.rows:
                parts.append(" | ".join(c.text.strip() for c in r.cells))
        return "\n".join(parts)
    if s == ".pdf":
        from pypdf import PdfReader
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
    if s in (".html", ".htm"):
        from bs4 import BeautifulSoup
        return BeautifulSoup(p.read_text(encoding="utf-8", errors="ignore"), "html.parser").get_text("\n")
    return ""


def clean(t: str) -> str:
    t = t.replace("\r", " ").replace("\xa0", "  ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


# ────────────────────────── метаданные документа ─────────────────────────
def extract_doc_meta(text: str, file_stem: str) -> dict:
    """Достаём номер, дату и признак 'утратил силу' из шапки документа."""
    head = text[:1500]
    num = None
    m = DOC_NUM_RE.search(head[:500])
    if m:
        num = m.group(1).strip(".")
    dates = DATE_RE.findall(head[:500])
    date = dates[-1] if dates else None
    lost = bool(re.search(r"утратил силу|утративш", file_stem + " " + head[:500], re.I))
    return {"num": num, "date": date, "lost": lost}


def doc_type(name: str) -> str:
    n = name.lower()
    if n.startswith("законы"):
        return "law"
    if n.startswith("документы"):
        return "company"
    return "other"


def law_ref_from_name(name: str) -> str:
    """'законы__НК_ст112_...' -> 'НК ст. 112' (человекочитаемая ссылка для цитирования)."""
    m = re.match(r"законы__([A-Za-zА-Яа-я0-9]+?)_ст(\d+(?:[.-]\d+)*)", name)
    if m:
        return f"{m.group(1)} ст. {m.group(2)}"
    m = re.match(r"законы_([^_]+)", name)
    return m.group(1) if m else name


# ────────────────────────── window: перекрытие по границе слова ─────────────────────────
def window(text: str, max_chars: int):
    if len(text) <= max_chars:
        return [text]
    paras = re.split(r"\n+", text)
    out, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 1 <= max_chars:
            cur = f"{cur}\n{p}" if cur else p
            continue
        if cur:
            out.append(cur)
        if len(p) > max_chars:
            sent = re.split(r"(?<=[.;:])\s+", p)
            buf = ""
            for s in sent:
                if len(buf) + len(s) + 1 > max_chars and buf:
                    out.append(buf)
                    tail = buf[-OVERLAP:]
                    sp = tail.find(" ")
                    buf = (tail[sp + 1:] if sp != -1 else tail) + " " + s
                else:
                    buf = f"{buf} {s}".strip()
            cur = buf
        else:
            tail = out[-1][-OVERLAP:] if out else ""
            sp = tail.find(" ")
            tail = tail[sp + 1:] if sp != -1 else tail
            cur = f"{tail}\n{p}".strip()
    if cur:
        out.append(cur)
    return out


# ────────────────────────── чанкинг законов ─────────────────────────
LAW_PART = re.compile(r"^\s*(\d{1,2}(?:\.\d+)?[.)]\s|п\.\s*\d+)")


def chunk_law(text: str, file_stem: str):
    ref = law_ref_from_name(file_stem)
    lines = text.split("\n")
    title = lines[0].strip()[:200] if lines else ""
    if len(text) <= LAW_MAX:
        return [{"section": title or ref, "ref": ref, "text": text}]

    # сначала собираем пункты с их заголовками
    parts, cur_head, cur_body = [], "", []
    for ln in lines[1:]:
        m = LAW_PART.match(ln)
        if m and cur_body:
            parts.append((cur_head, "\n".join(cur_body)))
            cur_head, cur_body = m.group(0).strip(), []
        elif m:
            cur_head = m.group(0).strip()
        cur_body.append(ln)
    if cur_body:
        parts.append((cur_head, "\n".join(cur_body)))

    # склеиваем до лимита, сохраняя заголовок родителя как контекст
    out, buf, head_ctx = [], "", ""
    for h, b in parts:
        if len(buf) + len(b) > LAW_MAX and buf:
            out.append((head_ctx, buf))
            buf, head_ctx = "", ""
        if not head_ctx:
            head_ctx = h
        buf = f"{buf}\n{b}".strip()
    if buf:
        out.append((head_ctx, buf))

    res = []
    for i, (ctx, b) in enumerate(out):
        for w in window(b, LAW_MAX):
            res.append({
                "section": title,
                "part": i + 1,
                "context": ctx,
                "ref": ref,
                "text": w,
            })
    return res


# ────────────────────────── чанкинг документов компании ─────────────────────────
SECTION = re.compile(r"^\s*(\d{1,2})\.\s+[А-ЯЁA-Z][^\n]{2,120}$")
CLAUSE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,3}){1,3})\.?\s+\S")
SPECIAL = re.compile(
    r"^\s*(Статья|Глава|Раздел|Приложение|Дополнительное соглашение|Спецификация|Протокол)\b.*", re.I
)


def chunk_company(text: str, file_stem: str):
    lines = text.split("\n")
    raw_title = next((l.strip() for l in lines if l.strip()), file_stem)[:200]

    meta = extract_doc_meta(text, file_stem)

    doc_label = raw_title
    if meta["num"]:
        if meta["num"] not in raw_title:
            doc_label = f"{raw_title} № {meta['num']}"
    if meta["date"]:
        year_m = re.search(r"\d{4}\b", meta["date"])
        if year_m:
            doc_label += f" (ред. {year_m.group(0)})"
        else:
            doc_label += f" (от {meta['date']})"
    if meta["lost"]:
        doc_label += " [утратил силу]"

    sections, cur_head, buf = [], "Преамбула", []

    def flush():
        if "".join(buf).strip():
            sections.append((cur_head, "\n".join(buf).strip()))

    for ln in lines:
        if SECTION.match(ln) or (SPECIAL.match(ln) and len(ln) < 160):
            flush()
            buf.clear()
            cur_head = ln.strip()[:140]
        buf.append(ln)
    flush()

    chunks = []
    for head, body in sections:
        clauses, cur = [], []
        for ln in body.split("\n"):
            if CLAUSE.match(ln) and cur:
                clauses.append("\n".join(cur))
                cur = []
            cur.append(ln)
        if cur:
            clauses.append("\n".join(cur))

        group, first_no = "", None
        for c in clauses:
            m = CLAUSE.match(c)
            no = m.group(1) if m else None
            if len(group) + len(c) > COMPANY_MAX and group:
                chunks.append({"section": head, "clause": first_no, "text": group})
                group, first_no = "", None
            if first_no is None:
                first_no = no
            group = f"{group}\n{c}".strip()
        if group:
            chunks.append({"section": head, "clause": first_no, "text": group})

    final = []
    for c in chunks:
        for w in window(c["text"], COMPANY_MAX):
            final.append({**c, "text": w})

    is_amend = bool(re.search(r"дополнительное соглашение|изменени[яе] в договор", text[:2000], re.I))
    for c in final:
        c["doc_title"] = doc_label
        c["doc_date"] = meta["date"]
        c["doc_num"] = meta["num"]
        c["is_amendment"] = is_amend
        c["lost"] = meta["lost"]
    return final


# ────────────────────────── сборка ─────────────────────────
def build_chunks():
    chunks = []
    for p in sorted(Path(DATA_DIR).rglob("*")):
        if not p.is_file() or p.suffix.lower() == ".zip":
            continue
        text = clean(read_file(p))
        if not text:
            print(f"[skip] пустой/неподдерживаемый файл: {p}", file=sys.stderr)
            continue
        typ = doc_type(p.stem)
        items = chunk_law(text, p.stem) if typ == "law" else chunk_company(text, p.stem)
        for it in items:
            chunks.append({
                "id": f"c{len(chunks):05d}",
                "file": p.name,
                "type": typ,
                "doc": it.get("ref") or it.get("doc_title") or p.stem,
                "section": it.get("section", ""),
                "clause": it.get("clause"),
                "doc_date": it.get("doc_date"),
                "is_amendment": it.get("is_amendment", False),
                "lost": it.get("lost", False),
                "text": it["text"],
            })
    return chunks


def embed_text(c):
    head = f"{c['doc']} | {c['section']}"
    if c.get("part"):
        head += f" | ч.{c['part']}"
    if c.get("context"):
        head += f" | {c['context']}"
    if c.get("clause"):
        head += f" | п.{c['clause']}"
    return f"{head}\n{c['text']}"


def inspect(chunks, show):
    for typ in ("law", "company", "other"):
        xs = [c for c in chunks if c["type"] == typ]
        if not xs:
            continue
        L = [len(c["text"]) for c in xs]
        print(f"\n=== {typ}: {len(xs)} чанков, файлов {len({c['file'] for c in xs})}; "
              f"длина min/median/max = {min(L)}/{int(statistics.median(L))}/{max(L)}")
        for c in random.sample(xs, min(show, len(xs))):
            print(f"\n--- [{c['id']}] {c['file']}\n    "
                  f"doc={c['doc']} | section={c['section']} | clause={c['clause']} "
                  f"| date={c['doc_date']} | amend={c['is_amendment']}\n    "
                  f"{c['text'][:350].replace(chr(10), ' ⏎ ')}…")
    tiny = [c for c in chunks if len(c["text"]) < 80]
    print(f"\nПодозрительно коротких (<80 симв.): {len(tiny)}")
    by_file = {}
    for c in chunks:
        by_file[c["file"]] = by_file.get(c["file"], 0) + 1
    print("Чанков на файл:", dict(sorted(by_file.items(), key=lambda x: -x[1])[:15]))


# ────────────────────────── эмбеддинги и сохранение в SQLite ─────────────────────────
def tokens(s: str):
    """Простейший «стемминг» для русского: обрезка до 6 символов."""
    return [w[:6] for w in re.findall(r"[а-яёa-z0-9]+", s.lower())]


def get_llm_client():
    from openai import OpenAI
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


def save_to_sqlite(chunks):
    os.makedirs(INDEX_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY,
            type TEXT,
            file TEXT,
            doc TEXT,
            section TEXT,
            clause TEXT,
            doc_date TEXT,
            is_amendment INTEGER,
            lost INTEGER,
            text TEXT,
            dense_vec TEXT,
            sparse_tokens TEXT
        )
    """)
    cur.execute("DELETE FROM chunks")

    llm = get_llm_client()
    print(f"Начинаем расчёт эмбеддингов для {len(chunks)} чанков...", file=sys.stderr)

    for i in range(0, len(chunks), BATCH):
        part = chunks[i:i + BATCH]
        texts = [embed_text(c) for c in part]
        dense_vectors = embed_batch(llm, texts)

        rows = []
        for j, c in enumerate(part):
            vec_json = json.dumps(dense_vectors[j])
            sparse_str = " ".join(tokens(texts[j]))
            rows.append((
                c["id"], c["type"], c["file"], c["doc"], c["section"],
                c["clause"], c["doc_date"],
                int(c.get("is_amendment", False)),
                int(c.get("lost", False)),
                c["text"], vec_json, sparse_str,
            ))

        cur.executemany("""
            INSERT INTO chunks
            (id, type, file, doc, section, clause, doc_date, is_amendment, lost, text, dense_vec, sparse_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        conn.commit()
        print(f"\r{min(i + BATCH, len(chunks))}/{len(chunks)}", end="", file=sys.stderr)

    conn.close()
    print(f"\n✅ Готово! Данные сохранены в {DB_PATH}", file=sys.stderr)


# ────────────────────────── main ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true", help="только чанкинг, без обращения к API")
    ap.add_argument("--show", type=int, default=3, help="сколько примеров каждого типа печатать")
    args = ap.parse_args()

    chunks = build_chunks()
    print(f"Всего чанков: {len(chunks)}")

    os.makedirs(INDEX_DIR, exist_ok=True)
    with open(f"{INDEX_DIR}/chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    if args.inspect:
        inspect(chunks, args.show)
        print(f"\nЧанки сохранены в {INDEX_DIR}/chunks.jsonl (эмбеддинги не считались).")
        return

    save_to_sqlite(chunks)


if __name__ == "__main__":
    main()