import os
import sys
import queue
import asyncio
from datetime import datetime
from dotenv import load_dotenv, find_dotenv

import meshtastic
import meshtastic.tcp_interface
import meshtastic.serial_interface
from pubsub import pub

import discord

ENV_FILE = find_dotenv() or ".env"

def first_time_setup():
    if not os.path.exists(ENV_FILE):
        print("First-time setup:")
        token = input("Enter your Discord bot token: ").strip()
        channel_id = input("Enter your Discord channel ID: ").strip()
        meshtastic_hostname = input("Enter your Meshtastic hostname (leave blank for serial): ").strip()

        with open(ENV_FILE, "w") as f:
            f.write(f"DISCORD_TOKEN={token}\n")
            f.write(f"DISCORD_CHANNEL_ID={channel_id}\n")
            f.write(f"MESHTASTIC_HOSTNAME={meshtastic_hostname}\n")

        print(f"\nConfiguration saved to {ENV_FILE}\n")
    else:
        print(f"Loading configuration from {ENV_FILE}\n")

first_time_setup()
load_dotenv(ENV_FILE)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
MESHTASTIC_HOSTNAME = os.getenv("MESHTASTIC_HOSTNAME")
meshtodiscord = queue.Queue()
discordtomesh = queue.Queue()
nodelistq = queue.Queue()

def onConnectionMesh(interface, topic=pub.AUTO_TOPIC):
    print(interface.myInfo)

def onReceiveMesh(packet, interface):
    try:
        if 'decoded' in packet:
            if packet['decoded']['portnum'] == 'TEXT_MESSAGE_APP':
                meshtodiscord.put(
                    f"Node {packet.get('fromId')} writes to node {packet.get('toId')}: {packet['decoded']['text']}"
                )
    except Exception as e:
        print("On receive mesh exception: " + str(e))

class MyClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def setup_hook(self):
        self.bg_task = self.loop.create_task(self.background_task())

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})\n------')

    async def on_message(self, message):
        if message.author.id == self.user.id:
            return

        sender = message.author.display_name

        if message.content.startswith('$help'):
            helpmsg = (
                "Meshtastic Discord Bridge is up. Command list:\n"
                "$sendprimary <message> - sends message to primary channel\n"
                "$send nodenum=<nodeid> <message> - sends message to specific node\n"
                "$activenodes - list nodes seen in last 15 minutes"
            )
            await message.channel.send(helpmsg)

        elif message.content.startswith('$sendprimary'):
            text = message.content[len('$sendprimary'):].strip()
            formatted = f"{sender}: {text[:225 - len(sender)-2]}"
            await message.channel.send(f"Sending the following message to the primary channel:\n{formatted}")
            discordtomesh.put(formatted)

        elif message.content.startswith('$send nodenum='):
            try:
                payload = message.content[len('$send nodenum='):].strip()
                parts = payload.split(' ', 1)
                if len(parts) != 2:
                    raise ValueError("Missing message")
                nodenum = parts[0]  # string, supports !hex
                text = parts[1]
                formatted = f"{sender}: {text[:225 - len(sender)-2]}"
                await message.channel.send(f"Sending the following message:\n{formatted}\nto nodenum:\n{nodenum}")
                discordtomesh.put(f"nodenum={nodenum} {formatted}")
            except Exception:
                await message.channel.send(
                    "Usage: `$send nodenum=<nodeid> <message>`\nExample: `$send nodenum=!9ea17f48 hello`"
                )

        elif message.content.startswith('$activenodes'):
            nodelistq.put("request_node_list")

    async def background_task(self):
        await self.wait_until_ready()
        counter = 0
        nodelist = ""
        channel = self.get_channel(DISCORD_CHANNEL_ID)

        # Connect to Meshtastic
        try:
            if MESHTASTIC_HOSTNAME:
                print("Connecting to TCP interface:", MESHTASTIC_HOSTNAME)
                iface = meshtastic.tcp_interface.TCPInterface(MESHTASTIC_HOSTNAME)
            else:
                print("Connecting to Serial interface")
                iface = meshtastic.serial_interface.SerialInterface()
        except Exception as e:
            print(f"Could not connect to Meshtastic: {e}")
            sys.exit(1)

        pub.subscribe(onReceiveMesh, "meshtastic.receive")
        pub.subscribe(onConnectionMesh, "meshtastic.connection.established")

        while not self.is_closed():
            counter += 1

            # Refresh node list approx every 1 min
            if counter % 12 == 1:
                nodelist = "Node list:\n"
                for node in iface.nodes:
                    try:
                        n = iface.nodes[node]
                        id_ = str(n['user']['id'])
                        num = str(n['num'])
                        longname = str(n['user']['longName'])
                        hops = str(n.get('hopsAway', 0))
                        snr = str(n.get('snr', '?'))
                        ts = int(n.get('lastHeard', 0))
                        timestr = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S') if ts else "Unknown"
                        nodelist += f"\nid:{id_}, num:{num}, longname:{longname}, hops:{hops}, snr:{snr}, lastheardutc:{timestr}"
                    except KeyError:
                        continue

            # Send messages from Meshtastic -> Discord
            try:
                meshmsg = meshtodiscord.get_nowait()
                await channel.send(meshmsg)
                meshtodiscord.task_done()
            except queue.Empty:
                pass

            # Send messages from Discord -> Meshtastic
            try:
                meshmsg = discordtomesh.get_nowait()
                if meshmsg.startswith('nodenum='):
                    nodenum = meshmsg[8:meshmsg.find(' ')]
                    text = meshmsg[meshmsg.find(' ') + 1:]
                    iface.sendText(text, destinationId=nodenum)
                else:
                    iface.sendText(meshmsg)
                discordtomesh.task_done()
            except queue.Empty:
                pass

            try:
                nodelistq.get_nowait()
                lines = nodelist.splitlines()
                packet = ""
                for line in lines:
                    if len(packet) + len(line) < 1900:
                        packet += line + "\n"
                    else:
                        await channel.send(packet)
                        packet = line + "\n"
                await channel.send(packet)
                nodelistq.task_done()
            except queue.Empty:
                pass

            await asyncio.sleep(5)

intents = discord.Intents.default()
intents.message_content = True

client = MyClient(intents=intents)
client.run(DISCORD_TOKEN)
