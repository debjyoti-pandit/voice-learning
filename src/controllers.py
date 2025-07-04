from flask import Blueprint, request, jsonify, Response, render_template, url_for, current_app
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client
from dotenv import load_dotenv
from src.call_events_handler import CallEventsHandler, handle_call_events
import os
import time

# Load environment variables (in case app.py didn't already)
load_dotenv()

api_bp = Blueprint('api', __name__)

# 🔐 Twilio credentials
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_API_KEY = os.getenv('TWILIO_API_KEY')
TWILIO_API_SECRET = os.getenv('TWILIO_API_SECRET')
CALLER_ID = os.getenv('CALLER_ID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
# TWIML_APP_SID = os.getenv('TWIML_APP_SID')
# TWIML_SECONDARY_APP_SID = os.getenv('TWIML_SECONDARY_APP_SID')

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

call_log = {}

def play_greeting_to_participant(participant_call_sid: str, conference_name: str):
    """Redirect a single call leg so it hears the greeting and then re-joins the conference."""
    greeting_url = url_for('.greet_then_rejoin', conference_name=conference_name, _external=True)
    client.calls(participant_call_sid).update(url=greeting_url, method='POST')

@api_bp.route('/')
def index():
    return render_template('index.html')


@api_bp.route('/call-events', methods=['GET', 'POST'])
def call_events():
    """Delegates to shared handler while accessing Socket.IO via app config."""
    socketio = current_app.config['socketio']
    return CallEventsHandler(socketio, call_log).handle(request) 


@api_bp.route('/hold-call', methods=['POST'])
def hold_call():
    """Move CHILD leg into a hold-music conference and hang up the PARENT leg."""
    data = request.json
    print("📥 /hold-call payload:", data)

    child_call_sid = data.get('child_call_sid')
    parent_call_sid = data.get('parent_call_sid')
    parent_target = data.get('parent_target')  # could be client:alice or phone number

    if not child_call_sid or not parent_call_sid:
        return jsonify({'error': 'Missing call SID(s)'}), 400

    conference_name = f"CallRoom_{parent_call_sid}"

    try:
        # 1️⃣ Move the CHILD leg into the conference where they'll hear hold music
        client.calls(child_call_sid).update(
            url=url_for('.join_conference', _external=True, conference_name=conference_name),
            method='POST',
        )

        # 2️⃣ Hang up the PARENT leg so they are effectively on hold
        client.calls(parent_call_sid).update(status='completed')

        # 3️⃣ Cache the parent's phone/Client identity for later dial-back
        parent_number = parent_target
        if not parent_number and parent_call_sid in call_log:
            events = call_log[parent_call_sid].get('events', [])
            if events:
                first_evt = events[0]
                cand_from = first_evt.get('from')
                cand_to = first_evt.get('to')

                # Prefer the party that is NOT our Twilio caller ID
                if cand_from and cand_from != CALLER_ID:
                    parent_number = cand_from
                elif cand_to and cand_to != CALLER_ID:
                    parent_number = cand_to

        if not parent_number:
            # Fallback: fetch from Twilio API
            try:
                parent_number = client.calls(parent_call_sid).fetch().from_
            except Exception:
                pass

        if parent_number:
            call_log.setdefault(parent_call_sid, {})['parent_number'] = parent_number
            print("⚠️ Parent target not determined; unhold may fail.")
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'message': 'Child placed in conference; parent dropped'}), 200


@api_bp.route('/join_conference', methods=['POST', 'GET'])
def join_conference():
    conference_name = request.args.get('conference_name', 'DefaultRoom')

    response = VoiceResponse()
    response.say("Your call is on hold. We will get back to you shortly.", voice='alice')

    dial = response.dial()
    dial.conference(
        conference_name,
        wait_url=url_for('.hold_music', _external=True),
        start_conference_on_enter=True,
        end_conference_on_exit=True,
    )

    return Response(str(response), mimetype='text/xml')


@api_bp.route('/unhold-call', methods=['POST'])
def unhold_call():
    """Dial the parent back into the conference they were originally on and play an unhold greeting."""
    data = request.json
    parent_call_sid = data.get('parent_call_sid')
    conference_friendly_name = f"CallRoom_{parent_call_sid}"

    # Retrieve cached parent number
    parent_number = call_log.get(parent_call_sid, {}).get('parent_number')

    if not parent_number:
        return jsonify({'error': 'Parent number not found for given SID'}), 400

    # 🔍 1) Retrieve the actual conference SID
    conf_sid = None
    for _ in range(5):  # up to ~5 seconds total wait
        try:
            conferences = client.conferences.list(
                friendly_name=conference_friendly_name,
                status='in-progress',
                limit=1,
            )
            if conferences:
                conf_sid = conferences[0].sid
                break
        except Exception as e:
            print(f"⚠️ Error while searching for conference: {e}. Retrying…")
        time.sleep(1)

    if not conf_sid:
        return jsonify({'error': 'Conference not found or not in progress'}), 404

    try:
        participants = client.conferences(conf_sid).participants.list(limit=20)
        for participant in participants:
            # Play a greeting to each existing participant
            play_greeting_to_participant(participant.call_sid, conference_friendly_name)
    except Exception as ann_e:
        print(f"⚠️ Could not play greeting to child leg: {ann_e}")

    try:
        client.calls.create(
            url=url_for('.connect_to_conference', _external=True, conference_name=conference_friendly_name),
            to=parent_number,
            from_=CALLER_ID,
        )
        return jsonify({'message': 'Parent re-dialed into conference'}), 200
    except Exception as e:
        return jsonify({'error': f'Failed to redial parent: {e}'}), 500


@api_bp.route('/hold-music', methods=['GET', 'POST'])
def hold_music():
    response = VoiceResponse()
    response.play("https://com.twilio.music.classical.s3.amazonaws.com/BusyStrings.mp3", loop=0)
    return Response(str(response), mimetype='text/xml')


@api_bp.route('/connect_to_conference', methods=['POST', 'GET'])
def connect_to_conference():
    conference_name = request.args.get('conference_name', 'DefaultRoom')

    response = VoiceResponse()
    dial = response.dial()
    dial.conference(
        conference_name,
        start_conference_on_enter=True,
        end_conference_on_exit=True,
    )
    return Response(str(response), mimetype='text/xml')


@api_bp.route('/conference-announcement', methods=['POST', 'GET'])
def conference_announcement():
    response = VoiceResponse()
    response.say("You are being joined back into the call.", voice='alice', language='en-US')
    return Response(str(response), mimetype='text/xml')


@api_bp.route('/hangup', methods=['GET', 'POST'])
def hangup_call():
    resp = VoiceResponse()
    resp.hangup()
    return Response(str(resp), mimetype='text/xml')


@api_bp.route('/answer', methods=['GET', 'POST'])
def answer_call():
    resp = VoiceResponse()
    resp.say("Thank you for calling! Have a great day.")
    return Response(str(resp), mimetype='text/xml')


@api_bp.route('/dialer')
def dialer():
    """Serve a dialer page that can be instantiated with a custom identity."""
    return render_template('dialer.html')


@api_bp.route('/greet_then_rejoin', methods=['GET', 'POST'])
def greet_then_rejoin():
    """TwiML endpoint: plays a short greeting, then dials the caller back into the same conference."""
    conference_name = request.args.get('conference_name', 'DefaultRoom')

    vr = VoiceResponse()
    vr.say("You are being joined back into the call.", voice='alice', language='en-US')

    dial = vr.dial()
    dial.conference(
        conference_name,
        start_conference_on_enter=True,
        end_conference_on_exit=True,
    )
    return Response(str(vr), mimetype='text/xml') 