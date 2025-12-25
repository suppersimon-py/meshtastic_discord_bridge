FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy your code
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose any ports if needed (optional)
# EXPOSE 12345

# Run the bot
CMD ["python", "meshtastic_discord_bridge.py"]