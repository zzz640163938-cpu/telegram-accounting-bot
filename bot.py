import os
import re
import asyncio
import threading
import sqlite3
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# 配置
BOT_TOKEN = "8607596225:AAE_WtgnI7nN3Pf9ARUHlaDg7KFtB-v5jGo"
DB_PATH = "accounting.db"
FLASK_PORT = int(os.getenv("PORT", 10000))
DEFAULT_CURRENCY = "U"

# Flask 保活
app = Flask(__name__)
@app.route('/')
def home():
    return "OK"
def run_web():
    app.run(host="0.0.0.0", port=FLASK_PORT, use_reloader=False)
threading.Thread(target=run_web, daemon=True).start()

# 数据库
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS bills(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,username TEXT,opt_type TEXT,amount REAL,currency TEXT,operate_name TEXT,create_time TEXT,create_date TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS sys_config(key TEXT PRIMARY KEY,value TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS admins(uid INTEGER PRIMARY KEY,uname TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS operators(uid INTEGER PRIMARY KEY,uname TEXT)')
    for k,v in [("rate","0.08"),("exchange","7.4"),("switch_status","on"),("bot_name","记账机器人")]:
        c.execute("INSERT OR IGNORE INTO sys_config(key,value) VALUES(?,?)",(k,v))
    conn.commit()
    conn.close()

def get_conf(k):
    conn = sqlite3.connect(DB_PATH)
    res = conn.execute("SELECT value FROM sys_config WHERE key=?",(k,)).fetchone()
    conn.close()
    return res[0] if res else ""

def set_conf(k,v):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("REPLACE INTO sys_config(key,value) VALUES(?,?)",(k,v))
    conn.commit()
    conn.close()

def is_admin(uid):
    conn = sqlite3.connect(DB_PATH)
    ok = conn.execute("SELECT 1 FROM admins WHERE uid=?",(uid,)).fetchone()
    conn.close()
    return bool(ok)

# 命令
async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = """📖记账机器人使用说明
/help - 显示此帮助
/设置费率 8%
/设置汇率 7.4
/开始 / 结束 - 开关记账
/配置 - 查看费率汇率
/设置管理员 @xxx
/设置操作人 @xxx
今日账单 - 导出今日账单
下发 张三 500U / 下发 400
+800 / 张三-200"""
    await update.message.reply_text(text)

async def set_rate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌仅管理员可操作")
        return
    if not ctx.args:
        await update.message.reply_text("格式：/设置费率 8%")
        return
    num = re.findall(r"\d+\.?\d*",ctx.args[0])
    if num:
        set_conf("rate",num[0])
        await update.message.reply_text(f"✅费率已设置为：{num[0]}%")

async def set_exchange(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌仅管理员可操作")
        return
    if not ctx.args:
        await update.message.reply_text("格式：/设置汇率 7.4")
        return
    set_conf("exchange",ctx.args[0])
    await update.message.reply_text(f"✅汇率已设置为：{ctx.args[0]}")

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    set_conf("switch_status","on")
    await update.message.reply_text("✅记账功能已开启")

async def end(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    set_conf("switch_status","off")
    await update.message.reply_text("✅记账功能已关闭")

async def config(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"⚙️当前配置\n费率：{get_conf('rate')}%\n汇率：{get_conf('exchange')}")

async def set_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args or not ctx.args[0].startswith("@"):
        await update.message.reply_text("格式：/设置管理员 @用户名")
        return
    uname = ctx.args[0].replace("@","")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("REPLACE INTO admins(uid,uname) VALUES(?,?)",(update.effective_user.id,uname))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅已添加 {uname} 为管理员")

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    uid = update.effective_user.id
    uname = update.effective_user.username or ""
    switch = get_conf("switch_status")
    if switch != "on" and not is_admin(uid):
        return
    # 下发
    xiafa = re.match(r"^(.*?)下发\s*(\d+\.?\d*)\s*([A-Za-z]*)?$",txt)
    if xiafa:
        name = xiafa.group(1).strip() or ""
        amt = float(xiafa.group(2))
        cur = xiafa.group(3) or DEFAULT_CURRENCY
        now = datetime.now()
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO bills(user_id,username,opt_type,amount,currency,operate_name,create_time,create_date) VALUES(?,?,?,?,?,?,?,?)",
                     (uid,uname,"下发",amt,cur,name,now.strftime("%Y-%m-%d %H:%M:%S"),now.strftime("%Y-%m-%d")))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅下发记账成功\n{name} {amt} {cur}")
        return
    # 入款
    ruku = re.match(r"^(.*?)([+-])(\d+\.?\d*)$",txt)
    if ruku:
        name = ruku.group(1).strip() or ""
        sym = ruku.group(2)
        amt = float(ruku.group(3))
        real_amt = amt if sym=="+" else -amt
        now = datetime.now()
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO bills(user_id,username,opt_type,amount,currency,operate_name,create_time,create_date) VALUES(?,?,?,?,?,?,?,?)",
                     (uid,uname,"入款",real_amt,DEFAULT_CURRENCY,name,now.strftime("%Y-%m-%d %H:%M:%S"),now.strftime("%Y-%m-%d")))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅入款记账成功\n{name} {sym}{amt}")
        return
    # 今日账单
    if txt == "今日账单":
        today = datetime.now().strftime("%Y-%m-%d")
        conn = sqlite3.connect(DB_PATH)
        data = conn.execute("SELECT * FROM bills WHERE create_date=?",(today,)).fetchall()
        conn.close()
        if not data:
            await update.message.reply_text("📭今日暂无账单记录")
            return
        with open("today_bill.txt","w",encoding="utf-8") as f:
            f.write(f"====今日账单====\n")
            for d in data:
                f.write(f"{d[7]} | {d[3]} | {d[4]}{d[5]} | {d[6]}\n")
        await update.message.reply_document(document=open("today_bill.txt","rb"))

async def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("设置费率", set_rate))
    app.add_handler(CommandHandler("设置汇率", set_exchange))
    app.add_handler(CommandHandler("开始", start))
    app.add_handler(CommandHandler("结束", end))
    app.add_handler(CommandHandler("配置", config))
    app.add_handler(CommandHandler("设置管理员", set_admin))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
