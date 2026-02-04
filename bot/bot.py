import os, asyncio, discord, yt_dlp, aiohttp, gspread, pytz, json
from discord.ext import commands
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from web import keep_alive

TOKEN = os.getenv("TOKEN")
SHEET_ID = os.getenv("SHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
GUILD_LOG_WEBHOOK = os.getenv("GUILD_LOG_WEBHOOK")
VOICE_IDLE_SECONDS = int(os.getenv("VOICE_IDLE_SECONDS","120"))
TZ = os.getenv("TZ","UTC")

intents = discord.Intents.default()
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

# -------- GOOGLE SHEETS --------
creds = Credentials.from_service_account_info(
    json.loads(GOOGLE_CREDS_JSON),
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SHEET_ID)

def get_ws(name, headers):
    try:
        return sheet.worksheet(name)
    except:
        ws = sheet.add_worksheet(title=name, rows=1000, cols=len(headers))
        ws.append_row(headers)
        return ws

users_ws = get_ws("users",["user_id","name","plays"])
meta_ws = get_ws("meta",["key","value"])

# -------- MUSIC --------
ytdlp_opts = {
 "format":"bestaudio/best",
 "quiet":True,
 "default_search":"scsearch",
 "noplaylist":True
}

ffmpeg_opts = {
 "options":"-vn -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
}

queues = {}
idle_tasks = {}

# -------- STATS --------
def add_play(u):
    rows = users_ws.get_all_records()
    for i,r in enumerate(rows,start=2):
        if str(r["user_id"]) == str(u.id):
            users_ws.update_cell(i,3,int(r["plays"])+1)
            break
    else:
        users_ws.append_row([u.id,u.name,1])

    meta = {r["key"]:r["value"] for r in meta_ws.get_all_records()}
    total = int(meta.get("total",0))+1
    if meta:
        meta_ws.update("B2",total)
    else:
        meta_ws.append_row(["total",total])

# -------- LOG --------
async def guild_log(msg):
    if not GUILD_LOG_WEBHOOK: return
    async with aiohttp.ClientSession() as s:
        await s.post(GUILD_LOG_WEBHOOK,json={"content":msg})

# -------- IDLE --------
async def idle_timer(g):
    await asyncio.sleep(VOICE_IDLE_SECONDS)
    vc = g.voice_client
    if vc and not vc.is_playing():
        await vc.disconnect()

class YTDL:
    @staticmethod
    async def fetch(q):
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(ytdlp_opts) as y:
            d = await loop.run_in_executor(None, lambda:y.extract_info(q,download=False))
            if "entries" in d: d = d["entries"][0]
            return d["url"], d.get("title","Unknown")

# -------- PLAYER --------
async def play_next(g):
    vc = g.voice_client
    if not vc or not vc.is_connected() or not queues.get(g.id):
        return

    url,title,u = queues[g.id].pop(0)
    add_play(u)

    src = discord.FFmpegPCMAudio(url,**ffmpeg_opts)

    def after(_):
        asyncio.run_coroutine_threadsafe(play_next(g),bot.loop)

    vc.play(src,after=after)

# -------- COMMANDS --------
@bot.tree.command(name="play")
async def play(i:discord.Interaction,query:str):
    if not i.user.voice:
        await i.response.send_message("Join voice first",ephemeral=True); return

    await i.response.defer(ephemeral=True)

    vc = i.guild.voice_client
    if not vc:
        vc = await i.user.voice.channel.connect()
        await asyncio.sleep(2)

    url,title = await YTDL.fetch(query)
    queues.setdefault(i.guild.id,[]).append((url,title,i.user))

    if not vc.is_playing():
        await play_next(i.guild)

    await i.followup.send(title,ephemeral=True)

@bot.tree.command(name="stop")
async def stop(i:discord.Interaction):
    queues[i.guild.id]=[]
    if i.guild.voice_client:
        await i.guild.voice_client.disconnect()
    await i.response.send_message("Stopped",ephemeral=True)

@bot.tree.command(name="skip")
async def skip(i:discord.Interaction):
    vc=i.guild.voice_client
    if vc: vc.stop()
    await i.response.send_message("Skipped",ephemeral=True)

@bot.tree.command(name="queue")
async def queue(i:discord.Interaction):
    q=queues.get(i.guild.id,[])
    await i.response.send_message("\n".join(x[1] for x in q[:10]) or "Empty",ephemeral=True)

@bot.tree.command(name="nowplaying")
async def np(i:discord.Interaction):
    vc=i.guild.voice_client
    await i.response.send_message("Playing" if vc and vc.is_playing() else "Nothing",ephemeral=True)

@bot.tree.command(name="ping")
async def ping(i:discord.Interaction):
    await i.response.send_message(f"{round(bot.latency*1000)}ms",ephemeral=True)

@bot.tree.command(name="invite")
async def invite(i:discord.Interaction):
    url=discord.utils.oauth_url(bot.user.id)
    await i.response.send_message(url,ephemeral=True)

# -------- DAILY RESTART --------
async def daily_restart():
    tz=pytz.timezone(TZ)
    while True:
        now=datetime.now(tz)
        t=now.replace(hour=3,minute=0,second=0,microsecond=0)
        if now>=t: t+=timedelta(days=1)
        await asyncio.sleep((t-now).total_seconds())
        os._exit(0)

@bot.event
async def on_ready():
    keep_alive()
    bot.loop.create_task(daily_restart())
    await bot.tree.sync()
    print("online")

@bot.event
async def on_guild_join(g): await guild_log(f"Joined {g.name}")
@bot.event
async def on_guild_remove(g): await guild_log(f"Left {g.name}")

bot.run(TOKEN,reconnect=True)
