// Package protocol defines the unified communication protocol between any UI
// and this gateway service. Every message flowing over WebSocket uses this envelope.
//
// Design principles:
//   - All messages share a common envelope (Envelope) for routing and correlation.
//   - Every request MUST include sessionId and flow. These two fields form the
//     immutable binding key: once a sessionId is paired with a flow (agent type),
//     that binding cannot change. Requests with a mismatched flow are rejected.
//   - The Payload field carries the type-specific data as raw JSON so we can
//     decode lazily and support forward-compatible evolution.
//   - Each CLI agent adapter translates between this protocol and the agent's
//     native format. The UI never knows which agent is behind a session.
package protocol

import (
	"encoding/json"
	"fmt"
	"time"
)

// -----------------------------------------------------------------------
// Envelope — the top-level WebSocket message wrapper
// -----------------------------------------------------------------------

// Envelope wraps every message exchanged over the WebSocket connection.
// Direction: UI ↔ Gateway (bidirectional).
//
// REQUIRED on every inbound request from the UI:
//   - SessionID: identifies the conversation/context (upstream-provided, stable)
//   - Flow:      identifies the agent type (e.g. "claude-code", "cursor", "gemini")
//
// Once a SessionID is first seen with a given Flow, that pairing is permanent.
// Subsequent requests with the same SessionID but a different Flow are rejected.
type Envelope struct {
	// ID is a unique message identifier (UUID v4). The sender generates it.
	ID string `json:"id"`

	// Type discriminates the payload kind. See MessageType constants.
	Type MessageType `json:"type"`

	// SessionID ties the message to a particular agent session. REQUIRED.
	// This is provided by the upstream caller and used as-is (not generated).
	SessionID string `json:"sessionId"`

	// Flow identifies the agent type / conversation flow. REQUIRED.
	// Immutably bound to the SessionID on first use.
	// Examples: "claude-code", "cursor", "gemini"
	Flow string `json:"flow"`

	// ReplyTo is the ID of the message this is responding to (for req/resp pairs).
	ReplyTo string `json:"replyTo,omitempty"`

	// Timestamp is when the message was created (ISO-8601 / RFC-3339).
	Timestamp time.Time `json:"timestamp"`

	// Payload carries the type-specific data. Decode with the appropriate struct
	// based on Type.
	Payload json.RawMessage `json:"payload"`

	// Error is set only when the message represents an error response.
	Error *ErrorPayload `json:"error,omitempty"`
}

// Validate checks that the mandatory routing fields are present.
func (e *Envelope) Validate() error {
	if e.ID == "" {
		return fmt.Errorf("missing required field: id")
	}
	if e.SessionID == "" {
		return fmt.Errorf("missing required field: sessionId")
	}
	if e.Flow == "" {
		return fmt.Errorf("missing required field: flow")
	}
	if e.Type == "" {
		return fmt.Errorf("missing required field: type")
	}
	return nil
}

// MessageType is a dotted string that identifies what is inside Payload.
type MessageType string

// -----------------------------------------------------------------------
// Message types — organised by domain
// -----------------------------------------------------------------------
const (
	// --- Session lifecycle ---------------------------------------------------
	TypeSessionCreate  MessageType = "session.create"
	TypeSessionCreated MessageType = "session.created"
	TypeSessionResume  MessageType = "session.resume"
	TypeSessionResumed MessageType = "session.resumed"
	TypeSessionList    MessageType = "session.list"
	TypeSessionListRes MessageType = "session.list.result"
	TypeSessionEnd     MessageType = "session.end"
	TypeSessionEnded   MessageType = "session.ended"

	// --- Chat / prompt -------------------------------------------------------
	TypePromptSend   MessageType = "prompt.send"
	TypePromptCancel MessageType = "prompt.cancel"

	// --- Streaming responses from agent --------------------------------------
	TypeStreamStart MessageType = "stream.start"
	TypeStreamDelta MessageType = "stream.delta"
	TypeStreamEnd   MessageType = "stream.end"
	TypeStreamError MessageType = "stream.error"

	// --- Tool / function calls the agent wants to execute --------------------
	TypeToolUseStart  MessageType = "tool.use.start"
	TypeToolUseResult MessageType = "tool.use.result"
	TypeToolUseEnd    MessageType = "tool.use.end"
	TypeToolApprove   MessageType = "tool.approve"
	TypeToolReject    MessageType = "tool.reject"

	// --- File system events --------------------------------------------------
	TypeFileChanged MessageType = "file.changed"
	TypeFileCreated MessageType = "file.created"
	TypeFileDeleted MessageType = "file.deleted"
	TypeFileDiff    MessageType = "file.diff"

	// --- Progress & status ---------------------------------------------------
	TypeProgress    MessageType = "progress"
	TypeAgentStatus MessageType = "agent.status"

	// --- Conversation history ------------------------------------------------
	TypeHistoryRequest MessageType = "history.request"
	TypeHistoryResult  MessageType = "history.result"

	// --- Agent capabilities --------------------------------------------------
	TypeCapabilities MessageType = "capabilities"

	// --- Modes ---------------------------------------------------------------
	TypeModesList       MessageType = "modes.list"
	TypeModesListResult MessageType = "modes.list.result"

	// --- Skills --------------------------------------------------------------
	TypeSkillList     MessageType = "skill.list"
	TypeSkillListRes  MessageType = "skill.list.result"
	TypeSkillAttach   MessageType = "skill.attach"
	TypeSkillAttached MessageType = "skill.attached"
	TypeSkillDetach   MessageType = "skill.detach"
	TypeSkillDetached MessageType = "skill.detached"

	// --- MCPs ----------------------------------------------------------------
	TypeMCPList     MessageType = "mcp.list"
	TypeMCPListRes  MessageType = "mcp.list.result"
	TypeMCPAttach   MessageType = "mcp.attach"
	TypeMCPAttached MessageType = "mcp.attached"
	TypeMCPDetach   MessageType = "mcp.detach"
	TypeMCPDetached MessageType = "mcp.detached"

	// --- Errors --------------------------------------------------------------
	TypeErrorMsg MessageType = "error"
)

// -----------------------------------------------------------------------
// Payload structs
// -----------------------------------------------------------------------

// ErrorPayload describes an error.
type ErrorPayload struct {
	Code    string `json:"code"`
	Message string `json:"message"`
	Details any    `json:"details,omitempty"`
}

// SessionCreatePayload is sent by the UI to create a new agent session.
// The sessionId and flow are already on the Envelope — this carries
// the additional configuration needed to spin up the agent.
type SessionCreatePayload struct {
	// ConnectionMode is "spawn" (start a new process) or "connect" (attach to existing).
	ConnectionMode string `json:"connectionMode"`

	// WorkingDir is the directory the agent should operate in.
	WorkingDir string `json:"workingDir,omitempty"`

	// ConnectAddress is used when ConnectionMode == "connect". Agent-specific.
	ConnectAddress string `json:"connectAddress,omitempty"`

	// Model override (e.g. "claude-sonnet-4-20250514", "gemini-2.5-pro").
	Model string `json:"model,omitempty"`

	// Extra agent-specific configuration.
	Config map[string]any `json:"config,omitempty"`
}

// SessionCreatedPayload confirms a session was created or resumed.
type SessionCreatedPayload struct {
	SessionID    string        `json:"sessionId"`
	Flow         string        `json:"flow"`
	Status       string        `json:"status"` // "created", "resumed", "reconnected"
	Capabilities *Capabilities `json:"capabilities,omitempty"`
}

// SessionResumePayload requests re-attaching to an existing session.
// SessionID and Flow are on the envelope — this is intentionally empty
// but kept for future extension.
type SessionResumePayload struct{}

// SessionListPayload is an empty request to list sessions.
type SessionListPayload struct{}

// SessionListResult returns known sessions.
type SessionListResult struct {
	Sessions []SessionInfo `json:"sessions"`
}

// SessionInfo describes a session.
type SessionInfo struct {
	SessionID  string    `json:"sessionId"`
	Flow       string    `json:"flow"`
	Status     string    `json:"status"` // "running", "stopped", "error"
	CreatedAt  time.Time `json:"createdAt"`
	WorkingDir string    `json:"workingDir,omitempty"`
}

// PromptSendPayload carries the user's message to the agent.
type PromptSendPayload struct {
	// Content is the text prompt.
	Content string `json:"content"`

	// Attachments lists files or images to include.
	Attachments []Attachment `json:"attachments,omitempty"`

	// Options lets the UI pass agent-specific flags.
	Options map[string]any `json:"options,omitempty"`
}

// Attachment is a file or image sent with a prompt.
type Attachment struct {
	Type     string `json:"type"` // "file", "image", "url"
	Name     string `json:"name"`
	Content  string `json:"content,omitempty"`  // base64 or text
	MimeType string `json:"mimeType,omitempty"`
	Path     string `json:"path,omitempty"`
}

// StreamDeltaPayload is a chunk of streaming output from the agent.
type StreamDeltaPayload struct {
	// ContentType differentiates text, markdown, code, thinking, etc.
	ContentType string `json:"contentType"` // "text", "markdown", "code", "thinking", "tool_input"
	Content     string `json:"content"`
	// Role is "assistant" or "system".
	Role string `json:"role,omitempty"`
}

// StreamEndPayload signals the end of a streamed response.
type StreamEndPayload struct {
	// FinishReason: "complete", "cancelled", "error", "max_tokens"
	FinishReason string     `json:"finishReason"`
	Usage        *UsageInfo `json:"usage,omitempty"`
}

// UsageInfo tracks token/cost metrics.
type UsageInfo struct {
	InputTokens  int     `json:"inputTokens,omitempty"`
	OutputTokens int     `json:"outputTokens,omitempty"`
	TotalCost    float64 `json:"totalCost,omitempty"`
}

// ToolUseStartPayload notifies the UI that the agent wants to use a tool.
type ToolUseStartPayload struct {
	ToolID   string         `json:"toolId"`
	ToolName string         `json:"toolName"`
	Input    map[string]any `json:"input,omitempty"`
}

// ToolUseResultPayload sends the result of a tool execution.
type ToolUseResultPayload struct {
	ToolID  string `json:"toolId"`
	Output  string `json:"output,omitempty"`
	IsError bool   `json:"isError,omitempty"`
}

// ToolApprovePayload is sent by the UI to approve a pending tool call.
type ToolApprovePayload struct {
	ToolID string `json:"toolId"`
}

// ToolRejectPayload is sent by the UI to reject a pending tool call.
type ToolRejectPayload struct {
	ToolID string `json:"toolId"`
	Reason string `json:"reason,omitempty"`
}

// FileEventPayload describes a file-system event from the agent.
type FileEventPayload struct {
	Path    string `json:"path"`
	Diff    string `json:"diff,omitempty"`
	Content string `json:"content,omitempty"`
	Lang    string `json:"lang,omitempty"`
}

// ProgressPayload reports progress on a long-running operation.
type ProgressPayload struct {
	TaskID     string  `json:"taskId,omitempty"`
	Message    string  `json:"message"`
	Percentage float64 `json:"percentage,omitempty"` // 0-100, -1 = indeterminate
}

// AgentStatusPayload reports the agent's current state.
type AgentStatusPayload struct {
	Status  string `json:"status"` // "idle", "thinking", "tool_use", "error"
	Message string `json:"message,omitempty"`
}

// Capabilities tells the UI what this agent supports.
type Capabilities struct {
	AgentType       string   `json:"agentType"`
	SupportsTools   bool     `json:"supportsTools"`
	SupportsFiles   bool     `json:"supportsFiles"`
	SupportsImages  bool     `json:"supportsImages"`
	SupportsDiff    bool     `json:"supportsDiff"`
	SupportsHistory bool     `json:"supportsHistory"`
	SupportedModels []string `json:"supportedModels,omitempty"`
	MaxTokens       int      `json:"maxTokens,omitempty"`
	// Extra agent-specific capabilities.
	Extra map[string]any `json:"extra,omitempty"`
}

// HistoryRequestPayload asks for conversation history.
type HistoryRequestPayload struct {
	Limit  int    `json:"limit,omitempty"`
	Before string `json:"before,omitempty"` // message ID cursor
}

// HistoryResultPayload returns conversation history.
type HistoryResultPayload struct {
	Messages []HistoryMessage `json:"messages"`
	HasMore  bool             `json:"hasMore"`
}

// HistoryMessage is a single turn in conversation history.
type HistoryMessage struct {
	ID        string               `json:"id"`
	Role      string               `json:"role"` // "user", "assistant", "system", "tool"
	Content   string               `json:"content"`
	Timestamp time.Time            `json:"timestamp"`
	ToolUse   *ToolUseStartPayload `json:"toolUse,omitempty"`
}

// -----------------------------------------------------------------------
// Modes payloads — protocol-layer mirror of agent.AgentMode
// -----------------------------------------------------------------------

// ModeInfo is the protocol-layer representation of an agent operating mode.
// It mirrors agent.AgentMode field-for-field to avoid a circular import
// between internal/protocol and internal/agent.
type ModeInfo struct {
	Name        string `json:"name"`
	Description string `json:"description,omitempty"`
	Default     bool   `json:"default,omitempty"`
}

// ModesListPayload is an empty client request — the sessionId+flow on the
// envelope already identify which agent's modes to return.
type ModesListPayload struct{}

// ModesListResultPayload returns the modes available for the session's agent.
type ModesListResultPayload struct {
	AgentName string     `json:"agentName"`
	Modes     []ModeInfo `json:"modes"`
}

// -----------------------------------------------------------------------
// Skill payloads
// -----------------------------------------------------------------------

// SkillInfo is the protocol-layer representation of a Skill.
type SkillInfo struct {
	Name        string `json:"name"`
	Scope       string `json:"scope"` // "global" or agent name
	Description string `json:"description,omitempty"`
	Prompt      string `json:"prompt"`
}

// SkillListPayload is an empty request — session context determines which
// skills are visible (global + agent-scoped).
type SkillListPayload struct{}

// SkillListResultPayload returns the skills visible to a session, including
// globally scoped skills and agent-specific ones, annotated with attachment status.
type SkillListResultPayload struct {
	Skills []SkillStatus `json:"skills"`
}

// SkillStatus wraps a skill with a flag indicating whether it is currently
// attached to the requesting session.
type SkillStatus struct {
	SkillInfo
	Attached bool `json:"attached"`
}

// SkillAttachPayload asks the gateway to attach a registered skill to the session.
type SkillAttachPayload struct {
	SkillName string `json:"skillName"`
}

// SkillAttachedPayload confirms a skill was successfully attached.
type SkillAttachedPayload struct {
	SkillName string `json:"skillName"`
}

// SkillDetachPayload asks the gateway to detach a skill from the session.
type SkillDetachPayload struct {
	SkillName string `json:"skillName"`
}

// SkillDetachedPayload confirms a skill was successfully detached.
type SkillDetachedPayload struct {
	SkillName string `json:"skillName"`
}

// -----------------------------------------------------------------------
// MCP payloads
// -----------------------------------------------------------------------

// MCPServerInfo is the protocol-layer representation of an MCPServer.
type MCPServerInfo struct {
	Name    string            `json:"name"`
	Scope   string            `json:"scope"`
	Type    string            `json:"type"`
	Command string            `json:"command,omitempty"`
	Args    []string          `json:"args,omitempty"`
	URL     string            `json:"url,omitempty"`
	Env     map[string]string `json:"env,omitempty"`
}

// MCPListPayload is an empty request.
type MCPListPayload struct{}

// MCPListResultPayload returns MCP server configs visible to a session,
// annotated with attachment status.
type MCPListResultPayload struct {
	MCPs []MCPStatus `json:"mcps"`
}

// MCPStatus wraps an MCPServerInfo with a flag indicating attachment.
type MCPStatus struct {
	MCPServerInfo
	Attached bool `json:"attached"`
}

// MCPAttachPayload asks the gateway to attach a registered MCP server to the session.
type MCPAttachPayload struct {
	MCPName string `json:"mcpName"`
}

// MCPAttachedPayload confirms an MCP server was successfully attached.
type MCPAttachedPayload struct {
	MCPName string `json:"mcpName"`
}

// MCPDetachPayload asks the gateway to detach an MCP server from the session.
type MCPDetachPayload struct {
	MCPName string `json:"mcpName"`
}

// MCPDetachedPayload confirms an MCP server was successfully detached.
type MCPDetachedPayload struct {
	MCPName string `json:"mcpName"`
}
