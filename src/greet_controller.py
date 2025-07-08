from flask import Blueprint, current_app, request, url_for
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv
from src.utils import xml_response
import logging
from src.constants import NAME

load_dotenv()

greet_bp = Blueprint('greet', __name__)

def play_greeting_to_participant(participant_call_sid: str, conference_name: str):
    """Redirect a single call leg so it hears the greeting and then re-joins the conference."""
    client = current_app.config['twilio_client']
    current_app.logger.debug("🙋 Redirecting call %s to greeting for conference %s", participant_call_sid, conference_name)
    greeting_url = url_for('greet.greet_then_rejoin', conference_name=conference_name, _external=True)
    client.calls(participant_call_sid).update(url=greeting_url, method='POST')

@greet_bp.route('/greeting', methods=['GET', 'POST'])
def greeting():
    current_app.logger.info("🙋 greeting endpoint invoked")
    resp = VoiceResponse()
    resp.say(f"Thank you for calling {NAME.title()}\'s Dialer App! Have a great day.")
    current_app.logger.info("🙋 greeting endpoint processing complete")
    return xml_response(resp)


@greet_bp.route('/temporary_message', methods=['GET', 'POST'])
def temporary_message():
    current_app.logger.info("🙋 temporary_message endpoint invoked")
    resp = VoiceResponse()
    resp.say('This is a temporary message simulating the transcription coming from aiva. Please wait while we connect you to the call. After this message, you will be connected to the customer.')
    resp.pause(length=1)
    current_app.logger.info("🙋 temporary_message endpoint processing complete")
    return xml_response(resp)

@greet_bp.route('/greet_then_rejoin', methods=['GET', 'POST'])
def greet_then_rejoin():
    conference_name = request.args.get('conference_name', 'DefaultRoom')
    current_app.logger.info("🙋 greet_then_rejoin invoked", extra={"conference_name": conference_name})
    vr = VoiceResponse()
    vr.say("You are being joined back into the call.", voice='alice', language='en-US')

    dial = vr.dial()
    dial.conference(
        conference_name,
        start_conference_on_enter=True,
        end_conference_on_exit=True,
    )
    current_app.logger.info("🙋 greet_then_rejoin processing complete")
    return xml_response(vr)
