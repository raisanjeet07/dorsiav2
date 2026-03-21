package main

import (
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"time"

	"github.com/cli-agents-go-wrapper-service/internal/protocol"
)

// streamOpts configures how inbound gateway envelopes are printed.
type streamOpts struct {
	quiet   bool // only assistant-visible text to stdout; almost no stderr
	verbose bool // full tool payloads, longer truncation, content-type tags
}

// handleStreamEnvelope processes one server→client envelope during prompt streaming.
// Assistant-visible text goes to stdout; adapter activity goes to stderr (unless quiet).
// Returns done=true when the turn is finished (stream.end) or fatal error.
func handleStreamEnvelope(env *protocol.Envelope, out io.Writer, log io.Writer, opt streamOpts) (done bool, err error) {
	ts := time.Now().Format("15:04:05.000")

	switch env.Type {
	case protocol.TypeStreamStart:
		if !opt.quiet {
			fmt.Fprintf(log, "[%s] stream.start\n", ts)
		}
		return false, nil

	case protocol.TypeStreamDelta:
		var p protocol.StreamDeltaPayload
		if err := json.Unmarshal(env.Payload, &p); err != nil {
			if !opt.quiet {
				fmt.Fprintf(log, "[%s] stream.delta (parse error): %v raw=%s\n", ts, err, truncate(string(env.Payload), 200))
			}
			return false, nil
		}
		ct := strings.ToLower(strings.TrimSpace(p.ContentType))
		if ct == "" {
			ct = "text"
		}
		visible := isAssistantVisibleContentType(ct)
		switch {
		case p.Content == "":
			if opt.verbose && !opt.quiet {
				fmt.Fprintf(log, "[%s] stream.delta [%s] (empty)\n", ts, ct)
			}
		case visible:
			fmt.Fprint(out, p.Content)
		default:
			// thinking, tool_input, etc. — mirror adapter activity on stderr
			if !opt.quiet {
				prefix := fmt.Sprintf("[%s] stream.delta [%s]", ts, ct)
				if opt.verbose {
					fmt.Fprintf(log, "%s role=%s\n%s\n", prefix, p.Role, indentOrTruncate(p.Content, opt.verbose))
				} else {
					fmt.Fprintf(log, "%s %s\n", prefix, truncateForLog(p.Content, 400))
				}
			}
		}
		return false, nil

	case protocol.TypeStreamEnd:
		var p protocol.StreamEndPayload
		_ = json.Unmarshal(env.Payload, &p)
		if !opt.quiet {
			line := fmt.Sprintf("[%s] stream.end finish=%s", ts, p.FinishReason)
			if p.Usage != nil {
				line += fmt.Sprintf(" usage_in=%d out=%d cost=%.4f",
					p.Usage.InputTokens, p.Usage.OutputTokens, p.Usage.TotalCost)
			}
			fmt.Fprintln(log, line)
		}
		return true, nil

	case protocol.TypeStreamError:
		if !opt.quiet {
			fmt.Fprintf(log, "[%s] stream.error payload=%s\n", ts, string(env.Payload))
		}
		return false, fmt.Errorf("stream.error: %s", string(env.Payload))

	case protocol.TypeErrorMsg:
		if env.Error != nil {
			return true, fmt.Errorf("%s: %s", env.Error.Code, env.Error.Message)
		}
		return true, fmt.Errorf("error envelope")

	case protocol.TypeAgentStatus:
		if !opt.quiet {
			var p protocol.AgentStatusPayload
			_ = json.Unmarshal(env.Payload, &p)
			fmt.Fprintf(log, "[%s] agent.status status=%s msg=%s\n", ts, p.Status, p.Message)
		}
		return false, nil

	case protocol.TypeToolUseStart:
		if !opt.quiet {
			var p protocol.ToolUseStartPayload
			_ = json.Unmarshal(env.Payload, &p)
			if opt.verbose {
				in, _ := json.MarshalIndent(p.Input, "", "  ")
				fmt.Fprintf(log, "[%s] tool.use.start id=%s name=%s\n%s\n", ts, p.ToolID, p.ToolName, string(in))
			} else {
				fmt.Fprintf(log, "[%s] tool.use.start name=%s id=%s input=%s\n", ts, p.ToolName, p.ToolID, truncateForLog(string(mustJSON(p.Input)), 500))
			}
		}
		return false, nil

	case protocol.TypeToolUseResult:
		if !opt.quiet {
			var p protocol.ToolUseResultPayload
			_ = json.Unmarshal(env.Payload, &p)
			flag := ""
			if p.IsError {
				flag = " ERROR"
			}
			if opt.verbose {
				fmt.Fprintf(log, "[%s] tool.use.result id=%s%s\n%s\n", ts, p.ToolID, flag, indentOrTruncate(p.Output, true))
			} else {
				fmt.Fprintf(log, "[%s] tool.use.result id=%s%s %s\n", ts, p.ToolID, flag, truncateForLog(p.Output, 800))
			}
		}
		return false, nil

	case protocol.TypeToolUseEnd:
		if !opt.quiet {
			fmt.Fprintf(log, "[%s] tool.use.end payload=%s\n", ts, string(env.Payload))
		}
		return false, nil

	case protocol.TypeProgress:
		if !opt.quiet {
			var p protocol.ProgressPayload
			_ = json.Unmarshal(env.Payload, &p)
			fmt.Fprintf(log, "[%s] progress %s (%.0f%%)\n", ts, p.Message, p.Percentage)
		}
		return false, nil

	case protocol.TypeFileChanged, protocol.TypeFileCreated, protocol.TypeFileDeleted, protocol.TypeFileDiff:
		if !opt.quiet {
			var p protocol.FileEventPayload
			_ = json.Unmarshal(env.Payload, &p)
			fmt.Fprintf(log, "[%s] %s path=%s\n", ts, env.Type, p.Path)
			if opt.verbose && p.Diff != "" {
				fmt.Fprintf(log, "%s\n", indentOrTruncate(p.Diff, true))
			}
		}
		return false, nil

	default:
		if !opt.quiet {
			if opt.verbose {
				fmt.Fprintf(log, "[%s] %s\n%s\n", ts, env.Type, string(env.Payload))
			} else {
				fmt.Fprintf(log, "[%s] %s payload=%s\n", ts, env.Type, truncate(string(env.Payload), 300))
			}
		}
		return false, nil
	}
}

func isAssistantVisibleContentType(ct string) bool {
	switch ct {
	case "text", "markdown", "code", "":
		return true
	default:
		return false
	}
}

func truncate(s string, max int) string {
	if max <= 0 || len(s) <= max {
		return s
	}
	return s[:max] + "…"
}

func truncateForLog(s string, max int) string {
	s = strings.ReplaceAll(s, "\n", "⏎")
	return truncate(s, max)
}

func indentOrTruncate(s string, verbose bool) string {
	if !verbose {
		return truncateForLog(s, 2000)
	}
	if s == "" {
		return "(empty)"
	}
	return s
}

func mustJSON(v any) []byte {
	b, err := json.Marshal(v)
	if err != nil {
		return []byte("{}")
	}
	return b
}
