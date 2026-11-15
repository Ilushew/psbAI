package handlers

import (
	"errors"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/ilushew/psbAI/backend/internal/repository"
	"github.com/ilushew/psbAI/backend/internal/service"
)

type MessageHandler struct {
	chats    *service.ChatService
	messages *service.MessageService
}

func NewMessageHandler(
	chats *service.ChatService,
	messages *service.MessageService,
) *MessageHandler {
	return &MessageHandler{
		chats:    chats,
		messages: messages,
	}
}

func (h *MessageHandler) GetByChatID(c *gin.Context) {
	chatID, err := strconv.ParseInt(c.Param("chat_id"), 10, 64)
	if err != nil || chatID <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid chat_id"})
		return
	}

	_, err = h.chats.GetByID(c.Request.Context(), chatID)
	if err != nil {
		if errors.Is(err, repository.ErrNotFound) {
			c.JSON(http.StatusNotFound, gin.H{"error": "chat not found"})
			return
		}

		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to get chat"})
		return
	}

	messages, err := h.messages.GetByChatID(c.Request.Context(), chatID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to get messages"})
		return
	}

	c.JSON(http.StatusOK, messages)
}

type sendMessageRequest struct {
	Content string `json:"content" binding:"required"`
}

func (h *MessageHandler) Send(c *gin.Context) {
	chatID, err := strconv.ParseInt(c.Param("chat_id"), 10, 64)
	if err != nil || chatID <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid chat_id"})
		return
	}

	var req sendMessageRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}

	_, err = h.chats.GetByID(c.Request.Context(), chatID)
	if err != nil {
		if errors.Is(err, repository.ErrNotFound) {
			c.JSON(http.StatusNotFound, gin.H{"error": "chat not found"})
			return
		}

		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to get chat"})
		return
	}

	result, err := h.messages.SendMessage(
		c.Request.Context(),
		chatID,
		req.Content,
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to send message"})
		return
	}

	c.JSON(http.StatusOK, result)
}
