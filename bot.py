#!/usr/bin/env python3
import logging, sqlite3, os, re
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
DB_PATH = "accounting_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS operators (user_id INTEGER PRIMARY KEY, username TEXT, name TEXT, added_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, username TEXT, added_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS bills (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, time TEXT, type TEXT, name TEXT, amount REAL, currency TEXT, note TEXT, operator_id INTEGER, operator_name TEXT, created_at TEXT)")
    for k, v in {"rate": "0", "exchange_rate": "1", "switch": "off", "day_cut_hour": "0", "bot_name": "记账机器人", "expiry_date": "2099-12-31"}.items():
        c.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()

def get_config(key):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key = ?", (key,)); r = c.fetchone(); conn.close()
    return r[0] if r else ""

def set_config(key, value):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value)); conn.commit(); conn.close()

def is_admin(uid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT user_id FROM admins WHERE user_id = ?", (uid,)); r = c.fetchone(); conn.close()
    return r is not None

def is_operator(uid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT user_id FROM operators WHERE user_id = ?", (uid,)); r = c.fetchone(); conn.close()
    return r is not None

def can_operate(uid):
    return is_admin(uid) or is_operator(uid)

def get_effective_date():
    h = int(get_config("day_cut_hour")); now = datetime.now()
    return (now - timedelta(days=1)).strftime("%Y-%m-%d") if now.hour < h else now.strftime("%Y-%m-%d")

def gen_bill(bills, title, u=""):
    fn = f"bill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(fn, "w", encoding="utf-8") as f:
        f.write(f"{'='*40}\n{title}\n{'='*40}\n"); 
        if u: f.write(f"成员: {u}\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'─'*40}\n\n")
        if not bills: f.write("暂无账单记录\n")
        else:
            for i, b in enumerate(bills, 1):
                f.write(f"【{i}】\n时间: {b[1]} {b[2]}\n类型: {b[3]}\n名字: {b[4]}\n金额: {b[5]} {b[6]}\n备注: {b[7] or '无'}\n操作人: {b[9]}\n{'─'*20}\n\n")
        if bills:
            f.write(f"\n{'='*40}\n统计\n{'='*40}\n")
            s = {}
            for b in bills: t, a = b[3], float(b[5]); s[t] = s.get(t, 0) + a
            for t, a in s.items(): f.write(f"{t}: {a}\n")
    return fn

async def cmd_help(u, c): await u.message.reply_text("📖 帮助\n①帮助\n②设置费率8%\n③设置汇率7.4\n④开始/结束\n⑤配置\n⑥开关状态\n⑦到期时间\n⑧设置操作人@成员\n⑨移除操作人@成员\n⑩设置日切时间14\n⑪今日账单\n⑫今日成员账单张三\n⑬账单明细-2\n⑭账单明细240203\n⑮账单明细240202-240304\n⑯下发500U\n⑰+800/-200\n⑱机器人名字XX\n⑲设置管理员@成员\n⑳移除管理员@成员\n㉑删除账单", parse_mode=ParseMode.MARKDOWN)

async def cmd_config(u, c):
    r, er, sw, dc, bn, ed = get_config("rate"), get_config("exchange_rate"), get_config("switch"), get_config("day_cut_hour"), get_config("bot_name"), get_config("expiry_date")
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    ops = [f"@{x[0]}" for x in cur.execute("SELECT username FROM operators").fetchall()]
    ads = [f"@{x[0]}" for x in cur.execute("SELECT username FROM admins").fetchall()]
    conn.close()
    await u.message.reply_text(f"⚙️ 配置\n\n🤖 {bn}\n💱 费率: {r}%\n💱 汇率: {er}\n🔄 {'开启' if sw=='on' else '关闭'}\n🕐 日切: {dc}点\n📅 到期: {ed}\n\n👥 操作员({len(ops)}): {', '.join(ops) or '无'}\n👑 管理员({len(ads)}): {', '.join(ads) or '无'}", parse_mode=ParseMode.MARKDOWN)

async def cmd_switch_status(u, c): await u.message.reply_text(f"开关状态: {'🟢开启' if get_config('switch')=='on' else '🔴关闭'}", parse_mode=ParseMode.MARKDOWN)

async def cmd_expiry(u, c):
    ed = datetime.strptime(get_config("expiry_date"), "%Y-%m-%d")
    await u.message.reply_text(f"📅 到期: {get_config('expiry_date')}\n⏰ 剩余: {(ed-datetime.now()).days} 天", parse_mode=ParseMode.MARKDOWN)

async def cmd_start(u, c):
    if not can_operate(u.message.from_user.id): await u.message.reply_text("❌ 权限不足"); return
    set_config("switch", "on"); await u.message.reply_text("✅ 开启")

async def cmd_stop(u, c):
    if not can_operate(u.message.from_user.id): await u.message.reply_text("❌ 权限不足"); return
    set_config("switch", "off"); await u.message.reply_text("✅ 关闭")

async def cmd_set_rate(u, c):
    if not is_admin(u.message.from_user.id): await u.message.reply_text("❌ 仅管理员"); return
    t = u.message.text.replace("设置费率", "").strip().replace("%", "")
    if not t.isdigit(): await u.message.reply_text("❌ 数字"); return
    set_config("rate", t); await u.message.reply_text(f"✅ 费率{t}%")

async def cmd_set_exchange_rate(u, c):
    if not is_admin(u.message.from_user.id): await u.message.reply_text("❌ 仅管理员"); return
    t = u.message.text.replace("设置汇率", "").strip()
    try: float(t)
    except: await u.message.reply_text("❌ 数字"); return
    set_config("exchange_rate", t); await u.message.reply_text(f"✅ 汇率{t}")

async def cmd_day_cut_time(u, c):
    if not is_admin(u.message.from_user.id): await u.message.reply_text("❌ 仅管理员"); return
    t = u.message.text.replace("设置日切时间", "").replace("查看日切时间", "").strip()
    if not t: await u.message.reply_text(f"🕐 {get_config('day_cut_hour')}点"); return
    if not t.isdigit() or int(t) > 23: await u.message.reply_text("❌ 0-23"); return
    set_config("day_cut_hour", t); await u.message.reply_text(f"✅ 日切{t}点")

async def cmd_set_operator(u, c):
    if not is_admin(u.message.from_user.id): await u.message.reply_text("❌ 仅管理员"); return
    t = u.message.text.replace("设置操作人", "").replace(" ", "").strip()
    if not t.startswith("@"): await u.message.reply_text("❌ 格式"); return
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO operators (username, added_at) VALUES (?, ?)", (t[1:], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit(); conn.close(); await u.message.reply_text(f"✅ 添加@{t[1:]}")

async def cmd_remove_operator(u, c):
    if not is_admin(u.message.from_user.id): await u.message.reply_text("❌ 仅管理员"); return
    t = u.message.text.replace("移除操作人", "").replace(" ", "").strip()
    if not t.startswith("@"): await u.message.reply_text("❌ 格式"); return
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("DELETE FROM operators WHERE username = ?", (t[1:],)); conn.commit(); conn.close()
    await u.message.reply_text(f"✅ 移除@{t[1:]}")

async def cmd_set_admin(u, c):
    uid = u.message.from_user.id
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor(); cur.execute("SELECT COUNT(*) FROM admins")
    if cur.fetchone()[0] > 0 and not is_admin(uid): conn.close(); await u.message.reply_text("❌ 仅管理员"); return
    conn.close()
    t = u.message.text.replace("设置管理员", "").replace(" ", "").strip()
    if not t.startswith("@"): await u.message.reply_text("❌ 格式"); return
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO admins (username, added_at) VALUES (?, ?)", (t[1:], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit(); conn.close(); await u.message.reply_text(f"✅ 设为管理员@{t[1:]}")

async def cmd_remove_admin(u, c):
    if not is_admin(u.message.from_user.id): await u.message.reply_text("❌ 仅管理员"); return
    t = u.message.text.replace("移除管理员", "").replace(" ", "").strip()
    if not t.startswith("@"): await u.message.reply_text("❌ 格式"); return
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("DELETE FROM admins WHERE username = ?", (t[1:],)); conn.commit(); conn.close()
    await u.message.reply_text(f"✅ 移除@{t[1:]}")

async def cmd_set_bot_name(u, c):
    if not is_admin(u.message.from_user.id): await u.message.reply_text("❌ 仅管理员"); return
    t = u.message.text.replace("机器人名字", "").strip()
    if not t: await u.message.reply_text("❌ 名字"); return
    set_config("bot_name", t); await u.message.reply_text(f"✅ {t}")

async def cmd_today_bill(u, c):
    if not can_operate(u.message.from_user.id): await u.message.reply_text("❌ 权限"); return
    d = get_effective_date()
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT * FROM bills WHERE date = ? ORDER BY time DESC", (d,)); bills = cur.fetchall(); conn.close()
    fn = gen_bill(bills, f"今日账单 {d}")
    with open(fn, "rb") as f: await u.message.reply_document(document=f, filename=fn, caption=f"📊 {d}")
    os.remove(fn)

async def cmd_member_bill(u, c):
    if not can_operate(u.message.from_user.id): await u.message.reply_text("❌ 权限"); return
    t = u.message.text.replace("今日成员账单", "").strip()
    if not t: await u.message.reply_text("❌ 名字"); return
    d = get_effective_date()
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT * FROM bills WHERE date = ? AND name = ? ORDER BY time DESC", (d, t)); bills = cur.fetchall(); conn.close()
    fn = gen_bill(bills, f"成员账单 {t}({d})", t)
    with open(fn, "rb") as f: await u.message.reply_document(document=f, filename=fn, caption=f"👤 {t}")
    os.remove(fn)

async def cmd_bill_detail(u, c):
    if not can_operate(u.message.from_user.id): await u.message.reply_text("❌ 权限"); return
    t = u.message.text.replace("账单明细", "").strip()
    if not t: await u.message.reply_text("❌ 日期"); return
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    if "-" in t and len(t) == 17:
        s, e = t.split("-"); sd = datetime.strptime(f"20{s}", "%Y%m%d").strftime("%Y-%m-%d"); ed = datetime.strptime(f"20{e}", "%Y%m%d").strftime("%Y-%m-%d")
        cur.execute("SELECT * FROM bills WHERE date >= ? AND date <= ? ORDER BY date DESC, time DESC", (sd, ed)); bills = cur.fetchall()
        fn = gen_bill(bills, f"{sd}~{ed}")
    elif t.startswith("-"):
        d = (datetime.now() - timedelta(days=int(t[1:]))).strftime("%Y-%m-%d")
        cur.execute("SELECT * FROM bills WHERE date = ? ORDER BY time DESC", (d,)); bills = cur.fetchall()
        fn = gen_bill(bills, f"账单 {d}")
    elif len(t) == 6 and t.isdigit():
        d = datetime.strptime(f"20{t}", "%Y%m%d").strftime("%Y-%m-%d")
        cur.execute("SELECT * FROM bills WHERE date = ? ORDER BY time DESC", (d,)); bills = cur.fetchall()
        fn = gen_bill(bills, f"账单 {d}")
    else:
        conn.close(); await u.message.reply_text("❌ 格式"); return
    conn.close()
    with open(fn, "rb") as f: await u.message.reply_document(document=f, filename=fn, caption=f"📋 账单")
    os.remove(fn)

async def cmd_delete_bill(u, c):
    if not is_admin(u.message.from_user.id): await u.message.reply_text("❌ 仅管理员"); return
    d = get_effective_date()
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("DELETE FROM bills WHERE date = ?", (d,)); n = cur.rowcount; conn.commit(); conn.close()
    await u.message.reply_text(f"✅ 删除{d}的{n}条")

async def handle_msg(u, c)
...(truncated)...
