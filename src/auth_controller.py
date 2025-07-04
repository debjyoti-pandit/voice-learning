from flask import Blueprint, request, jsonify
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from dotenv import load_dotenv
import os

load_dotenv()

auth_bp = Blueprint('auth', __name__)

                                                                            
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_API_KEY = os.getenv('TWILIO_API_KEY')
TWILIO_API_SECRET = os.getenv('TWILIO_API_SECRET')
TWIML_APP_SID = os.getenv('TWIML_APP_SID')


@auth_bp.route('/token', methods=['GET'])
def token():
    """Generate a JWT access token for Twilio Voice."""
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