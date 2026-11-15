package app

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/ilushew/psbAI/backend/internal/handlers"
	"github.com/ilushew/psbAI/backend/internal/service"
)

func setupRouter(services *service.Services) *gin.Engine {
	r := gin.Default()

	setupStaticAndTemplates(r)

	chatHandler := handlers.NewChatHandler(services.Chats)
	indexHandler := handlers.NewIndexHandler()
	sessionHandler := handlers.NewSessionHandler(services.Sessions)

	r.GET("/", indexHandler.ShowIndexPage)
	r.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	})
	messageHandler := handlers.NewMessageHandler(
		services.Chats,
		services.Messages,
	)
	api := r.Group("/api/v1")
	{
		api.POST("/chats/:chat_id/messages", messageHandler.Send)
		api.GET("/chats/:chat_id/messages", messageHandler.GetByChatID)
		api.POST("/sessions", sessionHandler.Create)
		api.POST("/chats", chatHandler.Create)
		api.GET("/sessions/:session_id/chats", chatHandler.GetBySessionID)
	}

	return r
}
