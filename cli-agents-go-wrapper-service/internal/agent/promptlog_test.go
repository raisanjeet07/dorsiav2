package agent

import (
	"strings"
	"testing"
)

func TestPromptForLog(t *testing.T) {
	t.Parallel()
	if got := PromptForLog(""); got != "(empty)" {
		t.Fatalf("empty: %q", got)
	}
	if got := PromptForLog("hi"); got != "hi" {
		t.Fatalf("short: %q", got)
	}
	long := strings.Repeat("あ", 9000) // >8000 runes
	got := PromptForLog(long)
	if !strings.HasSuffix(got, "… (truncated)") {
		t.Fatalf("expected truncation suffix")
	}
	if len([]rune(got)) > 8100 {
		t.Fatalf("truncated too long: %d runes", len([]rune(got)))
	}
}
