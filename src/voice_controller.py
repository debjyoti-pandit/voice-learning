from flask import Blueprint, request, Response, url_for
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client
from dotenv import load_dotenv
import os

# Ensure environment variables are available
load_dotenv()

voice_bp = Blueprint('voice', __name__)

# Twilio credentials --------------------------------------------------------
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
CALLER_ID = os.getenv('CALLER_ID')

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


@voice_bp.route('/voice', methods=['POST'])
def voice():
    """TwiML endpoint that dials a number or client via Twilio Programmable Voice."""
    to_number = request.values.get('To')
    response = VoiceResponse()

    if to_number:
        dial = response.dial(
            caller_id=CALLER_ID,
            action=url_for('api.hangup_call', _external=True),  # hangup endpoint lives in api_bp (controllers.py)
            method='POST',
            timeout=20,
        )
        dial.number(
            to_number,
            status_callback=url_for('api.call_events', _external=True),
            status_callback_method='GET',
            status_callback_event='initiated ringing answered completed',
            url=url_for('greet.greeting', _external=True),
        )
    else:
        response.say("Thanks for calling!")

    return Response(str(response), mimetype='text/xml') 