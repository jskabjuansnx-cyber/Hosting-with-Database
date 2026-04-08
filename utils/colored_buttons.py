# -*- coding: utf-8 -*-
"""
Colored Inline Buttons — Bot API 9.4
Supports: style (success/danger/primary) + icon_custom_emoji_id
"""


def btn(
    text: str,
    callback_data: str = None,
    url: str = None,
    style: str = "default",
    icon: str = None,
) -> dict:
    """Build a single colored inline button dict."""
    b = {"text": text}
    if callback_data:
        b["callback_data"] = callback_data
    if url:
        b["url"] = url
    if style and style != "default":
        b["style"] = style
    if icon:
        b["icon_custom_emoji_id"] = icon
    return b


def markup(*rows: list) -> dict:
    """Build inline_keyboard dict from rows of button dicts."""
    return {"inline_keyboard": list(rows)}
