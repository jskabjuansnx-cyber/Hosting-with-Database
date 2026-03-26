# -*- coding: utf-8 -*-
"""
Helper to build Telegram messages with custom emoji entities.
Handles UTF-16 offset calculation automatically.
"""
from telegram import MessageEntity


def utf16_len(s: str) -> int:
    return len(s.encode('utf-16-le')) // 2


def build_message(template: str, emoji_map: dict) -> tuple[str, list]:
    """
    Build a message with custom emoji entities.

    Args:
        template: Message text with emoji placeholders like {UPLOAD}, {FOLDER}
        emoji_map: dict of {placeholder: (emoji_char, custom_emoji_id)}

    Returns:
        (text, entities) tuple ready to pass to send_message

    Example:
        text, entities = build_message(
            "{UPLOAD} أرسل ملف .py أو .js",
            {"UPLOAD": ("📤", "5363793701728450630")}
        )
    """
    # First pass: replace placeholders with actual emoji chars
    text = template
    for key, (char, _) in emoji_map.items():
        text = text.replace("{" + key + "}", char)

    # Second pass: calculate UTF-16 offsets and build entities
    entities = []
    for key, (char, emoji_id) in emoji_map.items():
        pos = text.find(char)
        while pos != -1:
            offset = utf16_len(text[:pos])
            length = utf16_len(char)
            entities.append(MessageEntity(
                type="custom_emoji",
                offset=offset,
                length=length,
                custom_emoji_id=emoji_id
            ))
            pos = text.find(char, pos + len(char))

    return text, entities
