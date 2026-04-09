# -*- coding: utf-8 -*-
"""
User-facing handlers: /start, main menu, stats, speed test, /getid.
"""
import logging
import time
from datetime import datetime

from telegram import Update, MessageEntity
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, filters

import database as db
import runner
from config import OWNER_ID, ADMIN_FILE_LIMIT, WELCOME_PHOTO
from utils.helpers import format_uptime
from utils.colored_buttons import btn, markup
from utils.msg_builder import build_message, build_entities, utf16_len, utf16_offset
from utils.sub_guard import check_and_guard, is_channel_member, send_subscription_required

logger = logging.getLogger(__name__)
_bot_start_time = datetime.utcnow()


def _get_file_limit(user_id: int) -> int:
    if db.is_admin(user_id):
        return ADMIN_FILE_LIMIT
    if db.is_subscribed(user_id):
        return int(db.get_config("paid_file_limit", "15"))
    return int(db.get_config("free_file_limit", "3"))


def main_menu_kb(user_id: int) -> dict:
    """القائمة الرئيسية — الأيقونات تُقرأ من DB."""
    rows = [
        [
            btn("رفع ملف",          "upload_info",   style="success", icon=db.get_emoji("BTN_UPLOAD")[1]),
            btn("ملفاتي",            "my_files",      style="primary", icon=db.get_emoji("BTN_FILES")[1]),
        ],
        [
            btn("حالة السكربتات",   "scripts_status", style="primary", icon=db.get_emoji("BTN_STATUS")[1]),
            btn("إحصائياتي",         "my_stats",      style="primary", icon=db.get_emoji("BTN_STATS")[1]),
        ],
        [
            btn("سرعة البوت",        "ping",          style="primary", icon=db.get_emoji("BTN_SPEED")[1]),
            btn("مساعدة",            "help_menu",     style="primary", icon=db.get_emoji("BTN_HELP")[1]),
        ],
        [
            btn("التواصل مع المالك", "contact_owner", style="primary", icon=db.get_emoji("BTN_CONTACT")[1]),
            btn("قناة التحديثات",    url=db.get_config("update_channel", "https://t.me/Raven_xx24"), style="primary"),
        ],
    ]
    if db.is_admin(user_id):
        rows.insert(2, [btn("لوحة الأدمن", "admin_panel", style="success", icon=db.get_emoji("BTN_ADMIN")[1])])
    return markup(*rows)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = user.id

    with db.get_session() as s:
        existing_user = s.get(db.User, user_id)
        is_new = existing_user is None

    db.upsert_user(user_id, user.username, user.full_name)

    if db.is_banned(user_id):
        banned_char, banned_id = db.get_emoji("BANNED")
        text = f"{banned_char} أنت محظور من استخدام البوت."
        await update.message.reply_text(
            text,
            entities=build_entities(text, [(banned_char, banned_id)])
        )
        return

    if not db.get_flag("bot_enabled"):
        lock_char, lock_id = db.get_emoji("LOCKED")
        text = f"{lock_char} البوت مغلق مؤقتاً. حاول لاحقاً."
        await update.message.reply_text(
            text,
            entities=build_entities(text, [(lock_char, lock_id)])
        )
        return

    if db.get_flag("bot_locked") and not db.is_admin(user_id):
        lock_char, lock_id = db.get_emoji("LOCKED")
        text = f"{lock_char} البوت مغلق حالياً للصيانة."
        await update.message.reply_text(
            text,
            entities=build_entities(text, [(lock_char, lock_id)])
        )
        return

    # إشعار المالك بمستخدم جديد (قبل فحص الاشتراك عشان يوصل دايماً)
    if is_new and user_id != OWNER_ID:
        try:
            nu_char, nu_id = db.get_emoji("NEW_USER")
            notif_text = (
                f"{nu_char} مستخدم جديد!\n\n"
                f"الاسم: {user.full_name or 'غير معروف'}\n"
                f"المعرف: @{user.username or 'بدون'}\n"
                f"الآي دي: `{user_id}`"
            )
            await ctx.bot.send_message(
                chat_id=OWNER_ID,
                text=notif_text,
                entities=build_entities(notif_text, [(nu_char, nu_id)]),
            )
        except Exception:
            pass

    # ─── فحص الاشتراك الإجباري ───────────────────────────
    if not await check_and_guard(update, ctx):
        return

    # ─── بيانات الدور ────────────────────────────────────
    file_limit = _get_file_limit(user_id)
    is_admin_user = db.is_admin(user_id)
    is_paid_user  = db.is_subscribed(user_id)

    if is_admin_user:
        role_key   = "CROWN2"
        role_label = "مدير النظام"
        tier_line  = "صلاحيات كاملة — ملفات غير محدودة"
    elif is_paid_user:
        role_key   = "PAID_USER"
        role_label = "مشترك"
        tier_line  = f"حتى {file_limit} ملف نشط"
    else:
        role_key   = "FREE_USER"
        role_label = "مجاني"
        tier_line  = f"حتى {file_limit} ملفات"

    # ─── إيموجيات ────────────────────────────────────────
    wave_char,   wave_id   = db.get_emoji("WAVE")
    role_char,   role_id   = db.get_emoji(role_key)
    folder_char, folder_id = db.get_emoji("FOLDER2")
    brain_char,  brain_id  = db.get_emoji("BRAIN")
    up_char,     up_id     = db.get_emoji("BTN_UPLOAD")

    # ─── بناء النص حسب نوع المستخدم ─────────────────────
    greeting = f"أهلاً بعودتك، {user.first_name}!" if not is_new else f"أهلاً {user.first_name}، يسعدنا انضمامك!"

    if is_admin_user:
        desc = "أنت تتحكم في كل شيء من هنا."
    elif is_paid_user:
        desc = "اشتراكك نشط — استمتع بكامل المزايا."
    else:
        desc = "ارفع سكربتاتك وشغّلها مباشرة على السيرفر."

    text = (
        f"{wave_char} أهلاً {user.first_name}!\n\n"
        f"{role_char} الباقة: {role_label}\n"
        f"{folder_char} الملفات: {tier_line}\n\n"
        f"{brain_char} منصة لاستضافة وتشغيل السكربتات\n"
        f"{up_char} ارفع · شغّل · تحكم · تابع السجلات\n\n"
        "اختر من القائمة:"
    )

    entities = build_entities(text, [
        (wave_char,   wave_id),
        (role_char,   role_id),
        (folder_char, folder_id),
        (brain_char,  brain_id),
        (up_char,     up_id),
    ])

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

    msg      = update.message
    entities = msg.entities or msg.caption_entities or []
    ids_found = [e.custom_emoji_id for e in entities if e.type == "custom_emoji"]

    if ids_found:
        result = "\n".join(f"`{eid}`" for eid in ids_found)
        await msg.reply_text(f"🆔 Custom Emoji IDs:\n\n{result}", parse_mode="Markdown")
    else:
        await msg.reply_text(
            "❌ ما لقيتش custom emoji في الرسالة.\n"
            "ابعت رسالة فيها الإيموجي المتحركة مع /getid كـ reply."
        )


async def cb_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await check_and_guard(update, ctx):
        return
    t0       = time.time()
    test_msg = await ctx.bot.send_message(query.message.chat_id, "⏱ جاري قياس السرعة...")

    response_time = round((time.time() - t0) * 1000, 2)
    uptime    = format_uptime(_bot_start_time)
    user_id   = query.from_user.id
    user_role = "أدمن" if db.is_admin(user_id) else ("مشترك" if db.is_subscribed(user_id) else "مجاني")

    l2_char, l2_id = db.get_emoji("LIGHTNING2")
    ti_char, ti_id = db.get_emoji("TIMER")
    cl_char, cl_id = db.get_emoji("CLOCK")
    mk_char, mk_id = db.get_emoji("MASK2")
    up_char, up_id = db.get_emoji("UP_CHART")
    bk_char, bk_id = db.get_emoji("BTN_BACK")

    text = (
        f"{l2_char} اختبار سرعة البوت\n\n"
        f"{ti_char} وقت الاستجابة: {response_time} مللي ثانية\n"
        f"{cl_char} وقت التشغيل: {uptime}\n"
        f"{mk_char} دورك: {user_role}\n"
        f"{up_char} الملفات النشطة: {len(runner._processes)}"
    )

    await test_msg.edit_text(
        text,
        entities=build_entities(text, [
            (l2_char, l2_id), (ti_char, ti_id), (cl_char, cl_id),
            (mk_char, mk_id), (up_char, up_id),
        ]),
        reply_markup=markup([btn("رجوع", "main_menu", style="danger", icon=bk_id)])
    )


async def cb_my_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    if not await check_and_guard(update, ctx):
        return
    user_id = query.from_user.id
    scripts = db.get_user_scripts(user_id)
    running_scripts = [s for s in scripts if db.get_script_status(s.id) and db.get_script_status(s.id).is_running]
    running = len(running_scripts)
    role    = "أدمن" if db.is_admin(user_id) else ("مشترك" if db.is_subscribed(user_id) else "مجاني")

    up_char, up_id   = db.get_emoji("UP_CHART")
    id_char, id_id   = db.get_emoji("ID_BADGE")
    mk_char, mk_id   = db.get_emoji("MASK2")
    fl_char, fl_id   = db.get_emoji("FOLDER2")
    gd_char, gd_id   = db.get_emoji("GREEN_DOT")
    ut_char, ut_id   = db.get_emoji("UPTIME_ICON")
    rc_char, rc_id   = db.get_emoji("RESTART_CNT")
    ex_char, ex_id   = db.get_emoji("SUB_EXPIRY")
    bk_char, bk_id   = db.get_emoji("BTN_BACK")

    lines = [
        f"{up_char} إحصائياتك\n",
        f"{id_char} المعرف: `{user_id}`",
        f"{mk_char} الباقة: {role}",
        f"{fl_char} الملفات: {len(scripts)}",
        f"{gd_char} يعمل الآن: {running}",
    ]

    # إجمالي وقت التشغيل لكل سكربت شغال
    if running_scripts:
        lines.append(f"\n{ut_char} أوقات التشغيل:")
        for sc in running_scripts:
            uptime = runner.get_uptime(sc.id) or "—"
            lines.append(f"  • `{sc.file_name}` — {uptime}")

    # عدد إعادة التشغيل الكلي
    total_restarts = sum(runner._restart_counts.get(sc.id, 0) for sc in scripts)
    if total_restarts > 0:
        lines.append(f"\n{rc_char} إجمالي إعادة التشغيل: {total_restarts} مرة")

    # تاريخ انتهاء الاشتراك
    if db.is_subscribed(user_id):
        with db.get_session() as s:
            user_obj = s.get(db.User, user_id)
            expiry = user_obj.subscription_expiry if user_obj else None
        if expiry:
            remaining = expiry - datetime.utcnow()
            days = remaining.days
            lines.append(f"\n{ex_char} الاشتراك ينتهي بعد: {days} يوم")

    full_text = "\n".join(lines)
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=full_text,
        entities=build_entities(full_text, [
            (up_char, up_id), (id_char, id_id), (mk_char, mk_id),
            (fl_char, fl_id), (gd_char, gd_id), (ut_char, ut_id),
            (rc_char, rc_id), (ex_char, ex_id),
        ]),
        parse_mode="Markdown",
        reply_markup=markup([btn("رجوع", "main_menu", style="danger", icon=bk_id)])
    )


async def cb_upload_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await check_and_guard(update, ctx):
        return
    if not db.get_flag("upload_enabled"):
        await query.answer("❌ رفع الملفات معطل حالياً.", show_alert=True)
        return

    up_char, up_id = db.get_emoji("UPLOAD3")
    bk_char, bk_id = db.get_emoji("BTN_BACK")
    text, entities = build_message(
        "{UPLOAD} أرسل ملف .py أو .js مباشرة في المحادثة.",
        {"UPLOAD": (up_char, up_id)}
    )
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        entities=entities,
        reply_markup=markup([btn("رجوع", "main_menu", style="danger", icon=bk_id)])
    )


async def cb_contact_owner(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    username = db.get_config("your_username", "@P_X_24").replace("@", "")
    bk_char, bk_id = db.get_emoji("BTN_BACK")
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text="📞 للتواصل مع المالك مباشرة:",
        reply_markup=markup(
            [btn("💬 فتح المحادثة", url=f"https://t.me/{username}", style="primary")],
            [btn("رجوع", "main_menu", style="danger", icon=bk_id)]
        )
    )


async def cb_main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    if not await check_and_guard(update, ctx):
        return
    user    = query.from_user
    user_id = user.id

    file_limit = _get_file_limit(user_id)
    if db.is_admin(user_id):
        role_label = "مدير النظام"
        tier_line  = "صلاحيات كاملة — ملفات غير محدودة"
        role_key   = "CROWN2"
    elif db.is_subscribed(user_id):
        role_label = "مشترك"
        tier_line  = f"حتى {file_limit} ملف نشط"
        role_key   = "PAID_USER"
    else:
        role_label = "مجاني"
        tier_line  = f"حتى {file_limit} ملفات"
        role_key   = "FREE_USER"

    wave_char,   wave_id   = db.get_emoji("WAVE")
    role_char,   role_id   = db.get_emoji(role_key)
    folder_char, folder_id = db.get_emoji("FOLDER2")
    brain_char,  brain_id  = db.get_emoji("BRAIN")
    up_char,     up_id     = db.get_emoji("BTN_UPLOAD")

    text = (
        f"{wave_char} أهلاً {user.first_name}!\n\n"
        f"{role_char} الباقة: {role_label}\n"
        f"{folder_char} الملفات: {tier_line}\n\n"
        f"{brain_char} منصة لاستضافة وتشغيل السكربتات\n"
        f"{up_char} ارفع · شغّل · تحكم · تابع السجلات\n\n"
        "اختر من القائمة:"
    )

    entities = build_entities(text, [
        (wave_char,   wave_id),
        (role_char,   role_id),
        (folder_char, folder_id),
        (brain_char,  brain_id),
        (up_char,     up_id),
    ])

    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        entities=entities,
        reply_markup=main_menu_kb(user_id)
    )


async def cb_scripts_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """حالة كل السكربتات مع تفاصيل كاملة."""
    query   = update.callback_query
    await query.answer()
    if not await check_and_guard(update, ctx):
        return
    user_id = query.from_user.id
    scripts = db.get_user_scripts(user_id)
    bk_id   = db.get_emoji("BTN_BACK")[1]

    if not scripts:
        e, eid = db.get_emoji("FOLDER3")
        t = f"{e} لا توجد سكربتات مرفوعة بعد."
        await ctx.bot.send_message(
            query.message.chat_id, t,
            entities=build_entities(t, [(e, eid)]),
            reply_markup=markup([btn("رجوع", "main_menu", style="danger", icon=bk_id)])
        )
        return

    on_char,  on_id  = db.get_emoji("SCRIPT_ON")
    off_char, off_id = db.get_emoji("SCRIPT_OFF")
    ut_char,  ut_id  = db.get_emoji("UPTIME_ICON")
    rc_char,  rc_id  = db.get_emoji("RESTART_CNT")
    st_char,  st_id  = db.get_emoji("BTN_STATUS")
    ft_char,  ft_id  = db.get_emoji("FILE_TYPE")
    fd_char,  fd_id  = db.get_emoji("FILE_DATE")
    st2_char, st2_id = db.get_emoji("STATUS_STOP")

    total   = len(scripts)
    running = sum(1 for sc in scripts if runner.is_running(sc.id))

    lines = [
        f"{st_char} حالة السكربتات",
        f"الإجمالي: {total}  |  شغال: {running}  |  واقف: {total - running}\n",
    ]

    for sc in scripts:
        is_run   = runner.is_running(sc.id)
        icon     = on_char if is_run else off_char
        uptime   = runner.get_uptime(sc.id)
        restarts = runner._restart_counts.get(sc.id, 0)
        st_db    = db.get_script_status(sc.id)

        lines.append(f"{icon} `{sc.file_name}`")
        lines.append(f"  {ft_char} النوع: {sc.file_type.upper()}")

        if is_run and uptime:
            lines.append(f"  {ut_char} مدة التشغيل: {uptime}")
        elif st_db and st_db.stopped_at:
            lines.append(f"  {fd_char} آخر توقف: {st_db.stopped_at.strftime('%Y-%m-%d %H:%M')}")

        if restarts > 0:
            if restarts >= runner.MAX_RESTART_ATTEMPTS:
                lines.append(f"  {st2_char} إعادة التشغيل: توقفت بعد {restarts} محاولة")
            else:
                lines.append(f"  {rc_char} إعادة التشغيل: {restarts} مرة")

        lines.append("")  # سطر فاصل بين السكربتات

    full_text = "\n".join(lines).rstrip()
    all_pairs = [
        (st_char, st_id), (on_char, on_id), (off_char, off_id),
        (ut_char, ut_id), (rc_char, rc_id), (ft_char, ft_id),
        (fd_char, fd_id), (st2_char, st2_id),
    ]
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=full_text,
        entities=build_entities(full_text, all_pairs),
        parse_mode="Markdown",
        reply_markup=markup([btn("رجوع", "main_menu", style="danger", icon=bk_id)])
    )


async def cb_help_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """صفحة المساعدة وكيفية الاستخدام."""
    query   = update.callback_query
    await query.answer()
    if not await check_and_guard(update, ctx):
        return
    bk_id   = db.get_emoji("BTN_BACK")[1]

    h_char,  h_id  = db.get_emoji("HELP_ICON")
    py_char, py_id = db.get_emoji("PYTHON_ICON")
    js_char, js_id = db.get_emoji("JS_ICON")
    up_char, up_id = db.get_emoji("BTN_UPLOAD")
    nt_char, nt_id = db.get_emoji("NOTIFY_ICON")
    br_char, br_id = db.get_emoji("BRAIN")

    text = (
        f"{h_char} دليل الاستخدام\n\n"
        f"{up_char} كيف أرفع سكربت؟\n"
        "اضغط 'رفع ملف' ثم أرسل الملف مباشرة في المحادثة.\n\n"
        f"{py_char} الأنواع المدعومة:\n"
        "• Python (.py) — مدعوم بالكامل\n"
        "• JavaScript (.js) — يحتاج Node.js على السيرفر\n\n"
        f"{br_char} المكتبات:\n"
        "البوت يثبّت المكتبات الناقصة تلقائياً عند التشغيل.\n"
        "يمكنك أيضاً تثبيتها يدوياً من زر 'تثبيت المكتبات'.\n\n"
        f"{nt_char} الإشعارات:\n"
        "ستصلك رسالة فورية إذا توقف سكربتك.\n"
        "البوت يعيد تشغيله تلقائياً حتى 10 مرات.\n\n"
        f"{up_char} تحديث الملف:\n"
        "يمكنك تحديث الكود بدون حذف السكربت من زر 'تحديث الملف'.\n\n"
        "للمساعدة الإضافية تواصل مع المالك."
    )

    all_pairs = [
        (h_char, h_id), (py_char, py_id), (js_char, js_id),
        (up_char, up_id), (nt_char, nt_id), (br_char, br_id),
    ]
    username = db.get_config("your_username", "@P_X_24").replace("@", "")
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        entities=build_entities(text, all_pairs),
        reply_markup=markup(
            [btn("💬 تواصل مع المالك", url=f"https://t.me/{username}", style="primary")],
            [btn("رجوع", "main_menu", style="danger", icon=bk_id)]
        )
    )


async def cb_check_subscription(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """يتحقق من اشتراك المستخدم في القناة عند الضغط على الزر."""
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if await is_channel_member(ctx.bot, user_id):
        sf_char, sf_id = db.get_emoji("SUB_SUCCESS")
        bk_id = db.get_emoji("BTN_BACK")[1]
        text = f"{sf_char} تم التحقق! يمكنك الآن استخدام البوت."
        await ctx.bot.send_message(
            chat_id=query.message.chat_id,
            text=text,
            entities=build_entities(text, [(sf_char, sf_id)]),
            reply_markup=markup([btn("القائمة الرئيسية", "main_menu", style="success", icon=bk_id)])
        )
    else:
        # فشل التحقق — رسالة واضحة مع إبراز الخطأ
        channel_username = db.get_config("sub_channel_username", "").strip().lstrip("@")
        channel_title    = db.get_config("sub_channel_title", "القناة").strip()

        fl_char, fl_id = db.get_emoji("SUB_FAIL")
        ch_char, ch_id = db.get_emoji("SUB_CHANNEL")
        jn_char, jn_id = db.get_emoji("SUB_JOIN")
        ck_char, ck_id = db.get_emoji("SUB_CHECK")

        text = (
            f"{fl_char} لم يتم التحقق!\n\n"
            f"أنت لم تشترك في {channel_title} بعد.\n\n"
            f"{ch_char} اضغط 'انضم' ثم عد واضغط 'تحقق' مجدداً."
        )
        await ctx.bot.send_message(
            chat_id=query.message.chat_id,
            text=text,
            entities=build_entities(text, [(fl_char, fl_id), (ch_char, ch_id)]),
            reply_markup=markup(
                [btn(f"انضم لـ {channel_title}", url=f"https://t.me/{channel_username}", style="success", icon=jn_id)],
                [btn("تحقق من اشتراكي", "check_subscription", style="primary", icon=ck_id)],
            )
        )


def register(app):
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("getid",  cmd_getid))
    app.add_handler(CallbackQueryHandler(cb_ping,                pattern="^ping$"))
    app.add_handler(CallbackQueryHandler(cb_my_stats,            pattern="^my_stats$"))
    app.add_handler(CallbackQueryHandler(cb_scripts_status,      pattern="^scripts_status$"))
    app.add_handler(CallbackQueryHandler(cb_help_menu,           pattern="^help_menu$"))
    app.add_handler(CallbackQueryHandler(cb_upload_info,         pattern="^upload_info$"))
    app.add_handler(CallbackQueryHandler(cb_contact_owner,       pattern="^contact_owner$"))
    app.add_handler(CallbackQueryHandler(cb_main_menu,           pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(cb_check_subscription,  pattern="^check_subscription$"))
