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
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")
COMPETITION_ID = os.getenv("COMPETITION_ID", "WC")
DAILY_HOUR_UTC = int(os.getenv("DAILY_HOUR_UTC", "12"))

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
    "Bosnia-Herzegovina": "🇧🇦", "Slovenia": "🇸🇮", "Albania": "🇦🇱",
    "New Zealand": "🇳🇿",
}

STAGE_COLORS = {
    "GROUP_STAGE": 0x5865F2, "LAST_16": 0x9B59B6,
    "QUARTER_FINALS": 0xE67E22, "SEMI_FINALS": 0xE74C3C,
    "THIRD_PLACE": 0xCD853F, "FINAL": 0xFFD700,
}
STAGE_EMOJI = {
    "GROUP_STAGE": "🏟️", "LAST_16": "⚔️", "QUARTER_FINALS": "🔥",
    "SEMI_FINALS": "💥", "THIRD_PLACE": "🥉", "FINAL": "🏆",
}
STAGE_NAMES = {
    "GROUP_STAGE": "Fase de Grupos", "LAST_16": "Octavos de Final",
    "QUARTER_FINALS": "Cuartos de Final", "SEMI_FINALS": "Semifinales",
    "THIRD_PLACE": "Tercer Puesto", "FINAL": "GRAN FINAL",
}

def get_flag(name): return TEAM_FLAGS.get(name, "🏳️")
def get_stage(m): return m.get("stage", "GROUP_STAGE")
def get_color(m): return STAGE_COLORS.get(get_stage(m), 0x5865F2)
def get_emoji(m): return STAGE_EMOJI.get(get_stage(m), "⚽")

def get_stage_name(m):
    stage = get_stage(m)
    group = m.get("group") or ""
    name = STAGE_NAMES.get(stage, stage.replace("_", " ").title())
    if group and "GROUP" in stage:
        letter = group.replace("Group ", "").replace("GROUP_", "")
        name = f"Grupo {letter}"
    return name

def format_date_es(dt):
    return f"{DIAS_ES[dt.weekday()]} {dt.day} de {MESES_ES[dt.month]} {dt.year}"

def format_times(utc_str):
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        col1, col2 = [], []
        for i, (flag, code, offset) in enumerate(TIMEZONES):
            local = dt + timedelta(hours=offset)
            entry = f"{flag} **{code}** `{local.strftime('%H:%M')}`"
            (col1 if i % 2 == 0 else col2).append(entry)
        return "\n".join(col1), "\n".join(col2)
    except Exception:
        return "?", ""

def get_utc_dt(m):
    try:
        return datetime.fromisoformat(m.get("utcDate", "").replace("Z", "+00:00"))
    except Exception:
        return None

def is_today(m):
    dt = get_utc_dt(m)
    return dt and dt.date() == datetime.now(timezone.utc).date()

# ─────────────────────────────
#  API — DOS LLAMADAS SEPARADAS
# ─────────────────────────────

async def fd_request(params):
    url = f"https://api.football-data.org/v4/competitions/{COMPETITION_ID}/matches"
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                print(f"[API ERROR] {resp.status} params={params}")
                return []
            data = await resp.json()
            return data.get("matches", [])

async def fetch_today_matches():
    """Trae partidos de hoy y del día siguiente hasta las 06:00 UTC (cubre partidos nocturnos LATAM)."""
    scheduled = await fd_request({"status": "SCHEDULED"})
    await asyncio.sleep(1)
    timed = await fd_request({"status": "TIMED"})

    all_matches = {m["id"]: m for m in scheduled + timed}

    now = datetime.now(timezone.utc)
    # Ventana: desde las 00:00 UTC de hoy hasta las 06:00 UTC de mañana
    window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    window_end = window_start + timedelta(hours=30)  # 30hs cubre toda la noche LATAM

    def in_window(m):
        dt = get_utc_dt(m)
        return dt and window_start <= dt <= window_end

    today = [m for m in all_matches.values() if in_window(m)]
    today.sort(key=lambda m: m.get("utcDate", ""))

    print(f"[BOT] Hoy: {len(today)} partidos → {[m['homeTeam']['name']+' vs '+m['awayTeam']['name'] for m in today]}")
    return today

async def fetch_finished():
    return await fd_request({"status": "FINISHED"})

async def fetch_upcoming():
    scheduled = await fd_request({"status": "SCHEDULED"})
    timed = await fd_request({"status": "TIMED"})
    all_m = {m["id"]: m for m in scheduled + timed}
    result = sorted(all_m.values(), key=lambda m: m.get("utcDate", ""))
    return result[:10]

# ─────────────────────────────
#  EMBEDS
# ─────────────────────────────

def build_today_header(matches, today_dt):
    color = max((STAGE_COLORS.get(get_stage(m), 0x5865F2) for m in matches), default=0x5865F2)
    embed = discord.Embed(color=color)
    embed.set_author(name="🌍  MUNDIAL 2026  •  Partidos del Día")
    embed.title = f"📅  {format_date_es(today_dt)}"
    embed.description = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"**{len(matches)}** partido{'s' if len(matches) != 1 else ''} programado{'s' if len(matches) != 1 else ''} para hoy\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    embed.set_footer(text="Horarios en tiempo local de cada país")
    return embed

def build_match_embed(m, index=None, total=None):
    home, away = m["homeTeam"]["name"], m["awayTeam"]["name"]
    hf, af = get_flag(home), get_flag(away)
    home_crest = m["homeTeam"].get("crest") or m["homeTeam"].get("tla", "")
    away_crest = m["awayTeam"].get("crest") or m["awayTeam"].get("tla", "")
    utc = m.get("utcDate", "")
    col1, col2 = format_times(utc)
    dt = get_utc_dt(m)
    utc_time = dt.strftime("%H:%M UTC") if dt else "?"
    fecha = format_date_es(dt) if dt else ""
    counter = f"Partido {index}/{total}  •  " if index and total else ""

    embed = discord.Embed(color=get_color(m))
    embed.set_author(name=f"{counter}{get_emoji(m)}  {get_stage_name(m)}  •  {fecha}")
    embed.title = f"{hf} {home}  🆚  {away} {af}"
    embed.add_field(name="🕐  Horario central", value=f"**`{utc_time}`**", inline=False)
    embed.add_field(name="🌎  Latinoamérica", value=col1, inline=True)
    embed.add_field(name="\u200b", value=col2, inline=True)
    if home_crest and home_crest.startswith("http"):
        embed.set_thumbnail(url=home_crest)
    embed.set_footer(text=f"Mundial 2026  •  {hf} {home} vs {af} {away}", icon_url=away_crest if away_crest and away_crest.startswith("http") else discord.embeds.EmptyEmbed)
    return embed

def build_result_embed(m):
    home, away = m["homeTeam"]["name"], m["awayTeam"]["name"]
    hf, af = get_flag(home), get_flag(away)
    home_crest = m["homeTeam"].get("crest") or ""
    away_crest = m["awayTeam"].get("crest") or ""
    sh = m["score"]["fullTime"]["home"]
    sa = m["score"]["fullTime"]["away"]

    if sh > sa:
        resultado = f"🏆  **{hf} {home}** se llevó la victoria"
        color = 0x2ECC71
        winner_crest = home_crest
    elif sa > sh:
        resultado = f"🏆  **{af} {away}** se llevó la victoria"
        color = 0x2ECC71
        winner_crest = away_crest
    else:
        resultado = "🤝  El partido terminó en **empate**"
        color = 0xF1C40F
        winner_crest = home_crest

    embed = discord.Embed(color=color)
    embed.set_author(name=f"🔔  RESULTADO FINAL  •  {get_emoji(m)} {get_stage_name(m)}")
    embed.title = f"{hf} {home}  {sh} — {sa}  {away} {af}"
    embed.description = f"━━━━━━━━━━━━━━━━━━━━━━━━\n{resultado}\n━━━━━━━━━━━━━━━━━━━━━━━━"

    ht = m.get("score", {}).get("halfTime", {})
    if ht.get("home") is not None:
        embed.add_field(name="⏱️  Primer tiempo", value=f"`{ht['home']} — {ht['away']}`", inline=True)
        embed.add_field(name="⏱️  Final", value=f"`{sh} — {sa}`", inline=True)

    if winner_crest and winner_crest.startswith("http"):
        embed.set_thumbnail(url=winner_crest)
    embed.set_footer(text="Mundial 2026  •  Resultado oficial")
    embed.timestamp = datetime.now(timezone.utc)
    return embed

def build_poll_embed(m, index=None, total=None):
    home, away = m["homeTeam"]["name"], m["awayTeam"]["name"]
    hf, af = get_flag(home), get_flag(away)
    home_crest = m["homeTeam"].get("crest") or ""
    utc = m.get("utcDate", "")
    col1, col2 = format_times(utc)
    dt = get_utc_dt(m)
    utc_time = dt.strftime("%H:%M UTC") if dt else "?"
    counter = f"Partido {index}/{total}  •  " if index and total else ""

    embed = discord.Embed(color=get_color(m))
    embed.set_author(name=f"{counter}{get_emoji(m)}  {get_stage_name(m)}  •  ¿Quién ganará?")
    embed.title = f"🗳️  {hf} {home}  🆚  {af} {away}"
    embed.description = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{hf}  →  **{home}**\n"
        f"🤝  →  **Empate**\n"
        f"{af}  →  **{away}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊  **¡Votá con las reacciones de abajo!**"
    )
    embed.add_field(name="🕐  Horario", value=f"**`{utc_time}`**", inline=False)
    embed.add_field(name="🌎  Latinoamérica", value=col1, inline=True)
    embed.add_field(name="\u200b", value=col2, inline=True)
    if home_crest and home_crest.startswith("http"):
        embed.set_thumbnail(url=home_crest)
    embed.set_footer(text="Mundial 2026  •  Poll abierta 1h antes del partido")
    return embed

# ─────────────────────────────
#  TAREAS
# ─────────────────────────────

async def send_daily_matches(channel):
    today_dt = datetime.now(timezone.utc)
    matches = await fetch_today_matches()

    if not matches:
        embed = discord.Embed(color=0x5865F2, title="📅  Sin partidos hoy",
            description=f"No hay partidos del Mundial para hoy.\n**{format_date_es(today_dt)}**")
        embed.set_footer(text="Mundial 2026")
        await channel.send(embed=embed)
        return

    await channel.send(embed=build_today_header(matches, today_dt))
    await asyncio.sleep(0.5)
    for i, m in enumerate(matches, 1):
        hf, af = get_flag(m["homeTeam"]["name"]), get_flag(m["awayTeam"]["name"])
        msg = await channel.send(embed=build_match_embed(m, i, len(matches)))
        await msg.add_reaction(hf)
        await msg.add_reaction("🤝")
        await msg.add_reaction(af)
        await asyncio.sleep(0.8)

@tasks.loop(minutes=1)
async def daily_schedule_sender():
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    if now.hour == DAILY_HOUR_UTC and now.minute == 0 and today not in daily_announced_dates:
        daily_announced_dates.add(today)
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            await send_daily_matches(channel)

@tasks.loop(minutes=3)
async def check_results():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return
    for m in await fetch_finished():
        mid = m["id"]
        if mid not in announced_matches:
            announced_matches.add(mid)
            await channel.send(embed=build_result_embed(m))

@tasks.loop(minutes=5)
async def check_upcoming_polls():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return
    now = datetime.now(timezone.utc)
    for m in await fetch_upcoming():
        mid = m["id"]
        if mid in active_polls:
            continue
        dt = get_utc_dt(m)
        if dt and 0 < (dt - now).total_seconds() / 60 <= 60:
            hf, af = get_flag(m["homeTeam"]["name"]), get_flag(m["awayTeam"]["name"])
            msg = await channel.send(embed=build_poll_embed(m))
            await msg.add_reaction(hf)
            await msg.add_reaction("🤝")
            await msg.add_reaction(af)
            active_polls[mid] = msg.id

# ─────────────────────────────
#  COMANDOS
# ─────────────────────────────

@bot.command(name="hoy")
async def hoy(ctx):
    await send_daily_matches(ctx.channel)

@bot.command(name="proximos")
async def proximos(ctx):
    matches = await fetch_upcoming()
    if not matches:
        await ctx.send("No hay partidos programados próximamente.")
        return
    await ctx.send(embed=build_today_header(matches[:5], datetime.now(timezone.utc)))
    for i, m in enumerate(matches[:5], 1):
        await ctx.send(embed=build_match_embed(m, i, min(5, len(matches))))
        await asyncio.sleep(0.5)

@bot.command(name="resultados")
async def resultados(ctx):
    matches = await fetch_finished()
    if not matches:
        await ctx.send("No hay resultados disponibles todavía.")
        return
    for m in matches[-5:]:
        await ctx.send(embed=build_result_embed(m))
        await asyncio.sleep(0.5)

@bot.command(name="votar")
@commands.has_permissions(manage_messages=True)
async def votar(ctx, *, partido: str):
    partes = partido.split(" vs ", 1)
    if len(partes) != 2:
        await ctx.send("Formato: `!votar Equipo1 vs Equipo2`")
        return
    home, away = partes[0].strip(), partes[1].strip()
    mock = {"homeTeam": {"name": home}, "awayTeam": {"name": away},
            "utcDate": datetime.now(timezone.utc).isoformat(),
            "stage": "GROUP_STAGE", "group": ""}
    hf, af = get_flag(home), get_flag(away)
    msg = await ctx.send(embed=build_poll_embed(mock))
    await msg.add_reaction(hf)
    await msg.add_reaction("🤝")
    await msg.add_reaction(af)

@bot.event
async def on_ready():
    print(f"[BOT] Conectado como {bot.user} ({bot.user.id})")
    check_results.start()
    check_upcoming_polls.start()
    daily_schedule_sender.start()

bot.run(TOKEN)
