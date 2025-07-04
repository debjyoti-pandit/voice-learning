from flask import Blueprint, request, url_for, current_app
from twilio.twiml.voice_response import VoiceResponse
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

    if to_number:
        dial = response.dial(
            caller_id=CALLER_ID,
            action=url_for('voice.hangup_call', _external=True),
            method='POST',
            timeout=20,
        )
        dial.number(
            to_number,
            status_callback=url_for('events.call_events', _external=True),
            status_callback_method='GET',
            status_callback_event='initiated ringing answered completed',
        )
    else:
        response.say("Thanks for calling!")

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
    resp = VoiceResponse()
    resp.say("Thank you for calling! Have a great day.")
    return xml_response(resp) 