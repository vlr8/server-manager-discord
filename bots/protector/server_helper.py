"""
Server Helper Bot - Discord ToS Protection
==========================================

A standalone Discord bot for real-time content moderation and ToS compliance.
Features:
- Live message monitoring and auto-deletion
- Censored message reposting
- Historical message scanning from Discord exports
- Pattern learning from sample deleted messages
- Sentiment and toxicity analysis

Setup:
1. pip install interactions.py vaderSentiment
2. python setup_moderation.py
3. Configure BOT_TOKEN below
4. python server_helper.py
"""

import os
import re
import json
import asyncio
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Set
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv()
PROTECTOR_BOT_TOKEN = os.environ["PROTECTOR_BOT_TOKEN"]

try:
    import ijson
    IJSON_AVAILABLE = True
except ImportError:
    IJSON_AVAILABLE = False
    print("Warning: ijson not installed. Run 'pip install ijson' for streaming large file support.")

import interactions
from interactions import (
    Client,
    Intents,
    listen,
    slash_command,
    slash_option,
    SlashContext,
    OptionType,
    SlashCommandChoice,
    Embed,
    Button,
    ButtonStyle,
    auto_defer,
)
from interactions.api.events import MessageCreate

# ============== CONFIGURATION ==============

# Bot token from Discord Developer Portal (SEPARATE bot from your main bot)
# BOT_TOKEN = os.environ.get("HELPER_BOT_TOKEN", "BOT_TOKEN_HERE")
BOT_TOKEN = ""

# Your server ID
GUILD_ID = 1158203871554961579

# Mod log channel for audit trail
MOD_LOG_CHANNEL_ID = 1306403996550041650

# Admin/Support role IDs for permission checks
ADMIN_ROLE_ID = 1158203871760490522
SUPPORT_ROLE_ID = 1158203871760490518

# ---------- Moderation Behavior ----------

# Primary bad words list - instant flag (severity 5)
# Based on Discord ToS violations and your sample deleted messages
BAD_WORDS_CRITICAL = [
    # Slurs and hate speech
    'chink','chinks', 'faggot','faggots', 'fag','fags',
    'nigger','niggers','kike','kikes', 'spic', 'wetback','negroid',
    'gook', 'coon', 'dyke','paki','nog','troon','troons',
    # Violence keywords in threatening context
    'kys', 'kill yourself', 'kill urself', 'kill all',
    'death to','should die','rape you',
]

# Secondary bad words - flag with context check (severity 3)
BAD_WORDS_MODERATE = [
    # These need context - "kill" alone might be gaming
    'kill', 'murder', 'rape', 'lynch', 'hang yourself',
    # Dehumanizing language
    'subhuman', 'untermensch', 'vermin', 'cockroach', 'parasite',
    # Conspiracy/extremism markers
    'deep state', 'white genocide', 'great replacement', 'race war',
    # Doxxing indicators
    'doxx', 'dox', 'leak their', 'find where they live',
]

# Reclaimed slurs - only flag when used with hateful context (severity 3)
# These terms may be used for self-identification, so we check for negative intent
SLUR_WORDS_MODERATE = [
    'tranny', 'trannies',
]

# Hateful context indicators - words/phrases that precede slurs in hateful usage
HATEFUL_CONTEXT_PATTERNS = [
    r'\b(fucking|fuckin|fking)\s+',           # "fucking trannies"
    r'\b(hate|hating)\s+',                     # "hate trannies"
    r'\bi\s+(fucking\s+)?hate\s+',             # "i hate trannies", "i fucking hate trannies"
    r'\b(dumb|stupid|disgusting|gross|ugly)\s+',  # "dumb trannies"
    r'\b(kill|shoot|beat|attack)\s+(the\s+|all\s+)?',  # "kill the trannies"
    r'\b(all\s+)?(those|these)\s+(fucking\s+)?',  # "all those trannies"
    r'\b(die|death\s+to)\s+',                  # "die trannies"
    r'\b(filthy|dirty|nasty)\s+',              # "filthy trannies"
    r'\b(degenerate|sick|mentally\s+ill)\s+',  # "degenerate trannies"
]

# Protected groups for combination detection (ethnicity + religion)
PROTECTED_GROUPS = [
    # Ethnic groups
    'jews', 'jewish', 'jew', 'whites', 'white', 'white man', 'white men', 'white people',
    'blacks', 'black', 'black man', 'black men', 'black people',
    'asians', 'asian', 'arabs', 'arab',
    # Religious groups
    'muslims', 'muslim', 'christians', 'christian',
    # Sexual orientation / gender identity
    'gays', 'queers', 'queer','lgbt',
    # Other
    'women', 'immigrants', 'refugees', 'children'
]

# Hate action verbs that indicate hate speech when combined with protected groups
HATE_ACTION_VERBS = [
    # Violence
    'kill', 'murder', 'hang', 'shoot', 'stab', 'beat', 'attack', 'lynch',
    # Hatred
    'hate', 'hates', 'hating', 'hated', 'despise', 'despises', 'loathe',
    # Dehumanization
    'exterminate', 'eradicate', 'eliminate', 'purge', 'cleanse',
]

# Phrases that indicate ToS violations (from your sample deleted messages)
TOS_VIOLATION_PATTERNS = [
    # Threats and violence (ToS #2, #5)
    (r'\b(i\s+will|i\'ll|gonna|going\s+to)\s+(kill|hurt|find|attack)\s+(you|them|him|her)\b', 'threat'),
    (r'\b(hope\s+you|you\s+should|go)\s+(die|kill\s+yourself|kys)\b', 'self_harm_encouragement'),
    (r'\breally\s+wanna\s+kill\b', 'threat'),
    
    # Hate speech patterns (ToS #4)
    (r'\b(jews?|jewish)\s+(are|women|men|people)\s+\w*\s*(evil|greedy|control|soulless|shapeshifter)', 'antisemitism'),
    (r'\b(blacks?|whites?|asians?)\s+aren\'?t\s+human\b', 'dehumanization'),
    (r'\b(trann|fag|dyke)s?\s+(are|is)\s+\w*\s*(problem|disease|mental)', 'hate_speech'),
    (r'\bnazi\s+girl\b', 'hate_imagery'),
    (r'\bimported\s+a\s+tranny\b', 'hate_speech'),
    
    # Doxxing (ToS #3)
    (r'\b(doxx|dox)\s+(them|him|her|you)\b', 'doxxing'),
    (r'\bwould\s+(really\s+)?doxx\b', 'doxxing'),
    (r'\bleak\s+their\s+(address|info|location)\b', 'doxxing'),
    
    # Harassment patterns (ToS #1)
    (r'\b(nobody|no\s*one)\s+(likes?|wants?|cares?\s+about)\s+(you|u)\b', 'harassment'),
    (r'\byou\'?re?\s+(worthless|pathetic|disgusting|trash|garbage)\b', 'harassment'),
    
    # Violent extremism (ToS #5)
    (r'\b(race\s+war|white\s+genocide|great\s+replacement)\b', 'extremism'),
    (r'\b(killed\s+by\s+the\s+deep\s+state|israel\s+did)\b', 'conspiracy'),
    
    # Dehumanization
    (r'\b\w+s?\s+aren\'?t\s+human\b', 'dehumanization'),
    (r'\bsoulless\s+shapeshifters?\b', 'dehumanization'),
]

# Map of Latin characters to homoglyphs, ordered by visual similarity (best first)
HOMOGLYPHS = {
    'a': ['а'],           # Cyrillic - virtually identical
    'A': ['А'],           # Cyrillic
    'B': ['В'],           # Cyrillic
    'c': ['с'],           # Cyrillic
    'C': ['С'],           # Cyrillic
    'e': ['е'],           # Cyrillic
    'E': ['Е'],           # Cyrillic
    'H': ['Н'],           # Cyrillic
    'i': ['і'],           # Cyrillic (Ukrainian)
    'I': ['І'],           # Cyrillic (Ukrainian)
    'j': ['ј'],           # Cyrillic (Serbian)
    'K': ['К'],           # Cyrillic
    'M': ['М'],           # Cyrillic
    'N': ['Ν'],           # Greek (no Cyrillic equivalent)
    'o': ['о'],           # Cyrillic
    'O': ['О'],           # Cyrillic
    'p': ['р'],           # Cyrillic
    'P': ['Р'],           # Cyrillic
    's': ['ѕ'],           # Cyrillic (Macedonian)
    'S': ['Ѕ'],           # Cyrillic (Macedonian)
    'T': ['Т'],           # Cyrillic
    'x': ['х'],           # Cyrillic
    'X': ['Х'],           # Cyrillic
    'y': ['у'],           # Cyrillic
    'Y': ['У'],           # Cyrillic
    'Z': ['Ζ'],           # Greek
}

# Priority score for each character (lower = more visually identical)
# Based on how indistinguishable the best homoglyph is
PRIORITY = {
    'o': 1, 'O': 1, 'a': 1, 'A': 1, 'e': 1, 'E': 1,  # Perfect matches
    'c': 1, 'C': 1, 'p': 1, 'P': 1, 'x': 1, 'X': 1,
    'y': 1, 'Y': 1, 'i': 1, 'I': 1, 's': 1, 'S': 1,
    'H': 2, 'M': 2, 'T': 2, 'K': 2, 'B': 2,          # Very close
    'j': 2, 'N': 2, 'Z': 2,                          # Slight differences possible
}

# Channels
message_log_channel_id = 1158203871982792787
mod_log_channel_id = 1306403996550041650
invite_log_channel_id = 1172884351491518545
member_count_channel_id = 1158203871982792785
unverified_channel_id = 1464809531698839828

trans_channel_id = 1163525301444296795
verified_selifes_channel_id = 1158203872674840584
verified_nsfw_channel_id = 1158203872674840585
voice_practice = 1420104463628112033

dolls_chat_id = 1302299629659881603
dolls_selfies_id = 1329710733432197255
dolls_nsfw_id = 1262267477774041158

new_monkey_channel_id = 1465796764949938432
tranner_central_id = 1158681076504469514
public_pics_id = 1194335452782669925
public_nsfw_id = 1220844022780657674
aesthetics_id = 1158203872960065626

transition_advice_id = 1158203872960065628
beauty_fashion_id = 1159022771788054538
armchair_endos_id = 1159032921445904406
psych_wormfree_id = 1159032691979718746

meme_dump_id = 1162817069566394518
vids_n_tunes_id = 1158203872674840581
confessions_id = 1175263822211203193
server_polls_id = 1359048496526790686
commands_id = 1164026321194713098
autism_politics_id = 1242477145088065639
dooming_id = 1159138033694691378
copypasta_id = 1333855091999899668

commands_vc_id = 1163300880582459452
yapping_vc_id = 1158203872960065634
movies_vs_id = 1325346217521315962

tryhard_nerd_theory_id = 1159034063663927347
games_n_tabletop_id = 1159030095223201946
culture_war_news_id = 1159033602168860692
stem_ai_news_id = 1159030212336570528
finance_n_crypto_id = 1250954992613986405
non_neets_chat_id = 1159030428280307792

# Channels to monitor (empty = all channels except blocked)
MONITORED_CHANNELS = [
    trans_channel_id, verified_selifes_channel_id, verified_nsfw_channel_id,
    voice_practice, dolls_chat_id, dolls_selfies_id,
    dolls_nsfw_id, new_monkey_channel_id, tranner_central_id,
    public_pics_id, public_nsfw_id, aesthetics_id,
    transition_advice_id, beauty_fashion_id, armchair_endos_id,
    psych_wormfree_id, meme_dump_id, confessions_id,
    autism_politics_id, dooming_id, commands_vc_id,
    yapping_vc_id, movies_vs_id, games_n_tabletop_id,
    culture_war_news_id, stem_ai_news_id, finance_n_crypto_id
]

# Channels to NEVER moderate (mod channels, admin chat)
BLOCKED_CHANNELS = [
    1172884351491518545,1306403996550041650,1158203871982792787,
    1158203871982792788,1158203871982792789,1360355294265213070,
    1162467224808857610,1181002734464409750
]

# Path to Discord exports directory
EXPORT_DIR = "./server_export"

# Path to sample deleted messages for pattern learning
SAMPLE_DELETED_PATH = "./sample_deleted_messages.txt"

# Censoring character
CENSOR_CHAR = "█"

# Auto-timeout settings
AUTO_TIMEOUT_ENABLED = False
AUTO_TIMEOUT_DURATION = 600  # 10 minutes
OFFENSES_BEFORE_TIMEOUT = 3

# ============== END CONFIGURATION ==============

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("helper_bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger("ServerHelper")

# Try to import optional modules
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    sentiment_analyzer = SentimentIntensityAnalyzer()
    SENTIMENT_AVAILABLE = True
    logger.info("Sentiment analysis enabled")
except ImportError:
    sentiment_analyzer = None
    SENTIMENT_AVAILABLE = False
    logger.warning("vaderSentiment not installed - sentiment analysis disabled")

# Try to import moderation database
try:
    import common.moderation_db as mdb
    MDB_AVAILABLE = True
except ImportError:
    MDB_AVAILABLE = False
    logger.warning("moderation_db not found - using in-memory tracking only")

# Initialize client
client = Client(
    token=PROTECTOR_BOT_TOKEN,
    intents=Intents.GUILDS | Intents.GUILD_MESSAGES | Intents.MESSAGE_CONTENT | Intents.GUILD_MEMBERS,
)

# In-memory tracking (fallback if no database)
flagged_messages_cache: Dict[str, dict] = {}
user_offenses_cache: Dict[str, List[datetime]] = {}
recently_processed: Set[str] = set()

# Live monitoring state
MONITORING_ENABLED = True  # Global toggle for live monitoring


# ============== ANALYSIS RESULT ==============

@dataclass
class AnalysisResult:
    """Result of content analysis."""
    is_flagged: bool
    severity: int  # 1-5, 5 being most severe
    reasons: List[str]
    matched_words: List[str]
    matched_patterns: List[Tuple[str, str]]  # (pattern, category)
    sentiment_score: float
    should_delete: bool
    should_timeout: bool
    censored_content: str


# ============== CONTENT ANALYZER ==============

class ContentAnalyzer:
    """
    Analyzes message content for Discord ToS violations.
    Uses multiple methods:
    - Keyword matching (critical and moderate lists)
    - Regex pattern matching (ToS violation patterns)
    - Sentiment analysis (negative sentiment as additional signal)
    """
    
    def __init__(self):
        # Compile regex patterns for efficiency
        self.compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), category)
            for pattern, category in TOS_VIOLATION_PATTERNS
        ]
        
        # Load learned patterns from sample deleted messages
        self.learned_phrases = set()
        self._load_sample_deleted_messages()
    
    def _load_sample_deleted_messages(self):
        """Load and learn from sample deleted messages."""
        if Path(SAMPLE_DELETED_PATH).exists():
            try:
                with open(SAMPLE_DELETED_PATH, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            # Extract key phrases (3+ word sequences)
                            words = line.lower().split()
                            for i in range(len(words) - 2):
                                phrase = ' '.join(words[i:i+3])
                                if len(phrase) > 10:  # Meaningful length
                                    self.learned_phrases.add(phrase)
                logger.info(f"Loaded {len(self.learned_phrases)} learned phrases from samples")
            except Exception as e:
                logger.error(f"Error loading sample deleted messages: {e}")
    
    def analyze(self, content: str, author_id: str = None) -> AnalysisResult:
        """
        Analyze message content for ToS violations.
        
        Returns AnalysisResult with all detection details.
        """
        if not content or not content.strip():
            return AnalysisResult(
                is_flagged=False, severity=0, reasons=[], matched_words=[],
                matched_patterns=[], sentiment_score=0, should_delete=False,
                should_timeout=False, censored_content=content
            )
        
        content_lower = content.lower()
        reasons = []
        matched_words = []
        matched_patterns = []
        severity = 0
        
        # 1. Check critical bad words (instant flag, severity 5)
        for word in BAD_WORDS_CRITICAL:
            pattern = r'\b' + re.escape(word) + r'\b'
            if re.search(pattern, content_lower):
                matched_words.append(word)
                severity = 5
                reasons.append(f"critical_word:{word}")
        
        # 2. Check moderate bad words (need context, severity 3)
        for word in BAD_WORDS_MODERATE:
            pattern = r'\b' + re.escape(word) + r'\b'
            if re.search(pattern, content_lower):
                # Context check - is it in a threatening context?
                if self._is_threatening_context(content_lower, word):
                    matched_words.append(word)
                    severity = max(severity, 3)
                    reasons.append(f"moderate_word:{word}")

        # 3. Check reclaimed slurs - only flag if used in hateful context
        for slur in SLUR_WORDS_MODERATE:
            pattern = r'\b' + re.escape(slur) + r'\b'
            if re.search(pattern, content_lower):
                # Only flag if preceded by hateful context indicators
                if self._is_hateful_slur_context(content_lower, slur):
                    matched_words.append(slur)
                    severity = max(severity, 3)
                    reasons.append(f"hateful_slur:{slur}")

        # 4. Check hate verb + protected group combinations
        is_hate_combo, hate_matches = self._is_hate_combination(content_lower)
        if is_hate_combo:
            for phrase in hate_matches:
                matched_patterns.append((phrase, 'hate_combination'))
            severity = max(severity, 4)
            reasons.append(f"hate_combination:{','.join(hate_matches[:3])}")

        # 5. Check ToS violation patterns
        for compiled_pattern, category in self.compiled_patterns:
            match = compiled_pattern.search(content)
            if match:
                matched_patterns.append((match.group(0), category))
                severity = max(severity, 4)
                reasons.append(f"pattern:{category}")

        # 6. Check learned phrases from sample deleted messages
        for phrase in self.learned_phrases:
            if phrase in content_lower:
                severity = max(severity, 2)
                reasons.append("learned_pattern")
                break  # One match is enough

        # 7. Sentiment analysis (supplementary signal)
        sentiment_score = self._analyze_sentiment(content)
        if sentiment_score < -0.6 and len(matched_words) > 0:
            severity = min(5, severity + 1)
            reasons.append("very_negative_sentiment")

        # 8. Check for repeat offender
        if author_id and self._is_repeat_offender(author_id):
            severity = min(5, severity + 1)
            reasons.append("repeat_offender")
        
        # Determine actions
        is_flagged = severity >= 2 or len(matched_words) > 0 or len(matched_patterns) > 0
        should_delete = severity >= 3 or len(matched_words) > 0
        should_timeout = severity >= 5
        
        # Generate censored content
        censored_content = self._censor_content(content, matched_words)
        
        return AnalysisResult(
            is_flagged=is_flagged,
            severity=severity,
            reasons=reasons,
            matched_words=matched_words,
            matched_patterns=matched_patterns,
            sentiment_score=sentiment_score,
            should_delete=should_delete,
            should_timeout=should_timeout,
            censored_content=censored_content
        )
    
    def _is_threatening_context(self, content: str, word: str) -> bool:
        """Check if a moderate word is used in a threatening context."""
        # Gaming context exceptions
        gaming_indicators = ['game', 'gaming', 'player', 'level', 'boss', 'enemy', 'mob', 'npc','points']
        if any(g in content for g in gaming_indicators):
            return False

        # Check for threatening patterns around the word
        threatening_contexts = [
            r'(i\s+will|gonna|going\s+to|want\s+to|wanna)\s+' + re.escape(word),
            re.escape(word) + r'\s+(you|yourself|them|him|her)',
            r'should\s+' + re.escape(word),
            r'fuck\s+' + re.escape(word),
        ]

        for pattern in threatening_contexts:
            if re.search(pattern, content, re.IGNORECASE):
                return True

        # Check if this word is part of a hate combination (verb + protected group)
        is_hate_combo, _ = self._is_hate_combination(content)
        if is_hate_combo:
            return True

        return False

    def _is_hateful_slur_context(self, content: str, slur: str) -> bool:
        """
        Check if a reclaimed slur is used in a hateful context.
        Returns True if hateful indicators precede the slur.
        Allows neutral/self-referential usage like "I'm a tranny" or "fellow trannies".
        """
        # Build patterns that check for hateful words preceding the slur
        for hateful_pattern in HATEFUL_CONTEXT_PATTERNS:
            # Pattern: hateful context followed by the slur
            full_pattern = hateful_pattern + re.escape(slur) + r'\b'
            if re.search(full_pattern, content, re.IGNORECASE):
                return True

        # Additional check: slur followed by derogatory descriptors
        derogatory_after = [
            r'\b' + re.escape(slur) + r's?\s+(are|is)\s+(disgusting|gross|sick|evil|wrong|bad|mentally\s+ill)',
            r'\b' + re.escape(slur) + r's?\s+should\s+(die|be\s+killed|not\s+exist)',
            r'\b' + re.escape(slur) + r's?\s+deserve\s+(to\s+die|death|nothing)',
        ]
        for pattern in derogatory_after:
            if re.search(pattern, content, re.IGNORECASE):
                return True

        return False

    def _is_hate_combination(self, content: str) -> Tuple[bool, List[str]]:
        """
        Check for hate verb + protected group combinations.
        Returns (is_hate, list_of_matched_phrases).

        Detects patterns like:
        - "kill the jews", "murder all muslims"
        - "everyone hates jews", "we all hate blacks"
        - "admitted hate for jews"
        - "jews should die", "whites must be killed"
        """
        matches = []
        content_lower = content.lower()

        # Build group pattern (handles multi-word groups like "white man")
        # Sort by length descending so "white man" matches before "white"
        sorted_groups = sorted(PROTECTED_GROUPS, key=len, reverse=True)
        group_pattern = '|'.join(re.escape(g) for g in sorted_groups)

        # Build verb pattern
        verb_pattern = '|'.join(re.escape(v) for v in HATE_ACTION_VERBS)

        # Pattern 1: [verb] (the|all|those|these|every)? [group]
        # e.g., "kill the jews", "murder all muslims", "hate blacks"
        pattern1 = rf'\b({verb_pattern})\s+(the\s+|all\s+|those\s+|these\s+|every\s+)?({group_pattern})\b'
        for match in re.finditer(pattern1, content_lower):
            matches.append(match.group(0))

        # Pattern 2: (everyone|we|all|people) (here)? [hate verb] [group]
        # e.g., "everyone here hates jews", "we all hate muslims"
        pattern2 = rf'\b(everyone|we|all|people)\s+(here\s+)?({verb_pattern})\s+(the\s+)?({group_pattern})\b'
        for match in re.finditer(pattern2, content_lower):
            matches.append(match.group(0))

        # Pattern 3: [group] (should|must|need to|deserve to|gonna|will) (die|be killed|be eliminated)
        # e.g., "jews should die", "blacks must be killed"
        pattern3 = rf'\b({group_pattern})\s+(should|must|need\s+to|deserve\s+to|gonna|will)\s+(die|be\s+killed|be\s+eliminated|be\s+exterminated)\b'
        for match in re.finditer(pattern3, content_lower):
            matches.append(match.group(0))

        # Pattern 4: (admitted|confessed|expressed) [hate verb] (for|of|towards)? [group]
        # e.g., "admitted hate for jews", "confessed hatred of muslims"
        pattern4 = rf'\b(admitted|confessed|expressed)\s+(hate|hatred|hating|loathing)\s+(for\s+|of\s+|towards\s+)?({group_pattern})\b'
        for match in re.finditer(pattern4, content_lower):
            matches.append(match.group(0))

        # Pattern 5: [hate verb] (for|of|towards) [group]
        # e.g., "hate for jews", "hatred of muslims"
        pattern5 = rf'\b({verb_pattern})\s+(for|of|towards)\s+(the\s+)?({group_pattern})\b'
        for match in re.finditer(pattern5, content_lower):
            matches.append(match.group(0))

        return (len(matches) > 0, matches)

    def _analyze_sentiment(self, content: str) -> float:
        """Analyze sentiment using VADER. Returns -1 to 1."""
        if not SENTIMENT_AVAILABLE or not sentiment_analyzer:
            return 0.0
        
        try:
            scores = sentiment_analyzer.polarity_scores(content)
            return scores['compound']
        except:
            return 0.0
    
    def _is_repeat_offender(self, author_id: str) -> bool:
        """Check if user has multiple recent offenses."""
        if MDB_AVAILABLE:
            try:
                count = mdb.get_user_offense_count(author_id, hours=24)
                return count >= OFFENSES_BEFORE_TIMEOUT
            except:
                pass
        
        # Fallback to in-memory cache
        if author_id in user_offenses_cache:
            recent = [t for t in user_offenses_cache[author_id] 
                     if datetime.now() - t < timedelta(hours=24)]
            return len(recent) >= OFFENSES_BEFORE_TIMEOUT
        
        return False
    
    def _homoglyph_replace(self, text: str, num_replacements=1):
        """
        Replace characters with visually identical homoglyphs.
        - Prioritizes characters with the most similar homoglyphs
        - Replaces ALL instances of chosen character(s) in the word
        """
        # Find unique replaceable characters in the text
        replaceable_chars = set(c for c in text if c in HOMOGLYPHS)
        
        if not replaceable_chars:
            return text
        
        # Sort by priority (lowest = best visual match), then shuffle within same priority
        sorted_chars = sorted(replaceable_chars, key=lambda c: (PRIORITY.get(c, 99), random.random()))
        
        # Pick the top N characters to replace
        chars_to_replace = sorted_chars[:num_replacements]
        
        result = text
        
        for char in chars_to_replace:
            replacement = HOMOGLYPHS[char][0]  # Best homoglyph is first
            result = result.replace(char, replacement)
        
        return result

    def _censor_content(self, content: str, matched_words: List[str]) -> str:
        """Censor matched bad words in the content."""
        censored = content
        
        for word in matched_words:
            pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
            censored_word = self._homoglyph_replace(word)
            censored = pattern.sub(censored_word, censored)
        
        # Also censor pattern matches
        for compiled_pattern, _ in self.compiled_patterns:
            match = compiled_pattern.search(censored)
            if match:
                matched_text = match.group(0)
                censored_text = self._homoglyph_replace(matched_text)
                censored = censored.replace(matched_text, censored_text)
        
        return censored


# Global analyzer instance
analyzer = ContentAnalyzer()


# ============== MODERATION FUNCTIONS ==============

def log_flagged_message(
    message_id: str,
    channel_id: str,
    channel_name: str,
    author_id: str,
    author_name: str,
    original_content: str,
    censored_content: str,
    result: AnalysisResult
):
    """Log a flagged message to database or cache."""
    record = {
        'message_id': message_id,
        'channel_id': channel_id,
        'channel_name': channel_name,
        'author_id': author_id,
        'author_name': author_name,
        'original_content': original_content,
        'censored_content': censored_content,
        'reasons': result.reasons,
        'matched_words': result.matched_words,
        'severity': result.severity,
        'timestamp': datetime.now().isoformat()
    }
    
    if MDB_AVAILABLE:
        try:
            mdb.log_flagged_message(
                message_id=message_id,
                channel_id=channel_id,
                channel_name=channel_name,
                author_id=author_id,
                author_name=author_name,
                original_content=original_content,
                censored_content=censored_content,
                flag_reason=','.join(result.reasons),
                matched_patterns=result.matched_words,
                sentiment_score=result.sentiment_score,
                toxicity_score=result.severity / 5.0,
                action_taken='deleted' if result.should_delete else 'flagged',
                auto_deleted=result.should_delete
            )
        except Exception as e:
            logger.error(f"Database logging failed: {e}")
    
    # Always cache in memory too
    flagged_messages_cache[message_id] = record


def log_user_offense(author_id: str, reason: str):
    """Track user offense for repeat offender detection."""
    if MDB_AVAILABLE:
        try:
            mdb.log_user_offense(author_id, reason, '', '')
        except:
            pass
    
    # Also track in memory
    if author_id not in user_offenses_cache:
        user_offenses_cache[author_id] = []
    user_offenses_cache[author_id].append(datetime.now())
    
    # Cleanup old offenses
    user_offenses_cache[author_id] = [
        t for t in user_offenses_cache[author_id]
        if datetime.now() - t < timedelta(days=7)
    ]


# ============== HISTORICAL SCANNING ==============

def scan_export_file(json_path: str, bad_words: List[str] = None) -> List[dict]:
    """
    Scan a Discord export JSON file for messages containing bad words.
    
    Returns list of flagged message records.
    """
    flagged = []
    words_to_check = bad_words or (BAD_WORDS_CRITICAL + BAD_WORDS_MODERATE)
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Error loading {json_path}: {e}")
        return flagged
    
    messages = data.get('messages', [])
    channel_name = data.get('channel', {}).get('name', 'unknown')
    
    for msg in messages:
        content = msg.get('content', '')
        if not content:
            continue
        
        # Run full analysis
        result = analyzer.analyze(content)
        
        if result.is_flagged:
            author = msg.get('author', {})
            flagged.append({
                'message_id': msg.get('id', ''),
                'channel_id': data.get('channel', {}).get('id', ''),
                'channel_name': channel_name,
                'author_id': author.get('id', ''),
                'author_name': author.get('name', 'Unknown'),
                'content': content,
                'censored_content': result.censored_content,
                'timestamp': msg.get('timestamp', ''),
                'reasons': result.reasons,
                'matched_words': result.matched_words,
                'severity': result.severity
            })
    
    return flagged


def scan_all_exports(export_dir: str = EXPORT_DIR, output_file: str = "flagged_messages.json") -> dict:
    """
    Scan all Discord export files in a directory.
    
    Returns summary statistics and saves flagged messages to file.
    """
    export_path = Path(export_dir)
    if not export_path.exists():
        logger.error(f"Export directory not found: {export_dir}")
        return {"error": "Directory not found"}
    
    json_files = list(export_path.rglob("*.json"))
    logger.info(f"Found {len(json_files)} JSON files to scan")
    
    all_flagged = []
    total_messages = 0
    
    for json_file in json_files:
        logger.info(f"Scanning {json_file.name}...")
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            total_messages += len(data.get('messages', []))
            flagged = scan_export_file(str(json_file))
            all_flagged.extend(flagged)
        except Exception as e:
            logger.error(f"Error scanning {json_file}: {e}")
    
    # Save results
    results = {
        'scan_time': datetime.now().isoformat(),
        'total_files_scanned': len(json_files),
        'total_messages_scanned': total_messages,
        'total_flagged': len(all_flagged),
        'flagged_messages': all_flagged
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Scan complete: {len(all_flagged)} flagged out of {total_messages} messages")
    logger.info(f"Results saved to {output_file}")
    
    return results


# ============== STREAMING SCANNER (Memory-Efficient) ==============

def scan_export_file_streaming(
    json_path: str,
    json_output_file=None,
    batch_size: int = 10000
) -> dict:
    """
    Stream-scan a Discord export JSON file.
    Writes flagged messages to both SQLite and optional JSON file.
    Memory usage: ~50-100MB regardless of file size.

    Args:
        json_path: Path to the Discord export JSON file
        json_output_file: Optional file handle to write flagged messages as JSON
        batch_size: How often to log progress (default 10000 messages)

    Returns:
        dict with stats: scanned, flagged, channel_id, channel_name
    """
    if not IJSON_AVAILABLE:
        logger.error("ijson not installed. Run 'pip install ijson'")
        return {'error': 'ijson not installed', 'scanned': 0, 'flagged': 0}

    stats = {
        'scanned': 0,
        'flagged': 0,
        'channel_id': '',
        'channel_name': 'unknown',
        'file_path': json_path
    }

    try:
        with open(json_path, 'rb') as f:
            # Extract channel metadata first (at top of file)
            parser = ijson.parse(f)
            for prefix, event, value in parser:
                if prefix == 'channel.name':
                    stats['channel_name'] = value
                elif prefix == 'channel.id':
                    stats['channel_id'] = value
                elif prefix == 'messages':
                    break

            # Reset and stream messages
            f.seek(0)
            messages = ijson.items(f, 'messages.item')

            for msg in messages:
                stats['scanned'] += 1
                content = msg.get('content', '')

                if not content or not content.strip():
                    continue

                author = msg.get('author', {})
                author_id = author.get('id', '')

                # Skip bot messages
                if author.get('isBot', False):
                    continue

                # Analyze content
                result = analyzer.analyze(content, author_id)

                if result.is_flagged:
                    stats['flagged'] += 1

                    flagged_record = {
                        'message_id': msg.get('id', ''),
                        'channel_id': stats['channel_id'],
                        'channel_name': stats['channel_name'],
                        'author_id': author_id,
                        'author_name': author.get('name', 'Unknown'),
                        'content': content,
                        'censored_content': result.censored_content,
                        'timestamp': msg.get('timestamp', ''),
                        'reasons': result.reasons,
                        'matched_words': result.matched_words,
                        'severity': result.severity
                    }

                    # Write to SQLite
                    if MDB_AVAILABLE:
                        try:
                            mdb.log_flagged_message(
                                message_id=flagged_record['message_id'],
                                channel_id=flagged_record['channel_id'],
                                channel_name=flagged_record['channel_name'],
                                author_id=flagged_record['author_id'],
                                author_name=flagged_record['author_name'],
                                original_content=content,
                                censored_content=result.censored_content,
                                flag_reason=','.join(result.reasons),
                                matched_patterns=result.matched_words,
                                sentiment_score=result.sentiment_score,
                                toxicity_score=result.severity / 5.0,
                                action_taken='flagged',
                                auto_deleted=False
                            )
                        except Exception as db_err:
                            logger.warning(f"DB write failed for message {flagged_record['message_id']}: {db_err}")

                    # Write to JSON file (streaming)
                    if json_output_file:
                        json_output_file.write(json.dumps(flagged_record, ensure_ascii=False))
                        json_output_file.write(',\n')

                # Progress update
                if stats['scanned'] % batch_size == 0:
                    logger.info(f"  [{stats['channel_name']}] {stats['scanned']:,} scanned, {stats['flagged']:,} flagged")

    except Exception as e:
        logger.error(f"Error scanning {json_path}: {e}")
        stats['error'] = str(e)

    return stats


def scan_all_exports_streaming(
    export_dir: str = EXPORT_DIR,
    output_file: str = "flagged_messages.json",
    batch_size: int = 10000
) -> dict:
    """
    Stream-scan all Discord export files.
    Outputs to both SQLite database and JSON file.
    Memory-efficient: processes files one message at a time.

    Args:
        export_dir: Directory containing Discord export JSON files
        output_file: Path to output JSON file for flagged messages
        batch_size: How often to log progress per file

    Returns:
        dict with summary stats
    """
    if not IJSON_AVAILABLE:
        logger.error("ijson not installed. Run 'pip install ijson' for streaming support.")
        return {"error": "ijson not installed"}

    export_path = Path(export_dir)
    if not export_path.exists():
        logger.error(f"Export directory not found: {export_dir}")
        return {"error": "Directory not found"}

    json_files = list(export_path.rglob("*.json"))

    if not json_files:
        logger.warning(f"No JSON files found in {export_dir}")
        return {"error": "No JSON files found"}

    # Sort by file size (smallest first for quick progress)
    json_files.sort(key=lambda p: p.stat().st_size)

    logger.info(f"Found {len(json_files)} JSON files to scan (streaming mode)")
    total_size_gb = sum(f.stat().st_size for f in json_files) / (1024**3)
    logger.info(f"Total size: {total_size_gb:.2f} GB")

    total_scanned = 0
    total_flagged = 0
    file_stats = []
    first_record = True

    # Open JSON output file for streaming writes
    with open(output_file, 'w', encoding='utf-8') as json_out:
        # Write JSON array opening
        json_out.write('{"flagged_messages": [\n')

        for i, json_file in enumerate(json_files, 1):
            file_size_mb = json_file.stat().st_size / (1024 * 1024)
            logger.info(f"[{i}/{len(json_files)}] Scanning {json_file.name} ({file_size_mb:.1f} MB)...")

            # Create a wrapper to handle comma insertion
            class JsonStreamWriter:
                def __init__(self, file_handle, is_first):
                    self.fh = file_handle
                    self.is_first = is_first
                    self.wrote_any = False

                def write(self, data):
                    if data.endswith(',\n'):
                        if not self.is_first and not self.wrote_any:
                            # Not first file and first record in this file - no comma needed before
                            pass
                        self.fh.write(data)
                        self.wrote_any = True
                    else:
                        self.fh.write(data)

            stats = scan_export_file_streaming(
                str(json_file),
                json_output_file=json_out,
                batch_size=batch_size
            )

            if stats.get('flagged', 0) > 0:
                first_record = False

            total_scanned += stats.get('scanned', 0)
            total_flagged += stats.get('flagged', 0)
            file_stats.append({
                'file': json_file.name,
                'scanned': stats.get('scanned', 0),
                'flagged': stats.get('flagged', 0),
                'channel': stats.get('channel_name', 'unknown')
            })

            logger.info(f"  Done: {stats.get('scanned', 0):,} messages, {stats.get('flagged', 0):,} flagged")

        # Handle the trailing comma issue
        # If we wrote any flagged messages, remove the trailing ',\n'
        if total_flagged > 0:
            pos = json_out.tell()
            json_out.seek(pos - 2)  # Go back 2 chars to remove ',\n'
            json_out.truncate()
            json_out.write('\n],\n')
        else:
            # No flagged messages, just close the empty array
            json_out.write('],\n')

        # Write summary
        summary = {
            'scan_time': datetime.now().isoformat(),
            'total_files_scanned': len(json_files),
            'total_messages_scanned': total_scanned,
            'total_flagged': total_flagged,
            'streaming_mode': True
        }
        json_out.write(f'"summary": {json.dumps(summary)}\n}}')

    logger.info(f"Scan complete: {total_flagged:,} flagged out of {total_scanned:,} messages")
    logger.info(f"Results saved to {output_file} and moderation.db")

    return {
        **summary,
        'file_stats': file_stats
    }


# ============== EVENT HANDLERS ==============

@listen()
async def on_ready():
    """Called when the bot is ready."""
    logger.info(f"Logged in as {client.user.display_name} (ID: {client.user.id})")
    logger.info(f"Monitoring {len(MONITORED_CHANNELS)} channels")
    logger.info(f"Blocking {len(BLOCKED_CHANNELS)} channels")
    logger.info(f"Critical words: {len(BAD_WORDS_CRITICAL)}")
    logger.info(f"Moderate words: {len(BAD_WORDS_MODERATE)}")
    logger.info(f"Reclaimed slurs (context-aware): {len(SLUR_WORDS_MODERATE)}")
    logger.info(f"ToS patterns: {len(TOS_VIOLATION_PATTERNS)}")

    # Initialize moderation database if available
    if MDB_AVAILABLE:
        try:
            mdb.init_moderation_db()
            # Sync bad words to database
            mdb.add_bad_words_bulk(BAD_WORDS_CRITICAL, severity=5, category='critical')
            mdb.add_bad_words_bulk(BAD_WORDS_MODERATE, severity=3, category='moderate')
            mdb.add_bad_words_bulk(SLUR_WORDS_MODERATE, severity=3, category='slur_contextual')
            logger.info("Moderation database initialized")
        except Exception as e:
            logger.error(f"Database init failed: {e}")


@listen()
async def on_message_create(event: MessageCreate):
    """Handle incoming messages - main live monitoring."""
    global MONITORING_ENABLED
    
    message = event.message
    
    # Skip if monitoring is disabled
    if not MONITORING_ENABLED:
        return
    
    # Skip bot messages
    if message.author.bot:
        return
    
    # Skip empty messages
    if not message.content or not message.content.strip():
        return
    
    # Skip blocked channels
    if message.channel.id in BLOCKED_CHANNELS:
        return
    
    # Skip if not in monitored channels (when list is defined)
    if MONITORED_CHANNELS and message.channel.id not in MONITORED_CHANNELS:
        return
    
    # Skip if recently processed
    msg_id = str(message.id)
    if msg_id in recently_processed:
        return
    recently_processed.add(msg_id)
    
    # Cleanup old processed messages
    if len(recently_processed) > 1000:
        recently_processed.clear()
    
    # Analyze the message
    result = analyzer.analyze(message.content, str(message.author.id))
    
    if not result.is_flagged:
        return
    
    logger.info(f"Flagged message from {message.author.display_name}: severity={result.severity}, reasons={result.reasons}")
    
    # Log to database/cache
    log_flagged_message(
        message_id=msg_id,
        channel_id=str(message.channel.id),
        channel_name=getattr(message.channel, 'name', 'Unknown'),
        author_id=str(message.author.id),
        author_name=str(message.author.display_name),
        original_content=message.content,
        censored_content=result.censored_content,
        result=result
    )
    
    # Log user offense
    log_user_offense(str(message.author.id), result.reasons[0] if result.reasons else 'unknown')
    
    # Take action if should delete
    if result.should_delete:
        # Store info before deletion
        channel = message.channel
        author_name = str(message.author.display_name)
        author_avatar = message.author.avatar_url
        author_id = message.author.id
        author_mention = f"<@{author_id}>"
        censored = result.censored_content
        
        try:
            # Delete the original message
            await message.delete()
            logger.info(f"Deleted message {message.id} from {author_name}")
            
            # Repost censored version with "user said:" prefix
            if censored and censored.strip() and censored != message.content:                
                await channel.send(f"**{author_mention}**\n{censored}")
            
            # Auto-timeout if needed
            if AUTO_TIMEOUT_ENABLED and result.should_timeout:
                try:
                    timeout_until = datetime.now() + timedelta(seconds=AUTO_TIMEOUT_DURATION)
                    guild = client.get_guild(GUILD_ID)
                    member = guild.get_member(author_id)
                    if member:
                        await member.timeout(timeout_until)
                        logger.info(f"Auto-timed out {author_name} for {AUTO_TIMEOUT_DURATION}s")
                except Exception as e:
                    logger.error(f"Timeout failed: {e}")
            
            # Log to mod channel
            await log_to_mod_channel(message, result, deleted=True)
            
        except Exception as e:
            logger.error(f"Error handling flagged message: {e}")
    else:
        # Just log, don't delete
        await log_to_mod_channel(message, result, deleted=False)


async def log_to_mod_channel(message, result: AnalysisResult, deleted: bool):
    """Send moderation action to mod log channel."""
    try:
        mod_channel = client.get_channel(MOD_LOG_CHANNEL_ID)
        if not mod_channel:
            return
        
        color = 0xff0000 if deleted else 0xffaa00
        
        embed = Embed(
            title="🚨 Auto-Moderation" if deleted else "⚠️ Content Flagged",
            color=color,
            timestamp=datetime.now()
        )
        
        embed.set_author(
            name=str(message.author.display_name),
            icon_url=message.author.avatar_url
        )
        
        embed.add_field(name="Channel", value=f"<#{message.channel.id}>", inline=True)
        embed.add_field(name="Severity", value=f"{result.severity}/5", inline=True)
        embed.add_field(name="Action", value="Deleted & Censored" if deleted else "Flagged Only", inline=True)
        embed.add_field(name="Reasons", value=', '.join(result.reasons[:5]) or "None", inline=False)
        embed.add_field(name="Content", value=f"||{message.content[:500]}||", inline=False)
        
        if result.matched_words:
            embed.add_field(name="Matched Words", value=', '.join(result.matched_words[:10]), inline=False)
        
        await mod_channel.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Failed to log to mod channel: {e}")


# ============== SLASH COMMANDS ==============

def has_permission(ctx: SlashContext) -> bool:
    """Check if user has admin """
    return ctx.author.has_role(ADMIN_ROLE_ID) or ctx.author.has_role(SUPPORT_ROLE_ID)


@slash_command(name="tos_scan", description="Scan historical messages from Discord exports.", scopes=[GUILD_ID])
@slash_option(name="preview", description="Only preview, don't save results", required=False, opt_type=OptionType.BOOLEAN)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def tos_scan_cmd(ctx: SlashContext, preview: bool = False):
    """Scan Discord exports for ToS violations."""
    if not has_permission(ctx):
        await ctx.send("❌ Permission denied.", ephemeral=True)
        return
    
    await ctx.send("🔍 Starting scan of Discord exports... This may take a few minutes.", ephemeral=True)
    
    # Run scan in a thread pool to avoid blocking the event loop / heartbeat
    import concurrent.futures
    loop = asyncio.get_event_loop()
    
    with concurrent.futures.ThreadPoolExecutor() as pool:
        results = await loop.run_in_executor(pool, scan_all_exports)
    
    if 'error' in results:
        await ctx.send(f"❌ Error: {results['error']}", ephemeral=True)
        return
    
    embed = Embed(title="📊 ToS Scan Complete", color=0x9c92d1)
    embed.add_field(name="Files Scanned", value=str(results['total_files_scanned']), inline=True)
    embed.add_field(name="Messages Scanned", value=f"{results['total_messages_scanned']:,}", inline=True)
    embed.add_field(name="Flagged", value=f"{results['total_flagged']:,}", inline=True)
    
    if results['total_flagged'] > 0:
        # Group by severity
        by_severity = {}
        for msg in results['flagged_messages']:
            sev = msg.get('severity', 0)
            by_severity[sev] = by_severity.get(sev, 0) + 1
        
        severity_text = "\n".join([f"Severity {s}: {c}" for s, c in sorted(by_severity.items(), reverse=True)])
        embed.add_field(name="By Severity", value=severity_text or "N/A", inline=False)
    
    embed.set_footer(text=f"Results saved to flagged_messages.json")
    
    await ctx.send(embed=embed, ephemeral=True)


@slash_command(name="tos_purge", description="Delete flagged messages from scan results.", scopes=[GUILD_ID])
@slash_option(name="confirm", description="Type DELETE to confirm", required=True, opt_type=OptionType.STRING)
@slash_option(name="min_severity", description="Minimum severity to delete (1-5)", required=False, opt_type=OptionType.INTEGER)
@slash_option(name="dry_run", description="Count only, don't delete", required=False, opt_type=OptionType.BOOLEAN)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def tos_purge_cmd(ctx: SlashContext, confirm: str, min_severity: int = 3, dry_run: bool = False):
    """Delete flagged messages from scan results."""
    if not has_permission(ctx):
        await ctx.send("❌ Permission denied.", ephemeral=True)
        return
    
    if confirm != "DELETE":
        await ctx.send("❌ You must type `DELETE` to confirm.", ephemeral=True)
        return
    
    # Load flagged messages
    flagged_path = Path("flagged_messages.json")
    if not flagged_path.exists():
        await ctx.send("❌ No scan results found. Run `/tos_scan` first.", ephemeral=True)
        return
    
    with open(flagged_path, 'r') as f:
        data = json.load(f)
    
    messages = [m for m in data.get('flagged_messages', []) if m.get('severity', 0) >= min_severity]
    
    if not messages:
        await ctx.send(f"✅ No messages with severity >= {min_severity} to delete.", ephemeral=True)
        return
    
    if dry_run:
        await ctx.send(f"🔍 **Dry Run**: Would delete {len(messages)} messages with severity >= {min_severity}", ephemeral=False)
        return
    
    status_msg = await ctx.send(f"🗑️ Deleting {len(messages)} flagged messages...")
    
    deleted = 0
    failed = 0
    
    # Group by channel for efficiency
    by_channel = {}
    for msg in messages:
        ch_id = msg['channel_id']
        if ch_id not in by_channel:
            by_channel[ch_id] = []
        by_channel[ch_id].append(msg['message_id'])
    
    for channel_id, msg_ids in by_channel.items():
        try:
            channel = client.get_channel(int(channel_id))
            if not channel:
                failed += len(msg_ids)
                continue
            
            for msg_id in msg_ids:
                try:
                    message = await channel.fetch_message(int(msg_id))
                    await message.delete()
                    deleted += 1
                    
                    if deleted % 5 == 0:
                        await asyncio.sleep(1)  # Rate limiting
                    
                    if deleted % 50 == 0:
                        await status_msg.edit(content=f"🗑️ Progress: {deleted}/{len(messages)} deleted...")
                        
                except interactions.errors.NotFound:
                    deleted += 1  # Already deleted
                except Exception as e:
                    logger.error(f"Failed to delete {msg_id}: {e}")
                    failed += 1
                    
        except Exception as e:
            logger.error(f"Error with channel {channel_id}: {e}")
            failed += len(msg_ids)
    
    embed = Embed(title="🗑️ Purge Complete", color=0x00ff00 if failed == 0 else 0xffaa00)
    embed.add_field(name="Deleted", value=str(deleted), inline=True)
    embed.add_field(name="Failed", value=str(failed), inline=True)
    embed.add_field(name="Min Severity", value=str(min_severity), inline=True)
    
    await status_msg.edit(content="", embed=embed)
    
    # Log to mod channel
    mod_channel = client.get_channel(MOD_LOG_CHANNEL_ID)
    if mod_channel:
        await mod_channel.send(f"📋 {ctx.author.mention} purged {deleted} flagged messages (severity >= {min_severity})")


@slash_command(name="tos_stats", description="View moderation statistics.", scopes=[GUILD_ID])
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def tos_stats_cmd(ctx: SlashContext):
    """View moderation statistics."""
    if not has_permission(ctx):
        await ctx.send("❌ Permission denied.", ephemeral=True)
        return
    
    embed = Embed(title="📊 Moderation Stats", color=0x9c92d1)
    
    # In-memory stats
    embed.add_field(name="Flagged (Session)", value=str(len(flagged_messages_cache)), inline=True)
    
    # User offense counts
    active_offenders = sum(1 for offenses in user_offenses_cache.values() if len(offenses) >= 2)
    embed.add_field(name="Active Offenders", value=str(active_offenders), inline=True)
    
    # Database stats if available
    if MDB_AVAILABLE:
        try:
            db_stats = mdb.get_moderation_stats(days=7)
            embed.add_field(name="Flagged (7 Days)", value=str(db_stats.get('total_flagged', 0)), inline=True)
            
            if db_stats.get('top_triggered_words'):
                words = [f"`{w['word']}`: {w['match_count']}" for w in db_stats['top_triggered_words'][:5]]
                embed.add_field(name="Top Triggers", value="\n".join(words) or "None", inline=False)
        except:
            pass
    
    # Config summary
    embed.add_field(
        name="Configuration",
        value=f"Critical words: {len(BAD_WORDS_CRITICAL)}\n"
              f"Moderate words: {len(BAD_WORDS_MODERATE)}\n"
              f"Reclaimed slurs: {len(SLUR_WORDS_MODERATE)}\n"
              f"ToS patterns: {len(TOS_VIOLATION_PATTERNS)}\n"
              f"Learned phrases: {len(analyzer.learned_phrases)}",
        inline=False
    )

    await ctx.send(embed=embed, ephemeral=True)


@slash_command(name="tos_test", description="Test a message against the ToS filter.", scopes=[GUILD_ID])
@slash_option(name="message", description="Message to test", required=True, opt_type=OptionType.STRING)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def tos_test_cmd(ctx: SlashContext, message: str):
    """Test a message against the ToS filter."""
    if not has_permission(ctx):
        await ctx.send("❌ Permission denied.", ephemeral=True)
        return
    
    result = analyzer.analyze(message)
    
    status = "🚨 WOULD DELETE" if result.should_delete else ("⚠️ FLAGGED" if result.is_flagged else "✅ CLEAN")
    
    embed = Embed(title=f"ToS Test: {status}", color=0xff0000 if result.should_delete else (0xffaa00 if result.is_flagged else 0x00ff00))
    embed.add_field(name="Severity", value=f"{result.severity}/5", inline=True)
    embed.add_field(name="Would Delete", value="Yes" if result.should_delete else "No", inline=True)
    embed.add_field(name="Would Timeout", value="Yes" if result.should_timeout else "No", inline=True)
    
    if result.reasons:
        embed.add_field(name="Reasons", value=', '.join(result.reasons), inline=False)
    
    if result.matched_words:
        embed.add_field(name="Matched Words", value=', '.join(result.matched_words), inline=False)
    
    if result.matched_patterns:
        patterns = [f"{cat}: `{pat[:30]}...`" for pat, cat in result.matched_patterns[:5]]
        embed.add_field(name="Matched Patterns", value='\n'.join(patterns), inline=False)
    
    embed.add_field(name="Censored Version", value=f"||{result.censored_content}||", inline=False)
    embed.add_field(name="Sentiment", value=f"{result.sentiment_score:.2f}", inline=True)
    
    await ctx.send(embed=embed, ephemeral=True)


@slash_command(name="tos_addword", description="Add a word to the bad words list.", scopes=[GUILD_ID])
@slash_option(name="word", description="Word to add", required=True, opt_type=OptionType.STRING)
@slash_option(name="severity", description="critical (5) or moderate (3)", required=False, opt_type=OptionType.STRING,
              choices=[SlashCommandChoice(name="critical", value="critical"), SlashCommandChoice(name="moderate", value="moderate")])
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def tos_addword_cmd(ctx: SlashContext, word: str, severity: str = "moderate"):
    """Add a word to the filter."""
    if not has_permission(ctx):
        await ctx.send("❌ Permission denied.", ephemeral=True)
        return
    
    word = word.lower().strip()
    
    if severity == "critical":
        if word not in BAD_WORDS_CRITICAL:
            BAD_WORDS_CRITICAL.append(word)
        sev_num = 5
    else:
        if word not in BAD_WORDS_MODERATE:
            BAD_WORDS_MODERATE.append(word)
        sev_num = 3
    
    # Also add to database if available
    if MDB_AVAILABLE:
        try:
            mdb.add_bad_word(word, sev_num, severity)
        except:
            pass
    
    await ctx.send(f"✅ Added `{word}` to {severity} list (severity {sev_num})", ephemeral=True)


@slash_command(name="tos_monitor_on", description="Enable live message monitoring.", scopes=[GUILD_ID])
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def tos_monitor_on_cmd(ctx: SlashContext):
    """Enable live monitoring."""
    global MONITORING_ENABLED
    
    if not ctx.author.has_role(ADMIN_ROLE_ID):
        await ctx.send("❌ Permission denied.", ephemeral=True)
        return
    
    if MONITORING_ENABLED:
        await ctx.send("ℹ️ Live monitoring is already **enabled**.", ephemeral=False)
        return
    
    MONITORING_ENABLED = True
    logger.info(f"Live monitoring ENABLED by {ctx.author.display_name}")
    
    await ctx.send("✅ Live monitoring is now **enabled**. Messages will be scanned and moderated.", ephemeral=False)
    
    # Log to mod channel
    mod_channel = client.get_channel(MOD_LOG_CHANNEL_ID)
    if mod_channel:
        embed = Embed(
            title="🟢 Live Monitoring Enabled",
            description=f"Enabled by {ctx.author.mention}",
            color=0x00ff00,
            timestamp=datetime.now()
        )
        embed.add_field(name="Monitored Channels", value=str(len(MONITORED_CHANNELS)), inline=True)
        await mod_channel.send(embed=embed)


@slash_command(name="tos_monitor_off", description="Disable live message monitoring.", scopes=[GUILD_ID])
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def tos_monitor_off_cmd(ctx: SlashContext):
    """Disable live monitoring."""
    global MONITORING_ENABLED
    
    if not ctx.author.has_role(ADMIN_ROLE_ID):
        await ctx.send("❌ Permission denied.", ephemeral=True)
        return
    
    if not MONITORING_ENABLED:
        await ctx.send("ℹ️ Live monitoring is already **disabled**.", ephemeral=False)
        return
    
    MONITORING_ENABLED = False
    logger.info(f"Live monitoring DISABLED by {ctx.author.display_name}")
    
    await ctx.send("🔴 Live monitoring is now **disabled**. Messages will NOT be moderated.", ephemeral=False)
    
    # Log to mod channel
    mod_channel = client.get_channel(MOD_LOG_CHANNEL_ID)
    if mod_channel:
        embed = Embed(
            title="🔴 Live Monitoring Disabled",
            description=f"Disabled by {ctx.author.mention}",
            color=0xff0000,
            timestamp=datetime.now()
        )
        await mod_channel.send(embed=embed)


@slash_command(name="tos_status", description="Check the current monitoring status.", scopes=[GUILD_ID])
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def tos_status_cmd(ctx: SlashContext):
    """Check monitoring status."""
    if not has_permission(ctx):
        await ctx.send("❌ Permission denied.", ephemeral=True)
        return
    
    status_emoji = "🟢" if MONITORING_ENABLED else "🔴"
    status_text = "ENABLED" if MONITORING_ENABLED else "DISABLED"
    
    embed = Embed(
        title=f"{status_emoji} Monitoring Status: {status_text}",
        color=0x00ff00 if MONITORING_ENABLED else 0xff0000
    )
    
    embed.add_field(name="Live Monitoring", value=status_text, inline=True)
    embed.add_field(name="Monitored Channels", value=str(len(MONITORED_CHANNELS)), inline=True)
    embed.add_field(name="Blocked Channels", value=str(len(BLOCKED_CHANNELS)), inline=True)
    
    embed.add_field(
        name="Filter Configuration",
        value=f"Critical words: {len(BAD_WORDS_CRITICAL)}\n"
              f"Moderate words: {len(BAD_WORDS_MODERATE)}\n"
              f"Reclaimed slurs: {len(SLUR_WORDS_MODERATE)}\n"
              f"ToS patterns: {len(TOS_VIOLATION_PATTERNS)}\n"
              f"Learned phrases: {len(analyzer.learned_phrases)}",
        inline=False
    )

    embed.add_field(
        name="Session Stats",
        value=f"Flagged this session: {len(flagged_messages_cache)}\n"
              f"Active offenders: {sum(1 for o in user_offenses_cache.values() if len(o) >= 2)}",
        inline=False
    )
    
    await ctx.send(embed=embed, ephemeral=True)


# ============== RUN ==============

def run_cli_scan():
    """Run a scan from command line without starting the bot."""
    print("=" * 60)
    print("ToS SCANNER - Streaming Mode")
    print("=" * 60)

    # Check for ijson
    if not IJSON_AVAILABLE:
        print("❌ Error: ijson not installed")
        print("   Run: pip install ijson")
        return

    # Initialize database
    if MDB_AVAILABLE:
        mdb.init_moderation_db()
        print("✅ Database initialized")
    else:
        print("⚠️  Database module not available - using JSON output only")

    # Import training samples if analytics DB exists
    analytics_db = Path("discord_analytics.db")
    if MDB_AVAILABLE and analytics_db.exists():
        print(f"\n📚 Importing training samples from {analytics_db}...")
        all_words = BAD_WORDS_CRITICAL + BAD_WORDS_MODERATE
        try:
            imported = mdb.import_training_samples_from_analytics(all_words)
            print(f"   Imported {imported} training samples")
        except Exception as e:
            print(f"   Warning: Could not import training samples: {e}")
    elif analytics_db.exists():
        print(f"ℹ️  Found {analytics_db} but database module not available")

    print(f"\n🔍 Starting streaming scan...")
    print(f"   Export directory: {EXPORT_DIR}")
    print(f"   Critical words: {len(BAD_WORDS_CRITICAL)}")
    print(f"   Moderate words: {len(BAD_WORDS_MODERATE)}")
    print(f"   ToS patterns: {len(TOS_VIOLATION_PATTERNS)}")
    print()

    results = scan_all_exports_streaming()

    if 'error' in results:
        print(f"❌ Error: {results['error']}")
        return

    print(f"\n{'=' * 60}")
    print(f"📊 Scan Complete!")
    print(f"   Files scanned: {results['total_files_scanned']}")
    print(f"   Messages scanned: {results['total_messages_scanned']:,}")
    print(f"   Flagged: {results['total_flagged']:,}")

    # Show per-file breakdown if there are multiple files
    if 'file_stats' in results and len(results['file_stats']) > 1:
        print(f"\n   Per-channel breakdown:")
        for fs in sorted(results['file_stats'], key=lambda x: x['flagged'], reverse=True)[:10]:
            if fs['flagged'] > 0:
                print(f"     {fs['channel']}: {fs['flagged']:,} flagged / {fs['scanned']:,} scanned")

    print(f"\n   Results saved to:")
    print(f"     - flagged_messages.json")
    if MDB_AVAILABLE:
        print(f"     - moderation.db")
    print("\nNext: Start the bot and use /tos_purge to delete flagged messages")


if __name__ == "__main__":
    import sys
    
    # Check for CLI mode
    if len(sys.argv) > 1 and sys.argv[1] == "--scan":
        run_cli_scan()
        sys.exit(0)
    
    if PROTECTOR_BOT_TOKEN == "BOT_TOKEN_HERE":
        print("=" * 50)
        print("ERROR: Please configure your bot token!")
        print("Set BOT_TOKEN in server_helper.py")
        print("Or set the HELPER_BOT_TOKEN environment variable")
        print("=" * 50)
        exit(1)
    
    print("=" * 50)
    print("Server Helper Bot - ToS Protection")
    print("=" * 50)
    print(f"Monitoring: {len(MONITORED_CHANNELS)} channels")
    print(f"Critical words: {len(BAD_WORDS_CRITICAL)}")
    print(f"Moderate words: {len(BAD_WORDS_MODERATE)}")
    print(f"Reclaimed slurs: {len(SLUR_WORDS_MODERATE)}")
    print(f"ToS patterns: {len(TOS_VIOLATION_PATTERNS)}")
    print(f"Sentiment analysis: {'Enabled' if SENTIMENT_AVAILABLE else 'Disabled'}")
    print(f"Database: {'Enabled' if MDB_AVAILABLE else 'In-memory only'}")
    print("=" * 50)
    print("\nTip: Run 'python server_helper.py --scan' to scan exports without starting the bot")
    print("")
    
    client.start()