from app.ingestion.sanitize import sanitize_text


def test_strips_zero_width():
    text = "hi​there‌ world‍!"
    assert sanitize_text(text) == "hithere world!"


def test_strips_bidi_override():
    text = "safe‮ evil"
    out = sanitize_text(text)
    assert "‮" not in out


def test_control_chars_become_space():
    text = "a\x00b\x01c"
    out = sanitize_text(text)
    assert "\x00" not in out and "\x01" not in out
