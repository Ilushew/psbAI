package models

import "time"

type Message struct {
	ID        int64     `json:"id"`
	ChatID    int64     `json:"chat_id"`
	Role      string    `json:"role"`
	Content   string    `json:"content"`
	CreatedAt time.Time `json:"created_at"`
}

type MessageSource struct {
	ID         int64  `json:"id"`
	MessageID  int64  `json:"message_id"`
	DocumentID string `json:"document_id"`
	Text       string `json:"text"`
}
