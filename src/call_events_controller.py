from flask import Blueprint, current_app, request

from src.call_events_handler import CallEventsHandler

events_bp = Blueprint("events", __name__)


@events_bp.route("/call-events", methods=["GET", "POST"])
def call_events():
    """Handle Twilio call status callbacks and forward them via Socket.IO."""
    socketio = current_app.config["socketio"]
    call_log = current_app.config["call_log"]
    resp = CallEventsHandler(socketio, call_log).handle(request)
    return resp
