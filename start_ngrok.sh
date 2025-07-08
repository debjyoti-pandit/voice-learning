#!/usr/bin/env bash
# start_ngrok.sh - Convenience script to start ngrok with reserved domain

set -euo pipefail

PORT=5678

# Load NAME from .env if available, otherwise fall back to environment/default
if [ -f .env ]; then
  # shellcheck disable=SC2046,SC1090
  export $(grep -v "^#" .env | xargs)  # load key=value lines
fi
NAME=${NAME:-debjyoti}
DOMAIN="${NAME}-voice-learning.ngrok-free.app"

# Check if ngrok is installed
if ! command -v ngrok &> /dev/null; then
  echo "Error: ngrok is not installed. Please install it first." >&2
  exit 1
fi

echo "Starting ngrok on port ${PORT} with reserved domain ${DOMAIN}..."
ngrok http ${PORT} --domain=${DOMAIN} 