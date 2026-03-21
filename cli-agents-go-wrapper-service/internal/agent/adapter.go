// Package agent defines the adapter interface that every CLI agent must implement
// and provides a registry for discovering adapters at runtime.
//
// To add support for a new CLI agent:
//  1. Create a new package under internal/agent/<name>/
//  2. Implement the Adapter interface
//  3. Call RegisterAdapter() in an init() function
package agent

import (
	"context"
	"fmt"
	"sync"

	"github.com/cli-agents-go-wrapper-service/internal/protocol"
)

// -----------------------------------------------------------------------
// Domain types — Modes, Skills, MCPs
// -----------------------------------------------------------------------

// AgentMode describes one operating mode an agent supports.
// Modes control permission levels, sandboxing, and autonomy settings.
type AgentMode struct {
	// Name is the mode identifier (e.g. "default", "bypassPermissions", "plan").
	Name string `json:"name"`

	// Description is a human-readable explanation of the mode.
	Description string `json:"description,omitempty"`

	// Default reports whether this is the agent's out-of-the-box mode.
	Default bool `json:"default,omitempty"`
}

// Skill is a named, reusable prompt fragment that is injected into a session
// as an additional system prompt. Skills can be scoped "global" (available to
// every agent) or scoped to a specific agent name (e.g. "claude-code").
type Skill struct {
	Name        string `json:"name"`
	Scope       string `json:"scope"`             // "global" or agent name
	Description string `json:"description,omitempty"`
	Prompt      string `json:"prompt"`            // system prompt text to inject
}

// MCPServerType identifies the transport protocol for an MCP server.
type MCPServerType string

const (
	MCPServerTypeStdio MCPServerType = "stdio" // subprocess via stdin/stdout
	MCPServerTypeSSE   MCPServerType = "sse"   // HTTP Server-Sent Events
	MCPServerTypeHTTP  MCPServerType = "http"  // plain HTTP
)

// MCPServer is a Model Context Protocol server configuration that can be
// attached to a session and passed to the underlying agent CLI.
// Scope is "global" or an agent name.
type MCPServer struct {
	Name    string            `json:"name"`
	Scope   string            `json:"scope"`
	Type    MCPServerType     `json:"type"`              // "stdio", "sse", "http"
	Command string            `json:"command,omitempty"` // for stdio: binary to run
	Args    []string          `json:"args,omitempty"`    // for stdio: arguments
	URL     string            `json:"url,omitempty"`     // for sse/http: endpoint
	Env     map[string]string `json:"env,omitempty"`     // extra env vars
}

// -----------------------------------------------------------------------
// Auth types
// -----------------------------------------------------------------------

// AuthStatus is the result of an authentication check.
type AuthStatus struct {
	// LoggedIn is true when the agent's credentials are valid and present.
	LoggedIn bool `json:"loggedIn"`

	// Detail is an optional human-readable message (e.g. logged-in account email,
	// or the reason the check failed).
	Detail string `json:"detail,omitempty"`
}

// LoginFlow describes an in-progress login initiated by the agent CLI.
type LoginFlow struct {
	// URL is the browser URL the user must visit to complete authentication.
	URL string `json:"url"`

	// Done receives nil when login completes successfully, or an error on failure.
	// May be nil for agents that do not signal completion programmatically.
	Done <-chan error `json:"-"`
}

// Authenticator is an optional interface that adapters may implement to support
// authentication checking and login flows. Use agent.AsAuthenticator() to test
// whether an adapter supports it.
type Authenticator interface {
	// CheckAuth checks whether the agent is currently authenticated.
	// It must be fast — implementations should read local credential files
	// or run a lightweight CLI sub-command.
	CheckAuth(ctx context.Context) (*AuthStatus, error)

	// Login initiates a login flow and returns a LoginFlow whose URL field
	// contains the browser URL the user should open. The returned Done channel
	// (if non-nil) will receive the result when the CLI confirms completion.
	Login(ctx context.Context) (*LoginFlow, error)
}

// AsAuthenticator returns (a, true) if the adapter implements Authenticator.
func AsAuthenticator(a Adapter) (Authenticator, bool) {
	auth, ok := a.(Authenticator)
	return auth, ok
}

// -----------------------------------------------------------------------
// ModelLister — optional dynamic model discovery
// -----------------------------------------------------------------------

// ModelLister is an optional interface adapters can implement to provide a
// live list of available models fetched from the agent's API or CLI.
// Adapters that do not implement it advertise no models (empty list).
type ModelLister interface {
	ListModels(ctx context.Context) ([]string, error)
}

// AsModelLister returns (a, true) if the adapter implements ModelLister.
func AsModelLister(a Adapter) (ModelLister, bool) {
	ml, ok := a.(ModelLister)
	return ml, ok
}

// -----------------------------------------------------------------------
// Core adapter interface
// -----------------------------------------------------------------------

// Adapter is the contract every CLI agent must satisfy.
// The gateway uses this interface exclusively — it never speaks
// agent-native protocols directly.
type Adapter interface {
	// Name returns the agent identifier (e.g. "claude-code", "cursor", "gemini").
	Name() string

	// Capabilities returns what this agent supports so the UI can adapt.
	Capabilities() *protocol.Capabilities

	// Modes returns the operating modes this agent supports (e.g. permission
	// levels for Claude Code, sandbox mode for Gemini). Returns nil if the
	// agent has no configurable modes.
	Modes() []AgentMode

	// Start initialises the agent. For "spawn" mode it launches the process;
	// for "connect" mode it dials an existing instance.
	Start(ctx context.Context, opts StartOptions) error

	// Stop gracefully shuts down the agent and cleans up resources.
	Stop(ctx context.Context) error

	// SendPrompt sends a user message and streams the response back
	// through the provided EventSink.
	SendPrompt(ctx context.Context, prompt *protocol.PromptSendPayload, sink EventSink) error

	// CancelPrompt aborts the current in-flight request if supported.
	CancelPrompt(ctx context.Context) error

	// ApproveToolUse tells the agent the user approved a tool call.
	ApproveToolUse(ctx context.Context, toolID string) error

	// RejectToolUse tells the agent the user rejected a tool call.
	RejectToolUse(ctx context.Context, toolID string, reason string) error

	// GetHistory returns past conversation turns if the agent supports it.
	GetHistory(ctx context.Context, req *protocol.HistoryRequestPayload) (*protocol.HistoryResultPayload, error)

	// IsRunning reports whether the agent process/connection is alive.
	IsRunning() bool

	// --- Skill attachment (per-session) ------------------------------------

	// AttachSkill adds a skill to this adapter's session. Idempotent by name.
	// Attached skills are injected as system prompt extensions on the next prompt.
	AttachSkill(s Skill)

	// DetachSkill removes an attached skill by name.
	// Returns false if the skill was not attached.
	DetachSkill(name string) bool

	// AttachedSkills returns a snapshot of the currently attached skills.
	AttachedSkills() []Skill

	// --- MCP attachment (per-session) -------------------------------------

	// AttachMCP adds an MCP server config to this adapter's session.
	// Idempotent by name. Attached MCPs are passed to the agent on the next spawn.
	AttachMCP(m MCPServer)

	// DetachMCP removes an attached MCP server config by name.
	// Returns false if the MCP was not attached.
	DetachMCP(name string) bool

	// AttachedMCPs returns a snapshot of the currently attached MCP server configs.
	AttachedMCPs() []MCPServer
}

// StartOptions are passed to Adapter.Start().
type StartOptions struct {
	// ConnectionMode is "spawn" or "connect".
	ConnectionMode string

	// WorkingDir for the agent process (spawn mode).
	WorkingDir string

	// ConnectAddress for connecting to an existing agent (connect mode).
	ConnectAddress string

	// Model override.
	Model string

	// Extra agent-specific key/value config.
	Config map[string]any

	// SessionID and Flow are the gateway routing key (immutable per session).
	// Adapters may derive stable CLI session UUIDs via AdapterSessionUUID(SessionID, Flow).
	// Not sent in session.create JSON — set only by the session manager.
	SessionID string `json:"-"`
	Flow      string `json:"-"`
}

// -----------------------------------------------------------------------
// EventSink — how adapters push events back to the gateway
// -----------------------------------------------------------------------

// EventSink receives translated events from an adapter. The gateway
// wires this to the WebSocket writer for the correct session.
type EventSink interface {
	// Emit sends a protocol event to the UI.
	Emit(msgType protocol.MessageType, payload any) error

	// EmitError sends an error event.
	EmitError(code, message string)

	// SessionID returns the session this sink belongs to.
	SessionID() string
}

// -----------------------------------------------------------------------
// Adapter factory & registry
// -----------------------------------------------------------------------

// AdapterFactory creates a new Adapter instance. Called once per session.
type AdapterFactory func() Adapter

var (
	registryMu sync.RWMutex
	registry   = map[string]AdapterFactory{}
)

// RegisterAdapter makes an adapter available by name.
// Typically called from init() in each adapter package.
func RegisterAdapter(name string, factory AdapterFactory) {
	registryMu.Lock()
	defer registryMu.Unlock()
	if _, exists := registry[name]; exists {
		panic(fmt.Sprintf("agent adapter %q already registered", name))
	}
	registry[name] = factory
}

// NewAdapter creates an adapter by name. Returns an error if unknown.
func NewAdapter(name string) (Adapter, error) {
	registryMu.RLock()
	defer registryMu.RUnlock()
	factory, ok := registry[name]
	if !ok {
		return nil, fmt.Errorf("unknown agent type %q; registered: %v", name, RegisteredAdapters())
	}
	return factory(), nil
}

// RegisteredAdapters returns the names of all registered adapters.
func RegisteredAdapters() []string {
	registryMu.RLock()
	defer registryMu.RUnlock()
	names := make([]string, 0, len(registry))
	for name := range registry {
		names = append(names, name)
	}
	return names
}
