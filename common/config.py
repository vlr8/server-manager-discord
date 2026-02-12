"""
Shared Configuration for all server-apps bots.

Centralizes paths, database locations, guild/server IDs, and
environment variable overrides so every bot resolves the same
files without hardcoded relative paths.

On Railway:
    Set DATA_DIR env var to point at the persistent volume mount.
    e.g. DATA_DIR=/data  (Railway volume mounted at /data)

Locally:
    Defaults to server-apps/data/ relative to this file.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Directory layout
# ---------------------------------------------------------------------------

# Root of the monorepo (parent of common/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Persistent data directory - override via env var for Railway volumes
# Locally this resolves to server-apps/data/
DATA_DIR = Path(os.environ.get("DATA_DIR", str(PROJECT_ROOT / "data")))

# Ensure data directory exists on startup
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Database paths
# ---------------------------------------------------------------------------

# Main analytics database - shared by all 3 bots (read/write)
ANALYTICS_DB_PATH = DATA_DIR / "discord_analytics.db"

# Moderation database - primarily used by protector bot
MODERATION_DB_PATH = DATA_DIR / "moderation.db"

# ---------------------------------------------------------------------------
# RAG / ChromaDB paths (persona bot only for now)
# ---------------------------------------------------------------------------

CHROMA_DIR = DATA_DIR / "chroma_db"

# Raw Discord JSON exports used by import scripts
SERVER_EXPORT_DIR = DATA_DIR / "server_export"

# ---------------------------------------------------------------------------
# Discord server identity
# Override via env var if you run this for a different server
# ---------------------------------------------------------------------------

GUILD_ID = os.environ.get("GUILD_ID", "1158203871554961579")

# ---------------------------------------------------------------------------
# Persona bot target user (Nadia's Discord user ID)
# Used by RAG embedder to tag is_persona metadata
# ---------------------------------------------------------------------------

PERSONA_USER_ID = os.environ.get("PERSONA_USER_ID", "1436260342475919365")

# ---------------------------------------------------------------------------
# SQLite pragmas applied to every connection
# ---------------------------------------------------------------------------
# WAL mode allows concurrent readers + one writer without blocking.
# busy_timeout tells SQLite to wait up to N ms if the db is locked
# instead of immediately raising OperationalError.
SQLITE_PRAGMAS = {
    "journal_mode": "WAL",
    "busy_timeout": "5000",
    "synchronous": "NORMAL",     # safe with WAL, faster than FULL
    "foreign_keys": "ON",
}
