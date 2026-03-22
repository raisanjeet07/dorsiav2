"""Application configuration — loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All settings overridable via env vars prefixed with RESEARCH_."""

    # Service
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/research_workflows"

    # CLI Agent Gateway
    gateway_ws_url: str = "ws://localhost:8080/ws"
    gateway_http_url: str = "http://localhost:8080"
    gateway_reconnect_max_attempts: int = 10
    gateway_reconnect_base_delay: float = 2.0

    # Capability Service (persona/skill extensions)
    capability_service_url: str = "http://localhost:8100"

    # Workspace (./workspace for local dev; /workspace for Docker)
    workspace_base_dir: str = "./workspace"

    # Working directory passed to the gateway when creating agent sessions.
    # Must be a path that EXISTS inside the gateway container (not this one).
    gateway_agent_work_dir: str = "/workspace"

    # When True, Claude Code runs one-shot (no --resume / no session id chain).
    # Default False: the gateway persists Claude's session_id and uses --resume so
    # the same gateway session continues the same Claude CLI conversation.
    gateway_claude_disable_resume: bool = False

    # Workflow defaults (1 = one resolve/re-review round then forced consensus — fast for testing)
    default_max_review_cycles: int = 1
    default_max_user_change_requests: int = 3
    default_depth: str = "standard"
    agent_prompt_timeout_seconds: int = 300
    user_review_timeout_hours: int = 24

    # Agent defaults
    researcher_agent: str = "gemini"
    reviewer_agent: str = "claude-code"
    resolver_agents: list[str] = ["gemini", "claude-code"]
    # When True, Gemini + Claude resolvers run concurrently (two gateway processes).
    # Default False: run sequentially and end each gateway session before starting the next
    # (avoids multiple CLI processes stacked during RESOLVING).
    resolvers_parallel: bool = False
    researcher_model: str = ""
    reviewer_model: str = "claude-sonnet-4-6"
    resolver_claude_model: str = "claude-sonnet-4-6"

    model_config = {"env_prefix": "RESEARCH_"}


settings = Settings()
