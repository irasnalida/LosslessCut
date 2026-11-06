from __future__ import annotations

from itertools import pairwise

import pytest

from losslesscut.ffmpeg_utils import FFmpegError
from losslesscut.ffprobe import probe_keyframes, probe_media


@pytest.mark.integration
def test_probe_media(sample_video) -> None:
    media = probe_media(sample_video)
    assert media.duration == pytest.approx(6.0, abs=0.15)
    assert media.fps == pytest.approx(30.0, abs=0.001)
    assert media.display_size == (320, 180)
    assert media.video_codec == "h264"
    assert media.audio_streams
    assert media.size > 0


@pytest.mark.integration
def test_probe_keyframes(sample_media) -> None:
    keyframes = probe_keyframes(sample_media)
    assert keyframes[0] == 0.0
    assert len(keyframes) >= 5
    assert all(b > a for a, b in pairwise(keyframes))
    assert any(abs(value - 3.0) < 0.05 for value in keyframes)


@pytest.mark.integration
def test_probe_rejects_non_video(tmp_path) -> None:
    text = tmp_path / "not-video.mp4"
    text.write_text("hello")
    with pytest.raises(FFmpegError):
        probe_media(text)
