// Package ws implements the WebSocket server that UI clients connect to.
// It routes incoming protocol messages to the correct session/adapter and
// streams agent events back to the client.
//
// Routing invariant: every inbound message MUST carry sessionId + flow.
// The hub validates these before dispatching to any handler.
package ws

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"sync"
	"time"

	"github.com/cli-agents-go-wrapper-service/internal/agent"
	authpkg "github.com/cli-agents-go-wrapper-service/internal/auth"
	"github.com/cli-agents-go-wrapper-service/internal/mcp"
	"github.com/cli-agents-go-wrapper-service/internal/protocol"
	"github.com/cli-agents-go-wrapper-service/internal/session"
	"github.com/cli-agents-go-wrapper-service/internal/skill"
	"github.com/cli-agents-go-wrapper-service/internal/workspacefile"
	"github.com/gorilla/websocket"
)

// Skill and MCP registries are held on Hub so session-level HTTP handlers
// can be wired through the same registries used at the global level.
// The hub itself does not dispatch skill/mcp WS messages — those are HTTP-only.

const (
	writeWait      = 10 * time.Second
	pongWait       = 60 * time.Second
	pingPeriod     = (pongWait * 9) / 10
	maxMessageSize = 10 * 1024 * 1024 // 10 MB
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  4096,
	WriteBufferSize: 4096,
	CheckOrigin:     func(r *http.Request) bool { return true }, // TODO: restrict in production
}

// Hub manages all connected WebSocket clients.
type Hub struct {
	sessions *session.Manager
	skills   *skill.Registry
	mcps     *mcp.Registry
	authMgr  *authpkg.Manager
	logger   *slog.Logger
	// workspace, when non-nil, provisions per-session working dirs via workspace-file-service
	// before starting an agent (session.create).
	workspace *workspacefile.Client

	mu      sync.RWMutex
	clients map[*Client]struct{}
}

// NewHub creates a Hub with the given session manager, skill registry, MCP registry, and auth manager.
// workspace may be nil; when set, session.create calls workspace-file-service to set workingDir.
func NewHub(sessions *session.Manager, skills *skill.Registry, mcps *mcp.Registry, authMgr *authpkg.Manager, logger *slog.Logger, workspace *workspacefile.Client) *Hub {
	return &Hub{
		sessions:  sessions,
		skills:    skills,
		mcps:      mcps,
		authMgr:   authMgr,
		logger:    logger,
		workspace: workspace,
		clients:   make(map[*Client]struct{}),
	}
}

// ServeHTTP upgrades the HTTP connection to WebSocket and registers the client.
func (h *Hub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		h.logger.Error("websocket upgrade failed", "error", err)
		return
	}

	client := &Client{
		hub:    h,
		conn:   conn,
		send:   make(chan []byte, 4096),
		sinks:  make(map[string]*clientSink),
		logger: h.logger,
	}

	h.mu.Lock()
	h.clients[client] = struct{}{}
	h.mu.Unlock()

	h.logger.Info("client connected", "remote", r.RemoteAddr)

	go client.writePump()
	go client.readPump()
}

// RemoveClient unregisters a client.
func (h *Hub) RemoveClient(c *Client) {
	h.mu.Lock()
	delete(h.clients, c)
	h.mu.Unlock()
}

// -----------------------------------------------------------------------
// Client — one WebSocket connection
// -----------------------------------------------------------------------

// Client represents a single connected UI.
type Client struct {
	hub    *Hub
	conn   *websocket.Conn
	send   chan []byte
	sinks  map[string]*clientSink // sessionID -> sink
	sinkMu sync.RWMutex
	logger *slog.Logger
}

func (c *Client) readPump() {
	defer func() {
		c.hub.RemoveClient(c)
		c.conn.Close()
	}()

	c.conn.SetReadLimit(maxMessageSize)
	_ = c.conn.SetReadDeadline(time.Now().Add(pongWait))
	c.conn.SetPongHandler(func(string) error {
		return c.conn.SetReadDeadline(time.Now().Add(pongWait))
	})

	for {
		_, message, err := c.conn.ReadMessage()
		if err != nil {
			// 1006 = abnormal closure: peer closed TCP without a WebSocket close frame (common for CLIs, Ctrl+C).
			var ce *websocket.CloseError
			if errors.As(err, &ce) && ce.Code == websocket.CloseAbnormalClosure {
				c.logger.Debug("websocket client disconnected", "code", ce.Code, "detail", "abnormal closure (EOF without close frame)")
				return
			}
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
				c.logger.Warn("websocket read error", "error", err)
			}
			return
		}
		c.handleMessage(message)
	}
}

func (c *Client) writePump() {
	ticker := time.NewTicker(pingPeriod)
	defer func() {
		ticker.Stop()
		c.conn.Close()
	}()

	for {
		select {
		case msg, ok := <-c.send:
			_ = c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if !ok {
				_ = c.conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}
			if err := c.conn.WriteMessage(websocket.TextMessage, msg); err != nil {
				return
			}
		case <-ticker.C:
			_ = c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if err := c.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}

// sendEnvelope marshals and queues an envelope for sending (blocks under backpressure — no silent drops).
func (c *Client) sendEnvelope(env *protocol.Envelope) {
	data, err := json.Marshal(env)
	if err != nil {
		c.logger.Error("failed to marshal envelope", "error", err)
		return
	}
	c.send <- data
}

// handleMessage validates the envelope and dispatches to the correct handler.
func (c *Client) handleMessage(data []byte) {
	var env protocol.Envelope
	if err := json.Unmarshal(data, &env); err != nil {
		c.sendEnvelope(protocol.NewError("", "", "", "PARSE_ERROR", "invalid message format"))
		return
	}

	// ── Mandatory field validation ──────────────────────────────────────
	if err := env.Validate(); err != nil {
		c.sendEnvelope(protocol.NewError(env.SessionID, env.Flow, env.ID, "VALIDATION_ERROR", err.Error()))
		return
	}

	c.logger.Debug("message received",
		"type", env.Type,
		"sessionId", env.SessionID,
		"flow", env.Flow,
	)

	// ── Dispatch ────────────────────────────────────────────────────────
	switch env.Type {
	case protocol.TypeSessionCreate:
		c.handleSessionCreate(&env)
	case protocol.TypeSessionList:
		c.handleSessionList(&env)
	case protocol.TypeSessionEnd:
		c.handleSessionEnd(&env)
	case protocol.TypeSessionResume:
		c.handleSessionResume(&env)
	case protocol.TypePromptSend:
		c.handlePromptSend(&env)
	case protocol.TypePromptCancel:
		c.handlePromptCancel(&env)
	case protocol.TypeToolApprove:
		c.handleToolApprove(&env)
	case protocol.TypeToolReject:
		c.handleToolReject(&env)
	case protocol.TypeHistoryRequest:
		c.handleHistoryRequest(&env)
	default:
		c.sendEnvelope(protocol.NewError(env.SessionID, env.Flow, env.ID, "UNKNOWN_TYPE",
			"unrecognized message type: "+string(env.Type)))
	}
}

// -----------------------------------------------------------------------
// Handler implementations
// -----------------------------------------------------------------------

func (c *Client) handleSessionCreate(env *protocol.Envelope) {
	payload, err := protocol.DecodePayload[protocol.SessionCreatePayload](env)
	if err != nil {
		c.sendEnvelope(protocol.NewError(env.SessionID, env.Flow, env.ID, "INVALID_PAYLOAD", err.Error()))
		return
	}

	// Check authentication before starting the agent.
	// We create a temporary adapter instance just for the auth check — the
	// real adapter is created inside Resolve().
	if tmpAdapter, adErr := agent.NewAdapter(env.Flow); adErr == nil {
		if authErr := c.hub.authMgr.EnsureAuth(context.Background(), env.Flow, tmpAdapter); authErr != nil {
			var authRequired *authpkg.ErrAuthRequired
			if errors.As(authErr, &authRequired) {
				c.sendEnvelope(protocol.NewError(env.SessionID, env.Flow, env.ID, "AUTH_REQUIRED", authErr.Error()))
				return
			}
			// Non-auth errors: log and continue (don't block session create).
			c.logger.Warn("auth check error", "agent", env.Flow, "error", authErr)
		}
	}

	// Optional: provision per-session directory via workspace-file-service and use it as workingDir.
	if c.hub.workspace != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		path, werr := c.hub.workspace.EnsureWorkspace(ctx, env.SessionID)
		cancel()
		if werr != nil {
			c.sendEnvelope(protocol.NewError(env.SessionID, env.Flow, env.ID, "WORKSPACE_SERVICE_FAILED", werr.Error()))
			return
		}
		if payload.WorkingDir != "" && payload.WorkingDir != path {
			c.logger.Debug("overriding client workingDir with workspace-file-service path",
				"sessionId", env.SessionID, "clientWorkingDir", payload.WorkingDir, "workspacePath", path)
		}
		payload.WorkingDir = path
	}

	c.logger.Info("agent working directory",
		"sessionId", env.SessionID,
		"flow", env.Flow,
		"workingDir", payload.WorkingDir,
		"workspaceFromService", c.hub.workspace != nil,
	)

	// Resolve handles create-if-new, flow-match-if-existing, and auto-resume.
	sess, status, err := c.hub.sessions.Resolve(context.Background(), env.SessionID, env.Flow, payload)
	if err != nil {
		c.sendEnvelope(protocol.NewError(env.SessionID, env.Flow, env.ID, "SESSION_CREATE_FAILED", err.Error()))
		return
	}

	// Register the event sink for this session.
	sink := &clientSink{client: c, sessionID: sess.ID, flow: sess.Flow}
	c.sinkMu.Lock()
	c.sinks[sess.ID] = sink
	c.sinkMu.Unlock()

	resp, _ := protocol.NewReply(env, protocol.TypeSessionCreated, &protocol.SessionCreatedPayload{
		SessionID:    sess.ID,
		Flow:         sess.Flow,
		Status:       status,
		Capabilities: sess.Adapter.Capabilities(),
	})
	c.sendEnvelope(resp)
}

func (c *Client) handleSessionList(env *protocol.Envelope) {
	sessions := c.hub.sessions.List()
	resp, _ := protocol.NewReply(env, protocol.TypeSessionListRes, &protocol.SessionListResult{
		Sessions: sessions,
	})
	c.sendEnvelope(resp)
}

func (c *Client) handleSessionEnd(env *protocol.Envelope) {
	// Validate flow binding before allowing end.
	if _, err := c.hub.sessions.ValidateFlow(env.SessionID, env.Flow); err != nil {
		c.sendEnvelope(protocol.NewError(env.SessionID, env.Flow, env.ID, "FLOW_MISMATCH", err.Error()))
		return
	}

	if err := c.hub.sessions.End(env.SessionID); err != nil {
		c.sendEnvelope(protocol.NewError(env.SessionID, env.Flow, env.ID, "SESSION_END_FAILED", err.Error()))
		return
	}

	c.sinkMu.Lock()
	delete(c.sinks, env.SessionID)
	c.sinkMu.Unlock()

	resp, _ := protocol.NewReply(env, protocol.TypeSessionEnded, nil)
	c.sendEnvelope(resp)
}

func (c *Client) handleSessionResume(env *protocol.Envelope) {
	// Resolve with nil createPayload — it will auto-resume if process is dead,
	// or return the existing session if alive. Rejects flow mismatches.
	sess, status, err := c.hub.sessions.Resolve(context.Background(), env.SessionID, env.Flow, nil)
	if err != nil {
		c.sendEnvelope(protocol.NewError(env.SessionID, env.Flow, env.ID, "SESSION_RESUME_FAILED", err.Error()))
		return
	}

	sink := &clientSink{client: c, sessionID: sess.ID, flow: sess.Flow}
	c.sinkMu.Lock()
	c.sinks[sess.ID] = sink
	c.sinkMu.Unlock()

	resp, _ := protocol.NewReply(env, protocol.TypeSessionResumed, &protocol.SessionCreatedPayload{
		SessionID:    sess.ID,
		Flow:         sess.Flow,
		Status:       status,
		Capabilities: sess.Adapter.Capabilities(),
	})
	c.sendEnvelope(resp)
}

// resolveForAction is a helper that validates flow, resolves the session
// (with auto-resume), and returns it. Used by prompt/tool/history handlers.
func (c *Client) resolveForAction(env *protocol.Envelope) (*session.Session, bool) {
	sess, _, err := c.hub.sessions.Resolve(context.Background(), env.SessionID, env.Flow, nil)
	if err != nil {
		c.sendEnvelope(protocol.NewError(env.SessionID, env.Flow, env.ID, "SESSION_ERROR", err.Error()))
		return nil, false
	}
	return sess, true
}

func (c *Client) handlePromptSend(env *protocol.Envelope) {
	sess, ok := c.resolveForAction(env)
	if !ok {
		return
	}

	payload, err := protocol.DecodePayload[protocol.PromptSendPayload](env)
	if err != nil {
		c.sendEnvelope(protocol.NewError(env.SessionID, env.Flow, env.ID, "INVALID_PAYLOAD", err.Error()))
		return
	}

	replyTo := env.ID
	sink := &clientSink{
		client:    c,
		sessionID: sess.ID,
		flow:      sess.Flow,
		replyTo:   replyTo,
	}

	// Run prompt async so we don't block the read pump; serialize prompts per session.
	go func() {
		sess.PromptLock()
		defer sess.PromptUnlock()

		pctx, pcancel := context.WithCancel(sess.Context())
		sess.SetActivePromptCancel(pcancel)
		defer func() {
			pcancel()
			sess.ClearActivePromptCancel()
		}()

		if err := sess.Adapter.SendPrompt(pctx, payload, sink); err != nil {
			sink.EmitError("PROMPT_FAILED", err.Error())
		}
	}()
}

func (c *Client) handlePromptCancel(env *protocol.Envelope) {
	sess, ok := c.resolveForAction(env)
	if !ok {
		return
	}
	sess.CancelActivePrompt()
	_ = sess.Adapter.CancelPrompt(sess.Context())
}

func (c *Client) handleToolApprove(env *protocol.Envelope) {
	sess, ok := c.resolveForAction(env)
	if !ok {
		return
	}
	payload, err := protocol.DecodePayload[protocol.ToolApprovePayload](env)
	if err != nil {
		return
	}
	_ = sess.Adapter.ApproveToolUse(sess.Context(), payload.ToolID)
}

func (c *Client) handleToolReject(env *protocol.Envelope) {
	sess, ok := c.resolveForAction(env)
	if !ok {
		return
	}
	payload, err := protocol.DecodePayload[protocol.ToolRejectPayload](env)
	if err != nil {
		return
	}
	_ = sess.Adapter.RejectToolUse(sess.Context(), payload.ToolID, payload.Reason)
}

func (c *Client) handleHistoryRequest(env *protocol.Envelope) {
	sess, ok := c.resolveForAction(env)
	if !ok {
		return
	}

	payload, err := protocol.DecodePayload[protocol.HistoryRequestPayload](env)
	if err != nil {
		c.sendEnvelope(protocol.NewError(env.SessionID, env.Flow, env.ID, "INVALID_PAYLOAD", err.Error()))
		return
	}

	result, err := sess.Adapter.GetHistory(sess.Context(), payload)
	if err != nil {
		c.sendEnvelope(protocol.NewError(env.SessionID, env.Flow, env.ID, "HISTORY_FAILED", err.Error()))
		return
	}

	resp, _ := protocol.NewReply(env, protocol.TypeHistoryResult, result)
	c.sendEnvelope(resp)
}

// -----------------------------------------------------------------------
// clientSink — bridges adapter events to the WebSocket client
// -----------------------------------------------------------------------

type clientSink struct {
	client    *Client
	sessionID string
	flow      string
	replyTo   string // inbound prompt.send envelope id; attached to streaming events
}

func (s *clientSink) Emit(msgType protocol.MessageType, payload any) error {
	var (
		env *protocol.Envelope
		err error
	)
	if s.replyTo != "" {
		env, err = protocol.NewEnvelopeWithReplyTo(msgType, s.sessionID, s.flow, s.replyTo, payload)
	} else {
		env, err = protocol.NewEnvelope(msgType, s.sessionID, s.flow, payload)
	}
	if err != nil {
		return err
	}
	s.client.sendEnvelope(env)
	return nil
}

func (s *clientSink) EmitError(code, message string) {
	env := protocol.NewError(s.sessionID, s.flow, s.replyTo, code, message)
	s.client.sendEnvelope(env)
}

func (s *clientSink) SessionID() string {
	return s.sessionID
}

// Ensure clientSink satisfies agent.EventSink.
var _ agent.EventSink = (*clientSink)(nil)
