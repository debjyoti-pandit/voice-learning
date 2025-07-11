import os
import time

from dotenv import load_dotenv
from flask import Blueprint, current_app, jsonify, request, url_for
from twilio.twiml.voice_response import VoiceResponse

from src.greet_controller import play_greeting_to_participant
from src.utils import xml_response

load_dotenv()

transfer_bp = Blueprint("transfer", __name__, url_prefix="/transfer")

CALLER_ID = os.getenv("CALLER_ID")


def get_value(obj, key):
    try:
        return obj[key]
    except (KeyError, TypeError):
        return None


@transfer_bp.route("/warm-transfer", methods=["POST"])
def warm_transfer():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON payload"}), 400
    current_app.logger.info("🔀 warm_transfer invoked", extra={"payload": data})

    client = current_app.config["twilio_client"]
    child_call_sid = data.get("child_call_sid")
    parent_call_sid = data.get("parent_call_sid")
    parent_name = data.get("parent_name")
    child_name = data.get("child_name")
    parent_role = data.get("parent_role")
    child_role = data.get("child_role")
    identity = data.get("identity")
    transfer_to = data.get("transfer_to")
    if not parent_role or not child_role:
        return jsonify({"error": "Missing role(s)"}), 400
    current_app.logger.debug(
        "🔀 Warm transfer details: identity=%s parent_role=%s child_role=%s parent_name=%s child_name=%s transfer_to=%s",
        identity,
        parent_role,
        child_role,
        parent_name,
        child_name,
        transfer_to,
    )

    if not child_call_sid or not parent_call_sid:
        return jsonify({"error": "Missing call SID(s)"}), 400
    if not parent_name or not child_name:
        return jsonify({"error": "Missing name(s)"}), 400

    conference_name = f"{parent_name}-with-{child_name}"

    recordings = {}
    try:
        recording = client.recordings.list(call_sid=parent_call_sid, limit=1)
        if recording:
            recordings[parent_call_sid] = recording[0].sid
            client.recordings(recording[0].sid).update(status="stopped")
        else:
            recording = client.recordings.list(call_sid=child_call_sid, limit=1)
            if recording:
                recordings[child_call_sid] = recording[0].sid
                client.recordings(recording[0].sid).update(status="stopped")
    except Exception as e:
        current_app.logger.error(
            f"Could not access recordings to stop initial: {e}"
        )

    hold_on_conference_join = {parent_call_sid: False, child_call_sid: False}
    if parent_role == "customer":
        hold_on_conference_join[parent_call_sid] = True
        if child_role == "agent":  # not possible
            hold_on_conference_join[child_call_sid] = False
        else:  # will only be this as child will call aiva
            hold_on_conference_join[child_call_sid] = True
    if parent_role == "agent":
        hold_on_conference_join[parent_call_sid] = False
        if child_role == "customer":
            hold_on_conference_join[child_call_sid] = True
        else:
            hold_on_conference_join[child_call_sid] = False
    current_app.logger.debug(
        "🔀 Hold-on-join configuration: %s", hold_on_conference_join
    )

    mute_on_conference_join = {parent_call_sid: False, child_call_sid: False}

    start_conference_on_enter = {parent_call_sid: True, child_call_sid: True}
    end_conference_on_exit = {parent_call_sid: False, child_call_sid: False}

    if parent_role == "customer":
        start_conference_on_enter[parent_call_sid] = True
        end_conference_on_exit[parent_call_sid] = True
        start_conference_on_enter[child_call_sid] = False
        end_conference_on_exit[child_call_sid] = False
        mute_on_conference_join[child_call_sid] = (
            True  # for aiva case it will be muted
        )
        mute_on_conference_join[parent_call_sid] = False
    elif parent_role == "agent":
        start_conference_on_enter[parent_call_sid] = False
        end_conference_on_exit[parent_call_sid] = False
        mute_on_conference_join[parent_call_sid] = True
        if child_role == "customer":
            start_conference_on_enter[child_call_sid] = True
            end_conference_on_exit[child_call_sid] = True
            mute_on_conference_join[child_call_sid] = False  # agent to customer
        else:
            start_conference_on_enter[child_call_sid] = False
            end_conference_on_exit[child_call_sid] = False
            mute_on_conference_join[child_call_sid] = True  # agent to agent

    for sid_label, sid in {"parent": parent_call_sid}.items():
        try:
            client.calls(sid).streams("initial_call_recording").update(
                status="stopped"
            )
        except Exception as e:
            current_app.logger.error(
                f"No stream to stop on {sid_label} leg: {e}"
            )

    try:
        redis = current_app.config["redis"]
        redis[parent_call_sid] = {
            "participant_label": parent_name,
            "child_call_sid": child_call_sid,
            "child_call_moved_to_conference": True,
            "identity": identity,
            "stream_audio": True,
            "conference": {
                "conference_name": conference_name,
                "on_hold": hold_on_conference_join[parent_call_sid],
                "role": parent_role,
                "start_conference_on_enter": start_conference_on_enter[
                    parent_call_sid
                ],
                "end_conference_on_exit": end_conference_on_exit[
                    parent_call_sid
                ],
                "mute": mute_on_conference_join[parent_call_sid],
                "add_to_conference": transfer_to,
                "participant_role": "agent",
                "participant_identity": (
                    transfer_to[7:]
                    if transfer_to.startswith("client:")
                    else transfer_to
                ),
            },
        }
        redis[conference_name] = {
            "created_by": identity,
            "created": False,
            "calls": {
                parent_call_sid: {
                    "add_to_conference": transfer_to,
                    "participant_role": "agent",
                    "participant_identity": identity,  # transfer_to[7:] if transfer_to.startswith("client:") else transfer_to,
                    "call_tag": parent_name,
                    "hold_on_conference_join": hold_on_conference_join[
                        parent_call_sid
                    ],
                    "initial_call_recording_sid": get_value(
                        recordings, parent_call_sid
                    ),
                    "role": parent_role,
                    "stream_audio": True,
                },
                child_call_sid: {
                    "call_tag": child_name,
                    "hold_on_conference_join": hold_on_conference_join[
                        child_call_sid
                    ],
                    "initial_call_recording_sid": get_value(
                        recordings, child_call_sid
                    ),
                    "role": child_role,
                    "stream_audio": True,
                },
            },
            "participants": {},
        }
        print("************************************************")
        print("redis: %s", redis)
        print("************************************************")

        client.calls(child_call_sid).update(
            url=url_for(
                "conference.join_conference",
                _external=True,
                conference_name=conference_name,
                participant_label=child_name,
                start_conference_on_enter=start_conference_on_enter[
                    child_call_sid
                ],
                end_conference_on_exit=end_conference_on_exit[child_call_sid],
                role=child_role,
                identity=identity,
                mute=True,
            ),
            method="POST",
        )
        redis[conference_name]["participants"][child_call_sid] = {
            "participant_label": child_name,
            "call_sid": child_call_sid,
            "muted": mute_on_conference_join[child_call_sid],
            "on_hold": hold_on_conference_join[child_call_sid],
            "role": child_role,
        }

        redis[conference_name]["participants"][parent_call_sid] = {
            "participant_label": parent_name,
            "call_sid": parent_call_sid,
            "muted": mute_on_conference_join[parent_call_sid],
            "on_hold": hold_on_conference_join[parent_call_sid],
            "role": parent_role,
        }
        current_app.logger.debug(
            "🔀 Child call %s joined conference %s",
            child_call_sid,
            conference_name,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    current_app.logger.info("🔀 warm_transfer processing complete")
    return jsonify({"message": "both legs in conference"}), 200


@transfer_bp.route("/unhold-call", methods=["POST"])
def unhold_call():
    """Dial the parent back into the conference they were originally on and play
    an unhold greeting.
    """
    data = request.json
    client = current_app.config["twilio_client"]
    call_log = current_app.config["call_log"]
    parent_call_sid = data.get("parent_call_sid")
    conference_friendly_name = f"CallRoom_{parent_call_sid}"

    parent_number = call_log.get(parent_call_sid, {}).get("parent_number")
    if not parent_number:
        return jsonify({"error": "Parent number not found for given SID"}), 400

    conf_sid = None
    for _ in range(5):
        try:
            conferences = client.conferences.list(
                friendly_name=conference_friendly_name,
                status="in-progress",
                limit=1,
            )
            if conferences:
                conf_sid = conferences[0].sid
                break
        except Exception as e:
            current_app.logger.warning(
                "Error while searching for conference: %s. Retrying…", e
            )
        time.sleep(1)

    if not conf_sid:
        return (
            jsonify({"error": "Conference not found or not in progress"}),
            404,
        )

    try:
        participants = client.conferences(conf_sid).participants.list(limit=20)
        for participant in participants:
            play_greeting_to_participant(
                participant.call_sid, conference_friendly_name
            )
    except Exception as err:
        current_app.logger.warning(
            "Could not play greeting to child leg: %s", err
        )

    try:
        client.calls.create(
            url=url_for(
                "conference.connect_to_conference",
                _external=True,
                conference_name=conference_friendly_name,
            ),
            to=parent_number,
            from_=CALLER_ID,
        )
        return jsonify({"message": "Parent re-dialed into conference"}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to redial parent: {e}"}), 500


@transfer_bp.route("/hold_music", methods=["GET", "POST"])
def hold_music():
    response = VoiceResponse()

    response.play(
        "https://com.twilio.music.classical.s3.amazonaws.com/BusyStrings.mp3",
        loop=0,
    )
    return xml_response(response)
