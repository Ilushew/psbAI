package service

import (
	"context"
	"fmt"

	"github.com/ilushew/psbAI/backend/internal/client/ai"
	"github.com/ilushew/psbAI/backend/internal/models"
	"github.com/ilushew/psbAI/backend/internal/repository"
)

const (
	RoleUser      = "user"
	RoleAssistant = "assistant"
)

type MessageService struct {
	messages       repository.MessageRepository
	messageSources repository.MessageSourceRepository
	aiClient       *ai.Client
}

func NewMessageService(
	messages repository.MessageRepository,
	messageSources repository.MessageSourceRepository,
	aiClient *ai.Client,
) *MessageService {
	return &MessageService{
		messages:       messages,
		messageSources: messageSources,
		aiClient:       aiClient,
	}
}

func (s *MessageService) CreateUserMessage(
	ctx context.Context,
	chatID int64,
	content string,
) (*models.Message, error) {
	message, err := s.messages.Create(ctx, chatID, RoleUser, content)
	if err != nil {
		return nil, fmt.Errorf("create user message: %w", err)
	}

	return message, nil
}

func (s *MessageService) CreateAssistantMessage(
	ctx context.Context,
	chatID int64,
	content string,
	sources []models.MessageSource,
) (*models.Message, error) {
	message, err := s.messages.CreateAssistantWithSources(
		ctx,
		chatID,
		content,
		sources,
	)
	if err != nil {
		return nil, fmt.Errorf("create assistant message: %w", err)
	}

	return message, nil
}

func (s *MessageService) GetByChatID(
	ctx context.Context,
	chatID int64,
) ([]MessageWithSources, error) {
	messages, err := s.messages.GetByChatID(ctx, chatID)
	if err != nil {
		return nil, fmt.Errorf("get messages: %w", err)
	}

	result := make([]MessageWithSources, 0, len(messages))

	for _, message := range messages {
		sources, err := s.messageSources.GetByMessageID(ctx, message.ID)
		if err != nil {
			return nil, fmt.Errorf(
				"get sources for message %d: %w",
				message.ID,
				err,
			)
		}

		result = append(result, MessageWithSources{
			Message: message,
			Sources: sources,
		})
	}

	return result, nil
}

func (s *MessageService) SendMessage(
	ctx context.Context,
	chatID int64,
	content string,
) (*MessageWithSources, error) {
	_, err := s.CreateUserMessage(ctx, chatID, content)
	if err != nil {
		return nil, err
	}

	response, err := s.aiClient.Answer(ctx, content)
	if err != nil {
		return nil, fmt.Errorf("get AI answer: %w", err)
	}

	sources := make([]models.MessageSource, 0, len(response.Sources))

	for _, source := range response.Sources {
		sources = append(sources, models.MessageSource{
			DocumentID: source.DocumentID,
			Text:       source.Text,
		})
	}

	assistantMessage, err := s.CreateAssistantMessage(
		ctx,
		chatID,
		response.Answer,
		sources,
	)
	if err != nil {
		return nil, err
	}

	return &MessageWithSources{
		Message: *assistantMessage,
		Sources: sources,
	}, nil
}
