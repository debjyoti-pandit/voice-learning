from flask import Blueprint, request, jsonify, Response, url_for, current_app
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv
import os
import time

from src.controllers import call_log, play_greeting_to_participant  # shared utilities

load_dotenv()

conference_bp = Blueprint('conference', __name__)

CALLER_ID = os.getenv('CALLER_ID')

# ------------------------------
# HOLD → UNHOLD FLOW ROUTES
# ------------------------------

@conference_bp.route('/hold-call', methods=['POST'])
def hold_call():
    """Move CHILD leg into a hold-music conference and hang up the PARENT leg."""
    data = request.json
    current_app.logger.info("📥 /hold-call payload: %s", data)

    client = current_app.config['twilio_client']
    child_call_sid = data.get('child_call_sid')
    parent_call_sid = data.get('parent_call_sid')
    parent_target = data.get('parent_target')

    if not child_call_sid or not parent_call_sid:
        return jsonify({'error': 'Missing call SID(s)'}), 400

    conference_name = f"CallRoom_{parent_call_sid}"

    try:
        client.calls(child_call_sid).update(
            url=url_for('.join_conference', _external=True, conference_name=conference_name),
            method='POST',
        )
        client.calls(parent_call_sid).update(status='completed')

        parent_number = parent_target
        if not parent_number and parent_call_sid in call_log:
            events = call_log[parent_call_sid].get('events', [])
            if events:
                first_evt = events[0]
                cand_from = first_evt.get('from')
                cand_to = first_evt.get('to')
                if cand_from and cand_from != CALLER_ID:
                    parent_number = cand_from
                elif cand_to and cand_to != CALLER_ID:
                    parent_number = cand_to
        if not parent_number:
            try:
                parent_number = client.calls(parent_call_sid).fetch().from_
            except Exception:
                pass
        if parent_number:
            call_log.setdefault(parent_call_sid, {})['parent_number'] = parent_number
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'message': 'Child placed in conference; parent dropped'}), 200


@conference_bp.route('/unhold-call', methods=['POST'])
def unhold_call():
    """Dial the parent back, playing an announcement first."""
    data = request.json
    client = current_app.config['twilio_client']
    parent_call_sid = data.get('parent_call_sid')
    conference_friendly_name = f"CallRoom_{parent_call_sid}"

    parent_number = call_log.get(parent_call_sid, {}).get('parent_number')
    if not parent_number:
        return jsonify({'error': 'Parent number not found for given SID'}), 400

    conf_sid = None
    for _ in range(5):
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
            current_app.logger.warning("Error finding conference: %s. Retrying…", e)
        time.sleep(1)

    if not conf_sid:
        return jsonify({'error': 'Conference not found or not in progress'}), 404

    try:
        participants = client.conferences(conf_sid).participants.list(limit=20)
        for p in participants:
            play_greeting_to_participant(p.call_sid, conference_friendly_name)
    except Exception as err:
        current_app.logger.warning("Could not play greeting: %s", err)

    try:
        client.calls.create(
            url=url_for('.connect_to_conference', _external=True, conference_name=conference_friendly_name),
            to=parent_number,
            from_=CALLER_ID,
        )
        return jsonify({'message': 'Parent re-dialed into conference'}), 200
    except Exception as e:
        return jsonify({'error': f'Failed to redial parent: {e}'}), 500


# ------------------------------
# SUPPORT ROUTES (HOLD MUSIC & BRIDGING)
# ------------------------------

@conference_bp.route('/hold-music', methods=['GET', 'POST'])
def hold_music():
    response = VoiceResponse()
    response.play("https://com.twilio.music.classical.s3.amazonaws.com/BusyStrings.mp3", loop=0)
    return Response(str(response), mimetype='text/xml')


@conference_bp.route('/join_conference', methods=['POST', 'GET'])
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
    return Response(str(response), mimetype='text/xml')


@conference_bp.route('/conference-announcement', methods=['POST', 'GET'])
def conference_announcement():
    response = VoiceResponse()
    response.say("You are being joined back into the call.", voice='alice', language='en-US')
    return Response(str(response), mimetype='text/xml') 