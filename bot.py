import discord
from discord.ext import commands, tasks
import docker
import asyncio
import random
import string
import time as t
import datetime
import io
import json
import os

# --- CONFIGURATION ---
TOKEN = 'YOUR_DISCORD_BOT_TOKEN_HERE' # Put your bot token here
HOST_IP = 'YOUR_SERVER_PUBLIC_IP'     # The public IP of your VPS/Server
START_PORT = 9500                     # Starting port for containers
MAX_CONTAINERS = 5                    # Max simultaneous labs
LAB_DURATION = 3600                   # Duration in seconds (1 hour)
ADMIN_ID = 123456789012345678         # Your Discord User ID for logs
BAN_FILE = "banned_users.json"        # Storage file for banned users

# --- SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
client = docker.from_env()

# Storage : {user_id: {'id': container_id, 'start_time': timestamp, 'username': name}}
active_labs = {}

# Load Blacklist at startup
if os.path.exists(BAN_FILE):
    with open(BAN_FILE, "r") as f:
        try:
            banned_users = json.load(f)
        except:
            banned_users = {}
else:
    banned_users = {}

# --- UTILITY FUNCTIONS ---

def save_bans():
    """Saves the banned list to the JSON file"""
    with open(BAN_FILE, "w") as f:
        json.dump(banned_users, f, indent=4)

def generate_password():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=8))

def get_remaining_time(start_time):
    elapsed = t.time() - start_time
    remaining = LAB_DURATION - elapsed
    return max(0, int(remaining))

def get_container_logs(container_id):
    """Retrieves the internal log file from the container"""
    try:
        container = client.containers.get(container_id)
        # Execute 'cat' inside the container to read the file created by the Dockerfile
        result = container.exec_run("cat /var/log/cmd.log")
        return result.output.decode('utf-8', errors='ignore')
    except Exception as e:
        return f"Unable to read logs (Container might be dead or image not updated) : {e}"

async def send_admin_log(title, description, color=0x5865F2, urgent=False, file=None):
    """Sends a clean log to the admin DM (with optional file)"""
    try:
        admin = await bot.fetch_user(ADMIN_ID)
        
        # --- Time Management (UTC+1) ---
        now = datetime.datetime.now() + datetime.timedelta(hours=1)
        timestamp = now.strftime("%H:%M:%S")
        # -------------------------------

        emoji = "🚨" if urgent else "📝"
        
        embed = discord.Embed(title=f"{emoji} LOG : {title}", description=description, color=color)
        embed.set_footer(text=f"Time : {timestamp}")
        
        await admin.send(embed=embed, file=file)
    except Exception as e:
        print(f"Unable to send log to admin : {e}")

async def kill_container_later(container_id, user_id):
    """Automatic Timer with Log and Command Report sending"""
    await asyncio.sleep(LAB_DURATION + 60)
    try:
        if user_id in active_labs and active_labs[user_id]['id'] == container_id:
            username = active_labs[user_id]['username']
            
            # 1. Retrieve logs BEFORE deletion
            logs = get_container_logs(container_id)
            log_file = discord.File(io.BytesIO(logs.encode()), filename=f"history_{username}.txt")
            
            # 2. Deletion
            container = client.containers.get(container_id)
            container.stop()
            container.remove()
            del active_labs[user_id]
            
            print(f"💀 Time's up for {username}")
            await send_admin_log("Auto Session End", f"The lab of **{username}** has expired. History attached.", 0xFFA500, file=log_file)
    except Exception as e:
        print(f"Auto cleanup error : {e}")

# --- BACKGROUND TASK (WATCHDOG) ---
@tasks.loop(seconds=60)
async def watchdog():
    """Checks every minute if containers died unexpectedly"""
    for user_id in list(active_labs.keys()):
        lab_info = active_labs[user_id]
        container_id = lab_info['id']
        username = lab_info['username']
        
        try:
            # Ask Docker if container still exists
            container = client.containers.get(container_id)
            if container.status != 'running':
                # If exists but not 'running', it's suspicious (crash?)
                
                # Try to retrieve post-mortem logs
                logs = get_container_logs(container_id)
                log_file = discord.File(io.BytesIO(logs.encode()), filename=f"crash_{username}.txt")

                container.remove()
                del active_labs[user_id]
                await send_admin_log(
                    "CRASH DETECTED", 
                    f"⚠️ The container of **{username}** stopped unexpectedly (Crash or OOM Kill).", 
                    0xFF0000, 
                    urgent=True,
                    file=log_file
                )
        except docker.errors.NotFound:
            # Container disappeared without the bot!
            del active_labs[user_id]
            await send_admin_log(
                "SUSPICIOUS DISAPPEARANCE", 
                f"👻 The container of **{username}** disappeared (manually deleted?).", 
                0xFF0000, 
                urgent=True
            )

@bot.event
async def on_ready():
    print(f"✅ Lab Bot connected! Logs enabled for admin ID: {ADMIN_ID}")
    watchdog.start() # Start the watchdog
    await send_admin_log("Bot Started", "The Lab system is online.", 0x00FF00)

# --- COMMANDS ---

@bot.command()
async def lab(ctx):
    user_id = ctx.author.id
    username = ctx.author.name
    user_id_str = str(user_id) # JSON uses strings for keys

    # --- 1. BAN CHECK ---
    if user_id_str in banned_users:
        reason = banned_users[user_id_str]
        await ctx.send(f"🚫 **ACCESS DENIED** : You are banned from this service.\n**Reason :** {reason}")
        await send_admin_log("Ban Block", f"**{username}** (Banned) tried to start a lab.", 0x000000)
        return
    # --------------------

    # SPAM / Cheat Detection
    if user_id in active_labs:
        await ctx.send(f"❌ {ctx.author.mention}, you already have a lab!")
        # Log spam attempt in orange
        await send_admin_log("Spam Attempt", f"**{username}** tried to start a 2nd lab.", 0xFFA500)
        return

    try:
        current_containers = client.containers.list(filters={"label": "type=discord-lab"})
        if len(current_containers) >= MAX_CONTAINERS:
            await ctx.send("⚠️ No containers available at the moment.")
            return

        # Find free port
        used_ports = []
        for c in current_containers:
            p = c.ports.get('7681/tcp')
            if p: used_ports.append(int(p[0]['HostPort']))
        
        free_port = None
        for p in range(START_PORT, START_PORT + MAX_CONTAINERS):
            if p not in used_ports:
                free_port = p
                break
        
        if not free_port:
            await ctx.send("❌ No ports available.")
            return

        await ctx.send("⚙️ **Deploying...**")

        password = generate_password()
        cmd_entrypoint = f"ttyd -W -p 7681 -c student:{password} /usr/local/bin/entrypoint.sh"

        container = client.containers.run(
            "lab-image",
            entrypoint=cmd_entrypoint,
            detach=True,
            ports={'7681/tcp': free_port},
            labels={"type": "discord-lab", "owner": str(user_id)},
            mem_limit="512m",
            nano_cpus=500000000,
            pids_limit=100,
            privileged=False,
            cap_drop=['NET_RAW'],
            name=f"lab-{user_id}-{random.randint(1000,9999)}"
        )

        active_labs[user_id] = {
            'id': container.id,
            'start_time': t.time(),
            'username': username
        }

        link = f"http://{HOST_IP}:{free_port}"
        
        embed = discord.Embed(title="🐧 Your Terminal is ready", color=0x00ff00)
        embed.add_field(name="Link", value=link, inline=False)
        embed.add_field(name="Login", value=f"User: `student`\nPass: `{password}`", inline=True)
        embed.set_footer(text="!stop when finished. !time to check remaining time.")

        try:
            await ctx.author.send(embed=embed)
            await ctx.send(f"✅ Link sent in DM to {ctx.author.mention} !")
            
            # SUCCESS LOG
            await send_admin_log("New Lab", f"✅ **{username}** started a container on port {free_port}.", 0x00FF00)
            
            bot.loop.create_task(kill_container_later(container.id, user_id))
        except discord.Forbidden:
            container.stop()
            container.remove()
            del active_labs[user_id]
            await ctx.send("❌ Open your DMs!")

    except Exception as e:
        await ctx.send(f"🔥 Error : {e}")
        await send_admin_log("CRITICAL ERROR", f"Error launching a lab : {e}", 0xFF0000, urgent=True)

@bot.command()
async def time(ctx):
    user_id = ctx.author.id
    if user_id not in active_labs:
        await ctx.send("You don't have an active lab.")
        return
    remaining = get_remaining_time(active_labs[user_id]['start_time'])
    minutes = remaining // 60
    await ctx.send(f"⏳ **{minutes} minutes** remaining.")

@bot.command()
async def stop(ctx):
    """Student stops their lab"""
    user_id = ctx.author.id
    username = ctx.author.name
    if user_id in active_labs:
        try:
            container_id = active_labs[user_id]['id']
            
            # 1. Retrieve logs
            logs = get_container_logs(container_id)
            log_file = discord.File(io.BytesIO(logs.encode()), filename=f"history_{username}.txt")
            
            # 2. Destruction
            container = client.containers.get(container_id)
            container.stop()
            container.remove()
            del active_labs[user_id]
            await ctx.send(f"🛑 Lab destroyed.")
            
            # CLEAN STOP LOG + FILE
            await send_admin_log("User Stop", f"🛑 **{username}** stopped their lab cleanly.", 0x5865F2, file=log_file)
        except:
            await ctx.send("Already destroyed.")
            del active_labs[user_id]
    else:
        await ctx.send("Nothing to stop.")

@bot.command()
@commands.has_permissions(administrator=True)
async def nuke(ctx, member: discord.Member):
    """Admin : Forced destruction"""
    user_id = member.id
    admin_name = ctx.author.name
    
    if user_id in active_labs:
        try:
            container_id = active_labs[user_id]['id']
            username = active_labs[user_id]['username']
            
            # 1. Retrieve logs
            logs = get_container_logs(container_id)
            log_file = discord.File(io.BytesIO(logs.encode()), filename=f"nuked_{username}.txt")
            
            # 2. Destruction
            container = client.containers.get(container_id)
            container.stop()
            container.remove()
            del active_labs[user_id]
            await ctx.send(f"💥 **BOOM !** Lab of {member.mention} destroyed.")
            
            # NUKE ADMIN LOG + FILE
            await send_admin_log("ADMIN NUKE", f"☢️ **{admin_name}** forcefully destroyed the lab of **{member.name}**.", 0xFF0000, urgent=True, file=log_file)
        except Exception as e:
            await ctx.send(f"Error : {e}")
    else:
        await ctx.send(f"🚫 No active lab.")

@bot.command()
@commands.has_permissions(administrator=True)
async def spy(ctx, member: discord.Member):
    """(ADMIN) View commands typed in real-time"""
    user_id = member.id
    if user_id in active_labs:
        container_id = active_labs[user_id]['id']
        logs = get_container_logs(container_id)
        
        # If log is too long for Discord (>2000 chars), send a file
        if len(logs) > 1900:
            log_file = discord.File(io.BytesIO(logs.encode()), filename=f"spy_{member.name}.txt")
            await ctx.author.send(f"🕵️‍♂️ **Spy Report for {member.name}** :", file=log_file)
        else:
            if not logs.strip():
                logs = "No commands typed yet."
            await ctx.author.send(f"🕵️‍♂️ **Commands of {member.name}** :\n```bash\n{logs}\n```")
        
        await ctx.message.add_reaction("👀") # Just to confirm the command
    else:
        await ctx.send("This user does not have an active lab.")

# --- NEW COMMAND : BAN ---
@bot.command()
@commands.has_permissions(administrator=True)
async def ban(ctx, member: discord.Member, *, reason="Dangerous behavior"):
    """Ban a user from the bot + Nuke their lab"""
    user_id = member.id
    user_id_str = str(user_id)
    
    # 1. Add to blacklist
    banned_users[user_id_str] = reason
    save_bans() # JSON Save

    # 2. If active lab, NUKE it
    if user_id in active_labs:
        try:
            username = active_labs[user_id]['username'] # Important for filename
            container_id = active_labs[user_id]['id']
            logs = get_container_logs(container_id)
            log_file = discord.File(io.BytesIO(logs.encode()), filename=f"banned_{username}.txt")
            
            container = client.containers.get(container_id)
            container.stop()
            container.remove()
            del active_labs[user_id]
            await ctx.send(f"🚫 **{member.mention} was BANNED and their lab destroyed.**")
            await send_admin_log("BAN HAMMER", f"🔨 **{member.name}** was banned by {ctx.author.name}.\nReason : {reason}", 0x000000, urgent=True, file=log_file)
        except Exception as e:
            await ctx.send(f"Banned but nuke error: {e}")
    else:
        await ctx.send(f"🚫 **{member.mention} was BANNED from the bot.**")
        await send_admin_log("BAN HAMMER", f"🔨 **{member.name}** was banned by {ctx.author.name}.\nReason : {reason}", 0x000000)

# --- NEW COMMAND : UNBAN ---
@bot.command()
@commands.has_permissions(administrator=True)
async def unban(ctx, member: discord.Member):
    """Unban a user"""
    user_id_str = str(member.id)
    if user_id_str in banned_users:
        del banned_users[user_id_str]
        save_bans()
        await ctx.send(f"✅ **{member.mention} was unbanned.**")
        await send_admin_log("Unban", f"🕊️ **{member.name}** was unbanned by {ctx.author.name}.", 0x00FF00)
    else:
        await ctx.send("This user is not banned.")

bot.run(TOKEN)
