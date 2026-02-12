"""
Analytics Database Module (shared across all bots).

Handles storage and querying of Discord message data:
- Bulk-imported historical messages (from DiscordChatExporter JSON)
- Live messages captured in real-time by on_message_create
- Highlight tracking
- Reply tracking
- User and channel metadata

All connections use WAL mode for safe concurrent access from
multiple bot processes. See common/config.py for path configuration.

Usage from any bot:
    from common.db import get_connection, insert_live_message, search_messages
"""

import sqlite3
import json
import os
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from collections import Counter

from .config import ANALYTICS_DB_PATH, SQLITE_PRAGMAS

# Optional streaming parser for large JSON imports
try:
    import ijson
    IJSON_AVAILABLE = True
except ImportError:
    IJSON_AVAILABLE = False

logger = logging.getLogger(__name__)


# ============================================================================
# CONNECTION MANAGEMENT
# ============================================================================

def get_connection(db_path: Path = None) -> sqlite3.Connection:
    """
    Get a WAL-enabled database connection with row factory.

    Every connection automatically applies the pragmas from config
    (WAL journal, busy timeout, etc.) so multiple bot processes can
    safely read/write concurrently.

    Args:
        db_path: Override path. Defaults to ANALYTICS_DB_PATH from config.

    Returns:
        sqlite3.Connection with Row factory enabled.
    """
    path = str(db_path or ANALYTICS_DB_PATH)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row

    # Apply WAL and other performance/safety pragmas
    for pragma, value in SQLITE_PRAGMAS.items():
        conn.execute(f"PRAGMA {pragma} = {value}")

    return conn


@contextmanager
def db_session(db_path: Path = None):
    """
    Context manager for database operations with automatic commit/rollback.

    Usage:
        with db_session() as (conn, cursor):
            cursor.execute("INSERT INTO ...")
        # auto-commits on success, rolls back on exception, always closes

    Args:
        db_path: Override path. Defaults to ANALYTICS_DB_PATH.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        yield conn, cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================================
# SCHEMA INITIALIZATION
# ============================================================================

def init_database():
    """
    Initialize the full analytics database schema.

    Safe to call multiple times - uses CREATE IF NOT EXISTS for all
    tables and indexes. Call this on bot startup to ensure the schema
    exists before any queries run.
    """
    with db_session() as (conn, cursor):

        # ----- Historical messages (bulk imported from DiscordChatExporter) -----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                message_id TEXT UNIQUE,
                channel_id TEXT,
                channel_name TEXT,
                author_id TEXT,
                author_name TEXT,
                author_discriminator TEXT,
                author_bot INTEGER DEFAULT 0,
                content TEXT,
                timestamp TEXT,
                timestamp_unix REAL,
                has_attachments INTEGER DEFAULT 0,
                has_embeds INTEGER DEFAULT 0,
                is_reply INTEGER DEFAULT 0,
                reply_to_id TEXT,
                word_count INTEGER DEFAULT 0,
                char_count INTEGER DEFAULT 0
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_channel_id ON messages(channel_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_author_id ON messages(author_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON messages(timestamp_unix)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_channel_timestamp ON messages(channel_id, timestamp_unix)")

        # ----- Channel metadata -----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY,
                channel_name TEXT,
                category TEXT,
                message_count INTEGER DEFAULT 0,
                last_updated TEXT
            )
        """)

        # ----- User metadata -----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                display_name TEXT,
                message_count INTEGER DEFAULT 0,
                first_seen TEXT,
                last_seen TEXT
            )
        """)

        # ----- Live messages (real-time capture from on_message_create) -----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE NOT NULL,
                channel_id TEXT NOT NULL,
                author_id TEXT NOT NULL,
                author_name TEXT,
                author_nickname TEXT,
                author_avatar_url TEXT,
                content TEXT,
                timestamp TEXT,
                timestamp_edited TEXT,
                is_pinned INTEGER DEFAULT 0,
                is_reply INTEGER DEFAULT 0,
                reply_to_message_id TEXT,
                attachments_json TEXT,
                embeds_json TEXT,
                reactions_json TEXT,
                mentions_json TEXT,
                created_at REAL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_channel ON live_messages(channel_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_author ON live_messages(author_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_timestamp ON live_messages(created_at)")

        # ----- Highlights (repost tracking) -----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS highlights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                highlight_id TEXT UNIQUE NOT NULL,
                original_message_id TEXT NOT NULL,
                author_id TEXT NOT NULL,
                created_at REAL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_highlight_original ON highlights(original_message_id)")

        # ----- Reply tracking -----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_reply_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reply_id TEXT UNIQUE NOT NULL,
                original_message_id TEXT NOT NULL,
                author_id TEXT NOT NULL,
                reply_content TEXT,
                created_at REAL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reply_original ON message_reply_tracking(original_message_id)")

    logger.info(f"Analytics database initialized at {ANALYTICS_DB_PATH}")


# ============================================================================
# DISCORD EXPORT IMPORT (historical data)
# ============================================================================

def _process_export_message(msg: dict, channel_id: str, channel_name: str) -> tuple:
    """
    Transform a single DiscordChatExporter JSON message into a row tuple
    matching the `messages` table schema.
    """
    message_id = str(msg.get('id', ''))
    author = msg.get('author', {})
    author_id = str(author.get('id', ''))
    author_name = author.get('name', 'Unknown')
    author_discriminator = author.get('discriminator', '0')
    author_bot = 1 if author.get('isBot', False) else 0

    content = msg.get('content', '')
    timestamp_str = msg.get('timestamp', '')

    # Parse ISO timestamp into unix float
    try:
        ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        timestamp_unix = ts.timestamp()
    except (ValueError, TypeError):
        timestamp_unix = 0

    has_attachments = 1 if msg.get('attachments') else 0
    has_embeds = 1 if msg.get('embeds') else 0

    reference = msg.get('reference', {}) or {}
    is_reply = 1 if reference.get('messageId') else 0
    reply_to_id = str(reference.get('messageId', '')) if is_reply else None

    word_count = len(content.split()) if content else 0
    char_count = len(content) if content else 0

    return (message_id, channel_id, channel_name, author_id, author_name,
            author_discriminator, author_bot, content, timestamp_str, timestamp_unix,
            has_attachments, has_embeds, is_reply, reply_to_id, word_count, char_count)


_INSERT_MSG_SQL = """
    INSERT OR IGNORE INTO messages
    (message_id, channel_id, channel_name, author_id, author_name,
     author_discriminator, author_bot, content, timestamp, timestamp_unix,
     has_attachments, has_embeds, is_reply, reply_to_id, word_count, char_count)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def import_discord_export(json_path: str, channel_name: str = None):
    """
    Import messages from a DiscordChatExporter JSON file.

    Automatically switches to streaming parser for files > 100 MB
    (requires ijson: pip install ijson).

    Args:
        json_path: Path to the exported JSON file.
        channel_name: Optional override for channel name.

    Returns:
        (imported_count, skipped_count) tuple.
    """
    file_size = os.path.getsize(json_path)
    if file_size > 100 * 1024 * 1024 and IJSON_AVAILABLE:
        logger.info(f"Large file ({file_size / (1024**3):.2f} GB), using streaming parser")
        return _import_streaming(json_path, channel_name)

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    channel_id = str(data.get('channel', {}).get('id', ''))
    ch_name = channel_name or data.get('channel', {}).get('name', 'unknown')
    category = data.get('channel', {}).get('category', 'uncategorized')
    messages = data.get('messages', [])

    imported_count = 0
    skipped_count = 0

    with db_session() as (conn, cursor):
        for msg in messages:
            try:
                row = _process_export_message(msg, channel_id, ch_name)
                cursor.execute(_INSERT_MSG_SQL, row)
                if cursor.rowcount > 0:
                    imported_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                logger.warning(f"Error importing message {msg.get('id')}: {e}")
                continue

        # Update channel metadata
        cursor.execute("""
            INSERT OR REPLACE INTO channels
            (channel_id, channel_name, category, message_count, last_updated)
            VALUES (?, ?, ?,
                    (SELECT COUNT(*) FROM messages WHERE channel_id = ?),
                    ?)
        """, (channel_id, ch_name, category, channel_id, datetime.now().isoformat()))

    logger.info(f"Imported {imported_count}, skipped {skipped_count} from {ch_name}")
    return imported_count, skipped_count


def _import_streaming(json_path: str, channel_name: str = None, batch_size: int = 5000):
    """
    Streaming import for large JSON files using ijson.

    Reads the file in two passes:
    1. Quick scan for channel metadata (stops before messages array)
    2. Streams messages one at a time, committing in batches
    """
    if not IJSON_AVAILABLE:
        raise ImportError("ijson required for streaming imports: pip install ijson")

    # --- Pass 1: channel metadata ---
    channel_id = ''
    ch_name = channel_name
    category = 'uncategorized'
    with open(json_path, 'rb') as f:
        parser = ijson.parse(f)
        for prefix, event, value in parser:
            if prefix == 'channel.id':
                channel_id = str(value)
            elif prefix == 'channel.name' and not ch_name:
                ch_name = value
            elif prefix == 'channel.category':
                category = value
            if prefix == 'messages':
                break
    ch_name = ch_name or 'unknown'

    imported_count = 0
    skipped_count = 0
    batch = []

    # --- Pass 2: stream messages ---
    conn = get_connection()
    cursor = conn.cursor()
    try:
        with open(json_path, 'rb') as f:
            for msg in ijson.items(f, 'messages.item'):
                try:
                    row = _process_export_message(msg, channel_id, ch_name)
                    batch.append(row)

                    if len(batch) >= batch_size:
                        cursor.executemany(_INSERT_MSG_SQL, batch)
                        imported_count += cursor.rowcount
                        skipped_count += len(batch) - cursor.rowcount
                        conn.commit()
                        batch = []
                        logger.info(f"  Progress: {imported_count + skipped_count} messages processed")
                except Exception as e:
                    logger.warning(f"Error importing message {msg.get('id')}: {e}")
                    continue

        # Flush remaining batch
        if batch:
            cursor.executemany(_INSERT_MSG_SQL, batch)
            imported_count += cursor.rowcount
            skipped_count += len(batch) - cursor.rowcount

        # Update channel metadata
        cursor.execute("""
            INSERT OR REPLACE INTO channels
            (channel_id, channel_name, category, message_count, last_updated)
            VALUES (?, ?, ?,
                    (SELECT COUNT(*) FROM messages WHERE channel_id = ?),
                    ?)
        """, (channel_id, ch_name, category, channel_id, datetime.now().isoformat()))

        conn.commit()
    finally:
        conn.close()

    logger.info(f"Imported {imported_count}, skipped {skipped_count} from {ch_name}")
    return imported_count, skipped_count


def import_all_exports(export_dir: str):
    """Import all JSON files from a directory."""
    export_path = Path(export_dir)
    json_files = sorted(export_path.glob("*.json"))

    total_imported = 0
    total_skipped = 0

    for json_file in json_files:
        logger.info(f"Importing {json_file.name}...")
        imported, skipped = import_discord_export(str(json_file))
        total_imported += imported
        total_skipped += skipped

    logger.info(f"Total: imported {total_imported}, skipped {total_skipped} across {len(json_files)} files")
    return total_imported, total_skipped


# ============================================================================
# LIVE MESSAGE STORAGE (real-time from on_message_create)
# ============================================================================

def insert_live_message(msg_data: dict) -> bool:
    """
    Insert a live message into the database.

    Intended to be called from a single writer bot (trannyverse/bot1.py).
    Other bots should read from this table, not write to it, to avoid
    duplicate storage.

    Args:
        msg_data: Dict with keys matching the live_messages schema:
            message_id, channel_id, author_id, author_name,
            author_nickname, author_avatar_url, content, timestamp,
            timestamp_edited, is_pinned, is_reply, reply_to_message_id,
            attachments, embeds, reactions, mentions, created_at

    Returns:
        True if inserted, False if duplicate or error.
    """
    try:
        with db_session() as (conn, cursor):
            cursor.execute("""
                INSERT OR IGNORE INTO live_messages
                (message_id, channel_id, author_id, author_name, author_nickname,
                 author_avatar_url, content, timestamp, timestamp_edited, is_pinned,
                 is_reply, reply_to_message_id, attachments_json, embeds_json,
                 reactions_json, mentions_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(msg_data.get('message_id', '')),
                str(msg_data.get('channel_id', '')),
                str(msg_data.get('author_id', '')),
                msg_data.get('author_name'),
                msg_data.get('author_nickname'),
                msg_data.get('author_avatar_url'),
                msg_data.get('content', ''),
                msg_data.get('timestamp'),
                msg_data.get('timestamp_edited'),
                1 if msg_data.get('is_pinned') else 0,
                1 if msg_data.get('is_reply') else 0,
                str(msg_data.get('reply_to_message_id', '')) if msg_data.get('reply_to_message_id') else None,
                json.dumps(msg_data.get('attachments', [])),
                json.dumps(msg_data.get('embeds', [])),
                json.dumps(msg_data.get('reactions', [])),
                json.dumps(msg_data.get('mentions', [])),
                msg_data.get('created_at', datetime.now().timestamp()),
            ))
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error inserting live message: {e}")
        return False


def get_live_message_by_id(message_id: str) -> Optional[dict]:
    """Get a live message by its Discord snowflake ID."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM live_messages WHERE message_id = ?", (str(message_id),))
        row = cursor.fetchone()
        if not row:
            return None

        result = dict(row)
        # Parse stored JSON fields back into lists
        for field in ('attachments_json', 'embeds_json', 'reactions_json', 'mentions_json'):
            if result.get(field):
                result[field.replace('_json', '')] = json.loads(result[field])
        return result
    finally:
        conn.close()


def get_recent_live_messages(channel_id: str = None, limit: int = 50) -> list:
    """
    Get the most recent live messages, optionally filtered by channel.

    Useful for the persona bot to build conversation context from the
    shared database instead of maintaining its own message buffer.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if channel_id:
            cursor.execute("""
                SELECT * FROM live_messages
                WHERE channel_id = ?
                ORDER BY created_at DESC LIMIT ?
            """, (str(channel_id), limit))
        else:
            cursor.execute("""
                SELECT * FROM live_messages
                ORDER BY created_at DESC LIMIT ?
            """, (limit,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# ============================================================================
# HIGHLIGHT TRACKING
# ============================================================================

def insert_highlight(highlight_id: str, original_message_id: str, author_id: str) -> bool:
    """
    Record that a message was highlighted (reposted to highlights channel).

    Returns True if inserted, False if already highlighted.
    """
    try:
        with db_session() as (conn, cursor):
            cursor.execute("""
                INSERT OR IGNORE INTO highlights
                (highlight_id, original_message_id, author_id, created_at)
                VALUES (?, ?, ?, ?)
            """, (str(highlight_id), str(original_message_id),
                  str(author_id), datetime.now().timestamp()))
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error inserting highlight: {e}")
        return False


def get_highlight_by_original(original_message_id: str) -> Optional[dict]:
    """Check if a message has already been highlighted."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM highlights WHERE original_message_id = ?",
            (str(original_message_id),)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ============================================================================
# REPLY TRACKING
# ============================================================================

def insert_reply_tracking(reply_id: str, original_message_id: str,
                          author_id: str, content: str) -> bool:
    """Track a reply to a message. Returns True if inserted."""
    try:
        with db_session() as (conn, cursor):
            cursor.execute("""
                INSERT OR IGNORE INTO message_reply_tracking
                (reply_id, original_message_id, author_id, reply_content, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (str(reply_id), str(original_message_id),
                  str(author_id), content, datetime.now().timestamp()))
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error inserting reply tracking: {e}")
        return False


def count_replies_to_message(original_message_id: str) -> int:
    """Count how many replies a message has received."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM message_reply_tracking WHERE original_message_id = ?",
            (str(original_message_id),)
        )
        return cursor.fetchone()[0]
    finally:
        conn.close()


def get_replies_to_message(original_message_id: str) -> list:
    """Get all tracked replies to a specific message."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM message_reply_tracking WHERE original_message_id = ? ORDER BY created_at",
            (str(original_message_id),)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# ============================================================================
# QUERY FUNCTIONS (analytics, stats, search)
# ============================================================================

def search_messages(query: str, limit: int = 100, author_id: str = None) -> list:
    """
    Full-text keyword search across historical messages.

    Used as a fallback by the RAG hybrid retriever when ChromaDB
    semantic search returns too few results.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if author_id:
            cursor.execute("""
                SELECT message_id, author_name, channel_name, content, timestamp
                FROM messages
                WHERE content LIKE ? AND author_id = ? AND author_bot = 0
                ORDER BY timestamp_unix DESC LIMIT ?
            """, (f'%{query}%', author_id, limit))
        else:
            cursor.execute("""
                SELECT message_id, author_name, channel_name, content, timestamp
                FROM messages
                WHERE content LIKE ? AND author_bot = 0
                ORDER BY timestamp_unix DESC LIMIT ?
            """, (f'%{query}%', limit))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_user_messages(user_id: str, limit: int = None) -> list:
    """
    Get all messages from a specific user, ordered chronologically.

    Used by prepare_chatbot.py to build the persona corpus and by
    the RAG embedder to tag is_persona metadata.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        query = """
            SELECT content, timestamp, channel_name
            FROM messages
            WHERE author_id = ? AND author_bot = 0 AND content != ''
            ORDER BY timestamp_unix ASC
        """
        if limit:
            query += f" LIMIT {limit}"
        cursor.execute(query, (user_id,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_user_stats(limit: int = 20) -> list:
    """Get most active users by message count."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                author_id,
                author_name,
                COUNT(*) as message_count,
                SUM(word_count) as total_words,
                ROUND(AVG(word_count), 1) as avg_words_per_msg,
                COUNT(DISTINCT channel_id) as channels_active,
                MIN(timestamp) as first_message,
                MAX(timestamp) as last_message
            FROM messages
            WHERE author_bot = 0
            GROUP BY author_id
            ORDER BY message_count DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_hourly_activity() -> dict:
    """Get message distribution by hour of day (UTC)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                COUNT(*) as message_count
            FROM messages
            WHERE author_bot = 0 AND timestamp IS NOT NULL
            GROUP BY hour
            ORDER BY hour
        """)
        results = {row['hour']: row['message_count'] for row in cursor.fetchall()}
        return {h: results.get(h, 0) for h in range(24)}
    finally:
        conn.close()


def get_daily_activity(days: int = 30) -> list:
    """Get message count per day for the last N days."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cutoff = (datetime.now() - timedelta(days=days)).timestamp()
        cursor.execute("""
            SELECT
                DATE(timestamp) as date,
                COUNT(*) as message_count,
                COUNT(DISTINCT author_id) as unique_users
            FROM messages
            WHERE author_bot = 0 AND timestamp_unix > ?
            GROUP BY date
            ORDER BY date DESC
        """, (cutoff,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_server_overview() -> dict:
    """Get overall server statistics."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) as total_messages,
                COUNT(DISTINCT author_id) as unique_users,
                COUNT(DISTINCT channel_id) as active_channels,
                SUM(word_count) as total_words,
                SUM(has_attachments) as total_attachments,
                SUM(is_reply) as total_replies,
                MIN(timestamp) as earliest_message,
                MAX(timestamp) as latest_message
            FROM messages
            WHERE author_bot = 0
        """)
        result = dict(cursor.fetchone())

        # Most active channel
        cursor.execute("""
            SELECT channel_name, COUNT(*) as count
            FROM messages WHERE author_bot = 0
            GROUP BY channel_id ORDER BY count DESC LIMIT 1
        """)
        top_channel = cursor.fetchone()
        result['top_channel'] = dict(top_channel) if top_channel else None

        # Most active user
        cursor.execute("""
            SELECT author_name, COUNT(*) as count
            FROM messages WHERE author_bot = 0
            GROUP BY author_id ORDER BY count DESC LIMIT 1
        """)
        top_user = cursor.fetchone()
        result['top_user'] = dict(top_user) if top_user else None

        return result
    finally:
        conn.close()


def get_user_vocabulary(user_id: str, top_n: int = 50) -> list:
    """Get most common words used by a specific user (minus stopwords)."""
    messages = get_user_messages(user_id)

    stopwords = {
        'the', 'a', 'an', 'is', 'it', 'to', 'of', 'and', 'i', 'you',
        'that', 'in', 'for', 'on', 'with', 'this', 'be', 'are', 'was',
        'have', 'has', 'my', 'me', 'your', 'but', 'not', 'so', 'just',
        'like', 'im', "i'm", 'its', "it's", 'do', 'if', 'or', 'at',
        'as', 'can', 'all', 'what', 'they', 'we', 'he', 'she', 'from',
        'her', 'his', 'been', 'would', 'there', 'their', 'will', 'when',
        'who', 'them',
    }

    all_words = []
    for msg in messages:
        words = msg['content'].lower().split()
        words = [
            w.strip('.,!?()[]{}":;')
            for w in words
            if len(w) > 2 and w.lower() not in stopwords and not w.startswith('<')
        ]
        all_words.extend(words)

    return Counter(all_words).most_common(top_n)


def get_channel_activity_comparison(channel_ids: list = None) -> list:
    """Compare activity across specified channels or all channels."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if channel_ids:
            placeholders = ','.join('?' * len(channel_ids))
            cursor.execute(f"""
                SELECT
                    channel_id, channel_name,
                    COUNT(*) as total_messages,
                    COUNT(DISTINCT author_id) as unique_users,
                    ROUND(AVG(word_count), 1) as avg_msg_length,
                    SUM(is_reply) * 100.0 / COUNT(*) as reply_percentage
                FROM messages
                WHERE author_bot = 0 AND channel_id IN ({placeholders})
                GROUP BY channel_id
                ORDER BY total_messages DESC
            """, channel_ids)
        else:
            cursor.execute("""
                SELECT
                    channel_id, channel_name,
                    COUNT(*) as total_messages,
                    COUNT(DISTINCT author_id) as unique_users,
                    ROUND(AVG(word_count), 1) as avg_msg_length,
                    SUM(is_reply) * 100.0 / COUNT(*) as reply_percentage
                FROM messages
                WHERE author_bot = 0
                GROUP BY channel_id
                ORDER BY total_messages DESC
            """)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def export_user_corpus(user_id: str, output_path: str) -> int:
    """
    Export all messages from a user to a plain text file.

    Useful for preparing chatbot training data or persona analysis.
    """
    messages = get_user_messages(user_id)

    with open(output_path, 'w', encoding='utf-8') as f:
        for msg in messages:
            if msg['content'].strip():
                f.write(msg['content'] + '\n')

    logger.info(f"Exported {len(messages)} messages to {output_path}")
    return len(messages)


# ============================================================================
# STANDALONE INIT
# ============================================================================

if __name__ == "__main__":
    init_database()
    print(f"Database initialized at {ANALYTICS_DB_PATH}")
    print("Run import_all_exports('path/to/exports') to import your Discord data")
