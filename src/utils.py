from flask import Response


def xml_response(twiml):
    """Return a Flask Response containing the given TwiML with the correct XML
    MIME type.
    """
    return Response(str(twiml), mimetype="text/xml")
