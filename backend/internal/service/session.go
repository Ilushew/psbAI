package service

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/ilushew/psbAI/backend/internal/models"
	"github.com/ilushew/psbAI/backend/internal/repository"
)

type SessionService struct {
	sessions repository.SessionRepository
}

func NewSessionService(
	sessions repository.SessionRepository,
) *SessionService {
	return &SessionService{
		sessions: sessions,
	}
}

func (s *SessionService) Create(
	ctx context.Context,
) (*models.Session, error) {
	session, err := s.sessions.Create(ctx)
	if err != nil {
		return nil, fmt.Errorf("create session: %w", err)
	}

	return session, nil
}

func (s *SessionService) GetByID(
	ctx context.Context,
	id uuid.UUID,
) (*models.Session, error) {
	session, err := s.sessions.GetByID(ctx, id)
	if err != nil {
		return nil, fmt.Errorf("get session: %w", err)
	}

	return session, nil
}
