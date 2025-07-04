import time
from flask_socketio import SocketIO


class CallEventsHandler:
    """Encapsulates the business logic for processing Twilio call-event webhooks."""

    def __init__(self, socketio: SocketIO, call_log: dict):
        self.socketio = socketio
        self.call_log = call_log

    # ------------------------------------------------------------------
    # Public entry-point
    # ------------------------------------------------------------------
    def handle(self, flask_request):
        """Process the incoming Flask request and emit events."""
        sid = flask_request.values.get('CallSid')
        parent_sid = flask_request.values.get('ParentCallSid')
        status = flask_request.values.get('CallStatus')
        from_number = flask_request.values.get('From')
        to_number = flask_request.values.get('To')
        timestamp = time.time()
        duration = flask_request.values.get('CallDuration')

        call_type = 'child' if parent_sid else 'parent'

        self._emit_parent_child_sids(call_type, sid, parent_sid)

        log_key = self._ensure_log_entry(sid, parent_sid, call_type)

        # Store this individual event
        self.call_log[log_key]['events'].append({
            'status': status,
            'from': from_number,
            'to': to_number,
            'timestamp': timestamp,
            'duration': duration,
        })

        # Track specific timestamps
        if status == 'ringing':
            self.call_log[log_key]['ringing_time'] = timestamp
        elif status == 'answered':
            self.call_log[log_key]['answered_time'] = timestamp
        elif status in ['completed', 'no-answer', 'busy', 'failed']:
            self.call_log[log_key]['end_time'] = timestamp

        # Emit general event
        self._emit_status_event(call_type, sid, parent_sid, status, from_number, to_number, timestamp, duration)

        # Maybe emit ring-duration event
        self._maybe_emit_ring_duration(log_key, call_type, sid, parent_sid, timestamp)

        return '', 204

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit_parent_child_sids(self, call_type: str, sid: str, parent_sid: str | None):
        # Parent SID emission
        if call_type == 'parent':
            if not self.call_log.get(sid, {}).get('parent_sid_emitted'):
                self.socketio.emit("parent_call_sid", {"parent_sid": sid})
                self.call_log.setdefault(sid, {})['parent_sid_emitted'] = True

        # Child SID emission
        if call_type == 'child':
            if not self.call_log.get(parent_sid, {}).get('parent_sid_emitted'):
                self.socketio.emit("parent_call_sid", {"parent_sid": parent_sid})
                self.call_log.setdefault(parent_sid, {})['parent_sid_emitted'] = True
                print(self.call_log)

            if not self.call_log.get(sid, {}).get('child_sid_emitted'):
                self.socketio.emit("child_call_sid", {"child_sid": sid, "parent_sid": parent_sid})
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

    def _emit_status_event(self, call_type, sid, parent_sid, status, from_number, to_number, timestamp, duration):
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

        self.socketio.emit("call_event", event_data)
        print(f"📞 {call_type.upper()} CALL EVENT:", event_data)

    def _maybe_emit_ring_duration(self, log_key, call_type, sid, parent_sid, timestamp):
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
            self.socketio.emit("call_event", ring_data)
            entry['ring_duration_emitted'] = True
            print(f"⏱️ RING DURATION EVENT:", ring_data)


# ---------------------------------------------------------------------------
# Backwards-compatibility thin wrapper
# ---------------------------------------------------------------------------


def handle_call_events(flask_request, socketio: SocketIO, call_log: dict):
    """Wrapper so existing imports continue to work after refactor."""
    return CallEventsHandler(socketio, call_log).handle(flask_request) 