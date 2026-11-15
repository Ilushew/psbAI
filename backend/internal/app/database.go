package app

import (
	"context"
	"database/sql"
	"fmt"

	"github.com/ilushew/psbAI/backend/internal/migrations"
	"github.com/ilushew/psbAI/backend/pkg/config"
	"github.com/ilushew/psbAI/backend/pkg/migrator"
	"github.com/ilushew/psbAI/backend/pkg/postgres"

	"github.com/jackc/pgx/v5/pgxpool"
)

func initPostgres(ctx context.Context) (*pgxpool.Pool, error) {
	cfg := postgres.Config{
		Host:     config.Get("DB_HOST", "localhost"),
		Port:     config.Get("DB_PORT", "5432"),
		User:     config.Get("DB_USER", "postgres"),
		Password: config.Get("DB_PASSWORD", "postgres"),
		Database: config.Get("DB_NAME", "legal_assistant"),
	}

	pool, err := postgres.NewPool(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("connect to postgres: %w", err)
	}

	return pool, nil
}

func runMigrations(db *sql.DB) error {
	m, err := migrator.EmbedMigrations(db, migrations.FS, ".")
	if err != nil {
		return fmt.Errorf("embed migrations: %w", err)
	}

	if err := m.Up(); err != nil {
		return fmt.Errorf("run migrations: %w", err)
	}

	return nil
}
