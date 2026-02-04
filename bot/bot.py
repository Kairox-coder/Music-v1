import os, asyncio, discord, yt_dlp, gspread, aiohttp, pytz, json
from discord.ext import commands
from google.oauth2.service_account import Credentials
from datetime import datetime,timedelta

TOKEN=os.getenv("TOKEN")
SHEET_ID=os.getenv("SHEET_ID")
TZ=os.getenv("TZ","UTC")
IDLE=int(os.getenv("VOICE_IDLE_SECONDS","120"))
WEBHOOK=os.getenv("GUILD_LOG_WEBHOOK")
CREDS=json.loads(os.getenv("GOOGLE_CREDS_JSON"))

intents=discord.Intents.default()
intents.voice_states=True
bot=commands.Bot(command_prefix="!",intents=intents)

# ---------- SHEETS ----------
creds=Credentials.from_service_account_info(CREDS,scopes=["https://www.googleapis.com/auth/spreadsheets"])
gc=gspread.authorize(creds)
sheet=gc.open_by_key(SHEET_ID)

def ws(name,headers):
    try:return sheet.worksheet(name)
    except:
        w=sheet.add_worksheet(title=name,rows=1000,cols=len(headers))
        w.append_row(headers)
        return w

users=ws("users",["id","name","plays"])
meta=ws("meta",["key","value"])

# ---------- MUSIC ----------
ytdlp_opts={
 "format":"bestaudio",
 "default_search":"scsearch",
 "quiet":True,
 "noplaylist":True
}

ffmpeg_opts={"options":"-vn"}

queues={}
idle={}

def add(u):
    rows=users.get_all_records()
    for i,r in enumerate(rows,start=2):
        if str(r["id"])==str(u.id):
            users.update_cell(i,3,int(r["plays"])+1);break
    else: users.append_row([u.id,u.name,1])

async def log(m):
    if not WEBHOOK:return
    async with aiohttp.ClientSession() as s:
        await s.post(WEBHOOK,json={"content":m})

class YTDL:
    @staticmethod
    async def fetch(q):
        loop=asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(ytdlp_opts) as y:
            d=await loop.run_in_executor(None,lambda:y.extract_info(q,download=False))
            if "entries" in d:d=d["entries"][0]
            return d["url"],d["title"]

async def idle_timer(g):
    await asyncio.sleep(IDLE)
    vc=g.voice_client
    if vc and not vc.is_playing(): await vc.disconnect()

async def play_next(g):
    vc=g.voice_client
    if not vc or not vc.is_connected():return
    if not queues.get(g.id):
        bot.loop.create_task(idle_timer(g));return

    url,title,u=queues[g.id].pop(0)
    add(u)

    src=discord.FFmpegPCMAudio(url,**ffmpeg_opts)

    def after(_):
        asyncio.run_coroutine_threadsafe(play_next(g),bot.loop)

    vc.play(src,after=after)

# ---------- CMDS ----------
@bot.tree.command()
async def play(i:discord.Interaction,q:str):
    if not i.user.voice:
        await i.response.send_message("join vc",ephemeral=True);return

    await i.response.defer(ephemeral=True)

    vc=i.guild.voice_client
    if not vc or not vc.is_connected():
        vc=await i.user.voice.channel.connect(reconnect=True)

    url,title=await YTDL.fetch(q)
    queues.setdefault(i.guild.id,[]).append((url,title,i.user))

    if not vc.is_playing():
        await play_next(i.guild)

    await i.followup.send(title,ephemeral=True)

@bot.tree.command()
async def stop(i:discord.Interaction):
    queues[i.guild.id]=[]
    if i.guild.voice_client: await i.guild.voice_client.disconnect()
    await i.response.send_message("stopped",ephemeral=True)

@bot.tree.command()
async def skip(i:discord.Interaction):
    vc=i.guild.voice_client
    if vc: vc.stop()
    await i.response.send_message("skipped",ephemeral=True)

@bot.tree.command()
async def queue(i:discord.Interaction):
    q=queues.get(i.guild.id,[])
    await i.response.send_message("\n".join(x[1] for x in q[:10]) or "empty",ephemeral=True)

@bot.tree.command()
async def ping(i:discord.Interaction):
    await i.response.send_message(f"{round(bot.latency*1000)}ms",ephemeral=True)

# ---------- EVENTS ----------
@bot.event
async def on_ready():
    await bot.tree.sync()
    bot.loop.create_task(restart())
    print("ONLINE")

@bot.event
async def on_guild_join(g): await log(f"joined {g.name}")
@bot.event
async def on_guild_remove(g): await log(f"left {g.name}")

# ---------- DAILY RESTART ----------
async def restart():
    tz=pytz.timezone(TZ)
    while True:
        n=datetime.now(tz)
        t=n.replace(hour=3,minute=0,second=0,microsecond=0)
        if n>=t:t+=timedelta(days=1)
        await asyncio.sleep((t-n).total_seconds())
        os._exit(0)

bot.run(TOKEN)
