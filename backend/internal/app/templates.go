package app

import (
	"github.com/gin-contrib/multitemplate"
	"github.com/gin-gonic/gin"
)

func setupStaticAndTemplates(r *gin.Engine) {
	r.HTMLRender = createRender()
	r.Static("/static", "./static")
}

func createRender() multitemplate.Renderer {
	renderer := multitemplate.NewRenderer()

	renderer.AddFromFiles(
		"index",
		"templates/base.html",
		"templates/index.html",
	)

	return renderer
}
