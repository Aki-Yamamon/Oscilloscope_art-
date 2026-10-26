"""Video and audio extraction helpers for OSA conversion."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Iterator

import numpy as np

DEFAULT_FPS = 30
DEFAULT_AUDIO_RATE = 22050
AUDIO_SILENCE = 128


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: float
    duration_sec: float
    has_audio: bool


def _require_tool(name: str) -> str:
    """Return the executable path or raise a helpful error."""
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(
            f"Required tool '{name}' was not found. "
            "Please install it and make sure it is on PATH."
        )
    return executable


def get_video_info(video_path: str | Path) -> VideoInfo:
    """Read video dimensions, frame rate, duration, and audio presence."""
    ffprobe = _require_tool("ffprobe")
    path = Path(video_path)

    if not path.is_file():
        raise FileNotFoundError(f"Video file not found: {path}")

    result = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-show_streams",
            "-show_format",
            "-of", "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    metadata = json.loads(result.stdout)
    streams = metadata.get("streams", [])

    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise ValueError(f"No video stream found in: {path}")

    rate_text = video_stream.get("avg_frame_rate") or video_stream.get(
        "r_frame_rate", "0/1"
    )
    try:
        fps = float(Fraction(rate_text))
    except (ValueError, ZeroDivisionError):
        fps = 0.0

    duration_text = video_stream.get("duration") or metadata.get(
        "format", {}
    ).get("duration", 0)
    duration_sec = float(duration_text or 0)

    return VideoInfo(
        width=int(video_stream["width"]),
        height=int(video_stream["height"]),
        fps=fps,
        duration_sec=duration_sec,
        has_audio=any(
            stream.get("codec_type") == "audio" for stream in streams
        ),
    )


def iter_frames(
    video_path: str | Path,
    fps: int = DEFAULT_FPS,
    start_sec: float = 0.0,
    max_frames: int | None = None,
) -> Iterator[np.ndarray]:
    """Yield writable, contiguous grayscale uint8 frames."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    if start_sec < 0:
        raise ValueError("start_sec must be non-negative")
    if max_frames is not None and max_frames < 0:
        raise ValueError("max_frames must be non-negative")

    ffmpeg = _require_tool("ffmpeg")
    info = get_video_info(video_path)

    command = [
        ffmpeg,
        "-v", "error",
        "-ss", str(start_sec),
        "-i", str(video_path),
        "-vf", f"fps={fps},format=gray",
    ]

    if max_frames is not None:
        command.extend(["-frames:v", str(max_frames)])

    command.extend([
        "-f", "rawvideo",
        "-pix_fmt", "gray",
        "-",
    ])

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None

    frame_bytes = info.width * info.height
    count = 0

    try:
        while max_frames is None or count < max_frames:
            raw = process.stdout.read(frame_bytes)
            if len(raw) == 0:
                break
            if len(raw) != frame_bytes:
                raise RuntimeError("ffmpeg returned an incomplete video frame")

            frame = np.frombuffer(raw, dtype=np.uint8).reshape(
                info.height, info.width
            )
            yield np.ascontiguousarray(frame).copy()
            count += 1

    finally:
        try:
            _, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            _, stderr = process.communicate()

        if process.returncode != 0:
            error_text = stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"ffmpeg failed: {error_text}")


def extract_audio(
    video_path: str | Path,
    rate: int = DEFAULT_AUDIO_RATE,
    start_sec: float = 0.0,
    duration_sec: float | None = None,
) -> np.ndarray:
    """Extract mono unsigned 8-bit PCM audio; return empty if no audio exists."""
    if rate <= 0:
        raise ValueError("rate must be positive")
    if start_sec < 0:
        raise ValueError("start_sec must be non-negative")
    if duration_sec is not None and duration_sec < 0:
        raise ValueError("duration_sec must be non-negative")

    info = get_video_info(video_path)
    if not info.has_audio:
        return np.empty(0, dtype=np.uint8)

    ffmpeg = _require_tool("ffmpeg")
    command = [
        ffmpeg,
        "-v", "error",
        "-ss", str(start_sec),
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", str(rate),
        "-c:a", "pcm_u8",
    ]

    if duration_sec is not None:
        command.extend(["-t", str(duration_sec)])

    command.extend(["-f", "u8", "-"])

    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
    )
    return np.frombuffer(result.stdout, dtype=np.uint8).copy()


def calc_audio_per_frame(
    rate: int = DEFAULT_AUDIO_RATE,
    fps: int = DEFAULT_FPS,
) -> int:
    """Return the integer number of audio samples per video frame."""
    if rate <= 0 or fps <= 0:
        raise ValueError("rate and fps must be positive")
    if rate % fps != 0:
        raise ValueError("audio rate must be divisible by fps")
    return rate // fps


def fit_audio_to_frames(
    audio: np.ndarray,
    frame_count: int,
    audio_per_frame: int,
) -> np.ndarray:
    """Pad audio with unsigned 8-bit silence or truncate to the required size."""
    if frame_count < 0 or audio_per_frame < 0:
        raise ValueError("frame_count and audio_per_frame must be non-negative")

    target_length = frame_count * audio_per_frame
    samples = np.asarray(audio, dtype=np.uint8).reshape(-1)

    if len(samples) >= target_length:
        return samples[:target_length].copy()

    result = np.full(target_length, AUDIO_SILENCE, dtype=np.uint8)
    result[:len(samples)] = samples
    return result

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m osaconv.extract <video_path>")
        raise SystemExit(1)

    path = sys.argv[1]
    info = get_video_info(path)
    print(info)

    n = sum(1 for _ in iter_frames(path, max_frames=60))
    print("frames:", n)

    audio = extract_audio(path, duration_sec=2.0)
    if len(audio) > 0:
        print("audio samples:", len(audio), "min/max:", audio.min(), audio.max())
    else:
        print("audio samples: 0 (no audio)")