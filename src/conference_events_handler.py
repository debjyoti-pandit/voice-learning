from flask import current_app, url_for
from flask_socketio import SocketIO


class ConferenceEventsHandler:
    """Encapsulates the business logic for processing Twilio conference-status callbacks."""

    def __init__(self, socketio: SocketIO):
        self.socketio = socketio


    def handle(self, flask_request):
        """Process the incoming Flask request and emit a structured Socket.IO event."""
        values = flask_request.values

        event_type = values.get("StatusCallbackEvent")
        conference_sid = values.get("ConferenceSid")
        call_sid = values.get("CallSid")  # e.g. "participant-join", "conference-end"
        friendly_name = values.get("FriendlyName")
        sequence_number = values.get("SequenceNumber")
        timestamp = values.get("Timestamp")
        participant_label = values.get("ParticipantLabel")
        coaching = values.get("Coaching")
        end_conference_on_exit = values.get("EndConferenceOnExit")
        start_conference_on_enter = values.get("StartConferenceOnEnter")
        hold = values.get("Hold")
        muted = values.get("Muted")
        redis = current_app.config['redis']
        redis.setdefault(friendly_name, {})
        redis[friendly_name]["conference_sid"] = conference_sid
        redis[friendly_name].setdefault("participants", {})
        participants = redis[friendly_name]["participants"]
        calls = redis[friendly_name].get("calls", {})
        # Get role from calls dict if available, else from request
        role = None
        if call_sid in calls:
            role = calls[call_sid].get("role")
        if not role:
            role = values.get("role")
        # Track participant state
        if event_type == "participant-join":
            print(participants)
            # Merge with existing state if present, but only update muted/on_hold if webhook value is not None
            prev = participants.get(call_sid, {})
            participants[call_sid] = {
                "participant_label": participant_label or prev.get("participant_label"),
                "call_sid": call_sid,
                "muted": bool(muted) if muted is not None else prev.get("muted", False),
                "on_hold": bool(hold) if hold is not None else prev.get("on_hold", False),
                "role": role or prev.get("role"),
            }
        elif event_type in ("mute", "hold"):
            if call_sid in participants:
                if event_type == "mute" and muted is not None:
                    participants[call_sid]["muted"] = bool(muted)
                if event_type == "hold" and hold is not None:
                    participants[call_sid]["on_hold"] = bool(hold)
        elif event_type == "participant-leave":
            if call_sid in participants:
                participants[call_sid]["left"] = True
        try:
            if event_type == "participant-join":
                hold_on_conference_join = redis[friendly_name]["calls"][call_sid]['hold_on_conference_join'];
                if hold_on_conference_join:
                    print(f"Holding on conference join for call label: {redis[friendly_name]['calls'][call_sid]['call_tag']}")
                    client = current_app.config['twilio_client']
                    client.conferences(conference_sid).participants(call_sid).update(
                        hold=True,
                        hold_url=url_for('hold.hold_music', _external=True),
                        hold_method='POST'
                    )
        except KeyError:
            print(f"Event type: {event_type}, Call sid: {call_sid}, Friendly name: {friendly_name}")
            return "", 204

        # Different callback types use different parameter names to reference the participant / call SIDs
        call_sid = (
            values.get("CallSid")
            or values.get("CallSidEndingConference")
            or values.get("ParticipantSid")
        )

        reason = values.get("Reason") or values.get("ReasonConferenceEnded")

        event_data = {
            "event": event_type,
            "conference_name": friendly_name,
            "sequence_number": sequence_number,
            "timestamp": timestamp,
            "call_sid": call_sid,
            "reason": reason,
            "participant_label": participant_label,
            "coaching": coaching,
            "end_conference_on_exit": end_conference_on_exit,
            "start_conference_on_enter": start_conference_on_enter,
            "hold": hold,
            "muted": muted,
        }

        # Strip keys whose value is None for a cleaner payload
        event_data = {k: v for k, v in event_data.items() if v is not None}

        # Emit over WebSocket so frontend can consume
        self.socketio.emit("conference_event", event_data)

        # Server-side log for debugging/tracing
        current_app.logger.info("📢 Conference event emitted: %s", event_data)

        # Twilio expects a 2xx; 204 avoids extra bytes
        return "", 204 