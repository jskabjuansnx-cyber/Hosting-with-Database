# -*- coding: utf-8 -*-
"""
Forced Channel Subscription Guard
يتحقق من اشتراك المستخدم في القناة الإجبارية ويعرض رسالة الانضمام إذا لم يكن مشتركاً.
"""
import logging
from telegram import Update, Bot
from telegram.ext import ContextTypes
from telegram.error import TelegramError

import database as db
from utils.colored_buttons import btn, markup
from utils.msg_builder import build_entities

logger = logging.getLogger(__name__)


async def is_channel_member(bot: Bot, user_id: int) -> bool:
    """
    يتحقق من اشتراك المستخدم في القناة الإجبارية.
    يرجع True إذا كان مشتركاً أو إذا كان الاشتراك الإجباري معطلاً.
    """
    if not db.get_flag("forced_subscription"):
        return True

    # الأدمن معفي دائماً
    if db.is_admin(user_id):
        return True

    # نستخدم اليوزرنيم مباشرة — أسهل وأوضح للقنوات العامة
    channel_username = db.get_config("sub_channel_username", "").strip().lstrip("@")
    if not channel_username:
        return True  # لم يُضبط يوزرنيم → لا يُطبق

    try:
        member = await bot.get_chat_member(chat_id=f"@{channel_username}", user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except TelegramError as e:
        logger.warning(f"sub_guard check failed for user {user_id}: {e}")
        return True  # في حالة خطأ → لا نحجب المستخدم


async def send_subscription_required(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """يرسل رسالة الاشتراك الإجباري مع زر الانضمام وزر التحقق."""
    channel_username = db.get_config("sub_channel_username", "").strip().lstrip("@")
    channel_title    = db.get_config("sub_channel_title", "قناتنا").strip()

    sr_char, sr_id = db.get_emoji("SUB_REQUIRED")
    ch_char, ch_id = db.get_emoji("SUB_CHANNEL")
    ck_char, ck_id = db.get_emoji("SUB_CHECK")
    jn_char, jn_id = db.get_emoji("SUB_JOIN")

    text = (
        f"{sr_char} الاشتراك في القناة مطلوب\n\n"
        f"{ch_char} القناة: {channel_title}\n"
        f"اشترك ثم اضغط 'تحقق من اشتراكي'."
    )

    entities = build_entities(text, [
        (sr_char, sr_id),
        (ch_char, ch_id),
    ])

    rows = []
    if channel_username:
        rows.append([btn(f"انضم لـ {channel_title}", url=f"https://t.me/{channel_username}", style="success", icon=jn_id)])
    rows.append([btn("تحقق من اشتراكي", "check_subscription", style="primary", icon=ck_id)])

    kb = markup(*rows)

    if update.callback_query:
        await update.callback_query.answer("❌ يجب الاشتراك في القناة أولاً.", show_alert=True)
        await ctx.bot.send_message(
            chat_id=update.callback_query.message.chat_id,
            text=text,
            entities=entities,
            reply_markup=kb
        )
    else:
        await update.message.reply_text(text, entities=entities, reply_markup=kb)


async def check_and_guard(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Helper شامل — يتحقق ويرسل الرسالة إذا لزم.
    يرجع True إذا مسموح للمستخدم بالمتابعة، False إذا تم حجبه.
    """
    user = update.effective_user
    if not user:
        return True

    if await is_channel_member(ctx.bot, user.id):
        return True

    await send_subscription_required(update, ctx)
    return False
