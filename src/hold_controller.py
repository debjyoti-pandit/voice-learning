from flask import Blueprint, request, jsonify, url_for, current_app
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv
import os
import time

from src.greet_controller import play_greeting_to_participant
from src.utils import xml_response

load_dotenv()

hold_bp = Blueprint('hold', __name__)

CALLER_ID = os.getenv('CALLER_ID')

@hold_bp.route('/hold-call', methods=['POST'])
def hold_call():
    """Move CHILD leg into a hold‐music conference and hang up the PARENT leg."""

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Invalid or missing JSON payload'}), 400
    current_app.logger.info("📥 /hold-call payload: %s", data)

    client = current_app.config['twilio_client']
    call_log = current_app.config['call_log']
    child_call_sid = data.get('child_call_sid')
    parent_call_sid = data.get('parent_call_sid')
    parent_target = data.get('parent_target')

    if not child_call_sid or not parent_call_sid:
        return jsonify({'error': 'Missing call SID(s)'}), 400

    conference_name = f"CallRoom_{parent_call_sid}"

    try:

        child_call = client.calls(child_call_sid).fetch()
        if child_call.status != "in-progress":
            current_app.logger.error(f"Child call {child_call_sid} is not in-progress (status: {child_call.status})")
            return jsonify({'error': f'Child call {child_call_sid} is not in-progress (status: {child_call.status})'}), 400

        parent_call = client.calls(parent_call_sid).fetch()
        if parent_call.status != "in-progress":
            current_app.logger.error(f"Parent call {parent_call_sid} is not in-progress (status: {parent_call.status})")
            return jsonify({'error': f'Parent call {parent_call_sid} is not in-progress (status: {parent_call.status})'}), 400

        client.calls(child_call_sid).update(
            url=url_for('conference.join_conference', _external=True, conference_name=conference_name),
            method='POST',
        )

        client.calls(parent_call_sid).update(
            url=url_for('conference.connect_to_conference', _external=True, conference_name=conference_name),
            method='POST',
        )

        conf_sid = None
        for _ in range(5):
            try:
                conferences = client.conferences.list(
                    friendly_name=conference_name,
                    status='in-progress',
                    limit=1,
                )
                if conferences:
                    conf_sid = conferences[0].sid
                    break
            except Exception as e:
                current_app.logger.warning("Error while searching for conference: %s. Retrying…", e)
            time.sleep(1)

        if conf_sid:
            try:
                participants = client.conferences(conf_sid).participants.list(limit=50)
                for participant in participants:
                    if participant.call_sid == child_call_sid:
                        client.conferences(conf_sid).participants(participant.call_sid).update(
                            hold=True,
                            hold_url=url_for('hold.hold_music', _external=True),
                            hold_method='POST',
                        )
                        break
            except Exception as e:
                current_app.logger.warning("Could not place child on hold: %s", e)

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

    return jsonify({'message': 'Child placed on hold; both legs in conference'}), 200

def get_value(obj, key):
    try:
        return obj[key]
    except (KeyError, TypeError):
        return None

@hold_bp.route('/hold-call-via-conference', methods=['POST'])
def hold_call_via_conference():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Invalid or missing JSON payload'}), 400
    current_app.logger.info("📥 /hold-call-via-conference payload: %s", data)

    client = current_app.config['twilio_client']
    child_call_sid = data.get('child_call_sid')
    parent_call_sid = data.get('parent_call_sid')
    parent_name = data.get('parent_name')
    child_name = data.get('child_name')
    parent_role = data.get('parent_role', 'agent')
    child_role = data.get('child_role', 'customer')
    identity = data.get('identity')
    print(f"Identity: {identity}")

    if not child_call_sid or not parent_call_sid:
        return jsonify({'error': 'Missing call SID(s)'}), 400
    if not parent_name or not child_name:
        return jsonify({'error': 'Missing name(s)'}), 400

    conference_name = f"{parent_name}'s-conference-with-{child_name}"

    recordings = {}
    try:
        recording = client.recordings.list(call_sid=parent_call_sid, limit=1)
        if recording:
            print(f"Stopping initial recording for parent call: {recording[0].sid}")
            recordings[parent_call_sid] = recording[0].sid
            client.recordings(recording[0].sid).update(status='stopped')
        else:
            recording = client.recordings.list(call_sid=child_call_sid, limit=1)
            if recording:
                print(f"Stopping initial recording for child call: {recording[0].sid}")
                recordings[child_call_sid] = recording[0].sid
                client.recordings(recording[0].sid).update(status='stopped')
    except Exception as e:
        current_app.logger.warning(f"Could not access recordings to stop initial: {e}")

    try:
        redis = current_app.config['redis']
        redis[conference_name] = {
            "created_by": identity,
            "calls": {
               parent_call_sid: {
                   "call_tag": parent_name,
                   "hold_on_conference_join": False,
                   "initial_call_recording_sid": get_value(recordings, parent_call_sid),
                   "role": parent_role,
               },
               child_call_sid: {
                   "call_tag": child_name,
                   "hold_on_conference_join": True,
                   "initial_call_recording_sid": get_value(recordings, child_call_sid),
                   "role": child_role,
               }
            },
            "participants": {}
        }
        client.calls(child_call_sid).update(
            url=url_for('conference.join_conference', _external=True, conference_name=conference_name, participant_label=child_name, start_conference_on_enter=False, end_conference_on_exit=True, role=child_role, identity=identity),
            method='POST',
        )
        print('after joining the child call to the conference')
        redis[conference_name]['participants'][child_call_sid] = {
            'participant_label': child_name,
            'call_sid': child_call_sid,
            'muted': False,
            'on_hold': True,
            'role': child_role,
        }
        client.calls(parent_call_sid).update(
            url=url_for('conference.join_conference', _external=True, conference_name=conference_name, participant_label=parent_name, start_conference_on_enter=True, end_conference_on_exit=False, mute=True, role=parent_role, identity=identity),
            method='POST',
        )
        print('after joining the parent call to the conference')

        redis[conference_name]['participants'][parent_call_sid] = {
            'participant_label': parent_name,
            'call_sid': parent_call_sid,
            'muted': True,
            'on_hold': False,
            'role': parent_role,
        }

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'message': 'both legs in conference'}), 200

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

    try:
        participants = client.conferences(conf_sid).participants.list(limit=20)
        for participant in participants:
            play_greeting_to_participant(participant.call_sid, conference_friendly_name)
    except Exception as err:
        current_app.logger.warning("Could not play greeting to child leg: %s", err)

    try:
        client.calls.create(
            url=url_for('conference.connect_to_conference', _external=True, conference_name=conference_friendly_name),
            to=parent_number,
            from_=CALLER_ID,
        )
        return jsonify({'message': 'Parent re-dialed into conference'}), 200
    except Exception as e:
        return jsonify({'error': f'Failed to redial parent: {e}'}), 500

@hold_bp.route('/hold_music', methods=['GET', 'POST'])
def hold_music():
    response = VoiceResponse()

    response.play("https://com.twilio.music.classical.s3.amazonaws.com/BusyStrings.mp3", loop=0)
    return xml_response(response)
