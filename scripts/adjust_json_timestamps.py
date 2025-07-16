import argparse
import json
import os
from typing import Any


def _adjust_word_time(word: dict[str, Any], epoch_start_ms: int) -> None:
    """Mutate a Deepgram word dict so its start/end times become absolute epoch."""
    epoch_sec = epoch_start_ms // 1000
    epoch_ms_remainder = epoch_start_ms % 1000
    epoch_nanos = epoch_ms_remainder * 1_000_000

    for key in ("startTime", "endTime"):
        tdict = word.get(key, {})
        sec = int(tdict.get("seconds", 0)) + epoch_sec
        nanos = int(tdict.get("nanos", 0)) + epoch_nanos
        if nanos >= 1_000_000_000:
            sec += nanos // 1_000_000_000
            nanos = nanos % 1_000_000_000
        tdict["seconds"] = sec
        tdict["finalseconds"] = sec
        tdict["nanos"] = str(nanos)
        tdict["finalnanos"] = str(nanos)


def adjust_transcript(
    data: dict[str, Any], epoch_start_ms: int
) -> dict[str, Any]:
    """Return transcript JSON with all word times shifted by epoch_start_ms."""
    for transcription in data.get("transcription", []):
        for result in transcription.get("results", []):
            for alt in result.get("alternatives", []):
                for word in alt.get("words", []):
                    _adjust_word_time(word, epoch_start_ms)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Adjust Deepgram transcript JSON times to absolute epoch."
    )
    parser.add_argument(
        "input",
        nargs="?",  # optional positional
        help="Path to the input transcript JSON file (omit to auto-select latest)",
    )
    # Removed positional epoch argument. The script will prompt the user for
    # the desired epoch start time interactively (this is the only prompt).
    parser.add_argument(
        "--output",
        help="Optional path for the output JSON file. Defaults to <input>_adjusted.json",
        default=None,
    )
    args = parser.parse_args()

    input_path = args.input
    if input_path is None:
        # Auto-select the most recent *.json file within the "transcripts" dir.
        transcripts_dir = os.path.join(os.getcwd(), "transcripts")
        if not os.path.isdir(transcripts_dir):
            raise SystemExit(
                "No input file specified and 'transcripts' directory not found."
            )

        json_files = [
            os.path.join(transcripts_dir, f)
            for f in os.listdir(transcripts_dir)
            if f.lower().endswith(".json")
        ]
        if not json_files:
            raise SystemExit(
                "No JSON transcripts found in 'transcripts'. Please specify input file."
            )

        input_path = max(json_files, key=os.path.getmtime)
        print(f"Auto-selected latest transcript: {input_path}")

    with open(input_path, encoding="utf-8") as fp:
        data = json.load(fp)

    # Always prompt the user for the desired absolute epoch start (ms).
    user_epoch_ms = int(
        input("Enter epoch start in milliseconds (absolute) to align with: ")
    )

    adjusted = adjust_transcript(data, user_epoch_ms)

    # Default output path: same name with "-adjusted" inserted before the
    # extension unless the user overrides with --output.
    output_path = (
        args.output or f"{os.path.splitext(input_path)[0]}-adjusted.json"
    )
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(adjusted, fp, ensure_ascii=False)

    print(f"Adjusted transcript written to {output_path}")


if __name__ == "__main__":
    main()
