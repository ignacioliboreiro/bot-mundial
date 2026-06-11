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

STAGE_NAMES = {
    "GROUP_STAGE": "Fase de Grupos",
    "LAST_16": "Octavos de Final",
    "QUARTER_FINALS": "Cuartos de Final",
    "SEMI_FINALS": "Semifinales",
    "THIRD_PLACE": "Tercer Puesto",
    "FINAL": "GRAN FINAL",
}

STAGE_COLORS = {
    "GROUP_STAGE": 0x5865F2,
    "LAST_16": 0x9B59B6,
    "QUARTER_FINALS": 0xE67E22,
    "SEMI_FINALS": 0xE74C3C,
    "THIRD_PLACE": 0xCD853F,
    "FINAL": 0xFFD700,
}

STAGE_EMOJI = {
    "GROUP_STAGE": "🏟️",
    "LAST_16": "⚔️",
    "QUARTER_FINALS": "🔥",
    "SEMI_FINALS": "💥",
    "THIRD_PLACE": "🥉",
    "FINAL": "🏆",
}

# Banderas por país (nombre en inglés de la API)
TEAM_FLAGS = {
    "Argentina": "🇦🇷", "Brazil": "🇧🇷", "Mexico": "🇲🇽", "Uruguay": "🇺🇾",
    "Colombia": "🇨🇴", "Chile": "🇨🇱", "Peru": "🇵🇪", "Venezuela": "🇻🇪",
    "Ecuador": "🇪🇨", "Bolivia": "🇧🇴", "Paraguay": "🇵🇾", "Panama": "🇵🇦",
    "Costa Rica": "🇨🇷", "Honduras": "🇭🇳", "Guatemala": "🇬🇹", "El Salvador": "🇸🇻",
    "United States": "🇺🇸", "Canada": "🇨🇦",
    "Germany": "🇩🇪", "France": "🇫🇷", "Spain": "🇪🇸", "Portugal": "🇵🇹",
    "England": "󠁧󠁢󠁥󠁮󠁧󠁿🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Netherlands": "🇳🇱", "Belgium": "🇧🇪",
    "Italy": "🇮🇹", "Croatia": "🇭🇷", "Serbia": "🇷🇸", "Poland": "🇵🇱",
    "Switzerland": "🇨🇭", "Austria": "🇦🇹", "Denmark": "🇩🇰", "Sweden": "🇸🇪",
    "Norway": "🇳🇴", "Czechia": "🇨🇿", "Slovakia": "🇸🇰", "Hungary": "🇭🇺",
    "Romania": "🇷🇴", "Ukraine": "🇺🇦", "Turkey": "🇹🇷", "Greece": "🇬🇷",
    "Morocco": "🇲🇦", "Senegal": "🇸🇳", "Nigeria": "🇳🇬", "Ghana": "🇬🇭",
    "Cameroon": "🇨🇲", "Egypt": "🇪🇬", "Tunisia": "🇹🇳", "Algeria": "🇩🇿",
    "South Africa": "🇿🇦", "Mali": "🇲🇱", "Ivory Coast": "🇨🇮",
    "Japan": "🇯🇵", "South Korea": "🇰🇷", "Australia": "🇦🇺", "Iran": "🇮🇷",
    "Saudi Arabia": "🇸🇦", "Qatar": "🇶🇦", "China": "🇨🇳", "Indonesia": "🇮🇩",
    "New Zealand": "🇳🇿",
    "Bosnia-Herzegovina": "🇧🇦", "Slovenia": "🇸🇮", "Albania": "🇦🇱",
}

def get_flag(team_name):
    return TEAM_FLAGS.get(team_name, "🏳️")

DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES_ES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

def format_date_es(dt):
    dia = DIAS_ES[dt.weekday()]
    return f"{dia} {dt.day} de {MESES_ES[dt.month]} {dt.year}"

def format_times(utc_str):
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
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
        return utc_str, ""

def get_stage(match):
    return match.get("stage", "GROUP_STAGE")

def get_color(match):
    return STAGE_COLORS.get(get_stage(match), 0x5865F2)

def get_stage_name(match):
    stage = get_stage(match)
    group = match.get("group") or ""
    name = STAGE_NAMES.get(stage, stage.replace("_", " ").title())
    if group and "GROUP" in stage:
        group_letter = group.replace("Group ", "").replace("GROUP_", "")
        name = f"Grupo {group_letter}"
    return name

def get_stage_emoji(match):
    return STAGE_EMOJI.get(get_stage(match), "⚽")

def is_today(utc_str):
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        today = datetime.now(timezone.utc).date()
        return dt.date() == today
    except Exception:
        return False

# ─────────────────────────────
#  API
# ─────────────────────────────

async def fetch_all_matches(status="SCHEDULED,TIMED"):
    url = f"https://api.football-data.org/v4/competitions/{COMPETITION_ID}/matches"
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    params = {"status": status, "limit": 100}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("matches", [])

async def fetch_today_matches():
    """Trae partidos de hoy usando dateFrom/dateTo — más confiable que filtrar por status."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = f"https://api.football-data.org/v4/competitions/{COMPETITION_ID}/matches"
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    params = {"dateFrom": today, "dateTo": today}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                print(f"[API ERROR] fetch_today_matches: {resp.status}")
                return []
            data = await resp.json()
            matches = data.get("matches", [])
            print(f"[BOT] Partidos de hoy encontrados: {len(matches)} → {[m['homeTeam']['name']+' vs '+m['awayTeam']['name'] for m in matches]}")
            return [m for m in matches if m.get("status") in ("SCHEDULED", "TIMED", "IN_PLAY", "PAUSED")]

async def fetch_finished_matches():
    return await fetch_all_matches("FINISHED")

async def fetch_upcoming_matches():
    matches = await fetch_all_matches("SCHEDULED,TIMED")
    return matches[:10]

# ─────────────────────────────
#  EMBEDS
# ─────────────────────────────

def build_today_header(matches, today_dt):
    color = 0x5865F2
    for m in matches:
        stage = get_stage(m)
        if stage == "FINAL":
            color = 0xFFD700
        elif stage == "SEMI_FINALS":
            color = 0xE74C3C

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

def build_match_embed(match, index=None, total=None):
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    home_flag = get_flag(home)
    away_flag = get_flag(away)
    utc = match.get("utcDate", "")
    col1, col2 = format_times(utc)
    color = get_color(match)
    stage_name = get_stage_name(match)
    stage_emoji = get_stage_emoji(match)

    try:
        dt = datetime.fromisoformat(utc.replace("Z", "+00:00"))
        utc_time = dt.strftime("%H:%M UTC")
        fecha_str = format_date_es(dt)
    except Exception:
        utc_time = "?"
        fecha_str = ""

    counter = f"Partido {index}/{total}  •  " if index and total else ""

    embed = discord.Embed(color=color)
    embed.set_author(name=f"{counter}{stage_emoji}  {stage_name}  •  {fecha_str}")
    embed.title = f"{home_flag} {home}  🆚  {away} {away_flag}"
    embed.add_field(name="🕐  Horario central", value=f"**`{utc_time}`**", inline=False)
    embed.add_field(name="🌎  Latinoamérica", value=col1, inline=True)
    embed.add_field(name="\u200b", value=col2, inline=True)
    embed.set_footer(text=f"Mundial 2026  •  {home_flag} {home}  vs  {away_flag} {away}")
    return embed

def build_result_embed(match):
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    home_flag = get_flag(home)
    away_flag = get_flag(away)
    sh = match["score"]["fullTime"]["home"]
    sa = match["score"]["fullTime"]["away"]
    stage_name = get_stage_name(match)
    stage_emoji = get_stage_emoji(match)

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
    embed.set_author(name=f"🔔  RESULTADO FINAL  •  {stage_emoji} {stage_name}")
    embed.title = f"{home_flag} {home}  {sh} — {sa}  {away} {away_flag}"
    embed.description = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{resultado}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    if match["score"].get("halfTime"):
        ht_h = match["score"]["halfTime"].get("home", "?")
        ht_a = match["score"]["halfTime"].get("away", "?")
        embed.add_field(name="⏱️  Primer tiempo", value=f"`{ht_h} — {ht_a}`", inline=True)
        embed.add_field(name="⏱️  Segundo tiempo", value=f"`{sh} — {sa}`", inline=True)
    embed.set_footer(text="Mundial 2026  •  Resultado oficial")
    embed.timestamp = datetime.now(timezone.utc)
    return embed

def build_poll_embed(match, index=None, total=None):
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    home_flag = get_flag(home)
    away_flag = get_flag(away)
    utc = match.get("utcDate", "")
    col1, col2 = format_times(utc)
    color = get_color(match)
    stage_name = get_stage_name(match)
    stage_emoji = get_stage_emoji(match)

    try:
        dt = datetime.fromisoformat(utc.replace("Z", "+00:00"))
        utc_time = dt.strftime("%H:%M UTC")
    except Exception:
        utc_time = "?"

    counter = f"Partido {index}/{total}  •  " if index and total else ""

    embed = discord.Embed(color=color)
    embed.set_author(name=f"{counter}{stage_emoji}  {stage_name}  •  ¿Quién ganará?")
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
    scheduled = await fetch_today_matches()

    if not scheduled:
        embed = discord.Embed(
            color=0x5865F2,
            title="📅  Sin partidos hoy",
            description=f"No hay partidos del Mundial programados para hoy.\n**{format_date_es(today_dt)}**"
        )
        embed.set_footer(text="Mundial 2026")
        await channel.send(embed=embed)
        return

    await channel.send(embed=build_today_header(scheduled, today_dt))
    await asyncio.sleep(0.5)

    for i, m in enumerate(scheduled, 1):
        home_flag = get_flag(m["homeTeam"]["name"])
        away_flag = get_flag(m["awayTeam"]["name"])
        embed = build_match_embed(m, index=i, total=len(scheduled))
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

@tasks.loop(minutes=2)
async def check_results():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return
    matches = await fetch_finished_matches()
    for match in matches:
        match_id = match["id"]
        if match_id in announced_matches:
            continue
        announced_matches.add(match_id)
        embed = build_result_embed(match)
        await channel.send(embed=embed)

@tasks.loop(minutes=5)
async def check_upcoming_polls():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return
    matches = await fetch_upcoming_matches()
    now = datetime.now(timezone.utc)
    for match in matches:
        match_id = match["id"]
        if match_id in active_polls:
            continue
        try:
            dt = datetime.fromisoformat(match.get("utcDate", "").replace("Z", "+00:00"))
        except Exception:
            continue
        diff_minutes = (dt - now).total_seconds() / 60
        if 0 < diff_minutes <= 60:
            home_flag = get_flag(match["homeTeam"]["name"])
            away_flag = get_flag(match["awayTeam"]["name"])
            embed = build_poll_embed(match)
            msg = await channel.send(embed=embed)
            await msg.add_reaction(home_flag)
            await msg.add_reaction("🤝")
            await msg.add_reaction(away_flag)
            active_polls[match_id] = msg.id

# ─────────────────────────────
#  COMANDOS
# ─────────────────────────────

@bot.command(name="hoy")
async def hoy(ctx):
    await send_daily_matches(ctx.channel)

@bot.command(name="proximos")
async def proximos(ctx):
    matches = await fetch_upcoming_matches()
    if not matches:
        await ctx.send("No hay partidos programados próximamente.")
        return
    today_dt = datetime.now(timezone.utc)
    await ctx.send(embed=build_today_header(matches[:5], today_dt))
    for i, m in enumerate(matches[:5], 1):
        await ctx.send(embed=build_match_embed(m, index=i, total=min(5, len(matches))))
        await asyncio.sleep(0.5)

@bot.command(name="resultados")
async def resultados(ctx):
    matches = await fetch_finished_matches()
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
    mock_match = {
        "homeTeam": {"name": home}, "awayTeam": {"name": away},
        "utcDate": datetime.now(timezone.utc).isoformat(),
        "stage": "GROUP_STAGE", "group": ""
    }
    home_flag = get_flag(home)
    away_flag = get_flag(away)
    msg = await ctx.send(embed=build_poll_embed(mock_match))
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
