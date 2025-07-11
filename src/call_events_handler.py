import os
import threading
import time
from flask_socketio import SocketIO
from flask import current_app

def str2bool(val, default=False):
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ('true', '1', 'yes')
    return default

class CallEventsHandler:
    """Encapsulates the business logic for processing Twilio call-event webhooks."""

    def __init__(self, socketio: SocketIO, call_log: dict):
        self.socketio = socketio
        self.call_log = call_log

    def handle(self, flask_request):
        """Process the incoming Flask request and emit events."""
        current_app.logger.info("📞 call_events_handler invoked", extra={"params": {**flask_request.values.to_dict(), **flask_request.args.to_dict()}})
        identity = flask_request.args.get('identity') or flask_request.values.get('identity')
        sid = flask_request.values.get('CallSid')
        parent_sid = flask_request.values.get('ParentCallSid')
        status = flask_request.values.get('CallStatus')
        from_number = flask_request.values.get('From')
        to_number = flask_request.values.get('To')
        timestamp = time.time()
        duration = flask_request.values.get('CallDuration')

        current_app.logger.debug("📞 Parsed params: from_number=%s to_number=%s status=%s", from_number, to_number, status)

        call_type = 'child' if parent_sid else 'parent'

        self._emit_parent_child_sids(call_type, sid, parent_sid, identity)

        log_key = self._ensure_log_entry(sid, parent_sid, call_type)

        self.call_log[log_key]['events'].append({
            'status': status,
            'from': from_number,
            'to': to_number,
            'timestamp': timestamp,
            'duration': duration,
        })

        if status == 'ringing':
            self.call_log[log_key]['ringing_time'] = timestamp
        elif status == 'in-progress':
            redis = current_app.config['redis']

            call_info = redis.get(sid, {})
            call_conference_info = call_info.get('conference', {})
            conference_name = call_conference_info.get('conference_name', None)
            conference_info = redis.get(conference_name, {})
            stream_audio = str2bool(call_info.get('stream_audio', False))
            kick_participant_from_conference = str2bool(call_conference_info.get('kick_participant_from_conference', False))
            update_participant_in_conference = str2bool(call_conference_info.get('update_participant_in_conference', False))
            current_app.logger.info("*************** Call Events Handler ********************")
            current_app.logger.info(redis)
            current_app.logger.info(call_info)
            current_app.logger.info(call_conference_info)
            current_app.logger.info(conference_name)
            current_app.logger.info(conference_info)
            current_app.logger.info(kick_participant_from_conference)
            current_app.logger.info(stream_audio)
            current_app.logger.info(update_participant_in_conference)
            current_app.logger.info("*************** Call Events Handler ********************")

            if update_participant_in_conference:
                conference_info['participants'][sid] = {
                    'participant_label': call_info.get('participant_label', None),
                    'call_sid': sid,
                    'muted': True,
                    'on_hold': False,
                    'role': call_info.get('role', None),
                }

            if kick_participant_from_conference:
                all_calls = conference_info["calls"]
                for call_sid, call_info in all_calls.items():
                   if call_info.get('role') == 'ai-voice-agent':
                       client = current_app.config['twilio_client']
                       client.conferences(conference_info["conference_sid"]).participants(call_sid).delete()
                       current_app.logger.info("🎤 Kicked participant %s from conference %s", call_info["call_tag"], conference_info["conference_name"])
            if stream_audio:
                participant_label = redis[sid]['participant_label']
                client = current_app.config['twilio_client']
                app = current_app._get_current_object()

                threading.Thread(
                    target=self._start_media_stream,
                    args=(client, sid, participant_label, app),
                    daemon=True
                ).start()
            self.call_log[log_key]['answered_time'] = timestamp
        elif status in ['completed', 'no-answer', 'busy', 'failed']:
            self.call_log[log_key]['end_time'] = timestamp

        self._emit_status_event(call_type, sid, parent_sid, status, from_number, to_number, timestamp, duration, identity)

        self._maybe_emit_ring_duration(log_key, call_type, sid, parent_sid, timestamp, identity)

        current_app.logger.info("📞 call_events_handler processing complete for call_sid: %s (status: %s)", sid, status)
        return '', 204
    
    def _start_media_stream(self, client, call_sid, participant_label, app):
        """Start a Media Stream on the specified call so audio is sent to the websocket."""
        with app.app_context():
            current_app.logger.info("*************** Call Events Handler ********************")
            current_app.logger.info("🎤 Starting media stream for %s", call_sid)
            stream_url = os.getenv('TRANSCRIPTION_WEBSOCKET_URL')
            if not stream_url:
                current_app.logger.warning("TRANSCRIPTION_WEBSOCKET_URL not set; skipping media stream start")
                return

            for attempt in range(3):
                try:
                    client.calls(call_sid).streams.create(
                        url=stream_url,
                        track='both_tracks',
                        name=participant_label,
                        **{
                            'parameter1_name': 'call_flow_type',
                            'parameter1_value': 'conference',
                            'parameter2_name': 'track0_label',
                            'parameter2_value': 'conference',
                            'parameter3_name': 'track1_label',
                            'parameter3_value': participant_label,
                        }
                    )
                    current_app.logger.debug("🎤 Successfully started media stream for %s (attempt %s)", call_sid, attempt + 1)
                    break
                except Exception as e:
                    current_app.logger.warning("Retry %s/3 - Failed to start media stream for %s: %s", attempt + 1, call_sid, e)
                    time.sleep(1)


    def _emit_parent_child_sids(self, call_type: str, sid: str, parent_sid: str | None, identity: str | None):

        if identity is None:
            return

        if call_type == 'parent':
            if not self.call_log.get(sid, {}).get('parent_sid_emitted'):
                self.socketio.emit("parent_call_sid", {"parent_sid": sid}, room=identity)
                self.call_log.setdefault(sid, {})['parent_sid_emitted'] = True

        if call_type == 'child':
            if not self.call_log.get(parent_sid, {}).get('parent_sid_emitted'):
                self.socketio.emit("parent_call_sid", {"parent_sid": parent_sid}, room=identity)
                self.call_log.setdefault(parent_sid, {})['parent_sid_emitted'] = True

            if not self.call_log.get(sid, {}).get('child_sid_emitted'):
                self.socketio.emit("child_call_sid", {"child_sid": sid, "parent_sid": parent_sid}, room=identity)
                self.call_log.setdefault(sid, {})['child_sid_emitted'] = True

    def _ensure_log_entry(self, sid: str, parent_sid: str | None, call_type: str) -> str:
        log_key = sid
        if log_key not in self.call_log:
            self.call_log[log_key] = {
                'sid': sid,
                'parent_sid': parent_sid,
                'type': call_type,
                'events': [],
                'ringing_time': None,
                'answered_time': None,
                'end_time': None,
                'ring_duration_emitted': False,
            }
        else:
            entry = self.call_log[log_key]
            entry.setdefault('sid', sid)
            entry.setdefault('parent_sid', parent_sid)
            entry.setdefault('type', call_type)
            entry.setdefault('events', [])
            entry.setdefault('ringing_time', None)
            entry.setdefault('answered_time', None)
            entry.setdefault('end_time', None)
            entry.setdefault('ring_duration_emitted', False)
        return log_key

    def _emit_status_event(self, call_type, sid, parent_sid, status, from_number, to_number, timestamp, duration, identity: str | None):
        if identity is None:
            return

        event_data = {
            'sid': sid,
            'parent_sid': parent_sid,
            'status': status,
            'from': from_number,
            'to': to_number,
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)),
            'type': call_type,
        }

        if status == 'answered':
            event_data['note'] = f"{call_type.capitalize()} call answered"
        elif status == 'ringing':
            event_data['note'] = f"{call_type.capitalize()} call is ringing"
        elif status == 'initiated':
            event_data['note'] = f"{call_type.capitalize()} call initiated"
        elif status == 'failed':
            event_data['note'] = f"{call_type.capitalize()} call failed"
        elif status == 'busy':
            event_data['note'] = f"{call_type.capitalize()} call got busy signal"
        elif status == 'no-answer':
            event_data['note'] = f"{call_type.capitalize()} call not answered"
        elif status == 'completed':
            event_data['note'] = (
                f"{call_type.capitalize()} call completed in {duration}s" if duration and int(duration) > 0 else f"{call_type.capitalize()} call completed (0s duration)"
            )

        self.socketio.emit("call_event", event_data, room=identity)

    def _maybe_emit_ring_duration(self, log_key, call_type, sid, parent_sid, timestamp, identity: str | None):
        if identity is None:
            return
        entry = self.call_log[log_key]
        if (
            entry['ringing_time'] is not None and
            entry['end_time'] is not None and
            not entry['ring_duration_emitted']
        ):
            ring_duration = round(entry['end_time'] - entry['ringing_time'])
            ring_data = {
                'sid': sid,
                'parent_sid': parent_sid,
                'type': call_type,
                'timestamp': time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)),
                'note': f"{call_type.capitalize()} call rang for {ring_duration} seconds",
                'event': 'ring_duration',
            }
            self.socketio.emit("call_event", ring_data, room=identity)
            entry['ring_duration_emitted'] = True
