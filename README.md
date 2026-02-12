# data/

Persistent storage directory for all bot databases and vector stores.

**This directory is gitignored.** Contents are created on first run:

- `discord_analytics.db` — Shared analytics database (all 3 bots)
- `moderation.db` — Moderation database (protector bot)
- `chroma_db/` — ChromaDB vector store (persona bot RAG)
- `server_export/` — Raw DiscordChatExporter JSON files

## Railway deployment

On Railway, set the environment variable `DATA_DIR=/data` and attach
a persistent volume mounted at `/data`. All three bot services will
read/write to the same volume.

## Local development

Databases are created automatically at `server-apps/data/` when you
first run any bot or the init scripts:

```bash
python -m common.db          # Initialize analytics DB
python -m common.moderation_db  # Initialize moderation DB
```
