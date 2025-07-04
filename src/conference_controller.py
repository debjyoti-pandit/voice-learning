from flask import Blueprint, request, url_for
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv
import os
from src.utils import xml_response

load_dotenv()

conference_bp = Blueprint('conference', __name__)

CALLER_ID = os.getenv('CALLER_ID')

@conference_bp.route('/join_conference', methods=['POST', 'GET'])
def join_conference():
    conference_name = request.args.get('conference_name', 'DefaultRoom')
    response = VoiceResponse()
    response.say("Your call is on hold. We will get back to you shortly.", voice='alice')
    dial = response.dial()
    dial.conference(
        conference_name,
        wait_url=url_for('hold.hold_music', _external=True),
        start_conference_on_enter=True,
        end_conference_on_exit=True,
    )
    return xml_response(response)


@conference_bp.route('/connect_to_conference', methods=['POST', 'GET'])
def connect_to_conference():
    conference_name = request.args.get('conference_name', 'DefaultRoom')
    response = VoiceResponse()
    dial = response.dial()
    dial.conference(
        conference_name,
        start_conference_on_enter=True,
        end_conference_on_exit=True,
    )
    return xml_response(response)


@conference_bp.route('/conference-announcement', methods=['POST', 'GET'])
def conference_announcement():
    response = VoiceResponse()
    response.say("You are being joined back into the call.", voice='alice', language='en-US')
    return xml_response(response) 