import os
import threading
import time

from flask import current_app, url_for
from flask_socketio import SocketIO


def str2bool(val, default=False):
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return default


class ConferenceEventsHandler:
    """Encapsulates the business logic for processing Twilio conference-status
    callbacks.
    """

    def __init__(self, socketio: SocketIO):
        self.socketio = socketio

    def handle(self, flask_request):
        """Process the incoming Flask request and emit a structured Socket.IO
        event.
        """
        values = flask_request.values

        # Build a concise contextual message for quick readability
        event_type_preview = values.get("StatusCallbackEvent")
        conference_name_preview = values.get("FriendlyName")
        current_app.logger.info(
            "🎤 conference_events_handler %s for conference %s",
            event_type_preview,
            conference_name_preview,
            extra={
                "params": {**values.to_dict(), **flask_request.args.to_dict()}
            },
        )

        identity = flask_request.args.get(
            "identity"
        ) or flask_request.values.get("identity")
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
        redis = current_app.config["redis"]
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

        current_app.logger.debug(
            "Redis conference snapshot: %s", redis.get(friendly_name)
        )
        if event_type == "participant-leave":
            # Twilio sometimes sends the participant's SID under the ParticipantSid parameter instead
            # of CallSid.  Fall back to that when CallSid is missing so that we correctly flag the
            # departing participant in our in-memory cache.
            leave_sid = call_sid or values.get("ParticipantSid")
            if leave_sid in participants:
                participants[leave_sid]["left"] = True
        try:
            if event_type == "participant-unhold":
                role = redis[friendly_name]["calls"][call_sid]["role"]
                current_app.logger.debug("🎤 role: %s", role)
                call_info = redis[friendly_name]["calls"].get(call_sid, {})
                stream_audio_flag = str2bool(
                    call_info.get("stream_audio", False)
                )
                if stream_audio_flag:
                    client = current_app.config["twilio_client"]
                    app = current_app._get_current_object()

                    threading.Thread(
                        target=self._start_media_stream,
                        args=(client, call_sid, participant_label, app),
                        daemon=True,
                    ).start()

            if event_type == "participant-hold":
                role = redis[friendly_name]["calls"][call_sid]["role"]
                current_app.logger.debug("🎤 role: %s", role)
                call_info = redis[friendly_name]["calls"].get(call_sid, {})
                stream_audio_flag = str2bool(
                    call_info.get("stream_audio", False)
                )
                if stream_audio_flag:
                    try:
                        client = current_app.config["twilio_client"]
                        client.calls(call_sid).streams(
                            participant_label
                        ).update(status="stopped")
                    except Exception as e:
                        current_app.logger.error(
                            f"No stream to stop on {call_sid} leg: {e}"
                )
                if role == "customer":
                    add_to_conference = call_info.get(
                        "add_to_conference", False
                    )
                    if add_to_conference:
                        participant_role = call_info.get(
                            "participant_role", None
                        )
                        identity = call_info.get("participant_identity", None)
                        current_app.logger.debug(
                            "🎤 Adding participant %s to conference %s",
                            participant_label,
                            add_to_conference,
                        )
                        client = current_app.config["twilio_client"]
                        app = current_app._get_current_object()

                        threading.Thread(
                            target=self._add_participant_to_conference,
                            args=(
                                client,
                                conference_sid,
                                friendly_name,
                                app,
                                add_to_conference,
                                participant_role,
                                identity,
                                True,
                            ),
                            daemon=True,
                        ).start()
            if event_type == "participant-join":
                role = redis[friendly_name]["calls"][call_sid]["role"]
                current_app.logger.debug("🎤 role: %s", role)
                call_info = redis[friendly_name]["calls"].get(call_sid, {})
                hold_on_conference_join = str2bool(
                    call_info.get("hold_on_conference_join", False)
                )
                play_temporary_greeting = str2bool(
                    call_info.get(
                        "play_temporary_greeting_to_participant", False
                    )
                )
                stream_audio_flag = str2bool(
                    call_info.get("stream_audio", False)
                )
                current_app.logger.debug(
                    "🎤 hold_on_conference_join: %s for call_sid: %s",
                    hold_on_conference_join,
                    call_sid,
                )
                current_app.logger.debug(
                    "🎤 play_temporary_greeting: %s for call_sid: %s",
                    play_temporary_greeting,
                    call_sid,
                )
                current_app.logger.debug(
                    "🎤 stream_audio_flag: %s for call_sid: %s",
                    stream_audio_flag,
                    call_sid,
                )

                if role == "agent":
                    call_info = redis[friendly_name]["calls"].get(call_sid, {})
                    add_to_conference = call_info.get(
                        "add_to_conference", False
                    )
                    if add_to_conference:
                        participant_role = redis[friendly_name]["calls"][
                            call_sid
                        ]["participant_role"]
                        identity = redis[friendly_name]["calls"][call_sid][
                            "participant_identity"
                        ]
                        current_app.logger.debug(
                            "🎤 Adding participant %s to conference %s",
                            participant_label,
                            add_to_conference,
                        )
                        client = current_app.config["twilio_client"]
                        app = current_app._get_current_object()

                        threading.Thread(
                            target=self._add_participant_to_conference,
                            args=(
                                client,
                                conference_sid,
                                friendly_name,
                                app,
                                add_to_conference,
                                participant_role,
                                identity,
                                True,
                                False,
                            ),
                            daemon=True,
                        ).start()

                if hold_on_conference_join:
                    current_app.logger.debug(
                        "🎤 Placing participant %s on hold (call_sid=%s)",
                        redis[friendly_name]["calls"][call_sid]["call_tag"],
                        call_sid,
                    )
                    client = current_app.config["twilio_client"]
                    app = current_app._get_current_object()

                    threading.Thread(
                        target=self._put_participant_on_hold,
                        args=(
                            client,
                            conference_sid,
                            call_sid,
                            friendly_name,
                            redis,
                            url_for,
                            app,
                        ),
                        daemon=True,
                    ).start()

                if play_temporary_greeting:
                    current_app.logger.debug(
                        "🎤 Playing temporary greeting for participant %s (call_sid=%s)",
                        redis[friendly_name]["calls"][call_sid]["call_tag"],
                        call_sid,
                    )
                    client = current_app.config["twilio_client"]
                    app = current_app._get_current_object()

                    threading.Thread(
                        target=self._play_temporary_greeting,
                        args=(
                            client,
                            conference_sid,
                            call_sid,
                            friendly_name,
                            redis,
                            url_for,
                            app,
                        ),
                        daemon=True,
                    ).start()

                current_app.logger.info(
                    "🎤 event_type: %s and stream_audio_flag: %s and call_sid: %s and participant_label: %s",
                    event_type,
                    stream_audio_flag,
                    call_sid,
                    participant_label,
                )
                if stream_audio_flag and not hold_on_conference_join:
                    client = current_app.config["twilio_client"]
                    app = current_app._get_current_object()

                    threading.Thread(
                        target=self._start_media_stream,
                        args=(client, call_sid, participant_label, app),
                        daemon=True,
                    ).start()

        except KeyError:
            current_app.logger.debug(
                "Unhandled KeyError while processing event %s for call %s in conf %s",
                event_type,
                call_sid,
                friendly_name,
            )

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

        current_app.logger.debug(
            "Emit targets calculated: identity=%s participant_label=%s",
            identity,
            participant_label,
        )
        current_app.logger.debug("Event data prepared: %s", event_data)

        # Collect target Socket.IO rooms.
        targets: set[str] = set()
        if identity:
            targets.add(identity)
        if participant_label and participant_label != identity:
            targets.add(participant_label)

        # Also include the agent that originally created the conference.
        created_by = redis.get(friendly_name, {}).get("created_by")
        if created_by:
            targets.add(created_by)

        # Emit to each distinct room so every agent sees up-to-date status.
        if targets:
            for room in targets:
                current_app.logger.debug(
                    "Emitting conference_event to room: %s", room
                )
                self.socketio.emit("conference_event", event_data, room=room)
        else:
            # Fallback: broadcast globally if we somehow have no target rooms.
            self.socketio.emit("conference_event", event_data)

        current_app.logger.debug("🎤 Conference event emitted: %s", event_data)

        # Info-level: completion
        current_app.logger.info(
            "🎤 conference_events_handler processing complete"
        )

        return "", 204

    def _put_participant_on_hold(
        self,
        client,
        conference_sid,
        call_sid,
        friendly_name,
        redis,
        url_for_func,
        app,
    ):
        with app.app_context():
            for attempt in range(5):
                try:
                    client.conferences(conference_sid).participants(
                        call_sid
                    ).update(
                        hold=True,
                        hold_url=url_for_func("hold.hold_music"),
                        hold_method="POST",
                    )
                    redis[friendly_name]["participants"][call_sid][
                        "on_hold"
                    ] = True
                    current_app.logger.debug(
                        "🎤 Successfully put %s on hold (attempt %s)",
                        call_sid,
                        attempt + 1,
                    )
                    break
                except Exception as e:
                    current_app.logger.warning(
                        "Retry %s/5 - Failed to put %s on hold: %s",
                        attempt + 1,
                        call_sid,
                        e,
                    )
                    time.sleep(1)

    def _play_temporary_greeting(
        self,
        client,
        conference_sid,
        call_sid,
        friendly_name,
        redis,
        url_for_func,
        app,
    ):
        with app.app_context():
            for attempt in range(5):
                try:
                    client.conferences(conference_sid).participants(
                        call_sid
                    ).update(
                        announce_url=url_for_func(
                            "greet.temporary_message", _external=True
                        )
                    )
                    redis[friendly_name]["participants"][call_sid][
                        "play_temporary_greeting"
                    ] = False
                    current_app.logger.debug(
                        "🎤 Successfully played temporary greeting for %s (attempt %s)",
                        call_sid,
                        attempt + 1,
                    )
                    break
                except Exception as e:
                    current_app.logger.warning(
                        "Retry %s/5 - Failed to play temporary greeting for %s: %s",
                        attempt + 1,
                        call_sid,
                        e,
                    )
                    time.sleep(1)

    def _start_media_stream(self, client, call_sid, participant_label, app):
        """Start a Media Stream on the specified call so audio is sent to the
        websocket.
        """
        with app.app_context():
            current_app.logger.info("🎤 Starting media stream for %s", call_sid)
            stream_url = os.getenv("TRANSCRIPTION_WEBSOCKET_URL")
            if not stream_url:
                current_app.logger.warning(
                    "TRANSCRIPTION_WEBSOCKET_URL not set; skipping media stream start"
                )
                return

            for attempt in range(3):
                try:
                    redis = current_app.config["redis"]

                    call_info = redis.get(call_sid, {})
                    conference_info_of_call = call_info.get("conference", {})
                    conference_name = conference_info_of_call.get(
                        "conference_name"
                    )
                    global_conference_info = redis.get(conference_name, {})
                    recording_start_time_epoch = global_conference_info.get(
                        "recording_start_time", 0
                    )
                    current_app.logger.debug(
                        "recording_start_time_epoch: %s in _start_media_stream of conference_events_handler.py",
                        recording_start_time_epoch,
                    )

                    client.calls(call_sid).streams.create(
                        url=stream_url,
                        track="both_tracks",
                        name=participant_label,
                        **{
                            "parameter1_name": "call_flow_type",
                            "parameter1_value": "conference",
                            "parameter2_name": "track0_label",
                            "parameter2_value": "conference",
                            "parameter3_name": "track1_label",
                            "parameter3_value": participant_label,
                            "parameter4_name": "stream_start_time_in_epoch_seconds",
                            "parameter4_value": time.time(),
                            "parameter5_name": "recording_start_time_in_epoch_seconds",
                            "parameter5_value": recording_start_time_epoch,
                        },
                    )
                    current_app.logger.warning(
                        "current time in epoch when the participant: %s was unheld: %s",
                        participant_label,
                        time.time(),
                    )
                    current_app.logger.debug(
                        "🎤 Successfully started media stream for %s (attempt %s)",
                        call_sid,
                        attempt + 1,
                    )
                    break
                except Exception as e:
                    current_app.logger.warning(
                        "Retry %s/3 - Failed to start media stream for %s: %s",
                        attempt + 1,
                        call_sid,
                        e,
                    )
                    time.sleep(1)

    def _add_participant_to_conference(
        self,
        client,
        conference_sid,
        friendly_name,
        app,
        add_to_conference,
        participant_role,
        identity,
        stream_audio,
        kick=True,
    ):
        participant_label = (
            add_to_conference[7:]
            if add_to_conference.startswith("client:")
            else add_to_conference
        )
        participant_identity = (
            participant_label
            if add_to_conference.startswith("client:")
            else None
        )

        to_is_client = add_to_conference.startswith("client:")
        if to_is_client:
            import re

            slug = re.sub(r"[^A-Za-z0-9_\-]", "-", friendly_name)[
                :80
            ]  # keep short
            caller_id = f"client:conference-of-{slug}"
        else:
            caller_id = current_app.config.get("TWILIO_CALLER_ID") or os.getenv(
                "CALLER_ID"
            )

        def _status_callback_url():
            base = url_for("events.call_events", _external=True)
            params = []
            if identity:
                params.append(f"identity={identity}")
            if stream_audio:
                params.append("stream_audio=true")
            return f"{base}?{'&'.join(params)}" if params else base

        with app.app_context():
            current_app.logger.debug(
                "🔀 Adding participant to conference %s: phone=%s identity=%s",
                conference_sid,
                add_to_conference,
                identity,
            )
            current_app.logger.debug(
                "Participant identity=%s label=%s",
                participant_identity,
                participant_label,
            )
            call = client.conferences(conference_sid).participants.create(
                to=add_to_conference,
                from_=caller_id,
                early_media=True,
                end_conference_on_exit=False,
                beep=False,
                muted=True,
                label=participant_label,
                conference_status_callback_method="POST",
                conference_status_callback_event="start end join leave hold mute",
                status_callback=_status_callback_url(),
                status_callback_method="GET",
                status_callback_event=[
                    "initiated",
                    "ringing",
                    "answered",
                    "completed",
                ],
            )
            call_sid = call.call_sid

            redis = current_app.config["redis"]
            if friendly_name not in redis:
                redis[friendly_name] = {
                    "created_by": identity,
                    "calls": {},
                    "participants": {},
                }

            redis[friendly_name]["calls"][call_sid] = {
                "call_tag": participant_label,
                "role": participant_role,
                "hold_on_conference_join": False,
                "play_temporary_greeting_to_participant": (
                    True if participant_role == "agent" else False
                ),
            }

            redis[call_sid] = {
                "stream_audio": stream_audio,
                "participant_label": participant_label,
                "muted": True,
                "on_hold": False,
                "role": participant_role,
                "conference": {
                    "conference_sid": conference_sid,
                    "conference_name": friendly_name,
                    "on_hold": False,
                    "role": participant_role,
                    "start_conference_on_enter": False,
                    "end_conference_on_exit": False,
                    "kick_participant_from_conference": kick,
                    "update_participant_in_conference": True,
                },
            }
