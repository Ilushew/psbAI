package repository

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/ilushew/psbAI/backend/internal/models"
)

var ErrNotFound = errors.New("entity not found")

type SessionRepository interface {
	Create(ctx context.Context) (*models.Session, error)
	GetByID(ctx context.Context, id uuid.UUID) (*models.Session, error)
}

type ChatRepository interface {
	Create(ctx context.Context, sessionID uuid.UUID, title string) (*models.Chat, error)
	GetBySessionID(ctx context.Context, sessionID uuid.UUID) ([]models.Chat, error)
	GetByID(ctx context.Context, id int64) (*models.Chat, error)
}

type MessageRepository interface {
	Create(ctx context.Context, chatID int64, role, content string) (*models.Message, error)
	CreateAssistantWithSources(
		ctx context.Context,
		chatID int64,
		content string,
		sources []models.MessageSource,
	) (*models.Message, error)
	GetByChatID(ctx context.Context, chatID int64) ([]models.Message, error)
}

type MessageSourceRepository interface {
	CreateMany(ctx context.Context, messageID int64, sources []models.MessageSource) error
	GetByMessageID(ctx context.Context, messageID int64) ([]models.MessageSource, error)
}
