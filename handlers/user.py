# -*- coding: utf-8 -*-
"""
User-facing handlers: /start, main menu, stats, speed test, /getid.
"""
import logging
import time
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, filters

import database as db
import runner
from config import OWNER_ID, ADMIN_FILE_LIMIT, WELCOME_PHOTO
from utils.helpers import format_uptime
from utils.colored_buttons import btn, markup
from utils.emoji_ids import (
    UPLOAD, LIGHTNING, FOLDER, CHART, CROWN, PHONE, BACK,
    WAVE, MASK, CROWN2, FOLDER2, BRAIN,
    UPLOAD3, FOLDER3, LIGHTNING2, TIMER, CLOCK, MASK2,
    CROWN3, DOWN_CHART, UP_CHART, ID_BADGE, GREEN_DOT,
    FREE_USER, PAID_USER
)
from utils.msg_builder import build_message

logger = logging.getLogger(__name__)
_bot_start_time = datetime.utcnow()


def _get_file_limit(user_id: int) -> int:
    if db.is_admin(user_id):
        return ADMIN_FILE_LIMIT
    if db.is_subscribed(user_id):
        return int(db.get_config("paid_file_limit", "15"))
    return int(db.get_config("free_file_limit", "1"))


def main_menu_kb(user_id: int) -> dict:
    rows = [
        [
            btn("رفع ملف",          "upload_info",   style="success", icon=UPLOAD),
            btn("ملفاتي",            "my_files",      style="primary", icon=FOLDER),
        ],
        [
            btn("سرعة البوت",        "ping",          style="primary", icon=LIGHTNING),
            btn("إحصائياتي",         "my_stats",      style="primary", icon=CHART),
        ],
        [
            btn("التواصل مع المالك", "contact_owner", style="primary", icon=PHONE),
            btn("قناة التحديثات",    url=db.get_config("update_channel", "https://t.me/Raven_xx24"), style="primary"),
        ],
    ]
    if db.is_admin(user_id):
        rows.insert(2, [btn("لوحة الأدمن", "admin_panel", style="success", icon=CROWN)])
    return markup(*rows)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    with db.get_session() as s:
        existing_user = s.get(db.User, user_id)
        is_new = existing_user is None

    db.upsert_user(user_id, user.username, user.full_name)

    if db.is_banned(user_id):
        await update.message.reply_text("🚫 أنت محظور من استخدام البوت.")
        return

    if not db.get_flag("bot_enabled"):
        await update.message.reply_text("🔒 البوت مغلق مؤقتاً. حاول لاحقاً.")
        return

    if db.get_flag("bot_locked") and not db.is_admin(user_id):
        await update.message.reply_text("🔒 البوت مغلق حالياً للصيانة.")
        return

    # Notify owner about new user
    if is_new and user_id != OWNER_ID:
        try:
            await ctx.bot.send_message(
                chat_id=OWNER_ID,
                text=(
                    "👤 مستخدم جديد دخل البوت!\n\n"
                    f"الاسم: {user.full_name or 'غير معروف'}\n"
                    f"المعرف: @{user.username or 'بدون'}\n"
                    f"الآي دي: `{user_id}`"
                ),
                parse_mode="Markdown"
            )
        except Exception:
            pass

    file_limit = _get_file_limit(user_id)
    if db.is_admin(user_id):
        role, status = "الأدمن", "لا نهائي"
        role_emoji_id = CROWN2       # 👑 custom
        role_emoji = "👑"
    elif db.is_subscribed(user_id):
        role, status = "مشترك مدفوع", f"{file_limit} ملفات"
        role_emoji_id = PAID_USER    # 💎 custom
        role_emoji = "💎"
    else:
        role, status = "مستخدم مجاني", f"{file_limit} ملف فقط"
        role_emoji_id = FREE_USER    # 👤 custom
        role_emoji = "👤"

    text = (
        f"👋 أهلاً {user.first_name}!\n\n"
        f"🎭 دورك: {role_emoji} {role}\n"
        f"📁 حد الملفات: {status}\n\n"
        f"🧠 يمكنك رفع وتشغيل سكربتات Python و JavaScript\n\n"
        "اختر من القائمة:"
    )

    def utf16_len(s):
        return len(s.encode('utf-16-le')) // 2

    def utf16_offset(text, char_offset):
        return utf16_len(text[:char_offset])

    from telegram import MessageEntity

    entities = []
    # 👋 at position 0
    entities.append(MessageEntity(
        type="custom_emoji", offset=0, length=utf16_len("👋"),
        custom_emoji_id="5353027129250422669"
    ))
    # 🎭 — find its position
    pos_mask = text.index("🎭")
    entities.append(MessageEntity(
        type="custom_emoji", offset=utf16_offset(text, pos_mask), length=utf16_len("🎭"),
        custom_emoji_id="5359441070201513074"
    ))
    # role emoji — use correct ID per role
    pos_role = text.index(role_emoji)
    entities.append(MessageEntity(
        type="custom_emoji", offset=utf16_offset(text, pos_role), length=utf16_len(role_emoji),
        custom_emoji_id=role_emoji_id
    ))
    # 📁
    pos_folder = text.index("📁")
    entities.append(MessageEntity(
        type="custom_emoji", offset=utf16_offset(text, pos_folder), length=utf16_len("📁"),
        custom_emoji_id="5433653135799228968"
    ))
    # 🧠
    pos_brain = text.index("🧠")
    entities.append(MessageEntity(
        type="custom_emoji", offset=utf16_offset(text, pos_brain), length=utf16_len("🧠"),
        custom_emoji_id="5226639745106330551"
    ))

    if WELCOME_PHOTO:
        try:
            await ctx.bot.send_photo(
                chat_id=update.message.chat_id,
                photo=WELCOME_PHOTO,
                caption=text,
                caption_entities=entities,
                reply_markup=main_menu_kb(user_id)
            )
            return
        except Exception:
            pass

    await update.message.reply_text(
        text,
        entities=entities,
        reply_markup=main_menu_kb(user_id)
    )


async def cmd_getid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """للأدمن فقط — يجيب custom emoji ID من أي رسالة فيها إيموجي مميزة."""
    if not db.is_admin(update.effective_user.id):
        return

    msg = update.message
    entities = msg.entities or msg.caption_entities or []
    ids_found = []

    for entity in entities:
        if entity.type == "custom_emoji":
            ids_found.append(entity.custom_emoji_id)

    if ids_found:
        result = "\n".join(f"`{eid}`" for eid in ids_found)
        await msg.reply_text(
            f"🆔 Custom Emoji IDs:\n\n{result}",
            parse_mode="Markdown"
        )
    else:
        await msg.reply_text(
            "❌ ما لقيتش custom emoji في الرسالة.\n"
            "ابعت رسالة فيها الإيموجي المتحركة مع /getid كـ reply."
        )


async def cb_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    t0 = time.time()
    
    # رسالة مؤقتة بدون custom emoji
    test_msg = await ctx.bot.send_message(query.message.chat_id, "⏱ جاري قياس السرعة...")
    
    response_time = round((time.time() - t0) * 1000, 2)
    uptime = format_uptime(_bot_start_time)
    user_id = query.from_user.id
    user_role = "أدمن" if db.is_admin(user_id) else ("مشترك" if db.is_subscribed(user_id) else "مجاني")

    from telegram import MessageEntity

    def utf16_len(s):
        return len(s.encode('utf-16-le')) // 2

    def utf16_off(text, pos):
        return utf16_len(text[:pos])

    line1 = "⚡ اختبار سرعة البوت\n\n"
    line2 = f"⏱ وقت الاستجابة: {response_time} مللي ثانية\n"
    line3 = f"⏰ وقت التشغيل: {uptime}\n"
    line4 = f"🎭 دورك: {user_role}\n"
    line5 = f"📊 الملفات النشطة: {len(runner._processes)}"
    full = line1 + line2 + line3 + line4 + line5

    entities = [
        MessageEntity(type="custom_emoji", offset=utf16_off(full, full.index("⚡")), length=utf16_len("⚡"), custom_emoji_id=LIGHTNING2),
        MessageEntity(type="custom_emoji", offset=utf16_off(full, full.index("⏱")), length=utf16_len("⏱"), custom_emoji_id=TIMER),
        MessageEntity(type="custom_emoji", offset=utf16_off(full, full.index("⏰")), length=utf16_len("⏰"), custom_emoji_id=CLOCK),
        MessageEntity(type="custom_emoji", offset=utf16_off(full, full.index("🎭")), length=utf16_len("🎭"), custom_emoji_id=MASK2),
        MessageEntity(type="custom_emoji", offset=utf16_off(full, full.index("📊")), length=utf16_len("📊"), custom_emoji_id=UP_CHART),
    ]

    await test_msg.edit_text(
        full,
        entities=entities,
        reply_markup=markup([btn("رجوع", "main_menu", style="danger", icon=BACK)])
    )


async def cb_my_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    scripts = db.get_user_scripts(user_id)
    running = sum(1 for s in scripts if db.get_script_status(s.id) and db.get_script_status(s.id).is_running)
    role = "أدمن" if db.is_admin(user_id) else ("مشترك" if db.is_subscribed(user_id) else "مجاني")

    from telegram import MessageEntity

    def utf16_len(s):
        return len(s.encode('utf-16-le')) // 2

    def utf16_off(text, pos):
        return utf16_len(text[:pos])

    line1 = "📊 إحصائياتك\n\n"
    line2 = f"🆔 المعرف: {user_id}\n"
    line3 = f"🎭 الدور: {role}\n"
    line4 = f"📁 عدد الملفات: {len(scripts)}\n"
    line5 = f"🟢 يعمل الآن: {running}"
    full = line1 + line2 + line3 + line4 + line5

    entities = [
        MessageEntity(type="custom_emoji", offset=utf16_off(full, full.index("📊")), length=utf16_len("📊"), custom_emoji_id=UP_CHART),
        MessageEntity(type="custom_emoji", offset=utf16_off(full, full.index("🆔")), length=utf16_len("🆔"), custom_emoji_id=ID_BADGE),
        MessageEntity(type="custom_emoji", offset=utf16_off(full, full.index("🎭")), length=utf16_len("🎭"), custom_emoji_id=MASK2),
        MessageEntity(type="custom_emoji", offset=utf16_off(full, full.index("📁")), length=utf16_len("📁"), custom_emoji_id=FOLDER2),
        MessageEntity(type="custom_emoji", offset=utf16_off(full, full.index("🟢")), length=utf16_len("🟢"), custom_emoji_id=GREEN_DOT),
    ]

    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=full,
        entities=entities,
        reply_markup=markup([btn("رجوع", "main_menu", style="danger", icon=BACK)])
    )


async def cb_upload_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not db.get_flag("upload_enabled"):
        await query.answer("❌ رفع الملفات معطل حالياً.", show_alert=True)
        return
    text, entities = build_message(
        "{UPLOAD} أرسل ملف .py أو .js مباشرة في المحادثة.",
        {"UPLOAD": ("📤", UPLOAD3)}
    )
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        entities=entities,
        reply_markup=markup([btn("رجوع", "main_menu", style="danger", icon=BACK)])
    )


async def cb_contact_owner(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    username = db.get_config("your_username", "@P_X_24").replace("@", "")
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text="📞 للتواصل مع المالك:",
        reply_markup=markup([
            btn("📞 التواصل", url=f"https://t.me/{username}", style="primary"),
            btn("رجوع", "main_menu", style="danger", icon=BACK)
        ])
    )


async def cb_main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text="🏠 القائمة الرئيسية:",
        reply_markup=main_menu_kb(user_id)
    )


def register(app):
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("getid",  cmd_getid))
    app.add_handler(CallbackQueryHandler(cb_ping,          pattern="^ping$"))
    app.add_handler(CallbackQueryHandler(cb_my_stats,      pattern="^my_stats$"))
    app.add_handler(CallbackQueryHandler(cb_upload_info,   pattern="^upload_info$"))
    app.add_handler(CallbackQueryHandler(cb_contact_owner, pattern="^contact_owner$"))
    app.add_handler(CallbackQueryHandler(cb_main_menu,     pattern="^main_menu$"))
