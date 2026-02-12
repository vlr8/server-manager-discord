"""
Moderation Database Module (protector bot + shared reads).

Tracks flagged messages, bad word lists, user offenses, learned
patterns, and scan progress for the live content moderation system.

Lives in its own database file (moderation.db) separate from
analytics. The protector bot is the primary writer; other bots
may read from it (e.g. to check if a user is a repeat offender
before responding).

Uses WAL mode for safe concurrent access from multiple processes.

Usage:
    from common.moderation_db import log_flagged_message, get_bad_words
"""

import sqlite3
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

from .config import MODERATION_DB_PATH, SQLITE_PRAGMAS, ANALYTICS_DB_PATH

logger = logging.getLogger(__name__)


# ============================================================================
# CONNECTION MANAGEMENT
# ============================================================================

def get_connection() -> sqlite3.Connection:
    """Get a WAL-enabled connection to the moderation database."""
    conn = sqlite3.connect(str(MODERATION_DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    for pragma, value in SQLITE_PRAGMAS.items():
        conn.execute(f"PRAGMA {pragma} = {value}")
    return conn


@contextmanager
def mod_session():
    """Context manager for moderation DB operations with auto commit/rollback."""
    conn = get_connection()
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

def init_moderation_db():
    """
    Initialize the moderation database schema.

    Safe to call multiple times. Run on protector bot startup.
    """
    with mod_session() as (conn, cursor):

        # ----- Flagged messages (auto-moderated) -----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS flagged_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE,
                channel_id TEXT,
                channel_name TEXT,
                author_id TEXT,
                author_name TEXT,
                original_content TEXT,
                censored_content TEXT,
                flag_reason TEXT,
                matched_patterns TEXT,
                sentiment_score REAL,
                toxicity_score REAL,
                action_taken TEXT,
                flagged_at TEXT,
                auto_deleted INTEGER DEFAULT 0
            )
        """)

        # ----- Bad word list -----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bad_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT UNIQUE,
                severity INTEGER DEFAULT 1,
                category TEXT,
                added_at TEXT,
                match_count INTEGER DEFAULT 0
            )
        """)

        # ----- Learned patterns (from historical scan) -----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS learned_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern TEXT UNIQUE,
                pattern_type TEXT,
                confidence REAL DEFAULT 0.5,
                match_count INTEGER DEFAULT 0,
                false_positive_count INTEGER DEFAULT 0,
                created_at TEXT,
                last_matched TEXT
            )
        """)

        # ----- User offense history -----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_offenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                offense_type TEXT,
                message_id TEXT,
                channel_id TEXT,
                occurred_at TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_offenses_user ON user_offenses(user_id)")

        # ----- Monitored channels config -----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS monitored_channels (
                channel_id TEXT PRIMARY KEY,
                channel_name TEXT,
                monitoring_level INTEGER DEFAULT 1,
                added_at TEXT
            )
        """)

        # ----- Training samples for pattern learning -----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS training_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT,
                label TEXT,
                source TEXT,
                added_at TEXT
            )
        """)

        # ----- Scan progress (for resuming interrupted historical scans) -----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scan_progress (
                channel_id TEXT PRIMARY KEY,
                file_path TEXT,
                last_message_id TEXT,
                messages_scanned INTEGER DEFAULT 0,
                messages_flagged INTEGER DEFAULT 0,
                last_updated TEXT
            )
        """)

    logger.info(f"Moderation database initialized at {MODERATION_DB_PATH}")


# ============================================================================
# BAD WORDS MANAGEMENT
# ============================================================================

def add_bad_word(word: str, severity: int = 1, category: str = "general") -> bool:
    """Add a bad word to the filter list. Returns True if newly added."""
    with mod_session() as (conn, cursor):
        cursor.execute("""
            INSERT OR IGNORE INTO bad_words (word, severity, category, added_at)
            VALUES (?, ?, ?, ?)
        """, (word.lower().strip(), severity, category, datetime.now().isoformat()))
        return cursor.rowcount > 0


def add_bad_words_bulk(words: List[str], severity: int = 1, category: str = "general") -> int:
    """Add multiple bad words at once. Returns count of newly added."""
    added = 0
    with mod_session() as (conn, cursor):
        for word in words:
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO bad_words (word, severity, category, added_at)
                    VALUES (?, ?, ?, ?)
                """, (word.lower().strip(), severity, category, datetime.now().isoformat()))
                if cursor.rowcount > 0:
                    added += 1
            except Exception:
                continue
    logger.info(f"Added {added} new bad words")
    return added


def get_bad_words(min_severity: int = 0) -> List[Dict]:
    """Get all bad words, optionally filtered by minimum severity."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT word, severity, category, match_count
            FROM bad_words
            WHERE severity >= ?
            ORDER BY severity DESC, match_count DESC
        """, (min_severity,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def increment_word_match(word: str):
    """Increment the match count for a bad word after it triggers."""
    with mod_session() as (conn, cursor):
        cursor.execute(
            "UPDATE bad_words SET match_count = match_count + 1 WHERE word = ?",
            (word.lower(),)
        )


# ============================================================================
# FLAGGED MESSAGES
# ============================================================================

def log_flagged_message(
    message_id: str,
    channel_id: str,
    channel_name: str,
    author_id: str,
    author_name: str,
    original_content: str,
    censored_content: str,
    flag_reason: str,
    matched_patterns: List[str],
    sentiment_score: float = 0.0,
    toxicity_score: float = 0.0,
    action_taken: str = "deleted",
    auto_deleted: bool = True,
):
    """Log a flagged/deleted message for audit trail."""
    with mod_session() as (conn, cursor):
        cursor.execute("""
            INSERT OR REPLACE INTO flagged_messages
            (message_id, channel_id, channel_name, author_id, author_name,
             original_content, censored_content, flag_reason, matched_patterns,
             sentiment_score, toxicity_score, action_taken, flagged_at, auto_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            message_id, channel_id, channel_name, author_id, author_name,
            original_content, censored_content, flag_reason,
            json.dumps(matched_patterns), sentiment_score, toxicity_score,
            action_taken, datetime.now().isoformat(), 1 if auto_deleted else 0
        ))


def get_flagged_messages(limit: int = 100, author_id: str = None) -> List[Dict]:
    """Get recent flagged messages, optionally filtered by user."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if author_id:
            cursor.execute("""
                SELECT * FROM flagged_messages
                WHERE author_id = ?
                ORDER BY flagged_at DESC LIMIT ?
            """, (author_id, limit))
        else:
            cursor.execute("""
                SELECT * FROM flagged_messages
                ORDER BY flagged_at DESC LIMIT ?
            """, (limit,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# ============================================================================
# USER OFFENSES
# ============================================================================

def log_user_offense(user_id: str, offense_type: str, message_id: str, channel_id: str):
    """Log a user offense for repeat-offender tracking."""
    with mod_session() as (conn, cursor):
        cursor.execute("""
            INSERT INTO user_offenses (user_id, offense_type, message_id, channel_id, occurred_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, offense_type, message_id, channel_id, datetime.now().isoformat()))


def get_user_offense_count(user_id: str, days: int = 30) -> int:
    """Get number of offenses for a user in the last N days."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor.execute("""
            SELECT COUNT(*) FROM user_offenses
            WHERE user_id = ? AND occurred_at > ?
        """, (user_id, cutoff))
        return cursor.fetchone()[0]
    finally:
        conn.close()


def get_repeat_offenders(min_offenses: int = 3, days: int = 7) -> List[Dict]:
    """Get users with multiple offenses in the given timeframe."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor.execute("""
            SELECT user_id, COUNT(*) as offense_count
            FROM user_offenses
            WHERE occurred_at > ?
            GROUP BY user_id
            HAVING offense_count >= ?
            ORDER BY offense_count DESC
        """, (cutoff, min_offenses))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# ============================================================================
# MONITORED CHANNELS
# ============================================================================

def add_monitored_channel(channel_id: str, channel_name: str, level: int = 1):
    """Add or update a channel's monitoring level."""
    with mod_session() as (conn, cursor):
        cursor.execute("""
            INSERT OR REPLACE INTO monitored_channels
            (channel_id, channel_name, monitoring_level, added_at)
            VALUES (?, ?, ?, ?)
        """, (channel_id, channel_name, level, datetime.now().isoformat()))


def remove_monitored_channel(channel_id: str):
    """Remove a channel from active monitoring."""
    with mod_session() as (conn, cursor):
        cursor.execute("DELETE FROM monitored_channels WHERE channel_id = ?", (channel_id,))


def get_monitored_channels() -> Dict[str, int]:
    """Get all monitored channels as {channel_id: monitoring_level}."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT channel_id, monitoring_level FROM monitored_channels")
        return {row['channel_id']: row['monitoring_level'] for row in cursor.fetchall()}
    finally:
        conn.close()


# ============================================================================
# TRAINING SAMPLES
# ============================================================================

def add_training_sample(content: str, label: str, source: str = "manual"):
    """Add a training sample for pattern learning."""
    with mod_session() as (conn, cursor):
        cursor.execute("""
            INSERT INTO training_samples (content, label, source, added_at)
            VALUES (?, ?, ?, ?)
        """, (content, label, source, datetime.now().isoformat()))


def import_training_samples_from_analytics(bad_words: List[str]) -> int:
    """
    Import messages containing bad words from the shared analytics DB
    as training samples for pattern learning.

    Uses ANALYTICS_DB_PATH from config so it works regardless of
    which directory the script is run from.
    """
    analytics_path = ANALYTICS_DB_PATH
    if not analytics_path.exists():
        logger.error(f"Analytics database not found: {analytics_path}")
        return 0

    # Read from the analytics DB (separate connection)
    analytics_conn = sqlite3.connect(str(analytics_path), timeout=10)
    analytics_conn.row_factory = sqlite3.Row

    imported = 0
    try:
        analytics_cursor = analytics_conn.cursor()
        for word in bad_words:
            analytics_cursor.execute("""
                SELECT content FROM messages
                WHERE content LIKE ? AND author_bot = 0 AND content != ''
                LIMIT 1000
            """, (f'%{word}%',))

            for row in analytics_cursor:
                add_training_sample(row['content'], 'bad', 'analytics_import')
                imported += 1
    finally:
        analytics_conn.close()

    logger.info(f"Imported {imported} training samples from analytics database")
    return imported


# ============================================================================
# LEARNED PATTERNS
# ============================================================================

def add_learned_pattern(pattern: str, pattern_type: str, confidence: float = 0.5) -> bool:
    """Add a learned pattern. Returns True if newly added."""
    with mod_session() as (conn, cursor):
        cursor.execute("""
            INSERT OR IGNORE INTO learned_patterns
            (pattern, pattern_type, confidence, created_at)
            VALUES (?, ?, ?, ?)
        """, (pattern, pattern_type, confidence, datetime.now().isoformat()))
        return cursor.rowcount > 0


def get_learned_patterns(min_confidence: float = 0.3) -> List[Dict]:
    """Get learned patterns above the confidence threshold."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT pattern, pattern_type, confidence, match_count
            FROM learned_patterns
            WHERE confidence >= ?
            ORDER BY confidence DESC
        """, (min_confidence,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def update_pattern_stats(pattern: str, matched: bool, false_positive: bool = False):
    """
    Update pattern statistics after a match event.

    False positives reduce confidence by 0.05 (floor at 0.1).
    """
    with mod_session() as (conn, cursor):
        if matched:
            cursor.execute("""
                UPDATE learned_patterns
                SET match_count = match_count + 1, last_matched = ?
                WHERE pattern = ?
            """, (datetime.now().isoformat(), pattern))
        if false_positive:
            cursor.execute("""
                UPDATE learned_patterns
                SET false_positive_count = false_positive_count + 1,
                    confidence = MAX(0.1, confidence - 0.05)
                WHERE pattern = ?
            """, (pattern,))


# ============================================================================
# MODERATION STATISTICS
# ============================================================================

def get_moderation_stats(days: int = 7) -> Dict:
    """Get moderation statistics for the last N days."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        stats = {}

        cursor.execute(
            "SELECT COUNT(*) as count FROM flagged_messages WHERE flagged_at > ?",
            (cutoff,)
        )
        stats['total_flagged'] = cursor.fetchone()['count']

        cursor.execute("""
            SELECT flag_reason, COUNT(*) as count
            FROM flagged_messages WHERE flagged_at > ?
            GROUP BY flag_reason ORDER BY count DESC
        """, (cutoff,))
        stats['by_reason'] = {row['flag_reason']: row['count'] for row in cursor.fetchall()}

        cursor.execute(
            "SELECT COUNT(DISTINCT author_id) as count FROM flagged_messages WHERE flagged_at > ?",
            (cutoff,)
        )
        stats['unique_offenders'] = cursor.fetchone()['count']

        cursor.execute(
            "SELECT word, match_count FROM bad_words ORDER BY match_count DESC LIMIT 10"
        )
        stats['top_triggered_words'] = [dict(row) for row in cursor.fetchall()]

        return stats
    finally:
        conn.close()


# ============================================================================
# SCAN PROGRESS TRACKING
# ============================================================================

def update_scan_progress(channel_id: str, file_path: str,
                         message_id: str, scanned: int, flagged: int):
    """Update scan progress for resume capability during historical scans."""
    with mod_session() as (conn, cursor):
        cursor.execute("""
            INSERT OR REPLACE INTO scan_progress
            (channel_id, file_path, last_message_id, messages_scanned,
             messages_flagged, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (channel_id, file_path, message_id, scanned, flagged,
              datetime.now().isoformat()))


def get_scan_progress(channel_id: str) -> Optional[Dict]:
    """Get scan progress for a channel (for resume)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM scan_progress WHERE channel_id = ?", (channel_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def clear_scan_progress():
    """Clear all scan progress (start fresh)."""
    with mod_session() as (conn, cursor):
        cursor.execute("DELETE FROM scan_progress")


def get_all_scan_progress() -> List[Dict]:
    """Get scan progress for all channels."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM scan_progress ORDER BY last_updated DESC")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# ============================================================================
# STANDALONE INIT
# ============================================================================

if __name__ == "__main__":
    init_moderation_db()
