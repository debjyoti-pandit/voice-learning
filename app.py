from flask import Flask
from flask_socketio import SocketIO
from dotenv import load_dotenv
from src.controllers import api_bp  # main API routes
from src.auth_controller import auth_bp  # authentication routes
from src.greet_controller import greet_bp  # greeting routes
from src.voice_controller import voice_bp  # voice routes

load_dotenv()

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Expose socketio so routes in the blueprint can access it via current_app.config
app.config['socketio'] = socketio

# Register application routes
app.register_blueprint(api_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(greet_bp)
app.register_blueprint(voice_bp)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5678, debug=True)
