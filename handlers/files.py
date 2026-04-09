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
from utils.emoji_ids import BACK, TRASH, NOTE
from utils.msg_builder import build_message, build_entities
from utils.sub_guard import check_and_guard

logger = logging.getLogger(__name__)


def _re(text: str, *emoji_keys: str) -> tuple[str, list]:
    """
    Helper سريع — يبني النص مع entities لإيموجيات من DB.
    الإيموجيات لازم تكون موجودة في النص بالفعل.
    مثال: text, ents = _re(f"{e} رسالة", "ERROR")
    """
    pairs = [db.get_emoji(k) for k in emoji_keys]
    return text, build_entities(text, pairs)


# ─── Helpers ────────────────────────────────────────────────

def _get_file_limit(user_id: int) -> int:
    if db.is_admin(user_id):
        return ADMIN_FILE_LIMIT
    if db.is_subscribed(user_id):
        return int(db.get_config("paid_file_limit", "15"))
    return int(db.get_config("free_file_limit", "3"))


def _script_kb(script_id: int, is_running: bool, auto_restart: bool = True) -> dict:
    # الأزرار بتستخدم icon للإيموجي المتحرك — مش في النص
    run_id    = db.get_emoji("BTN_RUN")[1]
    stop_id   = db.get_emoji("BTN_STOP")[1]
    ar_id     = db.get_emoji("BTN_AUTO_ON")[1]
    restart_id = db.get_emoji("BTN_RESTART")[1]
    install_id = db.get_emoji("BTN_INSTALL")[1]
    log_id    = db.get_emoji("BTN_LOG")[1]
    update_id = db.get_emoji("BTN_UPDATE")[1]
    diag_id   = db.get_emoji("BTN_DIAGNOSE")[1]
    del_id    = db.get_emoji("BTN_DELETE")[1]
    bk_id     = db.get_emoji("BTN_BACK")[1]

    toggle = (
        btn("إيقاف",       f"stop_{script_id}",  style="danger",   icon=stop_id)
        if is_running else
        btn("تشغيل",       f"run_{script_id}",   style="success",  icon=run_id)
    )
    ar_btn = btn(
        "تلقائي: مفعل" if auto_restart else "تلقائي: معطل",
        f"toggle_ar_{script_id}",
        style="success" if auto_restart else "danger",
        icon=ar_id
    )
    return markup(
        [toggle, btn("إعادة تشغيل", f"restart_{script_id}", style="primary", icon=restart_id)],
        [ar_btn],
        [
            btn("تثبيت المكتبات", f"install_deps_{script_id}", style="primary", icon=install_id),
            btn("السجل",          f"log_{script_id}",           style="primary", icon=log_id),
        ],
        [
            btn("تحديث الملف", f"update_script_{script_id}", style="primary", icon=update_id),
            btn("تشخيص",       f"diagnose_{script_id}",       style="primary", icon=diag_id),
        ],
        [
            btn("حذف",    f"delete_{script_id}", style="danger",  icon=del_id),
            btn("ملفاتي", "my_files",            style="danger",  icon=bk_id),
        ],
    )


# ─── Upload handler ─────────────────────────────────────────

async def handle_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    doc  = update.message.document

    if not db.get_flag("upload_enabled"):
        e, eid = db.get_emoji("ERROR")
        t = f"{e} رفع الملفات معطل حالياً."
        await update.message.reply_text(t, entities=build_entities(t, [(e, eid)]))
        return

    if db.is_banned(user.id):
        e, eid = db.get_emoji("BANNED")
        t = f"{e} أنت محظور."
        await update.message.reply_text(t, entities=build_entities(t, [(e, eid)]))
        return

    if db.get_flag("bot_locked") and not db.is_admin(user.id):
        e, eid = db.get_emoji("LOCKED")
        t = f"{e} البوت مغلق حالياً للصيانة."
        await update.message.reply_text(t, entities=build_entities(t, [(e, eid)]))
        return

    # ─── فحص الاشتراك الإجباري ───────────────────────────
    if not await check_and_guard(update, ctx):
        return

    db.upsert_user(user.id, user.username, user.full_name)

    file_name = doc.file_name or ""
    ext = os.path.splitext(file_name)[1].lower().lstrip(".")
    if ext not in ("py", "js"):
        e, eid = db.get_emoji("ERROR")
        t = f"{e} يُقبل فقط ملفات `.py` و `.js`."
        await update.message.reply_text(t, entities=build_entities(t, [(e, eid)]))
        return

    # Check limit
    scripts = db.get_user_scripts(user.id)
    limit   = _get_file_limit(user.id)
    is_paid = db.is_subscribed(user.id) or db.is_admin(user.id)

    if not is_paid:
        with db.get_session() as s:
            db_user = s.get(db.User, user.id)
            uploads_used = db_user.free_uploads_used if db_user else 0

        # تحقق من الحد التاريخي — بعد ما يستنفد الحد ما يرفعش تاني حتى لو حذف
        if uploads_used >= limit:
            paid_limit = db.get_config("paid_file_limit", "15")
            username   = db.get_config("your_username", "@P_X_24").replace("@", "")
            e, eid = db.get_emoji("BANNED")
            t = (
                f"{e} استنفدت حصتك المجانية ({limit} ملفات).\n\n"
                f"الباقة المجانية:\n"
                f"• {limit} ملفات فقط (مدى الحياة)\n"
                f"• لا يمكن الرفع بعد استنفاد الحصة\n\n"
                f"الباقة المدفوعة:\n"
                f"• حتى {paid_limit} ملف نشط\n"
                f"• إعادة تشغيل تلقائية عند التوقف\n"
                f"• تحديث الملفات بدون حدود\n"
                f"• أولوية في الدعم الفني\n\n"
                "للاشتراك تواصل مع المالك:"
            )
            await update.message.reply_text(
                t,
                entities=build_entities(t, [(e, eid)]),
                reply_markup=markup(
                    [btn("💬 تواصل مع المالك", url=f"https://t.me/{username}", style="success")]
                )
            )
            return

    if len(scripts) >= limit and is_paid:
        e, eid = db.get_emoji("ERROR")
        t = (f"{e} وصلت للحد الأقصى ({limit} ملفات).\n"
             "احذف ملفاً قديماً أو تواصل مع الأدمن لزيادة الحد.")
        await update.message.reply_text(t, entities=build_entities(t, [(e, eid)]))
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
        sh, sh_id = db.get_emoji("SHIELD")
        wa, wa_id = db.get_emoji("WARNING")
        warn_lines = "\n".join(f"{wa} {w}" for w in warnings)
        t = f"{sh} تم رفض الملف لأسباب أمنية:\n{warn_lines}"
        await update.message.reply_text(t, entities=build_entities(t, [(sh, sh_id), (wa, wa_id)]))
        return

    # Save to DB
    script = db.add_script(user.id, file_name, ext, file_path)

    # Mark free user upload count
    if not db.is_admin(user.id) and not db.is_subscribed(user.id):
        with db.get_session() as s:
            db_user = s.get(db.User, user.id)
            if db_user:
                db_user.has_uploaded_free  = True
                db_user.free_uploads_used  = (db_user.free_uploads_used or 0) + 1

    # Approval flow
    if db.get_flag("approval_required") and not db.is_admin(user.id):
        approval = db.add_approval(script.id)
        await update.message.reply_text(
            f"📨 تم رفع `{file_name}` وهو قيد المراجعة.\n"
            "سيتم إشعارك عند الموافقة.",
            parse_mode="Markdown"
        )
        await _notify_admins_approval(ctx, script, approval)
    else:
        ok_char, ok_id = db.get_emoji("SUCCESS")
        text = f"{ok_char} تم رفع `{file_name}` بنجاح!\nاضغط تشغيل لبدء السكربت."
        await update.message.reply_text(
            text,
            entities=build_entities(text, [(ok_char, ok_id)]),
            parse_mode="Markdown",
            reply_markup=_script_kb(script.id, False)
        )

async def _notify_admins_approval(ctx, script: db.Script, approval: db.Approval):
    from database import get_session, User
    with get_session() as s:
        admins = s.query(User).filter_by(is_admin=True).all()
        admin_ids = [a.id for a in admins]

    fa, fa_id = db.get_emoji("FILE_APPROVE")
    fu, fu_id = db.get_emoji("FILE_USER")
    fd, fd_id = db.get_emoji("FILE_DOC")
    ft, ft_id = db.get_emoji("FILE_TYPE")

    kb = markup(
        [
            btn(f"{db.get_emoji('BTN_APPROVE')[0]} موافقة", f"approve_{approval.id}", style="success"),
            btn(f"{db.get_emoji('BTN_REJECT')[0]} رفض",     f"reject_{approval.id}",  style="danger"),
        ],
        [btn(f"{db.get_emoji('BTN_VIEWCODE')[0]} عرض الكود", f"viewcode_{script.id}", style="primary")],
    )
    text = (
        f"{fa} طلب موافقة جديد\n\n"
        f"{fu} المستخدم: `{script.owner_id}`\n"
        f"{fd} الملف: `{script.file_name}`\n"
        f"{ft} النوع: {script.file_type.upper()}"
    )
    entities = build_entities(text, [(fa, fa_id), (fu, fu_id), (fd, fd_id), (ft, ft_id)])
    for admin_id in admin_ids:
        try:
            await ctx.bot.send_message(
                admin_id, text,
                entities=entities,
                parse_mode="Markdown",
                reply_markup=kb
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")


# ─── My Files ───────────────────────────────────────────────

async def cb_my_files(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    if not await check_and_guard(update, ctx):
        return
    user_id = query.from_user.id
    scripts = db.get_user_scripts(user_id)
    bk_id   = db.get_emoji("BTN_BACK")[1]

    if not scripts:
        folder_char, folder_id = db.get_emoji("FOLDER3")
        text, entities = build_message(
            "{FOLDER} لا توجد ملفات مرفوعة بعد.\nأرسل ملف .py أو .js للبدء.",
            {"FOLDER": (folder_char, folder_id)}
        )
        await ctx.bot.send_message(
            chat_id=query.message.chat_id,
            text=text,
            entities=entities,
            reply_markup=markup([btn("رجوع", "main_menu", style="danger", icon=bk_id)])
        )
        return

    rows = []
    for sc in scripts:
        st      = db.get_script_status(sc.id)
        running = st and st.is_running
        style   = "success" if running else "primary"
        icon    = db.get_emoji("GREEN_DOT")[1] if running else db.get_emoji("FOLDER3")[1]
        rows.append([btn(sc.file_name, f"script_info_{sc.id}", style=style, icon=icon)])
    rows.append([btn("رجوع", "main_menu", style="danger", icon=bk_id)])

    folder_char, folder_id = db.get_emoji("FOLDER3")
    text, entities = build_message(
        "{FOLDER} ملفاتك (COUNT):",
        {"FOLDER": (folder_char, folder_id)}
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

    if not script or (script.owner_id != query.from_user.id and not db.is_admin(query.from_user.id)):
        await query.answer("❌ غير مصرح.", show_alert=True)
        return

    st           = db.get_script_status(script_id)
    running      = st and st.is_running
    uptime       = runner.get_uptime(script_id)
    resources    = runner.get_resource_usage(script_id) if running else None
    auto_restart = script_id not in runner._intentional_stop


    fi,  fi_id  = db.get_emoji("FILE_ICON")
    up,  up_id  = db.get_emoji("UP_CHART")
    ft,  ft_id  = db.get_emoji("FILE_TYPE")
    fd,  fd_id  = db.get_emoji("FILE_DATE")
    on,  on_id  = db.get_emoji("STATUS_ON")
    off, off_id = db.get_emoji("STATUS_OFF")
    fc,  fc_id  = db.get_emoji("FILE_CPU")
    fr,  fr_id  = db.get_emoji("FILE_RESTART")

    status_line = f"{on} يعمل" if running else f"{off} متوقف"
    if running and uptime:
        status_line += f" — {uptime}"

    lines = [
        f"{fi} `{script.file_name}`",
        f"{up} الحالة: {status_line}",
        f"{ft} النوع: {script.file_type.upper()}",
        f"{fd} رُفع: {script.uploaded_at.strftime('%Y-%m-%d %H:%M')}",
    ]

    if resources:
        lines.append(f"{fc} CPU: {resources['cpu']}% | RAM: {resources['mem']} MB")

    rc = runner._restart_counts.get(script_id, 0)
    if rc > 0:
        lines.append(f"{fr} إعادة تشغيل: {rc} مرة")

    full_text = "\n".join(lines)
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=full_text,
        entities=build_entities(full_text, [
            (fi, fi_id), (up, up_id), (ft, ft_id), (fd, fd_id),
            (on, on_id), (off, off_id), (fc, fc_id), (fr, fr_id),
        ]),
        parse_mode="Markdown",
        reply_markup=_script_kb(script_id, running, auto_restart)
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
        await query.answer(f"{db.get_emoji('ERROR')[0]} تشغيل السكربتات معطل.", show_alert=True)
        return

    # Check approval
    if db.get_flag("approval_required") and not db.is_admin(query.from_user.id):
        from database import get_session, Approval
        with get_session() as s:
            ap = s.query(Approval).filter_by(script_id=script_id).order_by(Approval.id.desc()).first()
            ap_status = ap.status if ap else None  # ← read status inside session
        if ap_status != "approved":
            await query.answer(f"{db.get_emoji('STATUS_WAIT')[0]} الملف لم يُوافق عليه بعد.", show_alert=True)
            return

    def notify(msg):
        ctx.application.create_task(
            ctx.bot.send_message(query.message.chat_id, msg)
        )

    # حفظ notify_cb دائماً عشان إعادة التشغيل التلقائي تبعت إشعارات
    runner._notify_registry[script_id] = notify

    ok, msg = runner.start_script(script, notify_cb=notify)
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=msg,
        parse_mode="Markdown",
        reply_markup=_script_kb(script_id, ok, script_id not in runner._intentional_stop)
    )


async def cb_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[1])
    ok, msg   = runner.stop_script(script_id, intentional=True)
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=msg,
        reply_markup=_script_kb(script_id, False, auto_restart=False)
    )


async def cb_restart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer("🔄 جاري إعادة التشغيل...")
    script_id = int(query.data.split("_")[1])

    def notify(msg):
        ctx.application.create_task(ctx.bot.send_message(query.message.chat_id, msg))

    # حفظ notify_cb قبل الـ restart
    runner._notify_registry[script_id] = notify

    ok, msg = runner.restart_script(script_id)
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=msg,
        parse_mode="Markdown",
        reply_markup=_script_kb(script_id, ok, script_id not in runner._intentional_stop)
    )


async def cb_install_deps(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[-1])
    script    = db.get_script_by_id(script_id)
    
    if not script:
        await query.answer("❌ السكربت غير موجود.", show_alert=True)
        return

    m = await ctx.bot.send_message(query.message.chat_id, f"{db.get_emoji('STATUS_WAIT')[0]} جاري فحص وتثبيت المكتبات...")
    
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

    note_char, note_id = db.get_emoji("NOTE")
    bk_id  = db.get_emoji("BTN_BACK")[1]
    tr_id  = db.get_emoji("NOTE")[1]  # reuse NOTE for download icon
    text, entities = build_message(
        "{NOTE} آخر 50 سطر من FNAME:\n\nLOGS",
        {"NOTE": (note_char, note_id)}
    )
    log_content = f"```\n{tail[-3000:]}\n```"
    text = text.replace("FNAME", script.file_name).replace("LOGS", log_content)

    kb = markup(
        [
            btn("مسح السجل",    f"clearlog_{script_id}",    style="danger",  icon=db.get_emoji("ERROR")[1]),
            btn("تحميل السجل",  f"downloadlog_{script_id}", style="primary", icon=note_id),
        ],
        [btn("رجوع", f"script_info_{script_id}", style="danger", icon=bk_id)],
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

    bk_id = db.get_emoji("BTN_BACK")[1]
    dl, dl_id = db.get_emoji("BTN_DELETE")
    t = f"{dl} تم حذف `{script.file_name}`."
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=t,
        entities=build_entities(t, [(dl, dl_id)]),
        parse_mode="Markdown",
        reply_markup=markup([btn("ملفاتي", "my_files", style="danger", icon=bk_id)])
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


# ─── Update Script ──────────────────────────────────────────

async def cb_update_script(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """يطلب من المستخدم إرسال نسخة جديدة من الملف لاستبدال الموجود."""
    query     = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[-1])
    script    = db.get_script_by_id(script_id)

    if not script or (script.owner_id != query.from_user.id and not db.is_admin(query.from_user.id)):
        await query.answer("❌ غير مصرح.", show_alert=True)
        return

    ctx.user_data["awaiting_update_script_id"] = script_id
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=(
            f"🔄 أرسل الملف الجديد لاستبدال `{script.file_name}`.\n"
            "يجب أن يكون نفس النوع (.py أو .js)."
        ),
        parse_mode="Markdown",
        reply_markup=markup([btn("❌ إلغاء", f"script_info_{script_id}", style="danger")])
    )


async def handle_script_update(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """يستقبل الملف الجديد ويستبدل القديم."""
    script_id = ctx.user_data.get("awaiting_update_script_id")
    if not script_id:
        return

    user = update.effective_user
    doc  = update.message.document
    if not doc:
        return

    script = db.get_script_by_id(script_id)
    if not script or (script.owner_id != user.id and not db.is_admin(user.id)):
        return

    file_name = doc.file_name or ""
    ext = os.path.splitext(file_name)[1].lower().lstrip(".")
    if ext != script.file_type:
        await update.message.reply_text(
            f"❌ يجب أن يكون الملف من نفس النوع (.{script.file_type})."
        )
        return

    ctx.user_data.pop("awaiting_update_script_id", None)

    # إيقاف السكربت إن كان شغال
    was_running = runner.is_running(script_id)
    if was_running:
        runner.stop_script(script_id)

    # تنزيل الملف الجديد فوق القديم
    tg_file = await ctx.bot.get_file(doc.file_id)
    await tg_file.download_to_drive(script.file_path)

    # فحص أمني
    warnings = scan_file(script.file_path)
    if warnings:
        os.remove(script.file_path)
        db.set_script_stopped(script_id)
        sh, sh_id = db.get_emoji("SHIELD")
        wa, wa_id = db.get_emoji("WARNING")
        warn_lines = "\n".join(f"{wa} {w}" for w in warnings)
        t = f"{sh} تم رفض الملف لأسباب أمنية:\n{warn_lines}\n\nتم حذف الملف الجديد."
        await update.message.reply_text(t, entities=build_entities(t, [(sh, sh_id), (wa, wa_id)]))
        return

    ok, ok_id = db.get_emoji("SUCCESS")
    t = f"{ok} تم تحديث `{script.file_name}` بنجاح!"
    await update.message.reply_text(
        t,
        entities=build_entities(t, [(ok, ok_id)]),
        parse_mode="Markdown",
        reply_markup=_script_kb(script_id, False)
    )

    if was_running:
        ok2, msg2 = runner.start_script(script)
        if ok2:
            on, on_id = db.get_emoji("STATUS_ON")
            t = f"{on} تم إعادة تشغيل السكربت تلقائياً."
            await update.message.reply_text(t, entities=build_entities(t, [(on, on_id)]))


async def cb_toggle_auto_restart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """يفعّل أو يعطّل إعادة التشغيل التلقائي للسكربت."""
    query     = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[-1])
    script    = db.get_script_by_id(script_id)

    if not script or (script.owner_id != query.from_user.id and not db.is_admin(query.from_user.id)):
        await query.answer("❌ غير مصرح.", show_alert=True)
        return

    currently_auto = script_id not in runner._intentional_stop

    if currently_auto:
        runner._intentional_stop.add(script_id)
    else:
        runner._intentional_stop.discard(script_id)
        runner._restart_counts.pop(script_id, None)

    ar, ar_id = db.get_emoji("BTN_AUTO_ON")
    ok, ok_id = db.get_emoji("SUCCESS")
    er, er_id = db.get_emoji("ERROR")

    new_state  = not currently_auto
    state_char = ok if new_state else er
    state_id   = ok_id if new_state else er_id
    state_text = "مفعلة" if new_state else "معطلة"

    await query.answer(f"{'✅' if new_state else '❌'} إعادة التشغيل التلقائي {state_text}", show_alert=True)

    running = runner.is_running(script_id)
    t = f"{ar} إعادة التشغيل التلقائي: {state_char} {state_text}"
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=t,
        entities=build_entities(t, [(ar, ar_id), (state_char, state_id)]),
        reply_markup=_script_kb(script_id, running, new_state)
    )


async def _handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Router موحد للملفات — يوجه لتحديث أو رفع جديد حسب الحالة."""
    if ctx.user_data.get("awaiting_update_script_id"):
        await handle_script_update(update, ctx)
    else:
        await handle_upload(update, ctx)


# ─── Diagnose ───────────────────────────────────────────────

async def cb_diagnose(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """تشخيص ذكي وشامل لحالة السكربت."""
    query     = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[1])
    script    = db.get_script_by_id(script_id)

    if not script or (script.owner_id != query.from_user.id and not db.is_admin(query.from_user.id)):
        await query.answer("❌ غير مصرح.", show_alert=True)
        return

    # رسالة انتظار لأن الفحص قد يأخذ ثانية
    wait_msg = await ctx.bot.send_message(query.message.chat_id, f"{db.get_emoji('BTN_DIAGNOSE')[0]} جاري الفحص...")

    health = runner.get_script_health(script_id)
    st     = db.get_script_status(script_id)

    ok_e,  ok_id  = db.get_emoji("SUCCESS")
    er_e,  er_id  = db.get_emoji("ERROR")
    wa_e,  wa_id  = db.get_emoji("WARNING")
    on_e,  on_id  = db.get_emoji("STATUS_ON")
    off_e, off_id = db.get_emoji("STATUS_OFF")
    st_e,  st_id  = db.get_emoji("STATUS_STOP")
    ar_e,  ar_id  = db.get_emoji("BTN_AUTO_ON")
    fi_e,  fi_id  = db.get_emoji("FILE_CPU")
    cl_e,  cl_id  = db.get_emoji("CLOCK")
    dg_e,  dg_id  = db.get_emoji("BTN_DIAGNOSE")
    rn_e,  rn_id  = db.get_emoji("BTN_RUN")

    # نجمع كل الإيموجيات المحتملة عشان نمررها للـ entities
    all_emoji_pairs = [
        (ok_e, ok_id), (er_e, er_id), (wa_e, wa_id),
        (on_e, on_id), (off_e, off_id), (st_e, st_id),
        (ar_e, ar_id), (fi_e, fi_id), (cl_e, cl_id),
        (dg_e, dg_id), (rn_e, rn_id),
    ]

    lines = [f"{dg_e} تشخيص: `{script.file_name}`\n"]

    # ─── الحالة ───────────────────────────────────────────
    if health["status"] == "running":
        uptime = health.get("uptime") or "—"
        lines.append(f"{on_e} الحالة: يعمل — مدة التشغيل: {uptime}")
    else:
        lines.append(f"{off_e} الحالة: متوقف")

    # ─── الملف ────────────────────────────────────────────
    if health["file_exists"]:
        lines.append(f"{ok_e} الملف: موجود على السيرفر")
    else:
        lines.append(f"{er_e} الملف: غير موجود على السيرفر")
        lines.append("   ← الحل: احذف السكربت وأعد رفعه")

    # ─── Syntax (Python فقط) ──────────────────────────────
    if script.file_type == "py" and health["file_exists"]:
        if health.get("syntax_ok", True):
            lines.append(f"{ok_e} الكود: لا يوجد أخطاء syntax")
        else:
            lines.append(f"{er_e} الكود: يوجد خطأ syntax")
            lines.append("   ← صحح الخطأ وأعد رفع الملف")

    # ─── المكتبات ─────────────────────────────────────────
    missing = health.get("missing_pkgs", [])
    if script.file_type == "py":
        if not missing:
            lines.append(f"{ok_e} المكتبات: كلها مثبتة")
        else:
            lines.append(f"{wa_e} مكتبات ناقصة: `{', '.join(missing[:5])}`")
            lines.append("   ← اضغط 'تثبيت المكتبات' لتثبيتها")

    # ─── إعادة التشغيل ────────────────────────────────────
    rc = health["restart_count"]
    if rc == 0:
        lines.append(f"{ok_e} إعادة التشغيل: لم تحدث")
    elif rc < runner.MAX_RESTART_ATTEMPTS:
        lines.append(f"{wa_e} إعادة التشغيل: {rc} مرة")
    else:
        lines.append(f"{st_e} إعادة التشغيل: توقفت بعد {rc} محاولة")
        lines.append("   ← افتح السجل لمعرفة سبب التوقف المتكرر")

    # ─── مشاكل إضافية ─────────────────────────────────────
    if health["issues"]:
        lines.append(f"\n{wa_e} مشاكل مكتشفة:")
        for issue in health["issues"]:
            lines.append(f"  • {issue}")

    # ─── آخر توقف ─────────────────────────────────────────
    if st and st.stopped_at:
        lines.append(f"\n{cl_e} آخر توقف: {st.stopped_at.strftime('%Y-%m-%d %H:%M')} UTC")

    # ─── التشغيل التلقائي ─────────────────────────────────
    auto_restart = health.get("auto_restart", True)
    lines.append(f"{ok_e if auto_restart else er_e} إعادة التشغيل التلقائي: {'مفعلة' if auto_restart else 'معطلة'}")

    # ─── الموارد ──────────────────────────────────────────
    if health.get("resources"):
        r = health["resources"]
        lines.append(f"{fi_e} CPU: {r['cpu']}% | RAM: {r['mem']} MB")

    # ─── تلميح ────────────────────────────────────────────
    if not health["issues"] and health["status"] == "stopped":
        lines.append(f"\n{rn_e} السكربت متوقف ولا توجد مشاكل — اضغط تشغيل.")

    full_text = "\n".join(lines)
    await ctx.bot.edit_message_text(
        chat_id=wait_msg.chat_id,
        message_id=wait_msg.message_id,
        text=full_text,
        entities=build_entities(full_text, all_emoji_pairs),
        parse_mode="Markdown",
        reply_markup=markup([btn("رجوع", f"script_info_{script_id}", style="danger", icon=db.get_emoji("BTN_BACK")[1])])
    )


# ─── Register ───────────────────────────────────────────────

def register(app):
    # handler واحد للملفات يتعامل مع التحديث والرفع الجديد
    app.add_handler(MessageHandler(filters.Document.ALL, _handle_document))
    app.add_handler(CallbackQueryHandler(cb_my_files,       pattern="^my_files$"))
    app.add_handler(CallbackQueryHandler(cb_script_info,    pattern=r"^script_info_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_run,            pattern=r"^run_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_stop,           pattern=r"^stop_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_restart,        pattern=r"^restart_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_log,            pattern=r"^log_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_clearlog,       pattern=r"^clearlog_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_downloadlog,    pattern=r"^downloadlog_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_delete,         pattern=r"^delete_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_viewcode,       pattern=r"^viewcode_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_install_deps,        pattern=r"^install_deps_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_update_script,       pattern=r"^update_script_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_diagnose,            pattern=r"^diagnose_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_toggle_auto_restart, pattern=r"^toggle_ar_\d+$"))
