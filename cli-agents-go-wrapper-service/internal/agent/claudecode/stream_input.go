package claudecode

import "encoding/json"

// claudeStreamJSONUserLine returns one NDJSON line for --input-format stream-json (with --print).
// Format follows the Claude API message shape; adjust if the CLI schema changes.
func claudeStreamJSONUserLine(userText string) (string, error) {
	msg := map[string]any{
		"type": "user",
		"message": map[string]any{
			"role": "user",
			"content": []map[string]any{
				{"type": "text", "text": userText},
			},
		},
	}
	b, err := json.Marshal(msg)
	if err != nil {
		return "", err
	}
	return string(b), nil
}
