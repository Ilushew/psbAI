package handlers

import (
	"errors"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/ilushew/psbAI/backend/internal/repository"
	"github.com/ilushew/psbAI/backend/internal/service"
)

type ChatHandler struct {
	chats *service.ChatService
}

func NewChatHandler(chats *service.ChatService) *ChatHandler {
	return &ChatHandler{
		chats: chats,
	}
}

type createChatRequest struct {
	SessionID string `json:"session_id" binding:"required"`
	Title     string `json:"title" binding:"max=255"`
}

func (h *ChatHandler) Create(c *gin.Context) {
	var req createChatRequest

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": "invalid request body",
		})
		return
	}

	sessionID, err := uuid.Parse(req.SessionID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": "invalid session_id",
		})
		return
	}

	chat, err := h.chats.Create(
		c.Request.Context(),
		sessionID,
		req.Title,
	)
	if err != nil {
		if errors.Is(err, repository.ErrNotFound) {
			c.JSON(http.StatusNotFound, gin.H{
				"error": "session not found",
			})
			return
		}

		c.JSON(http.StatusInternalServerError, gin.H{
			"error": "failed to create chat",
		})
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"id":         chat.ID,
		"session_id": chat.SessionID,
		"title":      chat.Title,
		"created_at": chat.CreatedAt,
		"updated_at": chat.UpdatedAt,
	})
}

func (h *ChatHandler) GetBySessionID(c *gin.Context) {
	sessionID, err := uuid.Parse(c.Param("session_id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid session_id"})
		return
	}

	chats, err := h.chats.GetBySessionID(c.Request.Context(), sessionID)
	if err != nil {
		if errors.Is(err, repository.ErrNotFound) {
			c.JSON(http.StatusNotFound, gin.H{"error": "session not found"})
			return
		}

		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to get chats"})
		return
	}

	c.JSON(http.StatusOK, chats)
}
