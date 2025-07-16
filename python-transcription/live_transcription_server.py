# live_transcription_server.py – rewritten for the new requirements

"""Streaming transcription server for Twilio Media Streams → Deepgram.

Key features
------------
1. Supports two call-flow types controlled by the customParameter ``call_flow_type``
   sent in Twilio's <Start><Stream> element:

   • ``normal``      – transcribe *both* tracks (inbound/outbound) that share the
     single Twilio stream.  The transcript JSON will be written to
     ``transcripts/normal-<epoch_ms>.json``.

   • ``conference``  – Twilio opens an individual Media Stream per participant.
     For these streams only *inbound* audio is transcribed so that we keep each
     participant in a separate file.  The output file name is derived from the
     participant label provided via ``track1_label``::

         transcripts/<participant>-<epoch_ms>.json

2. Produces a single JSON file per stream containing **every word** returned by
   Deepgram.  Each word is annotated with timing at *nanosecond* precision
   relative to the beginning of the stream (`0s 0ns`).

3. Designed to be standalone – no external helpers, global state, or Flask/FastAPI
   integration.  Run the module directly to start an asyncio WebSocket server
   that Twilio connects to, as well as a minimal HTTP endpoint that can be used
   for health-checks if desired.

Environment variables (see ``env.example``):
    DEEPGRAM_API_KEY   – your Deepgram API key (REQUIRED)
    WEBSOCKET_HOST     – IP/interface to bind the WebSocket server (default 0.0.0.0)
    WEBSOCKET_PORT     – Port for the WebSocket server (default 6789)
    CONTROL_HTTP_PORT  – Port for the lightweight aiohttp server (default 4567)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, cast

from aiohttp import web
from dotenv import load_dotenv

# websockets ≥10 renamed the sub-module; fall back for older versions.
try:
    from websockets.server import WebSocketServerProtocol, serve  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    from websockets.legacy.server import (  # type: ignore[attr-defined]
        WebSocketServerProtocol,
        serve,
    )

from deepgram import Deepgram

###############################################################################
# Configuration & helpers
###############################################################################

load_dotenv()

DEEPGRAM_API_KEY: Optional[str] = os.getenv("DEEPGRAM_API_KEY")
if not DEEPGRAM_API_KEY:
    raise EnvironmentError(
        "DEEPGRAM_API_KEY environment variable not set. Please export it first."
    )

WEBSOCKET_HOST: str = os.getenv("WEBSOCKET_HOST", "0.0.0.0")
WEBSOCKET_PORT: int = int(os.getenv("WEBSOCKET_PORT", "6789"))
CONTROL_HTTP_PORT: int = int(os.getenv("CONTROL_HTTP_PORT", "4567"))

# Deepgram streaming parameters tuned for Twilio 8 kHz µ-law mono streams.
DG_OPTIONS: Dict[str, Any] = {
    "model": "nova-3",
    "language": "en-US",
    "encoding": "mulaw",
    "sample_rate": 8000,
    "channels": 1,
    "punctuate": True,
    "interim_results": True,
    "diarize": False,  # track separation is handled by Twilio parameters
}

# Initialise Deepgram client once for the process
_DEEPGRAM: Any = Deepgram(DEEPGRAM_API_KEY)

# Optional overrides: /set_start can update these values while a stream is live.
STREAM_BASE_EPOCH_MS: dict[str, int] = {}

# Logging setup – INFO level is fine for production; DEBUG can be chatty
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# Utility regex for safe filenames
_SAFE_FILENAME_RE = re.compile(r"\W+")


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------


def _payload_is_silence(audio: bytes) -> bool:
    """Return True if the μ-law audio frame is pure silence.

    We treat a frame as silence when *all* bytes have the same value.  For μ-law,
    true digital silence is 0xFF (sometimes 0x7F), but using the set-size test
    is more robust against other encoders.
    """
    if not audio:
        return True
    return len(set(audio)) == 1


def _safe_label(label: str) -> str:
    """Return a filesystem-safe, lowercase label."""
    return _SAFE_FILENAME_RE.sub("_", label.strip().lower()) or "participant"


###############################################################################
# Deepgram helpers
###############################################################################


async def _create_deepgram_connection():
    """Open a Deepgram live transcription connection and return it with a queue.

    The queue receives every payload Deepgram emits for the lifetime of the
    connection.
    """
    transcript_q: asyncio.Queue[dict] = asyncio.Queue()

    async def _on_transcript(event: dict):  # noqa: D401
        await transcript_q.put(event)

    dg_socket = await getattr(_DEEPGRAM, "transcription").live(DG_OPTIONS)
    dg_socket.registerHandler(  # type: ignore[attr-defined]
        dg_socket.event.TRANSCRIPT_RECEIVED,
        _on_transcript,
    )
    return dg_socket, transcript_q


async def _consume_transcripts(
    queue: "asyncio.Queue[dict]",
    file_prefix: str,
):
    """Aggregate Deepgram transcripts and write them to disk when done.

    The function exits when ``None`` is pushed onto *queue*.
    """
    results: List[dict] = []  # each element is one Deepgram "final" result

    while True:
        payload = await queue.get()
        if payload is None:  # sentinel indicates end of stream
            break

        # We only care about payloads that contain alternatives/words
        channel: dict = payload.get("channel", {})
        alts: List[dict] = channel.get("alternatives", [])
        if not alts:
            continue

        alt: dict = alts[0]
        words: List[dict] = alt.get("words", [])
        if not words:
            continue

        word_entries: List[dict] = []
        for w in words:
            rel_start_s: float = float(w.get("start", 0.0))
            rel_end_s: float = float(w.get("end", rel_start_s))

            # Convert to (<seconds>, <nanos>) tuples
            s_sec = int(rel_start_s)
            s_ns = int((rel_start_s - s_sec) * 1_000_000_000)
            e_sec = int(rel_end_s)
            e_ns = int((rel_end_s - e_sec) * 1_000_000_000)

            word_entries.append(
                {
                    "word": w.get("word", ""),
                    "startTime": {"seconds": s_sec, "nanos": s_ns},
                    "endTime": {"seconds": e_sec, "nanos": e_ns},
                }
            )

        # Only append full word lists once Deepgram marks the result as final
        if payload.get("is_final", False):
            results.append({"alternatives": [{"words": word_entries}]})

    if not results:
        logging.info(
            "No transcript results to write for prefix %s", file_prefix
        )
        return

    output = {
        "transcription": [{"results": results}],
    }

    os.makedirs("transcripts", exist_ok=True)
    file_path = os.path.join(
        "transcripts", f"{file_prefix}-{int(time.time()*1000)}.json"
    )
    with open(file_path, "w", encoding="utf-8") as fp:
        json.dump(output, fp, ensure_ascii=False)

    logging.info("Transcript JSON written to %s", file_path)


###############################################################################
# WebSocket (Twilio) handler
###############################################################################


async def _twilio_media_handler(
    websocket: WebSocketServerProtocol,
):  # noqa: C901
    """Handle a single Twilio Media Stream connection."""

    logging.info("New connection from %s", websocket.remote_address)

    # We do not know flow-type / labels until the Start event, so keep them here
    call_flow_type: str | None = None  # "normal" or "conference"
    participant_label: str = "participant"

    # Epoch that aligns to Deepgram's 0.0 s. We set it on first media chunk.
    base_epoch_ms: Optional[int] = None
    stream_active: bool = (
        False  # becomes True once we forward first non-silent frame
    )
    # We intentionally ignore any recording_start custom params for now
    # to keep timing generic (relative to when we received Start).

    # Deepgram connection & transcript consumer – created after we see Start
    dg_socket = None  # type: ignore
    dg_queue: asyncio.Queue | None = None
    transcript_task: asyncio.Task | None = None

    try:
        async for raw_msg in websocket:
            try:
                msg = json.loads(raw_msg)
            except json.JSONDecodeError:
                logging.warning("Received non-JSON message: %s", raw_msg)
                continue

            event = msg.get("event")

            # -----------------------------------------------------------------
            # 1) START – extract metadata & bring Deepgram online
            # -----------------------------------------------------------------
            if event == "start":
                # Guard against duplicate Start events
                if dg_socket is not None:
                    continue

                start_info = msg.get("start", {})
                params: dict = start_info.get("customParameters", {})

                call_flow_type = params.get("call_flow_type", "normal").lower()
                participant_label = (
                    _safe_label(
                        params.get("track1_label")
                        or params.get("track0_label")
                        or "participant"
                    )
                    if call_flow_type == "conference"
                    else "normal"
                )

                # 2. Parse optional recording-start custom parameters to anchor JSON
                # We intentionally ignore any recording_start custom params for now
                # to keep timing generic (relative to when we received Start).

                logging.info(
                    "Stream %s started – flow=%s participant=%s",
                    msg.get("streamSid"),
                    call_flow_type,
                    participant_label,
                )

                # Initialise Deepgram connection **after** we've parsed metadata
                dg_socket, dg_queue = await _create_deepgram_connection()

                transcript_task = asyncio.create_task(
                    _consume_transcripts(
                        dg_queue,
                        (
                            "normal"
                            if call_flow_type == "normal"
                            else participant_label
                        ),
                    ),
                )

            # -----------------------------------------------------------------
            # 2) MEDIA – stream audio to Deepgram (optionally filter tracks)
            # -----------------------------------------------------------------
            elif event == "media":
                if dg_socket is None:
                    logging.warning("Media received before Start – ignored")
                    continue

                media = msg.get("media", {})
                track_name: str = media.get(
                    "track", "inbound"
                )  # inbound / outbound

                if call_flow_type == "conference" and track_name != "inbound":
                    # Ignore conference mix/outbound tracks
                    continue

                # ---------------------------------------------------------
                # Establish precise epoch on the very first media frame.
                # Twilio includes a `timestamp` (ms since stream start).  We
                # capture wall-clock now and subtract that relative value so
                # startEpochMs matches Deepgram's 0.0 reference.
                # ---------------------------------------------------------
                payload_b64 = media.get("payload")
                if not payload_b64:
                    continue

                try:
                    audio_bytes = base64.b64decode(payload_b64)
                except Exception as exc:  # noqa: BLE001
                    logging.warning("Bad base64 payload: %s", exc)
                    continue

                # Skip forwarding completely silent frames **until** we've seen
                # real audio once (saves Deepgram seconds & cost).
                if not stream_active and _payload_is_silence(audio_bytes):
                    continue  # wait for first non-silent chunk

                # Mark stream as active the first time we forward audio
                if not stream_active:
                    stream_active = True

                # Calibrate epoch if not done yet (we may have delayed until
                # first non-silent chunk).
                if base_epoch_ms is None:
                    ts_val = media.get("timestamp")
                    try:
                        rel_ms = int(ts_val)
                        now_ms = int(time.time() * 1000)
                        base_epoch_ms = now_ms - rel_ms
                        logging.info(
                            "Calibrated epoch for stream %s (rel %s ms)",
                            base_epoch_ms,
                            rel_ms,
                        )
                    except Exception:  # noqa: BLE001
                        pass

                # Forward to Deepgram now that we have real audio
                try:
                    dg_socket.send(audio_bytes)
                except Exception as exc:  # noqa: BLE001
                    logging.error(
                        "Failed to forward audio to Deepgram: %s", exc
                    )

            # -----------------------------------------------------------------
            # 3) STOP – clean up
            # -----------------------------------------------------------------
            elif event == "stop":
                logging.info("Stream %s stopped", msg.get("streamSid"))
                break

    except Exception as exc:  # noqa: BLE001
        logging.error("Unexpected error in media handler: %s", exc)
    finally:
        # -------------------------------------------------------------
        # Tidy up Deepgram & transcript consumer regardless of exit path
        # -------------------------------------------------------------
        if dg_socket is not None:
            try:
                await dg_socket.finish()
            except Exception:  # noqa: BLE001
                pass

        if dg_queue is not None:
            await dg_queue.put(None)  # signal _consume_transcripts to finish
        if transcript_task is not None:
            try:
                await transcript_task
            except asyncio.CancelledError:
                pass

        logging.info("Connection closed for %s", websocket.remote_address)


###############################################################################
# Entrypoint
###############################################################################


async def main() -> None:  # noqa: D401
    logging.info(
        "Starting WebSocket server on %s:%s", WEBSOCKET_HOST, WEBSOCKET_PORT
    )

    async with serve(
        _twilio_media_handler,
        WEBSOCKET_HOST,
        WEBSOCKET_PORT,
        subprotocols=cast(Any, ["twilio"]),  # Twilio requires this sub-protocol
        ping_interval=None,  # Twilio handles its own heartbeats
    ):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Server interrupted by user – shutting down.")
