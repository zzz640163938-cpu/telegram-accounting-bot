import os
import re
import sqlite3
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --------- 配置区域 ---------
DB_PATH = "accounting.db"
# 可以在这里直接填入你的 Token，或者在 Render 的 Environment 环境变量里设置 TELEGRAM_BOT_TOKEN
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "在这里填入你的_TELEGRAM_BOT_TOKEN") 
# 管理员用户 ID（用于删除数据等高权操作），可在下方列表中填入你的数字 ID
ADMIN_IDS = [123456789] 

# --------- 数据库初始化 ---------
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

# --------- 辅助函数 ---------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def get_effective_date():
    # 默认获取当前日期，格式化为 YYYY-MM-DD
    return datetime.now().strftime("%Y-%m-%d")

# --------- 指令回调函数 (已修复中文指令问题) ---------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /start 指令 """
    await update.message.reply_text(
        "👋 欢迎使用记账机器人！\n\n"
        " 记账格式示例：\n"
        "`买菜 50`（记入默认账目）\n"
        "`晚餐 120 u`（支持带币种）\n\n"
        " 常用指令：\n"
        "/config - 查看或调整配置\n"
        "/delete - 删除今日账目数据"
    )

async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /config 指令（原 /配置） """
    await update.message.reply_text("⚙️ 机器人配置中心：当前运行状态正常。")

async def cmd_delete_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /delete 指令（原 /删除，已修复断行与未提交问题） """
    user_id = update.message.from_user.id
    if not is_admin(user_id): 
        await update.message.reply_text("❌ 抱歉，你没有权限执行删除操作。")
        return
        
    d = get_effective_date()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # 执行删除
    cur.execute("DELETE FROM bills WHERE date = ?", (d,))
    conn.commit()
    n = cur.rowcount  # 获取被删除的行数
    conn.close()
    
    await update.message.reply_text(f"✅ 已成功删除日期为 {d} 的 {n} 条账目数据数据。")

# --------- 消息处理逻辑 (文本自动记账) ---------
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ 处理日常文本记账 """
    if not update.message or not update.message.text:
        return
        
    uid = update.message.from_user.id
    t = update.message.text.strip()
    
    # 正则匹配格式：项目 金额 [币种] （例如: 吃饭 15 或 话费 100 u）
    m = re.match(r"^(.+?)\s+(\d+(?:\.\d+)?)(?:\s+([A-Za-z\u20a0-\u20cf]+))?$", t)
    
    if m:
        nm = m.group(1) or "默认"
        amt = float(m.group(2))
        cur_type = m.group(3) or "CNY" # 默认币种
        
        now = datetime.now()
        d = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        
        # 写入数据库
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

# --------- 主入口程序 ---------
def main():
    # 初始化数据库
    init_db()
    
    # 启动应用
    application = Application.builder().token(BOT_TOKEN).build()
    
    # 注册指令路由 (全部换成了合法的英文指令)
    application.add_handler(CommandHandler('start', cmd_start))
    application.add_handler(CommandHandler('config', cmd_config))
    application.add_handler(CommandHandler('delete', cmd_delete_bill))
    
    # 注册文本消息路由
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    
    # 开启轮询运行
    print("🤖 机器人已成功启动...")
    application.run_polling()

if __name__ == '__main__':
    main()
