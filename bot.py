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
DAILY_HOUR_UTC = int(os.getenv("DAILY_HOUR_UTC", "12"))  # hora UTC para el resumen diario

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

announced_matches = set()
active_polls = {}
daily_announced_dates = set()

TIMEZONES = {
    "🇦🇷 ARG": -3,
    "🇧🇷 BRA": -3,
    "🇨🇱 CHI": -4,
    "🇲🇽 MEX": -6,
    "🇨🇴 COL": -5,
    "🇵🇪 PER": -5,
}

STAGE_NAMES = {
    "GROUP_STAGE": "Fase de Grupos",
    "LAST_16": "Octavos de Final",
    "QUARTER_FINALS": "Cuartos de Final",
    "SEMI_FINALS": "Semifinales",
    "THIRD_PLACE": "Tercer Puesto",
    "FINAL": "⭐ FINAL",
}

STAGE_COLORS = {
    "GROUP_STAGE": 0x3498DB,
    "LAST_16": 0x9B59B6,
    "QUARTER_FINALS": 0xE67E22,
    "SEMI_FINALS": 0xE74C3C,
    "THIRD_PLACE": 0xCD853F,
    "FINAL": 0xF1C40F,
}

def format_times(utc_str):
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        lines = []
        for label, offset in TIMEZONES.items():
            local = dt + timedelta(hours=offset)
            lines.append(f"{label}: `{local.strftime('%d/%m %H:%M')}`")
        return "\n".join(lines)
    except Exception:
        return utc_str

def get_stage(match):
    return match.get("stage", "GROUP_STAGE")

def get_color(match):
    return STAGE_COLORS.get(get_stage(match), 0x3498DB)

def get_stage_name(match):
    stage = get_stage(match)
    group = match.get("group") or ""
    name = STAGE_NAMES.get(stage, stage.replace("_", " ").title())
    if group:
        name += f" — {group}"
    return name

# ─────────────────────────────
#  HELPERS API
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
    """Trae partidos de una fecha específica (YYYY-MM-DD)."""
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
    params = {"status": "SCHEDULED", "limit": 10}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("matches", [])

# ─────────────────────────────
#  EMBEDS
# ─────────────────────────────

def build_result_embed(match):
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    sh = match["score"]["fullTime"]["home"]
    sa = match["score"]["fullTime"]["away"]

    if sh > sa:
        resultado = f"🏆 **{home}** ganó el partido"
        color = 0x2ECC71
    elif sa > sh:
        resultado = f"🏆 **{away}** ganó el partido"
        color = 0x2ECC71
    else:
        resultado = "🤝 El partido terminó en **empate**"
        color = 0xF1C40F

    embed = discord.Embed(color=color)
    embed.set_author(name=f"⚽ Resultado Final — {get_stage_name(match)}")
    embed.title = f"{home}  {sh} — {sa}  {away}"
    embed.description = resultado

    if match["score"].get("halfTime"):
        ht_h = match["score"]["halfTime"].get("home", "?")
        ht_a = match["score"]["halfTime"].get("away", "?")
        embed.add_field(name="Medio tiempo", value=f"{ht_h} — {ht_a}", inline=True)

    embed.set_footer(text="Mundial 2026 • Resultados en vivo")
    embed.timestamp = datetime.now(timezone.utc)
    return embed

def build_upcoming_embed(match):
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    utc = match.get("utcDate", "")
    times = format_times(utc)
    color = get_color(match)

    embed = discord.Embed(color=color)
    embed.set_author(name=f"📅 Partido de hoy — {get_stage_name(match)}")
    embed.title = f"⚽  {home}  🆚  {away}"
    embed.add_field(name="🕐 Horarios", value=times, inline=False)
    embed.set_footer(text="Mundial 2026")
    return embed

def build_poll_embed(match):
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    utc = match.get("utcDate", "")
    times = format_times(utc)
    color = get_color(match)

    embed = discord.Embed(color=color)
    embed.set_author(name=f"🗳️ ¿Quién va a ganar? — {get_stage_name(match)}")
    embed.title = f"{home}  🆚  {away}"
    embed.description = (
        f"🇦 → **{home}**\n"
        f"🇧 → **Empate**\n"
        f"🇨 → **{away}**\n\n"
        f"📊 Votá con las reacciones de abajo"
    )
    embed.add_field(name="🕐 Horarios", value=times, inline=False)
    embed.set_footer(text="Mundial 2026 • Abre 1h antes del partido")
    return embed

# ─────────────────────────────
#  ENVIO DIARIO AUTOMATICO
# ─────────────────────────────

async def send_daily_matches(channel):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    matches = await fetch_matches_by_date(today)
    scheduled = [m for m in matches if m.get("status") in ("SCHEDULED", "TIMED")]

    if not scheduled:
        await channel.send("📅 **No hay partidos del Mundial hoy.**")
        return

    header = discord.Embed(
        title="📋 Partidos del Mundial de hoy",
        description=f"Hay **{len(scheduled)}** partido{'s' if len(scheduled) != 1 else ''} programado{'s' if len(scheduled) != 1 else ''} para hoy.",
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc)
    )
    header.set_footer(text="Mundial 2026")
    await channel.send(embed=header)

    for m in scheduled:
        embed = build_upcoming_embed(m)
        msg = await channel.send(embed=embed)
        await msg.add_reaction("⚽")
        await msg.add_reaction("🔥")
        await asyncio.sleep(0.5)

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
#  TAREA: RESULTADOS AUTOMATICOS
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
#  TAREA: POLLS AUTOMATICAS
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
    """Muestra los partidos de hoy manualmente."""
    await send_daily_matches(ctx.channel)

@bot.command(name="proximos")
async def proximos(ctx):
    matches = await fetch_upcoming_matches()
    if not matches:
        await ctx.send("No hay partidos programados próximamente.")
        return
    await ctx.send("📅 **Próximos partidos del Mundial:**")
    for m in matches[:5]:
        embed = build_upcoming_embed(m)
        await ctx.send(embed=embed)

@bot.command(name="resultados")
async def resultados(ctx):
    matches = await fetch_matches(status="FINISHED")
    if not matches:
        await ctx.send("No hay resultados disponibles todavía.")
        return
    await ctx.send("📊 **Últimos resultados del Mundial:**")
    for m in matches[-5:]:
        embed = build_result_embed(m)
        await ctx.send(embed=embed)

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
