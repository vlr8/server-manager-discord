"""
Initialize all databases.

Run this once after cloning or after clearing the data directory.
Safe to run repeatedly - all CREATE statements use IF NOT EXISTS.

Usage:
    python -m scripts.init_databases
    # or from project root:
    python scripts/init_databases.py
"""

import sys
from pathlib import Path

# Ensure common/ is importable when running as a standalone script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.config import DATA_DIR, ANALYTICS_DB_PATH, MODERATION_DB_PATH
from common.db import init_database
from common.moderation_db import init_moderation_db


def main():
    print(f"Data directory: {DATA_DIR}")
    print(f"Analytics DB:   {ANALYTICS_DB_PATH}")
    print(f"Moderation DB:  {MODERATION_DB_PATH}")
    print()

    init_database()
    init_moderation_db()

    print()
    print("All databases initialized. Ready to start bots.")


if __name__ == "__main__":
    main()
