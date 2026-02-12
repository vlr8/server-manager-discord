#!/usr/bin/env python3
"""
Content Moderation System Setup
================================

This script sets up the complete content moderation system:
1. Initializes databases
2. Imports historical data for pattern learning
3. Configures bad words
4. Tests the analyzer

Run this before starting your bot with live monitoring.
"""

import sys
import json
from pathlib import Path


def main():
    print("="*60)
    print("CONTENT MODERATION SYSTEM SETUP")
    print("="*60)
    
    # Step 1: Check dependencies
    print("\n[1/6] Checking dependencies...")
    
    missing = []
    
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        print("  ✅ vaderSentiment installed")
    except ImportError:
        missing.append("vaderSentiment")
        print("  ⚠️  vaderSentiment not installed (sentiment analysis will be disabled)")
    
    try:
        import interactions
        print("  ✅ interactions.py installed")
    except ImportError:
        missing.append("interactions.py")
        print("  ❌ interactions.py not installed (required)")
    
    if missing:
        print(f"\nInstall missing packages:")
        print(f"  pip install {' '.join(missing)}")
        if "interactions.py" in missing:
            sys.exit(1)
    
    # Step 2: Initialize databases
    print("\n[2/6] Initializing databases...")
    
    try:
        from common import db
        db.init_database()
        print("  ✅ Analytics database ready")
    except Exception as e:
        print(f"  ⚠️  Analytics database: {e}")
    
    try:
        import common.moderation_db as mdb
        mdb.init_moderation_db()
        print("  ✅ Moderation database ready")
    except Exception as e:
        print(f"  ❌ Moderation database error: {e}")
        sys.exit(1)
    
    # Step 3: Import historical data (if available)
    print("\n[3/6] Checking for historical data...")
    
    # Check for Discord exports
    export_dirs = ['./discord_exports', './exports', './data']
    json_files = []
    for dir_path in export_dirs:
        if Path(dir_path).exists():
            json_files.extend(Path(dir_path).glob("*.json"))
    
    if json_files:
        print(f"  Found {len(json_files)} Discord export files")
        response = input("  Import Discord exports to analytics DB? [y/N]: ").strip().lower()
        if response == 'y':
            from common import db
            for f in json_files:
                try:
                    db.import_discord_export(str(f))
                except Exception as e:
                    print(f"    ⚠️  Error importing {f.name}: {e}")
            print("  ✅ Import complete")
    else:
        print("  No Discord export files found")
    
    # Check for flagged messages file
    if Path("flagged_messages.json").exists():
        print("  Found flagged_messages.json")
        response = input("  Import as training samples? [y/N]: ").strip().lower()
        if response == 'y':
            from content_analyzer import import_bad_messages_as_samples
            count = import_bad_messages_as_samples()
            print(f"  ✅ Imported {count} training samples")
    
    # Step 4: Configure bad words
    print("\n[4/6] Configuring bad words...")
    
    existing_words = mdb.get_bad_words()
    print(f"  Current bad words: {len(existing_words)}")
    
    # Option to add from file
    if Path("bad_words.txt").exists():
        with open("bad_words.txt", 'r') as f:
            words = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        if words:
            response = input(f"  Found bad_words.txt with {len(words)} words. Import? [y/N]: ").strip().lower()
            if response == 'y':
                added = mdb.add_bad_words_bulk(words, severity=3)
                print(f"  ✅ Added {added} new bad words")
    
    # Option to add interactively
    response = input("  Add bad words interactively? [y/N]: ").strip().lower()
    if response == 'y':
        print("  Enter bad words (comma-separated), or 'done' to finish:")
        while True:
            words_input = input("  > ").strip()
            if words_input.lower() == 'done':
                break
            words = [w.strip() for w in words_input.split(',') if w.strip()]
            if words:
                severity = input("    Severity 1-5 [3]: ").strip()
                severity = int(severity) if severity.isdigit() else 3
                mdb.add_bad_words_bulk(words, severity=severity)
                print(f"    Added {len(words)} words")
    
    # Step 5: Learn patterns
    print("\n[5/6] Learning patterns from training data...")
    
    from content_analyzer import learn_patterns_from_samples
    
    # Check if we have training samples
    conn = mdb.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM training_samples WHERE label = 'bad'")
    sample_count = cursor.fetchone()['count']
    conn.close()
    
    if sample_count > 0:
        print(f"  Found {sample_count} training samples")
        response = input("  Learn patterns from samples? [Y/n]: ").strip().lower()
        if response != 'n':
            patterns_learned = learn_patterns_from_samples(min_frequency=2)
            print(f"  ✅ Learned {patterns_learned} new patterns")
    else:
        print("  No training samples available yet")
        print("  (Import flagged messages or add samples manually)")
    
    # Step 6: Test the analyzer
    print("\n[6/6] Testing content analyzer...")
    
    from content_analyzer import ContentAnalyzer
    
    analyzer = ContentAnalyzer()
    
    test_messages = [
        "Hello, how are you today?",
        "This is a normal message",
        "You are worthless and nobody likes you",
        "I hope you have a great day!",
    ]
    
    # Add a test with a configured bad word if any exist
    bad_words = mdb.get_bad_words()
    if bad_words:
        test_messages.append(f"This contains {bad_words[0]['word']} in it")
    
    print("\n  Test Results:")
    print("  " + "-"*50)
    
    for msg in test_messages:
        result = analyzer.analyze(msg)
        status = "🚨 FLAGGED" if result.is_flagged else "✅ Clean"
        print(f"  {status} | {msg[:40]}...")
        if result.is_flagged:
            print(f"           Reasons: {', '.join(result.reasons)}")
            print(f"           Toxicity: {result.toxicity_score:.2f}")
    
    print("\n" + "="*60)
    print("SETUP COMPLETE!")
    print("="*60)
    
    print("""
NEXT STEPS:
-----------

1. Add the monitor to your bot. In bot1.py, add these imports:
   
   from live_monitor import setup_live_monitor
   from live_monitor import *  # For slash commands

2. In your on_startup function, add:
   
   setup_live_monitor(client)

3. Configure monitored channels via Discord commands:
   
   /monitor_add channel:#general level:2
   /badword_add word:badword severity:4

4. View statistics:
   
   /modstats days:7

FILES CREATED:
--------------
• moderation.db - Stores flagged messages, patterns, offenses
• discord_analytics.db - Historical message data (if imported)

CONFIGURATION:
--------------
• Edit live_monitor.py MonitorConfig class to customize behavior
• Add bad words via /badword_add or bad_words.txt file
• Training samples improve pattern detection over time
""")


if __name__ == "__main__":
    main()
