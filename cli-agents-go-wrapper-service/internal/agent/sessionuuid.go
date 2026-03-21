package agent

import (
	"crypto/sha256"
	"os"
	"strings"

	"github.com/google/uuid"
)

// adapterSessionNamespace is the fixed UUID namespace for name-based (RFC 4122 UUID v5)
// adapter session IDs: SHA-1(namespace || name) truncated to 128 bits. The same
// (gatewaySessionID, flow) pair always yields the same UUID — it is a deterministic
// hash of the routing key, not random.
var adapterSessionNamespace = uuid.MustParse("6ba7b812-9dad-11d1-80b4-00c04fd430c8")

// SessionRoutingKey is the canonical string that gets hashed into AdapterSessionUUID:
// trimmed gateway session id and flow joined by ASCII RS (0x1e).
func SessionRoutingKey(sessionID, flow string) string {
	s := strings.TrimSpace(sessionID)
	f := strings.TrimSpace(flow)
	if s == "" || f == "" {
		return ""
	}
	return s + "\x1e" + f
}

func useSHA256AdapterUUID() bool {
	v := strings.TrimSpace(os.Getenv("GATEWAY_ADAPTER_SESSION_SHA256"))
	return v == "1" || strings.EqualFold(v, "true")
}

// AdapterSessionUUID returns a deterministic RFC-4122 UUID string for the (gateway
// sessionId, flow) routing key. Internally this is a UUID v5–style hash (SHA-1 by
// default) so the same pair always maps to the same value for CLI --session-id / resume.
//
// Set GATEWAY_ADAPTER_SESSION_SHA256=1 to derive the UUID with SHA-256 instead
// (still deterministic; produces different IDs than SHA-1).
//
// Returns empty if sessionID or flow is empty after trimming.
func AdapterSessionUUID(sessionID, flow string) string {
	name := SessionRoutingKey(sessionID, flow)
	if name == "" {
		return ""
	}
	if useSHA256AdapterUUID() {
		return uuid.NewHash(sha256.New(), adapterSessionNamespace, []byte(name), 5).String()
	}
	return uuid.NewSHA1(adapterSessionNamespace, []byte(name)).String()
}
