from flask import Blueprint, request, jsonify, Response, render_template, url_for, current_app
from flask.views import MethodView
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client
import os
import time
from dotenv import load_dotenv
from src.call_events_handler import CallEventsHandler

load_dotenv()

api_bp = Blueprint('api', __name__)

# Twilio credentials ---------------------------------------------------------
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_API_KEY = os.getenv('TWILIO_API_KEY')
TWILIO_API_SECRET = os.getenv('TWILIO_API_SECRET')
CALLER_ID = os.getenv('CALLER_ID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWIML_APP_SID = os.getenv('TWIML_APP_SID')

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Shared in-memory store ------------------------------------------------------
call_log: dict = {}

# Utility helper -------------------------------------------------------------

def play_greeting_to_participant(participant_call_sid: str, conference_name: str):
    greeting_url = url_for('api.greet_then_rejoin', conference_name=conference_name, _external=True)
    client.calls(participant_call_sid).update(url=greeting_url, method='POST')

# ---------------------------------------------------------------------------
# Controller Classes (MethodView)
# ---------------------------------------------------------------------------

class IndexController(MethodView):
    def get(self):
        return render_template('index.html')


class DialerController(MethodView):
    def get(self):
        return render_template('dialer.html')


class TokenController(MethodView):
    def get(self):
        identity = request.args.get('identity', 'debjyoti-dialer-app')
        token = AccessToken(
            TWILIO_ACCOUNT_SID,
            TWILIO_API_KEY,
            TWILIO_API_SECRET,
            identity=identity,
        )
        voice_grant = VoiceGrant(outgoing_application_sid=TWIML_APP_SID, incoming_allow=True)
        token.add_grant(voice_grant)
        jwt_token = token.to_jwt()
        if isinstance(jwt_token, bytes):
            jwt_token = jwt_token.decode()
        return jsonify(token=jwt_token, identity=identity)


class GreetingController(MethodView):
    def _response(self):
        resp = VoiceResponse()
        resp.say("Thank you for calling! Have a great day.")
        return Response(str(resp), mimetype='text/xml')
    get = post = _response


class VoiceController(MethodView):
    def post(self):
        to_number = request.values.get('To')
        response = VoiceResponse()
        if to_number:
            dial = response.dial(
                caller_id=CALLER_ID,
                action=url_for('api.hangup', _external=True),
                method='POST',
                timeout=20,
            )
            dial.number(
                to_number,
                status_callback=url_for('api.call_events', _external=True),
                status_callback_method='GET',
                status_callback_event='initiated ringing answered completed',
                url=url_for('api.greeting', _external=True),
            )
        else:
            response.say("Thanks for calling!")
        return Response(str(response), mimetype='text/xml')


class CallEventsController(MethodView):
    def _delegate(self):
        socketio = current_app.config['socketio']
        handler = CallEventsHandler(socketio, call_log)
        return handler.handle(request)
    get = post = _delegate


class HoldCallController(MethodView):
    def post(self):
        data = request.json
        child_call_sid = data.get('child_call_sid')
        parent_call_sid = data.get('parent_call_sid')
        parent_target = data.get('parent_target')
        if not child_call_sid or not parent_call_sid:
            return jsonify({'error': 'Missing call SID(s)'}), 400
        conference_name = f"CallRoom_{parent_call_sid}"
        try:
            client.calls(child_call_sid).update(
                url=url_for('api.join_conference', conference_name=conference_name, _external=True),
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


class JoinConferenceController(MethodView):
    def _response(self):
        conference_name = request.args.get('conference_name', 'DefaultRoom')
        response = VoiceResponse()
        response.say("Your call is on hold. We will get back to you shortly.", voice='alice')
        dial = response.dial()
        dial.conference(
            conference_name,
            wait_url=url_for('api.hold_music', _external=True),
            start_conference_on_enter=True,
            end_conference_on_exit=True,
        )
        return Response(str(response), mimetype='text/xml')
    get = post = _response


class UnholdCallController(MethodView):
    def post(self):
        data = request.json
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
            except Exception:
                time.sleep(1)
        if not conf_sid:
            return jsonify({'error': 'Conference not found or not in progress'}), 404
        try:
            participants = client.conferences(conf_sid).participants.list(limit=20)
            for p in participants:
                play_greeting_to_participant(p.call_sid, conference_friendly_name)
        except Exception:
            pass
        try:
            client.calls.create(
                url=url_for('api.connect_to_conference', conference_name=conference_friendly_name, _external=True),
                to=parent_number,
                from_=CALLER_ID,
            )
            return jsonify({'message': 'Parent re-dialed into conference'}), 200
        except Exception as e:
            return jsonify({'error': f'Failed to redial parent: {e}'}), 500


class HoldMusicController(MethodView):
    def _response(self):
        response = VoiceResponse()
        response.play("https://com.twilio.music.classical.s3.amazonaws.com/BusyStrings.mp3", loop=0)
        return Response(str(response), mimetype='text/xml')
    get = post = _response


class ConnectToConferenceController(MethodView):
    def _response(self):
        conference_name = request.args.get('conference_name', 'DefaultRoom')
        response = VoiceResponse()
        dial = response.dial()
        dial.conference(
            conference_name,
            start_conference_on_enter=True,
            end_conference_on_exit=True,
        )
        return Response(str(response), mimetype='text/xml')
    get = post = _response


class ConferenceAnnouncementController(MethodView):
    def _response(self):
        response = VoiceResponse()
        response.say("You are being joined back into the call.", voice='alice', language='en-US')
        return Response(str(response), mimetype='text/xml')
    get = post = _response


class HangupController(MethodView):
    def _response(self):
        resp = VoiceResponse()
        resp.hangup()
        return Response(str(resp), mimetype='text/xml')
    get = post = _response


class AnswerController(MethodView):
    def _response(self):
        resp = VoiceResponse()
        resp.say("Thank you for calling! Have a great day.")
        return Response(str(resp), mimetype='text/xml')
    get = post = _response


class GreetThenRejoinController(MethodView):
    def _response(self):
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
    get = post = _response

# ---------------------------------------------------------------------------
# Register URL rules ---------------------------------------------------------
# ---------------------------------------------------------------------------

def register_controllers():
    api_bp.add_url_rule('/', view_func=IndexController.as_view('index'))
    api_bp.add_url_rule('/dialer', view_func=DialerController.as_view('dialer'))
    api_bp.add_url_rule('/token', view_func=TokenController.as_view('token'))
    api_bp.add_url_rule('/greeting', view_func=GreetingController.as_view('greeting'))
    api_bp.add_url_rule('/voice', view_func=VoiceController.as_view('voice'))
    api_bp.add_url_rule('/call-events', view_func=CallEventsController.as_view('call_events'))
    api_bp.add_url_rule('/hold-call', view_func=HoldCallController.as_view('hold_call'))
    api_bp.add_url_rule('/join_conference', view_func=JoinConferenceController.as_view('join_conference'))
    api_bp.add_url_rule('/unhold-call', view_func=UnholdCallController.as_view('unhold_call'))
    api_bp.add_url_rule('/hold-music', view_func=HoldMusicController.as_view('hold_music'))
    api_bp.add_url_rule('/connect_to_conference', view_func=ConnectToConferenceController.as_view('connect_to_conference'))
    api_bp.add_url_rule('/conference-announcement', view_func=ConferenceAnnouncementController.as_view('conference_announcement'))
    api_bp.add_url_rule('/hangup', view_func=HangupController.as_view('hangup'))
    api_bp.add_url_rule('/answer', view_func=AnswerController.as_view('answer'))
    api_bp.add_url_rule('/greet_then_rejoin', view_func=GreetThenRejoinController.as_view('greet_then_rejoin'))

# Call registration immediately
register_controllers() 