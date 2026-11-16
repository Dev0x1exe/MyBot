import os
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════
#   Bot
# ═══════════════════════════════════════════════════════════
BOT_TOKEN = os.getenv("BOT_TOKEN", "8970262464:AAFOtFCLt5rBZHXelw93Q1u9QN28jDL_9RY").strip()
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN مفقود! ضعه في .env")

# ═══════════════════════════════════════════════════════════
#   Admins
# ═══════════════════════════════════════════════════════════
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "6861802815")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]
if not ADMIN_IDS:
    raise ValueError("❌ ADMIN_IDS مفقود!")

SUPPORT_CHANNEL = os.getenv("SUPPORT_CHANNEL", "https://t.me/devilxitofc")

# ═══════════════════════════════════════════════════════════
#   🔥 Val Town Gateway (X-Access-Key)
# ═══════════════════════════════════════════════════════════
PROXY_URL = os.getenv(
    "PROXY_URL",
    "https://devilxit--f5db6daad50711f1bcb71607ee4eb77e.web.val.run"
).strip()

ACCESS_KEY = os.getenv("ACCESS_KEY", "DevilXitVal").strip()
if not ACCESS_KEY:
    raise ValueError("❌ ACCESS_KEY مفقود!")

# ═══════════════════════════════════════════════════════════
#   Referral & Keys
# ═══════════════════════════════════════════════════════════
REFERRAL_POINTS = int(os.getenv("REFERRAL_POINTS", "3"))
DAILY_GIFT_POINTS = int(os.getenv("DAILY_GIFT_POINTS", "2"))

DEFAULT_KEY_DURATIONS = {
    "3600": 2,      # 1 ساعة
    "10800": 4,     # 3 ساعات
    "21600": 7,     # 6 ساعات
    "43200": 12,    # 12 ساعة
    "86400": 16,    # 24 ساعة
}

# ═══════════════════════════════════════════════════════════
#   Reset Limits
# ═══════════════════════════════════════════════════════════
KEY_MAX_RESETS = 2
KEY_WINDOW_SECONDS = 12 * 3600
USER_MAX_RESETS = 2
USER_WINDOW_SECONDS = 12 * 3600
ADMIN_BYPASS_RESET = True

# ═══════════════════════════════════════════════════════════
#   Local Data
# ═══════════════════════════════════════════════════════════
DATA_FILE = "data.json"