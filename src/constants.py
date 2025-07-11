import os

from dotenv import load_dotenv

# Load environment variables from a .env file if present
load_dotenv()

# ---------------------------------------------------------------------------
# Application-wide constants derived from environment variables
# ---------------------------------------------------------------------------

# Base name (e.g. for identities, friendly greetings, etc.)
NAME: str = os.getenv("NAME", "debjyoti")

# Default identity string used when the client / request doesn't provide one
DEFAULT_IDENTITY: str = f"{NAME}-dialer-app"

# Convenience helper for the Twilio "client:" address form
CLIENT_NUMBER: str = f"client:{NAME}"

# Fully-qualified public domain used when running behind ngrok
SERVER_DOMAIN: str = f"{NAME}-voice-learning.ngrok-free.app"

__all__ = [
    "CLIENT_NUMBER",
    "DEFAULT_IDENTITY",
    "NAME",
    "SERVER_DOMAIN",
]
