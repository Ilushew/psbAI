"""
api.py — HTTP-сервер (FastAPI) для интеграции RAG с Go-бэкендом.
"""
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional

# Импортируем твои существующие функции
from search_table import search
from generate import _pick_model, _build_user_prompt, _llm, RERANK_MIN

app = FastAPI(title="PSB AI RAG Service")

# --- DTO (соответствует ожидаемому в client.go) ---
class Source(BaseModel):
    document_id: str
    text: str

class AnswerRequest(BaseModel):
    question: str

class AnswerResponse(BaseModel):
    status: str  # "success", "insufficient_context", "clarification_required", "refused"
    answer: str
    sources: List[Source]

# --- Константы статусов (как в Go) ---
STATUS_SUCCESS = "success"
STATUS_INSUFFICIENT_CONTEXT = "insufficient_context"
STATUS_CLARIFICATION_REQUIRED = "clarification_required"
STATUS_REFUSED = "refused"

@app.post("/api/v1/answer", response_model=AnswerResponse)
async def get_answer(request: AnswerRequest):
    query = request.question.strip()
    if not query:
        return AnswerResponse(
            status=STATUS_CLARIFICATION_REQUIRED,
            answer="Пожалуйста, сформулируйте вопрос.",
            sources=[]
        )

    top_k = int(os.getenv("TOP_K", 8))
    
    # 1. Поиск чанков
    chunks = search(query, k=top_k, rerank=True)
    
    # 2. Проверка релевантности (как в generate.py)
    if not chunks:
        return AnswerResponse(
            status=STATUS_INSUFFICIENT_CONTEXT,
            answer="В предоставленной базе знаний информация отсутствует.",
            sources=[]
        )
    
    top_chunk = chunks[0]
    if "rerank_score" in top_chunk:
        if top_chunk["rerank_score"] < RERANK_MIN:
            return AnswerResponse(
                status=STATUS_INSUFFICIENT_CONTEXT,
                answer="В предоставленной базе знаний информация отсутствует.",
                sources=[]
            )
    elif top_chunk.get("score", 0) < 0.01:
        return AnswerResponse(
            status=STATUS_INSUFFICIENT_CONTEXT,
            answer="В предоставленной базе знаний информация отсутствует.",
            sources=[]
        )

    # 3. Формируем источники для ответа
    sources = []
    for c in chunks:
        # document_id может быть ID чанка или читаемым именем документа
        doc_id = str(c.get("id", "unknown"))
        doc_name = c.get("doc", "Неизвестный документ")
        section = c.get("section", "")
        header = f"{doc_name}" + (f" | {section}" if section else "")
        
        sources.append(Source(
            document_id=doc_id,
            text=f"[{header}]\n{c['text']}"
        ))

    # 4. Генерация ответа через LLM
    messages = [
        {"role": "system", "content": """Ты — юридический ассистент компании ООО «ПСБ».
Отвечай строго на основе документов из блока «КОНТЕКСТ».
Если в контексте нет ответа — так и скажи: «В предоставленной базе знаний информация отсутствует».
Не выдумывай факты и не используй внешние знания. Ссылайся на конкретные статьи/пункты.
Отвечай кратко, по делу, на русском языке."""},
        {"role": "user", "content": _build_user_prompt(query, chunks)},
    ]
    
    llm = _llm()
    model = _pick_model()
    
    try:
        resp = llm.chat.completions.create(
            model=model,
            messages=messages,
            temperature=float(os.getenv("TEMPERATURE", 0.2)),
            max_tokens=int(os.getenv("MAX_TOKENS", 1024)),
        )
        answer_text = resp.choices[0].message.content.strip()
        
        # Дополнительная проверка на отказ LLM
        if "информация отсутствует" in answer_text.lower():
            return AnswerResponse(
                status=STATUS_INSUFFICIENT_CONTEXT,
                answer=answer_text,
                sources=[]
            )
            
        return AnswerResponse(
            status=STATUS_SUCCESS,
            answer=answer_text,
            sources=sources
        )
        
    except Exception as e:
        print(f"[API ERROR] LLM generation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal LLM error")

if __name__ == "__main__":
    import uvicorn
    # Прогреваем индекс при запуске
    from search_table import get_index
    get_index()
    
    uvicorn.run(app, host="0.0.0.0", port=8000)