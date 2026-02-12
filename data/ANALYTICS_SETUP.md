# Discord Analytics Setup Guide

## Overview

This analytics system allows you to:
- Store all message history locally in SQLite
- Query usage statistics per channel and user
- Display analytics via Discord slash commands with embeds
- Export user message corpora for chatbot training

## Installation

### 1. Install DiscordChatExporter

**Windows (CLI):**
```bash
# Download from: https://github.com/Tyrrrz/DiscordChatExporter/releases
# Or use dotnet tool
dotnet tool install -g DiscordChatExporter.Cli
```

**Linux/macOS:**
```bash
# Using Docker
docker pull tyrrrz/discordchatexporter:stable
```

### 2. Export Your Server Data

Using your bot token (recommended for full access):

```bash
# Export entire server to JSON files (one per channel)
DiscordChatExporter.Cli exportguild -t "YOUR_BOT_TOKEN" -g YOUR_GUILD_ID --format Json -o ./discord_exports

# Or export specific channels
DiscordChatExporter.Cli export -t "YOUR_BOT_TOKEN" -c CHANNEL_ID --format Json -o ./discord_exports
```

**Docker version:**
```bash
docker run --rm -v /path/to/output:/out tyrrrz/discordchatexporter:stable \
  exportguild -t "YOUR_BOT_TOKEN" -g YOUR_GUILD_ID --format Json -o /out
```

### 3. Import Data Into Analytics Database

```python
import analytics_db as db

# Initialize the database (creates tables if they don't exist)
db.init_database()

# Import all JSON exports from a directory
db.import_all_exports('./discord_exports')

# Or import a single file
db.import_discord_export('./discord_exports/channel_name.json')
```

### 4. Add Commands to Your Bot

In your `bot1.py`, add these imports at the top:

```python
# Add to your imports
import analytics_db
from analytics_commands import *
```

Then add this to your `on_startup()` function:

```python
@interactions.listen()
async def on_startup():
    # ... your existing code ...
    
    # Initialize analytics database
    analytics_db.init_database()
    logger.info("Analytics database initialized")
```

### 5. Update Your consts.py (if needed)

Make sure these role IDs are available:
```python
# In common/consts.py
guild_id = YOUR_GUILD_ID
admin_role = YOUR_ADMIN_ROLE_ID
support_role = YOUR_SUPPORT_ROLE_ID
```

---

## Available Slash Commands

| Command | Description | Permissions |
|---------|-------------|-------------|
| `/server_stats` | Overall server statistics | Everyone |
| `/channel_stats` | Channel activity rankings | Everyone |
| `/user_stats` | Most active users leaderboard | Everyone |
| `/activity_hours` | Hourly activity heatmap (UTC) | Everyone |
| `/user_profile @user` | Detailed stats for a user | Everyone |
| `/daily_activity` | Recent daily message trends | Everyone |
| `/channel_compare` | Compare 2-3 channels side by side | Everyone |
| `/search_messages` | Search message content | Admin/Support |
| `/export_user @user` | Export user's messages to file | Admin/Support |

---

## Using Analytics Functions Directly

```python
import analytics_db as db

# Get server overview
stats = db.get_server_overview()
print(f"Total messages: {stats['total_messages']}")

# Get top channels
channels = db.get_channel_stats(limit=10)
for ch in channels:
    print(f"{ch['channel_name']}: {ch['message_count']} messages")

# Get top users
users = db.get_user_stats(limit=10)

# Get hourly activity pattern
hourly = db.get_hourly_activity()  # Returns dict: {0: count, 1: count, ..., 23: count}

# Get a user's messages for chatbot training
user_id = "123456789012345678"
messages = db.get_user_messages(user_id)

# Export to text file
db.export_user_corpus(user_id, "user_messages.txt")

# Get user's vocabulary (most common words)
vocab = db.get_user_vocabulary(user_id, top_n=50)

# Search messages
results = db.search_messages("keyword", limit=100)
```

---

## Keeping Data Updated

### Option A: Periodic Re-export (Simple)
Run the export monthly/weekly and re-import:

```python
# The import uses INSERT OR IGNORE, so duplicates are skipped
db.import_all_exports('./new_exports')
```

### Option B: Live Logging (Add to bot)
Add this to your `on_message_create` listener to log messages in real-time:

```python
import analytics_db as db
import sqlite3

@client.listen()
async def on_message_create(ctx):
    # ... your existing code ...
    
    # Log to analytics (skip bots)
    if not ctx.message.author.bot:
        try:
            conn = sqlite3.connect('discord_analytics.db')
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO messages 
                (message_id, channel_id, channel_name, author_id, author_name,
                 author_bot, content, timestamp, timestamp_unix, has_attachments,
                 has_embeds, is_reply, reply_to_id, word_count, char_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(ctx.message.id),
                str(ctx.message.channel.id),
                ctx.message.channel.name,
                str(ctx.message.author.id),
                ctx.message.author.display_name,
                0,
                ctx.message.content,
                datetime.datetime.now().isoformat(),
                datetime.datetime.now().timestamp(),
                1 if ctx.message.attachments else 0,
                1 if ctx.message.embeds else 0,
                1 if ctx.message.message_reference else 0,
                str(ctx.message.message_reference.message_id) if ctx.message.message_reference else None,
                len(ctx.message.content.split()),
                len(ctx.message.content)
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Analytics logging error: {e}")
```

---

## Future: Creating a User Chatbot

Once you have enough messages from a user, you can create a simple chatbot:

```python
import analytics_db as db

# Export user corpus
user_id = "123456789012345678"
db.export_user_corpus(user_id, "user_corpus.txt")

# Option 1: Use the corpus for fine-tuning a small model
# Option 2: Use as few-shot examples for an LLM
# Option 3: Simple markov chain (for fun, low quality)

# Example: Generate few-shot prompt for Claude/GPT
messages = db.get_user_messages(user_id, limit=50)
sample_messages = [m['content'] for m in messages if 10 < len(m['content']) < 200][:20]

prompt = f"""You are roleplaying as a Discord user. Here are examples of how they write:

{chr(10).join(f'- "{msg}"' for msg in sample_messages)}

Now respond in their style to: [user input here]"""
```

---

## Database Schema

The SQLite database (`discord_analytics.db`) has these tables:

**messages**
- message_id, channel_id, channel_name
- author_id, author_name, author_bot
- content, timestamp, timestamp_unix
- has_attachments, has_embeds, is_reply, reply_to_id
- word_count, char_count

**channels**
- channel_id, channel_name, category
- message_count, last_updated

**users**
- user_id, username, display_name
- message_count, first_seen, last_seen

---

## Tips

1. **First export might take a while** - large servers can have millions of messages
2. **Keep exports in a backup folder** - the JSON files are your raw source data
3. **SQLite is fast** - even millions of messages query quickly with proper indexes
4. **Privacy consideration** - keep the database file secure, it contains all message content
