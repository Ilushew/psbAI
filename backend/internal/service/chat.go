package service

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/ilushew/psbAI/backend/internal/models"
	"github.com/ilushew/psbAI/backend/internal/repository"
)

type ChatService struct {
	sessions repository.SessionRepository
	chats    repository.ChatRepository
}

func NewChatService(
	sessions repository.SessionRepository,
	chats repository.ChatRepository,
) *ChatService {
	return &ChatService{
		sessions: sessions,
		chats:    chats,
	}
}

func (s *ChatService) Create(
	ctx context.Context,
	sessionID uuid.UUID,
	title string,
) (*models.Chat, error) {
	_, err := s.sessions.GetByID(ctx, sessionID)
	if err != nil {
		return nil, fmt.Errorf("get session: %w", err)
	}

	chat, err := s.chats.Create(ctx, sessionID, title)
	if err != nil {
		return nil, fmt.Errorf("create chat: %w", err)
	}

	return chat, nil
}

func (s *ChatService) GetBySessionID(
	ctx context.Context,
	sessionID uuid.UUID,
) ([]models.Chat, error) {
	_, err := s.sessions.GetByID(ctx, sessionID)
	if err != nil {
		return nil, fmt.Errorf("get session: %w", err)
	}

	chats, err := s.chats.GetBySessionID(ctx, sessionID)
	if err != nil {
		return nil, fmt.Errorf("get chats: %w", err)
	}

	return chats, nil
}

func (s *ChatService) GetByID(
	ctx context.Context,
	chatID int64,
) (*models.Chat, error) {
	chat, err := s.chats.GetByID(ctx, chatID)
	if err != nil {
		return nil, fmt.Errorf("get chat: %w", err)
	}

	return chat, nil
}
