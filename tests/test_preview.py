from __future__ import annotations

import pytest
from PySide6.QtGui import QImage

from losslesscut.preview import FrameExtractor, extract_frame, fit_size


def test_fit_size() -> None:
    assert fit_size(1920, 1080, (1280, 720)) == (1280, 720)
    assert fit_size(640, 360, (1280, 720)) == (640, 360)
    assert fit_size(1080, 1920, (1280, 720)) == (405, 720)


@pytest.mark.integration
def test_extract_frame(sample_media) -> None:
    image = extract_frame(sample_media.path, 2.5, 160, 90)
    assert isinstance(image, QImage)
    assert not image.isNull()
    assert image.size().width() == 160
    assert image.size().height() == 90


@pytest.mark.integration
def test_frame_extractor_async(qtbot, sample_media) -> None:
    extractor = FrameExtractor()
    extractor.set_media(sample_media.path)
    with qtbot.waitSignal(extractor.frame_ready, timeout=15000) as blocker:
        extractor.request(1.0, 160, 90, immediate=True)
    at, image = blocker.args
    assert at == pytest.approx(1.0)
    assert isinstance(image, QImage)
    assert not image.isNull()
