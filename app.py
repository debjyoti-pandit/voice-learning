from flask import Flask
from flask_socketio import SocketIO
from dotenv import load_dotenv
from src.templates_controller import templates_bp  # page templates
from src.auth_controller import auth_bp  # authentication routes
from src.greet_controller import greet_bp  # greeting routes
from src.voice_controller import voice_bp  # voice routes
from src.call_events_controller import events_bp  # call events routes
from src.conference_controller import conference_bp  # conference routes
import os
from twilio.rest import Client

load_dotenv()

# ---------------------------------------------------------------------------
# Flask application setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# ---------------------------------------------------------------------------
# Shared Twilio REST client (single instance) --------------------------------
# ---------------------------------------------------------------------------

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Expose socketio so routes in the blueprint can access it via current_app.config
app.config['socketio'] = socketio
app.config['twilio_client'] = twilio_client

# Register application routes
app.register_blueprint(templates_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(greet_bp)
app.register_blueprint(voice_bp)
app.register_blueprint(events_bp)
app.register_blueprint(conference_bp)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5678, debug=True)
