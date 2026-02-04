import os, asyncio, discord, yt_dlp, aiohttp, gspread, pytz, json
from discord.ext import commands
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from web import keep_alive

TOKEN = os.getenv("TOKEN")
SHEET_ID = os.getenv("SHEET_ID")
VOICE_IDLE_SECONDS = int(os.getenv("VOICE_IDLE_SECONDS","120"))
TZ = os.getenv("TZ","UTC")
GUILD_LOG_WEBHOOK = os.getenv("GUILD_LOG_WEBHOOK")

intents = discord.Intents.default()
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- GOOGLE ----------
creds_json = json.loads(os.getenv("GOOGLE_CREDS_JSON"))
creds = Credentials.from_service_account_info(
    creds_json,
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

users_ws = get_ws("users", ["user_id","name","plays"])
meta_ws = get_ws("meta", ["key","value"])

def ensure_meta():
    rows = meta_ws.get_all_records()
    if not rows:
        meta_ws.append_row(["total",0])

ensure_meta()

# ---------- MUSIC ----------
ytdlp_opts = {
    "format":"bestaudio",
    "quiet":True,
    "default_search":"scsearch",
    "noplaylist":True
}

ffmpeg_opts = {"options":"-vn"}

queues = {}
idle_tasks = {}
now_playing = {}

class YTDL:
    @staticmethod
    async def fetch(q):
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(ytdlp_opts) as y:
            data = await loop.run_in_executor(None, lambda:y.extract_info(q,download=False))
            if "entries" in data:
                data = data["entries"][0]
            return data["url"], data.get("title","Unknown")

# ---------- SHEETS ----------
def add_play(user):
    rows = users_ws.get_all_records()
    found = False

    for i,r in enumerate(rows,start=2):
        if str(r["user_id"]) == str(user.id):
            users_ws.update_cell(i,3,int(r["plays"])+1)
            found=True
            break

    if not found:
        users_ws.append_row([user.id,user.name,1])

    meta = meta_ws.get_all_records()
    total = int(meta[0]["value"]) + 1
    meta_ws.update("B2", total)

# ---------- LOG ----------
async def guild_log(msg):
    if not GUILD_LOG_WEBHOOK:
        return
    try:
        async with aiohttp.ClientSession() as s:
            await s.post(GUILD_LOG_WEBHOOK,json={"content":msg},timeout=5)
    except:
        pass

# ---------- PLAYBACK ----------
async def idle_timer(g):
    await asyncio.sleep(VOICE_IDLE_SECONDS)
    vc = g.voice_client
    if vc and not vc.is_playing():
        await vc.disconnect()

async def play_next(g):
    vc = g.voice_client
    q = queues.get(g.id,[])

    if not vc or not q:
        idle_tasks[g.id] = asyncio.create_task(idle_timer(g))
        return

    url,title,user = q.pop(0)
    now_playing[g.id] = title

    try:
        add_play(user)
    except:
        pass

    source = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(url,**ffmpeg_opts),
        volume=0.5
    )

    def after(e):
        asyncio.run_coroutine_threadsafe(play_next(g),bot.loop)

    vc.play(source, after=after)

# ---------- COMMANDS ----------
@bot.tree.command(name="play")
async def play(i:discord.Interaction, query:str):
    if not i.user.voice:
        await i.response.send_message("Join voice first",ephemeral=True)
        return

    await i.response.defer(ephemeral=True)

    vc = i.guild.voice_client or await i.user.voice.channel.connect()

    try:
        url,title = await YTDL.fetch(query)
    except:
        await i.followup.send("Track failed",ephemeral=True)
        return

    queues.setdefault(i.guild.id,[]).append((url,title,i.user))

    if not vc.is_playing():
        await play_next(i.guild)

    await i.followup.send(title,ephemeral=True)

@bot.tree.command(name="stop")
async def stop(i:discord.Interaction):
    queues[i.guild.id]=[]
    now_playing.pop(i.guild.id,None)
    if i.guild.voice_client:
        await i.guild.voice_client.disconnect()
    await i.response.send_message("Stopped",ephemeral=True)

@bot.tree.command(name="skip")
async def skip(i:discord.Interaction):
    vc=i.guild.voice_client
    if vc: vc.stop()
    await i.response.send_message("Skipped",ephemeral=True)

@bot.tree.command(name="queue")
async def queue_cmd(i:discord.Interaction):
    q=queues.get(i.guild.id,[])
    txt="\n".join(f"{n+1}. {x[1]}" for n,x in enumerate(q[:10]))
    await i.response.send_message(txt or "Empty",ephemeral=True)

@bot.tree.command(name="nowplaying")
async def np(i:discord.Interaction):
    await i.response.send_message(now_playing.get(i.guild.id,"Nothing"),ephemeral=True)

@bot.tree.command(name="volume")
async def volume(i:discord.Interaction,val:float):
    vc=i.guild.voice_client
    if vc and vc.source:
        vc.source.volume=max(0,min(val,2))
    await i.response.send_message("Ok",ephemeral=True)

@bot.tree.command(name="ping")
async def ping(i:discord.Interaction):
    await i.response.send_message(f"{round(bot.latency*1000)}ms",ephemeral=True)

@bot.tree.command(name="invite")
async def invite(i:discord.Interaction):
    perms=discord.Permissions(connect=True,speak=True)
    url=discord.utils.oauth_url(bot.user.id,permissions=perms)
    await i.response.send_message(url,ephemeral=True)

# ---------- DAILY RESTART ----------
async def daily_restart():
    tz=pytz.timezone(TZ)
    while True:
        now=datetime.now(tz)
        t=now.replace(hour=3,minute=0,second=0,microsecond=0)
        if now>=t:
            t+=timedelta(days=1)
        await asyncio.sleep((t-now).total_seconds())
        os._exit(0)

# ---------- EVENTS ----------
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

bot.run(TOKEN)
