package claudecode

// ListModels fetches the current model list from the Anthropic REST API.
//
// Endpoint: GET https://api.anthropic.com/v1/models
// Auth:     ANTHROPIC_API_KEY environment variable.
//
// If the key is not set or the request fails, an error is returned and the
// caller (HandleAgentModels) falls back to an empty list.

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
)

const anthropicModelsURL = "https://api.anthropic.com/v1/models"

type anthropicModelsResponse struct {
	Data []struct {
		ID   string `json:"id"`
		Type string `json:"type"`
	} `json:"data"`
}

// ListModels calls the Anthropic API and returns model IDs whose type is "model".
func (a *Adapter) ListModels(ctx context.Context) ([]string, error) {
	apiKey := os.Getenv("ANTHROPIC_API_KEY")
	if apiKey == "" {
		return nil, fmt.Errorf("ANTHROPIC_API_KEY not set")
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, anthropicModelsURL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("x-api-key", apiKey)
	req.Header.Set("anthropic-version", "2023-06-01")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("anthropic models API: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("anthropic models API returned %d", resp.StatusCode)
	}

	var result anthropicModelsResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decode anthropic models response: %w", err)
	}

	ids := make([]string, 0, len(result.Data))
	for _, m := range result.Data {
		if strings.HasPrefix(m.ID, "claude-") {
			ids = append(ids, m.ID)
		}
	}
	return ids, nil
}
