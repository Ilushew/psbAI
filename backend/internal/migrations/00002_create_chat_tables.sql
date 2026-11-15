
-- +goose Up

-- Анонимные пользовательские сессии
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

-- Диалоги
CREATE TABLE chats (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL DEFAULT 'Новый диалог',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Сообщения
CREATE TABLE messages (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Источники ответов
CREATE TABLE message_sources (
    id BIGSERIAL PRIMARY KEY,
    message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL,
    text TEXT NOT NULL
);

-- Индексы для частых запросов
CREATE INDEX idx_chats_session_id ON chats(session_id);
CREATE INDEX idx_messages_chat_id ON messages(chat_id);
CREATE INDEX idx_message_sources_message_id ON message_sources(message_id);

-- Удаляем тестовую таблицу
DROP TABLE IF EXISTS schema_check;


-- +goose Down

CREATE TABLE schema_check (
    id BIGSERIAL PRIMARY KEY
);

DROP TABLE message_sources;
DROP TABLE messages;
DROP TABLE chats;
DROP TABLE sessions;
