import os
import re
import asyncio
import threading
import sqlite3
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# ==================== 配置区 ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8607596225:AAE_WtgnI7nN3Pf9ARUHlaDg7KFtB-v5jGo")
DB_PATH = "accounting.db"
FLASK_PORT = int(os.getenv("PORT", 10000))
DEFAULT_CURRENCY = "U"

# ==================== Flask 保活服务（Render 必备） ====================
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ 记账机器人运行正常"

def run_web_server():
    try:
        app.run(host="0.0.0.0", port=FLASK_PORT, use_reloader=False)
    except Exception as e:
        print(f"❌ Flask 服务启动失败: {e}")

# 启动后台线程运行 Flask
threading.Thread(target=run_web_server, daemon=True, name="FlaskServer").start()

# ==================== 数据库初始化 ====================
def init_db():
    """初始化数据库和表结构"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        # 1. 账单主表
        cur.execute('''
            CREATE TABLE IF NOT EXISTS bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                opt_type TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT NOT NULL,
                operate_name TEXT,
                create_time TEXT NOT NULL,
                create_date TEXT NOT NULL
            )
        ''')
        
        # 2. 系统配置表
        cur.execute('''
            CREATE TABLE IF NOT EXISTS sys_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        # 3. 初始化默认配置项
        default_configs = [
            ("rate", "0.08"),
            ("exchange", "7.4"),
            ("switch_status", "on"),
            ("daily_cut_hour", "0"),
            ("expire_time", "2099-12-31"),
            ("bot_name", "记账机器人")
        ]
        for key, value in default_configs:
            cur.execute("INSERT OR IGNORE INTO sys_config(key, value) VALUES (?, ?)", (key, value))
        
        # 4. 管理员表
        cur.execute('CREATE TABLE IF NOT EXISTS admins (uid INTEGER PRIMARY KEY, uname TEXT)')
        
        # 5. 操作人表
        cur.execute('CREATE TABLE IF NOT EXISTS operators (uid INTEGER PRIMARY KEY, uname TEXT)')
        
        conn.commit()
        conn.close()
        print("✅ 数据库初始化完成")
    except Exception as e:
        print(f"❌ 数据库初始化失败: {e}")
        raise

def get_config(key: str) -> str:
    """获取系统配置"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT value FROM sys_config WHERE key = ?", (key,))
    result = cur.fetchone()
    conn.close()
    return result[0] if result else ""

def set_config(key: str, value: str):
    """设置系统配置"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("REPLACE INTO sys_config(key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

# ==================== 权限工具 ====================
def is_admin(user_id: int) -> bool:
    """判断用户是否为管理员"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM admins WHERE uid = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    return bool(result)

def is_operator(user_id: int) -> bool:
    """判断用户是否为操作人"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM operators WHERE uid = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    return bool(result)

# ==================== 时间工具 ====================
def get_today_date() -> str:
    """获取今天的日期字符串 YYYY-MM-DD"""
    return datetime.now().strftime("%Y-%m-%d")

def get_current_full_time() -> str:
    """获取当前完整时间字符串 YYYY-MM-DD HH:MM:SS"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def parse_short_date(s: str) -> datetime:
    """解析短日期字符串（如 240203）为 datetime 对象"""
    return datetime.strptime(s, "%y%m%d")

# ==================== 命令处理器 ====================
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help 显示帮助信息"""
    help_text = """📖 记账机器人使用说明
【基础指令】
/help - 显示此帮助
/配置 - 查看当前费率和汇率
/开关状态 - 查看记账开关状态
/到期时间 - 查看服务到期时间

【管理员指令】
/设置费率 8% - 设置手续费率
/设置汇率 7.4 - 设置兑换汇率
/开始 / 结束 - 开启/关闭记账功能
/设置日切时间 14 - 设置每日切账时间
/删除账单 - 清空今日账单
/设置管理员 @xxx - 添加管理员
/移除管理员 @xxx - 移除管理员
/设置操作人 @xxx - 添加操作人
/移除操作人 @xxx - 移除操作人
/机器人名字 新名称 - 修改机器人昵称

【记账指令（直接发送消息）】
- 下发：`名字 下发 金额 币种`（如：张三 下发 500U）
- 入款：`名字 +金额` 或 `名字 -金额`（如：张三 -200）

【账单导出】
- 今日账单：导出今日全部账单文件
- 今日成员账单 张三：查看张三今日账单
- 账单明细-2：导出2日前账单
- 账单明细240203：导出指定日期账单
- 账单明细240202-240304：导出日期区间账单"""
    await update.message.reply_text(help_text)

async def cmd_set_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/设置费率 8%"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可操作此指令")
        return
    if not context.args:
        await update.message.reply_text("⚠️ 格式：/设置费率 8%")
        return
    rate_match = re.findall(r"\d+\.?\d*", context.args[0])
    if not rate_match:
        await update.message.reply_text("⚠️ 格式错误，请输入数字（如 8%）")
        return
    set_config("rate", rate_match[0])
    await update.message.reply_text(f"✅ 费率已设置为：{rate_match[0]}%")

async def cmd_set_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/设置汇率 7.4"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可操作此指令")
        return
    if not context.args:
        await update.message.reply_text("⚠️ 格式：/设置汇率 7.4")
        return
    set_config("exchange", context.args[0])
    await update.message.reply_text(f"✅ 汇率已设置为：{context.args[0]}")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/开始 开启记账功能"""
    if not is_admin(update.effective_user.id):
        return
    set_config("switch_status", "on")
    await update.message.reply_text("✅ 记账功能已开启")

async def cmd_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/结束 关闭记账功能"""
    if not is_admin(update.effective_user.id):
        return
    set_config("switch_status", "off")
    await update.message.reply_text("✅ 记账功能已关闭")

async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/配置 查看当前配置"""
    rate = get_config("rate")
    exchange = get_config("exchange")
    await update.message.reply_text(f"⚙️ 当前配置\n费率：{rate}%\n汇率：{exchange}")

async def cmd_switch_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/开关状态 查看记账开关状态"""
    status = get_config("switch_status")
    status_text = "✅ 已开启" if status == "on" else "❌ 已关闭"
    await update.message.reply_text(f"当前记账开关状态：{status_text}")

async def cmd_expire_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/到期时间 查看服务到期时间"""
    expire_time = get_config("expire_time")
    await update.message.reply_text(f"📅 服务到期时间：{expire_time}")

async def cmd_set_operator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/设置操作人 @xxx"""
    if not is_admin(update.effective_user.id):
        return
    if not context.args or not context.args[0].startswith("@"):
        await update.message.reply_text("⚠️ 格式：/设置操作人 @用户名")
        return
    username = context.args[0].replace("@", "")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("REPLACE INTO operators(uid, uname) VALUES (?, ?)", (update.effective_user.id, username))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ 已添加 {username} 为操作人")

async def cmd_remove_operator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/移除操作人 @xxx"""
    if not is_admin(update.effective_user.id):
        return
    if not context.args or not context.args[0].startswith("@"):
        await update.message.reply_text("⚠️ 格式：/移除操作人 @用户名")
        return
    username = context.args[0].replace("@", "")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM operators WHERE uname = ?", (username,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ 已移除 {username} 的操作权限")

async def cmd_set_cut_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/设置日切时间 14"""
    if not is_admin(update.effective_user.id):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("⚠️ 格式：/设置日切时间 14")
        return
    set_config("daily_cut_hour", context.args[0])
    await update.message.reply_text(f"✅ 日切时间已设置为 {context.args[0]} 点")

async def cmd_delete_today_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/删除账单 清空今日账单"""
    if not is_admin(update.effective_user.id):
        return
    today = get_today_date()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM bills WHERE create_date = ?", (today,))
    deleted_count = cur.rowcount
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ 已清空今日账单，共删除 {deleted_count} 条记录")

async def cmd_set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/设置管理员 @xxx"""
    if not context.args or not context.args[0].startswith("@"):
        await update.message.reply_text("⚠️ 格式：/设置管理员 @用户名")
        return
    username = context.args[0].replace("@", "")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("REPLACE INTO admins(uid, uname) VALUES (?, ?)", (update.effective_user.id, username))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ 已设置 {username} 为管理员")

async def cmd_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/移除管理员 @xxx"""
    if not context.args or not context.args[0].startswith("@"):
        await update.message.reply_text("⚠️ 格式：/移除管理员 @用户名")
        return
    username = context.args[0].replace("@", "")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM admins WHERE uname = ?", (username,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ 已移除 {username} 的管理员权限")

async def cmd_rename_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/机器人名字 新名称"""
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("⚠️ 格式：/机器人名字 新名称")
        return
    new_name = " ".join(context.args)
    set_config("bot_name", new_name)
    await update.message.reply_text(f"✅ 机器人名称已修改为：{new_name}")

# ==================== 消息处理器（处理记账和账单导出） ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    switch_status = get_config("switch_status")
    
    # 非管理员且开关关闭时不处理
    if switch_status != "on" and not is_admin(user_id):
        return

    # 1. 下发指令匹配：名字 下发 金额 币种（如：张三 下发 500U）
    xiafa_pattern = r"^(.*?)\s*下发\s*(\d+\.?\d*)\s*([A-Za-z]*)?$"
    xiafa_match = re.match(xiafa_pattern, text)
    if xiafa_match:
        operate_name = xiafa_match.group(1).strip() or ""
        amount = float(xiafa_match.group(2))
        currency = xiafa_match.group(3) or DEFAULT_CURRENCY
        now = datetime.now()
        create_time = now.strftime("%Y-%m-%d %H:%M:%S")
        create_date = now.strftime("%Y-%m-%d")
        
        # 写入数据库
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO bills (user_id, username, opt_type, amount, currency, operate_name, create_time, create_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, "下发", amount, currency, operate_name, create_time, create_date)
        )
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ 下发记账成功\n项目：{operate_name}\n金额：{amount} {currency}\n时间：{create_time}")
        return

    # 2. 入款指令匹配：名字 +金额 / 名字 -金额（如：张三 -200）
    ruku_pattern = r"^(.*?)([+-])(\d+\.?\d*)$"
    ruku_match = re.match(ruku_pattern, text)
    if ruku_match:
        operate_name = ruku_match.group(1).strip() or ""
        symbol = ruku_match.group(2)
        amount = float(ruku_match.group(3))
        real_amount = amount if symbol == "+" else -amount
        now = datetime.now()
        create_time = now.strftime("%Y-%m-%d %H:%M:%S")
        create_date = now.strftime("%Y-%m-%d")
        
        # 写入数据库
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO bills (user_id, username, opt_type, amount, currency, operate_name, create_time, create_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, "入款", real_amount, DEFAULT_CURRENCY, operate_name, create_time, create_date)
        )
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ 入款记账成功\n项目：{operate_name}\n金额：{symbol}{amount} {DEFAULT_CURRENCY}\n时间：{create_time}")
        return

    # 3. 今日账单导出
    if text == "今日账单":
        today = get_today_date()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT * FROM bills WHERE create_date = ?", (today,))
        records = cur.fetchall()
        conn.close()
        
        if not records:
            await update.message.reply_text("📭 今日暂无账单记录")
            return
        
        # 生成账单文件
        file_content = f"==== 今日账单（{today}）====\n"
        for record in records:
            file_content += f"{record[7]} | {record[3]} | {record[4]}{record[5]} | {record[6]}\n"
        
        with open("today_bill.txt", "w", encoding="utf-8") as f:
            f.write(file_content)
        
        await update.message.reply_document(document=open("today_bill.txt", "rb"), filename="今日账单.txt")
        return

    # 4. 今日成员账单查询：今日成员账单 张三
    member_bill_pattern = r"^今日成员账单\s*(.+)$"
    member_bill_match = re.match(member_bill_pattern, text)
    if member_bill_match:
        target_name = member_bill_match.group(1).strip()
        today = get_today_date()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT * FROM bills WHERE create_date = ? AND operate_name LIKE ?", (today, f"%{target_name}%"))
        records = cur.fetchall()
        conn.close()
        
        if not records:
            await update.message.reply_text(f"📭 今日暂无 {target_name} 的账单记录")
            return
        
        result_text = f"==== {target_name} 今日账单 ====\n"
        for record in records:
            result_text += f"{record[7]} | {record[3]} | {record[4]}{record[5]}\n"
        
        await update.message.reply_text(result_text)
        return

    # 5. 账单明细-N 导出N日前账单：账单明细-2
    day_bill_pattern = r"^账单明细-(\d+)$"
    day_bill_match = re.match(day_bill_pattern, text)
    if day_bill_match:
        days = int(day_bill_match.group(1))
        target_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT * FROM bills WHERE create_date = ?", (target_date,))
        records = cur.fetchall()
        conn.close()
        
        if not records:
            await update.message.reply_text(f"📭 {target_date} 暂无账单记录")
            return
        
        file_content = f"==== {target_date} 账单 ====\n"
        for record in records:
            file_content += f"{record[7]} | {record[3]} | {record[4]}{record[5]} | {record[6]}\n"
        
        file_name = f"bill_{target_date}.txt"
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(file_content)
        
        await update.message.reply_document(document=open(file_name, "rb"), filename=file_name)
        return

    # 6. 账单明细YYYYMMDD 导出指定日期账单：账单明细240203
    date_bill_pattern = r"^账单明细(\d{6})$"
    date_bill_match = re.match(date_bill_pattern, text)
    if date_bill_match:
        short_date = date_bill_match.group(1)
        try:
            target_date = parse_short_date(short_date).strftime("%Y-%m-%d")
        except ValueError:
            await update.message.reply_text("⚠️ 日期格式错误，请使用 240203 这种格式（YYMMDD）")
            return
        
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT * FROM bills WHERE create_date = ?", (target_date,))
        records = cur.fetchall()
        conn.close()
        
        if not records:
            await update.message.reply_text(f"📭 {target_date} 暂无账单记录")
            return
        
        file_content = f"==== {target_date} 账单 ====\n"
        for record in records:
            file_content += f"{record[7]} | {record[3]} | {record[4]}{record[5]} | {record[6]}\n"
        
        file_name = f"bill_{target_date}.txt"
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(file_content)
        
        await update.message.reply_document(document=open(file_name, "rb"), filename=file_name)
        return

    # 7. 账单明细YYYYMMDD-YYYYMMDD 导出日期区间账单：账单明细240202-240304
    range_bill_pattern = r"^账单明细(\d{6})-(\d{6})$"
    range_bill_match = re.match(range_bill_pattern, text)
    if range_bill_match:
        start_short, end_short = range_bill_match.groups()
        try:
            start_date = parse_short_date(start_short).strftime("%Y-%m-%d")
            end_date = parse_short_date(end_short).strftime("%Y-%m-%d")
        except ValueError:
            await update.message.reply_text("⚠️ 日期格式错误，请使用 240202-240304 这种格式（YYMMDD-YYMMDD）")
            return
        
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT * FROM bills WHERE create_date BETWEEN ? AND ?", (start_date, end_date))
        records = cur.fetchall()
        conn.close()
        
        if not records:
            await update.message.reply_text(f"📭 {start_date} 至 {end_date} 暂无账单记录")
            return
        
        file_content = f"==== {start_date} 至 {end_date} 账单 ====\n"
        for record in records:
            file_content += f"{record[7]} | {record[3]} | {record[4]}{record[5]} | {record[6]}\n"
        
        file_name = f"bill_{start_short}_{end_short}.txt"
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(file_content)
        
        await update.message.reply_document(document=open(file_name, "rb"), filename=file_name)
        return

# ==================== 机器人主函数 ====================
async def main_async():
    print("🤖 记账机器人正在启动...")
    
    # 初始化数据库
    init_db()
    
    # 检查 Bot Token 是否有效
    if not BOT_TOKEN or BOT_TOKEN == "你的Telegram Bot Token":
        print("❌ 错误：未设置有效的 BOT_TOKEN，请在环境变量或代码中配置")
        return
    
    # 创建应用
    application = Application.builder().token(BOT_TOKEN).build()
    
    # 注册所有命令处理器
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("设置费率", cmd_set_rate))
    application.add_handler(CommandHandler("设置汇率", cmd_set_exchange))
    application.add_handler(CommandHandler("开始", cmd_start))
    application.add_handler(CommandHandler("结束", cmd_end))
    application.add_handler(CommandHandler("配置", cmd_config))
    application.add_handler(CommandHandler("开关状态", cmd_switch_status))
    application.add_handler(CommandHandler("到期时间", cmd_expire_time))
    application.add_handler(CommandHandler("设置操作人", cmd_set_operator))
    application.add_handler(CommandHandler("移除操作人", cmd_remove_operator))
    application.add_handler(CommandHandler("设置日切时间", cmd_set_cut_time))
    application.add_handler(CommandHandler("删除账单", cmd_delete_today_bill))
    application.add_handler(CommandHandler("设置管理员", cmd_set_admin))
    application.add_handler(CommandHandler("移除管理员", cmd_remove_admin))
    application.add_handler(CommandHandler("机器人名字", cmd_rename_bot))
    
    # 注册消息处理器（过滤掉命令）
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ 所有处理器注册完成，开始轮询消息")
    
    # 启动机器人
    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        # 维持主循环运行
        while True:
            await asyncio.sleep(3600)

def main():
    """入口函数"""
    try:
        # 适配不同系统的事件循环
        if os.name == "nt":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main_async())
    except Exception as e:
        print(f"❌ 机器人运行出错：{e}")
    finally:
        loop.close()

if __name__ == "__main__":
    main()
