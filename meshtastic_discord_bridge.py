# Imports
import os
import sys
import asyncio
import json
import signal
import logging
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
import meshtastic.tcp_interface
import meshtastic.serial_interface
from pubsub import pub
import discord

# Configuration
Config = Path("config.json")
Envfile = Path(".env")
logfile = Path("bridge.log")
Maxmessagelen = 225

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(logfile), logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

# Config Management
def load_from_env():
    load_dotenv(Envfile)
    token = os.getenv("DISCORD_TOKEN")
    channel_id = os.getenv("DISCORD_CHANNEL_ID")
    if not token or not channel_id:
        return None
    try:
        int(channel_id)
    except (ValueError, TypeError):
        return None

    return {
        "DISCORD_TOKEN": token,
        "DISCORD_CHANNEL_ID": channel_id,
        "MESHTASTIC_HOSTNAME": os.getenv("MESHTASTIC_HOSTNAME", ""),
        "INCLUDE_USERNAME": os.getenv("INCLUDE_USERNAME", "true").lower() == "true",
        "COMMAND_PREFIX": os.getenv("COMMAND_PREFIX", "$").strip()
    }

def save_config(config):
    config["DISCORD_CHANNEL_ID"] = str(config["DISCORD_CHANNEL_ID"])
    config["INCLUDE_USERNAME"] = str(config.get("INCLUDE_USERNAME", True)).lower()
    config["COMMAND_PREFIX"] = config.get("COMMAND_PREFIX", "$").strip()
    with open(Config, "w") as f:
        json.dump(config, f, indent=4)
    log.info("Configuration saved to config.json")

def migrate_env_to_json():
    config = load_from_env()
    if not config:
        log.warning(".env exists but missing required")
        return False
    save_config(config)
    Envfile.unlink()
    log.info("Migrated .env to config.json")
    return True

def load_config():
    if Config.exists():
        try:
            with open(Config, "r") as f:
                data = json.load(f)
            log.info("Configuration Loaded")
            return data
        except Exception as e:
            log.error(f"Failed to read config.json: {e}")

    if Envfile.exists():
        log.info(".env detected — migrating config")
        if migrate_env_to_json():
            try:
                with open(Config, "r") as f:
                    data = json.load(f)
                log.info("Migrated complete - Saved to config.json")
                return data
            except Exception as e:
                log.error(f"Failed to read config.json: {e}")
    return None

config = load_config()
if not config or not config.get("DISCORD_TOKEN") or not config.get("DISCORD_CHANNEL_ID"):
    log.error("Config missing. Please run first-time setup or provide valid config.json")
    sys.exit(1)

DISCORD_TOKEN = config["DISCORD_TOKEN"]
DISCORD_CHANNEL_ID = int(config["DISCORD_CHANNEL_ID"])
MESHTASTIC_HOSTNAME = config.get("MESHTASTIC_HOSTNAME", "")
INCLUDE_USERNAME = config.get("INCLUDE_USERNAME", True) in (True, "true")
COMMAND_PREFIX = config.get("COMMAND_PREFIX", "$").strip() or "$"
log.info(f"Using command prefix: '{COMMAND_PREFIX}'")

# Queues
meshtodiscord = asyncio.Queue()
discordtomesh = asyncio.Queue()
nodelistq = asyncio.Queue()

# Helpers
def format_message(sender, text):
    if INCLUDE_USERNAME:
        prefix = f"{sender}: "
        return prefix + text[:Maxmessagelen-len(prefix)]
    return text[:Maxmessagelen]

# Meshtastic Callbacks
def on_connection_established(interface, topic=pub.AUTO_TOPIC):
    log.info("Connected to Meshtastic device")
    log.info(f"My node info: {interface.myInfo}")

def on_receive(packet, interface):
    try:
        decoded = packet.get("decoded", {})
        if decoded.get("portnum") != "TEXT_MESSAGE_APP":
            return
        text = decoded.get("text", "")
        if not text:
            return
        from_id = packet.get("from")
        from_node = interface.nodes.get(from_id, {}).get("user", {})
        sender_name = from_node.get("longName") or from_node.get("shortName") or f"Unknown({from_id})"
        to_id = packet.get("to")
        if to_id == interface.myInfo.my_node_num:
            dest = "me"
        elif to_id == 0xFFFFFFFF:
            dest = "broadcast"
        else:
            to_node = interface.nodes.get(to_id, {}).get("user", {})
            dest = to_node.get("longName") or to_node.get("shortName") or f"Node {to_id}"
        msg = f"{sender_name} → {dest}: {text}"
        asyncio.run_coroutine_threadsafe(meshtodiscord.put(msg), asyncio.get_event_loop())
    except Exception as e:
        log.error(f"Error processing packet: {e}")

# Discord Client
class MeshDiscordBridge(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.iface = None
        self.bg_task = None

    async def setup_hook(self):
        self.bg_task = asyncio.create_task(self.bridge_task())

    async def on_ready(self):
        log.info(f"Discord bot logged in as {self.user} (ID: {self.user.id})")

    async def on_message(self, message):
        if message.author.id == self.user.id: return
        if message.channel.id != DISCORD_CHANNEL_ID: return
        content = message.content.strip()
        if not content.startswith(COMMAND_PREFIX): return
        command = content[len(COMMAND_PREFIX):].strip()
        sender = message.author.display_name
        if command.startswith("help"):
            await message.channel.send(
                f"**Meshtastic ↔ Discord Bridge** (prefix `{COMMAND_PREFIX}`)\n"
                f"`{COMMAND_PREFIX}sendprimary <msg>` → Send to primary\n"
                f"`{COMMAND_PREFIX}send nodenum=<id> <msg>` → Send to node\n"
                f"`{COMMAND_PREFIX}activenodes` → List active nodes"
            )
        elif command.startswith("sendprimary"):
            text = command[len("sendprimary"):].strip()
            if text:
                await discordtomesh.put(format_message(sender, text))
                await message.channel.send(f"Sending the following message:\n`{format_message(sender,text)}`")
        elif command.startswith("send nodenum="):
            try:
                payload = command[len("send nodenum="):].strip()
                nodenum, text = payload.split(" ",1)
                int(nodenum)
                await discordtomesh.put(f"nodenum={nodenum} {format_message(sender,text)}")
                await message.channel.send(f"Sending to node {nodenum}: `{format_message(sender,text)}`")
            except Exception:
                await message.channel.send(f"Usage: `{COMMAND_PREFIX}send nodenum=<id> <msg>`")
        elif command.startswith("activenodes"):
            await nodelistq.put("request")

    async def connect_meshtastic(self):
        while not self.is_closed():
            try:
                if MESHTASTIC_HOSTNAME:
                    log.info(f"Connecting via TCP: {MESHTASTIC_HOSTNAME}")
                    self.iface = meshtastic.tcp_interface.TCPInterface(MESHTASTIC_HOSTNAME)
                else:
                    log.info("Connecting via serial")
                    self.iface = meshtastic.serial_interface.SerialInterface()
                pub.subscribe(on_receive, "meshtastic.receive")
                pub.subscribe(on_connection_established, "meshtastic.connection.established")
                return True
            except Exception as e:
                log.warning(f"Meshtastic connect failed: {e}. Retrying in 10s...")
                await asyncio.sleep(10)
        return False

    async def bridge_task(self):
        await self.wait_until_ready()
        channel = self.get_channel(DISCORD_CHANNEL_ID)
        if not channel:
            log.error(f"Cannot find Discord channel {DISCORD_CHANNEL_ID}")
            await self.close()
            return

        if not await self.connect_meshtastic():
            return

        while not self.is_closed():
            try:
                # Meshtastic -> Discord
                while not meshtodiscord.empty():
                    msg = await meshtodiscord.get()
                    await channel.send(msg)

                # Discord -> Meshtastic
                while not discordtomesh.empty():
                    msg = await discordtomesh.get()
                    if not self.iface:
                        await discordtomesh.put(msg)
                        break
                    try:
                        if msg.startswith("nodenum="):
                            parts = msg.split(" ",1)
                            nodenum = int(parts[0][8:])
                            text = parts[1]
                            self.iface.sendText(text, destinationId=nodenum)
                        else:
                            self.iface.sendText(msg)
                    except Exception as e:
                        log.warning(f"Send failed: {e}, reconnecting...")
                        try: self.iface.close()
                        except: pass
                        self.iface = None
                        await discordtomesh.put(msg)
                        await self.connect_meshtastic()
                        break

                # Active nodes
                while not nodelistq.empty():
                    await nodelistq.get()
                    if not self.iface:
                        await channel.send("Meshtastic not connected.")
                        continue
                    lines = ["**Active Nodes:**\n```"]
                    for node in sorted(self.iface.nodes.values(), key=lambda n: n.get("lastHeard",0), reverse=True):
                        user = node.get("user",{})
                        ts = node.get("lastHeard",0)
                        timestr = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if ts else "Never"
                        lines.append(f"{user.get('longName','?')} ({user.get('shortName','?')}) Num:{node.get('num')} | SNR:{node.get('snr','?')} | Hops:{node.get('hopsAway',0)} | Last:{timestr}")
                    lines.append("```")
                    packet = "\n".join(lines)
                    for i in range(0,len(packet),1900):
                        await channel.send(packet[i:i+1900])

                await asyncio.sleep(1)
            except Exception as e:
                log.error(f"Bridge task error: {e}")
                await asyncio.sleep(5)

# Shutdown Handler
def shutdown_handler(sig, frame):
    log.info("Shutdown signal received. Exiting...")
    sys.exit(0)
signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

# Start Bot
client = MeshDiscordBridge()
try:
    client.run(DISCORD_TOKEN)
except Exception as e:
    log.error(f"Discord client failed: {e}")
    sys.exit(1)
