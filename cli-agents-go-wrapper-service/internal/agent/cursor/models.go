package cursor

import (
	"bufio"
	"bytes"
	"context"
	"fmt"
	"os/exec"
	"regexp"
	"strings"

	"github.com/cli-agents-go-wrapper-service/internal/process"
)

// ansiEscape strips ANSI terminal escape sequences from a string.
var ansiEscape = regexp.MustCompile(`\x1b\[[0-9;]*[A-Za-z]|\x1b\[[0-9]*[A-Za-z]`)

// ListModels runs `agent models` and parses its output.
// Output format (after stripping ANSI): lines of "<id> - <display name>".
func (a *Adapter) ListModels(ctx context.Context) ([]string, error) {
	cmd := exec.CommandContext(ctx, "agent", "models")
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &out

	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("agent models: %w", err)
	}
	process.LogSpawned(cmd)
	if err := cmd.Wait(); err != nil {
		return nil, fmt.Errorf("agent models: %w", err)
	}

	var models []string
	scanner := bufio.NewScanner(&out)
	for scanner.Scan() {
		line := ansiEscape.ReplaceAllString(scanner.Text(), "")
		line = strings.TrimSpace(line)

		// Lines are: "<id> - <display name>"
		// Skip headers, tips, blank lines.
		idx := strings.Index(line, " - ")
		if idx <= 0 {
			continue
		}

		id := strings.TrimSpace(line[:idx])
		// Sanity check: model IDs don't contain spaces.
		if strings.ContainsAny(id, " \t") {
			continue
		}

		models = append(models, id)
	}

	return models, nil
}
