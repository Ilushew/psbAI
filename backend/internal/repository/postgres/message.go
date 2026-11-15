package postgres

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ilushew/psbAI/backend/internal/models"
	"github.com/ilushew/psbAI/backend/internal/repository"
)

type MessageRepository struct {
	pool *pgxpool.Pool
}

func NewMessageRepository(pool *pgxpool.Pool) *MessageRepository {
	return &MessageRepository{
		pool: pool,
	}
}

func (r *MessageRepository) Create(
	ctx context.Context,
	chatID int64,
	role string,
	content string,
) (*models.Message, error) {
	const query = `
		INSERT INTO messages (chat_id, role, content)
		VALUES ($1, $2, $3)
		RETURNING id, chat_id, role, content, created_at
	`

	message := &models.Message{}

	err := r.pool.QueryRow(ctx, query, chatID, role, content).Scan(
		&message.ID,
		&message.ChatID,
		&message.Role,
		&message.Content,
		&message.CreatedAt,
	)
	if err != nil {
		return nil, fmt.Errorf("create message: %w", err)
	}

	return message, nil
}

func (r *MessageRepository) GetByChatID(
	ctx context.Context,
	chatID int64,
) ([]models.Message, error) {
	const query = `
		SELECT id, chat_id, role, content, created_at
		FROM messages
		WHERE chat_id = $1
		ORDER BY created_at ASC, id ASC
	`

	rows, err := r.pool.Query(ctx, query, chatID)
	if err != nil {
		return nil, fmt.Errorf("get messages by chat id: %w", err)
	}
	defer rows.Close()

	messages := make([]models.Message, 0)

	for rows.Next() {
		var message models.Message

		if err := rows.Scan(
			&message.ID,
			&message.ChatID,
			&message.Role,
			&message.Content,
			&message.CreatedAt,
		); err != nil {
			return nil, fmt.Errorf("scan message: %w", err)
		}

		messages = append(messages, message)
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate messages: %w", err)
	}

	return messages, nil
}

var _ repository.MessageRepository = (*MessageRepository)(nil)

func (r *MessageRepository) CreateAssistantWithSources(
	ctx context.Context,
	chatID int64,
	content string,
	sources []models.MessageSource,
) (*models.Message, error) {
	tx, err := r.pool.Begin(ctx)
	if err != nil {
		return nil, fmt.Errorf("begin transaction: %w", err)
	}
	defer tx.Rollback(ctx)

	const messageQuery = `
		INSERT INTO messages (chat_id, role, content)
		VALUES ($1, 'assistant', $2)
		RETURNING id, chat_id, role, content, created_at
	`

	message := &models.Message{}

	err = tx.QueryRow(ctx, messageQuery, chatID, content).Scan(
		&message.ID,
		&message.ChatID,
		&message.Role,
		&message.Content,
		&message.CreatedAt,
	)
	if err != nil {
		return nil, fmt.Errorf("create assistant message: %w", err)
	}

	const sourceQuery = `
		INSERT INTO message_sources (message_id, document_id, text)
		VALUES ($1, $2, $3)
	`

	for _, source := range sources {
		_, err := tx.Exec(
			ctx,
			sourceQuery,
			message.ID,
			source.DocumentID,
			source.Text,
		)
		if err != nil {
			return nil, fmt.Errorf("create message source: %w", err)
		}
	}

	if err := tx.Commit(ctx); err != nil {
		return nil, fmt.Errorf("commit transaction: %w", err)
	}

	return message, nil
}
