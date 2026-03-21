package gemini

// ListModels fetches the current model list from the Google Generative AI REST API.
//
// Endpoint: GET https://generativelanguage.googleapis.com/v1beta/models
// Auth:     GOOGLE_API_KEY (or GEMINI_API_KEY) environment variable.
//
// Only models that support "generateContent" are returned, filtered to
// those whose name starts with "gemini-".

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
)

const googleModelsURL = "https://generativelanguage.googleapis.com/v1beta/models"

type googleModelsResponse struct {
	Models []struct {
		Name                       string   `json:"name"` // "models/gemini-2.5-pro"
		SupportedGenerationMethods []string `json:"supportedGenerationMethods"`
	} `json:"models"`
}

// ListModels calls the Google Generative AI API and returns model IDs.
func (a *Adapter) ListModels(ctx context.Context) ([]string, error) {
	apiKey := os.Getenv("GOOGLE_API_KEY")
	if apiKey == "" {
		apiKey = os.Getenv("GEMINI_API_KEY")
	}
	if apiKey == "" {
		return nil, fmt.Errorf("GOOGLE_API_KEY (or GEMINI_API_KEY) not set")
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, googleModelsURL, nil)
	if err != nil {
		return nil, err
	}
	q := req.URL.Query()
	q.Set("key", apiKey)
	req.URL.RawQuery = q.Encode()

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("google models API: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("google models API returned %d", resp.StatusCode)
	}

	var result googleModelsResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decode google models response: %w", err)
	}

	ids := make([]string, 0, len(result.Models))
	for _, m := range result.Models {
		// Strip the "models/" prefix and filter to gemini models that support generation.
		name := strings.TrimPrefix(m.Name, "models/")
		if !strings.HasPrefix(name, "gemini-") {
			continue
		}
		if !supportsGenerateContent(m.SupportedGenerationMethods) {
			continue
		}
		ids = append(ids, name)
	}
	return ids, nil
}

func supportsGenerateContent(methods []string) bool {
	for _, m := range methods {
		if m == "generateContent" {
			return true
		}
	}
	return false
}
