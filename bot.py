import os
import re
import asyncio
import threading
import sqlite3
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# 基础配置
BOT_TOKEN = "8607596225:AAE_WtgnI7nN3Pf9ARUHlaDg7KFtB-v5jGo"
DB_PATH = "accounting.db"
FLASK_PORT = int(os.getenv("PORT", 10000))
DEFAULT_CURRENCY = "U"

# 保活网页
app = Flask(__name__)
@app.route('/')
def home():
    return "记账机器人正常运行"
def run_web_server():
    try:
        app.run(host="0.0.0.0", port=FLASK_PORT, use_reloader=False)
    except:
        pass
threading.Thread(target=run_web_server, daemon=True).start()

# 数据库初始化
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS bills (
id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,username TEXT,opt_type TEXT NOT NULL,
amount REAL NOT NULL,currency TEXT NOT NULL,operate_name TEXT,create_time TEXT NOT NULL,create_date TEXT NOT NULL)''')
    cur.execute('CREATE TABLE IF NOT EXISTS sys_config (key TEXT PRIMARY KEY,value TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS admins (uid INTEGER PRIMARY KEY,uname TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS operators (uid INTEGER PRIMARY KEY,uname TEXT)')
    default_configs = [("rate","0.08"),("exchange","7.4"),("switch_status","on"),
    ("daily_cut_hour","0"),("expire_time","2099-12-31"),("bot_name","记账机器人")]
    for k,v in default_configs:
        cur.execute("INSERT OR IGNORE INTO sys_config(key,value) VALUES (?,?)",(k,v))
    conn.commit()
    conn.close()

def get_config(key:str)->str:
    conn=sqlite3.connect(DB_PATH)
    res=conn.execute("SELECT value FROM sys_config WHERE key=?",(key,)).fetchone()
    conn.close()
    return res[0] if res else ""

def set_config(key:str,value:str):
    conn=sqlite3.connect(DB_PATH)
    conn.execute("REPLACE INTO sys_config(key,value) VALUES (?,?)",(key,value))
    conn.commit()
    conn.close()

def is_admin(uid:int)->bool:
    conn=sqlite3.connect(DB_PATH)
    ok=conn.execute("SELECT 1 FROM admins WHERE uid=?",(uid,)).fetchone()
    conn.close()
    return bool(ok)

def is_operator(uid:int)->bool:
    conn=sqlite3.connect(DB_PATH)
    ok=conn.execute("SELECT 1 FROM operators WHERE uid=?",(uid,)).fetchone()
    conn.close()
    return bool(ok)

def get_today_date()->str:
    return datetime.now().strftime("%Y-%m-%d")
def parse_short_date(s:str)->datetime:
    return datetime.strptime(s,"%y%m%d")

# 核心消息监听（全部中文指令在这里）
async def main_handle(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    txt=update.message.text.strip()
    uid=update.effective_user.id
    uname=update.effective_user.username or ""
    switch=get_config("switch_status")

    # 中文指令全部在这里
    if txt=="/帮助":
        help_text="""📖 记账机器人使用说明
/帮助 - 显示此帮助
/设置费率 8% - 设置手续费率
/设置汇率 7.4 - 设置兑换汇率
/开始 - 开启记账
/结束 - 关闭记账
/配置 - 查看当前费率汇率
/开关状态 - 查看记账开关
/到期时间 - 查看服务到期时间
/设置操作人 @xxx - 添加操作人
/移除操作人 @xxx - 移除操作人
/设置日切时间 14 - 设置日切时间
/删除账单 - 清空今日账单
/设置管理员 @xxx - 添加管理员
/移除管理员 @xxx - 移除管理员
/机器人名字 新名称 - 修改昵称
今日账单 - 导出今日账单
今日成员账单 张三 - 成员今日账单
账单明细-2 - 导出2日前账单
账单明细240203 - 指定日期账单
账单明细240202-240304 - 区间账单
下发 张三 500U / 下发 400
+800 / 张三-200"""
        await update.message.reply_text(help_text)

    elif txt.startswith("/设置费率"):
        if not is_admin(uid):
            await update.message.reply_text("❌仅管理员可用")
            return
        args=txt.replace("/设置费率","").strip()
        num=re.findall(r"\d+\.?\d*",args)
        if not num:
            await update.message.reply_text("⚠️格式：/设置费率 8%")
            return
        set_config("rate",num[0])
        await update.message.reply_text(f"✅费率已设为：{num[0]}%")

    elif txt.startswith("/设置汇率"):
        if not is_admin(uid):
            await update.message.reply_text("❌仅管理员可用")
            return
        args=txt.replace("/设置汇率","").strip()
        if not args:
            await update.message.reply_text("⚠️格式：/设置汇率 7.4")
            return
        set_config("exchange",args)
        await update.message.reply_text(f"✅汇率已设为：{args}")

    elif txt=="/开始":
        if not is_admin(uid):return
        set_config("switch_status","on")
        await update.message.reply_text("✅记账功能已开启")

    elif txt=="/结束":
        if not is_admin(uid):return
        set_config("switch_status","off")
        await update.message.reply_text("✅记账功能已关闭")

    elif txt=="/配置":
        r=get_config("rate")
        e=get_config("exchange")
        await update.message.reply_text(f"⚙️当前配置\n费率：{r}%\n汇率：{e}")

    elif txt=="/开关状态":
        s=get_config("switch_status")
        t="✅已开启"if s=="on"else"❌已关闭"
        await update.message.reply_text(f"记账状态：{t}")

    elif txt=="/到期时间":
        t=get_config("expire_time")
        await update.message.reply_text(f"📅到期时间：{t}")

    elif txt.startswith("/设置操作人"):
        if not is_admin(uid):return
        u=txt.replace("/设置操作人","").strip()
        if not u.startswith("@"):
            await update.message.reply_text("⚠️格式：/设置操作人 @用户名")
            return
        name=u.replace("@","")
        conn=sqlite3.connect(DB_PATH)
        conn.execute("REPLACE INTO operators(uid,uname) VALUES(?,?)",(uid,name))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅已添加{name}为操作人")

    elif txt.startswith("/移除操作人"):
        if not is_admin(uid):return
        u=txt.replace("/移除操作人","").strip()
        if not u.startswith("@"):
            await update.message.reply_text("⚠️格式：/移除操作人 @用户名")
            return
        name=u.replace("@","")
        conn=sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM operators WHERE uname=?",(name,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅已移除{name}操作权限")

    elif txt.startswith("/设置日切时间"):
        if not is_admin(uid):return
        t=txt.replace("/设置日切时间","").strip()
        if not t.isdigit():
            await update.message.reply_text("⚠️格式：/设置日切时间 14")
            return
        set_config("daily_cut_hour",t)
        await update.message.reply_text(f"✅日切时间设为{t}点")

    elif txt=="/删除账单":
        if not is_admin(uid):return
        td=get_today_date()
        conn=sqlite3.connect(DB_PATH)
        n=conn.execute("DELETE FROM bills WHERE create_date=?",(td,)).rowcount
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅清空今日账单，共删除{n}条")

    elif txt.startswith("/设置管理员"):
        u=txt.replace("/设置管理员","").strip()
        if not u.startswith("@"):
            await update.message.reply_text("⚠️格式：/设置管理员 @用户名")
            return
        name=u.replace("@","")
        conn=sqlite3.connect(DB_PATH)
        conn.execute("REPLACE INTO admins(uid,uname) VALUES(?,?)",(uid,name))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅{name}已设为管理员")

    elif txt.startswith("/移除管理员"):
        u=txt.replace("/移除管理员","").strip()
        if not u.startswith("@"):
            await update.message.reply_text("⚠️格式：/移除管理员 @用户名")
            return
        name=u.replace("@","")
        conn=sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM admins WHERE uname=?",(name,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅已移除{name}管理员")

    elif txt.startswith("/机器人名字"):
        if not is_admin(uid):return
        na=txt.replace("/机器人名字","").strip()
        if not na:
            await update.message.reply_text("⚠️格式：/机器人名字 新名称")
            return
        set_config("bot_name",na)
        await update.message.reply_text(f"✅机器人名称改为：{na}")

    # 普通记账消息
    elif not txt.startswith("/"):
        if switch!="on" and not is_admin(uid) and not is_operator(uid):
            return
        # 下发
        xf=re.match(r"^(.*?)下发\s*(\d+\.?\d*)\s*([A-Za-z]*)?$",txt)
        if xf:
            nm=xf.group(1).strip() or ""
            am=float(xf.group(2))
            cy=xf.group(3) or DEFAULT_CURRENCY
            now=datetime.now()
            ct=now.strftime("%Y-%m-%d %H:%M:%S")
            cd=now.strftime("%Y-%m-%d")
            conn=sqlite3.connect(DB_PATH)
            conn.execute("INSERT INTO bills(user_id,username,opt_type,amount,currency,operate_name,create_time,create_date) VALUES(?,?,?,?,?,?,?,?)",
            (uid,uname,"下发",am,cy,nm,ct,cd))
            conn.commit()
            conn.close()
            await update.message.reply_text(f"✅下发记账成功\n项目：{nm}\n金额：{am} {cy}\n时间：{ct}")
            return
        # 出入款
        rk=re.match(r"^(.*?)([+-])(\d+\.?\d*)$",txt)
        if rk:
            nm=rk.group(1).strip() or ""
            fh=rk.group(2)
            am=float(rk.group(3))
            real=am if fh=="+" else -am
            now=datetime.now()
            ct=now.strftime("%Y-%m-%d %H:%M:%S")
            cd=now.strftime("%Y-%m-%d")
            conn=sqlite3.connect(DB_PATH)
            conn.execute("INSERT INTO bills(user_id,username,opt_type,amount,currency,operate_name,create_time,create_date) VALUES(?,?,?,?,?,?,?,?)",
            (uid,uname,"入款",real,DEFAULT_CURRENCY,nm,ct,cd))
            conn.commit()
            conn.close()
            await update.message.reply_text(f"✅入款记账成功\n项目：{nm}\n金额：{fh}{am} {DEFAULT_CURRENCY}\n时间：{ct}")
            return
        # 今日账单
        if txt=="今日账单":
            td=get_today_date()
            conn=sqlite3.connect(DB_PATH)
            data=conn.execute("SELECT * FROM bills WHERE create_date=?",(td,)).fetchall()
            conn.close()
            if not data:
                await update.message.reply_text("📭今日暂无账单")
                return
            text_all=f"====今日账单（{td}）====\n"
            for d in data:
                text_all+=f"{d[7]} | {d[3]} | {d[4]}{d[5]} | {d[6]}\n"
            with open("今日账单.txt","w",encoding="utf-8")as f:
                f.write(text_all)
            await update.message.reply_document(open("今日账单.txt","rb"),filename="今日账单.txt")
            return
        # 成员账单
        cz=re.match(r"^今日成员账单\s*(.+)$",txt)
        if cz:
            na=cz.group(1).strip()
            td=get_today_date()
            conn=sqlite3.connect(DB_PATH)
            res=conn.execute("SELECT * FROM bills WHERE create_date=? AND operate_name LIKE ?",(td,f"%{na}%")).fetchall()
            conn.close()
            if not res:
                await update.message.reply_text(f"📭暂无{na}今日账单")
                return
            res_text=f"===={na}今日账单====\n"
            for r in res:
                res_text+=f"{r[7]} | {r[3]} | {r[4]}{r[5]}\n"
            await update.message.reply_text(res_text)
            return
        # 前N天账单
        qt=re.match(r"^账单明细-(\d+)$",txt)
        if qt:
            day=int(qt.group(1))
            dt=(datetime.now()-timedelta(days=day)).strftime("%Y-%m-%d")
            conn=sqlite3.connect(DB_PATH)
            da=conn.execute("SELECT * FROM bills WHERE create_date=?",(dt,)).fetchall()
            conn.close()
            if not da:
                await update.message.reply_text(f"📭{dt}无账单")
                return
            cont=f"===={dt}账单====\n"
            for i in da:
                cont+=f"{i[7]} | {i[3]} | {i[4]}{i[5]} | {i[6]}\n"
            fn=f"{dt}账单.txt"
            with open(fn,"w",encoding="utf-8")as f:f.write(cont)
            await update.message.reply_document(open(fn,"rb"),filename=fn)
            return
        # 指定日期账单
        dr=re.match(r"^账单明细(\d{6})$",txt)
        if dr:
            sd=dr.group(1)
            try:
                ddt=parse_short_date(sd).strftime("%Y-%m-%d")
            except:
                await update.message.reply_text("⚠️日期格式错误 例：账单明细260517")
                return
            conn=sqlite3.connect(DB_PATH)
            dd=conn.execute("SELECT * FROM bills WHERE create_date=?",(ddt,)).fetchall()
            conn.close()
            if not dd:
                await update.message.reply_text(f"📭{ddt}无账单")
                return
            cont=f"===={ddt}账单====\n"
            for i in dd:
                cont+=f"{i[7]} | {i[3]} | {i[4]}{i[5]} | {i[6]}\n"
            fn=f"{ddt}账单.txt"
            with open(fn,"w",encoding="utf-8")as f:f.write(cont)
            await update.message.reply_document(open(fn,"rb"),filename=fn)
            return
        # 区间账单
        qj=re.match(r"^账单明细(\d{6})-(\d{6})$",txt)
        if qj:
            s1,s2=qj.groups()
            try:
                st=parse_short_date(s1).strftime("%Y-%m-%d")
                ed=parse_short_date(s2).strftime("%Y-%m-%d")
            except:
                await update.message.reply_text("⚠️格式：账单明细260501-260517")
                return
            conn=sqlite3.connect(DB_PATH)
            qjd=conn.execute("SELECT * FROM bills WHERE create_date BETWEEN ? AND ?",(st,ed)).fetchall()
            conn.close()
            if not qjd:
                await update.message.reply_text(f"📭{st}至{ed}无账单")
                return
            cont=f"===={st}至{ed}账单====\n"
            for i in qjd:
                cont+=f"{i[7]} | {i[3]} | {i[4]}{i[5]} | {i[6]}\n"
            fn=f"{s1}_{s2}区间账单.txt"
            with open(fn,"w",encoding="utf-8")as f:f.write(cont)
            await update.message.reply_document(open(fn,"rb"),filename=fn)

# 启动机器人
async def run_bot():
    init_db()
    app=Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT,main_handle))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    while True:await asyncio.sleep(3600)

if __name__=="__main__":
    asyncio.run(run_bot())
