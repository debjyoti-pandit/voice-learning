#!/usr/bin/env bash
# start_ngrok.sh - Convenience script to start ngrok with reserved domain

set -euo pipefail

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
NAME=${NAME:-debjyoti}
DOMAIN="${NAME}-voice-learning.ngrok-free.app"

# Check if ngrok is installed
if ! command -v ngrok &> /dev/null; then
  echo "Error: ngrok is not installed. Please install it first." >&2
  exit 1
fi

echo "Starting ngrok on port ${PORT} with reserved domain ${DOMAIN}..."
ngrok http ${PORT} --domain=${DOMAIN} 