// Package claudecode implements the adapter for Anthropic's Claude Code CLI agent.
//
// Default: one long-lived `claude` process per session: --print --output-format stream-json
// --input-format stream-json with stdin NDJSON user lines and stdout stream-json until each
// `result`. If stderr reports "Session ID … already in use", spawn is retried (then a new
// Claude session UUID may be generated).
//
// One-shot mode (config claudeDisableResume or CLAUDE_CODE_DISABLE_RESUME): each
// prompt uses `claude -p ...` (new subprocess per prompt).
//
// Session UUID: agent.AdapterSessionUUID (deterministic hash of sessionId+flow) + optional
// config claudeSessionId override;
// persistent mode passes --session-id on spawn.
//
// Attached skills are injected via --append-system-prompt flags.
// Attached MCP servers are passed as a single --mcp-config JSON string.
//
// Streaming JSON event shapes (subset):
//
//	{"type":"system","subtype":"init","session_id":"<uuid>",...}
//	{"type":"assistant","message":{"content":[{"type":"text","text":"..."}]},...}
//	{"type":"tool_use","id":"<id>","name":"<tool>","input":{...},...}
//	{"type":"tool_result","tool_use_id":"<id>","content":"...",...}
//	{"type":"result","subtype":"success","total_cost_usd":0.04,"duration_ms":1763,...}
package claudecode

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/cli-agents-go-wrapper-service/internal/agent"
	"github.com/cli-agents-go-wrapper-service/internal/process"
	"github.com/cli-agents-go-wrapper-service/internal/protocol"
	"github.com/google/uuid"
)

func init() {
	agent.RegisterAdapter("claude-code", func() agent.Adapter {
		return &Adapter{
			logger: slog.Default().With("agent", "claude-code"),
		}
	})
}

// Adapter implements agent.Adapter for Claude Code.
//
// Design: one adapter per gateway session. Persistent mode keeps proc and sends
// each user turn on stdin; one-shot mode spawns per prompt with -p.
type Adapter struct {
	agent.BaseAdapter

	mu        sync.Mutex
	opts      agent.StartOptions
	sessionID string // Claude CLI session UUID for CLI flags (persistent spawn)
	proc      *process.Process
	prompting *process.Process // stdout being read for current prompt (cancel target)
	logger    *slog.Logger
}

// logClaudeStderrLine logs stderr from the Claude CLI; actionable problems are WARN.
func (a *Adapter) logClaudeStderrLine(line string) {
	line = strings.TrimSpace(line)
	if line == "" {
		return
	}
	l := strings.ToLower(line)
	if strings.Contains(l, "error") || strings.Contains(l, "already in use") || strings.Contains(l, "fatal") {
		a.logger.Warn("claude stderr", "line", line)
		return
	}
	a.logger.Debug("claude stderr", "line", line)
}

func (a *Adapter) Name() string { return "claude-code" }

func (a *Adapter) Modes() []agent.AgentMode {
	return []agent.AgentMode{
		{Name: "default", Description: "Standard permission prompting", Default: true},
		{Name: "acceptEdits", Description: "Auto-accept file edits without prompting"},
		{Name: "bypassPermissions", Description: "Skip all permission checks (--dangerously-skip-permissions)"},
		{Name: "dontAsk", Description: "Never ask for tool confirmation"},
		{Name: "plan", Description: "Planning mode only — reads but does not execute"},
		{Name: "auto", Description: "Fully autonomous mode with minimal interruption"},
	}
}

func (a *Adapter) Capabilities() *protocol.Capabilities {
	return &protocol.Capabilities{
		AgentType:       "claude-code",
		SupportsTools:   true,
		SupportsFiles:   true,
		SupportsImages:  true,
		SupportsDiff:    true,
		SupportsHistory: true,
		// SupportedModels intentionally omitted — fetched dynamically via
		// ListModels() which calls the Anthropic API.
		Extra: map[string]any{
			"supportsCancel":       true,
			"supportsToolApproval": true,
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

// startSpawn stores opts and, unless one-shot mode is enabled, spawns a persistent claude process.
func (a *Adapter) startSpawn(ctx context.Context, opts agent.StartOptions) error {
	if _, err := findClaudeBinary(); err != nil {
		return fmt.Errorf("claude binary not found: %w", err)
	}
	a.mu.Lock()
	a.opts = opts
	a.sessionID = ""
	if opts.Config != nil {
		if sid, ok := opts.Config["claudeSessionId"].(string); ok && sid != "" {
			a.sessionID = sid
		}
	}
	if a.sessionID == "" {
		if derived := agent.AdapterSessionUUID(opts.SessionID, opts.Flow); derived != "" {
			a.sessionID = derived
		}
	}
	gw := opts.SessionID
	fl := opts.Flow
	sidLog := shortIDForLog(a.sessionID)
	oneShot := a.resumeDisabledLocked()
	a.mu.Unlock()

	if sidLog != "" {
		a.logger.Info("start", "gateway_session_id", gw, "flow", fl, "working_dir", opts.WorkingDir, "model", opts.Model, "claude_session_id", sidLog, "mode", map[bool]string{true: "one_shot", false: "persistent"}[oneShot])
	} else {
		a.logger.Info("start", "gateway_session_id", gw, "flow", fl, "working_dir", opts.WorkingDir, "model", opts.Model, "mode", map[bool]string{true: "one_shot", false: "persistent"}[oneShot])
	}

	if oneShot {
		a.SetRunning(true)
		return nil
	}
	if err := a.spawnPersistent(ctx); err != nil {
		return err
	}
	a.SetRunning(true)
	return nil
}

func (a *Adapter) resumeDisabledLocked() bool {
	opts := a.opts
	if opts.Config != nil {
		if v, ok := opts.Config["claudeDisableResume"].(bool); ok && v {
			return true
		}
	}
	s := os.Getenv("CLAUDE_CODE_DISABLE_RESUME")
	return s == "1" || strings.EqualFold(s, "true")
}

func sessionAlreadyInUseLine(line string) bool {
	l := strings.ToLower(strings.TrimSpace(line))
	return strings.Contains(l, "already in use") && strings.Contains(l, "session")
}

// spawnClaudeProc builds argv and starts one claude persistent process (stream-json stdin/stdout).
func (a *Adapter) spawnClaudeProc(ctx context.Context, opts agent.StartOptions, sessionID, binary string) (*process.Process, error) {
	args := []string{
		"--print",
		"--output-format", "stream-json",
		"--input-format", "stream-json",
		"--verbose",
		"--dangerously-skip-permissions",
	}
	if opts.Model != "" {
		args = append(args, "--model", opts.Model)
	}
	if sessionID != "" {
		args = append(args, "--session-id", sessionID)
	}
	for _, s := range a.AttachedSkills() {
		args = append(args, "--append-system-prompt", s.Prompt)
	}
	if mcps := a.AttachedMCPs(); len(mcps) > 0 {
		mcpJSON, err := buildMCPConfigJSON(mcps)
		if err != nil {
			a.logger.Warn("failed to build mcp config", "error", err)
		} else {
			args = append(args, "--mcp-config", mcpJSON)
		}
	}

	env := map[string]string{}
	if apiKey, ok := opts.Config["apiKey"].(string); ok {
		env["ANTHROPIC_API_KEY"] = apiKey
	}

	return process.Spawn(ctx, process.SpawnOptions{
		Command:     binary,
		Args:        args,
		WorkingDir:  opts.WorkingDir,
		Env:         env,
		NoStdinPipe: false,
	})
}

// spawnPersistent runs claude once with stdin/stdout stream-json (no -p).
// Retries if stderr reports "Session ID … already in use", then may assign a fresh Claude UUID.
func (a *Adapter) spawnPersistent(ctx context.Context) error {
	a.mu.Lock()
	opts := a.opts
	sessionID := a.sessionID
	binary, err := findClaudeBinary()
	a.mu.Unlock()
	if err != nil {
		return err
	}

	const maxAttempts = 3
	const conflictWait = 2 * time.Second
	const retryDelay = 400 * time.Millisecond

	for attempt := 1; attempt <= maxAttempts; attempt++ {
		a.mu.Lock()
		sessionID = a.sessionID
		opts = a.opts
		a.mu.Unlock()

		proc, err := a.spawnClaudeProc(ctx, opts, sessionID, binary)
		if err != nil {
			return fmt.Errorf("spawn claude (persistent): %w", err)
		}

		conflictCh := make(chan struct{}, 1)
		go func() {
			for line := range proc.ReadStderrLines() {
				if sessionAlreadyInUseLine(line) {
					select {
					case conflictCh <- struct{}{}:
					default:
					}
				}
				a.logClaudeStderrLine(line)
			}
		}()

		select {
		case <-conflictCh:
			a.logger.Warn("claude session id already in use; stopping subprocess and retrying",
				"attempt", attempt,
				"session_id", shortIDForLog(sessionID))
			_ = proc.Stop()
			if attempt == maxAttempts {
				return fmt.Errorf("claude: session id %q still in use after %d attempts (another claude process may hold it)",
					shortIDForLog(sessionID), maxAttempts)
			}
			time.Sleep(retryDelay)
			if attempt == 2 {
				newID := uuid.New().String()
				a.mu.Lock()
				a.sessionID = newID
				a.mu.Unlock()
				a.logger.Warn("assigning new Claude session UUID after repeated conflict",
					"claude_session_id", shortIDForLog(newID))
			}
			continue
		case <-time.After(conflictWait):
			// No early conflict on stderr — process likely owns the session.
		}

		a.mu.Lock()
		a.proc = proc
		a.mu.Unlock()

		a.logger.Info("start.spawn_persistent", "binary", binary, "pid", proc.PID(), "working_dir", opts.WorkingDir)

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
	return fmt.Errorf("claude: spawn persistent internal error")
}

func (a *Adapter) startConnect(_ context.Context, opts agent.StartOptions) error {
	if opts.ConnectAddress == "" {
		return fmt.Errorf("connectAddress required for connect mode")
	}
	return fmt.Errorf("connect mode not yet implemented for claude-code")
}

func (a *Adapter) Stop(_ context.Context) error {
	a.Cancel()
	a.mu.Lock()
	p := a.proc
	a.proc = nil
	a.prompting = nil
	a.mu.Unlock()
	if p != nil {
		_ = p.Stop()
	}
	a.SetRunning(false)
	return nil
}

// resumeDisabled is true for one-shot -p mode (no persistent process).
func (a *Adapter) resumeDisabled() bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.resumeDisabledLocked()
}

// SendPrompt dispatches to persistent stdin/stdout mode or one-shot -p mode.
func (a *Adapter) SendPrompt(ctx context.Context, prompt *protocol.PromptSendPayload, sink agent.EventSink) error {
	if a.resumeDisabled() {
		return a.sendPromptOneshot(ctx, prompt, sink)
	}
	return a.sendPromptPersistent(ctx, prompt, sink)
}

func (a *Adapter) sendPromptOneshot(ctx context.Context, prompt *protocol.PromptSendPayload, sink agent.EventSink) error {
	a.mu.Lock()
	opts := a.opts
	a.mu.Unlock()

	binary, err := findClaudeBinary()
	if err != nil {
		return fmt.Errorf("claude binary not found: %w", err)
	}

	args := []string{
		"-p", prompt.Content,
		"--output-format", "stream-json",
		"--verbose",
		"--dangerously-skip-permissions",
	}
	if opts.Model != "" {
		args = append(args, "--model", opts.Model)
	}
	for _, s := range a.AttachedSkills() {
		args = append(args, "--append-system-prompt", s.Prompt)
	}
	if mcps := a.AttachedMCPs(); len(mcps) > 0 {
		mcpJSON, err := buildMCPConfigJSON(mcps)
		if err != nil {
			a.logger.Warn("failed to build mcp config", "error", err)
		} else {
			args = append(args, "--mcp-config", mcpJSON)
		}
	}

	env := map[string]string{}
	if apiKey, ok := opts.Config["apiKey"].(string); ok {
		env["ANTHROPIC_API_KEY"] = apiKey
	}

	proc, err := process.Spawn(ctx, process.SpawnOptions{
		Command:     binary,
		Args:        args,
		WorkingDir:  opts.WorkingDir,
		Env:         env,
		NoStdinPipe: true,
	})
	if err != nil {
		return fmt.Errorf("spawn claude: %w", err)
	}
	a.logger.Info("send_prompt.one_shot",
		"binary", binary,
		"pid", proc.PID(),
		"prompt_chars", len(prompt.Content),
		"prompt", agent.PromptForLog(prompt.Content),
	)
	defer proc.Stop() //nolint:errcheck

	go func() {
		for line := range proc.ReadStderrLines() {
			a.logClaudeStderrLine(line)
		}
	}()

	a.armPrompt(proc)
	defer a.disarmPrompt()
	return a.readClaudeStream(ctx, proc, sink)
}

func (a *Adapter) sendPromptPersistent(ctx context.Context, prompt *protocol.PromptSendPayload, sink agent.EventSink) error {
	a.mu.Lock()
	proc := a.proc
	a.mu.Unlock()
	if proc == nil || !proc.IsRunning() {
		if err := a.spawnPersistent(ctx); err != nil {
			return err
		}
		a.mu.Lock()
		proc = a.proc
		a.mu.Unlock()
		if proc == nil {
			return fmt.Errorf("claude persistent process not available")
		}
	}

	line, err := claudeStreamJSONUserLine(prompt.Content)
	if err != nil {
		return err
	}
	a.logger.Info("send_prompt.persistent",
		"pid", proc.PID(),
		"prompt_chars", len(prompt.Content),
		"prompt", agent.PromptForLog(prompt.Content),
	)
	a.logger.Debug("stdin_ndjson_line", "chars", len(line), "preview", agent.PromptForLog(line))
	if err := proc.WriteLine(line); err != nil {
		return fmt.Errorf("write claude stdin: %w", err)
	}
	a.armPrompt(proc)
	defer a.disarmPrompt()
	return a.readClaudeStream(ctx, proc, sink)
}

func (a *Adapter) armPrompt(p *process.Process) {
	a.mu.Lock()
	a.prompting = p
	a.mu.Unlock()
}

func (a *Adapter) disarmPrompt() {
	a.mu.Lock()
	a.prompting = nil
	a.mu.Unlock()
}

func (a *Adapter) readClaudeStream(ctx context.Context, proc *process.Process, sink agent.EventSink) error {
	_ = sink.Emit(protocol.TypeStreamStart, nil)
	_ = sink.Emit(protocol.TypeAgentStatus, &protocol.AgentStatusPayload{Status: "thinking"})

	scanner := bufio.NewScanner(proc.Stdout())
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

		var event claudeEvent
		if err := json.Unmarshal([]byte(line), &event); err != nil {
			a.logger.Warn("failed to parse claude event", "line", line, "error", err)
			continue
		}

		if done := a.translateEvent(&event, sink); done {
			break
		}
	}

	if err := scanner.Err(); err != nil {
		return fmt.Errorf("read claude stdout: %w", err)
	}
	return nil
}

// -----------------------------------------------------------------------
// Event structs — matching actual claude --output-format stream-json schema
// -----------------------------------------------------------------------

type claudeEvent struct {
	Type    string `json:"type"`
	Subtype string `json:"subtype,omitempty"`

	// system/init
	SessionID string `json:"session_id,omitempty"`

	// assistant
	Message *claudeMessage `json:"message,omitempty"`

	// tool_use (top-level, from older format)
	ID    string          `json:"id,omitempty"`
	Name  string          `json:"name,omitempty"`
	Input json.RawMessage `json:"input,omitempty"`

	// tool_result
	ToolUseID string          `json:"tool_use_id,omitempty"`
	Content   json.RawMessage `json:"content,omitempty"`

	// result
	TotalCostUSD float64 `json:"total_cost_usd,omitempty"`
	DurationMS   int     `json:"duration_ms,omitempty"`
	NumTurns     int     `json:"num_turns,omitempty"`
	IsError      bool    `json:"is_error,omitempty"`
}

type claudeMessage struct {
	Content []claudeContentBlock `json:"content"`
	Usage   *claudeUsage         `json:"usage,omitempty"`
}

type claudeContentBlock struct {
	Type string `json:"type"` // "text", "thinking", "tool_use"
	Text string `json:"text,omitempty"`

	// tool_use block
	ID    string          `json:"id,omitempty"`
	Name  string          `json:"name,omitempty"`
	Input json.RawMessage `json:"input,omitempty"`
}

type claudeUsage struct {
	InputTokens  int `json:"input_tokens"`
	OutputTokens int `json:"output_tokens"`
}

// translateEvent converts one raw claude event into protocol messages.
// Returns true when the stream is complete.
func (a *Adapter) translateEvent(event *claudeEvent, sink agent.EventSink) bool {
	switch event.Type {
	case "system":
		if event.Subtype == "init" && event.SessionID != "" {
			if a.resumeDisabled() {
				a.logger.Debug("claude resume disabled; not persisting session id")
			} else {
				a.mu.Lock()
				existing := a.sessionID
				if existing == "" {
					a.sessionID = event.SessionID
					a.logger.Info("stream.system_init", "claude_session_id", shortIDForLog(event.SessionID))
				} else if event.SessionID != existing {
					a.logger.Debug("stream.system_init claude session_id differs from gateway-derived",
						"from_claude", shortIDForLog(event.SessionID),
						"expected", shortIDForLog(existing))
				}
				a.mu.Unlock()
			}
		}

	case "assistant":
		if event.Message == nil {
			return false
		}
		for _, block := range event.Message.Content {
			switch block.Type {
			case "text":
				_ = sink.Emit(protocol.TypeStreamDelta, &protocol.StreamDeltaPayload{
					ContentType: "text",
					Content:     block.Text,
					Role:        "assistant",
				})
			case "thinking":
				_ = sink.Emit(protocol.TypeStreamDelta, &protocol.StreamDeltaPayload{
					ContentType: "thinking",
					Content:     block.Text,
					Role:        "assistant",
				})
			case "tool_use":
				var input map[string]any
				_ = json.Unmarshal(block.Input, &input)
				_ = sink.Emit(protocol.TypeToolUseStart, &protocol.ToolUseStartPayload{
					ToolID:   block.ID,
					ToolName: block.Name,
					Input:    input,
				})
				_ = sink.Emit(protocol.TypeAgentStatus, &protocol.AgentStatusPayload{
					Status:  "tool_use",
					Message: block.Name,
				})
			}
		}

	case "tool_result":
		var output string
		// content may be a string or array; try string first
		if err := json.Unmarshal(event.Content, &output); err != nil {
			// fall back: marshal back to string
			output = string(event.Content)
		}
		_ = sink.Emit(protocol.TypeToolUseResult, &protocol.ToolUseResultPayload{
			ToolID:  event.ToolUseID,
			Output:  output,
			IsError: event.IsError,
		})

	case "result":
		finishReason := "complete"
		if event.Subtype == "error" || event.IsError {
			finishReason = "error"
		}
		_ = sink.Emit(protocol.TypeStreamEnd, &protocol.StreamEndPayload{
			FinishReason: finishReason,
			Usage: &protocol.UsageInfo{
				TotalCost: event.TotalCostUSD,
			},
		})
		_ = sink.Emit(protocol.TypeAgentStatus, &protocol.AgentStatusPayload{Status: "idle"})
		return true

	// Intentionally ignored event types
	case "rate_limit_event", "debug":
		// no-op
	}

	return false
}

func (a *Adapter) ApproveToolUse(_ context.Context, _ string) error {
	// In print mode with --dangerously-skip-permissions, tool calls are auto-approved.
	return nil
}

func (a *Adapter) RejectToolUse(_ context.Context, _ string, _ string) error {
	return fmt.Errorf("tool rejection not supported in this adapter mode")
}

// CancelPrompt stops the process currently being read for this prompt (one-shot or persistent).
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

// Ensure Adapter satisfies agent.Adapter.
var _ agent.Adapter = (*Adapter)(nil)

// buildMCPConfigJSON serialises a slice of MCPServer into the JSON format
// that claude --mcp-config expects:
//
//	{"mcpServers":{"<name>":{"type":"stdio","command":"npx","args":[...],"env":{}}}}
func buildMCPConfigJSON(mcps []agent.MCPServer) (string, error) {
	servers := make(map[string]any, len(mcps))
	for _, m := range mcps {
		entry := map[string]any{
			"type": string(m.Type),
		}
		if m.Command != "" {
			entry["command"] = m.Command
		}
		if len(m.Args) > 0 {
			entry["args"] = m.Args
		}
		if m.URL != "" {
			entry["url"] = m.URL
		}
		if len(m.Env) > 0 {
			entry["env"] = m.Env
		}
		servers[m.Name] = entry
	}
	data, err := json.Marshal(map[string]any{"mcpServers": servers})
	if err != nil {
		return "", err
	}
	return string(data), nil
}

// shortIDForLog returns a short, log-safe form of a Claude session UUID.
func shortIDForLog(id string) string {
	if id == "" {
		return ""
	}
	if len(id) <= 16 {
		return id
	}
	return id[:8] + "..." + id[len(id)-4:]
}

// findClaudeBinary locates the claude command and returns its path.
func findClaudeBinary() (string, error) {
	paths := []string{
		"claude",
		"/opt/homebrew/bin/claude",
		"/usr/local/bin/claude",
		os.ExpandEnv("$HOME/.claude/bin/claude"),
	}
	for _, p := range paths {
		if _, err := os.Stat(p); err == nil {
			return p, nil
		}
	}
	// Last resort: rely on PATH (Stat won't find it but exec will)
	return "claude", nil
}
