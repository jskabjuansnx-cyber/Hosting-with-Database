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

    return markup(
        [btn("🤖 البوت: مفعل" if bot_on else "🤖 البوت: معطل", "toggle_bot_enabled", style="success" if bot_on else "danger")],
        [btn("📤 الرفع: مفعل" if upload_on else "📤 الرفع: معطل", "toggle_upload_enabled", style="success" if upload_on else "danger")],
        [btn("التشغيل: مفعل" if run_on else "التشغيل: معطل", "toggle_run_enabled", style="success" if run_on else "danger")],
        [btn("الموافقة: مفعلة" if appr_on else "الموافقة: معطلة", "toggle_approval_required", style="success" if appr_on else "danger")],
        [btn("👥 المستخدمون", "admin_users", style="primary"), btn("💳 الاشتراكات", "admin_subscriptions", style="primary")],
        [btn("📋 الموافقات", "admin_approvals", style="primary"), btn("الاعدادات", "admin_settings", style="primary")],
        [btn("فتح البوت" if locked else "🔒 قفل البوت", "admin_lock_bot", style="success" if locked else "danger")],
        [btn("📢 بث رسالة", "admin_broadcast", style="primary")],
        [btn("تشغيل الكل", "admin_run_all", style="success"), btn("ايقاف الكل", "admin_stop_all", style="danger")],
        [btn("رجوع", "main_menu", style="danger", icon=BACK)],
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
    key   = query.data.replace("toggle_", "")
    
    # Map callback keys to flag keys
    key_map = {
        "toggle_bot_enabled": "bot_enabled",
        "toggle_upload_enabled": "upload_enabled",
        "toggle_run_enabled": "run_enabled",
        "toggle_approval_required": "approval_required",
    }
    
    flag_key = key_map.get(key, key)
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
            reply_markup=markup([btn("رجوع", "admin_panel", style="danger", icon=BACK)])
        )
        return

    rows = []
    for ap, sc in pending:
        rows.append([btn(f"📄 {sc.file_name} (#{ap.id})", f"viewcode_{sc.id}", style="primary")])
        rows.append([
            btn("✅ موافقة",  f"approve_{ap.id}", style="success"),
            btn("❌ رفض",     f"reject_{ap.id}",  style="danger"),
        ])
    rows.append([btn("رجوع", "admin_panel", style="danger", icon=BACK)])

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
    free  = db.get_config("free_file_limit",  "1")
    paid  = db.get_config("paid_file_limit",  "15")
    maxp  = db.get_config("max_processes",    "50")
    text  = (
        f"⚙️ الإعدادات الحالية:\n\n"
        f"📁 حد الملفات المجاني: {free} ملف\n"
        f"💎 حد الملفات المشترك: {paid} ملفات\n"
        f"⚙️ أقصى عمليات: {maxp}\n\n"
        "لتغيير الحد المشترك:\n"
        "`/setconfig paid_file_limit 20`\n\n"
        "لتغيير حد المجاني:\n"
        "`/setconfig free_file_limit 1`"
    )
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=markup([
            [btn("📁 تغيير حد المشترك", "set_paid_limit", style="primary")],
            [btn("رجوع", "admin_panel", style="danger", icon=BACK)]
        ])
    )


@admin_only
async def cb_set_paid_limit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["awaiting_paid_limit"] = True
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text="📁 أرسل عدد الملفات الجديد للمشتركين:\n"
             "(مثال: 20, 30, 50, 100)",
        reply_markup=markup([btn("❌ إلغاء", "admin_settings", style="danger")])
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
        reply_markup=markup([btn("رجوع", "admin_panel", style="danger", icon=BACK)])
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
        reply_markup=markup([btn("رجوع", "admin_panel", style="danger", icon=BACK)])
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
        reply_markup=markup([btn("لوحة الأدمن", "admin_panel", style="danger", icon=BACK)])
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


# ─── Register ───────────────────────────────────────────────

def register(app):
    app.add_handler(CallbackQueryHandler(cb_admin_panel,      pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(cb_toggle,           pattern=r"^toggle_\w+$"))
    app.add_handler(CallbackQueryHandler(cb_admin_approvals,  pattern="^admin_approvals$"))
    app.add_handler(CallbackQueryHandler(cb_approve,          pattern=r"^approve_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_reject,           pattern=r"^reject_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_run_all,          pattern="^admin_run_all$"))
    app.add_handler(CallbackQueryHandler(cb_stop_all,         pattern="^admin_stop_all$"))
    app.add_handler(CallbackQueryHandler(cb_admin_settings,   pattern="^admin_settings$"))
    app.add_handler(CallbackQueryHandler(cb_admin_users,      pattern="^admin_users$"))
    app.add_handler(CallbackQueryHandler(cb_admin_broadcast,  pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(cb_admin_subscriptions, pattern="^admin_subscriptions$"))
    app.add_handler(CallbackQueryHandler(cb_admin_lock_bot,   pattern="^admin_lock_bot$"))
    app.add_handler(CallbackQueryHandler(cb_set_paid_limit,   pattern="^set_paid_limit$"))
    app.add_handler(CommandHandler("ban",         cmd_ban))
    app.add_handler(CommandHandler("unban",       cmd_unban))
    app.add_handler(CommandHandler("addadmin",    cmd_addadmin))
    app.add_handler(CommandHandler("removeadmin", cmd_removeadmin))
    app.add_handler(CommandHandler("subscribe",   cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("checksubscription", cmd_checksubscription))
    app.add_handler(CommandHandler("setconfig",   cmd_setconfig))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_broadcast_message
    ))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_paid_limit
    ))
