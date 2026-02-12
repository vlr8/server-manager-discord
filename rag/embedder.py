"""
Message Embedder - Embeds messages from SQLite into ChromaDB with rich metadata.

Usage:
    python -m rag.embedder --rebuild   # Full rebuild from scratch
    python -m rag.embedder             # Incremental (only new messages)
    python -m rag.embedder --stats     # Show collection statistics
"""

import re
import sys
import json
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

# Add parent to path for imports when running as module
sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.config import (
    SQLITE_DB_PATH,
    PERSONA_AUTHOR_IDS,
    CHROMA_PERSIST_DIR,
    EMBEDDING_MODEL,
    COLLECTION_NAME,
    MIN_MESSAGE_LENGTH,
    MAX_MESSAGE_LENGTH,
    EMBEDDING_BATCH_SIZE,
    EMBED_STATE_FILE,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_messages_from_sqlite(since_timestamp: float = 0) -> list[dict]:
    """
    Load persona messages from SQLite with full metadata.

    Args:
        since_timestamp: Only load messages after this unix timestamp.
                         Pass 0 to load all.

    Returns list of dicts with 'id', 'text', and 'metadata'.
    """
    if not SQLITE_DB_PATH.exists():
        logger.error(f"SQLite database not found: {SQLITE_DB_PATH}")
        return []

    conn = sqlite3.connect(str(SQLITE_DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    placeholders = ','.join('?' * len(PERSONA_AUTHOR_IDS))

    cursor.execute(f"""
        SELECT
            m.message_id,
            m.content,
            m.author_id,
            m.author_name,
            m.channel_name,
            m.timestamp_unix,
            m.is_reply,
            m2.author_name AS reply_to_author
        FROM messages m
        LEFT JOIN messages m2 ON m.reply_to_id = m2.message_id
        WHERE m.author_id IN ({placeholders})
          AND m.char_count >= ?
          AND m.char_count <= ?
          AND m.timestamp_unix > ?
          AND m.content != ''
          AND m.author_bot = 0
        ORDER BY m.timestamp_unix ASC
    """, (*PERSONA_AUTHOR_IDS, MIN_MESSAGE_LENGTH, MAX_MESSAGE_LENGTH, since_timestamp))

    messages = []
    for row in cursor:
        text = row['content'].strip()

        if not text:
            continue
        if text.startswith('http') or text.startswith('<http'):
            continue
        if re.match(r'^(<a?:\w+:\d+>\s*)+$', text):
            continue
        if text.startswith('/') or text.startswith('.') or text.startswith('!'):
            continue
        if re.match(r'^(<@!?\d+>\s*)+$', text):
            continue

        ts = row['timestamp_unix']
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            year_month = dt.strftime('%Y-%m')
        except Exception:
            year_month = 'unknown'

        messages.append({
            'id': str(row['message_id']),
            'text': text,
            'metadata': {
                'author_id': row['author_id'],
                'author_name': row['author_name'],
                'channel_name': row['channel_name'] or 'unknown',
                'timestamp_unix': float(ts),
                'year_month': year_month,
                'is_persona': 1,
                'is_reply': int(row['is_reply']),
                'reply_to_author': row['reply_to_author'] or '',
                'char_length': len(text),
                'word_count': len(text.split()),
            }
        })

    conn.close()
    logger.info(f"Loaded {len(messages)} messages from SQLite (since_timestamp={since_timestamp})")
    return messages


def _load_embed_state() -> dict:
    """Load incremental embedding state from disk."""
    if EMBED_STATE_FILE.exists():
        with open(EMBED_STATE_FILE, 'r') as f:
            return json.load(f)
    return {}


def _save_embed_state(messages: list[dict], existing_count: int = 0):
    """Save embedding state after successful run."""
    max_ts = max((m['metadata']['timestamp_unix'] for m in messages), default=0)
    state = {
        'last_embedded_timestamp': max_ts,
        'last_run_iso': datetime.now(tz=timezone.utc).isoformat(),
        'total_embedded': len(messages) + existing_count,
    }
    EMBED_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EMBED_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)
    logger.info(f"Saved embed state: last_timestamp={max_ts}")


def embed_messages(messages: list[dict], rebuild: bool = False) -> None:
    """
    Embed messages and store in ChromaDB.

    Args:
        messages: List of message dicts with 'id', 'text', 'metadata'
        rebuild: If True, delete existing collection and rebuild
    """
    try:
        from sentence_transformers import SentenceTransformer
        import chromadb
    except ImportError as e:
        logger.error(f"Missing dependency: {e}")
        logger.error("Install with: pip install sentence-transformers chromadb")
        return

    CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)

    logger.info(f"Initializing ChromaDB at: {CHROMA_PERSIST_DIR}")
    client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))

    existing_collections = [c.name for c in client.list_collections()]

    if COLLECTION_NAME in existing_collections:
        if rebuild:
            logger.info(f"Rebuilding collection '{COLLECTION_NAME}'...")
            client.delete_collection(COLLECTION_NAME)
        else:
            # Incremental mode - collection exists, we'll upsert
            collection = client.get_collection(COLLECTION_NAME)
            existing_count = collection.count()
            logger.info(f"Collection '{COLLECTION_NAME}' has {existing_count} messages, upserting {len(messages)} new")

            if not messages:
                logger.info("No new messages to embed")
                return

            # Upsert in batches
            for i in range(0, len(messages), EMBEDDING_BATCH_SIZE):
                batch = messages[i:i + EMBEDDING_BATCH_SIZE]
                texts = [m['text'] for m in batch]
                embeddings = model.encode(texts, show_progress_bar=False)

                collection.upsert(
                    ids=[m['id'] for m in batch],
                    embeddings=embeddings.tolist(),
                    documents=texts,
                    metadatas=[m['metadata'] for m in batch]
                )

                progress = min(i + EMBEDDING_BATCH_SIZE, len(messages))
                logger.info(f"Progress: {progress}/{len(messages)} messages upserted")

            final_count = collection.count()
            logger.info(f"Done! Collection now has {final_count} messages")
            _save_embed_state(messages, existing_count)
            return

    # Create new collection with cosine similarity
    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )

    logger.info(f"Embedding {len(messages)} messages in batches of {EMBEDDING_BATCH_SIZE}...")

    for i in range(0, len(messages), EMBEDDING_BATCH_SIZE):
        batch = messages[i:i + EMBEDDING_BATCH_SIZE]
        texts = [m['text'] for m in batch]
        embeddings = model.encode(texts, show_progress_bar=False)

        collection.add(
            ids=[m['id'] for m in batch],
            embeddings=embeddings.tolist(),
            documents=texts,
            metadatas=[m['metadata'] for m in batch]
        )

        progress = min(i + EMBEDDING_BATCH_SIZE, len(messages))
        logger.info(f"Progress: {progress}/{len(messages)} messages embedded")

    final_count = collection.count()
    logger.info(f"Done! Embedded {final_count} messages to {CHROMA_PERSIST_DIR}")
    _save_embed_state(messages)


def show_stats():
    """Show collection statistics including metadata distribution."""
    try:
        import chromadb
    except ImportError:
        logger.error("chromadb not installed")
        return

    client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
    existing = [c.name for c in client.list_collections()]

    if COLLECTION_NAME not in existing:
        logger.info(f"Collection '{COLLECTION_NAME}' does not exist")
        return

    collection = client.get_collection(COLLECTION_NAME)
    count = collection.count()
    logger.info(f"Collection '{COLLECTION_NAME}': {count} messages")

    # Sample some documents to show metadata
    if count > 0:
        sample = collection.get(limit=5, include=['documents', 'metadatas'])
        logger.info("Sample messages:")
        for doc, meta in zip(sample['documents'], sample['metadatas']):
            ym = meta.get('year_month', '?')
            ch = meta.get('channel_name', '?')
            logger.info(f"  [{ym}, #{ch}] {doc[:80]}...")

        # Show year_month distribution from a larger sample
        big_sample = collection.get(limit=min(1000, count), include=['metadatas'])
        from collections import Counter
        ym_counts = Counter(m.get('year_month', '?') for m in big_sample['metadatas'])
        logger.info("Year-month distribution (sample):")
        for ym, c in sorted(ym_counts.items()):
            logger.info(f"  {ym}: {c}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Embed messages for RAG')
    parser.add_argument('--rebuild', action='store_true',
                        help='Delete existing embeddings and rebuild from scratch')
    parser.add_argument('--stats', action='store_true',
                        help='Show collection statistics')
    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if args.rebuild:
        logger.info(f"Full rebuild from SQLite: {SQLITE_DB_PATH}")
        messages = load_messages_from_sqlite(since_timestamp=0)
    else:
        # Incremental: only embed messages newer than last run
        state = _load_embed_state()
        last_ts = state.get('last_embedded_timestamp', 0)
        if last_ts > 0:
            logger.info(f"Incremental mode: loading messages since {last_ts}")
        else:
            logger.info("No previous state found, loading all messages")
        messages = load_messages_from_sqlite(since_timestamp=last_ts)

    if not messages:
        logger.info("No messages to embed.")
        return

    logger.info(f"Loaded {len(messages)} messages after filtering")
    embed_messages(messages, rebuild=args.rebuild)


if __name__ == "__main__":
    main()
