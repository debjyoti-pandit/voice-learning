from flask import Blueprint, request, url_for, current_app, jsonify
from twilio.twiml.voice_response import VoiceResponse, Start, Stream
from dotenv import load_dotenv
import os
from src.utils import xml_response

load_dotenv()

voice_bp = Blueprint('voice', __name__)

CALLER_ID = os.getenv('CALLER_ID')

@voice_bp.route('/voice', methods=['POST'])
def voice():
    to_number = request.values.get('To')
    response = VoiceResponse()

    stream_url = os.getenv('TRANSCRIPTION_WEBSOCKET_URL')
    start = Start()
    stream = Stream(url=stream_url, track='both_tracks', name="initial_call_recording")
    stream.parameter(name='call_flow_type', value="normal")
    stream.parameter(name='track0_label', value="divyanshu_call_track_0")
    stream.parameter(name='track1_label', value="aiva")
    start.append(stream)
    response.append(start)

    if to_number:
        dial = response.dial(
            caller_id=CALLER_ID,
            action=url_for('voice.hangup_call', _external=True),
            method='POST',
            timeout=20,
            record='record-from-answer-dual'
        )
        caller_identity = None
        from_header = request.values.get('From') or ''
        if from_header.startswith('client:'):
            caller_identity = from_header[len('client:'):]

        def sc_url():
            base = url_for('events.call_events', _external=True)
            if caller_identity:
                return f"{base}?identity={caller_identity}"
            return base

        if to_number.startswith('client:'):
            client_name = to_number[len('client:'):]
            dial.client(
                client_name,
                status_callback=sc_url(),
                status_callback_method='GET',
                status_callback_event='initiated ringing answered completed',
            )
        else:
            dial.number(
                to_number,
                status_callback=sc_url(),
                status_callback_method='GET',
                status_callback_event='initiated ringing answered completed',
            )
    else:
        response.say("No destination provided. Please specify a client or phone number.")

    return xml_response(response)

@voice_bp.route('/hangup', methods=['GET', 'POST'])
def hangup_call():
    """Terminate the current call leg."""
    redis = current_app.config['redis']
    call_id = request.values.get('CallSid')
    current_app.logger.info("📞 hangup_call invoked", extra={"params": request.values.to_dict()})
    if call_id in redis:
        redis_data = redis[call_id];
        if redis_data['child_call_moved_to_conference']:
            conference_name = redis_data['conference']['conference_name']
            participant_label = redis_data['participant_label']
            start_conference_on_enter = redis_data['conference']['start_conference_on_enter']
            end_conference_on_exit = redis_data['conference']['end_conference_on_exit']
            on_hold = redis_data['conference']['on_hold']
            mute = redis_data['conference']['mute']
            role = redis_data['conference']['role']
            identity = redis_data['identity']
            stream_audio = redis_data['stream_audio']

            client = current_app.config['twilio_client']
            current_app.logger.debug("📞 Updating parent call %s to join conference %s", call_id, conference_name)
            client.calls(call_id).update(
                url=url_for('conference.join_conference', _external=True, 
                            conference_name=conference_name, 
                            participant_label=participant_label, 
                            start_conference_on_enter=start_conference_on_enter, 
                            end_conference_on_exit=end_conference_on_exit, 
                            mute=mute, 
                            role=role, 
                            identity=identity, 
                            stream_audio=stream_audio),
                method='POST',
            )
            current_app.logger.debug("📞 Parent call %s joined conference %s update completed", call_id, conference_name)

            redis[conference_name]['participants'][call_id] = {
                'participant_label': participant_label,
                'call_sid': call_id,
                'muted': mute,
                'on_hold': on_hold,
                'role': role,
            }
            # Respond with an empty TwiML document to acknowledge the request.
            empty_resp = VoiceResponse()
            return xml_response(empty_resp)
        
    current_app.logger.debug("📞 No conference context for call %s; proceeding to hangup", call_id)
    resp = VoiceResponse()
    resp.hangup()
    current_app.logger.info("📞 hangup_call processing complete")
    return xml_response(resp)

@voice_bp.route('/answer', methods=['GET', 'POST'])
def answer_call():
    """Play a simple thank-you message to the caller."""
    response = VoiceResponse()
    response.say("Thank you for calling! Have a great day.")
    caller_identity = None
    from_header = request.values.get('From') or ''
    if from_header.startswith('client:'):
        caller_identity = from_header[len('client:'):]

    def sc_url():
        base = url_for('events.call_events', _external=True)
        if caller_identity:
            return f"{base}?identity={caller_identity}"
        return base
    dial = response.dial(
        caller_id=CALLER_ID,
        action=url_for('voice.hangup_call', _external=True),
        method='POST',
        timeout=20,
        record='record-from-answer-dual'
    )
    dial.number(
        "+18559421624",
        status_callback=sc_url(),
        status_callback_method='GET',
        status_callback_event='initiated ringing answered completed',
    )
    return xml_response(response)

@voice_bp.route('/redirect-action', methods=['GET', 'POST'])
def redirect_action():
    """Redirect the current call to a new TwiML URL provided via the `url` parameter.

    This endpoint is designed to be used as the `action` attribute of TwiML verbs such
    as <Dial>. When Twilio requests this URL, the handler will look for a parameter
    named `url` (supplied either as a query-string parameter or a POST field). If a
    value is present, the call is redirected to that TwiML document; otherwise the
    call is gracefully hung up.
    """
    new_url = request.values.get('url') or request.args.get('url')

    response = VoiceResponse()
    if new_url:
        # Redirect the call flow to the provided TwiML URL.
        response.redirect(new_url, method='POST')
    else:
        # If no URL was supplied, end the call politely.
        response.say("No redirect URL provided. Goodbye.")
        response.hangup()

    return xml_response(response)

@voice_bp.route('/update-call-url', methods=['POST'])
def update_call_url():
    """Update an in-progress call's TwiML URL.

    Expects a JSON body **or** form-encoded parameters with:

    • ``call_sid`` – the SID of the call to update.
    • ``url`` – the new absolute URL that Twilio should request for further instructions.
    """
    # Accept both JSON payloads and form/query parameters for flexibility.
    data = request.get_json(silent=True) or request.values
    current_app.logger.info("🔄 update_call_url invoked", extra={"payload": data.to_dict() if hasattr(data, 'to_dict') else data})

    call_sid = data.get('call_sid') or request.args.get('call_sid')
    new_url = data.get('url') or request.args.get('url')

    if not call_sid or not new_url:
        return jsonify({
            'success': False,
            'error': 'Missing required parameter(s): call_sid and url are both needed.'
        }), 400

    client = current_app.config['twilio_client']

    try:
        current_app.logger.debug("🔄 Calling Twilio API to update call %s", call_sid)
        client.calls(call_sid).update(url=new_url, method='POST')
        current_app.logger.debug("🔄 Twilio update completed for call %s", call_sid)
        current_app.logger.info("🔄 update_call_url processing complete")
        return jsonify({'success': True, 'message': 'Call URL updated.'})
    except Exception as e:
        current_app.logger.error("🔄 Failed to update call %s: %s", call_sid, e)
        return jsonify({'success': False, 'error': str(e)}), 500
