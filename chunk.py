"""
chunk.py — нарезка документов на чанки с сохранением юридической структуры.
Запуск:
    python rag/chunk.py --inspect          # статистика и примеры
    python rag/chunk.py                    # нарезка -> index/kb.db
"""
import argparse, json, os, random, re, sqlite3, statistics, sys
from pathlib import Path

DATA_DIR = os.getenv("DATA_DIR", "data")
INDEX_DIR = "index"
DB_PATH = os.path.join(INDEX_DIR, "kb.db")

DOC_NUM_RE = re.compile(r"№\s*([A-Za-zА-Яа-я0-9-/.]+)")
DATE_RE = re.compile(
    r"(\d{1,2}[.\s]\d{2}[.\s]\d{4}|\d{1,2}\s+"
    r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4})"
)

LAW_MAX = 3500
COMPANY_MAX = 1800
OVERLAP = 150


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


# ────────────────────────── метаданные документа (1.5) ─────────────────────────
def extract_doc_meta(text: str, file_stem: str) -> dict:
    head = text[:1500]
    num = None
    m = DOC_NUM_RE.search(head[:500])
    if m:
        num = m.group(1).strip(".")
    dates = DATE_RE.findall(head[:500])
    date = dates[-1] if dates else None

    # 1.5: более надёжное определение утративших силу
    lost_patterns = [
        r"утратил силу",
        r"утративш",
        r"не применяется",
        r"прекратил действие",
        r"признан утратившим",
    ]
    lost = any(re.search(p, file_stem + " " + head[:500], re.I) for p in lost_patterns)

    # 1.6: если это доп. соглашение — ищем ссылку на основной договор
    amends_doc = None
    am_m = re.search(
        r"(?:к\s+договору|по\s+договору|к\s+основному\s+договору|изменение\s+№?\s*\d+\s+к\s+договору)\s+"
        r"(?:№\s*)?([A-Za-zА-Яа-я0-9-/.]+)",
        head[:1000], re.I
    )
    if am_m:
        amends_doc = am_m.group(1).strip(".")

    return {"num": num, "date": date, "lost": lost, "amends_doc": amends_doc}


def doc_type(name: str) -> str:
    n = name.lower()
    if n.startswith("законы"):
        return "law"
    if n.startswith("документы"):
        return "company"
    return "other"


def law_ref_from_name(name: str) -> str:
    m = re.match(r"законы__([A-Za-zА-Яа-я0-9]+?)_ст(\d+(?:[.-]\d+)*)", name)
    if m:
        return f"{m.group(1)} ст. {m.group(2)}"
    m = re.match(r"законы_([^_]+)", name)
    return m.group(1) if m else name


# ────────────────────────── window (1.3: гарантированно <= max_chars) ─────────────────────────
def window(text: str, max_chars: int):
    """Режет текст на куски ≤ max_chars с перекрытием по границе слова."""
    if len(text) <= max_chars:
        return [text]

    out = []
    # Режем по абзацам, затем по предложениям, затем по словам
    paras = re.split(r"\n+", text)
    cur = ""
    for p in paras:
        if not p.strip():
            continue
        if len(cur) + len(p) + 1 <= max_chars:
            cur = f"{cur}\n{p}" if cur else p
            continue

        if cur:
            out.append(cur)
            cur = ""

        # абзац не влезает — режем по предложениям
        if len(p) > max_chars:
            sents = re.split(r"(?<=[.!?])\s+", p)
            buf = ""
            for s in sents:
                if len(buf) + len(s) + 1 <= max_chars:
                    buf = f"{buf} {s}".strip() if buf else s
                else:
                    if buf:
                        out.append(buf)
                    # предложение само длиннее лимита — режем по словам
                    if len(s) > max_chars:
                        words = s.split()
                        buf = ""
                        for w in words:
                            if len(buf) + len(w) + 1 <= max_chars:
                                buf = f"{buf} {w}".strip() if buf else w
                            else:
                                if buf:
                                    out.append(buf)
                                # одно слово длиннее лимита — режем жёстко
                                while len(w) > max_chars:
                                    out.append(w[:max_chars])
                                    w = w[max_chars:]
                                buf = w
                        # после цикла buf — начало следующего куска с перекрытием
                    else:
                        # перекрытие: хвост предыдущего куска
                        tail = buf[-OVERLAP:] if buf else ""
                        sp = tail.find(" ")
                        tail = tail[sp + 1:] if sp != -1 else tail
                        buf = f"{tail} {s}".strip() if tail else s
            cur = buf
        else:
            # перекрытие с предыдущим куском
            tail = out[-1][-OVERLAP:] if out else ""
            sp = tail.find(" ")
            tail = tail[sp + 1:] if sp != -1 else tail
            cur = f"{tail}\n{p}".strip() if tail else p

    if cur:
        out.append(cur)

    # финальная проверка: ни один кусок не длиннее лимита
    return [c[:max_chars] if len(c) > max_chars else c for c in out if c.strip()]


# ────────────────────────── чанкинг законов (1.4) ─────────────────────────
# 1.4: более точный regex для пунктов — учитывает "1)", "1.", "п. 1", "подпункт 1"
LAW_PART = re.compile(r"^\s*(?:(\d{1,2}(?:\.\d+)?)[.)]\s+|(?:п\.|подпункт)\s*(\d+(?:\.\d+)*))")


def chunk_law(text: str, file_stem: str):
    ref = law_ref_from_name(file_stem)
    lines = text.split("\n")
    title = lines[0].strip()[:200] if lines else ""

    # 1.4: ищем части статьи ("1.", "2.", ...)
    parts, cur_head, cur_body = [], "", []
    for ln in lines[1:]:
        m = LAW_PART.match(ln)
        if m:
            if cur_body:
                parts.append((cur_head, "\n".join(cur_body)))
            cur_head = (m.group(1) or m.group(2) or "").strip()
            cur_body = []
        cur_body.append(ln)
    if cur_body:
        parts.append((cur_head, "\n".join(cur_body)))

    # если статья короткая — один чанк
    if len(text) <= LAW_MAX:
        return [{"section": title or ref, "ref": ref, "text": text,
                 "part": None, "context": None}]

    # склеиваем до лимита
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
                "part": i + 1,          # 1.1: сохраняем part
                "context": ctx,         # 1.1: сохраняем context
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
        c["amends_doc"] = meta["amends_doc"]  # 1.6
    return final


# ────────────────────────── сборка (1.1: пробрасываем part/context) ─────────────────────────
def build_chunks():
    chunks = []
    for p in sorted(Path(f"{DATA_DIR}/tmp/kb").rglob("*")):
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
                "amends_doc": it.get("amends_doc"),  # 1.6
                "part": it.get("part"),              # 1.1
                "context": it.get("context"),        # 1.1
                "text": it["text"],
            })
    return chunks


def embed_text(c):
    """2.1: текст для эмбеддинга с part и context."""
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
                  f"| part={c.get('part')} | context={c.get('context')} "
                  f"| date={c['doc_date']} | amend={c['is_amendment']} | lost={c['lost']}\n    "
                  f"{c['text'][:350].replace(chr(10), ' ⏎ ')}…")
    tiny = [c for c in chunks if len(c["text"]) < 80]
    print(f"\nПодозрительно коротких (<80 симв.): {len(tiny)}")


# ────────────────────────── сохранение в SQLite ─────────────────────────
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
            amends_doc TEXT,
            part TEXT,
            context TEXT,
            text TEXT,
            dense_vec TEXT,
            sparse_tokens TEXT
        )
    """)
    cur.execute("DELETE FROM chunks")

    rows = []
    for c in chunks:
        rows.append((
            c["id"], c["type"], c["file"], c["doc"], c["section"],
            c["clause"], c["doc_date"],
            int(c.get("is_amendment", False)),
            int(c.get("lost", False)),
            c.get("amends_doc"),
            c.get("part"),
            c.get("context"),
            c["text"],
            None, None,
        ))

    cur.executemany("""
        INSERT INTO chunks
        (id, type, file, doc, section, clause, doc_date, is_amendment, lost, amends_doc, part, context, text, dense_vec, sparse_tokens)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    conn.close()
    print(f"✅ Нарезка сохранена в {DB_PATH} ({len(chunks)} чанков)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--show", type=int, default=3)
    args = ap.parse_args()

    chunks = build_chunks()
    print(f"Всего чанков: {len(chunks)}")

    if args.inspect:
        inspect(chunks, args.show)
        return

    save_to_sqlite(chunks)


if __name__ == "__main__":
    main()