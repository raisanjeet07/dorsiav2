// Command aw — Agent WebSocket CLI: talk to a running CLI Agent Gateway from the terminal.
//
// Examples (gateway must be running, e.g. go run ./cmd/server --port 8080):
//
//	aw -a claude -s my-wf-1 "Summarize the README"
//	aw -a gemini -f research -s wf-2 "What is 2+2?"   # session id = research-wf-2
//	aw -a cursor -s test1 -w /tmp/proj --no-create "hello"
//
// Flags -a / -f / -s:
//   -a  Agent / adapter (gateway flow): claude|gemini|cursor → claude-code, gemini, cursor.
//   -f  Optional use-case / workflow name; session id becomes "<f>-<s>" (e.g. research-wf-1).
//   -s  Session id (stable routing key with gateway flow on first use).
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/cli-agents-go-wrapper-service/internal/protocol"
	"github.com/gorilla/websocket"
)

func main() {
	os.Exit(run())
}

func run() int {
	var (
		wsURL    = flag.String("u", "ws://localhost:8080/ws", "gateway WebSocket URL")
		agentFl  = flag.String("a", "", "agent/adapter: claude|gemini|cursor (maps to gateway flow) (required)")
		useCase  = flag.String("f", "", "optional use case / workflow; session id becomes <f>-<s> (e.g. research)")
		session  = flag.String("s", "", "session id (required)")
		workdir  = flag.String("w", ".", "working directory for session.create")
		noCreate = flag.Bool("no-create", false, "skip session.create (session must exist)")
		rawJSON  = flag.Bool("json", false, "print raw envelope JSON lines (stdout in stream; session handshake to stderr)")
		quiet    = flag.Bool("q", false, "only print assistant-visible text to stdout (no adapter activity on stderr)")
		verbose  = flag.Bool("v", false, "verbose stderr: full tool I/O and payloads (default is summarized)")
	)
	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: %s [flags] <prompt>\n\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  Prompt is taken from arguments or stdin if no args.\n\n")
		flag.PrintDefaults()
		fmt.Fprintf(os.Stderr, "\nExample:\n  %s -a gemini -f research -s wf-1 \"Explain this repo\"\n", os.Args[0])
	}
	flag.Parse()

	if strings.TrimSpace(*agentFl) == "" || strings.TrimSpace(*session) == "" {
		fmt.Fprintln(os.Stderr, "aw: -a (agent) and -s (session) are required")
		flag.Usage()
		return 2
	}

	gatewayFlow := normalizeAdapter(strings.TrimSpace(*agentFl))

	sessID := strings.TrimSpace(*session)
	if uc := strings.TrimSpace(*useCase); uc != "" {
		sessID = strings.TrimSuffix(uc, "-") + "-" + sessID
	}

	prompt := strings.TrimSpace(strings.Join(flag.Args(), " "))
	if prompt == "" {
		b, err := io.ReadAll(os.Stdin)
		if err != nil {
			fmt.Fprintf(os.Stderr, "aw: read stdin: %v\n", err)
			return 1
		}
		prompt = strings.TrimSpace(string(b))
	}
	if prompt == "" {
		fmt.Fprintln(os.Stderr, "aw: empty prompt (pass as args or stdin)")
		return 2
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	dialer := websocket.Dialer{HandshakeTimeout: 15 * time.Second}
	conn, _, err := dialer.DialContext(ctx, *wsURL, nil)
	if err != nil {
		fmt.Fprintf(os.Stderr, "aw: dial %s: %v\n", *wsURL, err)
		return 1
	}
	defer conn.Close() //nolint:errcheck

	go func() {
		<-ctx.Done()
		_ = conn.WriteMessage(websocket.CloseMessage,
			websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""))
	}()

	if !*noCreate {
		if err := sendSessionCreate(ctx, conn, sessID, gatewayFlow, *workdir); err != nil {
			fmt.Fprintf(os.Stderr, "aw: session.create: %v\n", err)
			return 1
		}
		if err := waitForSessionCreated(ctx, conn, *rawJSON, *quiet); err != nil {
			fmt.Fprintf(os.Stderr, "aw: %v\n", err)
			return 1
		}
	}

	if err := sendPrompt(ctx, conn, sessID, gatewayFlow, prompt); err != nil {
		fmt.Fprintf(os.Stderr, "aw: prompt.send: %v\n", err)
		return 1
	}

	if err := streamResponses(ctx, conn, *rawJSON, streamOpts{quiet: *quiet, verbose: *verbose}); err != nil && ctx.Err() == nil {
		fmt.Fprintf(os.Stderr, "aw: read: %v\n", err)
		return 1
	}

	return 0
}

// normalizeAdapter maps CLI agent names to the gateway protocol flow field.
func normalizeAdapter(agent string) string {
	switch strings.ToLower(strings.TrimSpace(agent)) {
	case "claude", "claude-code":
		return "claude-code"
	case "gemini":
		return "gemini"
	case "cursor", "agent":
		return "cursor"
	default:
		return agent
	}
}

func sendSessionCreate(ctx context.Context, conn *websocket.Conn, sessionID, flow, workdir string) error {
	payload := &protocol.SessionCreatePayload{
		ConnectionMode: "spawn",
		WorkingDir:     workdir,
	}
	env, err := protocol.NewEnvelope(protocol.TypeSessionCreate, sessionID, flow, payload)
	if err != nil {
		return err
	}
	return writeEnv(conn, env)
}

func waitForSessionCreated(ctx context.Context, conn *websocket.Conn, rawJSON, quiet bool) error {
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		_, data, err := conn.ReadMessage()
		if err != nil {
			return err
		}
		var env protocol.Envelope
		if err := json.Unmarshal(data, &env); err != nil {
			return fmt.Errorf("parse message: %w", err)
		}
		if rawJSON {
			fmt.Fprintln(os.Stderr, string(data))
		}
		switch env.Type {
		case protocol.TypeSessionCreated, protocol.TypeSessionResumed:
			if !quiet && !rawJSON {
				fmt.Fprintln(os.Stderr, "→ session ready:", env.Type)
			}
			return nil
		case protocol.TypeErrorMsg:
			if env.Error != nil {
				return fmt.Errorf("gateway error: %s: %s", env.Error.Code, env.Error.Message)
			}
			return fmt.Errorf("gateway error envelope")
		default:
			if !quiet && !rawJSON {
				fmt.Fprintf(os.Stderr, "… (waiting) got %s\n", env.Type)
			}
		}
	}
}

func sendPrompt(ctx context.Context, conn *websocket.Conn, sessionID, flow, content string) error {
	payload := &protocol.PromptSendPayload{Content: content}
	env, err := protocol.NewEnvelope(protocol.TypePromptSend, sessionID, flow, payload)
	if err != nil {
		return err
	}
	return writeEnv(conn, env)
}

func streamResponses(ctx context.Context, conn *websocket.Conn, rawJSON bool, opt streamOpts) error {
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		_, data, err := conn.ReadMessage()
		if err != nil {
			if websocket.IsCloseError(err, websocket.CloseNormalClosure, websocket.CloseGoingAway) {
				return nil
			}
			return err
		}
		if rawJSON {
			fmt.Println(string(data))
			continue
		}
		var env protocol.Envelope
		if err := json.Unmarshal(data, &env); err != nil {
			fmt.Fprint(os.Stdout, string(data))
			continue
		}
		done, err := handleStreamEnvelope(&env, os.Stdout, os.Stderr, opt)
		if err != nil {
			return err
		}
		if done {
			return nil
		}
	}
}

func writeEnv(conn *websocket.Conn, env *protocol.Envelope) error {
	data, err := json.Marshal(env)
	if err != nil {
		return err
	}
	return conn.WriteMessage(websocket.TextMessage, data)
}
