"""
Admin panel: feature toggles, approvals, user management, broadcast.
"""
import logging
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

import database as db
import runner
from config import OWNER_ID
from utils.colored_buttons import btn, markup
from utils.emoji_ids import BACK, ROBOT, UPLOAD2, CHECK, USERS, CARD, NOTE, GEAR, LOCK, UNLOCK, MEGAPHONE, STOP, ARROW, CROWN

logger = logging.getLogger(__name__)

# ─── Guard ──────────────────────────────────────────────────

def admin_only(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = (update.effective_user or update.callback_query.from_user).id
        if not db.is_admin(user_id):
            if update.callback_query:
                await update.callback_query.answer("❌ للأدمن فقط.", show_alert=True)
            else:
                await update.message.reply_text("❌ للأدمن فقط.")
            return
        return await func(update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper


# ─── Admin Panel ────────────────────────────────────────────

def _admin_panel_kb() -> dict:
    bot_on    = db.get_flag("bot_enabled")
    upload_on = db.get_flag("upload_enabled")
    run_on    = db.get_flag("run_enabled")
    appr_on   = db.get_flag("approval_required")
    locked    = db.get_flag("bot_locked")
    sub_on    = db.get_flag("forced_subscription")
    bk_id     = db.get_emoji("BTN_BACK")[1]

    return markup(
        [btn("🤖 البوت: مفعل" if bot_on else "🤖 البوت: معطل", "toggle_bot_enabled", style="success" if bot_on else "danger")],
        [btn("📤 الرفع: مفعل" if upload_on else "📤 الرفع: معطل", "toggle_upload_enabled", style="success" if upload_on else "danger")],
        [btn("▶️ التشغيل: مفعل" if run_on else "⏹ التشغيل: معطل", "toggle_run_enabled", style="success" if run_on else "danger")],
        [btn("✅ الموافقة: مفعلة" if appr_on else "❌ الموافقة: معطلة", "toggle_approval_required", style="success" if appr_on else "danger")],
        [btn("🔔 الاشتراك الإجباري: مفعل" if sub_on else "🔔 الاشتراك الإجباري: معطل", "admin_forced_sub", style="success" if sub_on else "danger")],
        [btn("👥 المستخدمون", "admin_users", style="primary"), btn("💳 الاشتراكات", "admin_subscriptions", style="primary")],
        [btn("📋 الموافقات", "admin_approvals", style="primary"), btn("⚙️ الإعدادات", "admin_settings", style="primary")],
        [btn("📊 إحصائيات البوت", "admin_stats", style="primary")],
        [btn("🔓 فتح البوت" if locked else "🔒 قفل البوت", "admin_lock_bot", style="success" if locked else "danger")],
        [btn("📢 بث رسالة", "admin_broadcast", style="primary")],
        [btn("▶️ تشغيل الكل", "admin_run_all", style="success"), btn("⏹ إيقاف الكل", "admin_stop_all", style="danger")],
        [btn("رجوع", "main_menu", style="danger", icon=bk_id)],
    )


@admin_only
async def cb_admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text="👑 لوحة الأدمن:",
        reply_markup=_admin_panel_kb()
    )


# ─── Feature Toggles ────────────────────────────────────────

@admin_only
async def cb_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Map full callback_data to flag keys
    key_map = {
        "toggle_bot_enabled":       "bot_enabled",
        "toggle_upload_enabled":    "upload_enabled",
        "toggle_run_enabled":       "run_enabled",
        "toggle_approval_required": "approval_required",
    }

    flag_key = key_map.get(query.data)
    if not flag_key:
        return

    current = db.get_flag(flag_key)
    db.set_flag(flag_key, not current)

    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text="👑 لوحة الأدمن:",
        reply_markup=_admin_panel_kb()
    )


# ─── Approvals ──────────────────────────────────────────────

@admin_only
async def cb_admin_approvals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    pending = db.get_pending_approvals()

    if not pending:
        await ctx.bot.send_message(
            chat_id=query.message.chat_id,
            text="✅ لا توجد طلبات معلقة.",
            reply_markup=markup([btn("رجوع", "admin_panel", style="danger", icon=db.get_emoji("BTN_BACK")[1])])
        )
        return

    rows = []
    for ap, sc in pending:
        rows.append([btn(f"📄 {sc.file_name} (#{ap.id})", f"viewcode_{sc.id}", style="primary")])
        rows.append([
            btn("✅ موافقة",  f"approve_{ap.id}", style="success"),
            btn("❌ رفض",     f"reject_{ap.id}",  style="danger"),
        ])
    rows.append([btn("رجوع", "admin_panel", style="danger", icon=db.get_emoji("BTN_BACK")[1])])

    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"📋 الطلبات المعلقة ({len(pending)}):",
        reply_markup=markup(*rows)
    )


@admin_only
async def cb_approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query       = update.callback_query
    await query.answer("✅ تمت الموافقة.")
    approval_id = int(query.data.split("_")[1])
    db.update_approval(approval_id, "approved", query.from_user.id)

    # Notify owner of script
    from database import get_session, Approval, Script
    with get_session() as s:
        ap = s.get(Approval, approval_id)
        if ap:
            sc = s.get(Script, ap.script_id)
            if sc:
                try:
                    await ctx.bot.send_message(
                        sc.owner_id,
                        f"✅ تمت الموافقة على ملفك `{sc.file_name}`!\n"
                        "يمكنك الآن تشغيله من قائمة ملفاتك.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

    await cb_admin_approvals(update, ctx)


@admin_only
async def cb_reject(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query       = update.callback_query
    await query.answer("❌ تم الرفض.")
    approval_id = int(query.data.split("_")[1])
    db.update_approval(approval_id, "rejected", query.from_user.id)

    from database import get_session, Approval, Script
    with get_session() as s:
        ap = s.get(Approval, approval_id)
        if ap:
            sc = s.get(Script, ap.script_id)
            if sc:
                try:
                    await ctx.bot.send_message(
                        sc.owner_id,
                        f"❌ تم رفض ملفك `{sc.file_name}`.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

    await cb_admin_approvals(update, ctx)


# ─── Run All / Stop All ─────────────────────────────────────

@admin_only
async def cb_run_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🟢 جاري تشغيل الكل...")
    from database import get_session, Script, ScriptStatus
    with get_session() as s:
        scripts = s.query(Script).all()
        s.expunge_all()
    count = 0
    for sc in scripts:
        if not runner.is_running(sc.id):
            ok, _ = runner.start_script(sc)
            if ok:
                count += 1
    await ctx.bot.send_message(query.message.chat_id, f"🟢 تم تشغيل {count} سكربت.")


@admin_only
async def cb_stop_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🔴 جاري إيقاف الكل...")
    runner.stop_all()
    await ctx.bot.send_message(query.message.chat_id, "🔴 تم إيقاف جميع السكربتات.")


# ─── Settings ───────────────────────────────────────────────

@admin_only
async def cb_admin_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    free  = db.get_config("free_file_limit",  "3")
    paid  = db.get_config("paid_file_limit",  "15")
    maxp  = db.get_config("max_processes",    "50")
    text  = (
        f"⚙️ الإعدادات الحالية:\n\n"
        f"📁 حد الملفات المجاني: {free} ملف\n"
        f"💎 حد الملفات المشترك: {paid} ملفات\n"
        f"⚙️ أقصى عمليات: {maxp}\n"
    )
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=markup(
            [btn("📁 تغيير حد المجاني",   "set_free_limit",  style="primary"),
             btn("💎 تغيير حد المشترك",   "set_paid_limit",  style="primary")],
            [btn("🎨 إدارة الإيموجيات",   "admin_emojis",    style="primary")],
            [btn("رجوع", "admin_panel", style="danger", icon=db.get_emoji("BTN_BACK")[1])]
        )
    )


@admin_only
async def cb_set_paid_limit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["awaiting_paid_limit"] = True
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text="💎 أرسل عدد الملفات الجديد للمشتركين:\n(مثال: 20, 30, 50, 100)",
        reply_markup=markup([btn("❌ إلغاء", "admin_settings", style="danger")])
    )


@admin_only
async def cb_set_free_limit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["awaiting_free_limit"] = True
    current = db.get_config("free_file_limit", "3")
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"📁 الحد الحالي للمجاني: {current} ملف\n\nأرسل العدد الجديد:\n(مثال: 1, 3, 5)",
        reply_markup=markup([btn("❌ إلغاء", "admin_settings", style="danger")])
    )


async def handle_free_limit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("awaiting_free_limit"):
        return
    ctx.user_data["awaiting_free_limit"] = False
    try:
        new_limit = int(update.message.text.strip())
        if new_limit < 1:
            raise ValueError
        db.set_config("free_file_limit", str(new_limit))
        await update.message.reply_text(f"✅ تم تغيير حد الملفات المجاني إلى {new_limit}")
    except ValueError:
        await update.message.reply_text("❌ يجب إرسال رقم صحيح أكبر من صفر")


# ─── Emoji Management ───────────────────────────────────────

# تصنيف الإيموجيات بفئات مفهومة للأدمن
EMOJI_CATEGORIES = {
    "رسالة الترحيب /start":      ["WAVE", "BRAIN", "BTN_UPLOAD", "CROWN2", "PAID_USER", "FREE_USER", "FOLDER2"],
    "أزرار القائمة الرئيسية":    ["BTN_UPLOAD", "BTN_FILES", "BTN_SPEED", "BTN_STATS", "BTN_STATUS", "BTN_HELP", "BTN_CONTACT", "BTN_ADMIN", "BTN_BACK"],
    "صفحة السرعة والإحصائيات":  ["LIGHTNING2", "TIMER", "CLOCK", "MASK2", "UP_CHART", "ID_BADGE", "GREEN_DOT", "UPTIME_ICON", "RESTART_CNT", "SUB_EXPIRY"],
    "صفحة حالة السكربتات":       ["BTN_STATUS", "SCRIPT_ON", "SCRIPT_OFF", "UPTIME_ICON", "RESTART_CNT", "FILE_TYPE", "FILE_DATE", "STATUS_STOP"],
    "صفحة المساعدة":             ["HELP_ICON", "PYTHON_ICON", "JS_ICON", "NOTIFY_ICON", "BRAIN", "BTN_UPLOAD"],
    "أزرار السكربت":             ["BTN_RUN", "BTN_STOP", "BTN_RESTART", "BTN_INSTALL", "BTN_LOG", "BTN_UPDATE", "BTN_DIAGNOSE", "BTN_DELETE", "BTN_AUTO_ON"],
    "حالات السكربت":             ["STATUS_ON", "STATUS_OFF", "STATUS_WAIT", "STATUS_STOP", "FILE_CPU", "FILE_RESTART"],
    "صفحة الملفات":              ["FOLDER3", "UPLOAD3", "NOTE", "FILE_ICON", "FILE_TYPE", "FILE_DATE", "FILE_APPROVE", "FILE_USER", "FILE_DOC"],
    "أزرار الموافقة":            ["BTN_APPROVE", "BTN_REJECT", "BTN_VIEWCODE"],
    "رسائل النظام":              ["SUCCESS", "ERROR", "WARNING", "SHIELD", "BANNED", "LOCKED", "NEW_USER", "STATUS_WAIT"],
    "أزرار التواصل":             ["BTN_CONTACT", "BTN_CONTACT_OPEN"],
    "الاشتراك الإجباري":         ["SUB_REQUIRED", "SUB_CHANNEL", "SUB_CHECK", "SUB_JOIN", "SUB_SUCCESS", "SUB_FAIL"],
}


@admin_only
async def cb_admin_emojis(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة الإيموجيات مقسمة بفئات."""
    query = update.callback_query
    await query.answer()

    # عرض الفئات كأزرار
    rows = []
    for category in EMOJI_CATEGORIES:
        rows.append([btn(f"📂 {category}", f"emoji_cat_{category}", style="primary")])
    rows.append([btn("رجوع", "admin_settings", style="danger", icon=db.get_emoji("BTN_BACK")[1])])

    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=(
            "🎨 إدارة الإيموجيات المتحركة\n\n"
            "اختر الفئة التي تريد تعديلها:\n\n"
            "💡 كيف تغير إيموجي:\n"
            "١. اضغط على الفئة\n"
            "٢. اختر الإيموجي\n"
            "٣. ابعت الـ Custom ID الجديد\n\n"
            "للحصول على الـ ID: ابعت إيموجي متحرك ثم اكتب /getid كـ reply عليه."
        ),
        reply_markup=markup(*rows)
    )


@admin_only
async def cb_emoji_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """عرض إيموجيات فئة معينة."""
    query    = update.callback_query
    await query.answer()
    category = query.data.replace("emoji_cat_", "")
    keys     = EMOJI_CATEGORIES.get(category, [])

    rows = []
    seen = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        char, eid = db.get_emoji(key)
        desc = db.DEFAULT_EMOJIS.get(key, ("", "", ""))[2]
        rows.append([btn(
            f"{char}  {desc}",
            f"edit_emoji_{key}",
            style="primary"
        )])
    rows.append([btn("رجوع للفئات", "admin_emojis", style="danger", icon=db.get_emoji("BTN_BACK")[1])])

    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"🎨 {category}\n\nاضغط على الإيموجي لتغييره:",
        reply_markup=markup(*rows)
    )


@admin_only
async def cb_edit_emoji(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """يطلب من الأدمن إرسال الـ ID الجديد للإيموجي."""
    query     = update.callback_query
    await query.answer()
    emoji_key = query.data.replace("edit_emoji_", "")
    char, eid = db.get_emoji(emoji_key)
    desc      = db.DEFAULT_EMOJIS.get(emoji_key, ("", "", ""))[2]

    ctx.user_data["awaiting_emoji_key"] = emoji_key
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=(
            f"✏️ تعديل: {char} — {desc}\n\n"
            f"الـ ID الحالي:\n`{eid}`\n\n"
            "أرسل الـ Custom Emoji ID الجديد:\n"
            "_(رقم من 15-19 خانة)_\n\n"
            "للحصول على الـ ID:\n"
            "ابعت الإيموجي المتحرك ثم اكتب /getid كـ reply عليه."
        ),
        parse_mode="Markdown",
        reply_markup=markup([btn("❌ إلغاء", "admin_emojis", style="danger")])
    )


async def handle_emoji_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """يستقبل الـ ID الجديد ويحفظه."""
    if not ctx.user_data.get("awaiting_emoji_key"):
        return
    emoji_key = ctx.user_data.pop("awaiting_emoji_key")
    new_id = update.message.text.strip()

    if not new_id.isdigit() or len(new_id) < 10:
        er, er_id = db.get_emoji("ERROR")
        t = f"{er} الـ ID غير صحيح. يجب أن يكون رقماً من 15-19 خانة.\nاستخدم /getid للحصول على الـ ID الصحيح."
        await update.message.reply_text(t, entities=build_entities(t, [(er, er_id)]))
        ctx.user_data["awaiting_emoji_key"] = emoji_key
        return

    db.set_emoji(emoji_key, new_id)
    char, saved_id = db.get_emoji(emoji_key)
    desc = db.DEFAULT_EMOJIS.get(emoji_key, ("", "", ""))[2]

    ok, ok_id = db.get_emoji("SUCCESS")
    t = f"{ok} تم تحديث: {desc}\nالإيموجي الجديد: {char}\nالـ ID: `{new_id}`"
    await update.message.reply_text(
        t,
        entities=build_entities(t, [(ok, ok_id), (char, saved_id)]),
        parse_mode="Markdown",
        reply_markup=markup([btn("رجوع لإدارة الإيموجيات", "admin_emojis", style="primary")])
    )


async def handle_paid_limit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("awaiting_paid_limit"):
        return
    if not db.is_admin(update.effective_user.id):
        return
    
    ctx.user_data["awaiting_paid_limit"] = False
    try:
        new_limit = int(update.message.text)
        db.set_config("paid_file_limit", str(new_limit))
        await update.message.reply_text(
            f"✅ تم تغيير حد الملفات المشترك إلى {new_limit}",
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text(
            "❌ يجب إرسال رقم صحيح",
            parse_mode="Markdown"
        )


async def cmd_setconfig(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        return
    args = ctx.args
    if len(args) != 2:
        await update.message.reply_text("الاستخدام: `/setconfig <key> <value>`", parse_mode="Markdown")
        return
    db.set_config(args[0], args[1])
    await update.message.reply_text(f"✅ تم تحديث `{args[0]}` = `{args[1]}`", parse_mode="Markdown")


# ─── User Management ────────────────────────────────────────

@admin_only
async def cb_admin_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text="👥 إدارة المستخدمين\n\nالأوامر المتاحة:\n"
        "`/ban <user_id> [سبب]`\n"
        "`/unban <user_id>`\n"
        "`/addadmin <user_id>`\n"
        "`/removeadmin <user_id>`\n"
        "`/subscribe <user_id> <أيام>`",
        parse_mode="Markdown",
        reply_markup=markup([btn("رجوع", "admin_panel", style="danger", icon=db.get_emoji("BTN_BACK")[1])])
    )


async def cmd_ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("الاستخدام: `/ban <user_id> [سبب]`", parse_mode="Markdown")
        return
    target = int(ctx.args[0])
    reason = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else "لا يوجد سبب"
    with db.get_session() as s:
        user = s.get(db.User, target)
        if not user:
            user = db.User(id=target)
            s.add(user)
        user.is_banned  = True
        user.ban_reason = reason
    await update.message.reply_text(f"🚫 تم حظر المستخدم `{target}`.", parse_mode="Markdown")


async def cmd_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        return
    if not ctx.args:
        return
    target = int(ctx.args[0])
    with db.get_session() as s:
        user = s.get(db.User, target)
        if user:
            user.is_banned = False
    await update.message.reply_text(f"✅ تم رفع الحظر عن `{target}`.", parse_mode="Markdown")


async def cmd_addadmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ للمالك فقط.")
        return
    if not ctx.args:
        return
    target = int(ctx.args[0])
    db.upsert_user(target)
    with db.get_session() as s:
        user = s.get(db.User, target)
        if user:
            user.is_admin = True
    await update.message.reply_text(f"✅ تم تعيين `{target}` أدمناً.", parse_mode="Markdown")


async def cmd_removeadmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ للمالك فقط.")
        return
    if not ctx.args:
        return
    target = int(ctx.args[0])
    with db.get_session() as s:
        user = s.get(db.User, target)
        if user:
            user.is_admin = False
    await update.message.reply_text(f"✅ تم إزالة صلاحيات `{target}`.", parse_mode="Markdown")


async def cmd_subscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        return
    if len(ctx.args) < 2:
        await update.message.reply_text("الاستخدام: `/subscribe <user_id> <أيام>`", parse_mode="Markdown")
        return
    target = int(ctx.args[0])
    days   = int(ctx.args[1])
    db.upsert_user(target)
    with db.get_session() as s:
        user = s.get(db.User, target)
        if user:
            user.subscription_expiry = datetime.utcnow() + timedelta(days=days)
            user.has_uploaded_free = False  # Reset upload limit for paid users
    await update.message.reply_text(
        f"💎 تم تفعيل اشتراك `{target}` لمدة {days} يوم.\n"
        f"📁 حد الملفات: {db.get_config('paid_file_limit', '15')}",
        parse_mode="Markdown"
    )


async def cmd_unsubscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("الاستخدام: `/unsubscribe <user_id>`", parse_mode="Markdown")
        return
    target = int(ctx.args[0])
    with db.get_session() as s:
        user = s.get(db.User, target)
        if user:
            user.subscription_expiry = None
    await update.message.reply_text(
        f"🗑 تم إلغاء اشتراك `{target}`.",
        parse_mode="Markdown"
    )


async def cmd_checksubscription(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("الاستخدام: `/checksubscription <user_id>`", parse_mode="Markdown")
        return
    target = int(ctx.args[0])
    with db.get_session() as s:
        user = s.get(db.User, target)
        if user and user.subscription_expiry and user.subscription_expiry > datetime.utcnow():
            remaining = user.subscription_expiry - datetime.utcnow()
            days = remaining.days
            hours = remaining.seconds // 3600
            await update.message.reply_text(
                f"✅ المستخدم `{target}` مشترك.\n⏳ المتبقي: {days} يوم و {hours} ساعة.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"❌ المستخدم `{target}` غير مشترك.",
                parse_mode="Markdown"
            )


@admin_only
async def cb_admin_subscriptions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text="💳 إدارة الاشتراكات\n\nالأوامر المتاحة:\n"
             "`/subscribe <user_id> <أيام>` - تفعيل اشتراك\n"
             "`/unsubscribe <user_id>` - إلغاء اشتراك\n"
             "`/checksubscription <user_id>` - فحص اشتراك",
        parse_mode="Markdown",
        reply_markup=markup([btn("رجوع", "admin_panel", style="danger", icon=db.get_emoji("BTN_BACK")[1])])
    )


@admin_only
async def cb_admin_lock_bot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    locked = db.get_flag("bot_locked")
    db.set_flag("bot_locked", not locked)
    status = "مقفل" if not locked else "مفتوح"
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"🔒 تم {status} البوت للمستخدمين العاديين.",
        reply_markup=markup([btn("لوحة الأدمن", "admin_panel", style="danger", icon=db.get_emoji("BTN_BACK")[1])])
    )


# ─── Broadcast ──────────────────────────────────────────────

@admin_only
async def cb_admin_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["awaiting_broadcast"] = True
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text="📢 أرسل الرسالة التي تريد بثها لجميع المستخدمين:",
        reply_markup=markup([btn("❌ إلغاء", "admin_panel", style="danger")])
    )


async def handle_broadcast_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("awaiting_broadcast"):
        return
    if not db.is_admin(update.effective_user.id):
        return

    ctx.user_data["awaiting_broadcast"] = False
    text = update.message.text or update.message.caption or ""

    from database import get_session, User
    with get_session() as s:
        users = s.query(User).filter_by(is_banned=False).all()
        user_ids = [u.id for u in users]

    sent = failed = 0
    for uid in user_ids:
        try:
            await ctx.bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"📢 تم الإرسال\n✅ نجح: {sent}\n❌ فشل: {failed}"
    )


# ─── Bot Stats ──────────────────────────────────────────────

@admin_only
async def cb_admin_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    from database import get_session, User, Script, ScriptStatus
    from datetime import datetime

    with get_session() as s:
        total_users       = s.query(User).count()
        banned_users      = s.query(User).filter_by(is_banned=True).count()
        subscribed_users  = s.query(User).filter(
            User.subscription_expiry != None,
            User.subscription_expiry > datetime.utcnow()
        ).count()
        admin_users       = s.query(User).filter_by(is_admin=True).count()
        total_scripts     = s.query(Script).count()
        running_scripts   = s.query(ScriptStatus).filter_by(is_running=True).count()

    text = (
        "📊 إحصائيات البوت\n\n"
        f"👥 إجمالي المستخدمين: {total_users}\n"
        f"💎 المشتركين: {subscribed_users}\n"
        f"👑 الأدمنز: {admin_users}\n"
        f"🚫 المحظورين: {banned_users}\n\n"
        f"📁 إجمالي السكربتات: {total_scripts}\n"
        f"🟢 يعمل الآن: {running_scripts}\n"
        f"⚙️ في الذاكرة: {len(runner._processes)}"
    )

    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        reply_markup=markup([btn("رجوع", "admin_panel", style="danger", icon=db.get_emoji("BTN_BACK")[1])])
    )


# ─── Forced Subscription Management ────────────────────────

def _forced_sub_kb() -> dict:
    sub_on   = db.get_flag("forced_subscription")
    ch_user  = db.get_config("sub_channel_username", "").strip()
    ch_title = db.get_config("sub_channel_title", "غير محدد").strip()
    bk_id    = db.get_emoji("BTN_BACK")[1]

    return markup(
        [btn(
            "🔔 الاشتراك الإجباري: مفعل" if sub_on else "🔔 الاشتراك الإجباري: معطل",
            "toggle_forced_subscription",
            style="success" if sub_on else "danger"
        )],
        [btn("🔗 تغيير يوزرنيم القناة",  "set_sub_channel_username", style="primary")],
        [btn("✏️ تغيير اسم القناة",        "set_sub_channel_title",    style="primary")],
        [btn("رجوع", "admin_panel", style="danger", icon=bk_id)],
    )


@admin_only
async def cb_admin_forced_sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    sub_on   = db.get_flag("forced_subscription")
    ch_user  = db.get_config("sub_channel_username", "").strip() or "غير محدد"
    ch_title = db.get_config("sub_channel_title", "غير محدد").strip()

    text = (
        "🔔 إعدادات الاشتراك الإجباري\n\n"
        f"الحالة: {'✅ مفعل' if sub_on else '❌ معطل'}\n"
        f"اسم القناة: {ch_title}\n"
        f"يوزرنيم: @{ch_user}\n\n"
        "تأكد من إضافة البوت كـ Admin في القناة\n"
        "حتى يتمكن من التحقق من الاشتراك."
    )
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        reply_markup=_forced_sub_kb()
    )


@admin_only
async def cb_toggle_forced_sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = db.get_flag("forced_subscription")
    db.set_flag("forced_subscription", not current)
    await cb_admin_forced_sub(update, ctx)


@admin_only
async def cb_set_sub_channel_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["awaiting_sub_channel_id"] = True
    current = db.get_config("sub_channel_id", "غير محدد")
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=(
            f"📢 Channel ID الحالي: `{current}`\n\n"
            "أرسل الـ Channel ID الجديد:\n"
            "مثال: `-1001234567890`\n\n"
            "للحصول على الـ ID: أضف @userinfobot للقناة أو ابحث عنه."
        ),
        parse_mode="Markdown",
        reply_markup=markup([btn("❌ إلغاء", "admin_forced_sub", style="danger")])
    )


@admin_only
async def cb_set_sub_channel_username(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["awaiting_sub_channel_username"] = True
    current = db.get_config("sub_channel_username", "غير محدد")
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=(
            f"🔗 اليوزرنيم الحالي: @{current}\n\n"
            "أرسل يوزرنيم القناة الجديد (بدون @):\n"
            "مثال: mychannel"
        ),
        reply_markup=markup([btn("❌ إلغاء", "admin_forced_sub", style="danger")])
    )


@admin_only
async def cb_set_sub_channel_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["awaiting_sub_channel_title"] = True
    current = db.get_config("sub_channel_title", "قناتنا")
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=(
            f"✏️ اسم القناة الحالي: {current}\n\n"
            "أرسل الاسم الجديد الذي سيظهر للمستخدمين:"
        ),
        reply_markup=markup([btn("❌ إلغاء", "admin_forced_sub", style="danger")])
    )


async def handle_sub_channel_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("awaiting_sub_channel_id"):
        return
    ctx.user_data["awaiting_sub_channel_id"] = False
    value = update.message.text.strip()
    if not (value.lstrip("-").isdigit()):
        await update.message.reply_text(
            "❌ Channel ID غير صحيح. يجب أن يكون رقماً مثل: `-1001234567890`",
            parse_mode="Markdown"
        )
        ctx.user_data["awaiting_sub_channel_id"] = True
        return
    db.set_config("sub_channel_id", value)
    await update.message.reply_text(
        f"✅ تم تحديث Channel ID إلى: `{value}`",
        parse_mode="Markdown",
        reply_markup=markup([btn("رجوع لإعدادات الاشتراك", "admin_forced_sub", style="primary")])
    )


async def handle_sub_channel_username(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("awaiting_sub_channel_username"):
        return
    ctx.user_data["awaiting_sub_channel_username"] = False
    value = update.message.text.strip().lstrip("@")
    db.set_config("sub_channel_username", value)
    await update.message.reply_text(
        f"✅ تم تحديث يوزرنيم القناة إلى: @{value}",
        reply_markup=markup([btn("رجوع لإعدادات الاشتراك", "admin_forced_sub", style="primary")])
    )


async def handle_sub_channel_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("awaiting_sub_channel_title"):
        return
    ctx.user_data["awaiting_sub_channel_title"] = False
    value = update.message.text.strip()
    db.set_config("sub_channel_title", value)
    await update.message.reply_text(
        f"✅ تم تحديث اسم القناة إلى: {value}",
        reply_markup=markup([btn("رجوع لإعدادات الاشتراك", "admin_forced_sub", style="primary")])
    )


async def handle_admin_text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handler موحد لكل مدخلات النص من الأدمن — يمنع التعارض بين الـ handlers."""
    if not db.is_admin(update.effective_user.id):
        return

    if ctx.user_data.get("awaiting_broadcast"):
        await handle_broadcast_message(update, ctx)
        return

    if ctx.user_data.get("awaiting_paid_limit"):
        await handle_paid_limit(update, ctx)
        return

    if ctx.user_data.get("awaiting_free_limit"):
        await handle_free_limit(update, ctx)
        return

    if ctx.user_data.get("awaiting_emoji_key"):
        await handle_emoji_input(update, ctx)
        return

    if ctx.user_data.get("awaiting_sub_channel_id"):
        await handle_sub_channel_id(update, ctx)
        return

    if ctx.user_data.get("awaiting_sub_channel_username"):
        await handle_sub_channel_username(update, ctx)
        return

    if ctx.user_data.get("awaiting_sub_channel_title"):
        await handle_sub_channel_title(update, ctx)
        return


# ─── Register ───────────────────────────────────────────────

def register(app):
    app.add_handler(CallbackQueryHandler(cb_admin_panel,         pattern="^admin_panel$"))
    # ─── Forced Subscription (قبل toggle_\w+ عشان ما يتعارضش) ──
    app.add_handler(CallbackQueryHandler(cb_admin_forced_sub,         pattern="^admin_forced_sub$"))
    app.add_handler(CallbackQueryHandler(cb_toggle_forced_sub,        pattern="^toggle_forced_subscription$"))
    app.add_handler(CallbackQueryHandler(cb_set_sub_channel_username, pattern="^set_sub_channel_username$"))
    app.add_handler(CallbackQueryHandler(cb_set_sub_channel_title,    pattern="^set_sub_channel_title$"))
    # ─── Feature Toggles ────────────────────────────────────
    app.add_handler(CallbackQueryHandler(cb_toggle,              pattern=r"^toggle_\w+$"))
    app.add_handler(CallbackQueryHandler(cb_admin_approvals,     pattern="^admin_approvals$"))
    app.add_handler(CallbackQueryHandler(cb_approve,             pattern=r"^approve_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_reject,              pattern=r"^reject_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_run_all,             pattern="^admin_run_all$"))
    app.add_handler(CallbackQueryHandler(cb_stop_all,            pattern="^admin_stop_all$"))
    app.add_handler(CallbackQueryHandler(cb_admin_settings,      pattern="^admin_settings$"))
    app.add_handler(CallbackQueryHandler(cb_admin_users,         pattern="^admin_users$"))
    app.add_handler(CallbackQueryHandler(cb_admin_broadcast,     pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(cb_admin_subscriptions, pattern="^admin_subscriptions$"))
    app.add_handler(CallbackQueryHandler(cb_admin_lock_bot,      pattern="^admin_lock_bot$"))
    app.add_handler(CallbackQueryHandler(cb_set_paid_limit,      pattern="^set_paid_limit$"))
    app.add_handler(CallbackQueryHandler(cb_set_free_limit,      pattern="^set_free_limit$"))
    app.add_handler(CallbackQueryHandler(cb_admin_stats,         pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(cb_admin_emojis,        pattern="^admin_emojis$"))
    app.add_handler(CallbackQueryHandler(cb_emoji_category,      pattern=r"^emoji_cat_.+$"))
    app.add_handler(CallbackQueryHandler(cb_edit_emoji,          pattern=r"^edit_emoji_\w+$"))
    # ─── Commands ───────────────────────────────────────────
    app.add_handler(CommandHandler("ban",               cmd_ban))
    app.add_handler(CommandHandler("unban",             cmd_unban))
    app.add_handler(CommandHandler("addadmin",          cmd_addadmin))
    app.add_handler(CommandHandler("removeadmin",       cmd_removeadmin))
    app.add_handler(CommandHandler("subscribe",         cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe",       cmd_unsubscribe))
    app.add_handler(CommandHandler("checksubscription", cmd_checksubscription))
    app.add_handler(CommandHandler("setconfig",         cmd_setconfig))
    # handler واحد موحد بدل اتنين متعارضين
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text_input))
