from flask import url_for

def play_greeting_to_participant(participant_call_sid: str, conference_name: str):
    """Redirect a single call leg so it hears the greeting then re-joins."""
    greeting_url = url_for('.greet_then_rejoin', conference_name=conference_name, _external=True)
    client.calls(participant_call_sid).update(url=greeting_url, method='POST')