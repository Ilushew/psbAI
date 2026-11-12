"""
solution.py — главный скрипт для платформы.
Читает DATA_DIR, распаковывает ZIP, индексирует, отвечает на вопросы, сохраняет submission.csv.
"""
import csv, os, shutil, subprocess, sys, zipfile
from pathlib import Path

from rag.generate import generate


def main():
    data_dir = os.getenv("DATA_DIR", "data")
    index_dir = "index"
    db_path = os.path.join(index_dir, "kb.db")

    # 5.2: распаковка ZIP
    zip_path = os.path.join(data_dir, "knowledge-base.zip")
    if os.path.exists(zip_path):
        print(f"Распаковываю {zip_path}...", file=sys.stderr)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(data_dir)

    # 5.3: индексация (если базы ещё нет)
    if not os.path.exists(db_path):
        print("Запускаю чанкинг...", file=sys.stderr)
        subprocess.run([sys.executable, "rag/chunk.py"], check=True)
        print("Запускаю расчёт эмбеддингов...", file=sys.stderr)
        subprocess.run([sys.executable, "rag/embed.py"], check=True)

    # 5.4: чтение вопросов
    questions_path = os.path.join(data_dir, "questions.csv")
    if not os.path.exists(questions_path):
        print(f"❌ Файл вопросов не найден: {questions_path}", file=sys.stderr)
        sys.exit(1)

    questions = []
    with open(questions_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # предполагаем колонки "id" и "question" (или "text")
            q_id = row.get("id") or row.get("ID")
            q_text = row.get("question") or row.get("text") or row.get("QUESTION")
            if q_id and q_text:
                questions.append({"id": q_id, "question": q_text})

    print(f"Вопросов: {len(questions)}", file=sys.stderr)

    # 5.5/5.6: генерация и сохранение
    submission_path = "submission.csv"
    with open(submission_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "answer"])

        for i, q in enumerate(questions, 1):
            print(f"[{i}/{len(questions)}] {q['id']}: {q['question'][:60]}...", file=sys.stderr)
            try:
                answer = generate(q["question"])
                # 5.7: не допускаем пустых ответов
                if not answer.strip():
                    answer = "В предоставленной базе знаний информация отсутствует."
                writer.writerow([q["id"], answer])
            except Exception as e:
                print(f"❌ Ошибка на вопросе {q['id']}: {e}", file=sys.stderr)
                writer.writerow([q["id"], "Ошибка генерации ответа."])

    print(f"✅ Готово! Ответы сохранены в {submission_path}", file=sys.stderr)


if __name__ == "__main__":
    main()