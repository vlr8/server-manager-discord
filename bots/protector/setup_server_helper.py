#!/usr/bin/env python3
"""
Server Helper Bot Setup
=======================

Run this before starting server_helper.py for the first time.
This will:
1. Check dependencies
2. Initialize the moderation database
3. Load sample deleted messages for pattern learning
4. Run a test scan on exports (optional)
"""

import sys
from pathlib import Path


def main():
    print("=" * 60)
    print("SERVER HELPER BOT SETUP")
    print("=" * 60)
    
    # Step 1: Check dependencies
    print("\n[1/5] Checking dependencies...")
    
    missing = []
    
    try:
        import interactions
        print("  ✅ interactions.py installed")
    except ImportError:
        missing.append("discord-py-interactions")
        print("  ❌ interactions.py NOT installed")
    
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        print("  ✅ vaderSentiment installed")
    except ImportError:
        missing.append("vaderSentiment")
        print("  ⚠️  vaderSentiment not installed (sentiment analysis disabled)")
    
    if missing:
        print(f"\nInstall missing packages:")
        print(f"  pip install {' '.join(missing)}")
        if "discord-py-interactions" in missing:
            print("\n❌ interactions.py is required. Please install and re-run.")
            sys.exit(1)
    
    # Step 2: Check for required files
    print("\n[2/5] Checking project files...")
    
    required_files = [
        ("server_helper.py", True),
        ("moderation_db.py", False),
        ("sample_deleted_messages.txt", False),
    ]
    
    for filename, required in required_files:
        if Path(filename).exists():
            print(f"  ✅ {filename} found")
        elif required:
            print(f"  ❌ {filename} NOT FOUND (required)")
            sys.exit(1)
        else:
            print(f"  ⚠️  {filename} not found (optional)")
    
    # Step 3: Initialize database
    print("\n[3/5] Initializing moderation database...")
    
    try:
        import common.moderation_db as mdb
        mdb.init_moderation_db()
        print("  ✅ Moderation database ready")
        
        # Add default bad words
        from server_helper import BAD_WORDS_CRITICAL, BAD_WORDS_MODERATE
        
        added_critical = mdb.add_bad_words_bulk(BAD_WORDS_CRITICAL, severity=5, category='critical')
        added_moderate = mdb.add_bad_words_bulk(BAD_WORDS_MODERATE, severity=3, category='moderate')
        
        print(f"  ✅ Loaded {added_critical} critical words, {added_moderate} moderate words")
        
    except ImportError:
        print("  ⚠️  moderation_db.py not found - using in-memory tracking")
    except Exception as e:
        print(f"  ⚠️  Database init warning: {e}")
    
    # Step 4: Load sample deleted messages
    print("\n[4/5] Loading sample deleted messages...")
    
    sample_path = Path("sample_deleted_messages.txt")
    if sample_path.exists():
        try:
            with open(sample_path, 'r', encoding='utf-8') as f:
                lines = [l.strip() for l in f if l.strip() and not l.startswith('#')]
            print(f"  ✅ Loaded {len(lines)} sample messages")
            
            # Show a few examples
            print("  Examples:")
            for line in lines[:3]:
                print(f"    • {line[:60]}...")
                
        except Exception as e:
            print(f"  ⚠️  Error loading samples: {e}")
    else:
        print("  ⚠️  sample_deleted_messages.txt not found")
        print("  Creating template file...")
        
        template = """# Sample Deleted Messages
# Add one message per line that should be flagged
# These help the bot learn patterns from your server's history
# Lines starting with # are comments

# Example entries (remove these and add your own):
# some example bad message here
# another problematic message
"""
        with open(sample_path, 'w') as f:
            f.write(template)
        print("  ✅ Created template file - edit it with real examples")
    
    # Step 5: Check for Discord exports
    print("\n[5/5] Checking for Discord exports...")
    
    export_dirs = ["./server_export", "./discord_exports", "./exports"]
    found_exports = None
    
    for dir_path in export_dirs:
        if Path(dir_path).exists():
            json_files = list(Path(dir_path).rglob("*.json"))
            if json_files:
                found_exports = dir_path
                print(f"  ✅ Found {len(json_files)} export files in {dir_path}")
                break
    
    if not found_exports:
        print("  ⚠️  No Discord exports found")
        print("  To export your server history:")
        print("    1. Install DiscordChatExporter")
        print("    2. Run: DiscordChatExporter.Cli exportguild -t BOT_TOKEN -g GUILD_ID --format Json -o ./server_export")
    
    # Test the analyzer
    print("\n" + "=" * 60)
    print("TESTING CONTENT ANALYZER")
    print("=" * 60)
    
    try:
        from server_helper import ContentAnalyzer, BAD_WORDS_CRITICAL
        
        analyzer = ContentAnalyzer()
        
        test_cases = [
            ("Hello, how are you?", False),
            ("This is a normal message about games", False),
            ("I really wanna kill that boss in the game", False),  # Gaming context
            (f"You're a {BAD_WORDS_CRITICAL[0] if BAD_WORDS_CRITICAL else 'test'}", True),
            ("nobody likes you, you're worthless", True),
            ("kys", True),
        ]
        
        print("\nTest Results:")
        for msg, should_flag in test_cases:
            result = analyzer.analyze(msg)
            status = "🚨" if result.should_delete else ("⚠️" if result.is_flagged else "✅")
            expected = "FLAG" if should_flag else "CLEAN"
            actual = "FLAG" if result.is_flagged else "CLEAN"
            match = "✓" if (should_flag == result.is_flagged) else "✗"
            
            print(f"  {status} [{match}] {msg[:40]}... (expected: {expected}, got: {actual})")
        
    except Exception as e:
        print(f"  ⚠️  Analyzer test failed: {e}")
    
    # Summary
    print("\n" + "=" * 60)
    print("SETUP COMPLETE!")
    print("=" * 60)
    
    print("""
NEXT STEPS:
-----------

1. Configure your bot token in server_helper.py:
   BOT_TOKEN = "your_token_here"
   
   Or set environment variable:
   export HELPER_BOT_TOKEN="your_token_here"

2. Verify channel IDs in server_helper.py:
   - MONITORED_CHANNELS: channels to watch
   - BLOCKED_CHANNELS: channels to ignore
   - MOD_LOG_CHANNEL_ID: where to send mod logs

3. Start the bot:
   python server_helper.py

4. Use slash commands in Discord:
   /tos_scan    - Scan historical messages from exports
   /tos_purge   - Delete flagged messages
   /tos_stats   - View moderation statistics
   /tos_test    - Test a message against the filter
   /tos_addword - Add a word to the filter
""")


if __name__ == "__main__":
    main()
