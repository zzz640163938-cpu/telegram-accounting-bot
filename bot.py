import os
import re
import asyncio
import threading
import sqlite3
from datetime import datetime
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==================== 1. Render 端口检查兼容层 ====================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running perfectly!"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# 创建并启动后台线程跑 Web 服务
threading.Thread(target=run_web_server, daemon=True).start()
# ================================================================

DB_PATH = "accounting.db"
BOT_TOKEN = "8607596225:AAE_WtgnI7nN3Pf9ARUHlaDg7KFtB-v5jGo"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            time TEXT,
            name TEXT,
            amount REAL,
            currency TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_effective_date():
    return datetime.now().strftime("%Y-%m-%d")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "📝 Format:\n"
        "`下发 1000`\n"
        "`下发 1000 u`\n\n"
        "⚙️ Commands:\n"
        "/config - Config\n"
        "/delete - Delete today data"
    )

async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚙️ 机器人配置中心：当前运行状态正常。")

async def cmd_delete_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = get_effective_date()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM bills WHERE date = ?", (d,))
    conn.commit()
    n = cur.rowcount
    conn.close()
    await update.message.reply_text(f"✅ 已成功删除日期为 {d} 的 {n} 条账目数据。")

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    uid = update.message.from_user.id
    t = update.message.text.strip()
    m = re.match(r"^(.+?)\s+(\d+(?:\.\d+)?)(?:\s+([A-Za-z\u20a0-\u20cf\u4e00-\u9fa5]+))?$", t)
    if m:
        nm = m.group(1) or "默认"
        amt = float(m.group(2))
        cur_type = m.group(3) or "CNY"
        now = datetime.now()
        d = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        conn = sqlite3.connect(DB_PATH)
        cur2 = conn.cursor()
        cur2.execute(
            "INSERT INTO bills (user_id, date, time, name, amount, currency) VALUES (?, ?, ?, ?, ?, ?)",
            (uid, d, time_str, nm, amt, cur_type)
        )
        conn.commit()
        conn.close()
        await update.message.reply_text(f"📝 记账成功！\n项目：{nm}\n金额：{amt} {cur_type}\n时间：{d} {time_str}")
    else:
        await update.message.reply_text("❓ 记账格式好像不太对哦，请使用 `项目 金额` 格式（如：下发 1000）。")

async def main_async():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler('start', cmd_start))
    application.add_handler(CommandHandler('config', cmd_config))
    application.add_handler(CommandHandler('delete', cmd_delete_bill))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    
    print("🤖 机器人正在异步初始化并在后台轮询...")
    
    # 使用更加推荐的异步方式启动，避免 run_polling 在 Python 3.14 中直接崩溃
    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        print("🤖 机器人已成功启动！")
        # 维持运行防止退出
        while True:
            await asyncio.sleep(3600)

def main():
    # 针对新版 Python，强制创建并设置新的事件循环，彻底根治 'no current event loop' 错误
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main_async())

if __name__ == '__main__':
    main()
