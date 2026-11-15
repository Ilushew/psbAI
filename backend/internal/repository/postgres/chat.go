package postgres

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ilushew/psbAI/backend/internal/models"
	"github.com/ilushew/psbAI/backend/internal/repository"
)

type ChatRepository struct {
	pool *pgxpool.Pool
}

func NewChatRepository(pool *pgxpool.Pool) *ChatRepository {
	return &ChatRepository{
		pool: pool,
	}
}

func (r *ChatRepository) Create(
	ctx context.Context,
	sessionID uuid.UUID,
	title string,
) (*models.Chat, error) {
	const query = `
		INSERT INTO chats (session_id, title)
		VALUES ($1, COALESCE(NULLIF($2, ''), 'Новый диалог'))
		RETURNING id, session_id, title, created_at, updated_at
	`

	chat := &models.Chat{}

	err := r.pool.QueryRow(ctx, query, sessionID, title).Scan(
		&chat.ID,
		&chat.SessionID,
		&chat.Title,
		&chat.CreatedAt,
		&chat.UpdatedAt,
	)
	if err != nil {
		return nil, fmt.Errorf("create chat: %w", err)
	}

	return chat, nil
}

func (r *ChatRepository) GetBySessionID(
	ctx context.Context,
	sessionID uuid.UUID,
) ([]models.Chat, error) {
	const query = `
		SELECT id, session_id, title, created_at, updated_at
		FROM chats
		WHERE session_id = $1
		ORDER BY updated_at DESC
	`

	rows, err := r.pool.Query(ctx, query, sessionID)
	if err != nil {
		return nil, fmt.Errorf("get chats by session id: %w", err)
	}
	defer rows.Close()

	chats := make([]models.Chat, 0)

	for rows.Next() {
		var chat models.Chat

		err := rows.Scan(
			&chat.ID,
			&chat.SessionID,
			&chat.Title,
			&chat.CreatedAt,
			&chat.UpdatedAt,
		)
		if err != nil {
			return nil, fmt.Errorf("scan chat: %w", err)
		}

		chats = append(chats, chat)
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate chats: %w", err)
	}

	return chats, nil
}

func (r *ChatRepository) GetByID(
	ctx context.Context,
	id int64,
) (*models.Chat, error) {
	const query = `
		SELECT id, session_id, title, created_at, updated_at
		FROM chats
		WHERE id = $1
	`

	chat := &models.Chat{}

	err := r.pool.QueryRow(ctx, query, id).Scan(
		&chat.ID,
		&chat.SessionID,
		&chat.Title,
		&chat.CreatedAt,
		&chat.UpdatedAt,
	)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, repository.ErrNotFound
		}

		return nil, fmt.Errorf("get chat by id: %w", err)
	}

	return chat, nil
}

var _ repository.ChatRepository = (*ChatRepository)(nil)
