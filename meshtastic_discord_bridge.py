import os
import sys
import queue
import asyncio
import argparse
import time
from datetime import datetime
from dotenv import load_dotenv, find_dotenv
import meshtastic
import meshtastic.tcp_interface
import meshtastic.serial_interface
from pubsub import pub
import discord

MAX_MESSAGE_LEN = 225
ENV_FILE = find_dotenv() or ".env"

def parse_args():
    parser = argparse.ArgumentParser(description="Meshtastic Discord Bridge")
    parser.add_argument("--token", help="Discord bot token")
    parser.add_argument("--channel-id", help="Discord channel ID")
    parser.add_argument(
        "--meshtastic-host",
        help="Meshtastic TCP hostname (blank = serial)",
    )
    parser.add_argument(
        "--include-username",
        choices=["true", "false"],
        help="Prepend Discord username to messages",
    )
    return parser.parse_args()
args = parse_args()

def save_env(token, channel_id, hostname, include_username):
    with open(ENV_FILE, "w") as f:
        f.write(f"DISCORD_TOKEN={token}\n")
        f.write(f"DISCORD_CHANNEL_ID={channel_id}\n")
        f.write(f"MESHTASTIC_HOSTNAME={hostname}\n")
        f.write(f"INCLUDE_USERNAME={str(include_username).lower()}\n")
    print(f"Configuration saved to {ENV_FILE}\n")

def first_time_setup():
    print("First-time setup:\n")
    token = input("Enter your Discord bot token: ").strip()
    channel_id = input("Enter your Discord channel ID: ").strip()
    hostname = input(
        "Enter Meshtastic hostname (leave blank for serial): "
    ).strip()
    include_username = (
        input("Include Discord username in messages? (y/n): ")
        .strip()
        .lower()
        in ("y", "yes")
    )
    save_env(token, channel_id, hostname, include_username)

if args.token and args.channel_id and args.include_username is not None:
    save_env(
        token=args.token,
        channel_id=args.channel_id,
        hostname=args.meshtastic_host or "",
        include_username=args.include_username == "true",
    )
else:
    if not os.path.exists(ENV_FILE):
        first_time_setup()
load_dotenv(ENV_FILE)
DISCORD_TOKEN = args.token or os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = int(args.channel_id or os.getenv("DISCORD_CHANNEL_ID"))
MESHTASTIC_HOSTNAME = (
    args.meshtastic_host
    if args.meshtastic_host is not None
    else os.getenv("MESHTASTIC_HOSTNAME", "")
)
INCLUDE_USERNAME = (
    args.include_username.lower() == "true"
    if args.include_username is not None
    else os.getenv("INCLUDE_USERNAME", "true").lower() == "true"
)
if not DISCORD_TOKEN or not DISCORD_CHANNEL_ID:
    print("Missing required Discord configuration.")
    sys.exit(1)
meshtodiscord = queue.Queue()
discordtomesh = queue.Queue()
nodelistq = queue.Queue()

def format_message(sender, text):
    if INCLUDE_USERNAME:
        prefix = f"{sender}: "
        return prefix + text[: MAX_MESSAGE_LEN - len(prefix)]
    return text[:MAX_MESSAGE_LEN]

def onConnectionMesh(interface, topic=pub.AUTO_TOPIC):
    print("Connected to Meshtastic:")
    print(interface.myInfo)

def onReceiveMesh(packet, interface):
    try:
        if (
            "decoded" in packet
            and packet["decoded"]["portnum"] == "TEXT_MESSAGE_APP"
        ):
            meshtodiscord.put(
                f"Node {packet.get('fromId')} → {packet.get('toId')}: "
                f"{packet['decoded']['text']}"
            )
    except Exception as e:
        print("On receive mesh exception:", e)

class MyClient(discord.Client):
    async def setup_hook(self):
        self.bg_task = self.loop.create_task(self.background_task())

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")

    async def on_message(self, message):
        if message.author.id == self.user.id:
            return
        sender = message.author.display_name
        if message.content.startswith("$help"):
            await message.channel.send(
                "Meshtastic Discord Bridge\n"
                "$sendprimary <message>\n"
                "$send nodenum=<nodeid> <message>\n"
                "$activenodes"
            )

        elif message.content.startswith("$sendprimary"):
            text = message.content[len("$sendprimary"):].strip()
            formatted = format_message(sender, text)
            await message.channel.send(
                f"Sending the following message:\n{formatted}"
            )
            discordtomesh.put(formatted)
        elif message.content.startswith("$send nodenum="):
            try:
                payload = message.content[len("$send nodenum="):].strip()
                nodenum, text = payload.split(" ", 1)
                formatted = format_message(sender, text)
                discordtomesh.put(f"nodenum={nodenum} {formatted}")
            except Exception:
                await message.channel.send(
                    "Usage: `$send nodenum=<nodeid> <message>`"
                )

        elif message.content.startswith("$activenodes"):
            nodelistq.put("request")

    async def background_task(self):
        await self.wait_until_ready()
        channel = self.get_channel(DISCORD_CHANNEL_ID)
        iface = None
        start_time = time.time()
        while iface is None:
            try:
                if MESHTASTIC_HOSTNAME:
                    print(f"Connecting to Meshtastic TCP: {MESHTASTIC_HOSTNAME}")
                    iface = meshtastic.tcp_interface.TCPInterface(
                        MESHTASTIC_HOSTNAME
                    )
                else:
                    print("Connecting to Meshtastic serial interface")
                    iface = meshtastic.serial_interface.SerialInterface()
            except Exception:
                if time.time() - start_time > 10:
                    print(
                        "No Meshtastic device detected within 10 seconds. Exiting."
                    )
                    sys.exit(1)
                await asyncio.sleep(1)
        pub.subscribe(onReceiveMesh, "meshtastic.receive")
        pub.subscribe(onConnectionMesh, "meshtastic.connection.established")

        while not self.is_closed():
            try:
                msg = meshtodiscord.get_nowait()
                await channel.send(msg)
                meshtodiscord.task_done()
            except queue.Empty:
                pass
            try:
                msg = discordtomesh.get_nowait()
                if msg.startswith("nodenum="):
                    nodenum = msg[8 : msg.find(" ")]
                    text = msg[msg.find(" ") + 1 :]
                    iface.sendText(text, destinationId=nodenum)
                else:
                    iface.sendText(msg)
                discordtomesh.task_done()
            except queue.Empty:
                pass

            await asyncio.sleep(5)

intents = discord.Intents.default()
intents.message_content = True
client = MyClient(intents=intents)
client.run(DISCORD_TOKEN)
