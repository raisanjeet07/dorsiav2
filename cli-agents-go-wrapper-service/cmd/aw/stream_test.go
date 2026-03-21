package main

import (
	"bytes"
	"encoding/json"
	"testing"

	"github.com/cli-agents-go-wrapper-service/internal/protocol"
)

func TestIsAssistantVisibleContentType(t *testing.T) {
	t.Parallel()
	for _, tc := range []struct {
		ct   string
		want bool
	}{
		{"text", true},
		{"markdown", true},
		{"code", true},
		{"", true},
		{"thinking", false},
		{"tool_input", false},
		{"TOOL_INPUT", false},
	} {
		if got := isAssistantVisibleContentType(tc.ct); got != tc.want {
			t.Fatalf("isAssistantVisibleContentType(%q) = %v want %v", tc.ct, got, tc.want)
		}
	}
}

func TestHandleStreamEnvelope_textToStdout_thinkingToStderr(t *testing.T) {
	t.Parallel()
	var out, log bytes.Buffer
	opt := streamOpts{quiet: false, verbose: false}

	payload, _ := json.Marshal(protocol.StreamDeltaPayload{ContentType: "text", Content: "Hello"})
	env := &protocol.Envelope{Type: protocol.TypeStreamDelta, Payload: payload}
	done, err := handleStreamEnvelope(env, &out, &log, opt)
	if err != nil || done {
		t.Fatalf("delta text: err=%v done=%v", err, done)
	}
	if got := out.String(); got != "Hello" {
		t.Fatalf("stdout=%q", got)
	}

	out.Reset()
	log.Reset()
	payload2, _ := json.Marshal(protocol.StreamDeltaPayload{ContentType: "thinking", Content: "secret"})
	env2 := &protocol.Envelope{Type: protocol.TypeStreamDelta, Payload: payload2}
	_, err = handleStreamEnvelope(env2, &out, &log, opt)
	if err != nil {
		t.Fatal(err)
	}
	if out.String() != "" {
		t.Fatalf("thinking should not go to stdout, got %q", out.String())
	}
	if log.Len() == 0 {
		t.Fatal("expected stderr log for thinking")
	}
}

func TestHandleStreamEnd(t *testing.T) {
	t.Parallel()
	var out, log bytes.Buffer
	opt := streamOpts{quiet: false, verbose: false}
	payload, _ := json.Marshal(protocol.StreamEndPayload{FinishReason: "complete", Usage: &protocol.UsageInfo{InputTokens: 1, OutputTokens: 2}})
	env := &protocol.Envelope{Type: protocol.TypeStreamEnd, Payload: payload}
	done, err := handleStreamEnvelope(env, &out, &log, opt)
	if err != nil || !done {
		t.Fatalf("stream.end: err=%v done=%v log=%s", err, done, log.String())
	}
}

func TestHandleToolUseStartResult(t *testing.T) {
	t.Parallel()
	var out, log bytes.Buffer
	opt := streamOpts{quiet: false, verbose: true}

	p1, _ := json.Marshal(protocol.ToolUseStartPayload{ToolID: "t1", ToolName: "Read", Input: map[string]any{"path": "/x"}})
	e1 := &protocol.Envelope{Type: protocol.TypeToolUseStart, Payload: p1}
	if _, err := handleStreamEnvelope(e1, &out, &log, opt); err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(log.Bytes(), []byte("Read")) {
		t.Fatalf("log: %s", log.String())
	}

	p2, _ := json.Marshal(protocol.ToolUseResultPayload{ToolID: "t1", Output: "ok"})
	e2 := &protocol.Envelope{Type: protocol.TypeToolUseResult, Payload: p2}
	if _, err := handleStreamEnvelope(e2, &out, &log, opt); err != nil {
		t.Fatal(err)
	}
}
