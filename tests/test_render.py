from datetime import datetime

from conftest import requires_chromium
from veille.carousel.render import render_slides

pytestmark = requires_chromium


async def test_sample_renders_without_overflow(settings, sample_content, tmp_path):
    result = await render_slides(settings, sample_content, tmp_path, 1, datetime(2026, 1, 1), None)
    assert len(result.paths) == len(sample_content.slides)
    assert all(p.stat().st_size > 10_000 for p in result.paths)
    assert result.overflows == []


async def test_overflow_is_reported(settings, sample_content, tmp_path):
    content = sample_content.model_copy(deep=True)
    points = content.slides[1]
    points.bullets = ["A long bullet that keeps going to fill the slide with text over several lines " * 1] * 9
    result = await render_slides(settings, content, tmp_path, 1, datetime(2026, 1, 1), None)
    assert any(o.startswith("slide 2 (mechanism)") for o in result.overflows)
