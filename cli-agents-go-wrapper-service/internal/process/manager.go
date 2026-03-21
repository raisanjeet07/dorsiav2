// Package process provides utilities for spawning and managing CLI agent
// child processes. Adapters use this when ConnectionMode == "spawn".
package process

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"log/slog"
	"os/exec"
	"sync"
	"sync/atomic"
)

// Process wraps an OS process with structured I/O handling.
type Process struct {
	cmd    *exec.Cmd
	stdin  io.WriteCloser
	stdout io.ReadCloser
	stderr io.ReadCloser

	running atomic.Bool
	mu      sync.Mutex
	done    chan struct{}
}

// SpawnOptions configures how to launch a child process.
type SpawnOptions struct {
	Command    string            // e.g. "claude", "agent" (cursor adapter), "gemini"
	Args       []string          // CLI arguments
	WorkingDir string            // working directory
	Env        map[string]string // extra env vars (merged with os.Environ)

	// NoStdinPipe: when true, the child's stdin is not a pipe — Go attaches
	// the null device (same as redirecting from /dev/null). Use this when the
	// prompt is passed only via argv (e.g. claude -p, gemini --prompt). Leaving
	// an open pipe with no writes makes Claude Code wait ~3s and log:
	// "Warning: no stdin data received in 3s..."
	// When false (default), a pipe is created for process.Write() (Cursor).
	NoStdinPipe bool
}

// maxSpawnLogLen caps logged command strings so huge argv (e.g. -p prompts) do not flood logs.
const maxSpawnLogLen = 4096

// LogSpawned logs the full command line and OS process id immediately after a successful
// exec.Cmd.Start. Use for any adapter- or auth-spawned process not created via Spawn.
func LogSpawned(cmd *exec.Cmd) {
	if cmd == nil || cmd.Process == nil {
		return
	}
	full := cmd.String()
	s := full
	if len(s) > maxSpawnLogLen {
		s = s[:maxSpawnLogLen] + fmt.Sprintf(" ... <%d bytes total>", len(full))
	}
	slog.Info("process.spawn", "cmd", s, "pid", cmd.Process.Pid)
}

// Spawn starts a new child process and wires up stdin/stdout/stderr.
func Spawn(ctx context.Context, opts SpawnOptions) (*Process, error) {
	cmd := exec.CommandContext(ctx, opts.Command, opts.Args...)
	if opts.WorkingDir != "" {
		cmd.Dir = opts.WorkingDir
	}
	if len(opts.Env) > 0 {
		env := cmd.Environ()
		for k, v := range opts.Env {
			env = append(env, fmt.Sprintf("%s=%s", k, v))
		}
		cmd.Env = env
	}

	var stdin io.WriteCloser
	if opts.NoStdinPipe {
		// Child reads from null device; do not open a pipe we never write to.
		cmd.Stdin = nil
	} else {
		var err error
		stdin, err = cmd.StdinPipe()
		if err != nil {
			return nil, fmt.Errorf("stdin pipe: %w", err)
		}
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, fmt.Errorf("stdout pipe: %w", err)
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return nil, fmt.Errorf("stderr pipe: %w", err)
	}

	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("start %q: %w", opts.Command, err)
	}
	LogSpawned(cmd)

	p := &Process{
		cmd:    cmd,
		stdin:  stdin,
		stdout: stdout,
		stderr: stderr,
		done:   make(chan struct{}),
	}
	p.running.Store(true)

	// Monitor process exit in background.
	go func() {
		_ = cmd.Wait()
		p.running.Store(false)
		close(p.done)
	}()

	return p, nil
}

// Write sends bytes to the process's stdin.
func (p *Process) Write(data []byte) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if !p.running.Load() {
		return fmt.Errorf("process not running")
	}
	if p.stdin == nil {
		return fmt.Errorf("stdin not available (spawned with NoStdinPipe)")
	}
	_, err := p.stdin.Write(data)
	return err
}

// WriteLine sends a line (appends newline) to stdin.
func (p *Process) WriteLine(line string) error {
	return p.Write([]byte(line + "\n"))
}

// ReadLines returns a channel that yields lines from stdout.
// The channel closes when stdout is exhausted or the process exits.
func (p *Process) ReadLines() <-chan string {
	ch := make(chan string, 64)
	go func() {
		defer close(ch)
		scanner := bufio.NewScanner(p.stdout)
		scanner.Buffer(make([]byte, 1024*1024), 1024*1024) // 1 MB buffer
		for scanner.Scan() {
			ch <- scanner.Text()
		}
	}()
	return ch
}

// ReadStderrLines returns a channel that yields lines from stderr.
func (p *Process) ReadStderrLines() <-chan string {
	ch := make(chan string, 64)
	go func() {
		defer close(ch)
		scanner := bufio.NewScanner(p.stderr)
		scanner.Buffer(make([]byte, 256*1024), 256*1024)
		for scanner.Scan() {
			ch <- scanner.Text()
		}
	}()
	return ch
}

// Stdout returns the raw stdout reader for adapters that need streaming JSON.
func (p *Process) Stdout() io.Reader {
	return p.stdout
}

// Stderr returns the raw stderr reader.
func (p *Process) Stderr() io.Reader {
	return p.stderr
}

// IsRunning reports whether the process is still alive.
func (p *Process) IsRunning() bool {
	return p.running.Load()
}

// Done returns a channel that closes when the process exits.
func (p *Process) Done() <-chan struct{} {
	return p.done
}

// PID returns the OS process id of the child, or 0 if unavailable.
func (p *Process) PID() int {
	if p == nil || p.cmd == nil || p.cmd.Process == nil {
		return 0
	}
	return p.cmd.Process.Pid
}

// Stop gracefully terminates the process. Closes stdin first to signal
// the child, then waits briefly before killing.
func (p *Process) Stop() error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if !p.running.Load() {
		return nil
	}
	// Close stdin to signal the process.
	if p.stdin != nil {
		_ = p.stdin.Close()
	}

	// If the process doesn't exit on its own, kill it.
	if p.cmd.Process != nil {
		_ = p.cmd.Process.Kill()
	}
	return nil
}
