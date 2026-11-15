package app

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/ilushew/psbAI/backend/internal/client/ai"
	postgresrepo "github.com/ilushew/psbAI/backend/internal/repository/postgres"
	"github.com/ilushew/psbAI/backend/internal/service"
	"github.com/ilushew/psbAI/backend/pkg/config"
	"github.com/ilushew/psbAI/backend/pkg/postgres"
	"github.com/jackc/pgx/v5/pgxpool"
)

type App struct {
	pool         *pgxpool.Pool
	repositories *postgresrepo.Repositories
	services     *service.Services
	router       http.Handler
	server       *http.Server
}

func New() (*App, error) {
	if err := config.LoadDotEnv("../.env"); err != nil {
		return nil, fmt.Errorf("load env: %w", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	pool, err := initPostgres(ctx)
	if err != nil {
		return nil, err
	}

	stdDB := postgres.NewStdDB(pool)

	if err := runMigrations(stdDB); err != nil {
		pool.Close()
		return nil, err
	}

	repositories := postgresrepo.NewRepositories(pool)
	aiClient := ai.NewClient(config.MustGet("AI_SERVICE_URL"))
	services := &service.Services{
		Sessions: service.NewSessionService(repositories.Sessions),
		Chats:    service.NewChatService(repositories.Sessions, repositories.Chats),
		Messages: service.NewMessageService(
			repositories.Messages,
			repositories.MessageSources,
			aiClient,
		),
	}

	router := setupRouter(services)

	port := config.Get("SERVER_PORT", "8080")

	server := &http.Server{
		Addr:         ":" + port,
		Handler:      router,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	return &App{
		pool:         pool,
		repositories: repositories,
		services:     services,
		router:       router,
		server:       server,
	}, nil
}

func (a *App) Run(ctx context.Context) error {
	errCh := make(chan error, 1)

	go func() {
		errCh <- a.server.ListenAndServe()
	}()

	select {
	case err := <-errCh:
		if !errors.Is(err, http.ErrServerClosed) {
			a.pool.Close()
			return fmt.Errorf("http server: %w", err)
		}

	case <-ctx.Done():
		shutdownCtx, cancel := context.WithTimeout(
			context.Background(),
			5*time.Second,
		)
		defer cancel()

		if err := a.server.Shutdown(shutdownCtx); err != nil {
			a.pool.Close()
			return fmt.Errorf("shutdown server: %w", err)
		}

		a.pool.Close()
	}

	return nil
}
