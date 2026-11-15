package models

import (
	"time"

	"github.com/google/uuid"
)

type Chat struct {
	ID        int64     `json:"id"`
	SessionID uuid.UUID `json:"session_id"`
	Title     string    `json:"title"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}
