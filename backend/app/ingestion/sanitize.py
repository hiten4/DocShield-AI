"""Strip characters commonly used to hide prompt injection.

Kills zero-width chars, bidi overrides, control chars, and collapses
mixed-case Unicode homoglyph runs that don't add semantic value.
"""

import re
import unicodedata

_INVISIBLE = re.compile(
    "[​‌‍⁠﻿­"  # zero-width, soft hyphen
    "‪-‮⁦-⁩"              # bidi overrides
    "]"
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE.sub("", text)
    text = _CONTROL.sub(" ", text)
    # Collapse absurd whitespace runs
    text = re.sub(r"[ \t]{3,}", "  ", text)
    return text.strip()
