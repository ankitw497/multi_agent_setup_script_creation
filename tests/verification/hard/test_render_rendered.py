"""Tests for verification/hard/render_rendered.py -- V1C's rendered checks.

The pure judgment functions are unit-tested here with zero browser
dependency (the default fast suite). The one real-Chromium check is a
single @pytest.mark.integration test at the bottom -- run only via
`pytest -m integration`, matching this project's existing convention for
anything that needs a real browser or a real paid call.
"""
import pytest

from verification.hard.render_rendered import (
    _contrast_fails, _contrast_ratio, _is_clipped_or_overflowing, _is_invisible, _relative_luminance,
)


# ---- _is_clipped_or_overflowing ----

def test_content_fitting_its_box_is_not_clipped():
    assert _is_clipped_or_overflowing(scroll_width=500, client_width=500, scroll_height=200, client_height=200) is False


def test_content_wider_than_its_box_is_clipped():
    assert _is_clipped_or_overflowing(scroll_width=800, client_width=500, scroll_height=200, client_height=200) is True


def test_content_taller_than_its_box_is_clipped():
    assert _is_clipped_or_overflowing(scroll_width=500, client_width=500, scroll_height=600, client_height=200) is True


def test_sub_pixel_rounding_noise_is_not_flagged():
    """A 1px difference from rounding is not a real overflow."""
    assert _is_clipped_or_overflowing(scroll_width=501, client_width=500, scroll_height=200, client_height=200) is False


# ---- _is_invisible ----

def test_normal_visible_element_is_not_invisible():
    assert _is_invisible(opacity=1.0, visibility="visible", display="block", bbox_width=300, bbox_height=50) is False


def test_display_none_is_invisible():
    assert _is_invisible(opacity=1.0, visibility="visible", display="none", bbox_width=300, bbox_height=50) is True


def test_visibility_hidden_is_invisible():
    assert _is_invisible(opacity=1.0, visibility="hidden", display="block", bbox_width=300, bbox_height=50) is True


def test_zero_opacity_is_invisible():
    assert _is_invisible(opacity=0.0, visibility="visible", display="block", bbox_width=300, bbox_height=50) is True


def test_zero_size_bounding_box_is_invisible():
    assert _is_invisible(opacity=1.0, visibility="visible", display="block", bbox_width=0, bbox_height=50) is True


def test_partial_opacity_is_not_invisible():
    """0.05 opacity is a design choice (e.g. this codebase's own watermark
    experiments), not an accessibility failure -- only fully-zero counts."""
    assert _is_invisible(opacity=0.05, visibility="visible", display="block", bbox_width=300, bbox_height=50) is False


# ---- contrast ----

def test_black_on_white_has_maximum_contrast():
    ratio = _contrast_ratio((0, 0, 0), (255, 255, 255))
    assert ratio == pytest.approx(21.0, abs=0.1)


def test_identical_colors_have_a_contrast_of_one():
    ratio = _contrast_ratio((128, 128, 128), (128, 128, 128))
    assert ratio == pytest.approx(1.0, abs=0.01)


def test_contrast_ratio_is_symmetric_fg_bg_order_does_not_matter():
    a = _contrast_ratio((0, 0, 0), (255, 255, 255))
    b = _contrast_ratio((255, 255, 255), (0, 0, 0))
    assert a == pytest.approx(b, abs=0.001)


def test_light_gray_on_white_fails_the_wcag_threshold():
    """A real, common design mistake -- pale gray text on a white card."""
    ratio = _contrast_ratio((220, 220, 220), (255, 255, 255))
    assert _contrast_fails(ratio) is True


def test_black_on_white_passes_the_wcag_threshold():
    ratio = _contrast_ratio((0, 0, 0), (255, 255, 255))
    assert _contrast_fails(ratio) is False


def test_relative_luminance_of_white_is_one_and_black_is_zero():
    assert _relative_luminance((255, 255, 255)) == pytest.approx(1.0, abs=0.001)
    assert _relative_luminance((0, 0, 0)) == pytest.approx(0.0, abs=0.001)


# ---- real Chromium, one deliberately-broken fixture, all three checks at once ----

_BROKEN_FIXTURE_HTML = """\
<!doctype html><html><head><meta charset="utf-8"><style>
body { margin: 0; font-family: sans-serif; }
#clipped-scene { width: 100px; height: 30px; overflow: hidden; }
#clipped-scene .content { width: 500px; height: 200px; }
#invisible-scene { opacity: 0; }
#low-contrast-scene { color: rgb(230,230,230); background: rgb(255,255,255); }
#clean-scene { color: rgb(0,0,0); background: rgb(255,255,255); }
</style></head><body>
<div id="clipped-scene" data-narration-id="clipped-scene"><div class="content">this text is way too big for its clipped container and will overflow both dimensions of the box</div></div>
<div id="invisible-scene" data-narration-id="invisible-scene"><p>this scene has real narrated text but the whole thing is invisible</p></div>
<div id="low-contrast-scene" data-narration-id="low-contrast-scene"><p>pale gray text that fails WCAG contrast against a white background</p></div>
<div id="clean-scene" data-narration-id="clean-scene"><p>this scene is completely fine, black text on white</p></div>
</body></html>
"""


def _fixture_narration():
    from narration.models import SceneNarration, SentenceNarration

    return [
        SceneNarration(scene_id=sid, sentences=[SentenceNarration(text="x", sentence_type="transition")])
        for sid in ("clipped-scene", "invisible-scene", "low-contrast-scene", "clean-scene")
    ]


@pytest.mark.integration
def test_real_chromium_catches_all_three_deliberately_broken_scenes():
    """The one live check that actually opens a browser -- confirms the
    Playwright glue functions work against a real DOM, not just against
    the pure judgment functions' plain-value unit tests above."""
    from verification.hard.render_rendered import run_rendered_checks

    issues = run_rendered_checks(_BROKEN_FIXTURE_HTML, _fixture_narration())
    codes_by_scene = {(i.scene_id, i.code) for i in issues}

    assert ("clipped-scene", "rendered_clipping") in codes_by_scene
    assert ("invisible-scene", "rendered_invisible_required_content") in codes_by_scene
    assert ("low-contrast-scene", "rendered_low_contrast") in codes_by_scene
    # the clean scene must never be flagged by any check, at either viewport
    assert not any(i.scene_id == "clean-scene" for i in issues)


@pytest.mark.integration
def test_capture_scene_screenshots_returns_real_jpeg_data_uris():
    from verification.hard.render_rendered import capture_scene_screenshots

    screenshots = capture_scene_screenshots(_BROKEN_FIXTURE_HTML, ["clean-scene", "does-not-exist"])

    assert "does-not-exist" not in screenshots
    assert screenshots["clean-scene"].startswith("data:image/jpeg;base64,")
    import base64
    raw = base64.b64decode(screenshots["clean-scene"].split(",", 1)[1])
    assert raw[:2] == b"\xff\xd8"  # JPEG magic bytes
