package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

type IndexHandler struct{}

func NewIndexHandler() *IndexHandler {
	return &IndexHandler{}
}

func (h *IndexHandler) ShowIndexPage(c *gin.Context) {
	c.HTML(http.StatusOK, "index", gin.H{
		"Title": "Юридический ассистент",
	})
}
