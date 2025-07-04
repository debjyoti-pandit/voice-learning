from flask import Flask
from flask_socketio import SocketIO
from dotenv import load_dotenv
from src.templates_controller import templates_bp                  
from src.auth_controller import auth_bp                         
from src.greet_controller import greet_bp                   
from src.voice_controller import voice_bp                
from src.call_events_controller import events_bp                      
from src.conference_controller import conference_bp                     
import os
from twilio.rest import Client

load_dotenv()

                                                                             
                         
                                                                             

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

                                                                             
                                                                              
                                                                             

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

                                                                                 
app.config['socketio'] = socketio
app.config['twilio_client'] = twilio_client

                                                                             
                                                                               
                                                                             
call_log: dict[str, dict] = {}
app.config['call_log'] = call_log

                             
app.register_blueprint(templates_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(greet_bp)
app.register_blueprint(voice_bp)
app.register_blueprint(events_bp)
app.register_blueprint(conference_bp)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5678, debug=True)
