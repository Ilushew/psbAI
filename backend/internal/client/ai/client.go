package ai

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

var (
	ErrUnavailable      = errors.New("AI service unavailable")
	ErrHTTPStatus       = errors.New("AI service returned unsuccessful HTTP status")
	ErrInvalidResponse  = errors.New("invalid AI response")
	ErrResponseTooLarge = errors.New("AI response is too large")
	ErrUnexpectedStatus = errors.New("unexpected AI response status")
)

const maxResponseSize = 10 << 20 // 10 MB

type Client struct {
	baseURL    string
	httpClient *http.Client
}

func NewClient(baseURL string) *Client {
	return &Client{
		baseURL: strings.TrimRight(baseURL, "/"),
		httpClient: &http.Client{
			Timeout: 60 * time.Second,
		},
	}
}

func (c *Client) Answer(
	ctx context.Context,
	question string,
) (*AnswerResponse, error) {
	body, err := json.Marshal(AnswerRequest{
		Question: question,
	})
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		c.baseURL+"/api/v1/answer",
		bytes.NewReader(body),
	)
	if err != nil {
		return nil, fmt.Errorf("create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("%w: %w", ErrUnavailable, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf(
			"%w: status %d",
			ErrHTTPStatus,
			resp.StatusCode,
		)
	}

	responseBody, err := io.ReadAll(
		io.LimitReader(resp.Body, maxResponseSize+1),
	)
	if err != nil {
		return nil, fmt.Errorf("%w: read body: %w", ErrInvalidResponse, err)
	}

	if len(responseBody) > maxResponseSize {
		return nil, ErrResponseTooLarge
	}

	var result AnswerResponse

	if err := json.Unmarshal(responseBody, &result); err != nil {
		return nil, fmt.Errorf("%w: decode JSON: %w", ErrInvalidResponse, err)
	}

	if err := validateResponse(&result); err != nil {
		return nil, err
	}

	return &result, nil
}

func validateResponse(response *AnswerResponse) error {
	switch response.Status {
	case StatusSuccess,
		StatusInsufficientContext,
		StatusClarificationRequired,
		StatusRefused:
	default:
		return fmt.Errorf(
			"%w: %q",
			ErrUnexpectedStatus,
			response.Status,
		)
	}

	if response.Status == StatusSuccess && strings.TrimSpace(response.Answer) == "" {
		return fmt.Errorf("%w: empty answer", ErrInvalidResponse)
	}

	for i, source := range response.Sources {
		if strings.TrimSpace(source.DocumentID) == "" {
			return fmt.Errorf(
				"%w: source %d has empty document_id",
				ErrInvalidResponse,
				i,
			)
		}

		if strings.TrimSpace(source.Text) == "" {
			return fmt.Errorf(
				"%w: source %d has empty text",
				ErrInvalidResponse,
				i,
			)
		}
	}

	return nil
}
