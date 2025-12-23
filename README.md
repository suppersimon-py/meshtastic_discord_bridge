# meshtastic_discord_bridge

A Discord bot which bridges discussions between a Discord channel and a Meshtastic mesh through a locally connected radio

## Requirements

- Python
- A supported Meshtastic radio connected via USB 
- Discord key and a channel

## Installation and Startup

1. **Create a Discord Bot account**  
   Follow the [instructions](https://discordpy.readthedocs.io/en/stable/discord.html).
   
   Finding Channel ID [instructions](https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID#h_01HRSTXPS5FMK2A5SMVSX4JW4E).

3. **Configure bot permissions**  
   - Go to **OAuth2 > URL Generator** in your Discord application.  
   - Under **Scopes**, select **bot**.  
   - This will expand **Bot Permissions**—select the following:  
     - `Read Message History`  
     - `Send Messages`  
     - `View Channels`  

4. **Invite the bot to your server**  
   - Copy the generated URL from Step 2 and open it in a browser.  
   - Select the server you want the bot to join and click **Authorize**.


5. **Set up your environment**  
   - On first run, the bot will prompt you for your Discord token, channel ID, and Meshtastic hostname (if using TCP).
   - If you leave the Meshtastic hostname blank, the bot will attempt to connect via a serial interface.
   - Whether to include the Discord username in forwarded messages
   - These values will be saved automatically to a .env file for future runs.  

4. **Install dependencies**

```bash
python3 -m pip install -r requirements.txt
```

5. **start the bot**
```bash
python meshtastic_discord_bridge.py
```

You can also bypass the manual setup by passing along the enviroment settings while starting the script

```bash
python meshtastic_discord_bridge.py --token "TOKEN" --channel-id CHANNEL_ID --meshtastic-host "HOSTNAME-LEAVE-EMPTY-IF-USING-SERIAL" --include-username true
```

## Usage

You can now interact with Meshtastic through Discord.

```
$sendprimary <message> sends a message up to 225 characters to the the primary channel
$send nodenum=########### <message> sends a message up to 225 characters to nodenum ###########
$activenodes will list all nodes seen in the last 15 minutes
```
Message Length Note:

Meshtastic messages are limited to 225 characters.

If username inclusion is enabled, the sender’s Discord username is prepended to the message (for example: SupperSimon: Hello world).
This means longer usernames reduce the maximum length available for the message text itself.

If username inclusion is disabled, the full 225 characters are available for the message body.

## Screenshots

<img width="463" height="596" alt="image" src="https://github.com/user-attachments/assets/649dd8e7-1e40-4fb4-9c48-d44bf355a1b4" />

<img width="422" height="751" alt="IMG_7359" src="https://github.com/user-attachments/assets/6151814d-c907-493e-bc88-b8d17fac0ba6" />
