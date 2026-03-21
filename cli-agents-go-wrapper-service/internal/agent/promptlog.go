package agent

// PromptForLog returns user prompt text safe for structured logs: empty prompts are
// labeled, and very long prompts are truncated so log files stay usable.
//
// Adapters include this as the JSON field "prompt" on send_prompt / send_prompt.* INFO
// lines (alongside prompt_chars). Keep that logging when changing stdin wiring — it is
// relied on for debugging and audits (see logs/README.md).
func PromptForLog(s string) string {
	if s == "" {
		return "(empty)"
	}
	const maxRunes = 8000
	r := []rune(s)
	if len(r) <= maxRunes {
		return s
	}
	return string(r[:maxRunes]) + "… (truncated)"
}
