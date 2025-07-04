from flask import Blueprint, Response
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv

# Load environment variables (if not already loaded elsewhere)
load_dotenv()

# Blueprint for greeting routes
greet_bp = Blueprint('greet', __name__)


@greet_bp.route('/greeting', methods=['GET', 'POST'])
def greeting():
    """Simple TwiML greeting endpoint."""
    resp = VoiceResponse()
    resp.say("Thank you for calling Debjyoti's Dialer App! Have a great day.")
    return Response(str(resp), mimetype='text/xml') 