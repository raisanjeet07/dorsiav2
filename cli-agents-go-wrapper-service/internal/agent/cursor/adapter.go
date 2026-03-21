// Package cursor implements the gateway adapter for Cursor (flow name "cursor").
//
// The subprocess is always the **`agent`** CLI (not a binary named "cursor").
// Session routing and protocol use flow "cursor"; logs use agent=cursor for the adapter id.
//
// The agent process communicates via stdin/stdout; in agent mode it streams
// JSON-like messages with tool calls, diffs, and completions.
package cursor

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

// cursorCLICommand is the OS command used to spawn the Cursor-related CLI.
// The gateway flow name remains "cursor"; this is the actual executable name.
const cursorCLICommand = "agent"

func init() {
	agent.RegisterAdapter("cursor", func() agent.Adapter {
		return &Adapter{
			logger: slog.Default().With("agent", "cursor"),
		}
	})
}

// Adapter implements agent.Adapter for Cursor CLI.
type Adapter struct {
	agent.BaseAdapter
	mu        sync.Mutex
	proc      *process.Process
	prompting *process.Process
	logger    *slog.Logger
}

func (a *Adapter) Name() string { return "cursor" }

func (a *Adapter) Modes() []agent.AgentMode {
	return []agent.AgentMode{
		{Name: "agent", Description: "Agent mode with full tool use", Default: true},
		{Name: "composer", Description: "Composer mode focused on file generation"},
	}
}

func (a *Adapter) Capabilities() *protocol.Capabilities {
	return &protocol.Capabilities{
		AgentType:       "cursor",
		SupportsTools:   true,
		SupportsFiles:   true,
		SupportsImages:  false,
		SupportsDiff:    true,
		SupportsHistory: false,
		// SupportedModels intentionally omitted — Cursor does not expose
	// a model-list API; the model is managed inside the Cursor IDE.
		Extra: map[string]any{
			"supportsComposer": true,
		},
	}
}

func (a *Adapter) Start(ctx context.Context, opts agent.StartOptions) error {
	switch opts.ConnectionMode {
	case "spawn":
		return a.startSpawn(ctx, opts)
	case "connect":
		return a.startConnect(ctx, opts)
	default:
		return fmt.Errorf("unsupported connection mode: %s", opts.ConnectionMode)
	}
}

func (a *Adapter) startSpawn(ctx context.Context, opts agent.StartOptions) error {
	// `agent` CLI with agent/composer flags (gateway flow is still "cursor").
	args := []string{"--agent"}

	if opts.Model != "" {
		args = append(args, "--model", opts.Model)
	}

	// Additional flags from config.
	if extraArgs, ok := opts.Config["args"].([]any); ok {
		for _, arg := range extraArgs {
			if s, ok := arg.(string); ok {
				args = append(args, s)
			}
		}
	}

	proc, err := process.Spawn(ctx, process.SpawnOptions{
		Command:    cursorCLICommand,
		Args:       args,
		WorkingDir: opts.WorkingDir,
	})
	if err != nil {
		return fmt.Errorf("spawn %s (cursor adapter): %w", cursorCLICommand, err)
	}

	logArgs := []any{
		"cli_command", cursorCLICommand,
		"pid", proc.PID(),
		"working_dir", opts.WorkingDir,
		"model", opts.Model,
		"args", args,
	}
	if u := agent.AdapterSessionUUID(opts.SessionID, opts.Flow); u != "" {
		logArgs = append(logArgs, "gateway_session_id", opts.SessionID, "flow", opts.Flow, "adapter_session_uuid", u)
	}
	a.logger.Info("start", logArgs...)

	a.proc = proc
	a.SetRunning(true)

	go func() {
		<-proc.Done()
		a.SetRunning(false)
	}()

	go func() {
		for line := range proc.ReadStderrLines() {
			a.logger.Debug("cursor stderr", "line", line)
		}
	}()

	return nil
}

func (a *Adapter) startConnect(_ context.Context, opts agent.StartOptions) error {
	if opts.ConnectAddress == "" {
		return fmt.Errorf("connectAddress required for connect mode")
	}
	// TODO: Implement connection to running Cursor instance via its IPC.
	return fmt.Errorf("connect mode not yet implemented for cursor")
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
	return nil
}

// CancelPrompt stops the agent subprocess so an in-flight SendPrompt read exits.
func (a *Adapter) CancelPrompt(_ context.Context) error {
	a.mu.Lock()
	p := a.prompting
	if p != nil {
		a.prompting = nil
		a.proc = nil
	}
	a.mu.Unlock()
	if p != nil {
		return p.Stop()
	}
	return nil
}

func (a *Adapter) SendPrompt(ctx context.Context, prompt *protocol.PromptSendPayload, sink agent.EventSink) error {
	if a.proc == nil || !a.proc.IsRunning() {
		return fmt.Errorf("%s process not running (cursor adapter)", cursorCLICommand)
	}

	_ = sink.Emit(protocol.TypeStreamStart, nil)
	_ = sink.Emit(protocol.TypeAgentStatus, &protocol.AgentStatusPayload{Status: "thinking"})

	a.logger.Info("send_prompt",
		"pid", a.proc.PID(),
		"prompt_chars", len(prompt.Content),
		"prompt", agent.PromptForLog(prompt.Content),
	)

	a.mu.Lock()
	a.prompting = a.proc
	a.mu.Unlock()
	defer func() {
		a.mu.Lock()
		a.prompting = nil
		a.mu.Unlock()
	}()

	// Send prompt via stdin.
	if err := a.proc.WriteLine(prompt.Content); err != nil {
		return fmt.Errorf("write prompt: %w", err)
	}

	// Read and translate output.
	scanner := bufio.NewScanner(a.proc.Stdout())
	scanner.Buffer(make([]byte, 1024*1024), 1024*1024)

	for scanner.Scan() {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}

		// Try to parse as JSON event first.
		var event cursorEvent
		if err := json.Unmarshal([]byte(line), &event); err == nil && event.Type != "" {
			if done := a.translateEvent(&event, sink); done {
				break
			}
			continue
		}

		// Fallback: treat as plain text streaming output.
		_ = sink.Emit(protocol.TypeStreamDelta, &protocol.StreamDeltaPayload{
			ContentType: "text",
			Content:     line + "\n",
			Role:        "assistant",
		})
	}

	return nil
}

// cursorEvent represents Cursor CLI's JSON output events.
type cursorEvent struct {
	Type    string `json:"type"`
	Content string `json:"content,omitempty"`

	// Tool fields
	Tool   string          `json:"tool,omitempty"`
	ToolID string          `json:"toolId,omitempty"`
	Input  json.RawMessage `json:"input,omitempty"`
	Output string          `json:"output,omitempty"`

	// File change fields
	File string `json:"file,omitempty"`
	Diff string `json:"diff,omitempty"`

	// Completion fields
	FinishReason string `json:"finishReason,omitempty"`
}

func (a *Adapter) translateEvent(event *cursorEvent, sink agent.EventSink) bool {
	switch event.Type {
	case "text", "message":
		_ = sink.Emit(protocol.TypeStreamDelta, &protocol.StreamDeltaPayload{
			ContentType: "text",
			Content:     event.Content,
			Role:        "assistant",
		})

	case "thinking":
		_ = sink.Emit(protocol.TypeStreamDelta, &protocol.StreamDeltaPayload{
			ContentType: "thinking",
			Content:     event.Content,
			Role:        "assistant",
		})

	case "tool_call", "tool_use":
		var input map[string]any
		_ = json.Unmarshal(event.Input, &input)
		_ = sink.Emit(protocol.TypeToolUseStart, &protocol.ToolUseStartPayload{
			ToolID:   event.ToolID,
			ToolName: event.Tool,
			Input:    input,
		})
		_ = sink.Emit(protocol.TypeAgentStatus, &protocol.AgentStatusPayload{
			Status:  "tool_use",
			Message: event.Tool,
		})

	case "tool_result":
		_ = sink.Emit(protocol.TypeToolUseResult, &protocol.ToolUseResultPayload{
			ToolID: event.ToolID,
			Output: event.Output,
		})

	case "file_change", "diff":
		_ = sink.Emit(protocol.TypeFileChanged, &protocol.FileEventPayload{
			Path: event.File,
			Diff: event.Diff,
		})

	case "done", "complete", "result":
		finishReason := event.FinishReason
		if finishReason == "" {
			finishReason = "complete"
		}
		_ = sink.Emit(protocol.TypeStreamEnd, &protocol.StreamEndPayload{
			FinishReason: finishReason,
		})
		_ = sink.Emit(protocol.TypeAgentStatus, &protocol.AgentStatusPayload{Status: "idle"})
		return true
	}

	return false
}

var _ agent.Adapter = (*Adapter)(nil)
