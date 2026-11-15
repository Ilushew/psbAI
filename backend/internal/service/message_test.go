package service

import (
	"context"
	"testing"

	"github.com/ilushew/psbAI/backend/internal/models"
)

type fakeMessageRepository struct {
	messages         []models.Message
	assistantSources []models.MessageSource
	err              error
}

func (f *fakeMessageRepository) Create(
	ctx context.Context,
	chatID int64,
	role, content string,
) (*models.Message, error) {
	if f.err != nil {
		return nil, f.err
	}

	message := models.Message{
		ID:      int64(len(f.messages) + 1),
		ChatID:  chatID,
		Role:    role,
		Content: content,
	}

	f.messages = append(f.messages, message)
	return &message, nil
}

func (f *fakeMessageRepository) CreateAssistantWithSources(
	ctx context.Context,
	chatID int64,
	content string,
	sources []models.MessageSource,
) (*models.Message, error) {
	if f.err != nil {
		return nil, f.err
	}

	message, err := f.Create(ctx, chatID, RoleAssistant, content)
	if err != nil {
		return nil, err
	}

	for _, source := range sources {
		source.MessageID = message.ID
		f.assistantSources = append(f.assistantSources, source)
	}

	return message, nil
}

func (f *fakeMessageRepository) GetByChatID(
	ctx context.Context,
	chatID int64,
) ([]models.Message, error) {
	if f.err != nil {
		return nil, f.err
	}

	return f.messages, nil
}

type fakeMessageSourceRepository struct {
	sources []models.MessageSource
	err     error
}

func (f *fakeMessageSourceRepository) CreateMany(
	ctx context.Context,
	messageID int64,
	sources []models.MessageSource,
) error {
	if f.err != nil {
		return f.err
	}

	for _, source := range sources {
		source.MessageID = messageID
		f.sources = append(f.sources, source)
	}

	return nil
}

func (f *fakeMessageSourceRepository) GetByMessageID(
	ctx context.Context,
	messageID int64,
) ([]models.MessageSource, error) {
	if f.err != nil {
		return nil, f.err
	}

	var result []models.MessageSource

	for _, source := range f.sources {
		if source.MessageID == messageID {
			result = append(result, source)
		}
	}

	return result, nil
}
func TestMessageService_CreateUserMessage(t *testing.T) {
	messageRepo := &fakeMessageRepository{}
	sourceRepo := &fakeMessageSourceRepository{}

	messageService := NewMessageService(messageRepo, sourceRepo, nil)

	message, err := messageService.CreateUserMessage(
		context.Background(),
		1,
		"Какой срок рассмотрения претензии?",
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if message.Role != RoleUser {
		t.Errorf("expected role %q, got %q", RoleUser, message.Role)
	}

	if message.Content != "Какой срок рассмотрения претензии?" {
		t.Errorf("unexpected content: %q", message.Content)
	}
}
func TestMessageService_CreateAssistantMessage(t *testing.T) {
	messageRepo := &fakeMessageRepository{}
	sourceRepo := &fakeMessageSourceRepository{}

	messageService := NewMessageService(messageRepo, sourceRepo, nil)

	sources := []models.MessageSource{
		{
			DocumentID: "contract_123.txt",
			Text:       "Срок рассмотрения претензии составляет 10 рабочих дней.",
		},
	}

	message, err := messageService.CreateAssistantMessage(
		context.Background(),
		1,
		"Претензия рассматривается в течение 10 рабочих дней.",
		sources,
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if message.Role != RoleAssistant {
		t.Errorf("expected role %q, got %q", RoleAssistant, message.Role)
	}

	if len(messageRepo.assistantSources) != 1 {
		t.Fatalf(
			"expected 1 source, got %d",
			len(messageRepo.assistantSources),
		)
	}

	if messageRepo.assistantSources[0].DocumentID != "contract_123.txt" {
		t.Errorf(
			"unexpected document ID: %q",
			messageRepo.assistantSources[0].DocumentID,
		)
	}
}

func TestMessageService_GetByChatID(t *testing.T) {
	messageRepo := &fakeMessageRepository{
		messages: []models.Message{
			{
				ID:      1,
				ChatID:  1,
				Role:    RoleAssistant,
				Content: "Ответ ассистента",
			},
		},
	}

	sourceRepo := &fakeMessageSourceRepository{
		sources: []models.MessageSource{
			{
				ID:         1,
				MessageID:  1,
				DocumentID: "contract_123.txt",
				Text:       "Фрагмент документа",
			},
		},
	}

	messageService := NewMessageService(messageRepo, sourceRepo, nil)

	history, err := messageService.GetByChatID(
		context.Background(),
		1,
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(history) != 1 {
		t.Fatalf("expected 1 message, got %d", len(history))
	}

	if len(history[0].Sources) != 1 {
		t.Fatalf("expected 1 source, got %d", len(history[0].Sources))
	}
}
