"""
Bad Word Scanner Module
Searches the analytics database for messages containing specified bad words
and exports message IDs for targeted deletion.

Enhanced to integrate with the moderation database for pattern learning.
"""

import sqlite3
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List

# Import from your existing analytics module
DB_PATH = "discord_analytics.db"

# Try to import moderation database for integration
try:
    import common.moderation_db as mdb
    MDB_AVAILABLE = True
except ImportError:
    MDB_AVAILABLE = False

# ============== CONFIGURATION ==============
# Add your bad words here (case-insensitive matching)
# These will also be synced to the moderation database
BAD_WORDS = [
    # Add words/phrases to search for
    # "example_word",
    # "another_phrase",
]

# Output file for flagged message IDs
OUTPUT_FILE = "flagged_messages.json"


def sync_bad_words_to_moderation_db(words: List[str], severity: int = 3):
    """Sync bad words list to the moderation database."""
    if not MDB_AVAILABLE:
        print("⚠️  Moderation database not available, skipping sync")
        return
    
    mdb.init_moderation_db()
    added = mdb.add_bad_words_bulk(words, severity=severity)
    print(f"Synced {added} new words to moderation database")


def get_connection():
    """Get a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def search_bad_words(
    bad_words: list = None,
    output_file: str = None,
    include_bots: bool = False,
    channel_filter: list = None,
    author_filter: list = None,
    date_after: str = None,
    date_before: str = None,
) -> dict:
    """
    Search for messages containing any of the specified bad words.
    
    Args:
        bad_words: List of words/phrases to search for (uses BAD_WORDS if None)
        output_file: Path to output JSON file (uses OUTPUT_FILE if None)
        include_bots: Whether to include bot messages
        channel_filter: List of channel IDs to limit search to
        author_filter: List of author IDs to limit search to
        date_after: Only include messages after this date (YYYY-MM-DD)
        date_before: Only include messages before this date (YYYY-MM-DD)
    
    Returns:
        Dictionary with statistics and flagged message details
    """
    words = bad_words or BAD_WORDS
    output = output_file or OUTPUT_FILE
    
    if not words:
        print("⚠️  No bad words configured. Add words to BAD_WORDS list or pass them as argument.")
        return {"error": "No bad words configured"}
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Build the base query
    conditions = []
    params = []
    
    # Bot filter
    if not include_bots:
        conditions.append("author_bot = 0")
    
    # Channel filter
    if channel_filter:
        placeholders = ','.join('?' * len(channel_filter))
        conditions.append(f"channel_id IN ({placeholders})")
        params.extend(channel_filter)
    
    # Author filter
    if author_filter:
        placeholders = ','.join('?' * len(author_filter))
        conditions.append(f"author_id IN ({placeholders})")
        params.extend(author_filter)
    
    # Date filters
    if date_after:
        conditions.append("DATE(timestamp) >= ?")
        params.append(date_after)
    
    if date_before:
        conditions.append("DATE(timestamp) <= ?")
        params.append(date_before)
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    query = f"""
        SELECT 
            message_id,
            channel_id,
            channel_name,
            author_id,
            author_name,
            content,
            timestamp
        FROM messages
        WHERE {where_clause} AND content != ''
    """
    
    cursor.execute(query, params)
    
    # Process results
    results = {
        "scan_time": datetime.now().isoformat(),
        "bad_words_searched": words,
        "total_messages_scanned": 0,
        "total_flagged": 0,
        "flagged_by_word": {},
        "flagged_messages": []
    }
    
    # Initialize word counters
    for word in words:
        results["flagged_by_word"][word] = 0
    
    # Create case-insensitive patterns for each word
    patterns = {word: re.compile(re.escape(word), re.IGNORECASE) for word in words}
    
    seen_message_ids = set()  # Avoid duplicates
    
    for row in cursor:
        results["total_messages_scanned"] += 1
        content = row["content"]
        message_id = row["message_id"]
        
        # Check each bad word
        matched_words = []
        for word, pattern in patterns.items():
            if pattern.search(content):
                matched_words.append(word)
                results["flagged_by_word"][word] += 1
        
        # If any matches and not already seen
        if matched_words and message_id not in seen_message_ids:
            seen_message_ids.add(message_id)
            results["total_flagged"] += 1
            
            results["flagged_messages"].append({
                "message_id": message_id,
                "channel_id": row["channel_id"],
                "channel_name": row["channel_name"],
                "author_id": row["author_id"],
                "author_name": row["author_name"],
                "content": content[:500],  # Truncate long messages
                "timestamp": row["timestamp"],
                "matched_words": matched_words
            })
    
    conn.close()
    
    # Save results to file
    with open(output, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*50}")
    print(f"BAD WORD SCAN RESULTS")
    print(f"{'='*50}")
    print(f"Total messages scanned: {results['total_messages_scanned']:,}")
    print(f"Total flagged: {results['total_flagged']:,}")
    print(f"\nBreakdown by word:")
    for word, count in results["flagged_by_word"].items():
        print(f"  • '{word}': {count:,} matches")
    print(f"\nResults saved to: {output}")
    
    return results


def get_message_ids_only(input_file: str = None) -> list:
    """
    Extract just the message IDs from a scan results file.
    Useful for passing to deletion commands.
    
    Args:
        input_file: Path to the scan results JSON file
    
    Returns:
        List of message ID strings
    """
    input_path = input_file or OUTPUT_FILE
    
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    return [msg["message_id"] for msg in data.get("flagged_messages", [])]


def export_message_ids_txt(input_file: str = None, output_file: str = "message_ids.txt"):
    """
    Export just the message IDs to a simple text file (one per line).
    
    Args:
        input_file: Path to the scan results JSON file
        output_file: Path to output text file
    """
    message_ids = get_message_ids_only(input_file)
    
    with open(output_file, 'w') as f:
        for msg_id in message_ids:
            f.write(msg_id + '\n')
    
    print(f"Exported {len(message_ids)} message IDs to {output_file}")
    return message_ids


def group_by_channel(input_file: str = None) -> dict:
    """
    Group flagged messages by channel for easier batch deletion.
    
    Returns:
        Dictionary mapping channel_id -> list of message_ids
    """
    input_path = input_file or OUTPUT_FILE
    
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    by_channel = {}
    for msg in data.get("flagged_messages", []):
        channel_id = msg["channel_id"]
        if channel_id not in by_channel:
            by_channel[channel_id] = {
                "channel_name": msg["channel_name"],
                "message_ids": []
            }
        by_channel[channel_id]["message_ids"].append(msg["message_id"])
    
    # Print summary
    print("\nMessages grouped by channel:")
    for channel_id, info in by_channel.items():
        print(f"  #{info['channel_name']}: {len(info['message_ids'])} messages")
    
    return by_channel


def preview_flagged(input_file: str = None, limit: int = 10):
    """
    Preview flagged messages before deletion.
    
    Args:
        input_file: Path to the scan results JSON file
        limit: Number of messages to preview
    """
    input_path = input_file or OUTPUT_FILE
    
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    messages = data.get("flagged_messages", [])
    
    print(f"\n{'='*60}")
    print(f"PREVIEW: First {min(limit, len(messages))} flagged messages")
    print(f"{'='*60}\n")
    
    for i, msg in enumerate(messages[:limit], 1):
        print(f"[{i}] #{msg['channel_name']} | {msg['author_name']} | {msg['timestamp'][:10]}")
        print(f"    Words: {', '.join(msg['matched_words'])}")
        print(f"    Content: {msg['content'][:100]}...")
        print(f"    ID: {msg['message_id']}")
        print()


# ============== TRAINING DATA EXPORT ==============

def export_as_training_samples(input_file: str = None, label: str = "bad"):
    """
    Export flagged messages to the moderation database as training samples.
    This helps the content analyzer learn patterns from historical bad messages.
    
    Args:
        input_file: Path to flagged messages JSON
        label: Label for training ('bad' or 'good')
    """
    if not MDB_AVAILABLE:
        print("❌ Moderation database not available")
        return 0
    
    input_path = input_file or OUTPUT_FILE
    
    if not Path(input_path).exists():
        print(f"❌ File not found: {input_path}")
        return 0
    
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    messages = data.get('flagged_messages', [])
    imported = 0
    
    for msg in messages:
        content = msg.get('content', '')
        if content and len(content) > 10:  # Skip very short messages
            mdb.add_training_sample(content, label, 'scanner_export')
            imported += 1
    
    print(f"✅ Exported {imported} messages as '{label}' training samples")
    return imported


def full_workflow(
    bad_words: List[str],
    export_dir: str = None,
    sync_to_moderation: bool = True,
    export_training: bool = True,
    preview_count: int = 5
):
    """
    Run the complete bad word scanning workflow:
    1. Import Discord exports (if directory provided)
    2. Sync bad words to moderation database
    3. Scan for bad words
    4. Export as training samples
    5. Preview results
    
    Args:
        bad_words: List of words to search for
        export_dir: Directory containing Discord export JSON files
        sync_to_moderation: Whether to sync words to moderation DB
        export_training: Whether to export results as training samples
        preview_count: Number of messages to preview
    """
    print("="*60)
    print("BAD WORD SCANNER - FULL WORKFLOW")
    print("="*60)
    
    # Step 1: Import exports if directory provided
    if export_dir and Path(export_dir).exists():
        print(f"\n[1/5] Importing Discord exports from {export_dir}...")
        try:
            from common import db
            db.init_database()
            db.import_all_exports(export_dir)
        except Exception as e:
            print(f"⚠️  Import error: {e}")
    else:
        print("\n[1/5] Skipping import (no export directory provided)")
    
    # Step 2: Sync to moderation database
    if sync_to_moderation and bad_words:
        print("\n[2/5] Syncing bad words to moderation database...")
        sync_bad_words_to_moderation_db(bad_words)
    else:
        print("\n[2/5] Skipping moderation DB sync")
    
    # Step 3: Scan for bad words
    print("\n[3/5] Scanning for bad words...")
    results = search_bad_words(bad_words=bad_words)
    
    # Step 4: Export as training samples
    if export_training and results.get('total_flagged', 0) > 0:
        print("\n[4/5] Exporting as training samples...")
        export_as_training_samples()
    else:
        print("\n[4/5] Skipping training export")
    
    # Step 5: Preview
    if preview_count > 0 and results.get('total_flagged', 0) > 0:
        print(f"\n[5/5] Preview ({preview_count} messages)...")
        preview_flagged(limit=preview_count)
    
    # Summary
    print("\n" + "="*60)
    print("WORKFLOW COMPLETE")
    print("="*60)
    
    if results.get('total_flagged', 0) > 0:
        print(f"""
Results:
  • {results['total_flagged']} messages flagged
  • Saved to: {OUTPUT_FILE}
  
Next steps:
  • Review flagged_messages.json
  • Use /purge_flagged in Discord to delete
  • Or run: python -c "from bad_word_scanner import group_by_channel; group_by_channel()"
""")
    else:
        print("\n✅ No messages found containing those words!")
    
    return results


# ============== MAIN EXECUTION ==============
if __name__ == "__main__":
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Bad Word Scanner")
    parser.add_argument("--words", help="Comma-separated list of bad words")
    parser.add_argument("--words-file", help="File with bad words (one per line)")
    parser.add_argument("--import-dir", help="Directory with Discord exports to import")
    parser.add_argument("--preview", type=int, default=5, help="Number of results to preview")
    parser.add_argument("--no-sync", action="store_true", help="Skip syncing to moderation DB")
    parser.add_argument("--no-training", action="store_true", help="Skip exporting as training samples")
    
    args = parser.parse_args()
    
    print("Bad Word Scanner")
    print("================")
    
    # Check if database exists
    if not Path(DB_PATH).exists() and not args.import_dir:
        print(f"❌ Database not found at {DB_PATH}")
        print("Run your import first or provide --import-dir")
        sys.exit(1)
    
    # Load bad words
    bad_words = []
    
    if args.words:
        bad_words = [w.strip() for w in args.words.split(',') if w.strip()]
    
    if args.words_file and Path(args.words_file).exists():
        with open(args.words_file, 'r') as f:
            bad_words.extend([line.strip() for line in f if line.strip() and not line.startswith('#')])
    
    if not bad_words:
        bad_words = BAD_WORDS
    
    if not bad_words:
        print("\n⚠️  No bad words configured!")
        print("Use --words or --words-file, or edit BAD_WORDS in this file")
        sys.exit(0)
    
    # Run full workflow
    full_workflow(
        bad_words=bad_words,
        export_dir=args.import_dir,
        sync_to_moderation=not args.no_sync,
        export_training=not args.no_training,
        preview_count=args.preview
    )
