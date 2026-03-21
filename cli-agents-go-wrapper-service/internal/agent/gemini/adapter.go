// Package gemini implements the adapter for Google's Gemini CLI agent.
//
// Default: one long-lived `gemini` process per session (stdin prompts, stdout
// stream-json), same pattern as the cursor adapter. Each SendPrompt writes one
// line to stdin and reads until a terminal `result` / `error` event.
package gemini

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"sync"

	"github.com/cli-agents-go-wrapper-service/internal/agent"
	"github.com/cli-agents-go-wrapper-service/internal/process"
	"github.com/cli-agents-go-wrapper-service/internal/protocol"
)

func init() {
	agent.RegisterAdapter("gemini", func() agent.Adapter {
		return &Adapter{
			logger: slog.Default().With("agent", "gemini"),
		}
	})
}

// Adapter implements agent.Adapter for Gemini CLI.
type Adapter struct {
	agent.BaseAdapter
	mu        sync.Mutex
	startOpts agent.StartOptions
	proc      *process.Process
	prompting *process.Process
	logger    *slog.Logger
}

func (a *Adapter) Name() string { return "gemini" }

func (a *Adapter) Modes() []agent.AgentMode {
	return []agent.AgentMode{
		{Name: "default", Description: "Standard Gemini CLI mode", Default: true},
		{Name: "sandbox", Description: "Sandboxed code execution mode (--sandbox flag)"},
	}
}

func (a *Adapter) Capabilities() *protocol.Capabilities {
	return &protocol.Capabilities{
		AgentType:       "gemini",
		SupportsTools:   true,
		SupportsFiles:   true,
		SupportsImages:  true,
		SupportsDiff:    false,
		SupportsHistory: false,
		Extra: map[string]any{
			"supportsMultimodal": true,
			"supportsSearch":     true,
		},
	}
}

func (a *Adapter) Start(ctx context.Context, opts agent.StartOptions) error {
	switch opts.ConnectionMode {
	case "spawn", "":
		return a.startSpawn(ctx, opts)
	case "connect":
		return a.startConnect(ctx, opts)
	default:
		return fmt.Errorf("unsupported connection mode: %s", opts.ConnectionMode)
	}
}

func (a *Adapter) startSpawn(ctx context.Context, opts agent.StartOptions) error {
	a.mu.Lock()
	a.startOpts = opts
	a.mu.Unlock()

	if u := agent.AdapterSessionUUID(opts.SessionID, opts.Flow); u != "" {
		a.logger.Info("start", "gateway_session_id", opts.SessionID, "flow", opts.Flow,
			"working_dir", opts.WorkingDir, "model", opts.Model, "adapter_session_uuid", shortGeminiIDForLog(u))
	} else {
		a.logger.Info("start", "working_dir", opts.WorkingDir, "model", opts.Model)
	}

	if err := a.spawn(ctx); err != nil {
		return err
	}
	a.SetRunning(true)
	return nil
}

func (a *Adapter) spawn(ctx context.Context) error {
	a.mu.Lock()
	opts := a.startOpts
	a.mu.Unlock()

	args := []string{
		"--output-format", "stream-json",
		"-y", // yolo / auto-approve
	}
	if opts.Model != "" {
		args = append(args, "--model", opts.Model)
	}
	if v, ok := opts.Config["sandbox"].(bool); ok && v {
		args = append(args, "--sandbox")
	}

	env := map[string]string{}
	if apiKey, ok := opts.Config["apiKey"].(string); ok {
		env["GOOGLE_API_KEY"] = apiKey
	}

	proc, err := process.Spawn(ctx, process.SpawnOptions{
		Command:     "gemini",
		Args:        args,
		WorkingDir:  opts.WorkingDir,
		Env:         env,
		NoStdinPipe: false,
	})
	if err != nil {
		return fmt.Errorf("spawn gemini: %w", err)
	}

	a.mu.Lock()
	a.proc = proc
	a.mu.Unlock()

	a.logger.Info("start.spawn", "command", "gemini", "pid", proc.PID(), "working_dir", opts.WorkingDir)

	go func() {
		for line := range proc.ReadStderrLines() {
			a.logger.Debug("gemini stderr", "line", line)
		}
	}()

	go func() {
		<-proc.Done()
		a.mu.Lock()
		if a.proc == proc {
			a.proc = nil
		}
		a.mu.Unlock()
		a.SetRunning(false)
	}()

	return nil
}

func (a *Adapter) startConnect(_ context.Context, opts agent.StartOptions) error {
	if opts.ConnectAddress == "" {
		return fmt.Errorf("connectAddress required for connect mode")
	}
	return fmt.Errorf("connect mode not yet implemented for gemini")
}

func (a *Adapter) Stop(_ context.Context) error {
	a.Cancel()
	a.mu.Lock()
	p := a.proc
	a.proc = nil
	a.prompting = nil
	a.mu.Unlock()
	if p != nil {
		return p.Stop()
	}
	a.SetRunning(false)
	return nil
}

func (a *Adapter) SendPrompt(ctx context.Context, prompt *protocol.PromptSendPayload, sink agent.EventSink) error {
	a.mu.Lock()
	opts := a.startOpts
	proc := a.proc
	a.mu.Unlock()

	if proc == nil || !proc.IsRunning() {
		if err := a.spawn(ctx); err != nil {
			sink.EmitError("SPAWN_FAILED", err.Error())
			return fmt.Errorf("spawn gemini: %w", err)
		}
		a.mu.Lock()
		proc = a.proc
		a.mu.Unlock()
		if proc == nil {
			return fmt.Errorf("gemini process not available")
		}
	}

	input := prompt.Content
	for _, att := range prompt.Attachments {
		if att.Path != "" {
			input += fmt.Sprintf("\n[file: %s]", att.Path)
		}
	}

	sandbox := false
	if v, ok := opts.Config["sandbox"].(bool); ok && v {
		sandbox = v
	}

	a.logger.Info("send_prompt",
		"command", "gemini",
		"pid", proc.PID(),
		"working_dir", opts.WorkingDir,
		"model", opts.Model,
		"sandbox", sandbox,
		"prompt_chars", len(input),
		"prompt", agent.PromptForLog(input),
	)

	if err := proc.WriteLine(input); err != nil {
		return fmt.Errorf("write gemini stdin: %w", err)
	}

	a.mu.Lock()
	a.prompting = proc
	a.mu.Unlock()
	defer func() {
		a.mu.Lock()
		a.prompting = nil
		a.mu.Unlock()
	}()

	_ = sink.Emit(protocol.TypeStreamStart, nil)
	_ = sink.Emit(protocol.TypeAgentStatus, &protocol.AgentStatusPayload{Status: "thinking"})

	scanner := bufio.NewScanner(proc.Stdout())
	scanner.Buffer(make([]byte, 1024*1024), 1024*1024)

	streamEnded := false
	for scanner.Scan() {
		select {
		case <-ctx.Done():
			_ = proc.Stop()
			return ctx.Err()
		default:
		}

		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}

		var event geminiEvent
		if err := json.Unmarshal([]byte(line), &event); err == nil && event.Type != "" {
			if done := a.translateEvent(&event, sink); done {
				streamEnded = true
				break
			}
			continue
		}

		_ = sink.Emit(protocol.TypeStreamDelta, &protocol.StreamDeltaPayload{
			ContentType: "text",
			Content:     line + "\n",
			Role:        "assistant",
		})
	}

	if !streamEnded {
		_ = sink.Emit(protocol.TypeStreamEnd, &protocol.StreamEndPayload{FinishReason: "complete"})
		_ = sink.Emit(protocol.TypeAgentStatus, &protocol.AgentStatusPayload{Status: "idle"})
	}

	return nil
}

// CancelPrompt interrupts the running gemini process (same as persistent cursor).
func (a *Adapter) CancelPrompt(_ context.Context) error {
	a.mu.Lock()
	p := a.prompting
	if p != nil && p == a.proc {
		a.proc = nil
	}
	a.prompting = nil
	a.mu.Unlock()
	if p != nil {
		return p.Stop()
	}
	return nil
}

// geminiEvent represents Gemini CLI stream-json (JSONL) output.
type geminiEvent struct {
	Type      string `json:"type"`
	Timestamp string `json:"timestamp,omitempty"`

	Role    string `json:"role,omitempty"`
	Content string `json:"content,omitempty"`

	SessionID string `json:"session_id,omitempty"`
	Model     string `json:"model,omitempty"`

	ToolName string          `json:"toolName,omitempty"`
	ToolID   string          `json:"toolId,omitempty"`
	Name     string          `json:"name,omitempty"`
	Args     json.RawMessage `json:"args,omitempty"`

	Result string `json:"result,omitempty"`
	Output string `json:"output,omitempty"`

	Status      string        `json:"status,omitempty"`
	ResultError *geminiRError `json:"error,omitempty"`
	Stats       *geminiStats  `json:"stats,omitempty"`
}

type geminiRError struct {
	Type    string `json:"type,omitempty"`
	Message string `json:"message,omitempty"`
}

type geminiStats struct {
	TotalTokens  int `json:"total_tokens,omitempty"`
	InputTokens  int `json:"input_tokens,omitempty"`
	OutputTokens int `json:"output_tokens,omitempty"`
}

func (a *Adapter) translateEvent(event *geminiEvent, sink agent.EventSink) bool {
	switch event.Type {

	case "init":
		a.logger.Info("stream.init", "session_id", shortGeminiIDForLog(event.SessionID), "model", event.Model)

	case "message":
		if event.Role == "user" {
			break
		}
		if event.Content != "" {
			_ = sink.Emit(protocol.TypeStreamDelta, &protocol.StreamDeltaPayload{
				ContentType: "text",
				Content:     event.Content,
				Role:        "assistant",
			})
		}

	case "thought":
		if event.Content != "" {
			_ = sink.Emit(protocol.TypeStreamDelta, &protocol.StreamDeltaPayload{
				ContentType: "thinking",
				Content:     event.Content,
				Role:        "assistant",
			})
		}

	case "tool_use":
		toolName := event.ToolName
		if toolName == "" {
			toolName = event.Name
		}
		var input map[string]any
		if event.Args != nil {
			_ = json.Unmarshal(event.Args, &input)
		}
		_ = sink.Emit(protocol.TypeToolUseStart, &protocol.ToolUseStartPayload{
			ToolID:   event.ToolID,
			ToolName: toolName,
			Input:    input,
		})
		_ = sink.Emit(protocol.TypeAgentStatus, &protocol.AgentStatusPayload{
			Status:  "tool_use",
			Message: toolName,
		})

	case "tool_result":
		output := event.Result
		if output == "" {
			output = event.Output
		}
		_ = sink.Emit(protocol.TypeToolUseResult, &protocol.ToolUseResultPayload{
			ToolID: event.ToolID,
			Output: output,
		})

	case "result":
		if event.Status == "error" && event.ResultError != nil {
			sink.EmitError("GEMINI_ERROR", event.ResultError.Message)
			_ = sink.Emit(protocol.TypeStreamEnd, &protocol.StreamEndPayload{FinishReason: "error"})
			_ = sink.Emit(protocol.TypeAgentStatus, &protocol.AgentStatusPayload{Status: "idle"})
			return true
		}
		var usage *protocol.UsageInfo
		if event.Stats != nil {
			usage = &protocol.UsageInfo{
				InputTokens:  event.Stats.InputTokens,
				OutputTokens: event.Stats.OutputTokens,
			}
		}
		_ = sink.Emit(protocol.TypeStreamEnd, &protocol.StreamEndPayload{
			FinishReason: "complete",
			Usage:        usage,
		})
		_ = sink.Emit(protocol.TypeAgentStatus, &protocol.AgentStatusPayload{Status: "idle"})
		return true

	case "error":
		errMsg := event.Content
		if errMsg == "" && event.ResultError != nil {
			errMsg = event.ResultError.Message
		}
		sink.EmitError("GEMINI_ERROR", errMsg)
		_ = sink.Emit(protocol.TypeStreamEnd, &protocol.StreamEndPayload{FinishReason: "error"})
		_ = sink.Emit(protocol.TypeAgentStatus, &protocol.AgentStatusPayload{Status: "idle"})
		return true
	}

	return false
}

func (a *Adapter) ApproveToolUse(_ context.Context, _ string) error {
	return nil
}

func (a *Adapter) RejectToolUse(_ context.Context, _ string, _ string) error {
	return nil
}

func shortGeminiIDForLog(id string) string {
	if id == "" {
		return ""
	}
	if len(id) <= 16 {
		return id
	}
	return id[:8] + "..." + id[len(id)-4:]
}

var _ agent.Adapter = (*Adapter)(nil)
