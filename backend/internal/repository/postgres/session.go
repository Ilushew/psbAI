package postgres

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ilushew/psbAI/backend/internal/models"
	"github.com/ilushew/psbAI/backend/internal/repository"
)

type SessionRepository struct {
	pool *pgxpool.Pool
}

func NewSessionRepository(pool *pgxpool.Pool) *SessionRepository {
	return &SessionRepository{
		pool: pool,
	}
}

func (r *SessionRepository) Create(ctx context.Context) (*models.Session, error) {
	const query = `
		INSERT INTO sessions DEFAULT VALUES
		RETURNING id, created_at, expires_at
	`

	session := &models.Session{}

	var expiresAt pgtype.Timestamptz

	err := r.pool.QueryRow(ctx, query).Scan(
		&session.ID,
		&session.CreatedAt,
		&expiresAt,
	)
	if err != nil {
		return nil, fmt.Errorf("create session: %w", err)
	}

	if expiresAt.Valid {
		session.ExpiresAt = &expiresAt.Time
	}

	return session, nil
}

func (r *SessionRepository) GetByID(
	ctx context.Context,
	id uuid.UUID,
) (*models.Session, error) {
	const query = `
		SELECT id, created_at, expires_at
		FROM sessions
		WHERE id = $1
	`

	session := &models.Session{}

	var expiresAt pgtype.Timestamptz

	err := r.pool.QueryRow(ctx, query, id).Scan(
		&session.ID,
		&session.CreatedAt,
		&expiresAt,
	)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, repository.ErrNotFound
		}

		return nil, fmt.Errorf("get session by id: %w", err)
	}

	if expiresAt.Valid {
		session.ExpiresAt = &expiresAt.Time
	}

	return session, nil
}
