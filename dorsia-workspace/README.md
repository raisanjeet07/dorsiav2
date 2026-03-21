# Dorsia workspace (session files)

Per-session agent workspaces live here as subdirectories (`<session_id>/`), created by **workspace-file-service**.

- **Local path:** `dorsiav2/dorsia-workspace` (this folder at the repo root).
- **Docker:** bind-mounted at `/data/workspaces` in the workspace-file-service and gateway containers.

Contents are gitignored except this file.
