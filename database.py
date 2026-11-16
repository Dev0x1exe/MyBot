"""
💾 قاعدة بيانات موحدة
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ كل شيء محلي في data.json
🔥 Firebase يُستخدم فقط في keys/
"""

import json
import os
import random
import string
import shutil
import threading
import time
from datetime import datetime
import urllib3

import requests

from config import (
    DATA_FILE,
    DEFAULT_KEY_DURATIONS, REFERRAL_POINTS, DAILY_GIFT_POINTS,
    PROXY_URL, ACCESS_KEY,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LOCK = threading.RLock()

# ═══════════════════════════════════════════════════════════
#   🔥 Val Town Proxy
# ═══════════════════════════════════════════════════════════
class Firebase:
    def __init__(self, proxy_url, access_key, timeout=15):
        self.proxy_url = proxy_url.rstrip("/")
        self.access_key = access_key
        self.timeout = timeout

    def _build_url(self, path):
        return f"{self.proxy_url}/{path}.json" if path else f"{self.proxy_url}/.json"

    def _request(self, method, path, data=None):
        url = self._build_url(path)
        headers = {"X-Access-Key": self.access_key, "Content-Type": "application/json"}
        actual_method = method
        if method == "PUT":
            actual_method = "POST"
            headers["X-HTTP-Method-Override"] = "PUT"
        elif method == "DELETE":
            actual_method = "POST"
            headers["X-HTTP-Method-Override"] = "DELETE"
        try:
            if actual_method in ["POST", "PUT", "PATCH"]:
                r = requests.request(actual_method, url, headers=headers, json=data,
                                     timeout=self.timeout, verify=False)
            else:
                r = requests.request(actual_method, url, headers=headers,
                                     timeout=self.timeout, verify=False)
            if r.status_code == 200:
                if method == "GET":
                    return r.json() if r.text else None
                return True
            print(f"❌ Proxy error ({method} {path}): {r.status_code} {r.text[:100]}")
            return False if method != "GET" else None
        except Exception as e:
            print(f"❌ Request error ({method} {path}): {e}")
            return False if method != "GET" else None

    def get(self, path=""): return self._request("GET", path)
    def set(self, path, data): return self._request("PUT", path, data)
    def update(self, path, data): return self._request("PATCH", path, data)
    def delete(self, path): return self._request("DELETE", path)


fb = Firebase(PROXY_URL, ACCESS_KEY)

# ═══════════════════════════════════════════════════════════
#   Default data.json
# ═══════════════════════════════════════════════════════════
DEFAULT_DATA = {
    "settings": {
        "referral_points": REFERRAL_POINTS,
        "daily_gift_points": DAILY_GIFT_POINTS,
        "daily_gift_cooldown": 86400,
        "key_durations": DEFAULT_KEY_DURATIONS,
        "support_channel": "https://t.me/devilxitteam",
        "proofs_channel": "",
        "required_channels": [],
        "currency_emoji": "💰",
    },
    "bot_maintenance": {
        "active": False,
        "message": "⚠️ البوت تحت الصيانة\nسنعود قريباً...",
        "end_time": 0, "started_at": 0, "updated_at": 0, "updated_by": 0,
    },
    "users": {},
    "products": {},
    "orders": {},
    "points_links": {},
    "reset_logs": {},
    "key_reset_history": {},
    "user_reset_history": {},
    "referral_codes": {},
    "pending_starts": {},          # ← جديد
    "stats": {"total_sales": 0, "total_points_given": 0},
}

# ═══════════════════════════════════════════════════════════
#   Core: load / save
# ═══════════════════════════════════════════════════════════
def _load_local() -> dict:
    if not os.path.exists(DATA_FILE):
        _save_local(json.loads(json.dumps(DEFAULT_DATA)))
        return json.loads(json.dumps(DEFAULT_DATA))
    try:
        with LOCK:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        for k, v in DEFAULT_DATA.items():
            if k not in data:
                data[k] = json.loads(json.dumps(v))
        for sk, sv in DEFAULT_DATA["settings"].items():
            if sk not in data.get("settings", {}):
                data.setdefault("settings", {})[sk] = sv
        data["settings"]["key_durations"] = DEFAULT_KEY_DURATIONS
        if "bot_maintenance" not in data or not isinstance(data["bot_maintenance"], dict):
            data["bot_maintenance"] = dict(DEFAULT_DATA["bot_maintenance"])
        if "pending_starts" not in data or not isinstance(data["pending_starts"], dict):
            data["pending_starts"] = {}
        return data
    except Exception as e:
        print(f"❌ _load_local error: {e}")
        return json.loads(json.dumps(DEFAULT_DATA))


def _save_local(data: dict) -> bool:
    try:
        with LOCK:
            tmp = DATA_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, DATA_FILE)
        return True
    except Exception as e:
        print(f"❌ _save_local error: {e}")
        return False


def load() -> dict: return _load_local()
def save(data: dict) -> bool: return _save_local(data)


def backup() -> str:
    if not os.path.exists(DATA_FILE): return ""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"data_backup_{ts}.json"
    try:
        shutil.copy2(DATA_FILE, name)
        return name
    except Exception:
        return ""

# ═══════════════════════════════════════════════════════════
#   🔧 Bot Maintenance
# ═══════════════════════════════════════════════════════════
def get_bot_maintenance() -> dict:
    data = _load_local()
    m = data.get("bot_maintenance", {})
    if not isinstance(m, dict):
        m = dict(DEFAULT_DATA["bot_maintenance"])
    end = m.get("end_time", 0) or 0
    if end > 0 and int(time.time()) > end:
        m["active"] = False
        m["end_time"] = 0
        data["bot_maintenance"] = m
        _save_local(data)
    return {
        "active": m.get("active", False),
        "message": m.get("message", DEFAULT_DATA["bot_maintenance"]["message"]),
        "end_time": m.get("end_time", 0) or 0,
        "started_at": m.get("started_at", 0) or 0,
        "updated_at": m.get("updated_at", 0) or 0,
        "updated_by": m.get("updated_by", 0) or 0,
    }


def set_bot_maintenance(active=None, message=None, end_time=None, updated_by=None) -> bool:
    with LOCK:
        data = _load_local()
        if "bot_maintenance" not in data or not isinstance(data["bot_maintenance"], dict):
            data["bot_maintenance"] = dict(DEFAULT_DATA["bot_maintenance"])
        m = data["bot_maintenance"]
        if active is not None:
            m["active"] = bool(active)
            if active:
                m["started_at"] = int(time.time())
        if message is not None: m["message"] = message
        if end_time is not None: m["end_time"] = int(end_time)
        if updated_by is not None: m["updated_by"] = int(updated_by)
        m["updated_at"] = int(time.time())
        data["bot_maintenance"] = m
        return _save_local(data)


def is_bot_in_maintenance() -> tuple:
    m = get_bot_maintenance()
    return m.get("active", False), m

# ═══════════════════════════════════════════════════════════
#   Settings
# ═══════════════════════════════════════════════════════════
def get_settings() -> dict:
    data = _load_local()
    s = dict(data.get("settings", {}))
    for k, v in DEFAULT_DATA["settings"].items():
        if k not in s: s[k] = v
    return s


def update_settings(updates: dict) -> bool:
    with LOCK:
        data = _load_local()
        data.setdefault("settings", {}).update(updates)
        return _save_local(data)

# ═══════════════════════════════════════════════════════════
#   Users
# ═══════════════════════════════════════════════════════════
def gen_ref_code() -> str:
    return "REF_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def get_user(uid: int) -> dict:
    return _load_local().get("users", {}).get(str(uid), {})


def get_all_users() -> dict:
    return _load_local().get("users", {})


def find_user_by_code(code: str) -> dict:
    data = _load_local()
    uid = data.get("referral_codes", {}).get(code)
    if uid:
        return data.get("users", {}).get(str(uid), {})
    return {}


def register_user(uid: int, first_name: str, username: str = "", referred_by=None):
    with LOCK:
        data = _load_local()
        users = data.setdefault("users", {})
        uid_str = str(uid)
        if uid_str in users:
            return users[uid_str], False

        index = data.setdefault("referral_codes", {})
        code = gen_ref_code()
        attempts = 0
        while code in index and attempts < 100:
            code = gen_ref_code()
            attempts += 1

        user = {
            "user_id": uid,
            "first_name": first_name,
            "username": username,
            "points": 0,
            "referral_code": code,
            "referred_by": referred_by,
            "total_referrals": 0,
            "joined_at": int(time.time()),
            "last_gift": 0,
            "last_daily_gift": 0,
            "total_keys_bought": 0,
            "my_keys": {},
            "purchases": [],
            "total_spent": 0,
            "is_banned": False,
        }
        users[uid_str] = user
        index[code] = uid
        _save_local(data)
        return user, True


def save_user(uid: int, updates: dict) -> bool:
    with LOCK:
        data = _load_local()
        users = data.setdefault("users", {})
        uid_str = str(uid)
        if uid_str not in users: return False
        users[uid_str].update(updates)
        return _save_local(data)


def add_points(uid: int, amount: int) -> bool:
    with LOCK:
        data = _load_local()
        users = data.setdefault("users", {})
        uid_str = str(uid)
        if uid_str not in users:
            print(f"⚠️ add_points: user {uid} not found")
            return False
        users[uid_str]["points"] = users[uid_str].get("points", 0) + amount
        if amount > 0:
            stats = data.setdefault("stats", {})
            stats["total_points_given"] = stats.get("total_points_given", 0) + amount
        return _save_local(data)


def ban_user(uid: int, banned: bool = True) -> bool:
    return save_user(uid, {"is_banned": banned})


def get_top_users(limit=10) -> list:
    users = get_all_users()
    return sorted(users.values(), key=lambda u: u.get("points", 0), reverse=True)[:limit]


def get_top_referrers(limit=10) -> list:
    users = get_all_users()
    return sorted(users.values(), key=lambda u: u.get("total_referrals", 0), reverse=True)[:limit]

# ═══════════════════════════════════════════════════════════
#   🆕 Pending Starts (لحل مشكلة ضياع رمز الإحالة)
# ═══════════════════════════════════════════════════════════
def save_pending_start(uid: int, payload: str) -> bool:
    """احفظ /start payload (ref_... أو PTS_...) مؤقتاً حتى يتحقق الاشتراك."""
    if not payload: return False
    with LOCK:
        data = _load_local()
        data.setdefault("pending_starts", {})[str(uid)] = {
            "payload": payload,
            "saved_at": int(time.time()),
        }
        return _save_local(data)


def get_pending_start(uid: int) -> str:
    """اقرأ الـ payload المحفوظ بدون حذفه."""
    data = _load_local()
    entry = data.get("pending_starts", {}).get(str(uid))
    if not entry: return ""
    if int(time.time()) - entry.get("saved_at", 0) > 86400:
        return ""
    return entry.get("payload", "")


def pop_pending_start(uid: int) -> str:
    """اقرأ payload المحفوظ ثم احذفه (ذرياً)."""
    with LOCK:
        data = _load_local()
        pending = data.get("pending_starts", {})
        entry = pending.pop(str(uid), None)
        if entry is not None:
            _save_local(data)
        if not entry: return ""
        if int(time.time()) - entry.get("saved_at", 0) > 86400:
            return ""
        return entry.get("payload", "")


def cleanup_pending_starts(max_age_seconds: int = 86400) -> int:
    """احذف الـ payloads القديمة (يُستدعى عند بدء البوت)."""
    with LOCK:
        data = _load_local()
        pending = data.get("pending_starts", {})
        now = int(time.time())
        before = len(pending)
        data["pending_starts"] = {
            k: v for k, v in pending.items()
            if now - v.get("saved_at", 0) <= max_age_seconds
        }
        removed = before - len(data["pending_starts"])
        if removed:
            _save_local(data)
        return removed

# ═══════════════════════════════════════════════════════════
#   Products
# ═══════════════════════════════════════════════════════════
def get_products(active_only=True) -> dict:
    products = _load_local().get("products", {})
    if active_only:
        return {k: v for k, v in products.items() if v.get("active", True)}
    return products


def get_product(pid: str) -> dict:
    return _load_local().get("products", {}).get(pid, {})


def add_product(pid: str, product: dict) -> bool:
    with LOCK:
        data = _load_local()
        product["created_at"] = int(time.time())
        product["sold_count"] = 0
        data.setdefault("products", {})[pid] = product
        return _save_local(data)


def update_product(pid: str, updates: dict) -> bool:
    with LOCK:
        data = _load_local()
        products = data.get("products", {})
        if pid not in products: return False
        products[pid].update(updates)
        return _save_local(data)


def delete_product(pid: str) -> bool:
    with LOCK:
        data = _load_local()
        products = data.get("products", {})
        if pid in products:
            del products[pid]
            return _save_local(data)
        return False


def add_content_to_product(pid: str, item: dict) -> bool:
    with LOCK:
        data = _load_local()
        products = data.get("products", {})
        if pid not in products: return False
        products[pid].setdefault("contents", []).append(item)
        return _save_local(data)


def remove_content_from_product(pid: str, index: int) -> bool:
    with LOCK:
        data = _load_local()
        products = data.get("products", {})
        if pid not in products: return False
        contents = products[pid].get("contents", []) or []
        if 0 <= index < len(contents):
            del contents[index]
            products[pid]["contents"] = contents
            return _save_local(data)
        return False


def get_available_content(pid: str):
    p = get_product(pid)
    if not p: return None
    mode = p.get("delivery_mode", "single")
    if mode == "single":
        c = p.get("content", {})
        return c if c and c.get("data") else None
    contents = p.get("contents", [])
    sold = p.get("sold_count", 0)
    if sold >= len(contents): return None
    return contents[sold]


def increment_sold(pid: str) -> bool:
    with LOCK:
        data = _load_local()
        products = data.get("products", {})
        if pid not in products: return False
        products[pid]["sold_count"] = products[pid].get("sold_count", 0) + 1
        return _save_local(data)


def is_product_available(pid: str) -> bool:
    p = get_product(pid)
    if not p: return False
    if p.get("delivery_mode", "single") == "single": return True
    return p.get("sold_count", 0) < len(p.get("contents", []))


def get_product_stock(pid: str) -> int:
    p = get_product(pid)
    if not p: return 0
    if p.get("delivery_mode", "single") == "single": return -1
    return max(0, len(p.get("contents", [])) - p.get("sold_count", 0))

# ═══════════════════════════════════════════════════════════
#   Orders
# ═══════════════════════════════════════════════════════════
def add_order(oid: str, order: dict) -> bool:
    with LOCK:
        data = _load_local()
        data.setdefault("orders", {})[oid] = order
        stats = data.setdefault("stats", {})
        stats["total_sales"] = stats.get("total_sales", 0) + 1
        return _save_local(data)


def get_user_orders(uid: int) -> list:
    return [o for o in load().get("orders", {}).values() if o.get("user_id") == uid]

# ═══════════════════════════════════════════════════════════
#   Points Links
# ═══════════════════════════════════════════════════════════
def get_points_links() -> dict:
    return load().get("points_links", {})


def get_points_link(code: str) -> dict:
    return load().get("points_links", {}).get(code, {})


def add_points_link(code: str, data_: dict) -> bool:
    with LOCK:
        data = _load_local()
        data_["code"] = code
        data_["created_at"] = int(time.time())
        data_["uses"] = 0
        data_["claimed_by"] = {}
        data_["active"] = True
        data.setdefault("points_links", {})[code] = data_
        return _save_local(data)


def delete_points_link(code: str) -> bool:
    with LOCK:
        data = _load_local()
        links = data.get("points_links", {})
        if code in links:
            del links[code]
            return _save_local(data)
        return False


def is_points_link_valid(link: dict) -> tuple:
    if not link or not isinstance(link, dict): return False, "غير موجود"
    if not link.get("active", True): return False, "معطل"
    exp = link.get("expire_at", 0) or 0
    if exp > 0 and int(time.time()) > exp: return False, "منتهي"
    mx = link.get("max_uses", 0) or 0
    us = link.get("uses", 0) or 0
    if mx > 0 and us >= mx: return False, "استُنفد"
    return True, ""


def claim_points_link(code: str, uid: int) -> tuple:
    with LOCK:
        data = _load_local()
        links = data.get("points_links", {})
        link = links.get(code)
        if not link: return False, 0, "❌ الرابط غير موجود"
        valid, reason = is_points_link_valid(link)
        if not valid: return False, 0, f"❌ الرابط {reason}"
        claimed = link.get("claimed_by", {}) or {}
        if str(uid) in claimed: return False, 0, "⚠️ استخدمت هذا الرابط من قبل"
        amount = link.get("amount", 0)
        if amount <= 0: return False, 0, "❌ قيمة غير صحيحة"
        users = data.get("users", {})
        uid_str = str(uid)
        if uid_str not in users: return False, 0, "❌ سجّل أولاً بـ /start"
        users[uid_str]["points"] = users[uid_str].get("points", 0) + amount
        link["uses"] = link.get("uses", 0) + 1
        if "claimed_by" not in link or not isinstance(link["claimed_by"], dict):
            link["claimed_by"] = {}
        link["claimed_by"][uid_str] = int(time.time())
        stats = data.setdefault("stats", {})
        stats["total_points_given"] = stats.get("total_points_given", 0) + amount
        _save_local(data)
        return True, amount, "✅ تم استلام النقاط"

# ═══════════════════════════════════════════════════════════
#   🔥 KEYS
# ═══════════════════════════════════════════════════════════
def gen_devil_key() -> str:
    chars = string.ascii_uppercase + string.digits
    k = "DEVIL"
    for _ in range(3):
        k += "-" + "".join(random.choices(chars, k=4))
    return k


def gen_points_code() -> str:
    return "PTS_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def get_key(key: str) -> dict: return fb.get(f"keys/{key}") or {}
def set_key(key: str, data: dict) -> bool: return fb.set(f"keys/{key}", data)
def delete_key(key: str) -> bool: return fb.delete(f"keys/{key}")

# ═══════════════════════════════════════════════════════════
#   Reset Limits
# ═══════════════════════════════════════════════════════════
def check_key_limit(key: str, max_resets: int, window: int):
    data = _load_local()
    history = data.get("key_reset_history", {}).get(key, {})
    now = int(time.time())
    cutoff = now - window
    valid = [int(ts) for ts in history.keys() if ts.isdigit() and int(ts) >= cutoff]
    used = len(valid)
    if used >= max_resets:
        oldest = min(valid)
        return False, used, 0, max(0, (oldest + window) - now)
    return True, used, max_resets - used, 0


def check_user_limit(uid: int, max_resets: int, window: int):
    data = _load_local()
    history = data.get("user_reset_history", {}).get(str(uid), {})
    now = int(time.time())
    cutoff = now - window
    valid = [int(ts) for ts in history.keys() if ts.isdigit() and int(ts) >= cutoff]
    used = len(valid)
    if used >= max_resets:
        oldest = min(valid)
        return False, used, 0, max(0, (oldest + window) - now)
    return True, used, max_resets - used, 0


def add_key_reset_record(key: str, uid: int):
    with LOCK:
        data = _load_local()
        ts = str(int(time.time()))
        data.setdefault("key_reset_history", {}).setdefault(key, {})[ts] = {
            "user_id": uid, "at": int(time.time())
        }
        _save_local(data)


def add_user_reset_record(uid: int, key: str):
    with LOCK:
        data = _load_local()
        ts = str(int(time.time()))
        data.setdefault("user_reset_history", {}).setdefault(str(uid), {})[ts] = {
            "key": key, "at": int(time.time())
        }
        _save_local(data)


def reset_key_in_fb(key: str, uid: int):
    kd = fb.get(f"keys/{key}")
    if not kd or not isinstance(kd, dict):
        return False, "not_found", None
    devices = kd.get("Devices", {}) or {}
    device_ids = kd.get("device_ids", []) or []
    device_id = kd.get("device_id")
    old = []
    if isinstance(devices, dict):
        old += [d for d in devices.keys() if d != "dummy"]
    if isinstance(device_ids, list):
        old += [d for d in device_ids if d and d not in old]
    if device_id and device_id not in old:
        old.append(device_id)
    snap = {
        "expiry": kd.get("ExpiryDate", "") or str(kd.get("expiry", "")),
        "max_devices": kd.get("DeviceLimit", kd.get("max_devices", 1)),
        "created_by": kd.get("Username", kd.get("created_by", "")),
        "old_devices": old,
    }
    if not old: return False, "already_empty", snap
    kd["Devices"] = {"dummy": 0}
    kd["device_ids"] = []
    kd["device_id"] = None
    kd["activated_at"] = 0
    kd["reset"] = True
    kd["reset_at"] = int(time.time())
    kd["reset_by"] = uid
    if not fb.set(f"keys/{key}", kd): return False, "save_failed", snap
    return True, "ok", snap


def log_reset(key: str, uid: int, username: str, first_name: str, old_devices: list):
    with LOCK:
        data = _load_local()
        log_id = f"{int(time.time())}_{uid}"
        data.setdefault("reset_logs", {})[log_id] = {
            "key": key, "user_id": uid, "username": username,
            "first_name": first_name, "old_devices": old_devices,
            "reset_at": int(time.time()),
        }
        _save_local(data)

# ═══════════════════════════════════════════════════════════
#   Stats
# ═══════════════════════════════════════════════════════════
def get_stats() -> dict:
    data = _load_local()
    s = dict(data.get("stats", {}))
    s["total_users"] = len(data.get("users", {}))
    s["total_products"] = len(data.get("products", {}))
    return s