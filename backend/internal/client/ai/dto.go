package ai

type AnswerRequest struct {
	Question string `json:"question"`
}

type AnswerResponse struct {
	Status  string   `json:"status"`
	Answer  string   `json:"answer"`
	Sources []Source `json:"sources"`
}

type Source struct {
	DocumentID string `json:"document_id"`
	Text       string `json:"text"`
}

const (
	StatusSuccess               = "success"
	StatusInsufficientContext   = "insufficient_context"
	StatusClarificationRequired = "clarification_required"
	StatusRefused               = "refused"
)
