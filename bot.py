import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import json
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")
COMPETITION_ID = os.getenv("COMPETITION_ID", "WC")  # WC = World Cup

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Almacena partidos ya anunciados y polls activas
announced_matches = set()
active_polls = {}  # match_id -> message_id

# ─────────────────────────────
#  HELPERS API
# ─────────────────────────────

async def fetch_matches(status="LIVE,FINISHED"):
    url = f"https://api.football-data.org/v4/competitions/{COMPETITION_ID}/matches"
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    params = {"status": status}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                print(f"[API ERROR] Status {resp.status}")
                return []
            data = await resp.json()
            return data.get("matches", [])

async def fetch_upcoming_matches():
    url = f"https://api.football-data.org/v4/competitions/{COMPETITION_ID}/matches"
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    params = {"status": "SCHEDULED", "limit": 5}

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
    score_home = match["score"]["fullTime"]["home"]
    score_away = match["score"]["fullTime"]["away"]
    stage = match.get("stage", "").replace("_", " ").title()
    group = match.get("group") or ""

    if score_home > score_away:
        winner = f"🏆 {home} ganó"
        color = 0x57F287
    elif score_away > score_home:
        winner = f"🏆 {away} ganó"
        color = 0x57F287
    else:
        winner = "🤝 Empate"
        color = 0xFEE75C

    embed = discord.Embed(
        title=f"⚽ Resultado Final — {home} vs {away}",
        description=f"**{home}  {score_home} — {score_away}  {away}**\n{winner}",
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="Fase", value=f"{stage} {group}", inline=True)
    embed.set_footer(text="Mundial 2026 • Bot de resultados")
    return embed

def build_poll_embed(match):
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    utc_time = match.get("utcDate", "")
    try:
        dt = datetime.fromisoformat(utc_time.replace("Z", "+00:00"))
        hora = dt.strftime("%d/%m/%Y %H:%M UTC")
    except Exception:
        hora = utc_time

    embed = discord.Embed(
        title=f"🗳️ ¿Quién va a ganar?",
        description=(
            f"**{home}** 🆚 **{away}**\n"
            f"🕐 {hora}\n\n"
            f"🇦 → {home}\n"
            f"🇧 → Empate\n"
            f"🇨 → {away}"
        ),
        color=0x5865F2
    )
    embed.set_footer(text="Votá con las reacciones de abajo | Mundial 2026")
    return embed

# ─────────────────────────────
#  TAREAS PERIÓDICAS
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
        print(f"[BOT] Resultado enviado: {match['homeTeam']['name']} vs {match['awayTeam']['name']}")

@tasks.loop(minutes=5)
async def check_upcoming_polls():
    """Crea una poll ~1h antes de cada partido si no existe ya."""
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
            print(f"[BOT] Poll creada para: {match['homeTeam']['name']} vs {match['awayTeam']['name']}")

# ─────────────────────────────
#  COMANDOS
# ─────────────────────────────

@bot.command(name="proximos")
async def proximos(ctx):
    """Muestra los próximos partidos del Mundial."""
    matches = await fetch_upcoming_matches()
    if not matches:
        await ctx.send("No hay partidos programados próximamente.")
        return

    embed = discord.Embed(title="📅 Próximos partidos del Mundial", color=0x5865F2)
    for m in matches[:5]:
        home = m["homeTeam"]["name"]
        away = m["awayTeam"]["name"]
        utc = m.get("utcDate", "")
        try:
            dt = datetime.fromisoformat(utc.replace("Z", "+00:00"))
            hora = dt.strftime("%d/%m %H:%M UTC")
        except Exception:
            hora = utc
        embed.add_field(name=f"{home} vs {away}", value=hora, inline=False)

    await ctx.send(embed=embed)

@bot.command(name="resultados")
async def resultados(ctx):
    """Muestra los últimos resultados del Mundial."""
    matches = await fetch_matches(status="FINISHED")
    if not matches:
        await ctx.send("No hay resultados disponibles todavía.")
        return

    embed = discord.Embed(title="📊 Últimos resultados del Mundial", color=0x57F287)
    for m in matches[-5:]:
        home = m["homeTeam"]["name"]
        away = m["awayTeam"]["name"]
        sh = m["score"]["fullTime"]["home"]
        sa = m["score"]["fullTime"]["away"]
        embed.add_field(name=f"{home} vs {away}", value=f"**{sh} — {sa}**", inline=False)

    await ctx.send(embed=embed)

@bot.command(name="votar")
@commands.has_permissions(manage_messages=True)
async def votar(ctx, *, partido: str):
    """Crea una poll manual. Uso: !votar Argentina vs Francia"""
    partes = partido.split(" vs ", 1)
    if len(partes) != 2:
        await ctx.send("Formato: `!votar Equipo1 vs Equipo2`")
        return

    home, away = partes[0].strip(), partes[1].strip()
    mock_match = {
        "homeTeam": {"name": home},
        "awayTeam": {"name": away},
        "utcDate": datetime.now(timezone.utc).isoformat()
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

bot.run(TOKEN)
