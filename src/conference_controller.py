from flask import Blueprint, current_app, jsonify, request, url_for
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv
import os
from src.utils import xml_response
from src.conference_events_handler import ConferenceEventsHandler

load_dotenv()

conference_bp = Blueprint('conference', __name__)

CALLER_ID = os.getenv('CALLER_ID')

@conference_bp.route('/join_conference', methods=['POST', 'GET'])
def join_conference():
    conference_name = request.args.get('conference_name', 'DefaultRoom')
    response = VoiceResponse()
    dial = response.dial()
    dial.conference(
        conference_name,
        wait_url='http://twimlets.com/holdmusic?Bucket=com.twilio.music.silent',
        start_conference_on_enter=True,
        end_conference_on_exit=True,
        status_callback=url_for('conference.conference_events', _external=True),
        status_callback_method='POST',
        status_callback_event='start end join leave hold mute',
        participant_label=request.args.get('participant_label', 'DefaultParticipant')
    )

    return xml_response(response)

@conference_bp.route('/conference-events', methods=['POST', 'GET'])
def conference_events():
    """Webhook endpoint for Twilio conference status callbacks."""
    socketio = current_app.config['socketio']
    # Delegate processing to handler (mirrors pattern used for call events)
    return ConferenceEventsHandler(socketio).handle(request)


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