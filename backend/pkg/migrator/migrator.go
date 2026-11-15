package migrator

import (
	"database/sql"
	"embed"
	"fmt"
	"io/fs"

	"github.com/pressly/goose/v3"
)

type Migrator struct {
	db         *sql.DB
	migrations fs.FS
}

func New(db *sql.DB, migrations fs.FS) *Migrator {
	return &Migrator{
		db:         db,
		migrations: migrations,
	}
}

func (m *Migrator) Up() error {
	if err := m.setup(); err != nil {
		return fmt.Errorf("migrator.Up: %w", err)
	}
	if err := goose.Up(m.db, "."); err != nil {
		return fmt.Errorf("migrator: failed to up: %w", err)
	}
	return nil
}

func (m *Migrator) Down() error {
	if err := m.setup(); err != nil {
		return fmt.Errorf("migrator.Down %w", err)
	}
	if err := goose.Down(m.db, "."); err != nil {
		return fmt.Errorf("migrator: failed to down: %w", err)
	}

	return nil
}

func (m *Migrator) setup() error {
	goose.SetLogger(goose.NopLogger())
	goose.SetTableName("schema_migrations")
	if err := goose.SetDialect("postgres"); err != nil {
		return fmt.Errorf("migrator.setup: %w", err)
	}
	goose.SetBaseFS(m.migrations)
	return nil
}

func EmbedMigrations(db *sql.DB, efs embed.FS, dir string) (*Migrator, error) {
	sub, err := fs.Sub(efs, dir)
	if err != nil {
		return nil, fmt.Errorf("migrator.EmbedMigrations: %w", err)
	}

	return New(db, sub), nil
}
