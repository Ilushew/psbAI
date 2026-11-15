package postgres

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ilushew/psbAI/backend/internal/models"
	"github.com/ilushew/psbAI/backend/internal/repository"
)

type MessageSourceRepository struct {
	pool *pgxpool.Pool
}

func NewMessageSourceRepository(pool *pgxpool.Pool) *MessageSourceRepository {
	return &MessageSourceRepository{
		pool: pool,
	}
}

func (r *MessageSourceRepository) CreateMany(
	ctx context.Context,
	messageID int64,
	sources []models.MessageSource,
) error {
	if len(sources) == 0 {
		return nil
	}

	batch := &pgx.Batch{}

	for _, source := range sources {
		batch.Queue(
			`INSERT INTO message_sources (message_id, document_id, text)
			 VALUES ($1, $2, $3)`,
			messageID,
			source.DocumentID,
			source.Text,
		)
	}

	results := r.pool.SendBatch(ctx, batch)
	defer results.Close()

	for range sources {
		if _, err := results.Exec(); err != nil {
			return fmt.Errorf("create message source: %w", err)
		}
	}

	return nil
}

func (r *MessageSourceRepository) GetByMessageID(
	ctx context.Context,
	messageID int64,
) ([]models.MessageSource, error) {
	const query = `
		SELECT id, message_id, document_id, text
		FROM message_sources
		WHERE message_id = $1
		ORDER BY id ASC
	`

	rows, err := r.pool.Query(ctx, query, messageID)
	if err != nil {
		return nil, fmt.Errorf("get message sources: %w", err)
	}
	defer rows.Close()

	sources := make([]models.MessageSource, 0)

	for rows.Next() {
		var source models.MessageSource

		if err := rows.Scan(
			&source.ID,
			&source.MessageID,
			&source.DocumentID,
			&source.Text,
		); err != nil {
			return nil, fmt.Errorf("scan message source: %w", err)
		}

		sources = append(sources, source)
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate message sources: %w", err)
	}

	return sources, nil
}

var _ repository.MessageSourceRepository = (*MessageSourceRepository)(nil)
