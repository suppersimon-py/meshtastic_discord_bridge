# Meshtastic Discord Bridge

A Discord bot that bridges discussions between a Discord channel and a Meshtastic mesh through a locally connected radio

## Requirements

- Python 3.8+
- A supported Meshtastic radio connected via USB or TCP
- Discord key and a channel

## Meshtastic Radio Configuration (Important)

The Meshtastic device connected to this bot acts as both a Discord bridge and a mesh infrastructure node.
For reliable operation especially direct messages to and from the bridge the device must be configured correctly.

### Device Role Guidelines
   - If the bridge node is not intended to act as a repeater:
        Set it to `CLIENT`. It will function as a bridge only, without relaying messages for other mesh nodes.
   - If the bridge node should act as a repeater (recommended):
      - Set it to `ROUTER_CLIENT` if your firmware supports it.
         This allows the bridge to forward messages on the mesh network while also bridging to Discord.
      - If `Router_CLIENT` is not available, set it to `ROUTER`. This will still allow bridging and message forwarding, but **without full client only behavior**.

   Do not leave it as `CLIENT` if you want devices on the mesh to reliably send direct messages to the bridge while it also repeats messages.

   Using `CLIENT` in that case can result in messages appearing sent on the mesh but never reaching discord.

### Set the role from the Terminal
Use the Meshtastic CLI on the system connected to the radio:
```
# Example for repeater + bridge behavior
meshtastic --port /dev/ttyACM0 --set device.role ROUTER_CLIENT

# If ROUTER_CLIENT is not available
meshtastic --port /dev/ttyACM0 --set device.role ROUTER

# If bridge only, without repeater behavior
meshtastic --port /dev/ttyACM0 --set device.role CLIENT

# Reboot to apply changes
meshtastic --port /dev/ttyACM0 --reboot
```

Verify the role after reboot:
```
meshtastic --port /dev/ttyACM0 --info
```
You should see something like this:
```
"role": "ROUTER_CLIENT"
```


## Installation and Startup

1. **Create a Discord Bot account**  
   Follow the [instructions](https://discordpy.readthedocs.io/en/stable/discord.html).
   
   Finding Channel ID [instructions](https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID#h_01HRSTXPS5FMK2A5SMVSX4JW4E).

3. **Configure bot permissions**
   - Go to **Bot**.
   - Under **Privileged Gateway Intents** 
   - Select the following:  
     - `Presence Intents`  
     - `Server Members Intent`  
     - `Message Content Intent`
   - Save changes
     
   - Go to **OAuth2 > URL Generator > Scopes > select bot**.  
   - Under **Bot Permissions**, select:  
     - `Read Message History`  
     - `Send Messages`  
     - `View Channels`

5. **Invite the bot**  
   - Copy the generated URL from OAuth2 tab and open it in a browser.  
   - Select your server and click **Authorize**.

6. **Set up the environment**  
   - On the first run, the bot will prompt you for the following:.
      - Discord Token – your bot’s token.
      - Discord Channel ID – the ID of the channel to bridge messages to.
      - Meshtastic Hostname – only needed if connecting via TCP. Leave blank to use a serial connection.
      - Include Username – whether to include the Discord username in messages sent to the primary channel.
      - Command Prefix – the prefix for bot commands (default is $).
   - These values will be automatically saved to `config.json` for future runs.
   - Docker Users: Environment variables can be set directly in the start command instead of interactive input.

4. **Install dependencies**

   - Terminal Users:
      ```
      python3 -m pip install -r requirements.txt
      or
      pip install -r requirements.txt
      ```

   - Docker Users:
      ```
      docker build -t meshtastic_bridge .
      ```
   
5. **start the bot**

    - Terminal Users:
      ```
      python meshtastic_discord_bridge.py
      ```
    - Docker Users:
      ```
      docker run -d \
        --name meshtastic_bridge \
        --restart unless-stopped \
        --device /dev/ttyACM0:/dev/ttyACM0 \
        -e DISCORD_TOKEN="your_token_here" \
        -e DISCORD_CHANNEL_ID="you_channel_id_here" \
        -e MESHTASTIC_HOSTNAME="" \
        -e INCLUDE_USERNAME="true" \
        -e COMMAND_PREFIX="$" \
        meshtastic_bridge
      ```
Finding the serial device
1. Plug in your Meshtastic device.
2. Check which device it is using:
   ```ls /dev/tty*```
      - On Linux, common names are **/dev/ttyACM0** or **/dev/ttyUSB0**.
      - On macOS, it might be **/dev/cu.usbmodemXXXX** or **/dev/cu.usbserial-XXXX**.
3. Use the detected device path in the Docker command:
     ```--device /dev/ttyACM0:/dev/ttyACM0```

## Usage

You can now interact with Meshtastic through Discord.
```
$sendprimary <message> sends a message up to 225 characters to the primary channel
$send nodenum=########### <message> sends a message up to 225 characters to nodenum ###########
$activenodes will list all nodes seen in the last 15 minutes
```


- ### Sending direct messages through the bridge
    - #### From Discord to Meshtastic:
   
       Use the command `send nodenum=########`
       - This will send a direct message to the specific node on the Meshtastic network. Replace `########` with the node's ID.
      
    - #### From Meshtastic to Discord
   
      To send a direct message to a Discord user, start your message with: `!USERNAME Your message here.`
       - `USERNAME` must be the Discord username of someone who has access to the main bridge channel.
       - The bridge will send the message directly to that user via DM.
       - If the message is not prefixed with a bridge node or username, it will be broadcast and visible to everyone on the Meshtastic network.

Message Length Note:

Meshtastic messages are limited to 225 characters.
   
   - Direct node messages (using `send nodenum=########`) will always include the sender's Discord username, even if the username inclusion is disabled globally.
    
      - Direct Message Example: `!suppersimon: Hello World`
    
      - Because of this, longer usernames reduce the maximum available length for the message text.
   - Primary channel messages
      - If a username inclusion is **enabled**, the sender's Discord Server Name is prepended, reducing the available message length.
      - **Enabled** Example: `SupperSimon: Hello World.`

      -

      - If username inclusion is **disabled**, the full 225 characters are available for the message body.
      - **Disabled** Example: `Hello World.`
      

## Screenshots

<img width="463" height="596" alt="image" src="https://github.com/user-attachments/assets/649dd8e7-1e40-4fb4-9c48-d44bf355a1b4" />

<img width="422" height="751" alt="IMG_7359" src="https://github.com/user-attachments/assets/6151814d-c907-493e-bc88-b8d17fac0ba6" />
