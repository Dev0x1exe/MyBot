import logging
import random
import string
import time
import asyncio
import re
from datetime import datetime, timedelta

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters,
)

from config import (
    BOT_TOKEN, ADMIN_IDS, SUPPORT_CHANNEL,
    KEY_MAX_RESETS, KEY_WINDOW_SECONDS,
    USER_MAX_RESETS, USER_WINDOW_SECONDS, ADMIN_BYPASS_RESET,
)
import database as db

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("MasterBot")


# ═══════════════════════════════════════════════════════════
#   States
# ═══════════════════════════════════════════════════════════
(
    P_NAME, P_EMOJI, P_DESC, P_PRICE, P_MODE, P_FIRST_CONTENT,
    AC_CONTENT, PE_VALUE,
    UP_USER, UP_AMOUNT, UB_USER,
    MSG_USER, MSG_TEXT, BC_TEXT,
    MAINT_TIME, MAINT_MSG,
    PL_AMOUNT, PL_MAX_USES, PL_EXPIRE_HOURS,
    ADD_CH_ID, ADD_CH_TITLE, SET_VALUE,
) = range(22)


# ═══════════════════════════════════════════════════════════
#   Helpers
# ═══════════════════════════════════════════════════════════
def is_admin(uid): return uid in ADMIN_IDS

def esc(t):
    if not t: return ""
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def now_sec(): return int(time.time())

def fmt(n):
    try: return f"{int(n):,}"
    except: return str(n)

def cur(): return db.get_settings().get("currency_emoji", "💰")

def format_duration(s):
    if s <= 0: return "منتهي"
    d = s // 86400
    h = (s % 86400) // 3600
    m = (s % 3600) // 60
    if d > 0: return f"{d} يوم"
    if h > 0: return f"{h} ساعة"
    return f"{m} دقيقة"

def format_short(s):
    if s <= 0: return "الآن"
    h = s // 3600
    m = (s % 3600) // 60
    ss = s % 60
    if h > 0: return f"{h}س {m}د"
    if m > 0: return f"{m}د {ss}ث"
    return f"{ss}ث"

def get_duration_label(s):
    labels = {3600: "⏱️ ساعة", 10800: "⏱️ 3 ساعات", 21600: "⏱️ 6 ساعات",
              43200: "⏱️ 12 ساعة", 86400: "⏱️ يوم", 259200: "⏱️ 3 أيام",
              604800: "⏱️ أسبوع", 1296000: "⏱️ 15 يوم", 2592000: "⏱️ شهر"}
    return labels.get(s, f"⏱️ {format_duration(s)}")

def stock_label(pid):
    st = db.get_product_stock(pid)
    if st == -1: return "♾️ لا نهائي"
    if st == 0: return "❌ نفدت"
    return f"📦 متوفر: {st}"


# ═══════════════════════════════════════════════════════════
#   🔧 Maintenance — محلي فقط
# ═══════════════════════════════════════════════════════════
def check_maintenance():
    try:
        return db.is_bot_in_maintenance()
    except Exception as e:
        logger.warning(f"maintenance check error: {e}")
        return False, {}


# ═══════════════════════════════════════════════════════════
#   Subscription
# ═══════════════════════════════════════════════════════════
async def check_subscription(uid, context):
    channels = db.get_settings().get("required_channels", [])
    if not isinstance(channels, list) or not channels:
        return True, []
    missing = []
    for ch in channels:
        try:
            m = await context.bot.get_chat_member(ch.get("chat_id"), uid)
            if m.status in [ChatMember.LEFT, ChatMember.BANNED]:
                missing.append(ch)
        except Exception:
            missing.append(ch)
    return len(missing) == 0, missing


def subscription_kb(missing):
    rows = []
    for ch in missing:
        url = ch.get("url", "") or f"https://t.me/{str(ch.get('chat_id','')).lstrip('@')}"
        rows.append([InlineKeyboardButton(f"📢 {ch.get('title','قناة')}", url=url)])
    rows.append([InlineKeyboardButton("✅ تحقّق", callback_data="check_sub")])
    return InlineKeyboardMarkup(rows)


async def notify_admins(context, text):
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(aid, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
#   Keyboards
# ═══════════════════════════════════════════════════════════
def cancel_only_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ إلغاء", callback_data="cancel_conv")
    ]])


def cancel_kb(rows=None):
    rows = list(rows) if rows else []
    rows.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel_conv")])
    return InlineKeyboardMarkup(rows)


def main_menu_kb(uid):
    rows = [
        [InlineKeyboardButton("🔑 شراء مفتاح", callback_data="menu_buy_key"),
         InlineKeyboardButton("💎 مفاتيحي", callback_data="menu_my_keys")],
        [InlineKeyboardButton("🛍️ المتجر", callback_data="menu_shop"),
         InlineKeyboardButton("🎒 مشترياتي", callback_data="menu_purchases")],
        [InlineKeyboardButton("🔧 ريست مفتاح", callback_data="menu_reset_key")],
        [InlineKeyboardButton("🎁 الهدية اليومية", callback_data="menu_daily"),
         InlineKeyboardButton("💰 رصيدي", callback_data="menu_balance")],
        [InlineKeyboardButton("👥 دعوة أصدقاء", callback_data="menu_referral"),
         InlineKeyboardButton("📊 إحصائياتي", callback_data="menu_stats")],
        [InlineKeyboardButton("📱 قناتنا", url=SUPPORT_CHANNEL)],
    ]
    if is_admin(uid):
        rows.append([InlineKeyboardButton("⚙️ لوحة التحكم", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def buy_key_kb(points):
    settings = db.get_settings()
    durations = settings.get("key_durations", {})
    buttons = []
    for seconds_str, cost in durations.items():
        seconds = int(seconds_str)
        label = get_duration_label(seconds)
        emoji = "✅" if points >= cost else "🔒"
        buttons.append([InlineKeyboardButton(
            f"{label} — {fmt(cost)} نقطة {emoji}",
            callback_data=f"keybuy_{seconds}_{cost}"
        )])
    buttons.append([InlineKeyboardButton("⬅️ رجوع", callback_data="back_main")])
    return InlineKeyboardMarkup(buttons)


def key_result_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 شراء آخر", callback_data="menu_buy_key")],
        [InlineKeyboardButton("💎 مفاتيحي", callback_data="menu_my_keys")],
        [InlineKeyboardButton("⬅️ القائمة", callback_data="back_main")],
    ])


def shop_kb():
    products = db.get_products(active_only=True)
    keyboard, row = [], []
    for pid, p in products.items():
        emoji, name, price = p.get("emoji", "📦"), p.get("name", "?"), p.get("price", 0)
        avail = db.is_product_available(pid)
        status = "" if avail else " ❌"
        btn = InlineKeyboardButton(
            f"{emoji} {name} — {fmt(price)}{status}",
            callback_data=f"shop_view_{pid}"
        )
        if len(row) == 1:
            keyboard.append(row); row = []
        row.append(btn)
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("⬅️ رجوع", callback_data="back_main")])
    return InlineKeyboardMarkup(keyboard)


def shop_product_kb(pid):
    if db.is_product_available(pid):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 شراء", callback_data=f"shop_buy_{pid}")],
            [InlineKeyboardButton("⬅️ المتجر", callback_data="menu_shop")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ نفدت", callback_data="noop")],
        [InlineKeyboardButton("⬅️ المتجر", callback_data="menu_shop")],
    ])


def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔧 الصيانة", callback_data="adm_maint"),
         InlineKeyboardButton("📢 القنوات", callback_data="adm_channels")],
        [InlineKeyboardButton("💰 النقاط", callback_data="adm_points"),
         InlineKeyboardButton("⚙️ إعدادات", callback_data="adm_settings")],
        [InlineKeyboardButton("🛍️ المنتجات", callback_data="adm_products"),
         InlineKeyboardButton("➕ منتج", callback_data="adm_add_p")],
        [InlineKeyboardButton("👥 المستخدمون", callback_data="adm_users"),
         InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats")],
        [InlineKeyboardButton("📣 بث", callback_data="adm_broadcast"),
         InlineKeyboardButton("💾 نسخة احتياطية", callback_data="adm_backup")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="back_main")],
    ])


# ═══════════════════════════════════════════════════════════
#   Cancel
# ═══════════════════════════════════════════════════════════
async def cb_cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("❌ تم الإلغاء")
    context.user_data.clear()
    try:
        await q.edit_message_text(
            "❌ <b>تم الإلغاء</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚙️ اللوحة", callback_data="admin_panel")
            ]]),
        )
    except Exception:
        pass
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
#   /start + Main Menu
# ═══════════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    is_maint, m = check_maintenance()
    if is_maint and not is_admin(user.id):
        txt = f"🔧 <b>البوت تحت الصيانة</b>\n\n{m.get('message','⚠️')}"
        end = m.get("end_time", 0) or 0
        if end > 0:
            txt += f"\n\n⏰ ينتهي في: <code>{datetime.fromtimestamp(end).strftime('%Y-%m-%d %H:%M')}</code>"
        await update.message.reply_text(txt, parse_mode=ParseMode.HTML)
        return

    # التحقق من الاشتراك
    if not is_admin(user.id):
        is_sub, missing = await check_subscription(user.id, context)
        if not is_sub:
            await update.message.reply_text(
                "⚠️ <b>اشترك في القنوات أولاً:</b>",
                reply_markup=subscription_kb(missing),
                parse_mode=ParseMode.HTML,
            )
            return

    db_user = db.get_user(user.id)
    is_new = False

    if not db_user:
        referred_by = None
        # ✅ إصلاح: قبول البادئة الصغيرة ref_ (التي يولدها البوت) أو الكبيرة REF_
        if args:
            start_arg = args[0]
            # إذا كان يبدأ بـ ref_ (صغيرة) أو REF_ (كبيرة)
            if start_arg.startswith("ref_") or start_arg.startswith("REF_"):
                # إزالة البادئة لاستخراج الكود الأصلي
                if start_arg.startswith("ref_"):
                    actual_code = start_arg.replace("ref_", "", 1)
                else:
                    actual_code = start_arg
                
                # البحث عن المستخدم صاحب الكود
                r = db.find_user_by_code(actual_code)
                if r and r.get("user_id") != user.id:
                    referred_by = r.get("user_id")
                    logger.info(f"✅ Referral detected: {user.id} referred by {referred_by} (code: {actual_code})")
                else:
                    logger.warning(f"⚠️ Referral code invalid or self-referral: {actual_code}")

        db_user, is_new = db.register_user(
            user.id, user.first_name or "", user.username or "", referred_by
        )

        if is_new and referred_by:
            settings = db.get_settings()
            rp = settings.get("referral_points", 10)
            db.add_points(referred_by, rp)
            ru = db.get_user(referred_by)
            if ru:
                db.save_user(referred_by, {
                    "total_referrals": ru.get("total_referrals", 0) + 1
                })
            try:
                await context.bot.send_message(
                    referred_by,
                    f"🎉 <b>عضو جديد عبر رابطك!</b>\n💰 +{rp} نقطة",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

        username_str = f"@{user.username}" if user.username else "—"
        await notify_admins(context,
            f"🆕 <b>مستخدم جديد</b>\n"
            f"👤 {esc(user.first_name)}\n"
            f"🔗 {username_str}\n"
            f"🆔 <code>{user.id}</code>\n"
            f"📊 الإحالة: {'✅' if referred_by else '❌'}")

    if db_user.get("is_banned") and not is_admin(user.id):
        await update.message.reply_text("🚫 أنت محظور")
        return

    if args and args[0].startswith("PTS_"):
        ok, amount, msg = db.claim_points_link(args[0], user.id)
        if ok:
            db_user = db.get_user(user.id)
            await update.message.reply_text(
                f"🎉 <b>+{amount} نقطة</b>\n💰 رصيدك: {fmt(db_user.get('points',0))}",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text(msg)

    await show_main_menu(update, context, db_user)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, db_user=None):
    user = update.effective_user
    if db_user is None:
        db_user = db.get_user(user.id) or {}
    points = db_user.get("points", 0)
    refs = db_user.get("total_referrals", 0)
    text = (
        f"👋 <b>أهلاً {esc(user.first_name)}!</b>\n\n"
        f"💰 <b>رصيدك:</b> {fmt(points)} نقطة\n"
        f"👥 <b>إحالاتك:</b> {refs}\n\n"
        f"👇 اختر من القائمة:"
    )
    kb = main_menu_kb(user.id)
    if update.message:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            await update.callback_query.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════
#   Global callbacks
# ═══════════════════════════════════════════════════════════
async def cb_back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await show_main_menu(update, context)


async def cb_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


async def cb_check_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    is_sub, missing = await check_subscription(q.from_user.id, context)
    if is_sub:
        db_user = db.get_user(q.from_user.id)
        if not db_user:
            # ملاحظة: إذا ضغط "تحقق" بدون تسجيل سابق، لن يتم احتساب الإحالة هنا
            # لأن الإحالة تُحسب فقط عند الـ /start الأولي مع arguments
            db_user, _ = db.register_user(
                q.from_user.id, q.from_user.first_name or "", q.from_user.username or ""
            )
        await show_main_menu(update, context, db_user)
    else:
        await q.answer("❌ لم تشترك بعد!", show_alert=True)


# ═══════════════════════════════════════════════════════════
#   Balance / Stats / Referral / Daily
# ═══════════════════════════════════════════════════════════
async def cb_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = db.get_user(q.from_user.id) or {}
    await q.edit_message_text(
        f"💰 <b>رصيدك:</b> {fmt(u.get('points',0))} نقطة",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="back_main")]]),
        parse_mode=ParseMode.HTML,
    )


async def cb_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = db.get_user(q.from_user.id) or {}
    joined = datetime.fromtimestamp(u.get("joined_at", 0))
    await q.edit_message_text(
        f"📊 <b>إحصائياتي</b>\n\n"
        f"💰 النقاط: <b>{fmt(u.get('points',0))}</b>\n"
        f"👥 الإحالات: <b>{u.get('total_referrals',0)}</b>\n"
        f"🔑 المفاتيح: <b>{u.get('total_keys_bought',0)}</b>\n"
        f"📅 الانضمام: {joined.strftime('%Y-%m-%d')}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="back_main")]]),
        parse_mode=ParseMode.HTML,
    )


async def cb_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = db.get_user(q.from_user.id) or {}
    code = u.get("referral_code", "?")
    # ✅ إصلاح: استخدام بادئة ref_ صغيرة بدلاً من REF_ لتجنب مشاكل تيليجرام
    link = f"https://t.me/{context.bot.username}?start=ref_{code}"
    rp = db.get_settings().get("referral_points", 10)
    share = f"https://t.me/share/url?url={link}&text=انضم واكسب نقاط"
    await q.edit_message_text(
        f"👥 <b>دعوة أصدقاء</b>\n\n🔗 <code>{link}</code>\n\n"
        f"📊 إحالاتك: <b>{u.get('total_referrals',0)}</b>\n"
        f"💰 كل صديق = <b>+{rp}</b> نقطة\n"
        f"<i>ملاحظة: يجب أن يضغط صديقك على الرابط ويسجل لأول مرة.</i>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 مشاركة", url=share)],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="back_main")],
        ]),
        parse_mode=ParseMode.HTML,
    )


async def cb_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = db.get_user(q.from_user.id) or {}
    settings = db.get_settings()
    gift = settings.get("daily_gift_points", 20)
    cd = settings.get("daily_gift_cooldown", 86400)
    last = u.get("last_daily_gift", 0)
    now = now_sec()
    diff = now - last

    if last > 0 and diff < cd:
        rem = cd - diff
        await q.edit_message_text(
            f"🎁 <b>الهدية اليومية</b>\n\n❌ استلمت مسبقاً\n\n⏳ المتبقي: <b>{format_short(rem)}</b>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="back_main")]]),
            parse_mode=ParseMode.HTML,
        )
        return

    db.add_points(q.from_user.id, gift)
    db.save_user(q.from_user.id, {"last_daily_gift": now})
    nu = db.get_user(q.from_user.id)
    await q.edit_message_text(
        f"🎉 <b>+{gift} نقطة!</b>\n💰 رصيدك: {fmt(nu.get('points',0))}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="back_main")]]),
        parse_mode=ParseMode.HTML,
    )


# ═══════════════════════════════════════════════════════════
#   Buy Key
# ═══════════════════════════════════════════════════════════
async def cb_buy_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = db.get_user(q.from_user.id) or {}
    points = u.get("points", 0)
    await q.edit_message_text(
        f"🔑 <b>شراء مفتاح</b>\n\n💰 رصيدك: <b>{fmt(points)}</b> نقطة\n\nاختر المدة:",
        reply_markup=buy_key_kb(points),
        parse_mode=ParseMode.HTML,
    )


async def cb_key_buy_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split("_")
    try:
        seconds = int(parts[1])
        cost = int(parts[2])
    except (IndexError, ValueError):
        return

    u = db.get_user(q.from_user.id) or {}
    points = u.get("points", 0)
    if points < cost:
        await q.answer("❌ نقاطك غير كافية", show_alert=True)
        return

    new_points = points - cost
    if not db.save_user(q.from_user.id, {"points": new_points}):
        await q.answer("❌ فشل الخصم", show_alert=True)
        return

    key = db.gen_devil_key()
    now = now_sec()

    key_data = {
        "device_id": None,
        "device_ids": [],
        "max_devices": 1,
        "activated_at": 0,
        "active": True,
        "expiry": seconds,
        "created_by": "BOT",
        "created_at": now,
        "Banned": False,
        "DeviceLimit": 1,
        "Devices": {"dummy": 0},
        "ExpiryDate": (datetime.utcnow() + timedelta(seconds=seconds)).strftime("%Y-%m-%d"),
        "Username": q.from_user.first_name or q.from_user.username or "User",
    }

    if not db.set_key(key, key_data):
        db.save_user(q.from_user.id, {"points": points})
        await q.answer("❌ فشل الإنشاء في Firebase", show_alert=True)
        return

    my_keys = u.get("my_keys", {}) or {}
    my_keys[key] = {"key": key, "duration": seconds, "cost": cost, "bought_at": now}
    db.save_user(q.from_user.id, {
        "total_keys_bought": u.get("total_keys_bought", 0) + 1,
        "my_keys": my_keys,
    })

    username_str = f"@{q.from_user.username}" if q.from_user.username else "—"
    await notify_admins(context,
        f"🔑 <b>شراء مفتاح</b>\n"
        f"👤 {esc(q.from_user.first_name)}\n"
        f"🔗 {username_str}\n"
        f"🆔 <code>{q.from_user.id}</code>\n\n"
        f"🔑 <code>{key}</code>\n"
        f"⏱️ {format_duration(seconds)}\n"
        f"💰 {fmt(cost)} نقطة | 📊 المتبقي: {fmt(new_points)}")

    await q.edit_message_text(
        f"✅ <b>تم!</b>\n\n🔑 <code>{key}</code>\n\n"
        f"⏱️ {format_duration(seconds)}\n"
        f"💰 -{fmt(cost)} نقطة\n"
        f"📊 رصيدك: {fmt(new_points)}",
        reply_markup=key_result_kb(),
        parse_mode=ParseMode.HTML,
    )


async def cb_my_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = db.get_user(q.from_user.id) or {}
    my_keys = u.get("my_keys", {}) or {}
    if not my_keys:
        text = f"💎 <b>مفاتيحك</b>\n\nلا تملك أي مفاتيح.\n💰 رصيدك: <b>{fmt(u.get('points',0))}</b>"
    else:
        keys_list = list(my_keys.values())
        text = f"💎 <b>مفاتيحك ({len(keys_list)})</b>\n\n"
        for k in keys_list[-10:]:
            text += f"🔑 <code>{k.get('key','?')}</code>\n⏱️ {format_duration(k.get('duration',0))}\n\n"
    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="back_main")]]),
        parse_mode=ParseMode.HTML,
    )


# ═══════════════════════════════════════════════════════════
#   Reset
# ═══════════════════════════════════════════════════════════
async def cb_reset_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🔧 <b>ريست مفتاح</b>\n\n"
        "أرسل المفتاح:\n"
        "<code>DEVIL-XXXX-XXXX-XXXX</code>\n"
        "أو <code>DP-XXXX-XXXX</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="back_main")]]),
    )
    context.user_data["awaiting_reset"] = True


async def handle_reset_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_reset"):
        return

    context.user_data["awaiting_reset"] = False
    text = (update.message.text or "").strip().upper()
    uid = update.effective_user.id

    pattern = re.compile(
        r"^(?:DEVIL-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}|DP-[A-Z0-9]{4}-[A-Z0-9]{4})$"
    )
    if not pattern.match(text):
        await update.message.reply_text(
            "❌ صيغة غير صحيحة\n<code>DEVIL-XXXX-XXXX-XXXX</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    kd = db.get_key(text)
    if not kd or not isinstance(kd, dict) or not kd:
        await update.message.reply_text(f"❌ المفتاح غير موجود")
        return

    bypass = ADMIN_BYPASS_RESET and is_admin(uid)
    k_used = u_used = k_rem = u_rem = 0

    if not bypass:
        k_ok, k_used, k_rem, k_wait = db.check_key_limit(text, KEY_MAX_RESETS, KEY_WINDOW_SECONDS)
        if not k_ok:
            await update.message.reply_text(
                f"🚫 تجاوزت حد هذا المفتاح\n"
                f"📊 {k_used}/{KEY_MAX_RESETS}\n"
                f"⏳ {format_short(k_wait)}",
                parse_mode=ParseMode.HTML,
            )
            return

        u_ok, u_used, u_rem, u_wait = db.check_user_limit(uid, USER_MAX_RESETS, USER_WINDOW_SECONDS)
        if not u_ok:
            await update.message.reply_text(
                f"🚫 تجاوزت حدك الشخصي\n"
                f"📊 {u_used}/{USER_MAX_RESETS}\n"
                f"⏳ {format_short(u_wait)}",
                parse_mode=ParseMode.HTML,
            )
            return

    ok, status, snap = db.reset_key_in_fb(text, uid)
    if status == "not_found":
        await update.message.reply_text("❌ غير موجود")
        return
    if status == "already_empty":
        await update.message.reply_text(
            f"ℹ️ لا توجد أجهزة\n⏱️ {snap.get('expiry','')}",
            parse_mode=ParseMode.HTML,
        )
        return
    if status == "save_failed":
        await update.message.reply_text("❌ فشل")
        return

    if not bypass:
        db.add_key_reset_record(text, uid)
        db.add_user_reset_record(uid, text)

    db.log_reset(text, uid, update.effective_user.username or "",
                 update.effective_user.first_name or "", snap.get("old_devices", []))

    user = update.effective_user
    username_str = f"@{user.username}" if user.username else "—"
    bypass_tag = " 👑" if bypass else ""
    notif = (
        f"🔧 <b>عملية ريست</b>{bypass_tag}\n"
        f"👤 {esc(user.first_name)}\n"
        f"🔗 {username_str}\n"
        f"🆔 <code>{uid}</code>\n\n"
        f"🔑 <code>{text}</code>\n"
        f"📱 حذف: {len(snap.get('old_devices',[]))} جهاز"
    )
    await notify_admins(context, notif)

    if bypass:
        limit_note = "👑 أدمن — بدون حد"
    else:
        limit_note = (
            f"🔑 متبقي للمفتاح: {k_rem-1}/{KEY_MAX_RESETS}\n"
            f"👤 متبقي لك: {u_rem-1}/{USER_MAX_RESETS}"
        )

    await update.message.reply_text(
        f"✅ <b>تم الريست!</b>\n\n"
        f"🔑 <code>{text}</code>\n\n"
        f"🗑️ حذف: {len(snap.get('old_devices',[]))} جهاز\n"
        f"⏱️ ينتهي: {snap.get('expiry','')}\n\n"
        f"{limit_note}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ القائمة", callback_data="back_main")
        ]]),
    )


# ═══════════════════════════════════════════════════════════
#   Shop
# ═══════════════════════════════════════════════════════════
async def cb_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    products = db.get_products(active_only=True)
    if not products:
        await q.edit_message_text(
            "🛍️ <b>المتجر</b>\n\n📭 لا توجد منتجات",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="back_main")]]),
            parse_mode=ParseMode.HTML,
        )
        return
    u = db.get_user(q.from_user.id) or {}
    await q.edit_message_text(
        f"🛍️ <b>المتجر</b>\n{cur()} رصيدك: <b>{fmt(u.get('points',0))}</b>\n\n👇 اختر:",
        reply_markup=shop_kb(),
        parse_mode=ParseMode.HTML,
    )


async def cb_shop_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = q.data.replace("shop_view_", "")
    p = db.get_product(pid)
    if not p or not p.get("active", True):
        await q.answer("❌ غير متاح", show_alert=True)
        return
    u = db.get_user(q.from_user.id) or {}
    balance = u.get("points", 0)
    price = p.get("price", 0)
    avail = db.is_product_available(pid)
    if not avail:
        status = "❌ نفدت"
    elif balance >= price:
        status = "✅ يمكنك الشراء"
    else:
        status = f"❌ ينقصك {fmt(price - balance)}"
    await q.edit_message_text(
        f"{p.get('emoji','')} <b>{esc(p.get('name',''))}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 {esc(p.get('description') or '—')}\n\n"
        f"{cur()} <b>السعر:</b> {fmt(price)}\n"
        f"{stock_label(pid)}\n"
        f"💼 <b>رصيدك:</b> {fmt(balance)}\n{status}",
        reply_markup=shop_product_kb(pid),
        parse_mode=ParseMode.HTML,
    )


async def cb_shop_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = q.data.replace("shop_buy_", "")
    p = db.get_product(pid)
    u = db.get_user(q.from_user.id) or {}
    if not p or not p.get("active", True):
        await q.answer("❌ غير متاح", show_alert=True)
        return
    if not db.is_product_available(pid):
        await q.answer("❌ نفدت", show_alert=True)
        return
    price = p.get("price", 0)
    if u.get("points", 0) < price:
        await q.answer(f"❌ ينقصك {fmt(price - u.get('points',0))}", show_alert=True)
        return

    db.add_points(q.from_user.id, -price)
    content = db.get_available_content(pid)
    if not content:
        db.add_points(q.from_user.id, price)
        await q.answer("❌ نفدت", show_alert=True)
        return

    db.increment_sold(pid)
    oid = f"o{int(time.time())}"
    db.add_order(oid, {
        "order_id": oid, "user_id": q.from_user.id, "product_id": pid,
        "product_name": p.get("name", "?"), "price": price, "date": int(time.time()),
    })
    purchases = u.get("purchases", [])
    purchases.append({"pid": pid, "date": int(time.time())})
    db.save_user(q.from_user.id, {
        "purchases": purchases,
        "total_spent": u.get("total_spent", 0) + price,
    })

    ctype = content.get("type", "text")
    data_ = content.get("data", "")
    cap = content.get("caption", "")
    header = f"{p.get('emoji','')} <b>{esc(p.get('name',''))}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
    try:
        if ctype == "text":
            await context.bot.send_message(q.from_user.id, header + data_, parse_mode=ParseMode.HTML)
        elif ctype == "link":
            await context.bot.send_message(q.from_user.id, header + f"🔗 {data_}", parse_mode=ParseMode.HTML)
        elif ctype == "photo":
            await context.bot.send_photo(q.from_user.id, photo=data_,
                caption=(header + cap) if cap else header, parse_mode=ParseMode.HTML)
        elif ctype == "video":
            await context.bot.send_video(q.from_user.id, video=data_,
                caption=(header + cap) if cap else header, parse_mode=ParseMode.HTML)
        elif ctype == "document":
            await context.bot.send_document(q.from_user.id, document=data_,
                caption=(header + cap) if cap else header, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"deliver: {e}")

    nu = db.get_user(q.from_user.id)
    username_str = f"@{q.from_user.username}" if q.from_user.username else "—"
    await notify_admins(context,
        f"🛒 <b>عملية شراء</b>\n"
        f"👤 {esc(q.from_user.first_name)}\n"
        f"🔗 {username_str}\n"
        f"🆔 <code>{q.from_user.id}</code>\n\n"
        f"📦 {p.get('emoji','')} {esc(p.get('name',''))}\n"
        f"💸 {fmt(price)} نقطة\n"
        f"💰 رصيده: {fmt(nu.get('points',0))}")

    proofs = db.get_settings().get("proofs_channel", "")
    if proofs:
        try:
            await context.bot.send_message(proofs,
                f"✅ <b>دليل تسليم</b>\n\n"
                f"📦 {esc(p.get('name',''))}\n"
                f"💰 {fmt(price)} نقطة\n"
                f"👤 {esc(q.from_user.first_name)}",
                parse_mode=ParseMode.HTML)
        except Exception:
            pass

    await q.edit_message_text(
        f"✅ <b>تم الشراء!</b>\n\n"
        f"📦 {p.get('emoji','')} <b>{esc(p.get('name',''))}</b>\n"
        f"💸 {fmt(price)} نقطة\n"
        f"{cur()} رصيدك: <b>{fmt(nu.get('points',0))}</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛍️ المتجر", callback_data="menu_shop")],
            [InlineKeyboardButton("🏠 الرئيسية", callback_data="back_main")],
        ]),
        parse_mode=ParseMode.HTML,
    )


async def cb_purchases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    orders = db.get_user_orders(q.from_user.id)
    if not orders:
        text = "🎒 <b>مشترياتي</b>\n\n📭 لا شيء"
    else:
        text = f"🎒 <b>مشترياتي ({len(orders)})</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        for o in orders[-10:]:
            d = datetime.fromtimestamp(o.get("date", 0)).strftime("%Y-%m-%d %H:%M")
            text += f"📦 <b>{esc(o.get('product_name','?'))}</b>\n   💸 {fmt(o.get('price',0))} | 📅 {d}\n\n"
    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="back_main")]]),
        parse_mode=ParseMode.HTML,
    )


# ═══════════════════════════════════════════════════════════
#   ADMIN PANEL
# ═══════════════════════════════════════════════════════════
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await show_admin_panel(update.message)


async def cb_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    await show_admin_panel(q.message, edit=True)


async def show_admin_panel(msg, edit=False):
    st = db.get_stats()
    mt = check_maintenance()[0]
    text = (
        f"⚙️ <b>لوحة التحكم</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 المستخدمون: <b>{st.get('total_users',0)}</b>\n"
        f"📦 المنتجات: <b>{st.get('total_products',0)}</b>\n"
        f"🛒 المبيعات: <b>{st.get('total_sales',0)}</b>\n"
        f"💎 إجمالي النقاط: <b>{fmt(st.get('total_points_given',0))}</b>\n"
        f"🔧 صيانة البوت: <b>{'🔴 نشطة' if mt else '🟢 معطلة'}</b>"
    )
    if edit:
        try:
            await msg.edit_text(text, reply_markup=admin_kb(), parse_mode=ParseMode.HTML)
        except Exception:
            await msg.reply_text(text, reply_markup=admin_kb(), parse_mode=ParseMode.HTML)
    else:
        await msg.reply_text(text, reply_markup=admin_kb(), parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════
#   Admin: Maintenance
# ═══════════════════════════════════════════════════════════
async def cb_adm_maint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return

    active, m = db.is_bot_in_maintenance()

    text = (
        f"🔧 <b>صيانة البوت</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"الحالة: <b>{'🔴 نشطة' if active else '🟢 معطلة'}</b>\n"
        f"📝 الرسالة:\n<i>{esc(m.get('message','—'))}</i>\n"
    )

    end = m.get("end_time", 0) or 0
    if active and end > 0:
        text += f"\n⏰ تنتهي: <code>{datetime.fromtimestamp(end).strftime('%Y-%m-%d %H:%M')}</code>\n"
    elif active:
        text += "\n⏰ بدون وقت انتهاء\n"

    started = m.get("started_at", 0) or 0
    if active and started > 0:
        text += f"🚀 بدأت: <code>{datetime.fromtimestamp(started).strftime('%Y-%m-%d %H:%M')}</code>\n"

    text += "\n\n💡 هذه الصيانة خاصة بالبوت فقط\n(التطبيق والموقع لهما صيانة منفصلة في Firebase)"

    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🟢 إلغاء الصيانة" if active else "🔴 تفعيل الصيانة",
                callback_data="maint_toggle")],
            [InlineKeyboardButton("✏️ تعديل الرسالة", callback_data="maint_edit")],
            [InlineKeyboardButton("⏰ وقت الانتهاء", callback_data="maint_time")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_panel")],
        ]),
        parse_mode=ParseMode.HTML,
    )


async def cb_maint_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    active, _ = db.is_bot_in_maintenance()
    new_state = not active

    db.set_bot_maintenance(
        active=new_state,
        updated_by=q.from_user.id
    )

    if not new_state:
        db.set_bot_maintenance(end_time=0)

    await q.answer(f"{'🔴 مفعلة' if new_state else '🟢 معطلة'}", show_alert=True)

    try:
        await notify_admins(
            context,
            f"🔧 <b>صيانة البوت</b>\n"
            f"{'🔴 تم التفعيل' if new_state else '🟢 تم الإلغاء'}\n"
            f"👤 بواسطة: {esc(q.from_user.first_name)}"
        )
    except Exception:
        pass

    await cb_adm_maint(update, context)


async def cb_maint_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "✏️ أرسل رسالة الصيانة الجديدة:\n\n"
        "<i>(ستظهر للمستخدمين عند تفعيل الصيانة)</i>",
        reply_markup=cancel_only_kb(),
        parse_mode=ParseMode.HTML,
    )
    return MAINT_MSG


async def maint_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_text = update.message.text.strip()
    db.set_bot_maintenance(
        message=msg_text,
        updated_by=update.effective_user.id
    )
    await update.message.reply_text(
        f"✅ <b>تم تحديث الرسالة</b>\n\n"
        f"📝 <i>{esc(msg_text)}</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔧 الصيانة", callback_data="adm_maint")
        ]]),
    )
    return ConversationHandler.END


async def cb_maint_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "⏰ أرسل المدة بالدقائق:\n\n"
        "<i>(0 = إلغاء وقت الانتهاء — صيانة بدون نهاية)</i>",
        reply_markup=cancel_only_kb(),
        parse_mode=ParseMode.HTML,
    )
    return MAINT_TIME


async def maint_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        minutes = int(update.message.text.strip())
        if minutes < 0: raise ValueError
    except Exception:
        await update.message.reply_text("❌ رقم غير صحيح", reply_markup=cancel_only_kb())
        return MAINT_TIME

    end = int(time.time()) + minutes * 60 if minutes > 0 else 0
    active, _ = db.is_bot_in_maintenance()

    db.set_bot_maintenance(
        end_time=end,
        updated_by=update.effective_user.id
    )

    if minutes > 0:
        end_str = datetime.fromtimestamp(end).strftime('%Y-%m-%d %H:%M')
        await update.message.reply_text(
            f"✅ <b>تم تعيين وقت الانتهاء</b>\n\n"
            f"⏰ <code>{end_str}</code>\n"
            f"📊 الحالة: {'🔴 نشطة' if active else '🟢 معطلة'}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔧 الصيانة", callback_data="adm_maint")
            ]]),
        )
    else:
        await update.message.reply_text(
            "✅ تم إلغاء وقت الانتهاء (صيانة بدون نهاية)",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔧 الصيانة", callback_data="adm_maint")
            ]]),
        )

    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
#   Admin: Channels
# ═══════════════════════════════════════════════════════════
async def cb_adm_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return
    channels = db.get_settings().get("required_channels", [])
    if not isinstance(channels, list):
        channels = []
    text = f"📢 <b>القنوات ({len(channels)})</b>\n\n"
    for i, ch in enumerate(channels, 1):
        text += f"{i}. <b>{esc(ch.get('title','?'))}</b>\n   <code>{ch.get('chat_id','?')}</code>\n\n"
    keyboard = [[InlineKeyboardButton("➕ إضافة قناة", callback_data="add_ch")]]
    for ch in channels:
        keyboard.append([InlineKeyboardButton(
            f"🗑️ حذف {esc(ch.get('title','?'))}",
            callback_data=f"delch_{ch.get('chat_id','')}")])
    keyboard.append([InlineKeyboardButton("⬅️ رجوع", callback_data="admin_panel")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)


async def cb_del_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.data.replace("delch_", "")
    settings = db.get_settings()
    channels = settings.get("required_channels", [])
    new = [c for c in channels if c.get("chat_id") != chat_id]
    db.update_settings({"required_channels": new})
    await q.answer("✅ حذف", show_alert=True)
    await cb_adm_channels(update, context)


async def adm_add_ch_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return ConversationHandler.END
    await q.edit_message_text(
        "➕ أرسل معرّف القناة:\n<code>@username</code> أو <code>-100...</code>",
        reply_markup=cancel_only_kb(),
        parse_mode=ParseMode.HTML,
    )
    return ADD_CH_ID


async def add_ch_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.text.strip()
    context.user_data["new_ch_id"] = chat_id
    try:
        chat = await context.bot.get_chat(chat_id)
        title = chat.title or str(chat_id)
        context.user_data["new_ch_title"] = title
        context.user_data["new_ch_url"] = f"https://t.me/{chat.username}" if chat.username else ""
        await update.message.reply_text(
            f"✅ {esc(title)}\n\n📝 أرسل اسم القناة (أو <code>-</code>):",
            parse_mode=ParseMode.HTML,
            reply_markup=cancel_only_kb(),
        )
        return ADD_CH_TITLE
    except Exception as e:
        await update.message.reply_text(f"❌ {esc(str(e))}")
        return ConversationHandler.END


async def add_ch_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    title = context.user_data.get("new_ch_title", "قناة") if t == "-" else t
    chat_id = context.user_data.get("new_ch_id")
    url = context.user_data.get("new_ch_url", "")

    settings = db.get_settings()
    channels = settings.get("required_channels", [])
    if not isinstance(channels, list):
        channels = []
    for c in channels:
        if c.get("chat_id") == chat_id:
            await update.message.reply_text("⚠️ موجودة مسبقاً")
            return ConversationHandler.END
    channels.append({"chat_id": chat_id, "title": title, "url": url})
    db.update_settings({"required_channels": channels})

    await update.message.reply_text(
        f"✅ <b>تم إضافة:</b> {esc(title)}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📢 القنوات", callback_data="adm_channels")]]),
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
#   Admin: Points
# ═══════════════════════════════════════════════════════════
async def cb_adm_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return
    links = db.get_points_links()
    text = f"💰 <b>إدارة النقاط</b>\n\n📋 روابط نشطة: <b>{len(links)}</b>"
    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 إنشاء رابط نقاط", callback_data="pl_create")],
            [InlineKeyboardButton("📋 قائمة الروابط", callback_data="pl_list")],
            [InlineKeyboardButton("➕ إرسال نقاط", callback_data="adm_give")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_panel")],
        ]),
        parse_mode=ParseMode.HTML,
    )


async def cb_pl_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return
    links = db.get_points_links()
    if not links:
        await q.edit_message_text(
            "📭 لا توجد روابط",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="adm_points")]]),
        )
        return
    text = f"📋 <b>روابط النقاط ({len(links)})</b>\n\n"
    keyboard = []
    for code, link in list(links.items())[:20]:
        valid, reason = db.is_points_link_valid(link)
        status = "🟢" if valid else f"🔴 {reason}"
        text += f"{status} <code>{code}</code> — {fmt(link.get('amount',0))} | {link.get('uses',0)} استخدام\n"
        keyboard.append([InlineKeyboardButton(f"🗑️ {code}", callback_data=f"pl_del_{code}")])
    keyboard.append([InlineKeyboardButton("⬅️ رجوع", callback_data="adm_points")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)


async def cb_pl_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    code = q.data.replace("pl_del_", "")
    db.delete_points_link(code)
    await q.answer("✅ حذف", show_alert=True)
    await cb_pl_list(update, context)


async def adm_pl_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return ConversationHandler.END
    context.user_data["new_pl"] = {}
    await q.edit_message_text(
        "🎁 <b>إنشاء رابط نقاط</b>\n\n💰 أرسل عدد النقاط:",
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_only_kb(),
    )
    return PL_AMOUNT


async def pl_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        am = int(update.message.text.strip())
        if am <= 0: raise ValueError
    except Exception:
        await update.message.reply_text("❌", reply_markup=cancel_only_kb())
        return PL_AMOUNT
    context.user_data["new_pl"]["amount"] = am
    await update.message.reply_text(
        f"✅ {fmt(am)}\n\n👥 أرسل الحد الأقصى (0 = لا نهائي):",
        reply_markup=cancel_only_kb(),
    )
    return PL_MAX_USES


async def pl_max_uses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mu = int(update.message.text.strip())
        if mu < 0: raise ValueError
    except Exception:
        await update.message.reply_text("❌", reply_markup=cancel_only_kb())
        return PL_MAX_USES
    context.user_data["new_pl"]["max_uses"] = mu
    await update.message.reply_text(
        "⏰ أرسل مدة الصلاحية بالساعات (0 = لا نهائي):",
        reply_markup=cancel_only_kb(),
    )
    return PL_EXPIRE_HOURS


async def pl_expire_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        h = int(update.message.text.strip())
        if h < 0: raise ValueError
    except Exception:
        await update.message.reply_text("❌", reply_markup=cancel_only_kb())
        return PL_EXPIRE_HOURS
    data = context.user_data.get("new_pl", {})
    code = db.gen_points_code()
    while db.get_points_link(code):
        code = db.gen_points_code()
    exp = int(time.time()) + h * 3600 if h > 0 else 0
    db.add_points_link(code, {
        "amount": data.get("amount", 0),
        "max_uses": data.get("max_uses", 0),
        "expire_at": exp,
        "created_by": update.effective_user.id,
    })
    link_url = f"https://t.me/{context.bot.username}?start={code}"
    share = f"https://t.me/share/url?url={link_url}&text=احصل على نقاط مجاناً"
    await update.message.reply_text(
        f"✅ <b>تم!</b>\n\n🔗 <code>{link_url}</code>\n\n"
        f"💰 {fmt(data.get('amount',0))} نقطة",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 مشاركة", url=share)],
            [InlineKeyboardButton("📋 القائمة", callback_data="pl_list")],
        ]),
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def adm_give_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return ConversationHandler.END
    await q.edit_message_text(
        "💰 أرسل <b>ID المستخدم</b>:",
        reply_markup=cancel_only_kb(),
        parse_mode=ParseMode.HTML,
    )
    return UP_USER


async def up_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except Exception:
        await update.message.reply_text("❌", reply_markup=cancel_only_kb())
        return UP_USER
    u = db.get_user(uid)
    if not u:
        await update.message.reply_text("❌ غير موجود", reply_markup=cancel_only_kb())
        return UP_USER
    context.user_data["give_uid"] = uid
    await update.message.reply_text(
        f"✅ {esc(u.get('first_name','?'))}\n💰 رصيده: {fmt(u.get('points',0))}\n\nأرسل العدد (سالب للخصم):",
        reply_markup=cancel_only_kb(),
        parse_mode=ParseMode.HTML,
    )
    return UP_AMOUNT


async def up_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        am = int(update.message.text.strip())
    except Exception:
        await update.message.reply_text("❌", reply_markup=cancel_only_kb())
        return UP_AMOUNT
    uid = context.user_data.get("give_uid")
    if not uid: return ConversationHandler.END
    db.add_points(uid, am)
    nu = db.get_user(uid)
    await update.message.reply_text(
        f"✅ {esc(nu.get('first_name','?'))}\n💰 {fmt(nu.get('points',0))}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ اللوحة", callback_data="admin_panel")]]),
        parse_mode=ParseMode.HTML,
    )
    try:
        if am > 0:
            await context.bot.send_message(uid,
                f"🎁 <b>+{fmt(am)} نقطة</b>\n💰 رصيدك: {fmt(nu.get('points',0))}",
                parse_mode=ParseMode.HTML)
    except Exception:
        pass
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
#   Admin: Settings
# ═══════════════════════════════════════════════════════════
async def cb_adm_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return
    s = db.get_settings()
    text = (
        f"⚙️ <b>الإعدادات</b>\n\n"
        f"💰 إحالة: <b>{s.get('referral_points',10)}</b>\n"
        f"🎁 هدية: <b>{s.get('daily_gift_points',20)}</b>\n"
        f"⏰ مدة الهدية: <b>{s.get('daily_gift_cooldown',86400)//3600}</b> ساعة\n"
        f"📞 الدعم: {s.get('support_channel','—')}\n"
        f"📢 الإثباتات: <code>{esc(s.get('proofs_channel','—'))}</code>\n\n"
        f"🔑 <b>أسعار المفاتيح:</b>\n"
    )
    for sec_str, cost in s.get("key_durations", {}).items():
        text += f"• {get_duration_label(int(sec_str))}: <b>{fmt(cost)}</b>\n"

    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 نقاط الإحالة", callback_data="set_referral")],
            [InlineKeyboardButton("🎁 نقاط الهدية", callback_data="set_gift")],
            [InlineKeyboardButton("⏰ مدة الهدية", callback_data="set_cooldown")],
            [InlineKeyboardButton("📢 قناة الإثباتات", callback_data="set_proofs")],
            [InlineKeyboardButton("📞 قناة الدعم", callback_data="set_support")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_panel")],
        ]),
        parse_mode=ParseMode.HTML,
    )


async def cb_set_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    field = q.data.replace("set_", "")
    context.user_data["set_field"] = field
    hints = {
        "referral": "💰 أرسل عدد نقاط الإحالة (رقم)",
        "gift": "🎁 أرسل عدد نقاط الهدية (رقم)",
        "cooldown": "⏰ أرسل مدة الهدية بالساعات",
        "proofs": "📢 أرسل معرّف قناة الإثباتات (أو <code>-</code> لحذفها)",
        "support": "📞 أرسل رابط قناة الدعم",
    }
    await q.edit_message_text(hints.get(field, "أرسل القيمة:"),
                              reply_markup=cancel_only_kb(), parse_mode=ParseMode.HTML)
    return SET_VALUE


async def set_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.text.strip()
    field = context.user_data.get("set_field")
    if not field: return ConversationHandler.END

    mapping = {
        "referral": "referral_points",
        "gift": "daily_gift_points",
        "cooldown": "daily_gift_cooldown",
        "proofs": "proofs_channel",
        "support": "support_channel",
    }
    k = mapping.get(field)

    if field in ("referral", "gift"):
        try:
            v = int(v)
            if v < 0: raise ValueError
        except Exception:
            await update.message.reply_text("❌", reply_markup=cancel_only_kb())
            return SET_VALUE
    elif field == "cooldown":
        try:
            hours = int(v)
            if hours < 1: raise ValueError
            v = hours * 3600
        except Exception:
            await update.message.reply_text("❌", reply_markup=cancel_only_kb())
            return SET_VALUE
    elif field == "proofs":
        if v == "-":
            db.update_settings({k: ""})
            await update.message.reply_text("✅ تم الحذف")
            return ConversationHandler.END
        try:
            test = await context.bot.send_message(v, "🧪 اختبار", parse_mode=ParseMode.HTML)
            await asyncio.sleep(2)
            try:
                await context.bot.delete_message(v, test.message_id)
            except Exception:
                pass
        except Exception as e:
            await update.message.reply_text(f"❌ {esc(str(e))}")
            return SET_VALUE

    db.update_settings({k: v})
    await update.message.reply_text("✅ تم")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
#   Admin: Products
# ═══════════════════════════════════════════════════════════
async def cb_adm_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return
    products = db.get_products(active_only=False)
    if not products:
        await q.edit_message_text(
            "📭 لا توجد منتجات",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ إضافة", callback_data="adm_add_p")],
                [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_panel")],
            ]),
        )
        return
    keyboard = []
    for pid, p in products.items():
        active = "🟢" if p.get("active", True) else "🔴"
        keyboard.append([InlineKeyboardButton(
            f"{active} {p.get('emoji','')} {p.get('name','?')}",
            callback_data=f"editp_{pid}")])
    keyboard.append([InlineKeyboardButton("➕ منتج جديد", callback_data="adm_add_p")])
    keyboard.append([InlineKeyboardButton("⬅️ رجوع", callback_data="admin_panel")])
    await q.edit_message_text(
        f"📦 <b>المنتجات ({len(products)})</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
    )


async def cb_edit_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return ConversationHandler.END
    pid = q.data.replace("editp_", "")
    p = db.get_product(pid)
    if not p:
        await q.answer("❌", show_alert=True)
        return ConversationHandler.END
    context.user_data["edit_pid"] = pid
    mode = "single" if p.get("delivery_mode", "single") == "single" else "multi"
    text = (
        f"✏️ <b>{p.get('emoji','')} {esc(p.get('name',''))}</b>\n"
        f"💰 {fmt(p.get('price',0))}\n"
        f"🎯 {'♾️ لا نهائي' if mode=='single' else '📚 متعدد'}\n"
        f"{stock_label(pid)}"
    )
    keyboard = [
        [InlineKeyboardButton("📝 الاسم", callback_data="epf_name"),
         InlineKeyboardButton("😀 الإيموجي", callback_data="epf_emoji")],
        [InlineKeyboardButton("📄 الوصف", callback_data="epf_desc"),
         InlineKeyboardButton("💰 السعر", callback_data="epf_price")],
    ]
    if mode == "multi":
        keyboard.append([InlineKeyboardButton("📦 إدارة المحتوى", callback_data=f"mngc_{pid}")])
    else:
        keyboard.append([InlineKeyboardButton("📦 تعديل المحتوى", callback_data="epf_content")])
    keyboard += [
        [InlineKeyboardButton("🔄 تفعيل/تعطيل", callback_data=f"togglep_{pid}")],
        [InlineKeyboardButton("🗑️ حذف", callback_data=f"delp_{pid}")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="adm_products")],
    ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return PE_VALUE


async def cb_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    field = q.data.replace("epf_", "")
    context.user_data["edit_field"] = field
    names = {"name": "الاسم", "emoji": "الإيموجي", "desc": "الوصف",
             "price": "السعر", "content": "المحتوى"}
    await q.edit_message_text(
        f"✏️ أرسل {names.get(field, field)} الجديد:",
        reply_markup=cancel_only_kb(),
        parse_mode=ParseMode.HTML,
    )
    return PE_VALUE


async def pe_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.text.strip()
    field = context.user_data.get("edit_field")
    pid = context.user_data.get("edit_pid")
    if not field or not pid:
        return ConversationHandler.END
    if field == "price":
        try:
            v = int(v)
            if v < 0: raise ValueError
        except Exception:
            await update.message.reply_text("❌", reply_markup=cancel_only_kb())
            return PE_VALUE
    db.update_product(pid, {field: v})
    await update.message.reply_text(
        "✅ تم",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ تعديل المزيد", callback_data=f"editp_{pid}")],
            [InlineKeyboardButton("📦 المنتجات", callback_data="adm_products")],
        ]),
    )
    return ConversationHandler.END


async def cb_toggle_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    pid = q.data.replace("togglep_", "")
    p = db.get_product(pid)
    if not p:
        await q.answer("❌", show_alert=True)
        return
    db.update_product(pid, {"active": not p.get("active", True)})
    await q.answer("✅ تبديل")
    await cb_edit_product(update, context)


async def cb_delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = q.data.replace("delp_", "")
    p = db.get_product(pid)
    if not p: return
    db.backup()
    db.delete_product(pid)
    await q.edit_message_text(
        f"✅ حذف {esc(p.get('name','?'))}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦", callback_data="adm_products")]]),
        parse_mode=ParseMode.HTML,
    )


# ═══════════════════════════════════════════════════════════
#   Add Product (conversation)
# ═══════════════════════════════════════════════════════════
async def adm_add_p_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return ConversationHandler.END
    context.user_data["new_p"] = {}
    await q.edit_message_text(
        "➕ <b>منتج جديد — 1/6</b>\n\n📝 اسم المنتج:",
        reply_markup=cancel_only_kb(),
        parse_mode=ParseMode.HTML,
    )
    return P_NAME


async def p_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if not t: return P_NAME
    context.user_data["new_p"]["name"] = t
    await update.message.reply_text(
        f"✅ {esc(t)}\n\n😀 <b>2/6</b> — الإيموجي (أو <code>-</code>):",
        reply_markup=cancel_only_kb(),
        parse_mode=ParseMode.HTML,
    )
    return P_EMOJI


async def p_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    context.user_data["new_p"]["emoji"] = "📦" if t == "-" else t
    await update.message.reply_text(
        "✅\n\n📄 <b>3/6</b> — الوصف (أو <code>-</code>):",
        reply_markup=cancel_only_kb(),
    )
    return P_DESC


async def p_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    context.user_data["new_p"]["description"] = "" if t == "-" else t
    await update.message.reply_text(
        "✅\n\n💰 <b>4/6</b> — السعر:",
        reply_markup=cancel_only_kb(),
    )
    return P_PRICE


async def p_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        p = int(update.message.text.strip())
        if p < 0: raise ValueError
    except Exception:
        await update.message.reply_text("❌", reply_markup=cancel_only_kb())
        return P_PRICE
    context.user_data["new_p"]["price"] = p
    await update.message.reply_text(
        f"✅ {fmt(p)}\n\n🎯 <b>5/6</b> — نوع التسليم:",
        reply_markup=cancel_kb([
            [InlineKeyboardButton("♾️ محتوى واحد", callback_data="pmode_single")],
            [InlineKeyboardButton("📚 محتوى متعدد", callback_data="pmode_multi")],
        ]),
        parse_mode=ParseMode.HTML,
    )
    return P_MODE


async def p_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    mode = "single" if q.data == "pmode_single" else "multi"
    context.user_data["new_p"]["delivery_mode"] = mode
    prefix = "pct_" if mode == "single" else "mct_"
    await q.edit_message_text(
        f"✅ {'♾️' if mode=='single' else '📚'}\n\n📦 <b>6/6</b> — نوع المحتوى الأول:",
        reply_markup=cancel_kb([
            [InlineKeyboardButton("📝 نص", callback_data=f"{prefix}text"),
             InlineKeyboardButton("🔗 رابط", callback_data=f"{prefix}link")],
            [InlineKeyboardButton("📸 صورة", callback_data=f"{prefix}photo"),
             InlineKeyboardButton("🎬 فيديو", callback_data=f"{prefix}video")],
            [InlineKeyboardButton("📎 ملف", callback_data=f"{prefix}document")],
        ]),
        parse_mode=ParseMode.HTML,
    )
    return P_FIRST_CONTENT


async def p_first_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q and (q.data.startswith("pct_") or q.data.startswith("mct_")):
        await q.answer()
        prefix = "pct_" if q.data.startswith("pct_") else "mct_"
        ctype = q.data.replace(prefix, "")
        context.user_data["first_ctype"] = ctype
        hints = {"text": "📝", "link": "🔗", "photo": "📸", "video": "🎬", "document": "📎"}
        await q.edit_message_text(
            f"{hints.get(ctype, '')} أرسل المحتوى:",
            reply_markup=cancel_only_kb(),
        )
        return P_FIRST_CONTENT

    msg = update.message
    data = context.user_data.get("new_p", {})
    ctype = context.user_data.get("first_ctype")
    mode = data.get("delivery_mode", "single")
    cd, cap = "", ""
    if ctype in ("text", "link"):
        cd = msg.text or ""
    elif ctype == "photo" and msg.photo:
        cd = msg.photo[-1].file_id; cap = msg.caption or ""
    elif ctype == "video" and msg.video:
        cd = msg.video.file_id; cap = msg.caption or ""
    elif ctype == "document" and msg.document:
        cd = msg.document.file_id; cap = msg.caption or ""

    if not cd:
        await msg.reply_text("❌", reply_markup=cancel_only_kb())
        return P_FIRST_CONTENT

    if mode == "single":
        data["content"] = {"type": ctype, "data": cd}
        if cap: data["content"]["caption"] = cap
        data["contents"] = []
    else:
        item = {"type": ctype, "data": cd}
        if cap: item["caption"] = cap
        data["contents"] = [item]
        data["content"] = {}
    data["active"] = True
    pid = f"p{int(time.time())}"
    db.add_product(pid, data)

    if mode == "single":
        await msg.reply_text(
            f"✅ <b>تم!</b>\n\n{data.get('emoji','')} <b>{esc(data.get('name',''))}</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ آخر", callback_data="adm_add_p")],
                [InlineKeyboardButton("📦 المنتجات", callback_data="adm_products")],
            ]),
            parse_mode=ParseMode.HTML,
        )
    else:
        await msg.reply_text(
            f"✅ <b>تم!</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ إضافة عناصر", callback_data=f"addc_{pid}")],
                [InlineKeyboardButton("📦 المنتجات", callback_data="adm_products")],
            ]),
            parse_mode=ParseMode.HTML,
        )
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
#   Manage content (multi)
# ═══════════════════════════════════════════════════════════
async def cb_mngc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = q.data.replace("mngc_", "")
    p = db.get_product(pid)
    if not p: return ConversationHandler.END
    context.user_data["mng_pid"] = pid
    contents = p.get("contents", [])
    keyboard = []
    for i, c in enumerate(contents[:20]):
        ctype = c.get("type", "text")
        preview = (c.get("data", "")[:20] if ctype == "text" else ctype)
        keyboard.append([InlineKeyboardButton(
            f"🗑️ #{i+1} {preview}", callback_data=f"delc_{i}")])
    keyboard.append([InlineKeyboardButton("➕ إضافة", callback_data=f"addc_{pid}")])
    keyboard.append([InlineKeyboardButton("⬅️ رجوع", callback_data=f"editp_{pid}")])
    sold = p.get("sold_count", 0)
    rem = max(0, len(contents) - sold)
    await q.edit_message_text(
        f"📦 <b>{esc(p.get('name','?'))}</b>\n📚 {len(contents)} | 🛒 {sold} | 📊 {rem}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
    )
    return PE_VALUE


async def cb_delc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    idx = int(q.data.replace("delc_", ""))
    pid = context.user_data.get("mng_pid")
    if pid:
        db.remove_content_from_product(pid, idx)
    await cb_mngc(update, context)
    return PE_VALUE


async def cb_addc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = q.data.replace("addc_", "")
    context.user_data["addc_pid"] = pid
    await q.edit_message_text(
        "➕ اختر النوع:",
        reply_markup=cancel_kb([
            [InlineKeyboardButton("📝 نص", callback_data="ctext_text"),
             InlineKeyboardButton("🔗 رابط", callback_data="ctext_link")],
            [InlineKeyboardButton("📸 صورة", callback_data="ctext_photo"),
             InlineKeyboardButton("🎬 فيديو", callback_data="ctext_video")],
            [InlineKeyboardButton("📎 ملف", callback_data="ctext_document")],
        ]),
        parse_mode=ParseMode.HTML,
    )
    return AC_CONTENT


async def ac_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q and q.data.startswith("ctext_"):
        await q.answer()
        ctype = q.data.replace("ctext_", "")
        context.user_data["ac_type"] = ctype
        await q.edit_message_text("أرسل المحتوى:", reply_markup=cancel_only_kb())
        return AC_CONTENT

    msg = update.message
    pid = context.user_data.get("addc_pid")
    ctype = context.user_data.get("ac_type")
    if not pid or not ctype: return ConversationHandler.END
    data, cap = "", ""
    if ctype in ("text", "link"):
        data = msg.text or ""
    elif ctype == "photo" and msg.photo:
        data = msg.photo[-1].file_id; cap = msg.caption or ""
    elif ctype == "video" and msg.video:
        data = msg.video.file_id; cap = msg.caption or ""
    elif ctype == "document" and msg.document:
        data = msg.document.file_id; cap = msg.caption or ""
    if not data:
        await msg.reply_text("❌", reply_markup=cancel_only_kb())
        return AC_CONTENT
    item = {"type": ctype, "data": data}
    if cap: item["caption"] = cap
    db.add_content_to_product(pid, item)
    p = db.get_product(pid)
    await msg.reply_text(
        f"✅ تم\n📚 إجمالي: {len(p.get('contents',[]))}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ آخر", callback_data=f"addc_{pid}")],
            [InlineKeyboardButton("📦 إدارة", callback_data=f"mngc_{pid}")],
        ]),
    )
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
#   Admin: Users / Stats / Backup / Broadcast
# ═══════════════════════════════════════════════════════════
async def cb_adm_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return
    top = db.get_top_users(20)
    text = "👥 <b>أفضل 20</b>\n\n"
    for i, u in enumerate(top, 1):
        text += f"{i}. {esc(u.get('first_name','?'))} — {fmt(u.get('points',0))} 💰 | {u.get('total_referrals',0)} 👥\n"
    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="admin_panel")]]),
        parse_mode=ParseMode.HTML,
    )


async def cb_adm_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return
    st = db.get_stats()
    text = (
        f"📊 <b>الإحصائيات</b>\n\n"
        f"👥 المستخدمون: <b>{st.get('total_users',0)}</b>\n"
        f"📦 المنتجات: <b>{st.get('total_products',0)}</b>\n"
        f"🛒 المبيعات: <b>{st.get('total_sales',0)}</b>\n"
        f"💎 النقاط: <b>{fmt(st.get('total_points_given',0))}</b>"
    )
    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="admin_panel")]]),
        parse_mode=ParseMode.HTML,
    )


async def cb_adm_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    path = db.backup()
    await q.edit_message_text(
        f"✅ <b>نسخة</b>\n<code>{path}</code>" if path else "❌ فشل",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="admin_panel")]]),
        parse_mode=ParseMode.HTML,
    )


async def cb_adm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return ConversationHandler.END
    await q.edit_message_text(
        "📣 أرسل نص الرسالة للبث:",
        reply_markup=cancel_only_kb(),
        parse_mode=ParseMode.HTML,
    )
    return BC_TEXT


async def bc_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    users = db.get_all_users()
    await update.message.reply_text(f"📤 جاري الإرسال لـ {len(users)}...")
    ok, fl = 0, 0
    for u in users.values():
        try:
            await context.bot.send_message(u.get("user_id"),
                f"📢 <b>إعلان</b>\n\n{text}", parse_mode=ParseMode.HTML)
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            fl += 1
    await update.message.reply_text(f"✅ {ok} | ❌ {fl}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️", callback_data="admin_panel")]]))
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
#   Error / Main
# ═══════════════════════════════════════════════════════════
async def error_handler(update, context):
    logger.error("Exception:", exc_info=context.error)


def main():
    logger.info("🔥 Starting DEVIL MASTER BOT...")
    db.load()

    app = Application.builder().token(BOT_TOKEN).build()

    # ─── Commands
    app.add_handler(CommandHandler("start", cmd_start), group=0)
    app.add_handler(CommandHandler("admin", cmd_admin), group=0)

    # ─── Global callbacks
    app.add_handler(CallbackQueryHandler(cb_cancel_conv, pattern="^cancel_conv$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_back_main, pattern="^back_main$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_noop, pattern="^noop$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_check_sub, pattern="^check_sub$"), group=0)

    # ─── User
    app.add_handler(CallbackQueryHandler(cb_balance, pattern="^menu_balance$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_stats, pattern="^menu_stats$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_referral, pattern="^menu_referral$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_daily, pattern="^menu_daily$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_buy_key, pattern="^menu_buy_key$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_key_buy_confirm, pattern="^keybuy_"), group=0)
    app.add_handler(CallbackQueryHandler(cb_my_keys, pattern="^menu_my_keys$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_reset_key, pattern="^menu_reset_key$"), group=0)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reset_message), group=0)

    # ─── Shop
    app.add_handler(CallbackQueryHandler(cb_shop, pattern="^menu_shop$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_shop_view, pattern="^shop_view_"), group=0)
    app.add_handler(CallbackQueryHandler(cb_shop_buy, pattern="^shop_buy_"), group=0)
    app.add_handler(CallbackQueryHandler(cb_purchases, pattern="^menu_purchases$"), group=0)

    # ─── Admin callbacks
    app.add_handler(CallbackQueryHandler(cb_admin_panel, pattern="^admin_panel$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_adm_maint, pattern="^adm_maint$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_maint_toggle, pattern="^maint_toggle$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_adm_channels, pattern="^adm_channels$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_del_channel, pattern="^delch_"), group=0)
    app.add_handler(CallbackQueryHandler(cb_adm_points, pattern="^adm_points$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_pl_list, pattern="^pl_list$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_pl_del, pattern="^pl_del_"), group=0)
    app.add_handler(CallbackQueryHandler(cb_adm_settings, pattern="^adm_settings$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_adm_products, pattern="^adm_products$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_toggle_product, pattern="^togglep_"), group=0)
    app.add_handler(CallbackQueryHandler(cb_delete_product, pattern="^delp_"), group=0)
    app.add_handler(CallbackQueryHandler(cb_adm_users, pattern="^adm_users$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_adm_stats, pattern="^adm_stats$"), group=0)
    app.add_handler(CallbackQueryHandler(cb_adm_backup, pattern="^adm_backup$"), group=0)

    # ─── Conversations
    add_p_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_add_p_start, pattern="^adm_add_p$")],
        states={
            P_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_name)],
            P_EMOJI: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_emoji)],
            P_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_desc)],
            P_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_price)],
            P_MODE: [CallbackQueryHandler(p_mode, pattern="^pmode_")],
            P_FIRST_CONTENT: [
                CallbackQueryHandler(p_first_content, pattern="^(pct_|mct_)"),
                MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL,
                               p_first_content),
            ],
        },
        fallbacks=[CallbackQueryHandler(cb_cancel_conv, pattern="^cancel_conv$")],
        per_message=False, name="add_p",
    )

    add_c_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_addc, pattern="^addc_")],
        states={
            AC_CONTENT: [
                CallbackQueryHandler(ac_content, pattern="^ctext_"),
                MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL,
                               ac_content),
            ],
        },
        fallbacks=[CallbackQueryHandler(cb_cancel_conv, pattern="^cancel_conv$")],
        per_message=False, name="add_c",
    )

    edit_p_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_edit_product, pattern="^editp_"),
            CallbackQueryHandler(cb_mngc, pattern="^mngc_"),
        ],
        states={
            PE_VALUE: [
                CallbackQueryHandler(cb_edit_field, pattern="^epf_"),
                CallbackQueryHandler(cb_mngc, pattern="^mngc_"),
                CallbackQueryHandler(cb_delc, pattern="^delc_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, pe_value),
            ],
        },
        fallbacks=[CallbackQueryHandler(cb_cancel_conv, pattern="^cancel_conv$")],
        per_message=False, name="edit_p",
    )

    give_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_give_start, pattern="^adm_give$")],
        states={
            UP_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, up_user)],
            UP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, up_amount)],
        },
        fallbacks=[CallbackQueryHandler(cb_cancel_conv, pattern="^cancel_conv$")],
        per_message=False, name="give",
    )

    bc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_adm_broadcast, pattern="^adm_broadcast$")],
        states={BC_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, bc_text)]},
        fallbacks=[CallbackQueryHandler(cb_cancel_conv, pattern="^cancel_conv$")],
        per_message=False, name="bc",
    )

    maint_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_maint_edit, pattern="^maint_edit$"),
            CallbackQueryHandler(cb_maint_time, pattern="^maint_time$"),
        ],
        states={
            MAINT_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, maint_msg)],
            MAINT_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, maint_time)],
        },
        fallbacks=[CallbackQueryHandler(cb_cancel_conv, pattern="^cancel_conv$")],
        per_message=False, name="maint",
    )

    set_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_set_field, pattern="^set_")],
        states={SET_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_value)]},
        fallbacks=[CallbackQueryHandler(cb_cancel_conv, pattern="^cancel_conv$")],
        per_message=False, name="set",
    )

    ch_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_add_ch_start, pattern="^add_ch$")],
        states={
            ADD_CH_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_ch_id)],
            ADD_CH_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_ch_title)],
        },
        fallbacks=[CallbackQueryHandler(cb_cancel_conv, pattern="^cancel_conv$")],
        per_message=False, name="add_ch",
    )

    pl_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_pl_create_start, pattern="^pl_create$")],
        states={
            PL_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pl_amount)],
            PL_MAX_USES: [MessageHandler(filters.TEXT & ~filters.COMMAND, pl_max_uses)],
            PL_EXPIRE_HOURS: [MessageHandler(filters.TEXT & ~filters.COMMAND, pl_expire_hours)],
        },
        fallbacks=[CallbackQueryHandler(cb_cancel_conv, pattern="^cancel_conv$")],
        per_message=False, name="pl",
    )

    app.add_handler(add_p_conv, group=1)
    app.add_handler(add_c_conv, group=1)
    app.add_handler(edit_p_conv, group=1)
    app.add_handler(give_conv, group=1)
    app.add_handler(bc_conv, group=1)
    app.add_handler(maint_conv, group=1)
    app.add_handler(set_conv, group=1)
    app.add_handler(ch_conv, group=1)
    app.add_handler(pl_conv, group=1)

    app.add_error_handler(error_handler)

    logger.info("✅ Bot is ready!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()