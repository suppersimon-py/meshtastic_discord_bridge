# meshtastic_discord_bridge

A Discord bot which bridges discussions between a Discord channel and a Meshtastic mesh through a locally connected radio

## Requirements

- Python
- A supported Meshtastic radio connected via USB 
- Discord key and a channel

## Installation and Startup

1. **Create a Discord Bot account**  
   Follow the [instructions](https://discordpy.readthedocs.io/en/stable/discord.html).

2. **Configure bot permissions**  
   - Go to **OAuth2 > URL Generator** in your Discord application.  
   - Under **Scopes**, select **bot**.  
   - This will expand **Bot Permissions**—select the following:  
     - `Read Message History`  
     - `Send Messages`  
     - `View Channels`  

3. **Invite the bot to your server**  
   - Copy the generated URL from Step 2 and open it in a browser.  
   - Select the server you want the bot to join and click **Authorize**.


4. **Set up your environment**  
   - On first run, the bot will prompt you for your Discord token, channel ID, and Meshtastic hostname (if using TCP). 
   - These values will be saved automatically to a .env file for future runs.  
   - If you leave the Meshtastic hostname blank, the bot will attempt to connect via a serial interface.

4. **Install dependencies and start the bot**

```bash
python3 -m pip install -r requirements.txt
python meshtastic_discord_bridge.py
```
## Usage

You can now interact with Meshtastic through Discord.

```
$sendprimary <message> sends a message up to 225 characters to the the primary channel
$send nodenum=########### <message> sends a message up to 225 characters to nodenum ###########
$activenodes will list all nodes seen in the last 15 minutes
```
Note: The username of whoever interacts will be included in the message. Longer usernames will reduce the maximum available message length.

## Screenshot

![Interacting with Meshtastic through Discord](/DiscordScreenshot.png)

