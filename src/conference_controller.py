from flask import Blueprint, current_app, jsonify, request, url_for, abort
from twilio.twiml.voice_response import VoiceResponse, Start, Stream
from dotenv import load_dotenv
import os
from src.utils import xml_response
from src.conference_events_handler import ConferenceEventsHandler

load_dotenv()

conference_bp = Blueprint('conference', __name__)

CALLER_ID = os.getenv('CALLER_ID')

def str2bool(val, default=False):
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ('true', '1', 'yes')
    return default

def get_value(obj, key):
    try:
        return obj[key]
    except (KeyError, TypeError):
        return None

@conference_bp.route('/join_conference', methods=['POST', 'GET'])
def join_conference():
    conference_name = request.args.get('conference_name', 'DefaultRoom')
    current_app.logger.info("🎪 join_conference invoked", extra={"params": request.args.to_dict()})
    caller_identity = request.args.get('identity', None)
    start_conference_on_enter = str2bool(request.args.get('start_conference_on_enter'), True)
    end_conference_on_exit = str2bool(request.args.get('end_conference_on_exit'), True)
    muted = str2bool(request.args.get('mute'), False)
    participant_label = request.args.get('participant_label', 'DefaultParticipant')
    stream_audio = str2bool(request.args.get('stream_audio'), False)
    hold_on_conference_join = str2bool(request.args.get('hold_on_conference_join'), False)
    play_temporary_greeting = str2bool(request.args.get('play_temporary_greeting'), False)
    add_to_conference = request.args.get('add_to_conference', None)
    participant_role = request.args.get('participant_role', None)

    response = VoiceResponse()

    def sc_url():
        base = url_for('conference.conference_events', _external=True)
        params = []
        if caller_identity:
            current_app.logger.debug("🎪 Caller identity present for conference: %s", conference_name)
            params.append(f"identity={caller_identity}")
        if stream_audio:
            params.append("stream_audio=true")
        if hold_on_conference_join:
            params.append("hold_on_conference_join=true")
        if play_temporary_greeting:
            params.append("play_temporary_greeting=true")
        if add_to_conference:
            params.append(f"add_to_conference={add_to_conference}")
        if participant_role:
            params.append(f"participant_role={participant_role}")
        return f"{base}?{'&'.join(params)}" if params else base

    dial = response.dial()
    dial.conference(
        conference_name,
        wait_url=url_for("hold.hold_music", _external=True),
        wait_method='POST',
        start_conference_on_enter=start_conference_on_enter,
        end_conference_on_exit=end_conference_on_exit,
        muted=muted,
        beep=False,
        participant_label=participant_label,
        record='record-from-start',
        status_callback=sc_url(),
        status_callback_method='POST',
        status_callback_event='start end join leave hold mute',
        recording_status_callback=url_for('conference.conference_recording_events', _external=True),
        recording_status_callback_method='POST',
        recording_status_callback_event='in-progress completed absent'
    )
    current_app.logger.info("🎪 join_conference processing complete")
    return xml_response(response)

@conference_bp.route('/conference-events', methods=['POST', 'GET'])
def conference_events():
    """Webhook endpoint for Twilio conference status callbacks."""
    current_app.logger.info("🎪 conference_events endpoint invoked")
    socketio = current_app.config['socketio']

    resp = ConferenceEventsHandler(socketio).handle(request)
    current_app.logger.info("🎪 conference_events endpoint processing complete")
    return resp

@conference_bp.route('/connect_to_conference', methods=['POST', 'GET'])
def connect_to_conference():
    conference_name = request.args.get('conference_name', 'DefaultRoom')
    current_app.logger.info("🎪 connect_to_conference invoked", extra={"params": request.args.to_dict()})
    response = VoiceResponse()

    caller_identity = None
    from_header = request.values.get('From') or ''
    to_header = request.values.get('To') or ''
    if from_header.startswith('client:'):
        caller_identity = from_header[len('client:'):]
    elif to_header.startswith('client:'):
        caller_identity = to_header[len('client:'):]

    def sc_url():
        base = url_for('conference.conference_events', _external=True)
        if caller_identity:
            return f"{base}?identity={caller_identity}"
        return base

    dial = response.dial()
    dial.conference(
        conference_name,
        start_conference_on_enter=True,
        end_conference_on_exit=True,
        record='record-from-start',
        status_callback=sc_url(),
        status_callback_method='POST',
        status_callback_event='start end join leave hold mute',
        recording_status_callback=url_for('conference.conference_recording_events', _external=True),
        recording_status_callback_method='POST',
        recording_status_callback_event='in-progress completed absent'
    )
    current_app.logger.info("🎪 connect_to_conference processing complete")
    return xml_response(response)

@conference_bp.route('/conference-announcement', methods=['POST', 'GET'])
def conference_announcement():
    response = VoiceResponse()
    response.say("You are being joined back into the call.", voice='alice', language='en-US')
    return xml_response(response)

@conference_bp.route('/conference/<conference_name>/participants', methods=['GET'])
def get_conference_participants(conference_name):
    current_app.logger.info("🎪 get_conference_participants invoked", extra={"conference_name": conference_name})
    redis = current_app.config['redis']
    participants = redis.get(conference_name, {}).get('participants', {})
    result = []
    for sid, info in participants.items():
        # Skip any participant that has already left the conference
        if info.get('left'):
            continue
        result.append({
            'participant_label': info.get('participant_label'),
            'muted': info.get('muted'),
            'on_hold': info.get('on_hold'),
            'call_sid': info.get('call_sid'),
            'role': info.get('role'),
        })
    current_app.logger.info("🎪 get_conference_participants processing complete")
    return jsonify(result)

@conference_bp.route('/conference/mute', methods=['POST'])
def mute_participant():
    data = request.get_json()
    current_app.logger.info("🎪 mute_participant invoked", extra={"payload": data})
    conference_name = data.get('conference_name')
    call_sid = data.get('call_sid')
    mute = data.get('mute', True)
    redis = current_app.config['redis']
    client = current_app.config['twilio_client']
    conf_sid = redis.get(conference_name, {}).get('conference_sid')
    if not conf_sid or not call_sid:
        return abort(400, 'Missing conference_sid or call_sid')
    try:
        client.conferences(conf_sid).participants(call_sid).update(muted=bool(mute))

        p = redis[conference_name]['participants'].get(call_sid)
        if p:
            p['muted'] = bool(mute)
        current_app.logger.info("🎪 mute_participant processing complete")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@conference_bp.route('/conference/hold', methods=['POST'])
def hold_participant():
    data = request.get_json()
    current_app.logger.info("🎪 hold_participant invoked", extra={"payload": data})
    conference_name = data.get('conference_name')
    call_sid = data.get('call_sid')
    hold = data.get('hold', True)
    redis = current_app.config['redis']
    client = current_app.config['twilio_client']
    conf_sid = redis.get(conference_name, {}).get('conference_sid')
    if not conf_sid or not call_sid:
        return abort(400, 'Missing conference_sid or call_sid')
    try:
        client.conferences(conf_sid).participants(call_sid).update(hold=bool(hold))

        p = redis[conference_name]['participants'].get(call_sid)
        if p:
            p['on_hold'] = bool(hold)
        current_app.logger.info("🎪 hold_participant processing complete")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@conference_bp.route('/conference/kick', methods=['POST'])
def kick_participant():
    data = request.get_json()
    current_app.logger.info("🎪 kick_participant invoked", extra={"payload": data})
    conference_name = data.get('conference_name')
    call_sid = data.get('call_sid')

    requester_call_sid = request.args.get('call_sid') or data.get('requester_call_sid')
    if requester_call_sid and call_sid == requester_call_sid:
        return jsonify({'success': False, 'error': 'You cannot kick yourself.'}), 400
    redis = current_app.config['redis']
    client = current_app.config['twilio_client']
    conf_sid = redis.get(conference_name, {}).get('conference_sid')
    if not conf_sid or not call_sid:
        return abort(400, 'Missing conference_sid or call_sid')
    try:
        client.conferences(conf_sid).participants(call_sid).delete()

        p = redis[conference_name]['participants'].get(call_sid)
        if p:
            p['left'] = True
        current_app.logger.info("🎪 kick_participant processing complete")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@conference_bp.route('/conference-recording-events', methods=['POST', 'GET'])
def conference_recording_events():
    """Webhook endpoint for Twilio recording status callbacks."""
    current_app.logger.info("🎪 conference_recording_events endpoint invoked", extra={"params": request.values.to_dict()})

    socketio = current_app.config['socketio']

    # Broadcast the recording event details over websocket so clients can react in real-time.
    event_data = request.values.to_dict()
    socketio.emit("conference_recording_event", event_data)

    current_app.logger.info("🎪 conference_recording_events endpoint processing complete")
    # Twilio expects a 200 (empty) or 204 response.
    return "", 204
