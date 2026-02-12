"""
User Message Preparation for Chatbot Training
Analyzes and prepares a user's messages for use in few-shot prompting or fine-tuning.
"""

import json
import re
import random
from collections import Counter
from pathlib import Path
from typing import Optional
from common import db


def analyze_user_messages(user_id: str) -> dict:
    """
    Analyze a user's message patterns to understand their style.
    """
    messages = db.get_user_messages(user_id)
    
    if not messages:
        return {"error": "No messages found for this user"}
    
    # Filter to actual content (not just links, reactions, etc.)
    content_messages = [
        m for m in messages 
        if m['content'] 
        and len(m['content']) > 5 
        and not m['content'].startswith('http')
        and not re.match(r'^<[a-z]*:\w+:\d+>$', m['content'])  # Not just an emoji
    ]
    
    # Calculate statistics
    lengths = [len(m['content']) for m in content_messages]
    word_counts = [len(m['content'].split()) for m in content_messages]
    
    # Analyze punctuation and style
    all_text = ' '.join(m['content'] for m in content_messages)
    
    stats = {
        "total_messages": len(messages),
        "content_messages": len(content_messages),
        "avg_length_chars": sum(lengths) / len(lengths) if lengths else 0,
        "avg_length_words": sum(word_counts) / len(word_counts) if word_counts else 0,
        "median_length_chars": sorted(lengths)[len(lengths)//2] if lengths else 0,
        "uses_caps_frequently": sum(1 for m in content_messages if m['content'].isupper()) / len(content_messages) > 0.05,
        "uses_lowercase": sum(1 for m in content_messages if m['content'].islower()) / len(content_messages) > 0.3,
        "uses_punctuation": all_text.count('.') + all_text.count('!') + all_text.count('?') > len(content_messages) * 0.5,
        "emoji_frequency": len(re.findall(r'<:\w+:\d+>|[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF]', all_text)) / len(content_messages),
        "question_frequency": all_text.count('?') / len(content_messages),
        "exclamation_frequency": all_text.count('!') / len(content_messages),
    }
    
    # Common phrases (2-3 word combinations)
    words = all_text.lower().split()
    bigrams = [' '.join(words[i:i+2]) for i in range(len(words)-1)]
    trigrams = [' '.join(words[i:i+3]) for i in range(len(words)-2)]
    
    stats["common_bigrams"] = Counter(bigrams).most_common(20)
    stats["common_trigrams"] = Counter(trigrams).most_common(15)
    
    # Vocabulary
    stats["vocabulary"] = db.get_user_vocabulary(user_id, top_n=30)
    
    return stats


def select_representative_messages(user_id: str, count: int = 50, min_length: int = 15, max_length: int = 300) -> list:
    """
    Select diverse, representative messages for few-shot examples.
    Filters for quality and variety.
    """
    messages = db.get_user_messages(user_id)
    
    # Filter criteria
    filtered = []
    for m in messages:
        content = m['content'].strip()
        
        # Skip if too short or too long
        if len(content) < min_length or len(content) > max_length:
            continue
        
        # Skip if it's just a link
        if content.startswith('http') or content.startswith('<http'):
            continue
        
        # Skip if it's just emojis or a reaction
        if re.match(r'^(<[a-z]*:\w+:\d+>\s*)+$', content):
            continue
        
        # Skip if it's a bot command
        if content.startswith('/') or content.startswith('.') or content.startswith('!'):
            continue
        
        # Skip if too many mentions (probably context-dependent)
        if content.count('<@') > 2:
            continue
            
        filtered.append(content)
    
    # Remove near-duplicates
    unique = []
    seen_starts = set()
    for msg in filtered:
        start = msg[:30].lower()
        if start not in seen_starts:
            unique.append(msg)
            seen_starts.add(start)
    
    # Sample diverse messages
    if len(unique) <= count:
        return unique
    
    # Try to get variety in length and style
    short = [m for m in unique if len(m) < 50]
    medium = [m for m in unique if 50 <= len(m) < 150]
    long = [m for m in unique if len(m) >= 150]
    
    result = []
    for pool, target in [(short, count//3), (medium, count//3), (long, count//3)]:
        if pool:
            result.extend(random.sample(pool, min(target, len(pool))))
    
    # Fill remainder randomly
    remaining = [m for m in unique if m not in result]
    if remaining and len(result) < count:
        result.extend(random.sample(remaining, min(count - len(result), len(remaining))))
    
    random.shuffle(result)
    return result[:count]


def select_conversational_pairs(user_id: str, count: int = 30) -> list:
    """
    Find messages that are replies and pair them with context.
    Better for training conversational responses.
    """
    import sqlite3
    
    conn = sqlite3.connect('discord_analytics.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get user's replies with the message they replied to
    cursor.execute("""
        SELECT 
            m1.content as reply_content,
            m2.content as original_content,
            m2.author_name as original_author
        FROM messages m1
        JOIN messages m2 ON m1.reply_to_id = m2.message_id
        WHERE m1.author_id = ? 
        AND m1.is_reply = 1
        AND m1.content != ''
        AND m2.content != ''
        AND length(m1.content) > 10
        AND length(m2.content) > 10
        ORDER BY RANDOM()
        LIMIT ?
    """, (user_id, count * 2))  # Get extra to filter
    
    pairs = []
    for row in cursor.fetchall():
        # Filter out low-quality pairs
        if row['original_content'].startswith('http'):
            continue
        if len(row['reply_content']) < 15:
            continue
            
        pairs.append({
            "input": row['original_content'],
            "input_author": row['original_author'],
            "response": row['reply_content']
        })
        
        if len(pairs) >= count:
            break
    
    conn.close()
    return pairs


def generate_system_prompt(user_id: str, username: str, example_count: int = 30) -> str:
    """
    Generate a system prompt for Claude/GPT to emulate this user.
    """
    stats = analyze_user_messages(user_id)
    examples = select_representative_messages(user_id, count=example_count)
    
    # Build style description
    style_notes = []
    
    if stats.get('uses_lowercase'):
        style_notes.append("often types in all lowercase")
    if stats.get('uses_caps_frequently'):
        style_notes.append("sometimes uses ALL CAPS for emphasis")
    if not stats.get('uses_punctuation'):
        style_notes.append("rarely uses punctuation")
    if stats.get('emoji_frequency', 0) > 0.3:
        style_notes.append("frequently uses emojis")
    if stats.get('avg_length_words', 0) < 10:
        style_notes.append("tends to write short messages")
    elif stats.get('avg_length_words', 0) > 25:
        style_notes.append("often writes longer, detailed messages")
    if stats.get('question_frequency', 0) > 0.3:
        style_notes.append("asks questions often")
    if stats.get('exclamation_frequency', 0) > 0.3:
        style_notes.append("uses exclamation marks frequently")
    
    style_description = ", ".join(style_notes) if style_notes else "casual Discord chat style"
    
    # Common words/phrases
    vocab_words = [word for word, count in stats.get('vocabulary', [])[:15]]
    
    prompt = f"""You are roleplaying as {username}, a Discord user. Your goal is to respond exactly as they would - matching their personality, opinions, writing style, and mannerisms.

## Writing Style
{username} {style_description}.

## Vocabulary
Words/phrases they commonly use: {', '.join(vocab_words)}

## Example Messages
Here are real messages from {username} showing how they typically write:

"""
    
    for i, example in enumerate(examples, 1):
        prompt += f"{i}. \"{example}\"\n"
    
    prompt += f"""
## Instructions
- Match {username}'s exact writing style: capitalization, punctuation, message length
- Use similar vocabulary and phrases they would use
- Stay in character - respond as {username} would, not as an AI assistant
- Keep responses natural and conversational, similar length to their typical messages
- If asked about being an AI or bot, deflect naturally as {username} would
- Don't be overly helpful or formal - match their casual Discord energy
"""
    
    return prompt


def generate_training_data_jsonl(user_id: str, username: str, output_path: str, count: int = 100):
    """
    Generate JSONL training data for fine-tuning (OpenAI format).
    Uses conversational pairs when available.
    """
    pairs = select_conversational_pairs(user_id, count=count)
    examples = select_representative_messages(user_id, count=count)
    
    system_prompt = f"You are {username}, a Discord user. Respond naturally in their style."
    
    with open(output_path, 'w', encoding='utf-8') as f:
        # Write conversational pairs
        for pair in pairs:
            entry = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": pair['input']},
                    {"role": "assistant", "content": pair['response']}
                ]
            }
            f.write(json.dumps(entry) + '\n')
        
        # Write standalone examples as self-expression
        prompts = [
            "Say something",
            "What's on your mind?",
            "Share a thought",
            "React to this",
            "What do you think?",
        ]
        
        for example in examples[:50]:
            entry = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": random.choice(prompts)},
                    {"role": "assistant", "content": example}
                ]
            }
            f.write(json.dumps(entry) + '\n')
    
    total = len(pairs) + min(50, len(examples))
    print(f"Generated {total} training examples to {output_path}")
    return total


def export_for_chatbot(user_id: str, username: str, output_dir: str = "./chatbot_data"):
    """
    Export all necessary files for creating a user chatbot.
    """
    Path(output_dir).mkdir(exist_ok=True)
    
    # 1. System prompt
    system_prompt = generate_system_prompt(user_id, username, example_count=40)
    with open(f"{output_dir}/system_prompt.txt", 'w', encoding='utf-8') as f:
        f.write(system_prompt)
    print(f"✓ System prompt saved to {output_dir}/system_prompt.txt")
    
    # 2. Analysis
    stats = analyze_user_messages(user_id)
    with open(f"{output_dir}/analysis.json", 'w', encoding='utf-8') as f:
        # Convert Counter objects to regular lists for JSON serialization
        stats_clean = {k: v for k, v in stats.items() if not isinstance(v, list) or (v and not isinstance(v[0], tuple))}
        stats_clean['common_bigrams'] = stats.get('common_bigrams', [])
        stats_clean['vocabulary'] = stats.get('vocabulary', [])
        json.dump(stats_clean, f, indent=2, default=str)
    print(f"✓ Analysis saved to {output_dir}/analysis.json")
    
    # 3. Raw messages
    db.export_user_corpus(user_id, f"{output_dir}/all_messages.txt")
    print(f"✓ All messages saved to {output_dir}/all_messages.txt")
    
    # 4. Training data (JSONL)
    generate_training_data_jsonl(user_id, username, f"{output_dir}/training_data.jsonl", count=150)
    print(f"✓ Training data saved to {output_dir}/training_data.jsonl")
    
    # 5. Example messages (curated)
    examples = select_representative_messages(user_id, count=100)
    with open(f"{output_dir}/example_messages.json", 'w', encoding='utf-8') as f:
        json.dump(examples, f, indent=2, ensure_ascii=False)
    print(f"✓ Example messages saved to {output_dir}/example_messages.json")
    
    print(f"\n✓ All chatbot data exported to {output_dir}/")
    print(f"\nNext steps:")
    print(f"  1. Review system_prompt.txt and adjust if needed")
    print(f"  2. Use with Claude API: see user_chatbot.py")
    print(f"  3. Or fine-tune: upload training_data.jsonl to OpenAI/Together.ai")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python prepare_chatbot.py <user_id> <username>")
        print("Example: python prepare_chatbot.py 123456789012345678 'CoolUser'")
        sys.exit(1)
    
    user_id = sys.argv[1]
    username = sys.argv[2]
    
    print(f"Preparing chatbot data for {username} (ID: {user_id})...")
    export_for_chatbot(user_id, username)
