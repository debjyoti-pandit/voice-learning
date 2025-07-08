# voice-calling-learning

A reference Flask backend that demonstrates how to build a full-featured browser dialler with [Twilio Programmable Voice](https://www.twilio.com/voice). It issues access tokens, handles Twilio webhooks for incoming and outgoing calls, and exposes a Socket.IO channel so multiple browser clients can join, hold, transfer or conference calls in real-time.

The project is intentionally kept small and dependency-light so you can focus on learning the call-flow concepts rather than framework plumbing.

## Running locally

1. **Clone & create a virtual environment**

   ```bash
   git clone https://github.com/debjyoti-pandit/voice-learning.git
   cd voice-learning
   python -m venv venv && source venv/bin/activate
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables**  
   Copy the provided sample and fill in your real Twilio credentials:

   ```bash
   cp env.example .env
   # then edit .env with your favourite editor
   ```

   At a minimum you will need:

   • `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` – found in the Twilio Console  
   • `TWILIO_API_KEY`, `TWILIO_API_SECRET` – for generating Voice Access Tokens  
   • `CALLER_ID` – a verified/owned Twilio phone number you want to dial from  

4. **(Optional) Expose your server with ngrok**  
   Twilio needs to reach your machine over the public internet.  
   The provided helper script spins up a tunnel on the reserved sub-domain configured in `src/constants.py`:

   ```bash
   ./start_ngrok.sh
   ```

   Make a note of the HTTPS forwarding URL and add it to your Twilio application/webhook configuration.

5. **Run the development server**

   ```bash
   python app.py
   ```

   The app listens on `http://localhost:5678` by default.

Once the server is up you can open the web dialler (served from `/`) in two separate browser tabs or devices, connect them, and start experimenting with call flows (hold, transfer, conference, etc.).

## Development Helpers

### Start your local tunnel with ngrok

To expose the local development server running on port 5678 with your reserved ngrok subdomain, you can use the convenience script that lives at the project root:

```bash
./start_ngrok.sh
```

This starts ngrok using the reserved domain `debjyoti-voice-learning.ngrok-free.app`, so you don't need to type the full command every time. Ensure the script has execute permissions:

```bash
chmod +x start_ngrok.sh
```

You will see the forwarding URL printed in your terminal once the tunnel is established.
