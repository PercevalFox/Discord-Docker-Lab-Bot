# Discord Docker Lab Bot 🐧

A Discord bot that spawns temporary Docker Linux environments for users on demand. Each user gets a private terminal session accessed via browser (ttyd), monitored by the bot.

## Features

* **On-demand Linux Labs**: Users type `!lab` to get a fresh Debian container.
* **Web Terminal**: Access via browser using `ttyd`.
* **Auto-Kill**: Labs are automatically destroyed after 1 hour.
* **Admin Monitoring**:
    * **Spy Mode**: Admins can see commands typed by users in real-time (`!spy`).
    * **Logs**: Command history is sent to the admin upon session end.
    * **Nuke**: Forcefully destroy a user's lab.
* **Ban System**: Blacklist users from using the service.

## Prerequisites

* A Linux VPS/Server (Ubuntu/Debian recommended).
* **Docker** installed and running.
* **Python 3.9+**.
* A Discord Bot Token (Developer Portal).

## Installation Procedure

### 1. Download & Setup Server
Log into your VPS and clone the repository (or upload files):

```
# Create a folder for the bot
mkdir -p /root/discord-container
cd /root/discord-container
```
### (Upload the files bot.py, Dockerfile, discord-lab.service here)

### 2. Build the Docker Image
This image will be used to spawn the student labs.

```
docker build -t lab-image .
```

### 3. Python Environment
Set up a virtual environment to isolate dependencies.

```
# Install venv if needed
apt install python3-venv

# Create venv
python3 -m venv venv

# Activate and install requirements
source venv/bin/activate
pip install discord.py docker
deactivate
```

### 4. Discord Developer Portal Configuration
Go to [Discord Developer Portal.](https://discord.com/developers/applications) 

Create a New Application -> Bot.

Enable Message Content Intent (Required for the bot to read commands).

Copy your Token.

Invite the bot to your server using OAuth2 -> URL Generator -> bot + Administrator permissions.

### 5. Bot Configuration
Open bot.py and edit the configuration section:

```
# --- CONFIGURATION ---
TOKEN = 'YOUR_PASTED_TOKEN_HERE'
HOST_IP = 'YOUR_VPS_IP_ADDRESS'   # e.g., 123.45.67.89
START_PORT = 9500                 # Start of the port range
ADMIN_ID = 123456789012345678     # Your Discord User ID (Right click user -> Copy ID)
```

### 6. Run the Bot (Manual Test)
Test if everything works before running as a service.

```
source venv/bin/activate
python3 bot.py
```

You should see: ```✅ Lab Bot connected!```

### 7. Run as a Service (Background)
To keep the bot running 24/7 even if you close the terminal.

Move the service file (or create it) to systemd:

```
cp discord-lab.service /etc/systemd/system/
```
Reload systemd and start the service:

```
systemctl daemon-reload
systemctl enable discord-lab
systemctl start discord-lab
```
Check status:

```
systemctl status discord-lab
```

## Commands

### User Commands

* ```!lab``` : Deploys a new Linux container and sends the link in DM.

* ```!time``` : Checks remaining time for the active session.

* ```!stop``` : Stops and destroys the current lab immediately.

### Admin Commands

* ```!spy @user``` : Sends a report of commands currently typed by the user.

* ```!nuke @user``` : Forcefully destroys a user's container.

* ```!ban @user [reason]``` : Bans a user from using the bot and destroys their active lab.

* ```!unban @user``` : Unbans a user.

## Security Measures

The system is designed with several layers of security to protect the host VPS and prevent abuse:

### Container Hardening
* **Restricted Capabilities**: The `NET_RAW` capability is dropped (`cap_drop=['NET_RAW']`) to prevent packet spoofing and network attacks.
* **Non-Privileged**: Containers run without the `--privileged` flag, preventing access to host devices.
* **Ephemeral Environment**: Containers are destroyed immediately after the session ends; no data persists.

### Resource Limits (Anti-Abuse)
To prevent "Fork Bombs" or crypto-mining attempts, each container is strictly limited via Docker:
* **Memory**: Capped at 512MB.
* **CPU**: Usage limited via `nano_cpus`.
* **Process Limit**: Max 100 PIDs (Process IDs) allowed per container.

### Auditing & Monitoring
* **Deep Logging**: A background mechanism captures every command typed in Bash (via `PROMPT_COMMAND`) into a root-owned log file.
* **Admin Oversight**:
    * **Real-time Spy**: Admins can inspect active sessions using `!spy`.
    * **Post-Session Reports**: Full command history is sent to the Admin DM upon container destruction.
* **Watchdog**: A background task monitors for unexpected container crashes or manual deletions.

### Access Control
* **Random Credentials**: Each session generates a unique, random 8-character password.
* **Blacklist System**: Admins can permanently ban users via `!ban`, preventing them from spawning new containers.
