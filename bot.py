import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
APISPORTS_KEY = os.getenv("APISPORTS_KEY")
DAILY_HOUR_UTC = int(os.getenv("DAILY_HOUR_UTC", "12"))

# ID del Mundial 2026 en api-football
WORLD_CUP_ID = 1

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

announced_matches = set()
active_polls = {}
daily_announced_dates = set()

TIMEZONES = [
    ("🇦🇷", "ARG", -3),
    ("🇧🇷", "BRA", -3),
    ("🇨🇱", "CHI", -4),
    ("🇲🇽", "MEX", -6),
    ("🇨🇴", "COL", -5),
    ("🇵🇪", "PER", -5),
    ("🇺🇾", "URU", -3),
    ("🇻🇪", "VEN", -4),
]

DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES_ES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

TEAM_FLAGS = {
    "Argentina": "🇦🇷", "Brazil": "🇧🇷", "Mexico": "🇲🇽", "Uruguay": "🇺🇾",
    "Colombia": "🇨🇴", "Chile": "🇨🇱", "Peru": "🇵🇪", "Venezuela": "🇻🇪",
    "Ecuador": "🇪🇨", "Bolivia": "🇧🇴", "Paraguay": "🇵🇾", "Panama": "🇵🇦",
    "Costa Rica": "🇨🇷", "Honduras": "🇭🇳", "Guatemala": "🇬🇹",
    "United States": "🇺🇸", "Canada": "🇨🇦",
    "Germany": "🇩🇪", "France": "🇫🇷", "Spain": "🇪🇸", "Portugal": "🇵🇹",
    "Netherlands": "🇳🇱", "Belgium": "🇧🇪", "Italy": "🇮🇹", "Croatia": "🇭🇷",
    "Serbia": "🇷🇸", "Poland": "🇵🇱", "Switzerland": "🇨🇭", "Denmark": "🇩🇰",
    "Czechia": "🇨🇿", "Slovakia": "🇸🇰", "Hungary": "🇭🇺", "Romania": "🇷🇴",
    "Ukraine": "🇺🇦", "Turkey": "🇹🇷", "Greece": "🇬🇷", "Austria": "🇦🇹",
    "Morocco": "🇲🇦", "Senegal": "🇸🇳", "Nigeria": "🇳🇬", "Ghana": "🇬🇭",
    "Cameroon": "🇨🇲", "Egypt": "🇪🇬", "Tunisia": "🇹🇳", "South Africa": "🇿🇦",
    "Japan": "🇯🇵", "South Korea": "🇰🇷", "Australia": "🇦🇺", "Iran": "🇮🇷",
    "Saudi Arabia": "🇸🇦", "Qatar": "🇶🇦", "Indonesia": "🇮🇩",
    "Bosnia": "🇧🇦", "Slovenia": "🇸🇮", "Albania": "🇦🇱",
    "New Zealand": "🇳🇿", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
}

ROUND_COLORS = {
    "Group Stage": 0x5865F2,
    "Round of 16": 0x9B59B6,
    "Quarter-finals": 0xE67E22,
    "Semi-finals": 0xE74C3C,
    "3rd Place Final": 0xCD853F,
    "Final": 0xFFD700,
}

ROUND_EMOJI = {
    "Group Stage": "🏟️",
    "Round of 16": "⚔️",
    "Quarter-finals": "🔥",
    "Semi-finals": "💥",
    "3rd Place Final": "🥉",
    "Final": "🏆",
}

def get_flag(name):
    return TEAM_FLAGS.get(name, "🏳️")

def get_round_color(round_name):
    for key, color in ROUND_COLORS.items():
        if key.lower() in (round_name or "").lower():
            return color
    return 0x5865F2

def get_round_emoji(round_name):
    for key, emoji in ROUND_EMOJI.items():
        if key.lower() in (round_name or "").lower():
            return emoji
    return "⚽"

def format_date_es(dt):
    return f"{DIAS_ES[dt.weekday()]} {dt.day} de {MESES_ES[dt.month]} {dt.year}"

def format_times(timestamp):
    try:
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        col1, col2 = [], []
        for i, (flag, code, offset) in enumerate(TIMEZONES):
            local = dt + timedelta(hours=offset)
            entry = f"{flag} **{code}** `{local.strftime('%H:%M')}`"
            if i % 2 == 0:
                col1.append(entry)
            else:
                col2.append(entry)
        return "\n".join(col1), "\n".join(col2)
    except Exception:
        return "?", ""

def parse_dt(timestamp):
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except Exception:
        return None

# ─────────────────────────────
#  API-FOOTBALL
# ─────────────────────────────

async def api_request(endpoint, params):
    url = f"https://v3.football.api-sports.io/{endpoint}"
    headers = {"x-apisports-key": APISPORTS_KEY}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                print(f"[API ERROR] {endpoint} → {resp.status}")
                return []
            data = await resp.json()
            errors = data.get("errors", {})
            if errors:
                print(f"[API ERRORS] {errors}")
                return []
            return data.get("response", [])

async def get_season():
    """Detecta el año de la temporada activa del Mundial."""
    return 2026

async def fetch_today_matches():
    season = await get_season()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    results = await api_request("fixtures", {
        "league": WORLD_CUP_ID,
        "season": season,
        "date": today,
        "timezone": "UTC"
    })
    print(f"[BOT] Partidos de hoy: {len(results)} → {[r['teams']['home']['name']+' vs '+r['teams']['away']['name'] for r in results]}")
    return [r for r in results if r["fixture"]["status"]["short"] in ("NS", "TBD", "1H", "HT", "2H", "ET", "P")]

async def fetch_finished_today():
    season = await get_season()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    results = await api_request("fixtures", {
        "league": WORLD_CUP_ID,
        "season": season,
        "date": today,
        "timezone": "UTC",
        "status": "FT-AET-PEN"
    })
    return results

async def fetch_live():
    results = await api_request("fixtures", {
        "league": WORLD_CUP_ID,
        "live": "all"
    })
    return results

async def fetch_upcoming():
    season = await get_season()
    results = await api_request("fixtures", {
        "league": WORLD_CUP_ID,
        "season": season,
        "status": "NS",
        "timezone": "UTC"
    })
    return results[:10]

async def fetch_finished():
    season = await get_season()
    results = await api_request("fixtures", {
        "league": WORLD_CUP_ID,
        "season": season,
        "status": "FT",
        "timezone": "UTC"
    })
    return results

# ─────────────────────────────
#  EMBEDS
# ─────────────────────────────

def build_today_header(fixtures, today_dt):
    rounds = set(f["league"]["round"] for f in fixtures)
    color = 0x5865F2
    for r in rounds:
        if "Final" in r:
            color = 0xFFD700
        elif "Semi" in r:
            color = 0xE74C3C

    embed = discord.Embed(color=color)
    embed.set_author(name="🌍  MUNDIAL 2026  •  Partidos del Día")
    embed.title = f"📅  {format_date_es(today_dt)}"
    embed.description = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"**{len(fixtures)}** partido{'s' if len(fixtures) != 1 else ''} programado{'s' if len(fixtures) != 1 else ''} para hoy\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    embed.set_footer(text="Horarios en tiempo local de cada país")
    return embed

def build_match_embed(fixture, index=None, total=None):
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    home_flag = get_flag(home)
    away_flag = get_flag(away)
    ts = fixture["fixture"]["timestamp"]
    round_name = fixture["league"]["round"]
    col1, col2 = format_times(ts)
    color = get_round_color(round_name)
    emoji = get_round_emoji(round_name)

    dt = parse_dt(ts)
    utc_time = dt.strftime("%H:%M UTC") if dt else "?"
    fecha_str = format_date_es(dt) if dt else ""
    counter = f"Partido {index}/{total}  •  " if index and total else ""

    embed = discord.Embed(color=color)
    embed.set_author(name=f"{counter}{emoji}  {round_name}  •  {fecha_str}")
    embed.title = f"{home_flag} {home}  🆚  {away} {away_flag}"
    embed.add_field(name="🕐  Horario central", value=f"**`{utc_time}`**", inline=False)
    embed.add_field(name="🌎  Latinoamérica", value=col1, inline=True)
    embed.add_field(name="\u200b", value=col2, inline=True)
    embed.set_footer(text=f"Mundial 2026  •  {home_flag} {home} vs {away_flag} {away}")
    return embed

def build_result_embed(fixture):
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    home_flag = get_flag(home)
    away_flag = get_flag(away)
    sh = fixture["goals"]["home"] or 0
    sa = fixture["goals"]["away"] or 0
    round_name = fixture["league"]["round"]
    emoji = get_round_emoji(round_name)

    if sh > sa:
        resultado = f"🏆  **{home_flag} {home}** se llevó la victoria"
        color = 0x2ECC71
    elif sa > sh:
        resultado = f"🏆  **{away_flag} {away}** se llevó la victoria"
        color = 0x2ECC71
    else:
        resultado = "🤝  El partido terminó en **empate**"
        color = 0xF1C40F

    embed = discord.Embed(color=color)
    embed.set_author(name=f"🔔  RESULTADO FINAL  •  {emoji} {round_name}")
    embed.title = f"{home_flag} {home}  {sh} — {sa}  {away} {away_flag}"
    embed.description = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{resultado}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    ht = fixture.get("score", {}).get("halftime", {})
    if ht.get("home") is not None:
        embed.add_field(name="⏱️  Primer tiempo", value=f"`{ht['home']} — {ht['away']}`", inline=True)
        embed.add_field(name="⏱️  Final", value=f"`{sh} — {sa}`", inline=True)
    embed.set_footer(text="Mundial 2026  •  Resultado oficial")
    embed.timestamp = datetime.now(timezone.utc)
    return embed

def build_poll_embed(fixture, index=None, total=None):
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    home_flag = get_flag(home)
    away_flag = get_flag(away)
    ts = fixture["fixture"]["timestamp"]
    round_name = fixture["league"]["round"]
    col1, col2 = format_times(ts)
    color = get_round_color(round_name)
    emoji = get_round_emoji(round_name)
    dt = parse_dt(ts)
    utc_time = dt.strftime("%H:%M UTC") if dt else "?"
    counter = f"Partido {index}/{total}  •  " if index and total else ""

    embed = discord.Embed(color=color)
    embed.set_author(name=f"{counter}{emoji}  {round_name}  •  ¿Quién ganará?")
    embed.title = f"🗳️  {home_flag} {home}  🆚  {away_flag} {away}"
    embed.description = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{home_flag}  →  **{home}**\n"
        f"🤝  →  **Empate**\n"
        f"{away_flag}  →  **{away}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊  **¡Votá con las reacciones de abajo!**"
    )
    embed.add_field(name="🕐  Horario", value=f"**`{utc_time}`**", inline=False)
    embed.add_field(name="🌎  Latinoamérica", value=col1, inline=True)
    embed.add_field(name="\u200b", value=col2, inline=True)
    embed.set_footer(text="Mundial 2026  •  Poll abierta 1h antes del partido")
    return embed

# ─────────────────────────────
#  ENVIO DIARIO
# ─────────────────────────────

async def send_daily_matches(channel):
    today_dt = datetime.now(timezone.utc)
    fixtures = await fetch_today_matches()

    if not fixtures:
        embed = discord.Embed(
            color=0x5865F2,
            title="📅  Sin partidos hoy",
            description=f"No hay partidos del Mundial programados para hoy.\n**{format_date_es(today_dt)}**"
        )
        embed.set_footer(text="Mundial 2026")
        await channel.send(embed=embed)
        return

    await channel.send(embed=build_today_header(fixtures, today_dt))
    await asyncio.sleep(0.5)

    for i, f in enumerate(fixtures, 1):
        home_flag = get_flag(f["teams"]["home"]["name"])
        away_flag = get_flag(f["teams"]["away"]["name"])
        embed = build_match_embed(f, index=i, total=len(fixtures))
        msg = await channel.send(embed=embed)
        await msg.add_reaction(home_flag)
        await msg.add_reaction("🤝")
        await msg.add_reaction(away_flag)
        await asyncio.sleep(0.8)

@tasks.loop(minutes=1)
async def daily_schedule_sender():
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    if now.hour == DAILY_HOUR_UTC and now.minute == 0:
        if today not in daily_announced_dates:
            daily_announced_dates.add(today)
            channel = bot.get_channel(CHANNEL_ID)
            if channel:
                await send_daily_matches(channel)

@tasks.loop(minutes=3)
async def check_results():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return
    fixtures = await fetch_finished_today()
    for f in fixtures:
        fid = f["fixture"]["id"]
        if fid in announced_matches:
            continue
        announced_matches.add(fid)
        await channel.send(embed=build_result_embed(f))
        print(f"[BOT] Resultado: {f['teams']['home']['name']} vs {f['teams']['away']['name']}")

@tasks.loop(minutes=5)
async def check_upcoming_polls():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return
    fixtures = await fetch_upcoming()
    now = datetime.now(timezone.utc)
    for f in fixtures:
        fid = f["fixture"]["id"]
        if fid in active_polls:
            continue
        ts = f["fixture"]["timestamp"]
        dt = parse_dt(ts)
        if not dt:
            continue
        diff_minutes = (dt - now).total_seconds() / 60
        if 0 < diff_minutes <= 60:
            home_flag = get_flag(f["teams"]["home"]["name"])
            away_flag = get_flag(f["teams"]["away"]["name"])
            msg = await channel.send(embed=build_poll_embed(f))
            await msg.add_reaction(home_flag)
            await msg.add_reaction("🤝")
            await msg.add_reaction(away_flag)
            active_polls[fid] = msg.id

# ─────────────────────────────
#  COMANDOS
# ─────────────────────────────

@bot.command(name="hoy")
async def hoy(ctx):
    await send_daily_matches(ctx.channel)

@bot.command(name="proximos")
async def proximos(ctx):
    fixtures = await fetch_upcoming()
    if not fixtures:
        await ctx.send("No hay partidos programados próximamente.")
        return
    today_dt = datetime.now(timezone.utc)
    await ctx.send(embed=build_today_header(fixtures[:5], today_dt))
    for i, f in enumerate(fixtures[:5], 1):
        await ctx.send(embed=build_match_embed(f, index=i, total=min(5, len(fixtures))))
        await asyncio.sleep(0.5)

@bot.command(name="resultados")
async def resultados(ctx):
    fixtures = await fetch_finished()
    if not fixtures:
        await ctx.send("No hay resultados disponibles todavía.")
        return
    for f in fixtures[-5:]:
        await ctx.send(embed=build_result_embed(f))
        await asyncio.sleep(0.5)

@bot.command(name="votar")
@commands.has_permissions(manage_messages=True)
async def votar(ctx, *, partido: str):
    partes = partido.split(" vs ", 1)
    if len(partes) != 2:
        await ctx.send("Formato: `!votar Equipo1 vs Equipo2`")
        return
    home, away = partes[0].strip(), partes[1].strip()
    mock = {
        "teams": {"home": {"name": home}, "away": {"name": away}},
        "fixture": {"timestamp": datetime.now(timezone.utc).timestamp()},
        "league": {"round": "Group Stage"}
    }
    home_flag = get_flag(home)
    away_flag = get_flag(away)
    msg = await ctx.send(embed=build_poll_embed(mock))
    await msg.add_reaction(home_flag)
    await msg.add_reaction("🤝")
    await msg.add_reaction(away_flag)

@bot.event
async def on_ready():
    print(f"[BOT] Conectado como {bot.user} ({bot.user.id})")
    check_results.start()
    check_upcoming_polls.start()
    daily_schedule_sender.start()

bot.run(TOKEN)
