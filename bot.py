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

# ========== 基础配置 ==========
BOT_TOKEN = os.getenv("BOT_TOKEN", "8607596225:AAE_WtgnI7nN3Pf9ARUHlaDg7KFtB-v5jGo")
DB_PATH = "accounting.db"
FLASK_PORT = int(os.getenv("PORT", 10000))
DEFAULT_CURRENCY = "U"

# ========== Flask保活 ==========
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ 记账机器人在线运行"

def run_web():
    try:
        app.run(host="0.0.0.0", port=FLASK_PORT, use_reloader=False)
    except Exception as e:
        print(f"❌ Flask 服务启动失败: {e}")

threading.Thread(target=run_web, daemon=True).start()

# ========== 数据库初始化 ==========
def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # 账单表
        cur.execute('''CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            opt_type TEXT,
            amount REAL,
            currency TEXT,
            operate_name TEXT,
            create_time TEXT,
            create_date TEXT
        )''')
        # 系统配置表
        cur.execute('''CREATE TABLE IF NOT EXISTS sys_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')
        # 初始化默认配置
        init_conf = [
            ("rate", "0.08"),
            ("exchange", "7.4"),
            ("switch_status", "on"),
            ("daily_cut_hour", "0"),
            ("expire_time", "2099-12-31"),
            ("bot_name", "记账机器人")
        ]
        for k, v in init_conf:
            cur.execute("INSERT OR IGNORE INTO sys_config(key,value) VALUES(?,?)", (k, v))
        # 管理员表
        cur.execute('CREATE TABLE IF NOT EXISTS admins(uid INTEGER PRIMARY KEY, uname TEXT)')
        # 操作人表
        cur.execute('CREATE TABLE IF NOT EXISTS operators(uid INTEGER PRIMARY KEY, uname TEXT)')
        conn.commit()
        conn.close()
        print("✅ 数据库初始化成功")
    except Exception as e:
        print(f"❌ 数据库初始化失败: {e}")
        raise

def get_conf(key):
    conn = sqlite3.connect(DB_PATH)
    res = conn.execute("SELECT value FROM sys_config WHERE key=?", (key,)).fetchone()
    conn.close()
    return res[0] if res else ""

def set_conf(key, val):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("REPLACE INTO sys_config(key,value) VALUES(?,?)", (key, val))
    conn.commit()
    conn.close()

# ========== 权限判断 ==========
def is_admin(uid):
    conn = sqlite3.connect(DB_PATH)
    ok = conn.execute("SELECT 1 FROM admins WHERE uid=?", (uid,)).fetchone()
    conn.close()
    return bool(ok)

def is_operator(uid):
    conn = sqlite3.connect(DB_PATH)
    ok = conn.execute("SELECT 1 FROM operators WHERE uid=?", (uid,)).fetchone()
    conn.close()
    return bool(ok)

# ========== 时间工具 ==========
def now_date():
    return datetime.now().strftime("%Y-%m-%d")

def now_full_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def str2date(s):
    return datetime.strptime(s, "%y%m%d")

# ========== 指令功能 ==========
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = """📖记账机器人使用大全
1.帮助-查看使用说明
2.设置费率8% 设置对应费率
3.设置汇率7.4 设置兑换汇率
4.开始/结束 开关记账功能
5.配置 查看当前费率+汇率
6.开关状态 查看记账启停状态
7.到期时间 查看服务到期时间
8.设置操作人 @xxx 添加操作权限
9.移除操作人 @xxx 取消操作权限
10.设置日切时间14 设置每日切账小时
11.今日账单 导出今日全部账单文件
12.今日成员账单+名字 查看单人今日账单
13.账单明细-2 导出N日前账单
14.账单明细240203 导出指定日期账单
15.账单明细240202-240304 导出区间账单
16.下发 张三下发500U / 下发400
17.入款 +800 / 张三-200
18.机器人名字XX 修改机器人昵称
19.设置管理员@xxx 添加管理员
20.移除管理员@xxx 移除管理员
21.删除账单 清空今日所有账单"""
    await update.message.reply_text(text)

async def cmd_set_rate(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌仅管理员可操作")
        return
    if not ctx.args:
        await update.message.reply_text("格式：/设置费率 8%")
        return
    num = re.findall(r"\d+\.?\d*", ctx.args[0])
    if not num:
        await update.message.reply_text("格式错误")
        return
    set_conf("rate", num[0])
    await update.message.reply_text(f"✅费率已设置为：{num[0]}%")

async def cmd_set_exchange(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌仅管理员可操作")
        return
    if not ctx.args:
        await update.message.reply_text("格式：/设置汇率 7.4")
        return
    set_conf("exchange", ctx.args[0])
    await update.message.reply_text(f"✅汇率已设置为：{ctx.args[0]}")

async def cmd_switch_start(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    set_conf("switch_status", "on")
    await update.message.reply_text("✅记账功能已开启")

async def cmd_switch_end(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    set_conf("switch_status", "off")
    await update.message.reply_text("✅记账功能已关闭")

async def cmd_config(update: Update, ctx):
    r = get_conf("rate")
    e = get_conf("exchange")
    await update.message.reply_text(f"⚙️当前配置\n费率：{r}%\n汇率：{e}")

async def cmd_switch_status(update: Update, ctx):
    s = get_conf("switch_status")
    txt = "✅已开启" if s == "on" else "❌已关闭"
    await update.message.reply_text(f"当前记账开关状态：{txt}")

async def cmd_expire_time(update: Update, ctx):
    t = get_conf("expire_time")
    await update.message.reply_text(f"📅服务到期时间：{t}")

async def cmd_set_op(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args or not ctx.args[0].startswith("@"):
        await update.message.reply_text("格式：/设置操作人 @用户名")
        return
    uname = ctx.args[0].replace("@", "")
    uid = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    conn.execute("REPLACE INTO operators(uid,uname) VALUES(?,?)", (uid, uname))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅已添加 {uname} 为操作人")

async def cmd_del_op(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args or not ctx.args[0].startswith("@"):
        await update.message.reply_text("格式：/移除操作人 @用户名")
        return
    uname = ctx.args[0].replace("@", "")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM operators WHERE uname=?", (uname,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅已移除 {uname} 操作权限")

async def cmd_set_cut(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("格式：/设置日切时间 14")
        return
    set_conf("daily_cut_hour", ctx.args[0])
    await update.message.reply_text(f"✅日切时间设置为 {ctx.args[0]} 点")

async def cmd_del_today_bill(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    td = now_date()
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("DELETE FROM bills WHERE create_date=?", (td,)).rowcount
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅已清空今日账单共{n}条")

async def cmd_set_admin(update: Update, ctx):
    if not ctx.args or not ctx.args[0].startswith("@"):
        await update.message.reply_text("格式：/设置管理员 @xxx")
        return
    uname = ctx.args[0].strip("@")
    uid = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    conn.execute("REPLACE INTO admins(uid,uname) VALUES(?,?)", (uid, uname))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅成功设置{uname}为管理员")

async def cmd_del_admin(update: Update, ctx):
    if not ctx.args or not ctx.args[0].startswith("@"):
        await update.message.reply_text("格式：/移除管理员 @xxx")
        return
    uname = ctx.args[0].strip("@")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM admins WHERE uname=?", (uname,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅已移除{uname}管理员权限")

async def cmd_rename_bot(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("格式：/机器人名字 新名称")
        return
    newname = " ".join(ctx.args)
    set_conf("bot_name", newname)
    await update.message.reply_text(f"✅机器人名称已修改为：{newname}")

# ========== 消息监听：下发/入款/账单导出 ==========
async def msg_handler(update: Update, ctx):
    txt = update.message.text.strip()
    uid = update.effective_user.id
    uname = update.effective_user.username or ""
    switch = get_conf("switch_status")
    if switch != "on" and not is_admin(uid):
        return

    # 下发匹配
    pat_xiafa = r"^(.*?)下发\s*(\d+\.?\d*)\s*([A-Za-z]*)?$"
    m1 = re.match(pat_xiafa, txt)
    if m1:
        name = m1.group(1).strip() or ""
        amt = float(m1.group(2))
        cur = m1.group(3) or DEFAULT_CURRENCY
        conn = sqlite3.connect(DB_PATH)
        conn.execute('INSERT INTO bills(user_id,username,opt_type,amount,currency,operate_name,create_time,create_date) VALUES(?,?,?,?,?,?,?,?)',
                     (uid, uname, "下发", amt, cur, name, now_full_time(), now_date()))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅下发记账成功\n{name} {amt} {cur}")
        return

    # 入款匹配
    pat_rukuan = r"^(.*?)([+-])(\d+\.?\d*)$"
    m2 = re.match(pat_rukuan, txt)
    if m2:
        name = m2.group(1).strip() or ""
        sym = m2.group(2)
        amt = float(m2.group(3))
        real_amt = amt if sym == "+" else -amt
        conn = sqlite3.connect(DB_PATH)
        conn.execute('INSERT INTO bills(user_id,username,opt_type,amount,currency,operate_name,create_time,create_date) VALUES(?,?,?,?,?,?,?,?)',
                     (uid, uname, "入款", real_amt, DEFAULT_CURRENCY, name, now_full_time(), now_date()))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅入款记账成功\n{name} {sym}{amt}")
        return

    # 今日账单
    if txt == "今日账单":
        conn = sqlite3.connect(DB_PATH)
        data = conn.execute("SELECT * FROM bills WHERE create_date=?", (now_date(),)).fetchall()
        conn.close()
        cont = "====今日账单====\n"
        for d in data:
            cont += f"{d[7]} | {d[3]} | {d[4]}{d[5]} | {d[6]}\n"
        with open("today_bill.txt", "w", encoding="utf-8") as f:
            f.write(cont)
        await update.message.reply_document(document=open("today_bill.txt", "rb"))
        return

    # 今日成员账单
    m_mem = re.match(r"^今日成员账单(.+)$", txt)
    if m_mem:
        nick = m_mem.group(1).strip()
        conn = sqlite3.connect(DB_PATH)
        res = conn.execute("SELECT * FROM bills WHERE create_date=? and operate_name like ?", (now_date(), f"%{nick}%")).fetchall()
        conn.close()
        if not res:
            await update.message.reply_text("暂无该成员今日账单")
            return
        t = ""
        for i in res:
            t += f"{i[7]} {i[3]} {i[4]}{i[5]}\n"
        await update.message.reply_text(t)
        return

    # 账单明细-数字
    m_sub = re.match(r"^账单明细-(\d+)$", txt)
    if m_sub:
        days = int(m_sub.group(1))
        target = datetime.now() - timedelta(days=days)
        tar_date = target.strftime("%Y-%m-%d")
        conn = sqlite3.connect(DB_PATH)
        data = conn.execute("SELECT * FROM bills WHERE create_date=?", (tar_date,)).fetchall()
        conn.close()
        text = f"===={tar_date}账单====\n"
        for i in data:
            text += f"{i[7]} {i[3]} {i[4]}{i[5]}\n"
        with open(f"bill_{tar_date}.txt", "w", encoding="utf-8") as f:
            f.write(text)
        await update.message.reply_document(open(f"bill_{tar_date}.txt", "rb"))
        return

    # 单日日期账单 账单明细240203
    m_day = re.match(r"^账单明细(\d{6})$", txt)
    if m_day:
        s = m_day.group(1)
        try:
            d = str2date(s)
            fd = d.strftime("%Y-%m-%d")
        except:
            await update.message.reply_text("日期格式错误 例240203")
            return
        conn = sqlite3.connect(DB_PATH)
        data = conn.execute("SELECT * FROM bills WHERE create_date=?", (fd,)).fetchall()
        conn.close()
        txtout = f"===={fd}账单====\n"
        for i in data:
            txtout += f"{i[7]} {i[3]} {i[4]}{i[5]}\n"
        with open(f"bill_{fd}.txt", "w", encoding="utf-8") as f:
            f.write(txtout)
        await update.message.reply_document(open(f"bill_{fd}.txt", "rb"))
        return

    # 区间账单 账单明细240202-240304
    m_range = re.match(r"^账单明细(\d{6})-(\d{6})$", txt)
    if m_range:
        s1, s2 = m_range.groups()
        try:
            d1 = str2date(s1).strftime("%Y-%m-%d")
            d2 = str2date(s2).strftime("%Y-%m-%d")
        except:
            await update.message.reply_text("日期格式错误")
            return
        conn = sqlite3.connect(DB_PATH)
        data = conn.execute("SELECT * FROM bills WHERE create_date BETWEEN ? AND ?", (d1, d2)).fetchall()
        conn.close()
        out = f"===={d1}至{d2}账单====\n"
        for i in data:
            out += f"{i[7]} {i[3]} {i[4]}{i[5]}\n"
        with open(f"bill_range_{s1}_{s2}.txt", "w", encoding="utf-8") as f:
            f.write(out)
        await update.message.reply_document(open(f"bill_range_{s1}_{s2}.txt", "rb"))
        return

# ========== 主启动 ==========
async def main_async():
    print("🤖 机器人正在初始化...")
    init_db()
    
    if not BOT_TOKEN or BOT_TOKEN == "你的Telegram Bot Token":
        print("❌ 错误：未设置有效的 BOT_TOKEN")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # 注册全部命令
    application.add_handler(CommandHandler("帮助", cmd_help))
    application.add_handler(CommandHandler("设置费率", cmd_set_rate))
    application.add_handler(CommandHandler("设置汇率", cmd_set_exchange))
    application.add_handler(CommandHandler("开始", cmd_switch_start))
    application.add_handler(CommandHandler("结束", cmd_switch_end))
    application.add_handler(CommandHandler("配置", cmd_config))
    application.add_handler(CommandHandler("开关状态", cmd_switch_status))
    application.add_handler(CommandHandler("到期时间", cmd_expire_time))
    application.add_handler(CommandHandler("设置操作人", cmd_set_op))
    application.add_handler(CommandHandler("移除操作人", cmd_del_op))
    application.add_handler(CommandHandler("设置日切时间", cmd_set_cut))
    application.add_handler(CommandHandler("删除账单", cmd_del_today_bill))
    application.add_handler(CommandHandler("设置管理员", cmd_set_admin))
    application.add_handler(CommandHandler("移除管理员", cmd_del_admin))
    application.add_handler(CommandHandler("机器人名字", cmd_rename_bot))

    # 普通文本消息
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))

    print("✅ 所有处理器注册完成，开始轮询消息")
    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        while True:
            await asyncio.sleep(3600)

def main():
    try:
        # 适配不同系统的事件循环
        if os.name == 'nt':
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
