from flask import current_app, url_for

# In-memory call log shared across blueprints
call_log: dict = {}

def play_greeting_to_participant(participant_call_sid: str, conference_name: str):
    """Redirect the given call leg to a greeting and then back to its conference."""
    client = current_app.config['twilio_client']
    greeting_url = url_for('greet.greet_then_rejoin', conference_name=conference_name, _external=True)
    client.calls(participant_call_sid).update(url=greeting_url, method='POST')
