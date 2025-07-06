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

        print(f"Event type: {event_type}, Call sid: {call_sid}, sequence number: {sequence_number}, timestamp: {timestamp}, participant label: {participant_label}, hold: {hold}, muted: {muted}, role: {role}")
                                 
        # if event_type in ("mute", "participant-hold"):
        #     print(participants)
        #     if call_sid in participants:
        #         print(call_sid)
        #         if event_type == "mute" and muted is not None:
        #             participants[call_sid]["muted"] = bool(muted)
        #         if event_type == "hold" and hold is not None:
        #             print('in hold change', bool(hold))
        #             participants[call_sid]["on_hold"] = bool(hold)
        if event_type == "participant-leave":
            if call_sid in participants:
                participants[call_sid]["left"] = True
        try:
            if event_type == "participant-join":
                hold_on_conference_join = redis[friendly_name]["calls"][call_sid]['hold_on_conference_join'];
                if hold_on_conference_join:
                    print(f"Holding on conference join for call label: {redis[friendly_name]['calls'][call_sid]['call_tag']}")
                    client = current_app.config['twilio_client']
                    app = current_app._get_current_object()
                                                                                
                    threading.Thread(
                        target=self._put_participant_on_hold,
                        args=(client, conference_sid, call_sid, friendly_name, redis, url_for, app),
                        daemon=True
                    ).start()
        except KeyError:
            print(f"Event type: {event_type}, Call sid: {call_sid}, Friendly name: {friendly_name}")
            return "", 204

        print("after trying to hold")                                                                                           
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

                                                     
        self.socketio.emit("conference_event", event_data)

                                               
        current_app.logger.info("📢 Conference event emitted: %s", event_data)

                                                      
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
                    print(f"Successfully put {call_sid} on hold on attempt {attempt+1}")
                    break
                except Exception as e:
                    print(f"[Retry {attempt+1}/5] Failed to put on hold: {e}")
                    time.sleep(1) 