"""
File upload, approval flow, and script management handlers.
"""
import os
import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, CallbackQueryHandler, filters

import database as db
import runner
from config import OWNER_ID, ADMIN_FILE_LIMIT
from utils.helpers import get_user_scripts_dir, get_log_path, read_log_tail, clear_log
from utils.security import scan_file
from utils.colored_buttons import btn, markup
from utils.emoji_ids import (
    BACK, STOP, REFRESH, NOTE, TRASH, UPLOAD, ARROW,
    FOLDER3, UP_CHART, GREEN_DOT, UPLOAD3, CLOCK
)
from utils.msg_builder import build_message

logger = logging.getLogger(__name__)


# ─── Helpers ────────────────────────────────────────────────

def _get_file_limit(user_id: int) -> int:
    if db.is_admin(user_id):
        return ADMIN_FILE_LIMIT
    if db.is_subscribed(user_id):
        return int(db.get_config("paid_file_limit", "15"))
    return int(db.get_config("free_file_limit", "3"))


def _script_kb(script_id: int, is_running: bool) -> dict:
    toggle = (
        btn("إيقاف",        f"stop_{script_id}",    style="danger")
        if is_running else
        btn("تشغيل",        f"run_{script_id}",     style="success")
    )
    return markup(
        [toggle, btn("إعادة تشغيل", f"restart_{script_id}", style="primary")],
        [
            btn("تثبيت المكتبات 📦", f"install_deps_{script_id}", style="primary"),
            btn("السجل",    f"log_{script_id}",     style="primary"),
        ],
        [
            btn("حذف",       f"delete_{script_id}",  style="danger"),
            btn("ملفاتي", "my_files", style="danger", icon=BACK)
        ],
    )


# ─── Upload handler ─────────────────────────────────────────

async def handle_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    doc  = update.message.document

    if not db.get_flag("upload_enabled"):
        await update.message.reply_text("❌ رفع الملفات معطل حالياً.")
        return

    if db.is_banned(user.id):
        await update.message.reply_text("🚫 أنت محظور.")
        return

    if db.get_flag("bot_locked") and not db.is_admin(user.id):
        await update.message.reply_text("🔒 البوت مغلق حالياً للصيانة.")
        return

    db.upsert_user(user.id, user.username, user.full_name)

    file_name = doc.file_name or ""
    ext = os.path.splitext(file_name)[1].lower().lstrip(".")
    if ext not in ("py", "js"):
        await update.message.reply_text("❌ يُقبل فقط ملفات `.py` و `.js`.")
        return

    # Check limit
    scripts = db.get_user_scripts(user.id)
    limit   = _get_file_limit(user.id)
    
    # Check if user is free and already has a file
    is_paid = db.is_subscribed(user.id) or db.is_admin(user.id)
    
    # For free users: check if they already uploaded before
    if not is_paid:
        with db.get_session() as s:
            db_user = s.get(db.User, user.id)
            has_uploaded = db_user.has_uploaded_free if db_user else False
        
        if has_uploaded:
            await update.message.reply_text(
                "❌你已经上传过一个文件了。\n"
                "المجاني يسمح بملف واحد فقط.\n"
                "اشترك في الباقة المدفوعة لرفع ملفات إضافية."
            )
            return
    
    if not is_paid and len(scripts) >= limit:
        await update.message.reply_text(
            "❌ وصلت للحد الأقصى (ملف واحد فقط).\n"
            "اشترك في الباقة المدفوعة لرفع أكثر من ملف."
        )
        return
    
    if is_paid and len(scripts) >= limit:
        await update.message.reply_text(
            f"❌ وصلت للحد الأقصى ({limit} ملفات).\n"
            "احذف ملفاً قديماً أو تواصل مع الأدمن لزيادة الحد."
        )
        return

    # Download
    user_dir  = get_user_scripts_dir(user.id)
    file_path = os.path.join(user_dir, file_name)
    tg_file   = await ctx.bot.get_file(doc.file_id)
    await tg_file.download_to_drive(file_path)

    # Security scan
    warnings = scan_file(file_path)
    if warnings:
        os.remove(file_path)
        warn_text = "\n".join(f"⚠️ {w}" for w in warnings)
        await update.message.reply_text(
            f"🛡 تم رفض الملف لأسباب أمنية:\n{warn_text}"
        )
        return

    # Save to DB
    script = db.add_script(user.id, file_name, ext, file_path)

    # Mark free user as having uploaded
    if not db.is_admin(user.id) and not db.is_subscribed(user.id):
        with db.get_session() as s:
            db_user = s.get(db.User, user.id)
            if db_user:
                db_user.has_uploaded_free = True

    # Approval flow
    if db.get_flag("approval_required") and not db.is_admin(user.id):
        approval = db.add_approval(script.id)
        await update.message.reply_text(
            f"📨 تم رفع `{file_name}` وهو قيد المراجعة.\n"
            "سيتم إشعارك عند الموافقة.",
            parse_mode="Markdown"
        )
        # Notify admins
        await _notify_admins_approval(ctx, script, approval)
    else:
        await update.message.reply_text(
            f"✅ تم رفع `{file_name}` بنجاح!\n"
            "اضغط تشغيل لبدء السكربت.",
            parse_mode="Markdown",
            reply_markup=_script_kb(script.id, False)
        )

async def _notify_admins_approval(ctx, script: db.Script, approval: db.Approval):
    from database import get_session, User
    with get_session() as s:
        admins = s.query(User).filter_by(is_admin=True).all()
        admin_ids = [a.id for a in admins]  # ← read IDs inside session

    kb = markup(
        [
            btn("✅ موافقة",  f"approve_{approval.id}", style="success"),
            btn("❌ رفض",     f"reject_{approval.id}",  style="danger"),
        ],
        [btn("👁 عرض الكود", f"viewcode_{script.id}", style="primary")],
    )
    text = (
        f"📋 طلب موافقة جديد\n\n"
        f"👤 المستخدم: `{script.owner_id}`\n"
        f"📄 الملف: `{script.file_name}`\n"
        f"🔧 النوع: {script.file_type.upper()}"
    )
    for admin_id in admin_ids:
        try:
            await ctx.bot.send_message(admin_id, text, parse_mode="Markdown", reply_markup=kb)
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")


# ─── My Files ───────────────────────────────────────────────

async def cb_my_files(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    scripts = db.get_user_scripts(user_id)

    if not scripts:
        text, entities = build_message(
            "{FOLDER} لا توجد ملفات مرفوعة بعد.\nأرسل ملف .py أو .js للبدء.",
            {"FOLDER": ("📂", FOLDER3)}
        )
        await ctx.bot.send_message(
            chat_id=query.message.chat_id,
            text=text,
            entities=entities,
            reply_markup=markup([btn("رجوع", "main_menu", style="danger", icon=BACK)])
        )
        return

    rows = []
    for sc in scripts:
        st      = db.get_script_status(sc.id)
        running = st and st.is_running
        style   = "success" if running else "primary"
        rows.append([btn(sc.file_name, f"script_info_{sc.id}", style=style, icon=GREEN_DOT if running else FOLDER3)])
    rows.append([btn("رجوع", "main_menu", style="danger", icon=BACK)])

    text, entities = build_message(
        "{FOLDER} ملفاتك (COUNT):",
        {"FOLDER": ("📂", FOLDER3)}
    )
    text = text.replace("COUNT", str(len(scripts)))

    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        entities=entities,
        reply_markup=markup(*rows)
    )


async def cb_script_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[-1])
    script    = db.get_script_by_id(script_id)

    if not script or script.owner_id != query.from_user.id and not db.is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح.", show_alert=True)
        return

    st      = db.get_script_status(script_id)
    running = st and st.is_running
    status  = "يعمل" if running else "متوقف"

    text = (
        f"📂 {script.file_name}\n"
        f"📊 الحالة: {status}\n"
        f"📤 النوع: {script.file_type.upper()}\n"
        f"📅 رُفع: {script.uploaded_at.strftime('%Y-%m-%d %H:%M')}"
    )

    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        reply_markup=_script_kb(script_id, running)
    )


# ─── Run / Stop / Restart ───────────────────────────────────

async def cb_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[1])
    script    = db.get_script_by_id(script_id)

    if not script:
        await query.answer("❌ الملف غير موجود.", show_alert=True)
        return

    if not db.get_flag("run_enabled"):
        await query.answer("❌ تشغيل السكربتات معطل.", show_alert=True)
        return

    # Check approval
    if db.get_flag("approval_required") and not db.is_admin(query.from_user.id):
        from database import get_session, Approval
        with get_session() as s:
            ap = s.query(Approval).filter_by(script_id=script_id).order_by(Approval.id.desc()).first()
            ap_status = ap.status if ap else None  # ← read status inside session
        if ap_status != "approved":
            await query.answer("⏳ الملف لم يُوافق عليه بعد.", show_alert=True)
            return

    def notify(msg):
        ctx.application.create_task(
            ctx.bot.send_message(query.message.chat_id, msg)
        )

    ok, msg = runner.start_script(script, notify_cb=notify)
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=msg,
        parse_mode="Markdown",
        reply_markup=_script_kb(script_id, ok)
    )


async def cb_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[1])
    ok, msg   = runner.stop_script(script_id)
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=msg,
        reply_markup=_script_kb(script_id, False)
    )


async def cb_restart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer("🔄 جاري إعادة التشغيل...")
    script_id = int(query.data.split("_")[1])
    runner.stop_script(script_id)
    script    = db.get_script_by_id(script_id)
    if script:
        ok, msg = runner.start_script(script)
        await ctx.bot.send_message(
            chat_id=query.message.chat_id,
            text=msg,
            parse_mode="Markdown",
            reply_markup=_script_kb(script_id, ok)
        )


async def cb_install_deps(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[-1])
    script    = db.get_script_by_id(script_id)
    
    if not script:
        await query.answer("❌ السكربت غير موجود.", show_alert=True)
        return

    m = await ctx.bot.send_message(query.message.chat_id, "⏳ جاري فحص وتثبيت المكتبات...")
    
    def notify(msg):
        ctx.application.create_task(
            ctx.bot.edit_message_text(msg, m.chat_id, m.message_id)
        )

    ok, msg = runner.install_dependencies(script_id, notify_cb=notify)
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=msg,
        reply_markup=_script_kb(script_id, False) # Status doesn't change
    )


# ─── Logs ───────────────────────────────────────────────────

async def cb_log(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[1])
    script    = db.get_script_by_id(script_id)
    if not script:
        await query.answer("❌ الملف غير موجود.", show_alert=True)
        return

    log_path = get_log_path(script.owner_id, script.file_name)
    tail     = read_log_tail(log_path, 50)

    text, entities = build_message(
        "{NOTE} آخر 50 سطر من FNAME:\n\nLOGS",
        {"NOTE": ("📝", NOTE)}
    )
    log_content = f"```\n{tail[-3000:]}\n```"
    text = text.replace("FNAME", script.file_name).replace("LOGS", log_content)

    kb = markup(
        [
            btn("مسح السجل",    f"clearlog_{script_id}",    style="danger",  icon=TRASH),
            btn("تحميل السجل",  f"downloadlog_{script_id}", style="primary", icon=NOTE),
        ],
        [btn("رجوع", f"script_info_{script_id}", style="danger", icon=BACK)],
    )
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        entities=entities,
        parse_mode="Markdown",
        reply_markup=kb
    )


async def cb_clearlog(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer("🗑 تم مسح السجل.")
    script_id = int(query.data.split("_")[1])
    script    = db.get_script_by_id(script_id)
    if script:
        clear_log(get_log_path(script.owner_id, script.file_name))


async def cb_downloadlog(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[1])
    script    = db.get_script_by_id(script_id)
    if not script:
        return
    log_path = get_log_path(script.owner_id, script.file_name)
    if not os.path.exists(log_path):
        await ctx.bot.send_message(query.message.chat_id, "📭 لا يوجد سجل.")
        return
    with open(log_path, "rb") as f:
        await ctx.bot.send_document(query.message.chat_id, f, filename=f"{script.file_name}.log")


# ─── Delete ─────────────────────────────────────────────────

async def cb_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[1])
    script    = db.get_script_by_id(script_id)

    if not script:
        await query.answer("❌ الملف غير موجود.", show_alert=True)
        return

    runner.stop_script(script_id)
    if os.path.exists(script.file_path):
        os.remove(script.file_path)
    db.delete_script(script_id)

    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"🗑 تم حذف `{script.file_name}`.",
        parse_mode="Markdown",
        reply_markup=markup([btn("ملفاتي", "my_files", style="danger", icon=BACK)])
    )


# ─── View Code ──────────────────────────────────────────────

async def cb_viewcode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    if not db.is_admin(query.from_user.id):
        await query.answer("❌ للأدمن فقط.", show_alert=True)
        return
    script_id = int(query.data.split("_")[1])
    script    = db.get_script_by_id(script_id)
    if not script or not os.path.exists(script.file_path):
        await query.answer("❌ الملف غير موجود.", show_alert=True)
        return
    with open(script.file_path, "r", encoding="utf-8", errors="ignore") as f:
        code = f.read()
    preview = code[:3500]
    await ctx.bot.send_message(
        query.message.chat_id,
        f"```{script.file_type}\n{preview}\n```",
        parse_mode="Markdown"
    )


# ─── Register ───────────────────────────────────────────────

def register(app):
    app.add_handler(MessageHandler(filters.Document.ALL, handle_upload))
    app.add_handler(CallbackQueryHandler(cb_my_files,    pattern="^my_files$"))
    app.add_handler(CallbackQueryHandler(cb_script_info, pattern=r"^script_info_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_run,         pattern=r"^run_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_stop,        pattern=r"^stop_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_restart,     pattern=r"^restart_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_log,         pattern=r"^log_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_clearlog,    pattern=r"^clearlog_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_downloadlog, pattern=r"^downloadlog_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_delete,      pattern=r"^delete_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_viewcode,    pattern=r"^viewcode_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_install_deps, pattern=r"^install_deps_\d+$"))
