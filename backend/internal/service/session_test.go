package service

import (
	"context"
	"testing"

	"github.com/google/uuid"
	"github.com/ilushew/psbAI/backend/internal/models"
)

func TestSessionService_Create(t *testing.T) {
	expectedSession := &models.Session{
		ID: uuid.New(),
	}

	sessionRepo := &fakeSessionRepository{
		session: expectedSession,
	}

	sessionService := NewSessionService(sessionRepo)

	session, err := sessionService.Create(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if session.ID != expectedSession.ID {
		t.Errorf(
			"expected session ID %s, got %s",
			expectedSession.ID,
			session.ID,
		)
	}
}

func TestSessionService_GetByID(t *testing.T) {
	expectedSession := &models.Session{
		ID: uuid.New(),
	}

	sessionRepo := &fakeSessionRepository{
		session: expectedSession,
	}

	sessionService := NewSessionService(sessionRepo)

	session, err := sessionService.GetByID(
		context.Background(),
		expectedSession.ID,
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if session.ID != expectedSession.ID {
		t.Errorf(
			"expected session ID %s, got %s",
			expectedSession.ID,
			session.ID,
		)
	}
}
