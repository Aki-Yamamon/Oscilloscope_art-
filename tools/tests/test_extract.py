import subprocess
from pathlib import Path

import numpy as np
import pytest

from osaconv.extract import (
    AUDIO_SILENCE,
    DEFAULT_AUDIO_RATE,
    DEFAULT_FPS,
    VideoInfo,
    calc_audio_per_frame,
    extract_audio,
    fit_audio_to_frames,
    get_video_info,
    iter_frames,
)


def test_video_info_defaults():
    info = VideoInfo(
        width=640,
        height=480,
        fps=30.0,
        duration_sec=2.0,
        has_audio=True,
    )
    assert info.width == 640
    assert info.height == 480
    assert info.fps == 30.0
    assert info.duration_sec == 2.0
    assert info.has_audio is True


def test_calc_audio_per_frame_default():
    assert calc_audio_per_frame() == 735
    assert calc_audio_per_frame() == DEFAULT_AUDIO_RATE // DEFAULT_FPS


def test_calc_audio_per_frame_custom():
    assert calc_audio_per_frame(rate=24000, fps=30) == 800


def test_calc_audio_per_frame_invalid_rate():
    with pytest.raises(ValueError):
        calc_audio_per_frame(rate=22050, fps=29)


def test_calc_audio_per_frame_non_positive_values():
    with pytest.raises(ValueError):
        calc_audio_per_frame(rate=0, fps=30)
    with pytest.raises(ValueError):
        calc_audio_per_frame(rate=22050, fps=0)


def test_fit_audio_to_frames_pads_with_silence():
    audio = np.array([10, 20, 30], dtype=np.uint8)

    result = fit_audio_to_frames(audio, frame_count=2, audio_per_frame=3)

    expected = np.array([10, 20, 30, AUDIO_SILENCE, AUDIO_SILENCE, AUDIO_SILENCE])
    np.testing.assert_array_equal(result, expected)
    assert result.dtype == np.uint8


def test_fit_audio_to_frames_truncates():
    audio = np.array([10, 20, 30, 40, 50], dtype=np.uint8)

    result = fit_audio_to_frames(audio, frame_count=1, audio_per_frame=3)

    np.testing.assert_array_equal(result, np.array([10, 20, 30], dtype=np.uint8))


def test_fit_audio_to_frames_empty_audio():
    result = fit_audio_to_frames(
        np.array([], dtype=np.uint8),
        frame_count=2,
        audio_per_frame=3,
    )

    np.testing.assert_array_equal(
        result,
        np.full(6, AUDIO_SILENCE, dtype=np.uint8),
    )


def test_fit_audio_to_frames_zero_frames():
    result = fit_audio_to_frames(
        np.array([10, 20], dtype=np.uint8),
        frame_count=0,
        audio_per_frame=3,
    )

    assert result.size == 0


def test_fit_audio_to_frames_rejects_negative_values():
    with pytest.raises(ValueError):
        fit_audio_to_frames(np.array([], dtype=np.uint8), -1, 3)
    with pytest.raises(ValueError):
        fit_audio_to_frames(np.array([], dtype=np.uint8), 1, -1)


@pytest.fixture
def sample_videos(tmp_path):
    video_with_audio = tmp_path / "with_audio.mp4"
    video_without_audio = tmp_path / "without_audio.mp4"

    common = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-f", "lavfi",
        "-i", "testsrc=size=64x48:rate=30:duration=1",
    ]

    subprocess.run(
        common + [
            "-f", "lavfi",
            "-i", "sine=frequency=440:sample_rate=22050:duration=1",
            "-c:v", "mpeg4",
            "-c:a", "aac",
            "-shortest",
            str(video_with_audio),
        ],
        check=True,
        capture_output=True,
    )

    subprocess.run(
        common + [
            "-an",
            "-c:v", "mpeg4",
            str(video_without_audio),
        ],
        check=True,
        capture_output=True,
    )

    return video_with_audio, video_without_audio


def test_get_video_info(sample_videos):
    video, _ = sample_videos
    info = get_video_info(video)

    assert info.width == 64
    assert info.height == 48
    assert info.fps == 30
    assert info.duration_sec > 0
    assert info.has_audio is True


def test_get_video_info_without_audio(sample_videos):
    _, video = sample_videos
    info = get_video_info(video)

    assert info.has_audio is False


def test_iter_frames(sample_videos):
    video, _ = sample_videos
    frames = list(iter_frames(video, fps=30, max_frames=3))

    assert len(frames) == 3
    for frame in frames:
        assert frame.shape == (48, 64)
        assert frame.dtype == np.uint8
        assert frame.flags.c_contiguous
        assert frame.flags.writeable


def test_extract_audio(sample_videos):
    video, _ = sample_videos
    audio = extract_audio(video, rate=22050)

    assert audio.dtype == np.uint8
    assert len(audio) > 0


def test_extract_audio_without_audio(sample_videos):
    _, video = sample_videos
    audio = extract_audio(video, rate=22050)

    assert audio.dtype == np.uint8
    assert len(audio) == 0