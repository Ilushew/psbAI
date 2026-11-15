package postgres

import (
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ilushew/psbAI/backend/internal/repository"
)

type Repositories struct {
	Sessions       repository.SessionRepository
	Chats          repository.ChatRepository
	Messages       repository.MessageRepository
	MessageSources repository.MessageSourceRepository
}

func NewRepositories(pool *pgxpool.Pool) *Repositories {
	return &Repositories{
		Sessions:       NewSessionRepository(pool),
		Chats:          NewChatRepository(pool),
		Messages:       NewMessageRepository(pool),
		MessageSources: NewMessageSourceRepository(pool),
	}
}
