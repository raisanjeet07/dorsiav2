# workspace-file-service

Small **Go** HTTP service that provides a **1:1 on-disk workspace per `session_id`** and **read-only file browsing** over HTTP. Session data lives under a configurable root; **service logs** go to stdout and optionally to a **separate** file (never under the workspace tree).

## Configuration

| Env | Default | Description |
|-----|---------|-------------|
| `WORKSPACE_FILE_HOST` | `0.0.0.0` | Bind address |
| `WORKSPACE_FILE_PORT` | `8090` | HTTP port |
| `WORKSPACE_FILE_ROOT` | `../dorsia-workspace` (or set to repo `dorsia-workspace/` absolute path) | Directory where `/<session_id>/` folders are created |
| `WORKSPACE_FILE_LOG_FILE` | *(empty)* | Optional path for JSON logs (append); also echoed to stdout |

## Session IDs

Allowed characters: letters, digits, `.`, `_`, `-` (max length 256). No `/` or `..`.

## API

### Health

`GET /health` → `{"status":"ok"}`

### Get workspace path (ensure directory)

`GET /api/v1/sessions/{sessionId}`  
`GET /api/v1/sessions/{sessionId}/location`  

Creates the directory if it does not exist, then returns the absolute path.

Response `200`:

```json
{
  "session_id": "my-session-1",
  "workspace_path": "/abs/path/to/workspaces/my-session-1",
  "created": true
}
```

`created` is `false` if the directory already existed.

### Create workspace (legacy / explicit)

`POST /api/v1/sessions`  
Body: `{"session_id":"my-session-1"}`

Response `201` with the same JSON shape as `GET` (including `created`).

### Browse / download files

`GET /files/{sessionId}/` — directory listing (HTML) for the session root.  
`GET /files/{sessionId}/relative/path/to/file` — file download or subdirectory listing.

The session workspace must exist (use **`GET /api/v1/sessions/{sessionId}`** first to create it, or rely on the gateway doing that before agents run). Paths are sanitized to prevent traversal outside the session directory.

## Local run

Default session root is **`<repo>/dorsia-workspace`** (`make run` sets `WORKSPACE_FILE_ROOT` to that path).

```bash
cd workspace-file-service
make run
# or explicit (matches repo layout):
WORKSPACE_FILE_ROOT=/path/to/dorsiav2/dorsia-workspace WORKSPACE_FILE_LOG_FILE=/tmp/ws-service.log make run
```

## Docker

```bash
docker build -t workspace-file-service:latest .
docker run --rm -p 8090:8090 -v wsdata:/data/workspaces workspace-file-service:latest
```

## Integration

Other services (gateway, research workflow) can call this API to **resolve** `workspace_path` for a `session_id` before starting agents, and users can open **`/files/...`** in a browser to inspect artifacts.
