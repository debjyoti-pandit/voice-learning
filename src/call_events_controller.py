from flask import Blueprint, request, current_app

from src.call_events_handler import CallEventsHandler
from src.controllers import call_log  # shared call log dictionary

# Blueprint dedicated to Twilio status callbacks and related events
events_bp = Blueprint('events', __name__)


@events_bp.route('/call-events', methods=['GET', 'POST'])
def call_events():
    """Handle Twilio call status callbacks and forward them via Socket.IO."""
    socketio = current_app.config['socketio']
    return CallEventsHandler(socketio, call_log).handle(request) 