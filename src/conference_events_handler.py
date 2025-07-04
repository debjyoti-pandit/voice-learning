from flask import current_app
from flask_socketio import SocketIO


class ConferenceEventsHandler:
    """Encapsulates the business logic for processing Twilio conference-status callbacks."""

    def __init__(self, socketio: SocketIO):
        self.socketio = socketio

    def handle(self, flask_request):
        """Process the incoming Flask request and emit a structured Socket.IO event."""
        values = flask_request.values

        event_type = values.get("StatusCallbackEvent")  # e.g. "participant-join", "conference-end"
        conference_sid = values.get("ConferenceSid")
        friendly_name = values.get("FriendlyName")
        sequence_number = values.get("SequenceNumber")
        timestamp = values.get("Timestamp")

        # Different callback types use different parameter names to reference the participant / call SIDs
        call_sid = (
            values.get("CallSid")
            or values.get("CallSidEndingConference")
            or values.get("ParticipantSid")
        )

        reason = values.get("Reason") or values.get("ReasonConferenceEnded")

        event_data = {
            "event": event_type,
            "conference_sid": conference_sid,
            "conference_name": friendly_name,
            "sequence_number": sequence_number,
            "timestamp": timestamp,
            "call_sid": call_sid,
            "reason": reason,
        }

        # Strip keys whose value is None for a cleaner payload
        event_data = {k: v for k, v in event_data.items() if v is not None}

        # Emit over WebSocket so frontend can consume
        self.socketio.emit("conference_event", event_data)

        # Server-side log for debugging/tracing
        current_app.logger.info("📢 Conference event emitted: %s", event_data)

        # Twilio expects a 2xx; 204 avoids extra bytes
        return "", 204 