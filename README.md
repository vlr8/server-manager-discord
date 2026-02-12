# server-manager-discord

A monorepo running three Discord bots as a unified ecosystem for the Trannerland server. All bots share a common database layer and deploy to Railway as a single service.

## The bots

**Trannyverse** — Main server bot. Slash commands for unit conversion, analytics, activity tracking, highlights, gag system, daily posts, and server utilities. Primary writer of all live messages to the shared database.

**tos-cleaner (protector)** — Content moderation bot. Real-time message scanning with bad word detection, sentiment analysis (VADER), ToS violation flagging, pattern learning, and auto-deletion with configurable severity levels.

**Nadiabot (persona)** — AI persona chatbot that emulates a specific community member using RAG retrieval over the full message archive, Claude API for response generation, and local GPU vision analysis (CLIP Interrogator + Florence-2) for image reactions.

## Repository structure

```
server-manager-discord/
├── run_all.py                  # Process manager: spawns all 3 bots
├── Procfile                    # Railway: worker: python run_all.py
├── requirements.txt            # Shared dependencies (no GPU packages)
├── requirements-local.txt      # GPU dependencies (local dev only)
├── pyproject.toml              # Editable install config
├── .env                        # Local tokens & secrets (gitignored)
│
├── common/                     # Shared library — all bots import from here
│   ├── __init__.py
│   ├── config.py               # Paths, DB locations, env var overrides
│   ├── db.py                   # Unified analytics DB (WAL mode, shared)
│   ├── moderation_db.py        # Moderation DB (protector + shared reads)
│   └── models.py               # Typed dataclasses for cross-module contracts
│
├── bots/
│   ├── persona/                # Nadiabot entry: python -m bots.persona.persona_bot
│   │   ├── persona_bot.py
│   │   ├── system_prompt.txt
│   │   └── ...
│   │
│   ├── trannyverse/            # Main bot entry: python -m bots.trannyverse.bot1
│   │   ├── bot1.py
│   │   ├── extensions/         # Slash command modules (renamed from discord/)
│   │   ├── analytics_commands.py
│   │   ├── highlights.py
│   │   └── ...
│   │
│   └── protector/              # Moderation bot entry: python -m bots.protector.server_helper
│       ├── server_helper.py
│       ├── bad_word_scanner.py
│       ├── content_analyzer.py
│       └── ...
│
├── rag/                        # RAG pipeline (persona bot)
│   ├── config.py               # Embedding model, ChromaDB settings
│   ├── embedder.py             # Batch + real-time message embedding
│   └── retriever.py            # Semantic search with temporal/author filters
│
├── vision/                     # Image analysis (persona bot, local GPU only)
│   ├── interrogator.py         # CLIP Interrogator singleton
│   ├── florence.py             # Florence-2 OCR + captioning
│   └── parsing.py              # Image type classification, output formatting
│
├── scripts/
│   ├── init_databases.py       # Create all tables (safe to run repeatedly)
│   └── prepare_chatbot.py      # Analyze user message patterns for persona
│
└── data/                       # Persistent storage (gitignored)
    ├── discord_analytics.db    # ~1.6 GB shared analytics database
    ├── moderation.db           # Moderation tracking
    └── chroma_db/              # ChromaDB vector store (~460 MB)
```

## How it runs

`run_all.py` is a process manager that spawns each bot as a **separate Python subprocess** using `python -m bots.<name>.<entry>`. This is important because `discord-py-interactions` registers slash command decorators against a specific `Client` instance at import time — multiple clients in one process breaks command handling.

Each bot gets its own Python interpreter and event loop, but they all share the same filesystem (and therefore the same SQLite databases). The process manager monitors all children and auto-restarts any bot that crashes after a 10-second delay.

```
run_all.py (parent process)
├── python -m bots.trannyverse.bot1    (child PID 1)
├── python -m bots.protector.server_helper  (child PID 2)
└── python -m bots.persona.persona_bot      (child PID 3)
```

Railway sends SIGTERM when stopping the service. The process manager catches it and gracefully terminates all children.

## Local development

### First-time setup

```bash
git clone git@github.com:vlr8/server-manager-discord.git
cd server-manager-discord

# Create virtualenv
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install GPU deps if you have an NVIDIA GPU (for vision pipeline)
pip install -r requirements-local.txt

# Register the monorepo as an editable package so all imports work
pip install -e .

# Create your .env file with bot tokens
cp .env.example .env  # then edit with your tokens
```

### Environment variables

Create a `.env` file at the repo root:

```env
PERSONA_BOT_TOKEN=your_token_here
TRANNYVERSE_BOT_TOKEN=your_token_here
PROTECTOR_BOT_TOKEN=your_token_here
ANTHROPIC_API_KEY=sk-ant-...
GUILD_ID=1158203871554961579
PERSONA_USER_ID=1436260342475919365
```

### Running locally

```bash
# Run all bots together (recommended)
python run_all.py

# Or run individual bots for development
python -m bots.trannyverse.bot1
python -m bots.protector.server_helper
python -m bots.persona.persona_bot
```

### Initialize databases (if starting fresh)

```bash
python scripts/init_databases.py
```

This creates empty `discord_analytics.db` and `moderation.db` in `data/` with all tables. Safe to run multiple times — all statements use `CREATE IF NOT EXISTS`.

## Database architecture

Two SQLite databases, both using WAL (Write-Ahead Logging) mode for safe concurrent access from multiple bot processes.

**discord_analytics.db** (shared by all 3 bots)
- `messages` — Bulk-imported historical messages from DiscordChatExporter JSON
- `live_messages` — Real-time messages captured by trannyverse's `on_message_create`
- `channels` — Channel metadata
- `users` — User metadata
- `highlights` — Repost/highlight tracking
- `message_reply_tracking` — Reply chain tracking

**moderation.db** (protector bot primary, others can read)
- `flagged_messages` — Auto-moderated message audit trail
- `bad_words` — Configurable word filter with severity levels
- `learned_patterns` — ML-discovered moderation patterns
- `user_offenses` — Repeat offender tracking
- `monitored_channels` — Per-channel monitoring config
- `training_samples` — Pattern learning training data
- `scan_progress` — Resume capability for historical scans

### Write responsibility

| Table | Writer | Readers |
|-------|--------|---------|
| `live_messages` | trannyverse only | persona, protector |
| `messages` (historical) | import scripts | all 3 |
| `highlights` | trannyverse | persona |
| `flagged_messages` | protector | trannyverse |
| `moderation.db` tables | protector | all 3 |

This avoids duplicate writes. Trannyverse is the single source of truth for live messages.

### Concurrency

WAL mode + busy timeout on every connection:

```python
conn.execute("PRAGMA journal_mode = WAL")     # concurrent readers + 1 writer
conn.execute("PRAGMA busy_timeout = 5000")    # wait 5s if locked
conn.execute("PRAGMA synchronous = NORMAL")   # safe with WAL, faster than FULL
```

At Discord message rates (5-10 msg/sec peak), this handles three concurrent bot processes without lock contention.

## Railway deployment

The entire ecosystem runs as a **single Railway service** with one persistent volume. This is necessary because Railway volumes can only attach to one service.

### Architecture on Railway

```
Railway Project: server-manager-discord
└── Service: worker
    ├── Procfile: worker: python run_all.py
    ├── Volume: /data (5 GB, US West)
    └── Environment Variables:
        ├── DATA_DIR=/data
        ├── GUILD_ID=...
        ├── TRANNYVERSE_BOT_TOKEN=...
        ├── PROTECTOR_BOT_TOKEN=...
        ├── PERSONA_BOT_TOKEN=...
        └── ANTHROPIC_API_KEY=...
```

### Initial setup

1. Create a Railway project and connect the GitHub repo
2. Railway auto-detects the Procfile and creates a worker service
3. Add a volume mounted at `/data`
4. Add all environment variables (tokens, DATA_DIR, GUILD_ID, etc.)
5. Seed the databases (see below)
6. Deploy

### Seeding databases to the Railway volume

Railway volumes start empty. The databases need to be uploaded on first deploy. `run_all.py` includes a one-time seeding mechanism that downloads from Google Drive.

**Step 1: Compress and upload locally**

```bash
cd data/

# Compress the large analytics DB (1.6 GB → ~200 MB)
xz -k discord_analytics.db

# Tar the ChromaDB directory
tar cJf chroma_db.tar.xz chroma_db/

# Upload all 3 to Google Drive, share each as "Anyone with the link"
# discord_analytics.db.xz
# moderation.db
# chroma_db.tar.xz
```

**Step 2: Add seed URLs as Railway env vars**

For each Google Drive file, get the file ID from the share link (`https://drive.google.com/file/d/FILE_ID/view`) and set:

```
DB_SEED_URL=https://drive.google.com/uc?export=download&id=FILE_ID
MODERATION_DB_SEED_URL=https://drive.google.com/uc?export=download&id=FILE_ID
CHROMA_SEED_URL=https://drive.google.com/uc?export=download&id=FILE_ID
```

**Step 3: Deploy**

The seeding code in `run_all.py` checks if each file exists on the volume. If not, it downloads and decompresses using `gdown` (handles Google Drive's large file confirmation). After the first successful deploy, remove the `*_SEED_URL` env vars.

### GPU limitations

Railway has no GPU instances. The vision pipeline (CLIP Interrogator, Florence-2) is disabled in production. The RAG embedding model (`all-MiniLM-L6-v2`) runs fine on CPU at ~10-20ms per message.

Locally with an RTX 4070 Super, install `requirements-local.txt` for full vision support.

### Monitoring

- **Railway dashboard** → Deploy Logs shows interleaved output from all 3 bots
- **Volume metrics** → Shows disk usage over time
- **Discord commands** → `/db_stats` for live message counts, `/db_backup` for snapshots

### Costs

Railway Hobby plan: $5/month credit. A single worker service running 24/7 with 3 bot processes uses ~$3-4/month of compute. The 5 GB volume is included. Monitor usage at Railway dashboard → Settings → Usage.

## Import pipeline

### Historical messages (from DiscordChatExporter)

```bash
# Export channels using DiscordChatExporter (JSON format)
# Place exports in data/server_export/

# Import all at once
python -c "from common.db import import_all_exports; import_all_exports('data/server_export')"

# Or import individual files (auto-uses streaming for files > 100 MB)
python -c "from common.db import import_discord_export; import_discord_export('data/server_export/general.json')"
```

### RAG embeddings

After importing historical messages, build the ChromaDB vector store:

```bash
python -m rag.embedder
```

This encodes all messages using `all-MiniLM-L6-v2` and stores them in ChromaDB with metadata (author, channel, timestamp, is_persona flag) for filtered retrieval.

Live messages are embedded in real-time by the persona bot's `on_message_create` handler using `embed_live_message()`.

## Key design decisions

**Why a monorepo?** All three bots were duplicating `analytics_db.py` and maintaining separate databases. The shared `common/` package eliminates code duplication, and a single `discord_analytics.db` means consistent data across all bots.

**Why subprocess spawning instead of asyncio.gather?** `discord-py-interactions` registers slash command decorators against a `Client` instance at import time. Importing multiple bot modules into one process causes decorator registration conflicts and commands fail to respond. Separate processes give each bot its own interpreter.

**Why SQLite instead of Postgres?** SQLite with WAL mode handles the concurrency requirements (3 bots, 5-10 msg/sec peak) without a separate database server. The file lives on a Railway volume, is trivially backed up, and works identically in local development. ChromaDB uses SQLite internally too.

**Why not 3 Railway services?** Railway volumes can only attach to one service. A single service with subprocess-managed bots gets around this while keeping the shared filesystem.

## Troubleshooting

**Bot commands not responding:** If slash commands are detected in logs but Discord shows "The application did not respond", the bot's `Client` instance isn't the one that registered the command. This happens when multiple clients share a process. Make sure each bot runs as a separate subprocess via `run_all.py`.

**`ModuleNotFoundError: No module named 'discord'`:** The `bots/trannyverse/extensions/` directory was previously named `discord/`, which shadows the actual discord library. If you see this error, check for any local directories named `discord`.

**`common` import conflicts:** Do NOT install the PyPI package `common==0.1.2`. It conflicts with the local `common/` directory. If `pip freeze` shows it, run `pip uninstall common`.

**Database locked errors:** All connections should use WAL mode. Check that `common/config.py` SQLITE_PRAGMAS are being applied. If a bot crashes mid-write, WAL mode recovers automatically on next connection.

**Railway deploy crashes with KeyError for tokens:** Environment variable changes in Railway's UI need to be explicitly applied with the "Apply X changes" button before they take effect.