package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/ilushew/psbAI/backend/internal/service"
)

type SessionHandler struct {
	sessions *service.SessionService
}

func NewSessionHandler(sessions *service.SessionService) *SessionHandler {
	return &SessionHandler{
		sessions: sessions,
	}
}

func (h *SessionHandler) Create(c *gin.Context) {
	session, err := h.sessions.Create(c.Request.Context())
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": "failed to create session",
		})
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"id":         session.ID,
		"created_at": session.CreatedAt,
	})
}
