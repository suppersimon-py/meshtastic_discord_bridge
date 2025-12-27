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
envFile = Path(".env")
logFile = Path("bridge.log")
maxMessageLen = 225

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(logFile), logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

# Config Management
def first_time_setup():
    log.info("No configuration found. Starting first-time setup.")
    try:
        token = input("Enter Discord Bot Token: ").strip()
        if not token:
            raise ValueError("Token required")
        channel_id = input("Enter Discord Channel ID: ").strip()
        channel_id = int(channel_id)
        meshtastic_host = input("Meshtastic hostname (leave blank for serial): ").strip()
        include_username = input("Include username in messages? [Y/n]: ").strip().lower()
        include_username = include_username != "n"
        command_prefix = input("Command prefix [$]: ").strip() or "$"
        config = {
            "DISCORD_TOKEN": token,
            "DISCORD_CHANNEL_ID": str(channel_id),
            "MESHTASTIC_HOSTNAME": meshtastic_host,
            "INCLUDE_USERNAME": str(include_username).lower(),
            "COMMAND_PREFIX": command_prefix
        }
        save_config(config)
        log.info("First-time setup complete.")
        return config
    except Exception as e:
        log.error(f"First-time setup failed: {e}")
        sys.exit(1)

def load_from_env():
    load_dotenv(envFile)
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
        log.warning(".env exists but missing required fields")
        first_time_setup()
        return False
    save_config(config)
    envFile.unlink()
    log.info("Migrated .env to config.json")
    return True

def load_config():
    env_config = {
        "DISCORD_TOKEN": os.getenv("DISCORD_TOKEN"),
        "DISCORD_CHANNEL_ID": os.getenv("DISCORD_CHANNEL_ID"),
        "MESHTASTIC_HOSTNAME": os.getenv("MESHTASTIC_HOSTNAME", ""),
        "INCLUDE_USERNAME": os.getenv("INCLUDE_USERNAME", "true").lower() == "true",
        "COMMAND_PREFIX": os.getenv("COMMAND_PREFIX", "$").strip()
    }
    if env_config["DISCORD_TOKEN"] and env_config["DISCORD_CHANNEL_ID"]:
        log.info("Configuration loaded from environment variables")
        return env_config
    if envFile.exists():
        load_dotenv(envFile)
        token = os.getenv("DISCORD_TOKEN")
        channel_id = os.getenv("DISCORD_CHANNEL_ID")
        if token and channel_id:
            log.info("Configuration loaded from .env")
            return {
                "DISCORD_TOKEN": token,
                "DISCORD_CHANNEL_ID": channel_id,
                "MESHTASTIC_HOSTNAME": os.getenv("MESHTASTIC_HOSTNAME", ""),
                "INCLUDE_USERNAME": os.getenv("INCLUDE_USERNAME", "true").lower() == "true",
                "COMMAND_PREFIX": os.getenv("COMMAND_PREFIX", "$").strip()
            }
    if Config.exists():
        try:
            with open(Config, "r") as f:
                data = json.load(f)
            log.info("Configuration loaded from config.json")
            return data
        except Exception as e:
            log.error(f"Failed to read config.json: {e}")
    return first_time_setup()

config = load_config()
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

# Message Formatting
def format_mesh_message(packet, interface):
    try:
        decoded = packet.get("decoded", {})
        if decoded.get("portnum") != "TEXT_MESSAGE_APP":
            return None
        text = decoded.get("text", "").strip()
        if not text:
            return None
        from_id = packet.get("from")
        node_id = f"!{from_id:08X}" if from_id is not None else "?"
        # Sender display
        from_node_info = interface.nodes.get(from_id, {})
        user = from_node_info.get("user", {})
        long_name = user.get("longName", "").strip()
        short_name = user.get("shortName", "").strip()
        if not long_name and not short_name:
            sender_display = "Node"
        elif long_name and short_name and long_name != short_name:
            sender_display = f"{long_name} ({short_name})"
        elif long_name:
            sender_display = long_name
        else:
            sender_display = short_name
        # Destination handling
        to_id = packet.get("to")
        if to_id == interface.myInfo.my_node_num:
            dest = "You"
        elif to_id == 0xFFFFFFFF:
            dest = "primary"
        else:
            to_node_info = interface.nodes.get(to_id, {})
            to_user = to_node_info.get("user", {})
            dest_long = to_user.get("longName", "").strip()
            dest_short = to_user.get("shortName", "").strip()
            dest = dest_long or dest_short or f"Node {to_id}"
        if dest == "primary":
            return f"**{sender_display}** (`{node_id}`) writes:\n{text}"
        else:
            arrow = "→" if dest != "You" else "whispers to"
            return f"**{sender_display}** (`{node_id}`) {arrow} **{dest}**:\n{text}"
    except Exception as e:
        log.error(f"Error formatting mesh message: {e}")
        return None
   
def format_message_for_mesh(author, text, is_dm=False):
    """Format message sent to mesh: use !username in DMs, display name in public"""
    if is_dm and INCLUDE_USERNAME:
        prefix = f"!{author.name}: "
    elif INCLUDE_USERNAME:
        prefix = f"{author.display_name}: "
    else:
        prefix = ""
    available = maxMessageLen - len(prefix)
    return prefix + text[:available]

# Meshtastic Callbacks
def on_connection_established(interface, topic=pub.AUTO_TOPIC):
    log.info("Connected to Meshtastic device")
    log.info(f"My node info: {interface.myInfo}")

async def handle_mesh_to_discord(packet, interface):
    decoded = packet.get("decoded", {})
    if decoded.get("portnum") != "TEXT_MESSAGE_APP":
        return
    raw_text = decoded.get("text", "").strip()
    if not raw_text:
        return
    main_channel = client.get_channel(DISCORD_CHANNEL_ID)
    if not main_channel:
        return

    # PRIVATE MESSAGE DETECTION (!username message)
    if raw_text.startswith("!") and len(raw_text) > 1 and raw_text[1] != " ":
        parts = raw_text[1:].split(" ", 1)
        username = parts[0]
        message_body = parts[1].strip() if len(parts) > 1 else ""
        if message_body:
            target_member = discord.utils.find(
                lambda m: m.name.lower() == username.lower(),
                main_channel.members
            )
            if target_member:
                try:
                    dm = target_member.dm_channel or await target_member.create_dm()
                    from_id = packet.get("from")
                    node = interface.nodes.get(from_id, {}).get("user", {})
                    sender_name = (
                        node.get("longName")
                        or node.get("shortName")
                        or f"Node !{packet.get('from', 'unknown'):08X}"
                    )
                    await dm.send(f"Private message from {sender_name}:\n{message_body}")
                    return
                except Exception as e:
                    log.error(f"Failed to DM {username}: {e}")

    # PUBLIC MESSAGE FALLBACK
    formatted = format_mesh_message(packet, interface)
    if formatted:
        await main_channel.send(formatted)

def on_receive(packet, interface):
    asyncio.run_coroutine_threadsafe(handle_mesh_to_discord(packet, interface), client.loop)

# Discord Client
class MeshDiscordBridge(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(intents=intents)
        self.iface = None
        self.bg_task = None

    async def setup_hook(self):
        self.bg_task = asyncio.create_task(self.bridge_task())

    async def on_ready(self):
        log.info(f"Discord bot logged in as {self.user} (ID: {self.user.id})")
        channel = self.get_channel(DISCORD_CHANNEL_ID)
        if not channel or not channel.guild:
            log.warning("Could not resolve guild from channel")
            return
        log.info(f"Users in guild '{channel.guild.name}':")
        for member in sorted(channel.guild.members, key=lambda m: m.name.lower()):
            log.info(f"- {member.name}#{member.discriminator} (ID: {member.id})")

    async def on_message(self, message):
        if message.author.id == self.user.id:
            return
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_bridge_channel = message.channel.id == DISCORD_CHANNEL_ID
        if not (is_dm or is_bridge_channel):
            return
        content = message.content.strip()
        if not content.startswith(COMMAND_PREFIX):
            return
        cmd = content[len(COMMAND_PREFIX):].strip()

        if cmd.startswith("help"):
            await message.channel.send(
                f"**Meshtastic ↔ Discord Bridge** (prefix `{COMMAND_PREFIX}`)\n\n"
                f"`{COMMAND_PREFIX}sendprimary <msg>` → Send to primary channel (not allowed in DMs)\n"
                f"`{COMMAND_PREFIX}send nodenum=<id> <msg>` → Send direct/private to node\n"
                f"`{COMMAND_PREFIX}activenodes` → List active nodes\n\n"
                f"*In DMs: use `{COMMAND_PREFIX}send nodenum=` to reply privately.*"
            )

        elif cmd.startswith("sendprimary "):
            if is_dm:
                await message.channel.send(f"`{COMMAND_PREFIX}sendprimary` cannot be used in DMs. Use `{COMMAND_PREFIX}send nodenum=` for private replies.")
                return
            text = cmd[len("sendprimary "):].strip()
            if not text:
                await message.channel.send(f"Usage: `{COMMAND_PREFIX}sendprimary <message>`")
                return
            formatted = format_message_for_mesh(message.author, text, is_dm=False)
            await discordtomesh.put(formatted)
            await message.channel.send(f"**Sending to primary channel:**\n{formatted}")

        elif cmd.startswith("send nodenum="):
            try:
                payload = cmd[len("send nodenum="):].strip()
                nodenum_str, text = payload.split(" ", 1)
                if nodenum_str.startswith("!"):
                    nodenum = int(nodenum_str[1:], 16)
                else:
                    nodenum = int(nodenum_str)
                formatted = format_message_for_mesh(message.author, text, is_dm=True)
                await discordtomesh.put(f"nodenum={nodenum} {formatted}")
                status = "privately" if is_dm else "direct"
                await message.channel.send(f"Sending {status} to node {nodenum_str}:\n{formatted}")
            except ValueError:
                await message.channel.send("**Invalid node ID.**")
            except:
                await message.channel.send(f"Usage: `{COMMAND_PREFIX}send nodenum=<id> <msg>`")

        elif cmd.startswith("activenodes"):
            await nodelistq.put(message)

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
        main_channel = self.get_channel(DISCORD_CHANNEL_ID)
        if not main_channel:
            log.error(f"Cannot find Discord channel {DISCORD_CHANNEL_ID}")
            await self.close()
            return
        if not await self.connect_meshtastic():
            return

        while not self.is_closed():
            try:
                # Discord → Mesh
                while not discordtomesh.empty():
                    item = await discordtomesh.get()
                    if not self.iface:
                        await discordtomesh.put(item)
                        break
                    try:
                        if item.startswith("nodenum="):
                            parts = item.split(" ", 1)
                            nodenum = int(parts[0][8:])
                            text = parts[1]
                            self.iface.sendText(text, destinationId=nodenum)
                        else:
                            self.iface.sendText(item)
                    except Exception as e:
                        log.warning(f"Send failed: {e}, reconnecting...")
                        try:
                            self.iface.close()
                        except:
                            pass
                        self.iface = None
                        await discordtomesh.put(item)
                        await self.connect_meshtastic()
                        break

                # Active nodes list - reply to requester
                while not nodelistq.empty():
                    request_msg = await nodelistq.get()
                    reply_channel = request_msg.channel
                    if not self.iface:
                        await reply_channel.send("Meshtastic not connected.")
                        continue

                    lines = ["**Active Nodes (last heard):**\n```"]
                    my_num = self.iface.myInfo.my_node_num if self.iface.myInfo else None

                    # Use nodesByNum for correct data
                    all_nodes = self.iface.nodesByNum.values()
                    nodes = sorted(all_nodes, key=lambda n: n.get("lastHeard", 0), reverse=True)

                    # Optional: exclude own node
                    nodes = [n for n in nodes if n.get("num") != my_num]

                    for node in nodes:
                        user = node.get("user", {})
                        num = node.get("num")
                        node_id = f"!{num:08X}" if num is not None else "?"
                        long_name = user.get("longName", "").strip() or "?"
                        short_name = user.get("shortName", "").strip() or "?"
                        name_display = (
                            f"{long_name} ({short_name})"
                            if long_name != "?" and short_name != "?" and long_name != short_name
                            else (long_name if long_name != "?" else short_name)
                        )
                        snr = node.get("snr", "?")
                        hops = node.get("hopsAway", 0)
                        ts = node.get("lastHeard", 0)
                        timestr = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S") if ts else "Never"
                        lines.append(f"{name_display:<30} | {node_id} | SNR: {snr:<5} | Hops: {hops} | Last: {timestr}")

                    lines.append("```")
                    packet = "\n".join(lines)
                    for i in range(0, len(packet), 1900):
                        await reply_channel.send(packet[i:i+1900])

                await asyncio.sleep(1)
            except Exception as e:
                log.error(f"Bridge task error: {e}")
                await asyncio.sleep(5)

# Shutdown & Run
def shutdown_handler(sig, frame):
    log.info("Shutdown signal received. Exiting...")
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

client = MeshDiscordBridge()
try:
    client.run(DISCORD_TOKEN)
except Exception as e:
    log.error(f"Discord client failed: {e}")
    sys.exit(1)
