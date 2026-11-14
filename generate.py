"""
generate.py — генерация ответа с проверкой контекста и retry.
"""
import argparse, os, sys, time
from openai import OpenAI

from psbAI.search_table import search


SYSTEM_PROMPT = """Ты — юридический ассистент компании ООО «ПСБ».
Отвечай строго на основе документов из блока «КОНТЕКСТ».

ПРАВИЛА:
1. Если в контексте нет ответа — так и скажи: «В предоставленной базе знаний информация отсутствует».
2. Не выдумывай факты и не используй внешние знания.
3. Ссылайся на конкретные статьи/пункты/номера договоров (например: «согласно п. 2.3 Регламента № 14-П»).
4. Если документ помечен [УТРАТИЛ СИЛУ] — упомяни это, если он используется в ответе.
5. Если документ помечен [ИЗМЕНЕНИЕ/ДОП. СОГЛАШЕНИЕ] — укажи, к какому основному договору он относится.
6. Отвечай кратко, по делу, на русском языке.
7. Не цитируй дословно длинные фрагменты — пересказывай своими словами."""


def _pick_model() -> str:
    return os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or os.getenv("GEN_MODEL") or "gpt-4o-mini"


def _build_user_prompt(query: str, chunks: list[dict]) -> str:
    if not chunks:
        return f"Вопрос: {query}\n\n(Контекст пуст — в базе ничего не найдено.)"

    parts = []
    for i, c in enumerate(chunks, 1):
        tags = []
        if c.get("lost"):
            tags.append("УТРАТИЛ СИЛУ")
        if c.get("is_amendment"):
            tags.append("ИЗМЕНЕНИЕ/ДОП. СОГЛАШЕНИЕ")
            if c.get("amends_doc"):
                tags.append(f"к договору №{c['amends_doc']}")
        tag_str = f"  [{', '.join(tags)}]" if tags else ""

        header = f"{c['doc']}"
        if c.get("section"):
            header += f" | {c['section']}"
        if c.get("clause"):
            header += f" | п.{c['clause']}"
        if c.get("doc_date"):
            header += f" | дата: {c['doc_date']}"

        parts.append(f"--- Документ {i}{tag_str} ---\n{header}\n{c['text']}")

    context = "\n\n".join(parts)
    return f"КОНТЕКСТ:\n{context}\n\n---\n\nВОПРОС ПОЛЬЗОВАТЕЛЯ: {query}"


def generate(query: str, rerank: bool = True) -> str:
    """4.7: retry при ошибках API."""
    top_k = int(os.getenv("TOP_K", 8))
    temperature = float(os.getenv("TEMPERATURE", 0.2))
    max_tokens = int(os.getenv("MAX_TOKENS", 1024))
    model = _pick_model()

    # 1. Поиск
    chunks = search(query, k=top_k, rerank=rerank)

    # 4.1: пустой контекст
    if not chunks:
        return "В предоставленной базе знаний информация отсутствует."

    # 4.2: проверка релевантности (если топ-1 имеет слишком низкий скор — контекст нерелевантен)
    if chunks[0]["score"] < 0.01:
        return "В предоставленной базе знаний информация отсутствует."

    # 2. Промпт
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(query, chunks)},
    ]

    # 3. Запрос к LLM с retry
    llm = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])
    for attempt in range(3):
        try:
            resp = llm.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content
        except Exception as e:
            wait = 2 ** attempt
            print(f"[LLM retry {attempt + 1}] {e!r}; жду {wait}s", file=sys.stderr)
            time.sleep(wait)

    return "Ошибка генерации ответа."


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--no-rerank", action="store_true")
    ap.add_argument("--show-context", action="store_true")
    a = ap.parse_args()

    if a.show_context:
        from psbAI.search_table import search as _search
        top_k = int(os.getenv("TOP_K", 8))
        ctx = _search(a.query, k=top_k, rerank=not a.no_rerank)
        print(f"=== Контекст ({len(ctx)} чанков) ===")
        for i, c in enumerate(ctx, 1):
            print(f"\n[{i}] {c['doc']} | {c['section']} | score={c['score']:.4f}")
            print("   ", c["text"][:250].replace("\n", " ⏎ "))
        print("\n=== Ответ LLM ===\n")

    answer = generate(a.query, rerank=not a.no_rerank)
    print(answer)