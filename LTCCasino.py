# LTCCasino.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiosqlite
import aiohttp
import asyncio
import datetime, pytz
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("MTQxMzg1NTY2MjU0NjYxNjMzMA.GI8hht.GJmVpsrNOL9Yy0iod77a63jm9VfRmYPOh-6QFE")
BLOCKCYPHER_TOKEN = os.getenv("BLOCKCYPHER_TOKEN")
OWNER_WALLET = os.getenv("LfZZjzaUM1oF57hedV1vwPLigVhzkraonk")
ADMIN_WEBHOOK = os.getenv("https://discord.com/api/webhooks/1413855296761237576/mVWYdGEhmLO4h-QXIlW6Dg3XVHDNrVg05fTpt7WmU7NszuoHrf-KGlidYhCko03RHypu")

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Database initialization ---
async def init_db():
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY,
                wallet_address TEXT,
                balance REAL DEFAULT 0,
                timezone TEXT DEFAULT 'UTC',
                daily_wager REAL DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS games(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER,
                game_type TEXT,
                wager REAL,
                status TEXT DEFAULT 'open'
            )
        """)
        await db.commit()

@bot.event
async def on_ready():
    await init_db()
    print(f"Logged in as {bot.user}")
    check_rakeback.start()

# --- Helper functions ---
async def send_admin_log(message):
    async with aiohttp.ClientSession() as session:
        await session.post(ADMIN_WEBHOOK, json={"content": message})

async def get_user(user_id):
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT * FROM users WHERE id=?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def update_balance(user_id, amount):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE id=?", (amount, user_id))
        await db.commit()

# --- Deposit ---
@app_commands.command(name="deposit", description="Get your LTC deposit address")
async def deposit(interaction: discord.Interaction):
    user = await get_user(interaction.user.id)
    if not user:
        # Generate a new LTC address using BlockCypher
        async with aiohttp.ClientSession() as session:
            async with session.post(f"https://api.blockcypher.com/v1/ltc/main/addrs?token={BLOCKCYPHER_TOKEN}") as resp:
                data = await resp.json()
                addr = data["address"]
        async with aiosqlite.connect("bot.db") as db:
            await db.execute("INSERT INTO users(id,wallet_address) VALUES (?,?)", (interaction.user.id, addr))
            await db.commit()
        await interaction.response.send_message(f"Your deposit address: `{addr}`")
    else:
        await interaction.response.send_message(f"Your deposit address: `{user[1]}`")

# --- Tip ---
@app_commands.command(name="tip", description="Tip another user")
@app_commands.describe(user="User to tip", amount="Amount to tip")
async def tip(interaction: discord.Interaction, user: discord.Member, amount: float):
    if amount < 0.5 or amount > 10000:
        await interaction.response.send_message("Tip must be between $0.5 and $10,000")
        return
    sender = await get_user(interaction.user.id)
    receiver = await get_user(user.id)
    if not sender or sender[2] < amount:
        await interaction.response.send_message("Insufficient balance")
        return
    rake = amount * 0.003
    net_amount = amount - rake
    await update_balance(interaction.user.id, -amount)
    await update_balance(user.id, net_amount)
    await update_balance("OWNER", rake)  # OWNER gets rake
    await send_admin_log(f"{interaction.user} tipped {user} ${amount} (rake: {rake})")
    await interaction.response.send_message(f"Tipped ${net_amount} to {user.mention}")

# --- Create game placeholder ---
@app_commands.command(name="create_game", description="Create a game")
@app_commands.describe(game_type="Type of game", wager="Amount to wager")
async def create_game(interaction: discord.Interaction, game_type: str, wager: float):
    await send_admin_log(f"{interaction.user} created {game_type} with wager ${wager}")
    await interaction.response.send_message(f"{game_type} created for ${wager}")

# --- Claim rakeback ---
@app_commands.command(name="claim_rakeback", description="Claim daily 0.5% rakeback")
async def claim_rakeback(interaction: discord.Interaction):
    user = await get_user(interaction.user.id)
    if not user:
        await interaction.response.send_message("No data found")
        return
    rakeback = user[4] * 0.005
    await update_balance(interaction.user.id, rakeback)
    await interaction.response.send_message(f"You claimed ${rakeback:.2f} rakeback")
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE users SET daily_wager=0 WHERE id=?", (interaction.user.id,))
        await db.commit()

# --- Set timezone ---
@app_commands.command(name="set_timezone", description="Set your timezone")
@app_commands.describe(tz="Timezone (e.g., UTC, Asia/Kolkata)")
async def set_timezone(interaction: discord.Interaction, tz: str):
    try:
        pytz.timezone(tz)
    except:
        await interaction.response.send_message("Invalid timezone")
        return
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE users SET timezone=? WHERE id=?", (tz, interaction.user.id))
        await db.commit()
    await interaction.response.send_message(f"Timezone set to {tz}")

# --- Daily rakeback DM task ---
@tasks.loop(minutes=60)
async def check_rakeback():
    now_utc = datetime.datetime.utcnow()
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT id,timezone FROM users") as cursor:
            async for row in cursor:
                user_id, tz = row
                tz_obj = pytz.timezone(tz)
                now = datetime.datetime.now(tz_obj)
                if now.hour == 22 and now.minute == 0:
                    user_obj = await bot.fetch_user(user_id)
                    try:
                        await user_obj.send("You can now claim your daily 0.5% rakeback using /claim_rakeback")
                    except:
                        pass

# --- Register commands ---
bot.tree.add_command(deposit)
bot.tree.add_command(tip)
bot.tree.add_command(create_game)
bot.tree.add_command(claim_rakeback)
bot.tree.add_command(set_timezone)

bot.run(TOKEN)