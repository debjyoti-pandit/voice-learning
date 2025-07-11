"""download_merge_recordings.py.

Download two audio recordings from the JustCall service by their recording IDs,
store them in recordings/source, merge (concat) them, and save the result into
recordings/result.

Usage (interactive):
    python src/download_merge_recordings.py

You need:
    - requests (pip install requests)
    - pydub   (pip install pydub)
    - ffmpeg  (brew install ffmpeg  # macOS, or use the official installers)
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from urllib.parse import urlparse

import requests
import urllib3
from pydub import AudioSegment

BASE_URL = (
    "https://callingservice.justcall.local/"
    "api/create_s3presigned_url.php?recsid={}&isnew=1&redirect=1"
)


def ensure_directories() -> tuple[str, str]:
    """Ensure recordings/source and recordings/result exist."""
    source_dir = os.path.join("recordings", "source")
    result_dir = os.path.join("recordings", "result")
    os.makedirs(source_dir, exist_ok=True)
    os.makedirs(result_dir, exist_ok=True)
    return source_dir, result_dir


def build_url(recording_id: str) -> str:
    return BASE_URL.format(recording_id)


def infer_extension(url: str, default: str = ".mp3") -> str:
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext if ext else default


def download_recording(
    recording_id: str,
    destination_folder: str,
    verify_ssl: bool = True,
) -> str:
    url = build_url(recording_id)

    try:
        response = requests.get(
            url,
            allow_redirects=True,
            timeout=30,
            verify=verify_ssl,
        )
        response.raise_for_status()
    except requests.exceptions.SSLError as ssl_err:
        if verify_ssl:
            # Retry once with SSL verification disabled.
            print(
                f"SSL verification failed for {recording_id}. Retrying without verification...",
                file=sys.stderr,
            )
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            return download_recording(
                recording_id, destination_folder, verify_ssl=False
            )
        raise ssl_err
    except requests.RequestException as exc:
        print(
            f"Failed to download recording {recording_id}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    ext = infer_extension(response.url)
    filename = f"{recording_id}{ext}"
    file_path = os.path.join(destination_folder, filename)

    with open(file_path, "wb") as file:
        file.write(response.content)

    print(f"Downloaded recording {recording_id} -> {file_path}")
    return file_path


def merge_recordings(first_path: str, second_path: str, output_path: str):
    print("Merging recordings...")
    first_audio = AudioSegment.from_file(first_path)
    second_audio = AudioSegment.from_file(second_path)

    merged_audio = first_audio + second_audio
    merged_audio.export(output_path, format="mp3")
    print(f"Merged audio saved to {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and merge two recordings."
    )
    parser.add_argument(
        "--skip-ssl-verify",
        action="store_true",
        help="Skip SSL certificate verification when downloading recordings.",
    )
    parser.add_argument(
        "--run-name",
        type=str,
        help=(
            "Optional unique name for this run. If omitted, a timestamp will be used. "
            "The value will be used for the source sub-folder and merged result filename."
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    base_source_dir, result_dir = ensure_directories()

    first_id = input("Enter the FIRST recording_id: ").strip()
    second_id = input("Enter the SECOND recording_id: ").strip()

    if not first_id or not second_id:
        print("Both recording IDs are required.", file=sys.stderr)
        sys.exit(1)

    # Determine unique run name
    if args.run_name:
        run_name = args.run_name.strip()
    else:
        # Use ISO-style timestamp to keep folder names sortable and unique
        run_name = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create per-run source directory
    run_source_dir = os.path.join(base_source_dir, run_name)
    os.makedirs(run_source_dir, exist_ok=True)

    first_path = download_recording(
        first_id,
        run_source_dir,
        verify_ssl=not args.skip_ssl_verify,
    )
    second_path = download_recording(
        second_id,
        run_source_dir,
        verify_ssl=not args.skip_ssl_verify,
    )

    output_filename = f"{run_name}.mp3"
    output_path = os.path.join(result_dir, output_filename)

    merge_recordings(first_path, second_path, output_path)


if __name__ == "__main__":
    main()
