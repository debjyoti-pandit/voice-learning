from flask import Blueprint, current_app, request, url_for
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv
from src.utils import xml_response

load_dotenv()

greet_bp = Blueprint('greet', __name__)

def play_greeting_to_participant(participant_call_sid: str, conference_name: str):
    """Redirect a single call leg so it hears the greeting and then re-joins the conference."""
    client = current_app.config['twilio_client']
    greeting_url = url_for('greet.greet_then_rejoin', conference_name=conference_name, _external=True)
    client.calls(participant_call_sid).update(url=greeting_url, method='POST')

@greet_bp.route('/greeting', methods=['GET', 'POST'])
def greeting():
    resp = VoiceResponse()
    resp.say("Thank you for calling Debjyoti's Dialer App! Have a great day.")
    return xml_response(resp)


@greet_bp.route('/temporary_message', methods=['GET', 'POST'])
def temporary_message():
    resp = VoiceResponse()
    resp.say('This is a temporary message simulating the transcription coming from aiva. Please wait while we connect you to the call. After this message, you will be connected to the customer.')
    resp.pause(length=1)
    return xml_response(resp)

@greet_bp.route('/greet_then_rejoin', methods=['GET', 'POST'])
def greet_then_rejoin():
    conference_name = request.args.get('conference_name', 'DefaultRoom')
    vr = VoiceResponse()
    vr.say("You are being joined back into the call.", voice='alice', language='en-US')

    dial = vr.dial()
    dial.conference(
        conference_name,
        start_conference_on_enter=True,
        end_conference_on_exit=True,
    )
    return xml_response(vr)
