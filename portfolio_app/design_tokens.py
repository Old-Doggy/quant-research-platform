"""Stable visual tokens for the v4 workbench prototypes.

The token layer is intentionally independent from Streamlit and chart code.
It defines the visual contract before any production page is migrated.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


def _freeze(values: Mapping[str, object]) -> MappingProxyType:
    return MappingProxyType(dict(values))


COLOR_TOKENS = _freeze({
    "background": "#F7F8FA",
    "surface": "#FFFFFF",
    "text": "#263238",
    "muted_text": "#59666F",
    "divider": "#D8DEE4",
    "primary": "#176B5B",
    "research": "#3F6CB5",
    "up": "#C93B45",
    "down": "#16836C",
    "warning": "#946C13",
})

FONT_SIZE_TOKENS = _freeze({
    "body": 14,
    "toolbar": 13,
    "table": 13,
    "page_title": 20,
    "section_title": 15,
    "price": 22,
    "key_metric": 18,
})

RADIUS_TOKENS = _freeze({
    "control": 4,
    "section": 6,
    "card": 6,
})

SPACING_TOKENS = (4, 8, 12, 16, 24)

UI_TOKENS = _freeze({
    **COLOR_TOKENS,
    "font_family_cjk": "Microsoft YaHei, PingFang SC",
    "font_family_latin": "sans-serif",
    "desktop_icon_button_px": 32,
    "mobile_touch_target_px": 44,
    "label_wrap": "wrap",
    "numeric_alignment": "right",
    "unknown_value": "—",
    "icon_button_requires_tooltip": True,
    "icon_button_requires_aria_label": True,
    "max_simultaneous_indicator_panes": 3,
    "default_indicator_panes": 1,
    "letter_spacing": 0,
    "spacing": SPACING_TOKENS,
    "radius": RADIUS_TOKENS,
    "font_size": FONT_SIZE_TOKENS,
})


def _channel(value: str) -> float:
    return int(value, 16) / 255.0


def _relative_luminance(color: str) -> float:
    normalized = color.strip().lstrip("#")
    if len(normalized) != 6 or any(char not in "0123456789abcdefABCDEF" for char in normalized):
        raise ValueError(f"invalid six-digit color: {color}")
    channels = [_channel(normalized[index:index + 2]) for index in (0, 2, 4)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    """Return the WCAG contrast ratio for two six-digit hex colors."""

    first = _relative_luminance(foreground)
    second = _relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def validate_design_tokens(overrides: Mapping[str, object] | None = None) -> list[str]:
    """Return contract violations without mutating the canonical tokens."""

    errors: list[str] = []
    values = dict(UI_TOKENS)
    if overrides:
        values.update(overrides)

    for key in ("text", "muted_text", "primary"):
        try:
            if contrast_ratio(str(values[key]), str(values["surface"])) < 4.5:
                errors.append(f"{key} does not meet 4.5:1 text contrast")
        except (KeyError, ValueError) as exc:
            errors.append(f"{key} has an invalid color: {exc}")

    spacing = values.get("spacing", SPACING_TOKENS)
    if spacing != SPACING_TOKENS:
        errors.append("spacing must use the fixed 4/8/12/16/24 scale")
    radius = values.get("radius", RADIUS_TOKENS)
    if not isinstance(radius, Mapping):
        errors.append("radius must be a mapping")
    elif any(not isinstance(value, int) or value < 0 or value > 8 for value in radius.values()):
        errors.append("radius values must be integer pixels between 0 and 8")
    font_sizes = values.get("font_size", FONT_SIZE_TOKENS)
    if not isinstance(font_sizes, Mapping):
        errors.append("font_size must be a mapping")
    elif any(not isinstance(value, int) or value <= 0 for value in font_sizes.values()):
        errors.append("font_size values must be positive integer pixels")

    if values.get("letter_spacing") != 0:
        errors.append("letter spacing must be zero")
    if values.get("mobile_touch_target_px", 0) < 44:
        errors.append("mobile touch targets must be at least 44px")
    if values.get("desktop_icon_button_px", 0) != 32:
        errors.append("desktop icon buttons must be 32px")
    if values.get("label_wrap") != "wrap":
        errors.append("long labels must wrap")
    return errors
