from flask import Blueprint, request, jsonify, Response, url_for, current_app
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv
import os
import time

from src.greet_controller import play_greeting_to_participant

load_dotenv()

hold_bp = Blueprint('hold', __name__)

CALLER_ID = os.getenv('CALLER_ID')


@hold_bp.route('/hold-call', methods=['POST'])
def hold_call():
    """Move CHILD leg into a hold‐music conference and hang up the PARENT leg."""
    data = request.json
    current_app.logger.info("📥 /hold-call payload: %s", data)

    client = current_app.config['twilio_client']
    call_log = current_app.config['call_log']
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
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'message': 'Child placed in conference; parent dropped'}), 200


@hold_bp.route('/unhold-call', methods=['POST'])
def unhold_call():
    """Dial the parent back into the conference they were originally on and play an unhold greeting."""
    data = request.json
    client = current_app.config['twilio_client']
    call_log = current_app.config['call_log']
    parent_call_sid = data.get('parent_call_sid')
    conference_friendly_name = f"CallRoom_{parent_call_sid}"

    parent_number = call_log.get(parent_call_sid, {}).get('parent_number')
    if not parent_number:
        return jsonify({'error': 'Parent number not found for given SID'}), 400

    # 🔍 Retrieve the actual conference SID (retry up to ~5 s)
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
            current_app.logger.warning("Error while searching for conference: %s. Retrying…", e)
        time.sleep(1)

    if not conf_sid:
        return jsonify({'error': 'Conference not found or not in progress'}), 404

    # Play greeting to existing participants
    try:
        participants = client.conferences(conf_sid).participants.list(limit=20)
        for participant in participants:
            play_greeting_to_participant(participant.call_sid, conference_friendly_name)
    except Exception as err:
        current_app.logger.warning("Could not play greeting to child leg: %s", err)

    # Dial the parent back
    try:
        client.calls.create(
            url=url_for('.connect_to_conference', _external=True, conference_name=conference_friendly_name),
            to=parent_number,
            from_=CALLER_ID,
        )
        return jsonify({'message': 'Parent re-dialed into conference'}), 200
    except Exception as e:
        return jsonify({'error': f'Failed to redial parent: {e}'}), 500


@hold_bp.route('/hold-music', methods=['GET', 'POST'])
def hold_music():
    response = VoiceResponse()
    response.play("https://com.twilio.music.classical.s3.amazonaws.com/BusyStrings.mp3", loop=0)
    return Response(str(response), mimetype='text/xml')
