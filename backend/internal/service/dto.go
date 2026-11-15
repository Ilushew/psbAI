package service

import "github.com/ilushew/psbAI/backend/internal/models"

type MessageWithSources struct {
	Message models.Message         `json:"message"`
	Sources []models.MessageSource `json:"sources"`
}
