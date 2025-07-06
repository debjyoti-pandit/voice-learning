from flask import Flask, request
from flask_socketio import SocketIO, join_room, leave_room
from dotenv import load_dotenv
from src.templates_controller import templates_bp
from src.auth_controller import auth_bp
from src.greet_controller import greet_bp
from src.voice_controller import voice_bp
from src.call_events_controller import events_bp
from src.conference_controller import conference_bp
from src.hold_controller import hold_bp
import os
from twilio.rest import Client
import logging

load_dotenv()

app = Flask(__name__)

app.logger.setLevel(logging.INFO)
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

@socketio.on('connect')
def handle_socket_connect():
    """Add the connecting client to a room matching its identity (if provided)."""
    identity = request.args.get('identity')
    if identity:
        join_room(identity)
        app.logger.info(f"🔌 Client connected and joined room: {identity}")
    else:
        app.logger.info("🔌 Client connected without identity")

@socketio.on('disconnect')
def handle_socket_disconnect():
    """Log disconnections; the Socket.IO server automatically removes rooms."""
    identity = request.args.get('identity')
    if identity:
        app.logger.info(f"🔌 Client with identity '{identity}' disconnected")
    else:
        app.logger.info("🔌 Client disconnected without identity")

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5678, debug=False)
