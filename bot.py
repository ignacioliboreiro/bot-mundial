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

TIMEZONES = {
    "🇦🇷": ("ARG", -3),
    "🇧🇷": ("BRA", -3),
    "🇨🇱": ("CHI", -4),
    "🇲🇽": ("MEX", -6),
    "🇨🇴": ("COL", -5),
    "🇵🇪": ("PER", -5),
    "🇺🇾": ("URU", -3),
    "🇻🇪": ("VEN", -4),
}

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
        items = list(TIMEZONES.items())
        for i, (flag, (code, offset)) in enumerate(items):
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

# ─────────────────────────────
#  API
# ─────────────────────────────

async def fetch_matches(status="FINISHED"):
    url = f"https://api.football-data.org/v4/competitions/{COMPETITION_ID}/matches"
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    params = {"status": status}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("matches", [])

async def fetch_matches_by_date(date_str):
    url = f"https://api.football-data.org/v4/competitions/{COMPETITION_ID}/matches"
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    params = {"dateFrom": date_str, "dateTo": date_str}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("matches", [])

async def fetch_upcoming_matches():
    url = f"https://api.football-data.org/v4/competitions/{COMPETITION_ID}/matches"
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    params = {"status": "SCHEDULED,TIMED", "limit": 10}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("matches", [])

# ─────────────────────────────
#  EMBEDS MODERNOS
# ─────────────────────────────

def build_today_header(matches, today_dt):
    fecha = format_date_es(today_dt)
    color = 0x5865F2

    # Si hay final o semifinal, cambiar color
    for m in matches:
        stage = get_stage(m)
        if stage == "FINAL":
            color = 0xFFD700
        elif stage == "SEMI_FINALS":
            color = 0xE74C3C

    embed = discord.Embed(color=color)
    embed.set_author(name="🌍  MUNDIAL 2026  •  Partidos del Día")
    embed.title = f"📅  {fecha}"
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

    embed.title = f"⚽  {home}  🆚  {away}"

    embed.add_field(
        name="🕐  Horario central",
        value=f"**`{utc_time}`**",
        inline=False
    )
    embed.add_field(name="🌎  Latinoamérica", value=col1, inline=True)
    embed.add_field(name="\u200b", value=col2, inline=True)
    embed.set_footer(text="Mundial 2026  •  Votá quién cree que gana 👇")
    return embed

def build_result_embed(match):
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    sh = match["score"]["fullTime"]["home"]
    sa = match["score"]["fullTime"]["away"]
    stage_name = get_stage_name(match)
    stage_emoji = get_stage_emoji(match)

    if sh > sa:
        resultado = f"🏆  **{home}** se llevó la victoria"
        color = 0x2ECC71
        winner_display = f"**{home}  {sh}** — {sa}  {away}"
    elif sa > sh:
        resultado = f"🏆  **{away}** se llevó la victoria"
        color = 0x2ECC71
        winner_display = f"{home}  {sh} — **{sa}  {away}**"
    else:
        resultado = "🤝  El partido terminó en **empate**"
        color = 0xF1C40F
        winner_display = f"{home}  **{sh} — {sa}**  {away}"

    embed = discord.Embed(color=color)
    embed.set_author(name=f"🔔  RESULTADO FINAL  •  {stage_emoji} {stage_name}")
    embed.title = winner_display
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
    embed.title = f"🗳️  {home}  🆚  {away}"
    embed.description = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🇦  →  **{home}**\n"
        f"🇧  →  **Empate**\n"
        f"🇨  →  **{away}**\n"
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
    today = today_dt.strftime("%Y-%m-%d")
    matches = await fetch_matches_by_date(today)
    scheduled = [m for m in matches if m.get("status") in ("SCHEDULED", "TIMED", "IN_PLAY", "PAUSED")]

    if not scheduled:
        embed = discord.Embed(
            color=0x5865F2,
            title="📅  Sin partidos hoy",
            description=f"No hay partidos del Mundial programados para hoy.\n**{format_date_es(today_dt)}**"
        )
        embed.set_footer(text="Mundial 2026")
        await channel.send(embed=embed)
        return

    header = build_today_header(scheduled, today_dt)
    await channel.send(embed=header)
    await asyncio.sleep(0.5)

    for i, m in enumerate(scheduled, 1):
        embed = build_match_embed(m, index=i, total=len(scheduled))
        msg = await channel.send(embed=embed)
        await msg.add_reaction("🇦")
        await msg.add_reaction("🇧")
        await msg.add_reaction("🇨")
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
                print(f"[BOT] Resumen diario enviado para {today}")

# ─────────────────────────────
#  RESULTADOS AUTOMATICOS
# ─────────────────────────────

@tasks.loop(minutes=2)
async def check_results():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return
    matches = await fetch_matches(status="FINISHED")
    for match in matches:
        match_id = match["id"]
        if match_id in announced_matches:
            continue
        announced_matches.add(match_id)
        embed = build_result_embed(match)
        await channel.send(embed=embed)
        print(f"[BOT] Resultado: {match['homeTeam']['name']} vs {match['awayTeam']['name']}")

# ─────────────────────────────
#  POLLS AUTOMATICAS
# ─────────────────────────────

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
        utc_date = match.get("utcDate", "")
        try:
            dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
        except Exception:
            continue
        diff_minutes = (dt - now).total_seconds() / 60
        if 0 < diff_minutes <= 60:
            embed = build_poll_embed(match)
            msg = await channel.send(embed=embed)
            await msg.add_reaction("🇦")
            await msg.add_reaction("🇧")
            await msg.add_reaction("🇨")
            active_polls[match_id] = msg.id
            print(f"[BOT] Poll: {match['homeTeam']['name']} vs {match['awayTeam']['name']}")

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
        embed = build_match_embed(m, index=i, total=min(5, len(matches)))
        await ctx.send(embed=embed)
        await asyncio.sleep(0.5)

@bot.command(name="resultados")
async def resultados(ctx):
    matches = await fetch_matches(status="FINISHED")
    if not matches:
        await ctx.send("No hay resultados disponibles todavía.")
        return
    for m in matches[-5:]:
        embed = build_result_embed(m)
        await ctx.send(embed=embed)
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
        "homeTeam": {"name": home},
        "awayTeam": {"name": away},
        "utcDate": datetime.now(timezone.utc).isoformat(),
        "stage": "GROUP_STAGE",
        "group": ""
    }
    embed = build_poll_embed(mock_match)
    msg = await ctx.send(embed=embed)
    await msg.add_reaction("🇦")
    await msg.add_reaction("🇧")
    await msg.add_reaction("🇨")

# ─────────────────────────────
#  EVENTOS
# ─────────────────────────────

@bot.event
async def on_ready():
    print(f"[BOT] Conectado como {bot.user} ({bot.user.id})")
    check_results.start()
    check_upcoming_polls.start()
    daily_schedule_sender.start()

bot.run(TOKEN)
