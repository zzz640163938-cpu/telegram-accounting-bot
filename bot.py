import os
import re
import asyncio
import threading
import sqlite3
from datetime import datetime
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# ==================== 配置项（从环境变量读取，避免硬编码敏感信息） ====================
# 优先读取环境变量，再用默认值（部署时更安全）
BOT_TOKEN = os.getenv("BOT_TOKEN", "你的Telegram Bot Token")
DB_PATH = os.getenv("DB_PATH", "accounting.db")
FLASK_PORT = int(os.getenv("PORT", 10000))  # Render 会自动注入 PORT 环境变量

# ==================== Flask 端口兼容层（解决 Render 无端口检测问题） ====================
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Bot is running normally! Accounting bot is online."

@app.route('/health')
def health_check():
    # 健康检查接口，Render 可以用这个做存活探针
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}, 200

def run_web_server():
    try:
        app.run(host="0.0.0.0", port=FLASK_PORT, use_reloader=False)
    except Exception as e:
        print(f"❌ Web 服务启动失败: {e}")

# 启动后台线程运行 Flask 服务（daemon=True 确保主进程退出时自动关闭）
threading.Thread(target=run_web_server, daemon=True, name="FlaskServer").start()

# ==================== 数据库初始化与工具函数 ====================
def init_db():
    """初始化数据库和表结构"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                name TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'CNY'
            )
        ''')
        # 为常用查询字段创建索引，提升性能
        cur.execute('CREATE INDEX IF NOT EXISTS idx_user_date ON bills(user_id, date)')
        conn.commit()
        print("✅ 数据库初始化成功")
    except sqlite3.Error as e:
        print(f"❌ 数据库初始化失败: {e}")
    finally:
        if conn:
            conn.close()

def get_effective_date() -> str:
    """获取当前日期字符串（YYYY-MM-DD）"""
    return datetime.now().strftime("%Y-%m-%d")

# ==================== 机器人命令处理函数 ====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start 命令：发送欢迎信息和使用说明"""
    if not update.effective_user:
        return
    await update.message.reply_text(
        "👋 欢迎使用记账机器人！\n\n"
        "📝 **记账格式**（直接发消息即可）：\n"
        "`项目 金额` → 如：`吃饭 35`\n"
        "`项目 金额 货币` → 如：`采购 100 USD`\n\n"
        "⚙️ **常用命令**：\n"
        "/start - 显示此帮助\n"
        "/config - 查看配置信息\n"
        "/delete - 删除今天的所有账目\n"
        "/today - 查看今天的账目汇总\n"
        "/help - 显示帮助信息"
    )

async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/config 命令：显示机器人配置状态"""
    await update.message.reply_text(
        "⚙️ 机器人配置中心\n"
        f"• 数据库路径：`{DB_PATH}`\n"
        f"• Web 服务端口：`{FLASK_PORT}`\n"
        "• 运行状态：✅ 正常\n"
        "• 货币默认：CNY"
    )

async def cmd_delete_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/delete 命令：删除当前用户今天的所有账目"""
    if not update.effective_user:
        return
    user_id = update.effective_user.id
    today = get_effective_date()
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM bills WHERE user_id = ? AND date = ?",
            (user_id, today)
        )
        conn.commit()
        deleted_count = cur.rowcount
        await update.message.reply_text(
            f"✅ 已删除你今天的 {deleted_count} 条账目数据。\n"
            f"日期：{today}"
        )
    except sqlite3.Error as e:
        await update.message.reply_text(f"❌ 删除失败：数据库错误 - {e}")
    finally:
        if conn:
            conn.close()

async def cmd_today_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/today 命令：查看当前用户今天的账目汇总"""
    if not update.effective_user:
        return
    user_id = update.effective_user.id
    today = get_effective_date()
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT name, amount, currency FROM bills WHERE user_id = ? AND date = ?",
            (user_id, today)
        )
        records = cur.fetchall()
        conn.close()
        
        if not records:
            await update.message.reply_text("📭 你今天还没有记账记录哦~")
            return
        
        # 按货币分类汇总
        summary = {}
        details = []
        for name, amount, currency in records:
            if currency not in summary:
                summary[currency] = 0
            summary[currency] += amount
            details.append(f"• {name}: {amount} {currency}")
        
        summary_text = f"📊 今日账目汇总（{today}）\n"
        summary_text += "\n".join(details) + "\n\n"
        summary_text += "💰 总金额：\n"
        for curr, total in summary.items():
            summary_text += f"• {curr}: {total}\n"
        
        await update.message.reply_text(summary_text)
    except sqlite3.Error as e:
        await update.message.reply_text(f"❌ 查询失败：数据库错误 - {e}")

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户的记账消息"""
    if not update.message or not update.message.text or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # 正则匹配记账格式（支持项目名包含中文/英文，金额，可选货币）
    pattern = r"^(.+?)\s+(\d+(?:\.\d+)?)(?:\s+([A-Za-z\u20a0-\u20cf\u4e00-\u9fa5]+))?$"
    match = re.match(pattern, text)
    
    if match:
        # 提取匹配到的数据
        item_name = match.group(1).strip()
        amount = float(match.group(2))
        currency = match.group(3) or "CNY"
        
        # 金额有效性校验
        if amount <= 0:
            await update.message.reply_text("❌ 金额必须大于0，请重新输入。")
            return
        
        # 获取当前时间
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO bills 
                   (user_id, date, time, name, amount, currency) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, date_str, time_str, item_name, amount, currency)
            )
            conn.commit()
            await update.message.reply_text(
                f"✅ 记账成功！\n"
                f"项目：{item_name}\n"
                f"金额：{amount} {currency}\n"
                f"时间：{date_str} {time_str}"
            )
        except sqlite3.Error as e:
            await update.message.reply_text(f"❌ 记账失败：数据库错误 - {e}")
        finally:
            if conn:
                conn.close()
    else:
        await update.message.reply_text(
            "❓ 记账格式不对哦~请使用以下格式：\n"
            "`项目 金额`（如：`奶茶 18`）\n"
            "或 `项目 金额 货币`（如：`打车 30 CNY`）\n"
            "输入 /start 查看帮助信息"
        )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help 命令：显示完整帮助信息"""
    await update.message.reply_text(
        "📖 记账机器人完整帮助\n\n"
        "【如何记账】\n"
        "直接发送消息即可，格式为：`项目 金额 [货币]`\n"
        "例：`早餐 12`、`网购 99.9 USD`\n\n"
        "【可用命令】\n"
        "/start - 显示欢迎信息\n"
        "/today - 查看今天的账目\n"
        "/delete - 删除今天的所有账目\n"
        "/config - 查看机器人配置\n"
        "/help - 显示此帮助\n\n"
        "【注意事项】\n"
        "• 项目名和金额之间用空格分隔\n"
        "• 金额支持整数和小数\n"
        "• 货币默认是CNY，也可以指定USD、EUR等"
    )

# ==================== 机器人主逻辑 ====================
async def main_async():
    """异步主函数：初始化并启动机器人"""
    # 初始化数据库
    init_db()
    
    # 检查 Bot Token 是否有效
    if not BOT_TOKEN or BOT_TOKEN == "你的Telegram Bot Token":
        print("❌ 错误：未设置有效的 BOT_TOKEN，请在环境变量或代码中配置")
        return
    
    # 创建机器人应用
    application = Application.builder().token(BOT_TOKEN).build()
    
    # 注册所有命令处理器
    application.add_handler(CommandHandler('start', cmd_start))
    application.add_handler(CommandHandler('config', cmd_config))
    application.add_handler(CommandHandler('delete', cmd_delete_bill))
    application.add_handler(CommandHandler('today', cmd_today_summary))
    application.add_handler(CommandHandler('help', cmd_help))
    # 注册消息处理器（过滤掉命令，只处理文本消息）
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    
    print("🤖 机器人正在启动...")
    
    # 推荐的异步启动方式（兼容新版 Python）
    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        print("✅ 机器人已成功启动并开始轮询消息！")
        # 维持主循环运行
        while True:
            await asyncio.sleep(3600)  # 每小时休眠一次，避免循环空转

def main():
    """入口函数：设置事件循环并运行主逻辑"""
    try:
        # 为 Windows 系统设置事件循环策略（兼容 Render/Linux 环境）
        if os.name == 'nt':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        # 创建并设置新的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main_async())
    except Exception as e:
        print(f"❌ 机器人运行出错：{e}")
    finally:
        loop.close()

if __name__ == '__main__':
    main()
