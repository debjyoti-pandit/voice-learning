from flask import Flask
from flask_socketio import SocketIO
from dotenv import load_dotenv
from src.controllers_class import api_bp

load_dotenv()

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Expose socketio so routes in the blueprint can access it via current_app.config
app.config['socketio'] = socketio

# Register application routes from controllers blueprint
app.register_blueprint(api_bp)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5678, debug=True)
