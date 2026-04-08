# -*- coding: utf-8 -*-
"""
Helper to build Telegram messages with custom emoji entities.
Handles UTF-16 offset calculation automatically.
"""
from telegram import MessageEntity


def utf16_len(s: str) -> int:
    """Returns the UTF-16 length of a string (used for Telegram entity offsets)."""
    return len(s.encode('utf-16-le')) // 2


def utf16_offset(text: str, char_pos: int) -> int:
    """Returns the UTF-16 offset of a character position in a string."""
    return utf16_len(text[:char_pos])


def build_message(template: str, emoji_map: dict) -> tuple[str, list]:
    """
    Build a message with custom emoji entities.

    Args:
        template: Message text with emoji placeholders like {UPLOAD}, {FOLDER}
        emoji_map: dict of {placeholder: (emoji_char, custom_emoji_id)}

    Returns:
        (text, entities) tuple ready to pass to send_message
    """
    text = template
    for key, (char, _) in emoji_map.items():
        text = text.replace("{" + key + "}", char)

    entities = []
    for key, (char, emoji_id) in emoji_map.items():
        if not emoji_id:
            continue
        pos = text.find(char)
        while pos != -1:
            entities.append(MessageEntity(
                type="custom_emoji",
                offset=utf16_offset(text, pos),
                length=utf16_len(char),
                custom_emoji_id=emoji_id
            ))
            pos = text.find(char, pos + len(char))

    return text, entities


def build_entities(text: str, emoji_pairs: list[tuple[str, str]]) -> list:
    """
    يبني entities لنص جاهز فيه إيموجيات.

    Args:
        text: النص الكامل
        emoji_pairs: قائمة من (emoji_char, custom_emoji_id)
                     كل إيموجي موجود في النص هيتحول لـ custom_emoji entity

    Returns:
        list of MessageEntity

    مثال:
        text = "👋 أهلاً! 📁 ملفاتك"
        entities = build_entities(text, [
            ("👋", "5353027129250422669"),
            ("📁", "5433653135799228968"),
        ])
    """
    entities = []
    for char, emoji_id in emoji_pairs:
        if not emoji_id or not char:
            continue
        pos = text.find(char)
        while pos != -1:
            entities.append(MessageEntity(
                type="custom_emoji",
                offset=utf16_offset(text, pos),
                length=utf16_len(char),
                custom_emoji_id=emoji_id
            ))
            pos = text.find(char, pos + len(char))
    return entities
