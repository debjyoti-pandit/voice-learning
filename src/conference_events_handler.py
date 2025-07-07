from flask import current_app, url_for
from flask_socketio import SocketIO
import time
import threading

def str2bool(val, default=False):
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ('true', '1', 'yes')
    return default

class ConferenceEventsHandler:
    """Encapsulates the business logic for processing Twilio conference-status callbacks."""

    def __init__(self, socketio: SocketIO):
        self.socketio = socketio

    def handle(self, flask_request):
        """Process the incoming Flask request and emit a structured Socket.IO event."""
        values = flask_request.values

        # Build a concise contextual message for quick readability
        event_type_preview = values.get("StatusCallbackEvent")
        conference_name_preview = values.get("FriendlyName")
        current_app.logger.info(
            "🎤 conference_events_handler %s for conference %s",
            event_type_preview,
            conference_name_preview,
            extra={"params": {**values.to_dict(), **flask_request.args.to_dict()}}
        )

        identity = flask_request.args.get('identity') or flask_request.values.get('identity')
        current_app.logger.debug("🔍 Identity: %s", identity)

        event_type = values.get("StatusCallbackEvent")
        conference_sid = values.get("ConferenceSid")
        call_sid = values.get("CallSid")
        friendly_name = values.get("FriendlyName")
        sequence_number = values.get("SequenceNumber")
        timestamp = values.get("Timestamp")
        participant_label = values.get("ParticipantLabel")
        coaching = values.get("Coaching")
        end_conference_on_exit = values.get("EndConferenceOnExit")
        start_conference_on_enter = values.get("StartConferenceOnEnter")
        hold = str2bool(values.get("Hold"))
        muted = str2bool(values.get("Muted"))
        redis = current_app.config['redis']
        redis.setdefault(friendly_name, {})
        redis[friendly_name]["conference_sid"] = conference_sid
        redis[friendly_name].setdefault("participants", {})
        participants = redis[friendly_name]["participants"]
        calls = redis[friendly_name].get("calls", {})

        role = None
        if call_sid in calls:
            role = calls[call_sid].get("role")
        if not role:
            role = values.get("role")

        current_app.logger.debug(
            "Conference event received: %s | call_sid=%s sequence=%s participant=%s hold=%s muted=%s role=%s",
            event_type,
            call_sid,
            sequence_number,
            participant_label,
            hold,
            muted,
            role,
        )

        current_app.logger.debug("Redis conference snapshot: %s", redis.get(friendly_name))
        if event_type == "participant-leave":
            # Twilio sometimes sends the participant's SID under the ParticipantSid parameter instead
            # of CallSid.  Fall back to that when CallSid is missing so that we correctly flag the
            # departing participant in our in-memory cache.
            leave_sid = call_sid or values.get("ParticipantSid")
            if leave_sid in participants:
                participants[leave_sid]["left"] = True
        try:
            if event_type == "participant-join":
                current_app.logger.debug("Redis conference snapshot on participant-join: %s", redis.get(friendly_name))
                hold_on_conference_join = redis[friendly_name]["calls"][call_sid]['hold_on_conference_join'];
                if hold_on_conference_join:
                    current_app.logger.debug("🎤 Placing participant %s on hold (call_sid=%s)", redis[friendly_name]['calls'][call_sid]['call_tag'], call_sid)
                    client = current_app.config['twilio_client']
                    app = current_app._get_current_object()

                    threading.Thread(
                        target=self._put_participant_on_hold,
                        args=(client, conference_sid, call_sid, friendly_name, redis, url_for, app),
                        daemon=True
                    ).start()

                play_temporary_greeting = redis[friendly_name]["participants"][call_sid]['play_temporary_greeting']
                if play_temporary_greeting:
                    current_app.logger.debug("🎤 Playing temporary greeting for participant %s (call_sid=%s)", redis[friendly_name]['calls'][call_sid]['call_tag'], call_sid)
                    client = current_app.config['twilio_client']
                    app = current_app._get_current_object()

                    threading.Thread(
                        target=self._play_temporary_greeting,
                        args=(client, conference_sid, call_sid, friendly_name, redis, url_for, app),
                        daemon=True
                    ).start()
                
        except KeyError:
            current_app.logger.debug("Unhandled KeyError while processing event %s for call %s in conf %s", event_type, call_sid, friendly_name)
            return "", 204

        current_app.logger.debug("Processed hold/announcement logic")
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

        event_data = {k: v for k, v in event_data.items() if v is not None}

        current_app.logger.debug("Emit targets calculated: identity=%s participant_label=%s", identity, participant_label)
        current_app.logger.debug("Event data prepared: %s", event_data)
        if identity:
            if identity != participant_label:
                current_app.logger.debug("Emitting conference_event to participant room: %s", participant_label)
                self.socketio.emit("conference_event", event_data, room=participant_label)
            current_app.logger.debug("Emitting conference_event to identity room: %s", identity)
            self.socketio.emit("conference_event", event_data, room=identity)
        else:
            self.socketio.emit("conference_event", event_data)

        current_app.logger.debug("🎤 Conference event emitted: %s", event_data)

        # Info-level: completion
        current_app.logger.info("🎤 conference_events_handler processing complete")

        return "", 204

    def _put_participant_on_hold(self, client, conference_sid, call_sid, friendly_name, redis, url_for_func, app):
        with app.app_context():
            for attempt in range(5):
                try:
                    client.conferences(conference_sid).participants(call_sid).update(
                        hold=True,
                        hold_url=url_for_func('hold.hold_music'),
                        hold_method='POST'
                    )
                    redis[friendly_name]["participants"][call_sid]["on_hold"] = True
                    current_app.logger.debug("🎤 Successfully put %s on hold (attempt %s)", call_sid, attempt+1)
                    break
                except Exception as e:
                    current_app.logger.warning("Retry %s/5 - Failed to put %s on hold: %s", attempt+1, call_sid, e)
                    time.sleep(1)

    def _play_temporary_greeting(self, client, conference_sid, call_sid, friendly_name, redis, url_for_func, app):
        with app.app_context():
            for attempt in range(5):
                try:
                    client.conferences(conference_sid).participants(call_sid).update(
                        announce_url=url_for_func('greet.temporary_message', _external=True)
                    )
                    redis[friendly_name]["participants"][call_sid]['play_temporary_greeting'] = False
                    current_app.logger.debug("🎤 Successfully played temporary greeting for %s (attempt %s)", call_sid, attempt+1)
                    break
                except Exception as e:
                    current_app.logger.warning("Retry %s/5 - Failed to play temporary greeting for %s: %s", attempt+1, call_sid, e)
                    time.sleep(1)
