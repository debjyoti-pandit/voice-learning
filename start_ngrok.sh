#!/usr/bin/env bash
# start_ngrok.sh - Convenience script to start ngrok with reserved domain

# Exit immediately on errors, treat unset variables as errors, fail on pipeline errors
set -euo pipefail

# ------------------------------------------------------------
# Helper – gracefully clean up any ngrok children when we exit
# ------------------------------------------------------------

# Array for storing child PIDs so we can iterate in cleanup
child_pids=()

cleanup() {
  echo "\n[cleanup] Shutting down ngrok tunnels …"
  # Iterate over recorded PIDs and terminate if still running
  for pid in "${child_pids[@]:-}"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      # Wait for the process to actually exit to prevent zombies
      wait "$pid" 2>/dev/null || true
    fi
  done
  echo "[cleanup] Done."
}

# Trap common termination signals so Ctrl+C (SIGINT) or `kill` (SIGTERM)
# invoke our cleanup before the script exits. EXIT covers normal completion.
trap cleanup INT TERM EXIT

# Load environment variables from .env safely — tolerate leading "export" and extra spaces around '='
if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a  # automatically export all sourced vars
  # Sanitize lines:
  #   • remove leading "export " if present
  #   • trim spaces around '=' so "KEY = value" becomes "KEY=value"
  #   • skip empty/comment lines
  source <(grep -v '^[[:space:]]*#' .env | \
           sed -E 's/^export[[:space:]]+//' | \
           sed -E 's/[[:space:]]*=[[:space:]]*/=/' )
  set +a
fi

# Derive defaults when variables are unset
PORT=${PORT:-5678}
# Web-socket server port (second tunnel)
WS_PORT=${WS_PORT:-6789}
# Control HTTP API port (third tunnel)
CONTROL_HTTP_PORT=${CONTROL_HTTP_PORT:-4567}
# Optional names for deriving domains
NAME=${NAME:-debjyoti}

# Primary HTTP tunnel domain (derived if not set explicitly)
DOMAIN="${DOMAIN:-${NAME}-voice-learning.ngrok-free.app}"
# Web-socket tunnel domain – strip any protocol prefix the caller might include
WS_DOMAIN_RAW="${WS_DOMAIN:-debjyoti-websocket-server.in.ngrok.io}"
# Remove leading "ws://" or "wss://" if present so ngrok gets just the host
WS_DOMAIN="${WS_DOMAIN_RAW#*://}"

# Check if ngrok is installed
if ! command -v ngrok &> /dev/null; then
  echo "Error: ngrok is not installed. Please install it first." >&2
  exit 1
fi

# echo "Cleaning existing ngrok tunnels..."
# pkill -f "ngrok.*debjyoti-voice-learning.ngrok-free.app" &

echo "Starting primary ngrok tunnel on port ${PORT} with reserved domain ${DOMAIN}..."
# Run the primary tunnel in background so we can start the websocket one next
ngrok http "${PORT}" --domain="${DOMAIN}"

# echo "Starting websocket ngrok tunnel on port ${WS_PORT} with reserved domain ${WS_DOMAIN}..."
# ngrok http "${WS_PORT}" --domain="${WS_DOMAIN}"
