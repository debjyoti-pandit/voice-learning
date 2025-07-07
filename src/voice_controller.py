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

    stream_url = f"wss://cowbird-above-globally.ngrok-free.app"
    start = Start()
    stream = Stream(url=stream_url, track='both_tracks', name="initial_call_recording")
    stream.parameter(name='call_flow_type', value="normal")
    stream.parameter(name='track0_label', value="divyanshu_call_track_0")
    stream.parameter(name='track1_label', value="aiva")
    start.append(stream)
    response.append(start)
    response.say('The stream has started.')

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
    resp = VoiceResponse()
    resp.hangup()
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

    call_sid = data.get('call_sid') or request.args.get('call_sid')
    new_url = data.get('url') or request.args.get('url')

    if not call_sid or not new_url:
        return jsonify({
            'success': False,
            'error': 'Missing required parameter(s): call_sid and url are both needed.'
        }), 400

    client = current_app.config['twilio_client']

    try:
        client.calls(call_sid).update(url=new_url, method='POST')
        current_app.logger.info(f"🔄 Updated call {call_sid} to fetch TwiML from {new_url}")
        return jsonify({'success': True, 'message': 'Call URL updated.'})
    except Exception as e:
        current_app.logger.error(f"❌ Failed to update call {call_sid}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
