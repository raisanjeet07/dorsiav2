#!/usr/bin/env bash
# deploy.sh — install and (re)start cli-agent-gateway as a systemd service.
#
# Usage (local or remote):
#   ANTHROPIC_API_KEY=sk-ant-... GOOGLE_API_KEY=AIza... ./deploy.sh /path/to/binary
#
# The script:
#   1. Copies the binary to /usr/local/bin
#   2. Writes a systemd unit file with env vars baked in
#   3. Enables and (re)starts the service
#
# Requires: systemd, sudo / root access.

set -euo pipefail

BINARY="${1:-./bin/cli-agent-gateway}"
SERVICE="cli-agent-gateway"
INSTALL_PATH="/usr/local/bin/$SERVICE"
PORT="${GATEWAY_PORT:-8080}"
HOST="${GATEWAY_HOST:-0.0.0.0}"

if [[ ! -f "$BINARY" ]]; then
  echo "ERROR: binary not found at $BINARY" >&2
  exit 1
fi

echo "==> Installing binary to $INSTALL_PATH"
sudo cp "$BINARY" "$INSTALL_PATH"
sudo chmod +x "$INSTALL_PATH"

echo "==> Writing systemd unit"
sudo tee /etc/systemd/system/$SERVICE.service > /dev/null <<EOF
[Unit]
Description=CLI Agent Gateway
After=network.target

[Service]
ExecStart=$INSTALL_PATH --port $PORT
Restart=always
RestartSec=5
User=nobody
Group=nogroup

# API keys — update here or use EnvironmentFile=/etc/cli-agent-gateway/env
Environment="ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}"
Environment="GOOGLE_API_KEY=${GOOGLE_API_KEY:-}"
Environment="CURSOR_API_KEY=${CURSOR_API_KEY:-}"
Environment="GATEWAY_HOST=$HOST"
Environment="GATEWAY_PORT=$PORT"

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SERVICE

[Install]
WantedBy=multi-user.target
EOF

echo "==> Enabling and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE"
sudo systemctl restart "$SERVICE"

echo "==> Status"
sudo systemctl status "$SERVICE" --no-pager
echo ""
echo "Health: http://$(hostname -I | awk '{print $1}'):$PORT/health"
echo ""
echo "Useful commands:"
echo "  journalctl -u $SERVICE -f        # tail logs"
echo "  systemctl status $SERVICE        # service status"
echo "  systemctl stop $SERVICE          # stop"
