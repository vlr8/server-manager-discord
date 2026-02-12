import requests
import time

# The API endpoint for mcsrvstat.us for your Minecraft server
minecraft_api_url = "https://api.mcsrvstat.us/3/tranners.duckdns.org"

# The webhook URL for your Discord channel
discord_webhook_url = "https://discord.com/api/webhooks/1169358939821985832/OqaRKSu-jfTHDGE6v-n9BEhExiW0qdEPnUPtGBapaJdLy7gflhK0YNX8pZixJ-KENWKw"
# discord_webhook_url = "https://discord.com/api/webhooks/1128797456444952646/pccI_UV-i1hUz7mFHasAUYBkC4ELFsyz0aMspzOcD3JrEeIgSJVb8pxF_U_4NoAlOEje" # test

# Store the list of players from the last time you checked
last_seen_players = set()

while True:
    try:
        # Fetch current player data from mcsrvstat.us
        response = requests.get(minecraft_api_url)
        response.raise_for_status()
        data = response.json()

        current_players = set(player['name'] for player in data.get('players', {}).get('list', []))

        # Detect players who have joined since last check
        joined_players = current_players - last_seen_players
        for player in joined_players:
            webhook_data = {"content": f"{player} joined the game"}
            requests.post(discord_webhook_url, json=webhook_data)

        # Detect players who have left since last check
        left_players = last_seen_players - current_players
        for player in left_players:
            webhook_data = {"content": f"{player} left the game"}
            requests.post(discord_webhook_url, json=webhook_data)

        # Update the last seen players
        last_seen_players = current_players

    except requests.RequestException as e:
        print(f"An error occurred: {e}")

    # Wait for some time before the next check (e.g., 10 seconds)
    time.sleep(10)
