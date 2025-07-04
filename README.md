# voice-calling-learning

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
