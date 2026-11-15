package ai

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestClient_Answer(t *testing.T) {
	tests := []struct {
		name            string
		statusCode      int
		responseBody    string
		wantErr         bool
		wantAnswer      string
		wantSourceCount int
	}{
		{
			name:       "success",
			statusCode: http.StatusOK,
			responseBody: `{
				"status": "success",
				"answer": "Претензия рассматривается в течение 10 рабочих дней.",
				"sources": [
					{
						"document_id": "contract_123.txt",
						"text": "Исполнитель рассматривает поступившую претензию..."
					}
				]
			}`,
			wantAnswer:      "Претензия рассматривается в течение 10 рабочих дней.",
			wantSourceCount: 1,
		},
		{
			name:         "service error",
			statusCode:   http.StatusInternalServerError,
			responseBody: `{"error":"internal error"}`,
			wantErr:      true,
		},
		{
			name:         "invalid JSON",
			statusCode:   http.StatusOK,
			responseBody: `invalid json`,
			wantErr:      true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(
				func(w http.ResponseWriter, r *http.Request) {
					if r.Method != http.MethodPost {
						t.Errorf("unexpected method: got %s, want POST", r.Method)
					}

					if r.URL.Path != "/api/v1/answer" {
						t.Errorf("unexpected path: got %s", r.URL.Path)
					}

					if r.Header.Get("Content-Type") != "application/json" {
						t.Errorf("unexpected Content-Type")
					}

					w.WriteHeader(tt.statusCode)
					_, _ = fmt.Fprint(w, tt.responseBody)
				},
			))
			defer server.Close()

			client := NewClient(server.URL)

			result, err := client.Answer(
				context.Background(),
				"Какой срок рассмотрения претензии?",
			)

			if (err != nil) != tt.wantErr {
				t.Fatalf("unexpected error: got %v, wantErr %v", err, tt.wantErr)
			}

			if tt.wantErr {
				return
			}

			if result.Answer != tt.wantAnswer {
				t.Errorf("unexpected answer: got %q, want %q", result.Answer, tt.wantAnswer)
			}

			if len(result.Sources) != tt.wantSourceCount {
				t.Errorf("unexpected source count: got %d, want %d",
					len(result.Sources), tt.wantSourceCount)
			}
		})
	}
}
