from flask import Flask, request, jsonify
from flask_socketio import SocketIO, join_room, leave_room
from dotenv import load_dotenv
from src.templates_controller import templates_bp
from src.auth_controller import auth_bp
from src.greet_controller import greet_bp
from src.voice_controller import voice_bp
from src.call_events_controller import events_bp
from src.conference_controller import conference_bp
from src.hold_controller import hold_bp
from src.transfer_controller import transfer_bp
import os
from twilio.rest import Client
import logging

load_dotenv()

# --- Logging -----------------------------------------------------------------
# Custom formatter that appends selected extra attributes only when they are present
# and non-empty so that lines without extras stay clean.
class OptionalExtraFormatter(logging.Formatter):
    """Formatter that appends selected extra attributes only when they are present
    and non-empty so that lines without extras stay clean.

    Extra attributes we care about: ``params``, ``payload``, ``conference_name``.
    """
    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        base = super().format(record)

        extras: list[str] = []
        for key in ("params", "payload", "conference_name"):
            if not hasattr(record, key):
                continue
            value = getattr(record, key)
            # Skip if value is falsy / empty ("", None, {}, [], etc.)
            if value:
                extras.append(f"{key}={value}")

        if extras:
            base = f"{base} {' '.join(extras)}"

        return base

# Remove any handlers that might have been added by previous basicConfig calls
for h in logging.root.handlers[:]:
    logging.root.removeHandler(h)

_handler = logging.StreamHandler()
_handler.setFormatter(OptionalExtraFormatter(
    "%(asctime)s %(levelname)s [%(module)s] %(message)s"
))
logging.root.setLevel(logging.INFO)
logging.root.addHandler(_handler)

# --- End logging setup -------------------------------------------------------

app = Flask(__name__)

app.logger.setLevel(logging.DEBUG)
socketio = SocketIO(app, cors_allowed_origins="*")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

app.config['socketio'] = socketio
app.config['twilio_client'] = twilio_client

call_log: dict[str, dict] = {}
app.config['call_log'] = call_log

redis: dict[str, dict] = {}
app.config['redis'] = redis

app.config['SERVER_NAME'] = 'debjyoti-voice-learning.ngrok-free.app'
app.config['PREFERRED_URL_SCHEME'] = 'https'

app.register_blueprint(templates_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(greet_bp)
app.register_blueprint(voice_bp)
app.register_blueprint(events_bp)
app.register_blueprint(conference_bp)
app.register_blueprint(hold_bp)
app.register_blueprint(transfer_bp)

# Track currently connected Socket.IO client identities so that the web dialer can
# populate a dropdown with live targets.
connected_identities: set[str] = set()
# Map Socket.IO session IDs -> identity strings so we can reliably clean up
# when a client disconnects (``request.args`` is not available in the
# disconnect handler).
sid_to_identity: dict[str, str] = {}

@socketio.on('connect')
def handle_socket_connect():
    """Handle a new Socket.IO connection.

    • Add the client to a room named after its identity (if provided)
    • Record the identity in the global ``connected_identities`` set so that
      other clients can discover currently available browser dialers.
    • Broadcast the updated list of identities to all connected clients so that
      their UI dropdowns stay in sync in real-time.
    """
    identity = request.args.get('identity')
    if identity:
        join_room(identity)
        # Record mapping so we can look it up on disconnect
        sid_to_identity[request.sid] = identity
        connected_identities.add(identity)
        # Broadcast the updated list to every client (no specific room).
        socketio.emit('connected_identities', list(connected_identities))
        app.logger.info(f"🔌 Client connected and joined room: {identity}")
    else:
        app.logger.info("🔌 Client connected without identity")

@socketio.on('disconnect')
def handle_socket_disconnect():
    """Clean up tracking state when a Socket.IO client disconnects."""
    sid = request.sid
    identity = sid_to_identity.pop(sid, None)

    if identity:
        # If no other active socket is using the same identity, remove it from the set
        if identity not in sid_to_identity.values():
            connected_identities.discard(identity)

        socketio.emit('connected_identities', list(connected_identities))
        app.logger.info(f"🔌 Client with identity '{identity}' disconnected (sid={sid})")
        # Optionally leave the room
        leave_room(identity)
    else:
        app.logger.info(f"🔌 Client disconnected without tracked identity (sid={sid})")

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

@app.route('/connected-dialers', methods=['GET'])
def get_connected_dialers():
    """Return a JSON list of identities for currently connected browser dialers."""
    return jsonify(list(connected_identities))

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5678, debug=False)
