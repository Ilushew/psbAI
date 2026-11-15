package service

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"
	"github.com/ilushew/psbAI/backend/internal/models"
	"github.com/ilushew/psbAI/backend/internal/repository"
)

type fakeSessionRepository struct {
	session *models.Session
	err     error
}

func (f *fakeSessionRepository) Create(ctx context.Context) (*models.Session, error) {
	return f.session, f.err
}

func (f *fakeSessionRepository) GetByID(ctx context.Context, id uuid.UUID) (*models.Session, error) {
	if f.err != nil {
		return nil, f.err
	}

	if f.session == nil || f.session.ID != id {
		return nil, repository.ErrNotFound
	}

	return f.session, nil
}

type fakeChatRepository struct {
	chat *models.Chat
	err  error
}

func (f *fakeChatRepository) Create(
	ctx context.Context,
	sessionID uuid.UUID,
	title string,
) (*models.Chat, error) {
	return f.chat, f.err
}

func (f *fakeChatRepository) GetBySessionID(
	ctx context.Context,
	sessionID uuid.UUID,
) ([]models.Chat, error) {
	if f.err != nil {
		return nil, f.err
	}

	if f.chat == nil {
		return []models.Chat{}, nil
	}

	return []models.Chat{*f.chat}, nil
}

func (f *fakeChatRepository) GetByID(
	ctx context.Context,
	id int64,
) (*models.Chat, error) {
	return f.chat, f.err
}

func TestChatService_Create(t *testing.T) {
	sessionID := uuid.New()

	sessionRepo := &fakeSessionRepository{
		session: &models.Session{
			ID: sessionID,
		},
	}

	expectedChat := &models.Chat{
		ID:        1,
		SessionID: sessionID,
		Title:     "Тестовый чат",
	}

	chatRepo := &fakeChatRepository{
		chat: expectedChat,
	}

	chatService := NewChatService(sessionRepo, chatRepo)

	chat, err := chatService.Create(
		context.Background(),
		sessionID,
		"Тестовый чат",
	)

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if chat.ID != expectedChat.ID {
		t.Errorf("expected chat ID %d, got %d", expectedChat.ID, chat.ID)
	}

	if chat.Title != expectedChat.Title {
		t.Errorf("expected title %q, got %q", expectedChat.Title, chat.Title)
	}
}

func TestChatService_Create_SessionNotFound(t *testing.T) {
	sessionRepo := &fakeSessionRepository{
		err: repository.ErrNotFound,
	}

	chatRepo := &fakeChatRepository{}

	chatService := NewChatService(sessionRepo, chatRepo)

	_, err := chatService.Create(
		context.Background(),
		uuid.New(),
		"Тестовый чат",
	)

	if !errors.Is(err, repository.ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}
