from flask import Blueprint, request, jsonify, url_for, current_app
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv
import os
import time
from src.greet_controller import play_greeting_to_participant
from src.utils import xml_response

load_dotenv()

transfer_bp = Blueprint('transfer', __name__, url_prefix='/transfer')

CALLER_ID = os.getenv('CALLER_ID')

def get_value(obj, key):
    try:
        return obj[key]
    except (KeyError, TypeError):
        return None

@transfer_bp.route('/warm-transfer', methods=['POST'])
def warm_transfer():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Invalid or missing JSON payload'}), 400
    current_app.logger.info("📥 /hold-call-via-conference payload: %s", data)

    client = current_app.config['twilio_client']
    child_call_sid = data.get('child_call_sid')
    parent_call_sid = data.get('parent_call_sid')
    parent_name = data.get('parent_name')
    child_name = data.get('child_name')
    print(f"Parent name: {parent_name} and child name: {child_name}")
    parent_role = data.get('parent_role')
    child_role = data.get('child_role')
    identity = data.get('identity')
    if not parent_role or not child_role:
        return jsonify({'error': 'Missing role(s)'}), 400
    print(f"Identity: {identity} and parent_role: {parent_role} and child_role: {child_role}")
    
    transfer_to = data.get('transfer_to')
    print(f"Transfer to: {transfer_to}")    

    if not child_call_sid or not parent_call_sid:
        return jsonify({'error': 'Missing call SID(s)'}), 400
    if not parent_name or not child_name:
        return jsonify({'error': 'Missing name(s)'}), 400

    conference_name = f"{parent_name}-with-{child_name}"

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

        add_participant_to_conference(conference_name, transfer_to, parent_role, identity)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'message': 'both legs in conference'}), 200


def add_participant_to_conference(conference_name, phone_number, role="agent", identity=None):
    print(f"Adding participant to conference: {conference_name}, {phone_number}, {identity}")
    client = current_app.config['twilio_client']

    # Determine a label to use for this participant inside the conference. If the
    # destination is a Twilio Client identity (e.g. "client:alice"), strip the
    # prefix; otherwise use the raw phone number.
    participant_label = phone_number[7:] if phone_number.startswith("client:") else phone_number

    # NEW: Extract the actual identity of this participant so that status
    # callbacks can be routed directly to *their* Socket.IO room rather than the
    # originating agent. This allows every agent that joins the conference to
    # receive real-time conference updates.
    participant_identity = participant_label if phone_number.startswith("client:") else None
    print(f"Participant identity in add_participant_to_conference: {participant_identity}")  

    to_is_client = phone_number.startswith("client:")

    if to_is_client:
        # Twilio client identities must be alphanumeric plus underscore and <=100 chars.
        # Convert the friendly conference name to a safe slug and prepend a fixed
        # marker so the receiving dialer can recognise it.
        import re

        slug = re.sub(r"[^A-Za-z0-9_\-]", "-", conference_name)[:80]  # keep short
        # Use a valid Twilio Client identity as the caller ID (must be prefixed with "client:")
        caller_id = f"client:conference-of-{slug}"
    else:
        caller_id = current_app.config.get("TWILIO_CALLER_ID") or os.getenv("CALLER_ID")

    # IMPORTANT: Pass the *participant's* identity (when available) so that the
    # ConferenceEventsHandler emits events to the correct Socket.IO room.
    call = client.calls.create(
        to=phone_number,
        from_=caller_id,
        url=url_for(
            'conference.join_conference',
            conference_name=conference_name,
            participant_label=participant_label,
            role=role,
            identity=participant_identity,
            _external=True
        ),
        method='POST'
    )

    # Persist the new call/participant details in our in-memory redis cache. If this
    # conference hasn't been tracked yet (e.g. when add_participant_to_conference is
    # called independently of warm_transfer/hold_call flows), we create the basic
    # structure so that subsequent look-ups via the /conference/<name>/participants
    # endpoint work as expected.
    redis = current_app.config['redis']

    if conference_name not in redis:
        redis[conference_name] = {
            "created_by": identity,
            "calls": {},
            "participants": {},
        }

    redis[conference_name]["calls"][call.sid] = {
        "call_tag": participant_label,
        "role": role,
        "hold_on_conference_join": False,
    }

    redis[conference_name]['participants'][call.sid] = {
        'participant_label': participant_label,
        'call_sid': call.sid,
        'muted': False,
        'on_hold': False,
        'role': role,
    }

    return call.sid


@transfer_bp.route('/unhold-call', methods=['POST'])
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

@transfer_bp.route('/hold_music', methods=['GET', 'POST'])
def hold_music():
    response = VoiceResponse()

    response.play("https://com.twilio.music.classical.s3.amazonaws.com/BusyStrings.mp3", loop=0)
    return xml_response(response)
