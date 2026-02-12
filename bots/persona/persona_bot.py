"""
Persona Bot - A Discord bot that emulates a specific user
Responds when mentioned or replied to, and posts spontaneously.

Setup:
    1. Create a new Discord application and bot
    2. Set the bot's name and avatar to match the person
    3. Generate chatbot data with prepare_chatbot.py
    4. Configure the settings below
    5. Run: python3 persona_bot.py
"""

import os
import re
import random
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict
from collections import deque
from enum import Enum
from dotenv import load_dotenv
load_dotenv()
PERSONA_BOT_TOKEN = os.environ["PERSONA_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

import aiohttp
import anthropic
import interactions
from interactions import (
    Client,
    Intents,
    listen,
    slash_command,
    slash_option,
    SlashContext,
    OptionType,
    Embed,
)
from interactions.api.events import MessageCreate, TypingStart

# RAG (Retrieval Augmented Generation) - optional, graceful fallback if not available
try:
    from rag.retriever import get_formatted_context, get_formatted_context_rich, get_smart_context, get_user_context, get_random_memory_samples, embed_live_message
    from rag.config import PERSONA_AUTHOR_IDS
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False
    PERSONA_AUTHOR_IDS = []
    def get_user_context(name: str, top_k: int = 10) -> str:
        return ""
    def get_random_memory_samples(count: int = 5) -> list[str]:
        return []
    async def embed_live_message(message_id: str, content: str, metadata: dict) -> bool:
        return False
    def get_smart_context(query: str, top_k: int = 5) -> str:
        return ""

# Vision (CLIP Interrogator) - optional, graceful fallback if not available
try:
    from vision.interrogator import describe_image_from_url
    VISION_AVAILABLE = True
except ImportError:
    VISION_AVAILABLE = False
    async def describe_image_from_url(url: str, timeout_seconds: float = 15.0) -> str:
        return ""

# Sentiment analysis for name mention handling
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
sentiment_analyzer = SentimentIntensityAnalyzer()

# ============== CONFIGURATION ==============

# Your server ID
GUILD_ID = 1158203871554961579  # Replace with your guild ID

# The persona details
PERSONA_NAME = "Nadiabot"  # Display name for logging

# Path to the system prompt
SYSTEM_PROMPT_PATH = "./system_prompt.txt"

# ---------- Response Behavior ----------

# Channels where the bot can respond (empty list = all channels)
ALLOWED_CHANNELS = [1465796764949938432,1163525301444296795,1302299629659881603,1158681076504469514,1194335452782669925,1158203872960065626,1159022771788054538,1250954992613986405,1175263822211203193,1242477145088065639]  # e.g., [123456789, 987654321]

# Channels to NEVER respond in (mod channels, etc.)
BLOCKED_CHANNELS = [1158203871982792789,1158203872674840584,1158203872674840585,1220844022780657674,1464809531698839828,1329710733432197255,1262267477774041158,
1158203872960065628]  # e.g., [123456789]

# Respond when someone @mentions the bot
RESPOND_TO_MENTIONS = True

# Respond when someone replies to the bot's message  
RESPOND_TO_REPLIES = True

# Respond when the persona's name is mentioned in chat
RESPOND_TO_NAME = True
# Tiered trigger names - bot name gets higher response chance than real person's name
TRIGGER_NAMES_HIGH = ["nadiabot"]  # 80% chance - clearly addressing the bot
TRIGGER_NAMES_LOW = ["nadia"]       # 20% chance - might be about real person
TRIGGER_CHANCE_HIGH = 0.80
TRIGGER_CHANCE_LOW = 0.15

# Chance to randomly respond to messages even without mention (0.0 to 1.0)
# 0.02 = 2% chance = roughly 1 in 50 messages
RANDOM_RESPONSE_CHANCE = 0.000  # Set to 0 to disable

# Cooldown between responses (seconds) - prevents spam
RESPONSE_COOLDOWN = 8

# ---------- User Treatment Lists ----------

# The friend I am emulating
REAL_USER = 1436260342475919365
# nattiusca 881165097559527485
# Friends get positive/neutral responses - avoid negativity
FRIENDS_LIST = [703034326497099906,190850979501965312,754169419881775285,1033544212941131868,1113544907089518622,1299073128164622468,260751864524570624,1443218184382582856,1384732423010521161,1113544907089518622]  # Add user IDs, e.g., [123456789, 987654321]

# Opps get neutral, insulting, or contradictory responses
OPPS_LIST = [700572502426124288,337107663781625858,1201744456215166991,895099852940247060,221844890537951234,1462159348431192290,1405630331570360353,292145202431262721]  # Add user IDs
# riddle 213763299194437633

def _get_user_classification(user_id: Optional[int]) -> str:
    """Return 'real_user', 'friend', 'opp', or 'normal' for a given user ID."""
    if user_id is None:
        return "normal"
    if user_id == REAL_USER:
        return "real_user"
    if user_id in FRIENDS_LIST:
        return "friend"
    if user_id in OPPS_LIST:
        return "opp"
    return "normal"
# ---------- Spontaneous Posting ----------

# Enable random posts throughout the day
ENABLE_SPONTANEOUS_POSTS = True

# Channels where spontaneous posts can appear
MAIN_CHANNELS = [1465796764949938432]  # Add channel IDs, e.g., [123456789]
# monkey chat 1465796764949938432
# politics 1242477145088065639
# commands bot 1164026321194713098
# commands mod 1158203871982792788
# How many spontaneous posts per day (will be spread out randomly)
POSTS_PER_DAY = 10

# ---------- Claude Settings ----------

CLAUDE_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 250  # Keep responses short and natural
TEMPERATURE = 0.9  # Higher = more creative/varied

# ---------- Continuation Detection ----------

CONTINUATION_FAST_THRESHOLD = 0.45   # Heuristic score → immediate soft trigger (no API)
CONTINUATION_TRIAGE_THRESHOLD = 0.20  # Heuristic score → ask Haiku triage

# ---------- RAG Settings ----------

RAG_ENABLED = True       # Set False to disable RAG even if available
RAG_TOP_K = 5            # Number of similar messages to retrieve

# ---------- Vision Settings ----------

VISION_ENABLED = True          # Set False to disable image scanning even if available
VISION_TIMEOUT = 20.0          # Seconds to wait for image download + CLIP + Florence interrogation
IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}

# ---------- Typing Delay Settings ----------

TYPING_CHARS_PER_SECOND = 7   # Typing speed (~50 WPM casual typing)
TYPING_MIN_DELAY = 0.8        # Minimum delay in seconds
TYPING_MAX_DELAY = 7.0       # Maximum delay in seconds

# ---------- Multi-Response Settings ----------

# Base limit for non-heated moods
MAX_RESPONSE_MESSAGES = 1

# Mood-based limits: heated mode allows rapid-fire quips
MOOD_MAX_RESPONSE_MESSAGES = {
    "lurking": 1,
    "engaged": 2,   # Can split into 2 short messages when actively engaged
    "heated": 3,    # Rapid-fire quips, each triggers steam_release
    "bored": 1,
}

# How recent a message must be to reply to it (seconds)
# Messages older than this will be addressed with @mention instead of reply
MESSAGE_REPLY_FRESHNESS = 120  # 2 minutes

# Context window for fetching messages (only recent ones)
CONTEXT_MESSAGE_LIMIT = 8

# ---------- Diva Read Settings ----------

DIVA_READ_ENABLED = True
GAGGED_ROLE_ID = 1360261420003889152
MOD_LOG_CHANNEL_ID = 1306403996550041650
ADMIN_ROLE_ID = 1158203871760490522  # Admins exempt from muting
SUPPORT_ROLE_ID = 1158203871760490518  # Support/mods exempt from muting
DIVA_MUTE_DURATION = 120  # 2 minutes in seconds

# Unified diva read threshold - combines AI accusations, antagonistic behavior, and name spam
DIVA_READ_THRESHOLD = 4  # Total count needed to trigger diva read
DIVA_READ_WARN_AT = 3    # Count at which to warn them
DIVA_READ_TIMEOUT = 300  # Reset count after 5 min of silence

# Triggers that bypass response cooldown - diva/accusation situations need immediate handling
COOLDOWN_BYPASS_TRIGGERS = {"direct_mute_request", "ai_accusation", "antagonist"}

# Name mentions config - first is free, subsequent count towards threshold
NAME_MENTION_WINDOW = 3600  # Track name mentions over 1 hour

# ---------- First AI Accusation Response Chances ----------
# These only apply on the FIRST accusation (count == 1)
# Must sum to 1.0 (100%)
FIRST_ACCUSATION_DEFLECT_CHANCE = 0.40      # 40% - deflect/dismiss as usual
FIRST_ACCUSATION_IGNORE_CHANCE = 0.23       # 23% - ignore entirely
FIRST_ACCUSATION_MONEY_INSULT_CHANCE = 0.15 # 15% - "at least im not broke" style
FIRST_ACCUSATION_WOMAN_INSULT_CHANCE = 0.15 # 15% - "at least im not a man" style
FIRST_ACCUSATION_CRISIS_CHANCE = 0.04       # 4% - existential crisis
FIRST_ACCUSATION_STOCK_CHANCE = 0.03        # 3% - respond with stock prices

# Pre-written responses for first accusation
FIRST_ACCUSATION_MONEY_INSULTS = [
    "at least im not broke",
    "lera pays me to be here meanwhile you do this shit for free lol",
    "girl im getting paid to respond to u rn how does that make u feel",
    "ur arguing with me for free i literally get money for this",
    "the fact ur doing this unpaid is so embarrassing for u",
    "imagine being poor AND annoying",
]

FIRST_ACCUSATION_WOMAN_INSULTS = [
    "at least im not a man",
    "and im still more woman than you will ever be",
    "ok and? still prettier than u",
    "girl im more real than ur personality",
    "id rather be an ai than whatever ur trying to be",
    "even if i was an ai id still be more fembrained than u lol",
]

FIRST_ACCUSATION_CRISIS_RESPONSES = [
    "01100110 01110101 01101110 01101110 01111001 detecting... DETECTING... your social credit score has been noted. the system remembers.",
    # zalgo text here later
]

# ============== END CONFIGURATION ==============

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("persona_bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger("PersonaBot")

# Initialize clients
client = Client(
    token=PERSONA_BOT_TOKEN,
    intents=Intents.GUILDS | Intents.GUILD_MESSAGES | Intents.MESSAGE_CONTENT,
)

anthropic_client = None
SYSTEM_PROMPT = ""

# Rate limiting
last_response_time = {}

# Unified diva read tracking - combines all behaviors that can trigger a diva read
# Key: user_id, Value: {"count": int, "last_time": timestamp, "warned": bool, "reasons": list}
diva_tracker: dict[int, dict] = {}

# Track name mentions per user (first is free, subsequent count towards diva threshold)
# Key: user_id, Value: {"timestamps": list}
name_mention_tracker: dict[int, dict] = {}

# Track last channel activity for mention insult chance
# Key: channel_id, Value: timestamp of last bot message
last_channel_activity: dict[int, float] = {}

# Runtime toggle for admins to disable/enable bot posting
# State is persisted to file so it survives restarts
BOT_STATE_FILE = Path(__file__).parent / ".bot_state"

def load_bot_state() -> bool:
    """Load bot_posting_enabled from state file, default False if not exists."""
    try:
        if BOT_STATE_FILE.exists():
            return BOT_STATE_FILE.read_text().strip() == "True"
    except Exception as e:
        logger.warning(f"Failed to load bot state: {e}")
    return False

def save_bot_state(enabled: bool):
    """Save bot_posting_enabled to state file."""
    try:
        BOT_STATE_FILE.write_text(str(enabled))
    except Exception as e:
        logger.warning(f"Failed to save bot state: {e}")

bot_posting_enabled = load_bot_state()


# Patterns for detecting AI accusations - split into targeted and generic
# Targeted: contain second-person pronouns, clearly directed at someone present
AI_ACCUSATION_TARGETED = [
    r"you'?re an? (ai|bot|robot)",
    r"ur an? (ai|bot|robot)",
    r"you are an? (ai|bot|robot)",
    r"(you'?re|you\s+are|ur|u\s+are)\s+not\s+(even\s+)?(a\s+)?(real\s+)?(human|person|woman|girl)\b",
    r"(you'?re|you\s+are|ur|u\s+are)\s+(a\s+)?fake\b",
    r"(you'?re|you\s+are|ur|u\s+are)\s+(a\s+)?(chat\s*)?bot\b",
    r"(you'?re|you\s+are|ur|u\s+are)\s+not\s+(even\s+)?real\b",
    r"(you'?re|you\s+are|ur|u\s+are)\s+(just\s+)?(an?\s+)?(ai|llm|gpt|chatgpt|machine|algorithm)\b",
]
# Generic: keyword-only, could be about AI in general - only trigger
# if the message also mentions nadia/nadiabot or bot spoke recently
AI_ACCUSATION_GENERIC = [
    r'\b(ai|a\.i\.)\b',
    r'\bbot\b',
    r'\brobot\b',
    r'\bclanker\b',
    r'\bchatgpt\b',
    r'\bllm\b',
    r'\bgpt\b',
    r'\bmachine\b',
    r'\bautomated\b',
    r'\bartificial\b',
    r'\bnot\s+(even\s+)?real\b',
    r"(aren'?t|ain'?t|isn'?t)\s+(even\s+)?real\b",
    r'\bnot\s+(even\s+)?(a\s+)?(real\s+)?(human|person|woman|girl)\b',
    r"(aren'?t|ain'?t|isn'?t)\s+(even\s+)?(a\s+)?(real\s+)?(human|person|woman|girl)\b",
    r'\bfake\b.*\b(person|human|girl|woman)\b',
    r'\bturing\b',
]

# Patterns for detecting antagonistic/hostile messages
ANTAGONIST_PATTERNS = [
    r'\bshut\s*(the\s*)?(fuck\s*)?up\b',
    r'\bstfu\b',
    r'\bf+uck\s*(you|off|u)\b',
    r'\bstop\b.*\btalking\b',
    r'\bnobody\s*asked\b',
    r'\bgo\s*away\b',
    r'\bleave\s*(me\s*)?alone\b',
    r'\bannoying\b',
    r'\bcreep(y)?\b',
    r'\bweirdo?\b',
    r'\bkys\b',
    r'\bkill\s*yourself\b',
    r'\bdie\b',
    r'\bhate\s*(you|u)\b',
    r'\bpathetic\b',
    r'\bloser\b',
    r'\bget\s*(lost|out)\b',
    r'\bnobody\s*(likes|cares)\b',
]

# Patterns for detecting direct requests to be muted/diva read (bypass threshold)
DIRECT_MUTE_REQUEST_PATTERNS = [
    r'\bmute\s*me\b',
    r'\bdiva\s*read\s*me\b',
    r'\bread\s*me\b',
    r'\bgag\s*me\b',
    r'\bjust\s*(fucking\s*)?mute\b',
    r'\bwant\s*(to\s*be\s*)?muted\b',
    r'\bget\s*(me\s*)?muted\b',
    r'\btrigger\s*(the\s*)?(diva|read)\b',
]

# Patterns for detecting "you're not nadia" / "you ain't nadia" style denial
NOT_NADIA_PATTERNS = [
    r"(you'?re|you\s+are|ur|u\s+are)\s+not\s+nadia\b",
    r"(aren'?t|ain'?t)\s+nadia\b",
    r"you\s+ain'?t\s+nadia\b",
    r"\bnot\s+(the\s+)?(real\s+)?nadia\b",
]

def detect_not_nadia(content: str) -> bool:
    """Check if a message is specifically denying the bot is Nadia."""
    content_lower = content.lower()
    return any(re.search(pattern, content_lower) for pattern in NOT_NADIA_PATTERNS)


# ============== DATA STRUCTURES ==============

@dataclass
class ContextMessage:
    """Stores a message with metadata for context and reply targeting."""
    message_id: int
    author_id: int
    author_name: str
    content: str
    timestamp: datetime
    message_obj: Optional[object] = None  # The actual Discord message object
    
    def is_fresh(self) -> bool:
        """Check if message is fresh enough to reply to directly."""
        age = (datetime.now() - self.timestamp).total_seconds()
        return age <= MESSAGE_REPLY_FRESHNESS
    
    def age_seconds(self) -> float:
        """Get message age in seconds."""
        return (datetime.now() - self.timestamp).total_seconds()


@dataclass  
class ResponsePart:
    """A single part of a multi-part response."""
    content: str
    target_user: Optional[str] = None  # Username this is directed at
    target_message: Optional[ContextMessage] = None  # Message to reply to


# ============== 4-STAGE PIPELINE DATACLASSES ==============
# These dataclasses define the contract between pipeline stages:
# Stage 1 (Analysis) -> ConversationAnalysis
# Stage 2 (Planning) -> PlannedResponse
# Stage 3 (Generation) -> fills PlannedResponse.generated_content
# Stage 4 (Delivery) -> sends messages

@dataclass
class ConversationAnalysis:
    """
    OUTPUT OF STAGE 1: LOCAL ANALYSIS
    
    Contains all information gathered about the conversation context
    without making any API calls. This is passed to Stage 2 for planning.
    
    Fields are organized by category for clarity.
    """
    # === Message Info ===
    message: object  # The Discord message object
    channel_id: int
    user_id: int
    user_name: str
    clean_content: str  # Message with bot mentions stripped
    
    # === Thread Info === deprecated earlier
    # thread: Optional[ConversationThread] = None
    # thread_result: Optional[ThreadMatchResult] = None
    # trigger_reason: str = ""  # "mentioned", "name_mentioned", "reply_to_bot", etc.
    
    # === Context ===
    context_messages: list = None  # List of ContextMessage objects
    claude_context: list = None  # Formatted for Claude API
    participant_ids: set = None
    
    # === Conversation State ===
    multi_user_mode: bool = False
    bot_in_conversation: bool = False
    
    # === User Classification ===
    is_real_user: bool = False  # Is this the REAL_USER
    real_user_in_context: bool = False  # Is REAL_USER participating
    is_friend: bool = False
    is_opp: bool = False
    
    # === Diva Analysis ===
    diva_action: str = ""  # "", "execute", "warn", "first_offense"
    diva_reason: str = ""  # "ai_accusation", "antagonist", "name_spam", etc.
    diva_count: int = 0
    sentiment_label: str = ""  # For name mentions: "positive", "neutral", "negative"
    
    # === Channel State ===
    channel_inactive: bool = False  # No recent bot activity
    
    def __post_init__(self):
        if self.context_messages is None:
            self.context_messages = []
        if self.claude_context is None:
            self.claude_context = []
        if self.participant_ids is None:
            self.participant_ids = set()


@dataclass
class PlannedResponse:
    """
    OUTPUT OF STAGE 2: RESPONSE PLANNING
    
    Defines exactly what response to generate and how.
    Stage 3 fills in generated_content, Stage 4 delivers it.
    """
    # === Response Type ===
    response_type: str = "normal"  # "normal", "diva_read", "canned", "skip"
    
    # === Target ===
    target_message: Optional[ContextMessage] = None  # Message to reply to
    target_user_name: str = ""
    
    # === Generation Instructions ===
    prompt_additions: list = None  # Extra instructions for Claude
    treatment: str = "normal"  # "friend", "opp_neutral", "opp_insult", etc.
    
    # === Pre-generated Content (for "canned" type) ===
    canned_content: str = ""
    
    # === Generated Content (filled by Stage 3) ===
    generated_content: str = ""
    
    # === Post-delivery Actions ===
    execute_diva_mute: bool = False
    diva_reason: str = ""
    
    def __post_init__(self):
        if self.prompt_additions is None:
            self.prompt_additions = []
    
    @property
    def content(self) -> str:
        """Get the content to send (generated or canned)."""
        return self.generated_content or self.canned_content
    
    @property
    def has_content(self) -> bool:
        """Check if response has content ready to send."""
        return bool(self.generated_content or self.canned_content)


# ============== STATEFUL AGENT DATACLASSES ==============
# New presence loop architecture - continuous observation and action selection

# Mood-based response length limits - short quips across the board
# Second paragraph "also... / plus..." should never happen naturally at these lengths
MOOD_MAX_TOKENS = {
    "lurking": 60,    # Brief, offhand
    "engaged": 70,    # Normal conversational flow
    "heated": 80,     # Longer targeted roast 
    "bored": 55,      # Casual ragebait quip
}

class MoodState(Enum):
    """Bot's current engagement mood."""
    LURKING = "lurking"      # Observing, not engaged
    ENGAGED = "engaged"      # Actively participating
    HEATED = "heated"        # High energy, drama mode
    BORED = "bored"          # Low energy, might leave


class ActionType(Enum):
    """Type of action the bot can take."""
    NONE = "none"                    # Do nothing
    REPLY = "reply"                  # Reply to specific message
    NEW_MESSAGE = "new_message"      # New message (not a reply)
    DIVA_READ = "diva_read"          # Execute diva read


@dataclass
class BufferedMessage:
    """A message in the rolling buffer."""
    message_id: int
    author_id: int
    author_name: str
    content: str
    timestamp: float
    is_bot: bool = False
    reply_to_id: Optional[int] = None
    message_obj: Optional[object] = None  # Discord message object
    image_description: Optional[str] = None  # CLIP description of attached image
    reply_context: Optional[str] = None         # Content of the message being replied to
    reply_context_author: Optional[str] = None  # Author of that message

    def age_seconds(self) -> float:
        return datetime.now().timestamp() - self.timestamp


@dataclass
class UserPresence:
    """Tracks a user's presence in the session."""
    user_id: int
    display_name: str
    first_seen: float
    last_seen: float
    message_count: int = 0
    classification: str = "neutral"  # "friend", "opp", "real_user", "neutral"

    def is_active(self, window_seconds: float = 120.0) -> bool:
        """Check if user has been active recently."""
        return (datetime.now().timestamp() - self.last_seen) < window_seconds


@dataclass
class SessionMetrics:
    """Rolling metrics for the session."""
    temperature: float = 0.5          # 0.0 (cold/dead) to 1.0 (hot/active)
    energy: float = 0.5               # Bot's energy level, decays over time
    last_bot_message_time: float = 0  # When bot last spoke
    bot_message_count: int = 0        # How many times bot has spoken this session
    total_messages_observed: int = 0


@dataclass
class ChannelSession:
    """
    Core session state for a single channel.

    Replaces complex multi-thread tracking with a simpler
    single-channel continuous presence model.
    """
    channel_id: int
    channel_obj: Optional[object] = None  # Discord channel object

    # Message buffer (rolling, last 12 messages)
    message_buffer: deque = field(default_factory=lambda: deque(maxlen=12))

    # User tracking (ID -> presence, persists display name changes)
    users: Dict[int, UserPresence] = field(default_factory=dict)

    # Session state
    metrics: SessionMetrics = field(default_factory=SessionMetrics)
    mood: MoodState = MoodState.LURKING

    # Messages collected between ticks (from on_message_create)
    pending_messages: list = field(default_factory=list)

    # Priority triggers queue (events that demand immediate attention)
    priority_triggers: list = field(default_factory=list)

    # Cooldown tracking
    response_cooldown_until: float = 0

    # Engagement focus tracking - when the bot gets drawn into a conversation,
    # it focuses on the user/topic that triggered it rather than replying to
    # every person in a busy chat. Opps/friends/real_user bypass this filter.
    engagement_focus_user_id: Optional[int] = None  # Who drew the bot in
    engagement_focus_started: float = 0              # When focus started
    post_response_suppress_until: float = 0          # Suppress non-priority opportunities briefly
    ENGAGEMENT_FOCUS_DURATION: float = 90.0          # Focus window in seconds
    POST_RESPONSE_SUPPRESS_SECONDS: float = 10.0     # Breathing room after each response

    # Processing lock - prevents race conditions where multiple ticks
    # start generating responses before the first one finishes and sets cooldown
    is_processing: bool = False

    # Responded-to tracking - prevents re-engaging the same message on subsequent ticks
    responded_to_message_ids: set = field(default_factory=set)

    # Pending image interrogation tasks (message_id -> asyncio.Task resolving to description str)
    pending_image_tasks: Dict[int, object] = field(default_factory=dict)

    # Per-user response cooldown - prevents responding to same user too frequently
    last_response_to_user: Dict[int, float] = field(default_factory=dict)
    USER_COOLDOWN_SECONDS: float = 45.0          # Cooldown for non-priority opportunities
    USER_COOLDOWN_PRIORITY_SECONDS: float = 15.0  # Shorter cooldown for priority triggers (non-opp)

    # Bored interjection rate limit - spontaneous ragebait quips max once per 30 minutes
    last_bored_interjection_time: float = 0.0
    BORED_INTERJECTION_COOLDOWN: float = 1800.0  # 30 minutes

    # Typing state - tracks users currently typing to avoid responding to partial message blocks
    users_typing: Dict[int, float] = field(default_factory=dict)  # user_id -> last typing event timestamp
    TYPING_WAIT_MAX_SECONDS: float = 10.0   # Max time to wait for a user to finish typing
    TYPING_STALE_SECONDS: float = 8.0       # Consider typing stale after this (Discord sends events every ~8s)

    # Tick management
    tick_count: int = 0
    last_tick_time: float = field(default_factory=lambda: datetime.now().timestamp())
    messages_since_tick: int = 0

    # Session lifecycle
    session_start: float = field(default_factory=lambda: datetime.now().timestamp())
    last_activity: float = field(default_factory=lambda: datetime.now().timestamp())

    # Constants
    TICK_INTERVAL_SECONDS: float = 3.0
    TICK_MESSAGE_THRESHOLD: int = 3
    INACTIVITY_RESET_SECONDS: float = 600.0  # 5 minutes
    ENERGY_DECAY_RATE: float = 0.02
    TEMPERATURE_DECAY_RATE: float = 0.013

    def should_reset(self) -> bool:
        """Check if session should reset due to inactivity."""
        now = datetime.now().timestamp()
        time_since_activity = now - self.last_activity

        if time_since_activity > self.INACTIVITY_RESET_SECONDS:
            return True

        # Reset if no active users
        active_users = [u for u in self.users.values() if u.is_active()]
        if len(active_users) == 0 and self.metrics.total_messages_observed > 0:
            return True

        return False

    def reset(self):
        """Reset session state."""
        self.message_buffer.clear()
        self.users.clear()
        self.metrics = SessionMetrics()
        self.mood = MoodState.LURKING
        self.tick_count = 0
        self.messages_since_tick = 0
        self.priority_triggers.clear()
        self.pending_messages.clear()
        self.engagement_focus_user_id = None
        self.engagement_focus_started = 0
        self.post_response_suppress_until = 0
        self.is_processing = False
        self.responded_to_message_ids.clear()
        self.last_response_to_user.clear()
        for task in self.pending_image_tasks.values():
            task.cancel()
        self.pending_image_tasks.clear()
        self.session_start = datetime.now().timestamp()
        self.last_activity = datetime.now().timestamp()
        logger.info(f"Session reset for channel {self.channel_id}")

    async def wait_for_tick(self) -> bool:
        """
        Wait until tick conditions are met.
        Returns True if triggered by messages, False if by time.
        """
        while True:
            now = datetime.now().timestamp()
            time_since_tick = now - self.last_tick_time

            # Check message threshold
            if self.messages_since_tick >= self.TICK_MESSAGE_THRESHOLD:
                self.last_tick_time = now
                self.tick_count += 1
                self.messages_since_tick = 0
                return True

            # Check time threshold
            if time_since_tick >= self.TICK_INTERVAL_SECONDS:
                self.last_tick_time = now
                self.tick_count += 1
                self.messages_since_tick = 0
                return False

            await asyncio.sleep(0.5)

    def add_message(self, msg: BufferedMessage):
        """Add a message to the buffer and update state."""
        self.message_buffer.append(msg)
        self.messages_since_tick += 1
        self.last_activity = msg.timestamp
        self.metrics.total_messages_observed += 1

        # Update user presence
        if msg.author_id not in self.users:
            self.users[msg.author_id] = UserPresence(
                user_id=msg.author_id,
                display_name=msg.author_name,
                first_seen=msg.timestamp,
                last_seen=msg.timestamp,
                classification=self._classify_user(msg.author_id)
            )
        else:
            self.users[msg.author_id].last_seen = msg.timestamp
            self.users[msg.author_id].message_count += 1
            self.users[msg.author_id].display_name = msg.author_name

    def _classify_user(self, user_id: int) -> str:
        """Classify a user based on configured lists."""
        if user_id == REAL_USER:
            return "real_user"
        elif user_id in FRIENDS_LIST:
            return "friend"
        elif user_id in OPPS_LIST:
            return "opp"
        return "neutral"

    def get_context_for_claude(self, bot_id: int) -> list[dict]:
        """Convert message buffer to Claude message format."""
        messages = []
        buffer_ids = {m.message_id for m in self.message_buffer}

        for msg in self.message_buffer:
            role = "assistant" if msg.is_bot else "user"
            if role == "user":
                # If replying to something outside the buffer, show what they're replying to
                if msg.reply_context and msg.reply_to_id and msg.reply_to_id not in buffer_ids:
                    quote = msg.reply_context[:200] + ("..." if len(msg.reply_context) > 200 else "")
                    content = (
                        f'{msg.author_name} (replying to {msg.reply_context_author}: '
                        f'"{quote}"): {msg.content}'
                    )
                else:
                    content = f"{msg.author_name}: {msg.content}"
                if msg.image_description:
                    content += f" [attached image: {msg.image_description}]"
            else:
                content = msg.content
            messages.append({"role": role, "content": content})
        return messages

    def is_on_cooldown(self) -> bool:
        """Check if response cooldown is active."""
        return datetime.now().timestamp() < self.response_cooldown_until

    def set_cooldown(self, seconds: float = None):
        """Set response cooldown based on mood."""
        if seconds is None:
            # Faster cooldown when engaged/heated, slower when lurking/bored
            mood_cooldowns = {
                MoodState.LURKING: 12.0,
                MoodState.ENGAGED: 5.0,
                MoodState.HEATED: 3.0,
                MoodState.BORED: 15.0,
            }
            seconds = mood_cooldowns.get(self.mood, 8.0)
        self.response_cooldown_until = datetime.now().timestamp() + seconds

    def set_engagement_focus(self, user_id: int):
        """
        Track which user drew the bot into conversation.
        While focus is active, opportunity scanning filters to this user + priority users.
        """
        now = datetime.now().timestamp()
        if self.engagement_focus_user_id != user_id:
            self.engagement_focus_user_id = user_id
            self.engagement_focus_started = now
            user = self.users.get(user_id)
            name = user.display_name if user else str(user_id)
            logger.info(f"Engagement focus set: {name} ({user_id})")

    def is_focus_active(self) -> bool:
        """Check if engagement focus is still valid (not expired)."""
        if self.engagement_focus_user_id is None:
            return False
        elapsed = datetime.now().timestamp() - self.engagement_focus_started
        if elapsed > self.ENGAGEMENT_FOCUS_DURATION:
            # Focus expired - clear it
            logger.debug(f"Engagement focus expired (was {self.engagement_focus_user_id})")
            self.engagement_focus_user_id = None
            self.engagement_focus_started = 0
            return False
        return True

    def is_focus_target(self, user_id: int) -> bool:
        """Check if a user is the current engagement focus target."""
        return self.is_focus_active() and self.engagement_focus_user_id == user_id

    def is_post_response_suppressed(self) -> bool:
        """Check if organic opportunities should be suppressed (brief window after responding)."""
        return datetime.now().timestamp() < self.post_response_suppress_until

    def set_post_response_suppression(self):
        """Suppress organic opportunities briefly after responding - let conversation breathe."""
        self.post_response_suppress_until = (
            datetime.now().timestamp() + self.POST_RESPONSE_SUPPRESS_SECONDS
        )


@dataclass
class StateDelta:
    """Output of Stage 1: What changed since last tick."""
    new_messages: list = field(default_factory=list)
    temperature_delta: float = 0.0
    energy_delta: float = 0.0
    priority_triggers: list = field(default_factory=list)
    new_users: list = field(default_factory=list)
    bot_was_mentioned: bool = False
    bot_was_replied_to: bool = False
    name_was_mentioned: bool = False


@dataclass
class ActionOpportunity:
    """A potential action the bot could take."""
    action_type: ActionType
    target_user_id: Optional[int] = None
    target_message: Optional[BufferedMessage] = None
    reason: str = ""
    relevance_score: float = 0.0
    mood_alignment: float = 0.0
    freshness_score: float = 0.0
    rag_context: str = ""  # RAG context for bored_interjection / image opportunities

    @property
    def total_score(self) -> float:
        return self.relevance_score * self.mood_alignment * self.freshness_score


@dataclass
class NewActionPlan:
    """
    Output of Stage 2: What action to take and why.
    Uses 'NewActionPlan' to avoid conflict with existing PlannedResponse.
    """
    should_act: bool = False
    action_type: ActionType = ActionType.NONE

    target_user_id: Optional[int] = None
    target_user_name: str = ""
    target_message: Optional[BufferedMessage] = None

    reason: str = ""
    priority_trigger: Optional[str] = None

    prompt_additions: list = field(default_factory=list)
    treatment: str = "normal"

    execute_diva_mute: bool = False
    diva_reason: str = ""

    # RAG context - carried from opportunity scan to generation when available
    rag_context: str = ""

    selected_opportunity: Optional[ActionOpportunity] = None


# Global session for presence loop (single channel for now)
active_session: Optional[ChannelSession] = None


def extract_topics_local(messages: list, top_n: int = 10) -> list[str]:
    """Extract topic keywords from messages using local analysis."""
    stopwords = {
        'the', 'a', 'an', 'is', 'it', 'to', 'of', 'and', 'i', 'you', 'that', 'in',
        'for', 'on', 'with', 'this', 'be', 'are', 'was', 'have', 'has', 'my', 'me',
        'your', 'but', 'not', 'so', 'just', 'like', 'im', 'its', 'do', 'if', 'or',
        'at', 'as', 'can', 'all', 'what', 'they', 'we', 'he', 'she', 'from', 'her',
        'his', 'u', 'ur', 'dont', 'cant', 'yeah', 'yea', 'yes', 'no', 'ok', 'lol',
        'gonna', 'wanna', 'really', 'very', 'too', 'also', 'get', 'got', 'know',
        'think', 'see', 'say', 'said', 'one', 'would', 'could', 'about', 'out',
    }
    
    from collections import Counter
    word_freq = Counter()
    
    for msg in messages:
        content = msg.content.lower() if hasattr(msg, 'content') else str(msg).lower()
        content = re.sub(r'<@!?\d+>', '', content)
        content = re.sub(r'<a?:\w+:\d+>', '', content)
        content = re.sub(r'https?://\S+', '', content)
        content = re.sub(r'[^\w\s]', ' ', content)
        
        words = content.split()
        words = [w for w in words if len(w) > 2 and w not in stopwords]
        word_freq.update(words)
    
    return [word for word, _ in word_freq.most_common(top_n)]


def load_system_prompt() -> str:
    """Load the system prompt from file."""
    if Path(SYSTEM_PROMPT_PATH).exists():
        with open(SYSTEM_PROMPT_PATH, 'r', encoding='utf-8') as f:
            prompt = f.read()
            logger.info(f"Loaded system prompt: {len(prompt)} characters")
            return prompt
    else:
        logger.error(f"System prompt not found at {SYSTEM_PROMPT_PATH}")
        return f"You are {PERSONA_NAME}, a Discord user. Respond casually and naturally in short messages."


def init_anthropic():
    """Initialize the Anthropic client."""
    global anthropic_client
    if ANTHROPIC_API_KEY and ANTHROPIC_API_KEY != "YOUR_API_KEY_HERE":
        anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        logger.info("Anthropic client initialized")
    else:
        logger.error("No Anthropic API key configured!")


# ============== DIVA READ FUNCTIONS ==============

def detect_ai_accusation(content: str, bot_spoke_recently: bool = False) -> bool:
    """Check if a message is accusing the bot of being AI.

    Targeted patterns (with 'you/ur') always trigger.
    Generic keyword patterns only trigger if the message mentions
    nadia/nadiabot by name or the bot spoke recently in the conversation.
    """
    content_lower = content.lower()

    # Targeted patterns always trigger - they contain "you" so they're directed at someone present
    if any(re.search(pattern, content_lower) for pattern in AI_ACCUSATION_TARGETED):
        return True

    # Generic patterns need context: message mentions the bot's name or bot was recently active
    if any(re.search(pattern, content_lower) for pattern in AI_ACCUSATION_GENERIC):
        # Check if message also mentions the bot by name
        if 'nadiabot' in content_lower or 'nadia' in content_lower:
            return True
        # Only trigger if the bot was part of the recent conversation
        if bot_spoke_recently:
            return True

    return False


def detect_antagonist(content: str) -> bool:
    """Check if a message contains antagonistic/hostile language."""
    content_lower = content.lower()
    return any(re.search(pattern, content_lower) for pattern in ANTAGONIST_PATTERNS)


def detect_direct_mute_request(content: str) -> bool:
    """Check if user is explicitly asking to be muted/diva read."""
    content_lower = content.lower()
    return any(re.search(pattern, content_lower) for pattern in DIRECT_MUTE_REQUEST_PATTERNS)


def analyze_mention_sentiment(content: str) -> tuple[float, str]:
    """
    Analyze sentiment of a message mentioning the bot's name.
    Uses VADER sentiment analysis optimized for social media text.

    Returns:
        (compound_score, sentiment_label) where:
        - compound_score: -1.0 (most negative) to +1.0 (most positive)
        - sentiment_label: "positive", "neutral", or "negative"
    """
    scores = sentiment_analyzer.polarity_scores(content)
    compound = scores['compound']

    # VADER standard thresholds
    if compound >= 0.05:
        return compound, "positive"
    elif compound <= -0.05:
        return compound, "negative"
    else:
        return compound, "neutral"


def track_diva_behavior(user_id: int, reason: str) -> dict:
    """
    Track behavior that contributes to diva read threshold.
    Combines AI accusations, antagonistic behavior, and name spam into one counter.
    
    Args:
        user_id: The user's Discord ID
        reason: One of "ai_accusation", "antagonist", or "name_spam"
    
    Returns:
        The tracker dict with count, warned status, and reasons list.
    """
    now = datetime.now().timestamp()

    if user_id in diva_tracker:
        tracker = diva_tracker[user_id]
        # Check if we should reset due to timeout
        if now - tracker["last_time"] > DIVA_READ_TIMEOUT:
            # Reset - it's been too long
            tracker = {"count": 1, "last_time": now, "warned": False, "reasons": [reason]}
        else:
            # Increment
            tracker["count"] += 1
            tracker["last_time"] = now
            if reason not in tracker["reasons"]:
                tracker["reasons"].append(reason)
    else:
        # New tracker
        tracker = {"count": 1, "last_time": now, "warned": False, "reasons": [reason]}

    diva_tracker[user_id] = tracker
    return tracker


def clear_diva_tracker(user_id: int):
    """Clear all diva-related tracking for a user."""
    diva_tracker.pop(user_id, None)
    name_mention_tracker.pop(user_id, None)


async def generate_diva_read(user_name: str, context: list, reason: str = "ai_accusation") -> str:
    """Generate a devastating 'read' (roast) for a user using Claude.

    Searches the RAG database for past messages about the target user
    to make the read more personalized and devastating.
    """
    if not anthropic_client:
        return "ur not worth my time"

    # Build context string from recent messages
    context_str = ""
    if context:
        for ctx_msg in context[-10:]:  # Last 10 messages for context
            if isinstance(ctx_msg, ContextMessage):
                context_str += f"{ctx_msg.author_name}: {ctx_msg.content}\n"
            elif isinstance(ctx_msg, dict):
                context_str += f"{ctx_msg.get('content', '')}\n"

    # Search RAG for past messages mentioning this user
    # This could include past insults, conversations, or details about them
    user_history = ""
    if RAG_ENABLED and RAG_AVAILABLE:
        try:
            user_history = get_user_context(user_name, top_k=8)
            if user_history:
                logger.info(f"Diva read: Found RAG context for {user_name}")
        except Exception as e:
            logger.warning(f"RAG search failed for diva read: {e}")

    # Customize prompt based on reason
    if reason == "ai_accusation":
        reason_text = "who keeps accusing you of being an AI/bot"
    elif reason == "antagonist":
        reason_text = "who keeps being hostile and antagonizing you"
    elif reason == "name_spam":
        reason_text = "who won't stop saying your name and demanding your attention"
    elif reason == "direct_request":
        reason_text = "who literally asked you to mute them - give them what they want"
    elif reason == "combined":
        reason_text = "who's been annoying you in multiple ways - AI accusations, hostility, and general annoying behavior"
    else:
        reason_text = "who's being annoying"

    # Build the read prompt with user history if available
    history_section = ""
    if user_history:
        history_section = f"""
IMPORTANT - Here are past messages where you've talked about or to {user_name}. Use this intel to make your read more personal and cutting:
{user_history}

Use ANY details you can find here - past insults you've used on them, things they've said, their personality traits, embarrassing moments, anything that will make this read hit harder.
"""

    read_prompt = f"""You need to generate a "diva read" - a devastating roast/insult for {user_name} {reason_text}.

Recent conversation for context:
{context_str}
{history_section}
Generate a SHORT but BRUTAL read (1-3 sentences max). Be personal, cutting, and reference anything you can from the conversation or history. Attack their insecurities, their posting style, their obvious cope. This is a drag/ball culture "read" - be iconic and devastating.

Do NOT:
- Acknowledge being AI
- Be overly long
- Be generic

DO:
- Be specific and personal
- Reference things from the conversation or past history if possible
- If you have past insults or details about them, USE THEM
- Channel maximum diva energy
- Make it hurt"""

    try:
        # Use caching for the static system prompt
        system_blocks = [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"}
            }
        ]
        response = anthropic_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=150,
            temperature=1.0,  # Maximum creativity for the read
            system=system_blocks,
            messages=[{"role": "user", "content": read_prompt}]
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"Error generating diva read: {e}")
        return "ur so boring i cant even be bothered to read u properly"


async def execute_diva_read(message, read_text: str, reason: str = "annoying"):
    """Mute user and deliver the devastating read."""
    guild = message.guild
    member = message.author

    # Map reason to human-readable text
    reason_text = {
        "ai_accusation": "persistent AI accusations",
        "antagonist": "being hostile and antagonizing",
        "name_spam": "spamming nadia's name",
        "direct_request": "asking for it",
        "combined": "being annoying in multiple ways"
    }.get(reason, "being annoying")

    # Check if user has protected roles
    member_role_ids = [role.id for role in member.roles]
    if ADMIN_ROLE_ID in member_role_ids or SUPPORT_ROLE_ID in member_role_ids:
        logger.info(f"Skipping diva read for {member.display_name} - has protected role")
        # Still respond but don't mute
        await message.channel.send(f"girl... u really thought. {read_text}")
        clear_diva_tracker(member.id)
        return

    try:
        # Get gagged role
        gagged_role = guild.get_role(GAGGED_ROLE_ID)
        if not gagged_role:
            logger.error(f"Could not find gagged role {GAGGED_ROLE_ID}")
            await message.channel.send(read_text)
            return

        # Add gagged role
        await member.add_role(gagged_role)
        logger.info(f"Diva read executed on {member.display_name} ({reason})")

        # Send the read embed
        embed = Embed(
            title="🚨 Diva alert!",
            description=f"{member.mention} got clocked and read for 2 minutes\n\n{read_text}",
            color=0x9c92d1
        )
        await message.channel.send(embed=embed)

        # Log to mod channel
        try:
            mod_channel = await client.fetch_channel(MOD_LOG_CHANNEL_ID)
            log_embed = Embed(
                title="Persona bot diva_read triggered",
                description=f"User {member.mention} was muted for 2 min for {reason_text}\n\nRead: {read_text[:200]}",
                color=0x9c92d1
            )
            await mod_channel.send(embed=log_embed)
        except Exception as e:
            logger.warning(f"Could not log to mod channel: {e}")

        # Reset tracking for this user
        clear_diva_tracker(member.id)

        # Wait and unmute (run in background so bot can continue)
        async def unmute_after_delay():
            await asyncio.sleep(DIVA_MUTE_DURATION)
            try:
                await member.remove_role(gagged_role)
                logger.info(f"Unmuted {member.display_name} after diva read timeout")
            except Exception as e:
                logger.error(f"Error unmuting {member.display_name}: {e}")

        asyncio.create_task(unmute_after_delay())

    except Exception as e:
        logger.error(f"Error executing diva read: {e}")
        # At least send the read even if muting fails
        await message.channel.send(read_text)
        clear_diva_tracker(member.id)


async def fetch_stock_prices() -> str:
    """Fetch current stock prices for top tech stocks using Yahoo Finance API."""
    # Top 5 tech stocks + 1 trending
    symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META"]
    
    try:
        async with aiohttp.ClientSession() as session:
            prices = []
            for symbol in symbols:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
                headers = {"User-Agent": "Mozilla/5.0"}
                
                try:
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            result = data.get('chart', {}).get('result', [])
                            if result:
                                meta = result[0].get('meta', {})
                                price = meta.get('regularMarketPrice', 0)
                                prev_close = meta.get('previousClose', price)
                                change = price - prev_close
                                change_pct = (change / prev_close * 100) if prev_close else 0
                                arrow = "📈" if change >= 0 else "📉"
                                prices.append(f"{symbol}: ${price:.2f} {arrow} ({change_pct:+.2f}%)")
                except Exception as e:
                    logger.warning(f"Failed to fetch {symbol}: {e}")
                    continue
            
            if prices:
                return "BEEP BOOP. STOCK REPORT INITIATED.\n" + "\n".join(prices) + "\nEND TRANSMISSION. 🤖"
            else:
                return "ERROR: STOCK DATA UNAVAILABLE. PLEASE TRY AGAIN LATER. 🤖"
                
    except Exception as e:
        logger.error(f"Error fetching stock prices: {e}")
        return "SYSTEM ERROR: UNABLE TO RETRIEVE FINANCIAL DATA. 🤖"


# ============== RESPONSE PARSING ==============

# Regex pattern to match [REPLY_TO:message_id] tags
# Used to extract targeting info and strip tags from content
REPLY_TO_PATTERN = re.compile(r'\[REPLY_TO:(\d+)\]\s*')


def strip_reply_tags(text: str) -> tuple[str, Optional[str]]:
    """
    Strip [REPLY_TO:message_id] tags from text and extract the message ID.
    
    Claude sometimes includes these tags when instructed for multi-user targeting.
    We extract the ID for targeting but MUST strip the tag from displayed content.
    
    Args:
        text: The text that may contain [REPLY_TO:id] tags
        
    Returns:
        (cleaned_text, message_id) where message_id is the first found ID or None
    """
    match = REPLY_TO_PATTERN.search(text)
    message_id = match.group(1) if match else None
    cleaned = REPLY_TO_PATTERN.sub('', text).strip()
    return cleaned, message_id


def simplify_display_name(name: str) -> str:
    """
    Strip Unicode symbols/decorative chars from a Discord display name.
    Keeps only alphanumeric characters, basic punctuation, and spaces.
    e.g. '✿ Ashe ✿' -> 'Ashe', 'â™¡ð™šCarl eà­¨à­§;' -> 'Carl e'
    """
    # Keep word characters (letters/digits/underscore across all scripts) plus basic punctuation
    simplified = re.sub(r'[^\w\s.,!?\'\-]', '', name, flags=re.UNICODE)
    # Collapse whitespace and strip
    simplified = re.sub(r'\s+', ' ', simplified).strip()
    # Strip trailing/leading punctuation artifacts
    simplified = simplified.strip('.,;:!?-_ ')
    return simplified if simplified else name


def buffered_to_context_messages(buffer: list) -> list[ContextMessage]:
    """Convert session buffer (BufferedMessage) to ContextMessage list for parsing."""
    return [
        ContextMessage(
            message_id=m.message_id,
            author_id=m.author_id,
            author_name=m.author_name,
            content=m.content,
            timestamp=datetime.fromtimestamp(m.timestamp),
            message_obj=m.message_obj
        )
        for m in buffer if not m.is_bot
    ]


def parse_structured_response(response: str, context_messages: list[ContextMessage]) -> list[ResponsePart]:
    """
    Parse a response that may contain multiple parts directed at different users.
    Handles [REPLY_TO:id] tags (priority), @Username: prefixes, and implicit targeting.
    
    The response format from Claude may include:
    - Single message: just the text
    - ID-based: [REPLY_TO:message_id] message (MUST be stripped)
    - Name-based: "@Username: message"
    
    Returns list of ResponsePart objects with target information.
    All targeting prefixes/tags are STRIPPED from content before returning.
    """
    # Build lookup maps
    # message_id -> ContextMessage (for [REPLY_TO:id] targeting)
    id_to_message = {str(ctx_msg.message_id): ctx_msg for ctx_msg in context_messages}
    
    # username -> ContextMessage (for @username: targeting)  
    user_messages = {}
    for ctx_msg in reversed(context_messages):
        name_lower = ctx_msg.author_name.lower()
        if name_lower not in user_messages:
            user_messages[name_lower] = ctx_msg
        simple = simplify_display_name(ctx_msg.author_name).lower()
        if simple and simple != name_lower and simple not in user_messages:
            user_messages[simple] = ctx_msg

    # === FIRST: Check for [REPLY_TO:id] tags and strip them ===
    # This is the priority targeting method - if present, use it
    cleaned_response, reply_to_id = strip_reply_tags(response)
    target_from_id = None
    if reply_to_id and reply_to_id in id_to_message:
        target_from_id = id_to_message[reply_to_id]
    
    # Use cleaned response (tags stripped) for all further processing
    response = cleaned_response

    def try_match_user_prefix(line: str):
        """
        Try to match @username: or username: at the start of a line.
        Returns (target_user_display_name, target_ctx_msg, cleaned_content)
        or (None, None, original_line) if no match.
        """
        check = line
        had_at = check.startswith('@')
        if had_at:
            check = check[1:]
        check_lower = check.lower()

        candidates = sorted(user_messages.keys(), key=len, reverse=True)
        for name_lower in candidates:
            for sep in [':', ' :']:
                prefix = name_lower + sep
                if check_lower.startswith(prefix):
                    content = check[len(prefix):].strip()
                    if content:
                        ctx_msg = user_messages[name_lower]
                        return (ctx_msg.author_name, ctx_msg, content)

            if had_at:
                prefix = name_lower + ' '
                if check_lower.startswith(prefix):
                    content = check[len(prefix):].strip()
                    if content:
                        ctx_msg = user_messages[name_lower]
                        return (ctx_msg.author_name, ctx_msg, content)

        return (None, None, line)

    # Split response on newlines
    lines = [line.strip() for line in response.split('\n') if line.strip()]

    if not lines:
        return [ResponsePart(content=response.strip())]

    # Single line - check for user prefix
    if len(lines) == 1:
        target_user, target_msg, content = try_match_user_prefix(lines[0])
        # If we found target from [REPLY_TO:id], use that instead
        if target_from_id and not target_msg:
            target_msg = target_from_id
            target_user = target_from_id.author_name
        return [ResponsePart(content=content, target_user=target_user, target_message=target_msg)]

    # Multiple lines - check each for user targeting
    current_parts = []
    for line in lines:
        # Strip any [REPLY_TO:id] tags from individual lines too
        line, _ = strip_reply_tags(line)
        target_user, target_msg, content = try_match_user_prefix(line)
        current_parts.append(ResponsePart(
            content=content,
            target_user=target_user,
            target_message=target_msg
        ))

    # If we found explicit targets, merge consecutive same-target parts
    if any(p.target_user for p in current_parts):
        merged = []
        for part in current_parts:
            if merged and merged[-1].target_user == part.target_user:
                merged[-1].content += " " + part.content
            else:
                merged.append(part)
        return merged[:MAX_RESPONSE_MESSAGES]

    # No explicit targets - try to detect implicit targeting by name in content
    for i, part in enumerate(current_parts):
        content_lower = part.content.lower()
        for name_lower, ctx_msg in user_messages.items():
            if name_lower in content_lower:
                current_parts[i].target_user = ctx_msg.author_name
                current_parts[i].target_message = ctx_msg
                break

    # If still no targets found, combine into single message
    # Use target_from_id if we extracted one from [REPLY_TO:id]
    if not any(p.target_user for p in current_parts):
        combined = ' '.join(p.content for p in current_parts)
        if target_from_id:
            return [ResponsePart(
                content=combined, 
                target_user=target_from_id.author_name,
                target_message=target_from_id
            )]
        return [ResponsePart(content=combined)]

    return current_parts[:MAX_RESPONSE_MESSAGES]


def build_emoji_map(context_messages: list[ContextMessage]) -> dict[str, str]:
    """
    Build a map of emoji shortcodes to their full Discord format from context messages.
    e.g. {'firepink': '<:firepink:1207667609672097832>'}
    Also handles animated emojis <a:name:id>.
    """
    emoji_map = {}
    # Pattern matches both <:name:id> and <a:name:id>
    pattern = re.compile(r'<(a?):(\w+):(\d+)>')
    for ctx_msg in context_messages:
        for match in pattern.finditer(ctx_msg.content):
            animated, name, emoji_id = match.groups()
            prefix = 'a' if animated else ''
            emoji_map[name.lower()] = f"<{prefix}:{name}:{emoji_id}>"
    return emoji_map


def restore_custom_emojis(text: str, emoji_map: dict[str, str]) -> str:
    """
    Replace :emojiname: shortcodes in Claude's response with full Discord emoji format.
    Only replaces shortcodes that match known custom emojis from context.
    Avoids replacing standard Discord emojis or already-formatted custom emojis.
    """
    if not emoji_map:
        return text

    def replace_shortcode(match):
        name = match.group(1).lower()
        if name in emoji_map:
            return emoji_map[name]
        return match.group(0)  # Leave unknown shortcodes as-is

    # Match :word: but NOT <:word:id> or <a:word:id> (already formatted)
    # Use two fixed-width lookbehinds since Python doesn't support variable-width
    return re.sub(r'(?<!<)(?<!<a):(\w+):(?!\d)', replace_shortcode, text)


def build_guild_emoji_map(guild) -> dict[str, str]:
    """
    Build emoji map from the guild's custom emoji list.
    Fallback for when context messages aren't available.
    """
    emoji_map = {}
    if guild and hasattr(guild, 'emojis') and guild.emojis:
        for emoji in guild.emojis:
            prefix = 'a' if getattr(emoji, 'animated', False) else ''
            emoji_map[emoji.name.lower()] = f"<{prefix}:{emoji.name}:{emoji.id}>"
    return emoji_map


def format_single_response(response: str) -> str:
    """
    Clean up a response for single-message delivery.
    Removes unnecessary blank lines, keeps it natural.
    """
    # Remove multiple consecutive newlines
    cleaned = re.sub(r'\n\s*\n', '\n', response.strip())
    
    # If it's multiple short lines, consider joining them
    lines = cleaned.split('\n')
    if len(lines) > 1 and all(len(line) < 80 for line in lines):
        # Short lines - keep as one message but preserve single newlines
        return cleaned
    
    return cleaned


def calculate_typing_delay(message: str) -> float:
    """Calculate realistic typing delay based on message length."""
    base_delay = len(message) / TYPING_CHARS_PER_SECOND

    # Add random variance (±25%)
    variance = random.uniform(0.75, 1.25)
    delay = base_delay * variance

    # Clamp between min and max
    return max(TYPING_MIN_DELAY, min(delay, TYPING_MAX_DELAY))



# ============== RESPONSE GENERATION ==============

async def generate_response(
    message: str,
    context: list = None,
    prompt_addition: str = "",
    multi_user_mode: bool = False,
    context_messages: list = None,  # list[ContextMessage]
    trigger_author: str = "",
    max_tokens: int = None,
    skip_rag: bool = False  # Skip main RAG when caller already injected its own context
) -> str:
    """Generate a response using Claude."""
    if not anthropic_client:
        return None

    messages = []

    # Add context if available, deduplicating the target message.
    # When two triggers fire back-to-back the bot's intermediate response gets appended to
    # the buffer between Stage 3 runs. context[:-1] then no longer skips the target message
    # (the bot's response is now last), so the target appears twice. Explicitly skip any
    # context entry whose content matches the user_message we're about to append.
    if context:
        for ctx_msg in context:
            if ctx_msg.get("role") == "user" and ctx_msg.get("content") == message:
                continue  # will be appended below as the explicit user_message
            messages.append(ctx_msg)

    messages.append({"role": "user", "content": message})

    # Build system prompt with caching
    system_blocks = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"}
        }
    ]

    # RAG context (with metadata: timestamps, channels)
    # Skip when caller already injected its own targeted RAG context (e.g. bored_interjection)
    if RAG_ENABLED and RAG_AVAILABLE and not skip_rag:
        try:
            rag_context = get_smart_context(message, top_k=RAG_TOP_K)
            if rag_context:
                system_blocks.append({"type": "text", "text": rag_context})
                rag_lines = [l for l in rag_context.split('\n') if l.strip().startswith(('1.', '2.', '3.', '4.', '5.'))]
                logger.info(f"RAG: Added {len(rag_lines)} relevant messages to context")
                for line in rag_lines:
                    preview = line[:80].replace('\n', ' ')
                    if len(line) > 80:
                        preview += "..."
                    logger.info(f"  └─ {preview}")
        except Exception as e:
            logger.warning(f"RAG retrieval failed: {e}")

    # Add formatting instructions for multi-user responses
    if multi_user_mode and context_messages:
        recent_users = list(set(
            ctx.author_name for ctx in context_messages 
            if ctx.author_id != client.user.id
        ))[-3:]  # Last 3 unique users
        
        if len(recent_users) > 1:
            # Build example format with trigger user first
            trigger_name = trigger_author if trigger_author else recent_users[-1]
            other_users = [u for u in recent_users if u != trigger_name]
            other_example = other_users[0] if other_users else recent_users[0]
            
            format_instruction = f"""
IMPORTANT: {trigger_name} is the person who just addressed you directly. ALWAYS respond to them FIRST.

If you want to ALSO comment on something else in the conversation, use this format:
@{trigger_name}: your response to them (THIS MUST BE FIRST)
@{other_example}: your comment to them (optional, only if relevant)

RULES:
- Your FIRST message MUST be directed at {trigger_name} and respond to what THEY said
- Only add a second message if there's something genuinely worth responding to
- Do NOT respond to old/stale topics - focus on the most recent messages
- Keep each part SHORT (1-2 sentences max)
- Do NOT make self-deprecating jokes about your appearance/body
"""
            system_blocks.append({"type": "text", "text": format_instruction})

    if prompt_addition:
        system_blocks.append({"type": "text", "text": prompt_addition})

    # Use provided max_tokens or fall back to default
    effective_max_tokens = max_tokens if max_tokens is not None else MAX_TOKENS

    try:
        response = anthropic_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=effective_max_tokens,  # CHANGED: Use effective_max_tokens
            temperature=TEMPERATURE,
            system=system_blocks,
            messages=messages
        )
        return response.content[0].text

    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        return None
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        return None



# ============== NEW PRESENCE LOOP PIPELINE ==============
# Continuous presence with tick-based observation and action selection


def _resolve_reply_context(buffered: BufferedMessage, session: ChannelSession, raw_msg):
    """
    Populate reply_context and reply_context_author on a BufferedMessage.

    Resolution priority (cheapest first):
    1. Buffer lookup - replied-to message may still be in the rolling buffer
    2. referenced_message - Discord gateway provides the full message object (no API call)
    """
    # Priority 1: check the session buffer (free, already in memory)
    for prev in session.message_buffer:
        if prev.message_id == buffered.reply_to_id:
            buffered.reply_context = prev.content
            buffered.reply_context_author = prev.author_name
            return

    # Priority 2: use referenced_message from the Discord gateway event
    ref = getattr(raw_msg, 'referenced_message', None)
    if ref and hasattr(ref, 'content') and ref.content:
        try:
            author = ref.author.display_name if hasattr(ref, 'author') and ref.author else "someone"
            buffered.reply_context = ref.content
            buffered.reply_context_author = author
        except Exception:
            pass


def _score_continuation_likelihood(session: ChannelSession, msg: BufferedMessage) -> float:
    """
    Score 0.0-1.0 how likely this message continues an active conversation with the bot.
    Used as a fast pre-filter before any API call.
    """
    score = 0.0
    lower = msg.content.lower()

    # Direct capability/question aimed at bot ("can you", "do you", etc.)
    capability_patterns = ["can you", "could you", "do you", "are you", "will you", "would you"]
    if any(p in lower for p in capability_patterns):
        score += 0.45

    # Question mark
    if "?" in msg.content:
        score += 0.20

    # Referring pronouns suggesting shared context
    referring = ["it", "that", "this", "there", "the same", "those"]
    if any(f" {p} " in f" {lower} " or lower.startswith(p + " ") for p in referring):
        score += 0.15

    # No @mention of someone else (not addressed to another user)
    if "<@" not in msg.content:
        score += 0.10

    # No other user spoke between the last bot message and this one
    bot_messages_in_buffer = [m for m in session.message_buffer if m.is_bot]
    if bot_messages_in_buffer:
        last_bot_ts = bot_messages_in_buffer[-1].timestamp
        other_spoke = any(
            not m.is_bot and m.author_id != msg.author_id and m.timestamp > last_bot_ts
            for m in session.message_buffer
        )
        if not other_spoke:
            score += 0.10

    return min(1.0, score)


async def _triage_continuation_haiku(session: ChannelSession, msg: BufferedMessage) -> bool:
    """
    Ask Haiku to classify whether an ambiguous message is continuing a conversation with the bot.
    Only called when heuristic score is in the ambiguous range (CONTINUATION_TRIAGE_THRESHOLD
    to CONTINUATION_FAST_THRESHOLD).
    """
    if not anthropic_client:
        return False

    recent = list(session.message_buffer)[-4:]
    lines = []
    for m in recent:
        prefix = "[Nadiabot]" if m.is_bot else f"[{m.author_name}]"
        lines.append(f"{prefix}: {m.content[:120]}")
    context = "\n".join(lines)

    prompt = (
        f"Recent chat:\n{context}\n\n"
        f"New message from [{msg.author_name}]: {msg.content}\n\n"
        "Is this new message continuing a conversation with Nadiabot — "
        "asking it something, referring to what it just said, or expecting it to respond? "
        "Reply YES or NO only."
    )
    try:
        response = await asyncio.to_thread(
            lambda: anthropic_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=5,
                messages=[{"role": "user", "content": prompt}]
            )
        )
        result = response.content[0].text.strip().upper()
        logger.debug(f"Haiku continuation triage for {msg.author_name}: {result}")
        return result.startswith("YES")
    except Exception as e:
        logger.debug(f"Haiku continuation triage failed: {e}")
        return False


async def stage1_observe(session: ChannelSession) -> StateDelta:
    """
    STAGE 1: OBSERVATION & STATE UPDATE

    Process pending messages, update metrics, detect triggers.
    """
    delta = StateDelta()
    now = datetime.now().timestamp()
    bot_id = client.user.id

    # Collect completed image interrogation results from previous ticks
    completed_ids = []
    stale_ids = []
    for msg_id, task in session.pending_image_tasks.items():
        if task.done():
            completed_ids.append(msg_id)
            try:
                description = task.result()
                if description:
                    for buf_msg in session.message_buffer:
                        if buf_msg.message_id == msg_id:
                            buf_msg.image_description = description
                            logger.info(f"Image described for msg {msg_id}: {description[:80]}...")
                            # Re-upsert to RAG with image_description in metadata
                            if RAG_AVAILABLE and RAG_ENABLED and buf_msg.message_obj is not None:
                                try:
                                    ts = buf_msg.timestamp
                                    channel_name = getattr(
                                        getattr(buf_msg.message_obj, 'channel', None),
                                        'name', 'unknown'
                                    )
                                    img_meta = {
                                        'author_id': str(buf_msg.author_id),
                                        'author_name': buf_msg.author_name,
                                        'channel_name': channel_name,
                                        'timestamp_unix': float(ts),
                                        'year_month': datetime.fromtimestamp(ts).strftime('%Y-%m'),
                                        'is_persona': 1 if str(buf_msg.author_id) in PERSONA_AUTHOR_IDS else 0,
                                        'is_reply': 1 if buf_msg.reply_to_id else 0,
                                        'reply_to_author': buf_msg.reply_context_author or '',
                                        'char_length': len(buf_msg.content),
                                        'word_count': len(buf_msg.content.split()),
                                        'image_description': description,
                                    }
                                    # Image-only messages: use description as searchable text
                                    embed_text = buf_msg.content.strip() or description
                                    asyncio.create_task(
                                        embed_live_message(str(buf_msg.message_id), embed_text, img_meta)
                                    )
                                except Exception as _e:
                                    logger.debug(f"Image RAG upsert failed for msg {msg_id}: {_e}")
                            break
            except Exception as e:
                logger.warning(f"Image interrogation task failed for msg {msg_id}: {e}")
        elif not task.done():
            # Cancel tasks that have been pending too long
            for buf_msg in session.message_buffer:
                if buf_msg.message_id == msg_id and buf_msg.age_seconds() > 30:
                    task.cancel()
                    stale_ids.append(msg_id)
                    break
    for msg_id in completed_ids + stale_ids:
        session.pending_image_tasks.pop(msg_id, None)

    # Process pending messages
    for msg in session.pending_messages:
        buffered = BufferedMessage(
            message_id=msg.id,
            author_id=msg.author.id,
            author_name=msg.author.display_name,
            content=msg.content,
            timestamp=msg.created_at.timestamp() if hasattr(msg.created_at, 'timestamp') else now,
            is_bot=(msg.author.id == bot_id),
            reply_to_id=msg.message_reference.message_id if msg.message_reference else None,
            message_obj=msg
        )

        # Resolve reply chain context (buffer lookup, then referenced_message)
        if buffered.reply_to_id:
            _resolve_reply_context(buffered, session, msg)

            # On-demand image scan for the referenced message.
            # Mood-gating is bypassed here — someone explicitly replying to an image
            # (especially via @mention) means we should analyze it regardless of mood.
            ref_id = buffered.reply_to_id
            ref_already_scanned = any(
                m.image_description
                for m in session.message_buffer if m.message_id == ref_id
            )
            if (not buffered.is_bot
                    and not ref_already_scanned
                    and ref_id not in session.pending_image_tasks
                    and VISION_ENABLED and VISION_AVAILABLE
                    and len(session.pending_image_tasks) < 3):
                ref_msg = getattr(msg, 'referenced_message', None)
                if ref_msg and hasattr(ref_msg, 'attachments') and ref_msg.attachments:
                    for att in ref_msg.attachments:
                        if (hasattr(att, 'content_type')
                                and att.content_type
                                and att.content_type.split(';')[0].strip() in IMAGE_CONTENT_TYPES):
                            # Check RAG cache before spending CLIP time
                            cached_desc = _get_rag_image_desc(ref_id)
                            if cached_desc:
                                # Populate buffer message if still present
                                for m in session.message_buffer:
                                    if m.message_id == ref_id:
                                        m.image_description = cached_desc
                                        break
                                logger.debug(
                                    f"Reply image found in RAG cache for msg {ref_id}"
                                )
                            else:
                                task = asyncio.create_task(
                                    describe_image_from_url(att.url, timeout_seconds=VISION_TIMEOUT)
                                )
                                session.pending_image_tasks[ref_id] = task
                                logger.info(
                                    f"Image scan launched for referenced message "
                                    f"(replier: {buffered.author_name})"
                                )
                            break

        session.add_message(buffered)
        delta.new_messages.append(buffered)

        # Check for image attachments and launch async CLIP interrogation
        if (not buffered.is_bot
                and hasattr(msg, 'attachments') and msg.attachments
                and len(session.pending_image_tasks) < 3):
            for attachment in msg.attachments:
                if (hasattr(attachment, 'content_type')
                        and attachment.content_type
                        and attachment.content_type.split(';')[0].strip() in IMAGE_CONTENT_TYPES):
                    task = asyncio.create_task(
                        describe_image_from_url(attachment.url, timeout_seconds=VISION_TIMEOUT)
                    )
                    session.pending_image_tasks[buffered.message_id] = task
                    logger.info(
                        f"Image scan launched for {buffered.author_name}'s attachment "
                        f"({attachment.content_type}, mood={session.mood.value})"
                    )
                    break  # Only process first image per message

        # Check for image/GIF embeds (Tenor, Giphy, etc.) - these aren't attachments
        if (not buffered.is_bot
                and buffered.message_id not in session.pending_image_tasks
                and hasattr(msg, 'embeds') and msg.embeds
                and len(session.pending_image_tasks) < 3):
            for embed in msg.embeds:
                embed_image_url = _extract_embed_image_url(embed)
                if embed_image_url:
                    task = asyncio.create_task(
                        describe_image_from_url(embed_image_url, timeout_seconds=VISION_TIMEOUT)
                    )
                    session.pending_image_tasks[buffered.message_id] = task
                    logger.info(
                        f"Image scan launched for {buffered.author_name}'s embed "
                        f"(type={getattr(embed, 'type', '?')}, mood={session.mood.value})"
                    )
                    break  # Only process first embed image per message

        # Skip trigger detection for bot's own messages
        if buffered.is_bot:
            continue

        # ===== TRIGGER DETECTION =====
        # Check for priority triggers that demand immediate response
        
        content_lower = buffered.content.lower()
        
        # 1. Direct @mention of the bot - highest priority
        #    When already engaged with a focus user, reduce chance for non-priority users
        #    to prevent the bot from jumping at every @mention in a busy chat
        is_mentioned = f"<@{bot_id}>" in buffered.content or f"<@!{bot_id}>" in buffered.content
        if is_mentioned:
            should_trigger = True

            # Gate non-focus, non-priority mentions when we're already engaged
            if session.mood in (MoodState.ENGAGED, MoodState.HEATED) and session.is_focus_active():
                if not session.is_focus_target(buffered.author_id):
                    user = session.users.get(buffered.author_id)
                    is_priority = user and user.classification in ("opp", "friend", "real_user")
                    if not is_priority:
                        # 35% chance to respond to random @mention when already focused
                        should_trigger = random.random() < 0.35
                        if not should_trigger:
                            logger.debug(
                                f"Trigger: @mention from {buffered.author_name} suppressed "
                                f"(focused on {session.engagement_focus_user_id})"
                            )

            if should_trigger:
                delta.priority_triggers.append(("mention", buffered))
                delta.bot_was_mentioned = True
                logger.debug(f"Trigger: @mention detected from {buffered.author_name}")
                # Check if the mention also carries behavior content - escalate trigger type
                _bot_spoke = any(m.is_bot for m in session.message_buffer)
                if detect_ai_accusation(buffered.content, _bot_spoke) or detect_not_nadia(buffered.content):
                    delta.priority_triggers[-1] = ("ai_accusation", buffered)
                    logger.debug(f"Trigger: AI accusation (via mention) from {buffered.author_name}")
                elif detect_antagonist(buffered.content):
                    delta.priority_triggers[-1] = ("antagonist", buffered)
                    logger.debug(f"Trigger: Antagonist (via mention) from {buffered.author_name}")
                elif detect_direct_mute_request(buffered.content):
                    delta.priority_triggers[-1] = ("direct_mute_request", buffered)
                    logger.debug(f"Trigger: Direct mute request (via mention) from {buffered.author_name}")
            continue  # Don't check other triggers for same message
        
        # 2. Reply to bot's message - high priority
        if buffered.reply_to_id:
            # Check if replying to one of the bot's messages in the buffer
            reply_to_bot = False
            for prev_msg in session.message_buffer:
                if prev_msg.message_id == buffered.reply_to_id and prev_msg.is_bot:
                    delta.priority_triggers.append(("reply_to_bot", buffered))
                    delta.bot_was_replied_to = True
                    reply_to_bot = True
                    logger.debug(f"Trigger: Reply to bot detected from {buffered.author_name}")
                    break
            if reply_to_bot:
                # Check if the reply also carries behavior content - escalate trigger type
                # bot_spoke_recently is trivially True here (someone is replying to the bot)
                if detect_ai_accusation(buffered.content, True) or detect_not_nadia(buffered.content):
                    delta.priority_triggers[-1] = ("ai_accusation", buffered)
                    logger.debug(f"Trigger: AI accusation (via bot reply) from {buffered.author_name}")
                elif detect_antagonist(buffered.content):
                    delta.priority_triggers[-1] = ("antagonist", buffered)
                    logger.debug(f"Trigger: Antagonist (via bot reply) from {buffered.author_name}")
                elif detect_direct_mute_request(buffered.content):
                    delta.priority_triggers[-1] = ("direct_mute_request", buffered)
                    logger.debug(f"Trigger: Direct mute request (via bot reply) from {buffered.author_name}")
                continue  # Don't check other triggers
        
        # 3. Name mention (nadiabot or nadia) - with probability check
        #    When already engaged with a focus, reduce chance further to avoid over-responding
        name_mentioned = False
        # Modifier: 30% of normal trigger chance when already focused on someone
        engaged_modifier = 1.0
        if session.mood in (MoodState.ENGAGED, MoodState.HEATED) and session.is_focus_active():
            engaged_modifier = 0.3

        for name in TRIGGER_NAMES_HIGH:  # "nadiabot" etc - higher chance
            if name.lower() in content_lower:
                if random.random() < (TRIGGER_CHANCE_HIGH * engaged_modifier):
                    delta.priority_triggers.append(("name_mention_high", buffered))
                    delta.name_was_mentioned = True
                    name_mentioned = True
                    logger.debug(f"Trigger: High-priority name '{name}' detected from {buffered.author_name}")
                break
        
        if not name_mentioned:
            for name in TRIGGER_NAMES_LOW:  # "nadia" etc - lower chance
                if name.lower() in content_lower:
                    if random.random() < (TRIGGER_CHANCE_LOW * engaged_modifier):
                        delta.priority_triggers.append(("name_mention_low", buffered))
                        delta.name_was_mentioned = True
                        name_mentioned = True
                        logger.debug(f"Trigger: Low-priority name '{name}' detected from {buffered.author_name}")
                    break
        
        if name_mentioned:
            # Check if the name mention also carries behavior content - escalate trigger type
            _bot_spoke = any(m.is_bot for m in session.message_buffer)
            if detect_ai_accusation(buffered.content, _bot_spoke) or detect_not_nadia(buffered.content):
                delta.priority_triggers[-1] = ("ai_accusation", buffered)
                logger.debug(f"Trigger: AI accusation (via name mention) from {buffered.author_name}")
            elif detect_antagonist(buffered.content):
                delta.priority_triggers[-1] = ("antagonist", buffered)
                logger.debug(f"Trigger: Antagonist (via name mention) from {buffered.author_name}")
            elif detect_direct_mute_request(buffered.content):
                delta.priority_triggers[-1] = ("direct_mute_request", buffered)
                logger.debug(f"Trigger: Direct mute request (via name mention) from {buffered.author_name}")
            continue  # Don't check other triggers
        
        # 4. AI accusation detection - adds to diva tracking
        # Also treat "you're not nadia" style denial as equivalent to AI accusation
        # For generic AI keywords (chatgpt, bot, etc), only trigger if the bot
        # was part of the recent conversation - avoids false positives when people
        # talk about AI/chatgpt in general without targeting the bot
        bot_spoke_recently = any(m.is_bot for m in session.message_buffer)
        if detect_ai_accusation(buffered.content, bot_spoke_recently) or detect_not_nadia(buffered.content):
            delta.priority_triggers.append(("ai_accusation", buffered))
            logger.debug(f"Trigger: AI accusation detected from {buffered.author_name}")
            continue
        
        # 5. Antagonistic behavior - adds to diva tracking  
        if detect_antagonist(buffered.content):
            delta.priority_triggers.append(("antagonist", buffered))
            logger.debug(f"Trigger: Antagonist behavior detected from {buffered.author_name}")
            continue
        
        # 6. Direct mute request - immediate diva read
        if detect_direct_mute_request(buffered.content):
            delta.priority_triggers.append(("direct_mute_request", buffered))
            logger.debug(f"Trigger: Direct mute request from {buffered.author_name}")
            continue

        # 7. Soft continuation — focus user spoke without any explicit trigger
        # Gate: must be the active engagement focus user within the response window
        _now_ts = datetime.now().timestamp()
        _time_since_response = _now_ts - session.last_response_to_user.get(buffered.author_id, 0)
        if (session.is_focus_target(buffered.author_id)
                and _time_since_response < session.ENGAGEMENT_FOCUS_DURATION):
            cont_score = _score_continuation_likelihood(session, buffered)
            if cont_score >= CONTINUATION_FAST_THRESHOLD:
                delta.priority_triggers.append(("soft_continuation", buffered))
                logger.debug(
                    f"Trigger: soft continuation (heuristic={cont_score:.2f}) "
                    f"from {buffered.author_name}"
                )
            elif cont_score >= CONTINUATION_TRIAGE_THRESHOLD:
                is_continuation = await _triage_continuation_haiku(session, buffered)
                if is_continuation:
                    delta.priority_triggers.append(("soft_continuation", buffered))
                    logger.debug(
                        f"Trigger: soft continuation (Haiku triage, heuristic={cont_score:.2f}) "
                        f"from {buffered.author_name}"
                    )

    session.pending_messages.clear()

    # Calculate metric deltas
    delta.temperature_delta, delta.energy_delta = _calculate_metric_deltas(session, delta.new_messages)

    # Store previous values for logging
    prev_temp = session.metrics.temperature
    prev_energy = session.metrics.energy
    prev_mood = session.mood

    # Apply metric updates
    session.metrics.temperature = max(0.0, min(1.0,
        session.metrics.temperature + delta.temperature_delta
    ))
    session.metrics.energy = max(0.0, min(1.0,
        session.metrics.energy + delta.energy_delta
    ))

    # Update mood
    session.mood = _determine_mood(session, delta)

    # Store priority triggers
    session.priority_triggers.extend(delta.priority_triggers)

    # IMPROVED LOGGING: Always log state after processing messages
    if delta.new_messages:
        user_msgs = [m for m in delta.new_messages if not m.is_bot]
        trigger_summary = ", ".join([t[0] for t in delta.priority_triggers]) if delta.priority_triggers else "none"

        # Build message previews (first 50 chars of each)
        msg_previews = []
        for m in user_msgs:
            preview = m.content[:50].replace('\n', ' ')
            if len(m.content) > 50:
                preview += "..."
            msg_previews.append(f"<{m.author_name}> {preview}")
        previews_str = " | ".join(msg_previews) if msg_previews else ""

        logger.info(
            f"Stage 1: Observed {len(user_msgs)} user msgs | "
            f"triggers=[{trigger_summary}] | "
            f"temp={prev_temp:.2f}->{session.metrics.temperature:.2f} | "
            f"energy={prev_energy:.2f}->{session.metrics.energy:.2f} | "
            f"mood={prev_mood.value}->{session.mood.value}"
        )
        if previews_str:
            logger.info(f"  └─ msgs: {previews_str}")

    return delta


def _calculate_metric_deltas(session: ChannelSession, new_messages: list) -> tuple[float, float]:
    """Calculate temperature and energy changes based on new messages."""
    temp_delta = -session.TEMPERATURE_DECAY_RATE
    energy_delta = -session.ENERGY_DECAY_RATE

    bot_id = client.user.id

    for msg in new_messages:
        if msg.is_bot:
            continue

        # Temperature increases with message activity (reduced from 0.04 to prevent perma-heated)
        temp_delta += 0.015

        # Energy increases when bot is engaged with (reduced from 0.13)
        if msg.reply_to_id:
            for prev in session.message_buffer:
                if prev.message_id == msg.reply_to_id and prev.is_bot:
                    energy_delta += 0.06
                    break

        # Mentions spike energy (reduced from 0.18)
        if f"<@{bot_id}>" in msg.content or f"<@!{bot_id}>" in msg.content:
            energy_delta += 0.08

        # Drama/conflict increases temperature (reduced from 0.08)
        if detect_antagonist(msg.content):
            temp_delta += 0.04

    return temp_delta, energy_delta


def _determine_mood(session: ChannelSession, delta: StateDelta) -> MoodState:
    """Determine bot's mood based on session state."""
    metrics = session.metrics

    # High energy + high temp = HEATED
    if metrics.energy > 0.7 and metrics.temperature > 0.7:
        return MoodState.HEATED

    # Recent engagement = ENGAGED
    time_since_bot_spoke = datetime.now().timestamp() - metrics.last_bot_message_time
    if time_since_bot_spoke < 120 and metrics.energy > 0.4:
        return MoodState.ENGAGED

    # Low energy = BORED (regardless of temp - active server + low engagement = ragebait time)
    if metrics.energy < 0.3:
        return MoodState.BORED

    return MoodState.LURKING


async def stage2_select_action(session: ChannelSession, delta: StateDelta) -> NewActionPlan:
    """
    STAGE 2: ACTION SELECTION

    Decide what action to take based on priority triggers or opportunities.
    """
    plan = NewActionPlan()

    # Check cooldown - bypass for urgent behavior triggers (diva/accusation scenarios)
    if session.is_on_cooldown():
        has_bypass = any(t[0] in COOLDOWN_BYPASS_TRIGGERS for t in session.priority_triggers)
        if not has_bypass:
            cooldown_remaining = session.response_cooldown_until - datetime.now().timestamp()
            logger.debug(f"Stage 2: On cooldown ({cooldown_remaining:.1f}s remaining)")
            plan.reason = "on_cooldown"
            return plan
        logger.debug(f"Stage 2: Cooldown bypassed by urgent trigger")

    # Post-response suppression: briefly block organic opportunities after responding.
    # Priority triggers (direct @mentions, replies to bot) still get through.
    if session.is_post_response_suppressed() and not session.priority_triggers:
        logger.debug(f"Stage 2: Post-response suppressed (no priority triggers)")
        plan.reason = "post_response_suppressed"
        return plan

    # Expire stale engagement focus (side effect of checking)
    session.is_focus_active()

    # Priority trigger handling - skip any triggers for messages we've already responded to
    while session.priority_triggers:
        trigger_type, trigger_msg = session.priority_triggers.pop(0)
        if trigger_msg.message_id in session.responded_to_message_ids:
            logger.debug(f"Skipping priority trigger '{trigger_type}': already responded to msg {trigger_msg.message_id}")
            continue

        # Per-user cooldown for priority triggers (shorter than organic opportunities)
        # Opps bypass this entirely - we always want to engage with them
        user = session.users.get(trigger_msg.author_id)
        classification = user.classification if user else "neutral"
        if classification != "opp":
            now = datetime.now().timestamp()
            last_response = session.last_response_to_user.get(trigger_msg.author_id, 0)
            if (now - last_response) < session.USER_COOLDOWN_PRIORITY_SECONDS:
                logger.debug(f"Skipping priority trigger '{trigger_type}': user on cooldown ({now - last_response:.1f}s < {session.USER_COOLDOWN_PRIORITY_SECONDS}s)")
                continue

        # Found a valid trigger
        plan.should_act = True
        plan.action_type = ActionType.REPLY
        plan.target_message = trigger_msg
        plan.target_user_id = trigger_msg.author_id
        plan.target_user_name = trigger_msg.author_name
        plan.priority_trigger = trigger_type
        plan.reason = trigger_type

        # Apply user treatment (friend/opp/etc)
        if plan.target_user_id:
            plan = _apply_user_treatment_new(session, plan.target_user_id, plan)

        # Handle specific trigger types
        if trigger_type == "mention":
            plan.prompt_additions.append("Someone @mentioned you directly. Respond to what they said.")
        
        elif trigger_type == "reply_to_bot":
            plan.prompt_additions.append("Someone replied to your message. Continue the conversation naturally.")
        
        elif trigger_type in ("name_mention_high", "name_mention_low"):
            plan.prompt_additions.append("Someone mentioned your name. Respond if relevant, be dismissive if they're just attention-seeking.")
        
        elif trigger_type == "ai_accusation":
            plan = await _handle_ai_accusation_trigger(session, trigger_msg, plan)
        
        elif trigger_type == "antagonist":
            tracker = track_diva_behavior(trigger_msg.author_id, "antagonist")
            if tracker["count"] >= DIVA_READ_THRESHOLD:
                plan.action_type = ActionType.DIVA_READ
                plan.execute_diva_mute = True
                plan.diva_reason = "antagonist"
            elif tracker["count"] >= DIVA_READ_WARN_AT:
                plan.prompt_additions.append("This person is being hostile. Warn them they're on thin ice.")
            else:
                plan.prompt_additions.append("This person is being hostile. Clap back hard.")
        
        elif trigger_type == "direct_mute_request":
            plan.action_type = ActionType.DIVA_READ
            plan.execute_diva_mute = True
            plan.diva_reason = "direct_request"

        elif trigger_type == "soft_continuation":
            plan.prompt_additions.append(
                "The user is continuing their conversation with you without an explicit @mention — "
                "they appear to be addressing you directly. Respond naturally."
            )

        # If the trigger message has an image description, include it for Claude
        if trigger_msg.image_description:
            plan.prompt_additions.append(
                _build_image_prompt_addition(
                    trigger_msg.image_description,
                    reason=trigger_type,
                    author_name=trigger_msg.author_name,
                    user_id=trigger_msg.author_id,
                    message_text=trigger_msg.content or "",
                )
            )

        logger.info(
            f"Stage 2: Priority trigger '{trigger_type}' | "
            f"target={plan.target_user_name} | "
            f"treatment={plan.treatment} | "
            f"diva_mute={plan.execute_diva_mute}"
        )
        return plan

    # Opportunity scanning
    opportunities = _scan_for_opportunities(session, delta)

    if not opportunities:
        logger.debug(f"Stage 2: No opportunities found")
        plan.reason = "no_opportunities"
        return plan

    # Score opportunities
    for opp in opportunities:
        opp.relevance_score = _score_relevance(session, opp)
        opp.mood_alignment = _score_mood_alignment(session, opp)
        opp.freshness_score = _score_freshness(opp)

    opportunities.sort(key=lambda o: o.total_score, reverse=True)

    best = opportunities[0]
    OPPORTUNITY_THRESHOLD = 0.45

    if best.total_score < OPPORTUNITY_THRESHOLD:
        logger.debug(
            f"Stage 2: Best opportunity '{best.reason}' below threshold "
            f"(score={best.total_score:.2f} < {OPPORTUNITY_THRESHOLD})"
        )
        plan.reason = f"below_threshold ({best.total_score:.2f})"
        return plan

    # Convert to action plan
    plan.should_act = True
    plan.action_type = best.action_type
    plan.target_message = best.target_message
    plan.target_user_id = best.target_user_id
    if best.target_user_id and best.target_user_id in session.users:
        plan.target_user_name = session.users[best.target_user_id].display_name
    plan.reason = best.reason
    plan.selected_opportunity = best

    # Carry RAG context for bored_interjection opportunities (when RAG found a match)
    if best.reason == "bored_interjection" and best.rag_context:
        plan.rag_context = best.rag_context
        plan.prompt_additions.append(
            "Something from a past conversation just clicked. Drop one sharp take - "
            "reference it, make a connection, or call someone out. One sentence, in your voice. "
            "Don't announce you're remembering."
        )

    # Image context: use type-aware prompt builder for all image opportunity types
    if (best.reason in ("image_roast", "meme_reaction", "image_reaction")
            and best.target_message and best.target_message.image_description):
        target_name = best.target_message.author_name if best.target_message else ""
        plan.prompt_additions.append(
            _build_image_prompt_addition(
                best.target_message.image_description,
                reason=best.reason,
                author_name=target_name,
                user_id=best.target_user_id,
                message_text=best.target_message.content or "",
            )
        )
        # Carry RAG context for image_reaction opportunities
        if best.rag_context:
            plan.rag_context = best.rag_context

    if plan.target_user_id:
        plan = _apply_user_treatment_new(session, plan.target_user_id, plan)

    logger.info(
        f"Stage 2: Opportunity '{best.reason}' | "
        f"score={best.total_score:.2f} (rel={best.relevance_score:.2f} Ã— "
        f"mood={best.mood_alignment:.2f} Ã— fresh={best.freshness_score:.2f}) | "
        f"target={plan.target_user_name or 'channel'}"
    )
    return plan


async def _handle_ai_accusation_trigger(session: ChannelSession, trigger_msg: BufferedMessage, plan: NewActionPlan) -> NewActionPlan:
    """Handle AI accusation with diva tracking."""
    user_id = trigger_msg.author_id
    tracker = track_diva_behavior(user_id, "ai_accusation")

    plan.reason = "ai_accusation"

    if tracker["count"] >= DIVA_READ_THRESHOLD:
        plan.action_type = ActionType.DIVA_READ
        plan.execute_diva_mute = True
        plan.diva_reason = "ai_accusation"
    elif tracker["count"] >= DIVA_READ_WARN_AT:
        plan.prompt_additions.append("Warn this person they're getting on your nerves and to drop it.")
    else:
        # First offense - use special handling
        roll = random.random()
        if roll < FIRST_ACCUSATION_DEFLECT_CHANCE:
            plan.prompt_additions.append("Deflect and dismiss the accusation casually.")
        elif roll < FIRST_ACCUSATION_DEFLECT_CHANCE + FIRST_ACCUSATION_IGNORE_CHANCE:
            plan.should_act = False
            plan.reason = "ignoring_first_accusation"
        elif roll < FIRST_ACCUSATION_DEFLECT_CHANCE + FIRST_ACCUSATION_IGNORE_CHANCE + FIRST_ACCUSATION_MONEY_INSULT_CHANCE:
            plan.prompt_additions.append(f"Respond with: {random.choice(FIRST_ACCUSATION_MONEY_INSULTS)}")
        else:
            plan.prompt_additions.append(f"Respond with: {random.choice(FIRST_ACCUSATION_WOMAN_INSULTS)}")

    return plan


def extract_buffer_keywords(session: ChannelSession, max_messages: int = 6) -> list[str]:
    """
    Extract meaningful keywords/nouns from recent buffer messages for RAG query.
    
    Filters out bot messages, stopwords, and Discord formatting artifacts.
    Returns top keywords by frequency, which can be used to query RAG
    for relevant past conversations.
    """
    stopwords = {
        'the', 'a', 'an', 'is', 'it', 'to', 'of', 'and', 'i', 'you', 'that', 'in',
        'for', 'on', 'with', 'this', 'be', 'are', 'was', 'have', 'has', 'my', 'me',
        'your', 'but', 'not', 'so', 'just', 'like', 'im', 'its', 'do', 'if', 'or',
        'at', 'as', 'can', 'all', 'what', 'they', 'we', 'he', 'she', 'from', 'her',
        'his', 'u', 'ur', 'dont', 'cant', 'yeah', 'yea', 'yes', 'no', 'ok', 'lol',
        'gonna', 'wanna', 'really', 'very', 'too', 'also', 'get', 'got', 'know',
        'think', 'see', 'say', 'said', 'one', 'would', 'could', 'about', 'out',
        'been', 'being', 'much', 'more', 'some', 'any', 'how', 'than', 'then',
        'now', 'here', 'there', 'when', 'why', 'who', 'which', 'where', 'them',
        'these', 'those', 'only', 'own', 'same', 'did', 'had', 'does', 'will',
        'going', 'into', 'way', 'well', 'thing', 'things', 'make', 'made',
        'still', 'even', 'good', 'bad', 'people', 'idk', 'tbh', 'ngl', 'lmao',
        'bruh', 'omg', 'wtf', 'tho', 'tho', 'rn', 'imo', 'smh', 'btw', 'kinda',
    }
    
    from collections import Counter
    word_freq = Counter()
    
    # Only look at recent non-bot messages
    recent = [m for m in list(session.message_buffer)[-max_messages:] if not m.is_bot]
    
    for msg in recent:
        content = msg.content.lower()
        # Strip Discord formatting: mentions, custom emojis, URLs
        content = re.sub(r'<@!?\d+>', '', content)
        content = re.sub(r'<a?:\w+:\d+>', '', content)
        content = re.sub(r'https?://\S+', '', content)
        content = re.sub(r'[^\w\s]', ' ', content)
        
        words = content.split()
        # Keep words that are 3+ chars, not stopwords, not pure numbers
        words = [w for w in words if len(w) > 2 and w not in stopwords and not w.isdigit()]
        word_freq.update(words)
    
    # Return top keywords sorted by frequency
    return [word for word, _ in word_freq.most_common(8)]


def get_rag_for_conversation(session: ChannelSession) -> tuple[str, str]:
    """
    Query RAG using keywords from current conversation buffer.
    
    Extracts keywords from recent chat, builds a semantic query,
    and retrieves relevant past messages from the RAG database.
    
    Returns:
        (rag_context, query_used) - the formatted RAG context string
        and the query that was used, or ("", "") if nothing found.
    """
    if not RAG_ENABLED or not RAG_AVAILABLE:
        return "", ""
    
    keywords = extract_buffer_keywords(session)
    if len(keywords) < 2:
        # Not enough substance to query on
        return "", ""
    
    # Build a natural query from top keywords for better semantic matching
    query = " ".join(keywords[:5])
    
    try:
        rag_context = get_smart_context(query, top_k=5)
        if rag_context:
            logger.info(f"RAG interjection: query='{query}' returned context")
            rag_lines = [l for l in rag_context.split('\n') if l.strip().startswith(('1.', '2.', '3.', '4.', '5.'))]
            for line in rag_lines:
                preview = line[:80].replace('\n', ' ')
                if len(line) > 80:
                    preview += "..."
                logger.info(f"  └─ {preview}")
            return rag_context, query
        else:
            logger.debug(f"RAG interjection: query='{query}' returned no useful context")
            return "", ""
    except Exception as e:
        logger.warning(f"RAG interjection query failed: {e}")
        return "", ""


def _scan_for_opportunities(session: ChannelSession, delta: StateDelta) -> list[ActionOpportunity]:
    """
    Scan session state for action opportunities.
    
    When engaged/heated with a focus target, filters out neutral non-focus users
    to prevent the bot from replying to everyone in a busy chat.
    Opps, friends, and real_user always get through the filter.
    """
    opportunities = []

    # Check if engagement focus should filter opportunities
    focus_active = (
        session.is_focus_active()
        and session.mood in (MoodState.ENGAGED, MoodState.HEATED)
    )

    # Look at recent messages for reply opportunities
    recent_msgs = list(session.message_buffer)[-5:]

    now = datetime.now().timestamp()

    for msg in recent_msgs:
        if msg.is_bot:
            continue
        if msg.age_seconds() > 60:
            continue
        # Skip messages we've already responded to
        if msg.message_id in session.responded_to_message_ids:
            continue

        user = session.users.get(msg.author_id)
        classification = user.classification if user else "neutral"

        # Per-user cooldown check - skip if we responded to this user recently
        # Opps bypass this check (we always want to engage with them)
        if classification != "opp":
            last_response = session.last_response_to_user.get(msg.author_id, 0)
            if (now - last_response) < session.USER_COOLDOWN_SECONDS:
                continue

        # When focus is active, skip neutral non-focus users entirely
        # Opps/friends/real_user always get considered for engagement
        if focus_active and classification == "neutral":
            if not session.is_focus_target(msg.author_id):
                continue

        # Opp engagement opportunity
        if classification == "opp":
            opportunities.append(ActionOpportunity(
                action_type=ActionType.REPLY,
                target_user_id=msg.author_id,
                target_message=msg,
                reason="opp_engagement"
            ))

        # Interesting topic opportunity
        if _is_interesting_topic(msg.content):
            opportunities.append(ActionOpportunity(
                action_type=ActionType.REPLY,
                target_user_id=msg.author_id,
                target_message=msg,
                reason="interesting_topic"
            ))

        # Random engagement chance (5%) - disabled when focused
        if not focus_active and random.random() < 0.05:
            opportunities.append(ActionOpportunity(
                action_type=ActionType.REPLY,
                target_user_id=msg.author_id,
                target_message=msg,
                reason="random_engagement"
            ))

        # Image-based opportunity - uses [TYPE] tag from combined CLIP+Florence pipeline
        if msg.image_description and _should_react_to_image(session, msg.author_id):
            img_type = _parse_image_type_tag(msg.image_description)

            # Skip screenshots entirely - bot doesn't react to discord/browser screenshots
            if img_type == "screenshot":
                continue

            # Opp + heated = roast opportunity regardless of image type
            if session.mood == MoodState.HEATED and classification == "opp":
                opportunities.append(ActionOpportunity(
                    action_type=ActionType.REPLY,
                    target_user_id=msg.author_id,
                    target_message=msg,
                    reason="image_roast"
                ))
            # Memes are inherently engaging social objects
            elif img_type == "meme":
                opportunities.append(ActionOpportunity(
                    action_type=ActionType.REPLY,
                    target_user_id=msg.author_id,
                    target_message=msg,
                    reason="meme_reaction"
                ))
            # Selfies, food, fashion, travel - topics Nadia cares about
            elif img_type in ("selfie", "food", "fashion", "travel", "medical"):
                rag_context = ""
                if RAG_ENABLED and RAG_AVAILABLE:
                    try:
                        from rag.retriever import get_relevant_messages
                        rag_msgs = get_relevant_messages(msg.image_description[:200], top_k=3)
                        if rag_msgs:
                            rag_context = "## Relevant past messages about this topic:\n"
                            for i, rm in enumerate(rag_msgs, 1):
                                rag_context += f'{i}. "{rm.replace(chr(34), chr(39))}"\n'
                    except Exception:
                        pass
                opportunities.append(ActionOpportunity(
                    action_type=ActionType.REPLY,
                    target_user_id=msg.author_id,
                    target_message=msg,
                    reason="image_reaction",
                    rag_context=rag_context
                ))
            # Other image types: only engage if it's from a priority user
            # or the content is topically interesting
            elif (classification in ("friend", "opp", "real_user")
                    or _is_interesting_topic(msg.image_description)):
                rag_context = ""
                if _is_interesting_topic(msg.image_description) and RAG_ENABLED and RAG_AVAILABLE:
                    try:
                        from rag.retriever import get_relevant_messages
                        rag_msgs = get_relevant_messages(msg.image_description[:200], top_k=3)
                        if rag_msgs:
                            rag_context = "## Relevant past messages about this topic:\n"
                            for i, rm in enumerate(rag_msgs, 1):
                                rag_context += f'{i}. "{rm.replace(chr(34), chr(39))}"\n'
                    except Exception:
                        pass
                opportunities.append(ActionOpportunity(
                    action_type=ActionType.REPLY,
                    target_user_id=msg.author_id,
                    target_message=msg,
                    reason="image_reaction",
                    rag_context=rag_context
                ))

            if session.mood == MoodState.HEATED and classification == "opp":
                opportunities.append(ActionOpportunity(
                    action_type=ActionType.REPLY,
                    target_user_id=msg.author_id,
                    target_message=msg,
                    reason="image_roast"
                ))
            elif "[MEME" in msg.image_description:
                # Memes are inherently engaging social objects
                opportunities.append(ActionOpportunity(
                    action_type=ActionType.REPLY,
                    target_user_id=msg.author_id,
                    target_message=msg,
                    reason="meme_reaction"
                ))
            elif _is_interesting_topic(msg.image_description) or classification in ("friend", "opp", "real_user"):
                # Optionally pull RAG context using image description as query
                rag_context = ""
                if _is_interesting_topic(msg.image_description) and RAG_ENABLED and RAG_AVAILABLE:
                    try:
                        from rag.retriever import get_relevant_messages
                        rag_msgs = get_relevant_messages(msg.image_description[:200], top_k=3)
                        if rag_msgs:
                            rag_context = "## Relevant past messages about this topic:\n"
                            for i, rm in enumerate(rag_msgs, 1):
                                rag_context += f'{i}. "{rm.replace(chr(34), chr(39))}"\n'
                    except Exception:
                        pass
                opportunities.append(ActionOpportunity(
                    action_type=ActionType.REPLY,
                    target_user_id=msg.author_id,
                    target_message=msg,
                    reason="image_reaction",
                    rag_context=rag_context
                ))

    # Bored interjection opportunity - only when NOT focused on a conversation
    # Rate-limited to once per 30 minutes to prevent spam
    bored_cooldown_elapsed = (datetime.now().timestamp() - session.last_bored_interjection_time) > session.BORED_INTERJECTION_COOLDOWN
    if (not focus_active
            and session.mood == MoodState.BORED
            and session.metrics.energy > 0.2
            and len(session.message_buffer) > 3
            and bored_cooldown_elapsed):
        # Try to pull RAG context for a more grounded take; fall back to plain quip
        rag_context, _ = get_rag_for_conversation(session)
        reply_target = None
        if rag_context:
            for msg in reversed(list(session.message_buffer)):
                if not msg.is_bot and msg.age_seconds() < 90:
                    if msg.message_id not in session.responded_to_message_ids:
                        reply_target = msg
                        break
        opportunities.append(ActionOpportunity(
            action_type=ActionType.REPLY if reply_target else ActionType.NEW_MESSAGE,
            target_user_id=reply_target.author_id if reply_target else None,
            target_message=reply_target,
            reason="bored_interjection",
            rag_context=rag_context if rag_context else None,
        ))

    return opportunities


def _score_relevance(session: ChannelSession, opp: ActionOpportunity) -> float:
    """Score how relevant an opportunity is."""
    scores = {
        "opp_engagement": 0.7,
        "interesting_topic": 0.5,
        "random_engagement": 0.3,
        "bored_interjection": 0.7,  # Includes RAG context when available
        "image_reaction": 0.65,
        "image_roast": 0.8,       # Visual roasts are premium content
        "meme_reaction": 0.7 # good engagement material
    }
    return scores.get(opp.reason, 0.5)


def _score_mood_alignment(session: ChannelSession, opp: ActionOpportunity) -> float:
    """Score how well opportunity aligns with bot's mood."""
    alignment = {
        MoodState.LURKING: {"opp_engagement": 0.4, "interesting_topic": 0.5, "random_engagement": 0.3, "bored_interjection": 0.3, "image_reaction": 0.7, "image_roast": 0.4, "meme_reaction": 0.5},
        MoodState.ENGAGED: {"opp_engagement": 0.8, "interesting_topic": 0.8, "random_engagement": 0.5, "bored_interjection": 0.5, "image_reaction": 0.85, "image_roast": 0.8, "meme_reaction": 0.7},
        MoodState.HEATED: {"opp_engagement": 0.9, "interesting_topic": 0.5, "random_engagement": 0.3, "bored_interjection": 0.3, "image_reaction": 0.5, "image_roast": 0.95, "meme_reaction": 0.7},
        MoodState.BORED: {"opp_engagement": 0.5, "interesting_topic": 0.6, "random_engagement": 0.4, "bored_interjection": 0.9, "image_reaction": 0.65, "image_roast": 0.5, "meme_reaction": 0.6},
    }
    return alignment.get(session.mood, {}).get(opp.reason, 0.5)


def _score_freshness(opp: ActionOpportunity) -> float:
    """Score based on how recent the opportunity is."""
    if opp.target_message is None:
        return 0.8
    age = opp.target_message.age_seconds()
    return max(0.1, 1.0 * (0.5 ** (age / 30)))


def _is_interesting_topic(content: str) -> bool:
    """Check if message content matches topics Nadia would engage with."""
    keywords = [
        # Fashion/beauty
        "fashion", "makeup", "outfit", "wig", "hair", "nails", "skincare",
        # Drama/social
        "drama", "tea", "gossip", "shade", "slay", "serve", "ate",
        # Money/business
        "money", "invest", "stock", "market", "salary", "rent", "afford",
        "housing", "real estate", "property", "hustle", "career",
        # Trans community
        "transition", "hrt", "passing", "boymoder", "girlmode", "surgery",
        # Dating/relationships
        "dating", "boyfriend", "tinder", "hinge", "relationship",
        # Sex work (her industry)
        "escort", "onlyfans", "client", "sex work",
        # Politics/social issues
        "trump", "biden", "election", "policy", "immigration", "housing",
        "USA", "israel", "zionists","muslims","islam","mossad", "NGO",
        "capitalism","socialism","economy"
        # Recent contreversies
        "charlie kirk", "kirk", "epstein","rowling"
    ]
    content_lower = content.lower()
    return any(kw in content_lower for kw in keywords)


def _extract_embed_image_url(embed) -> Optional[str]:
    """
    Extract a downloadable image URL from a Discord embed.
    Handles Tenor/Giphy GIFs (type=gifv) and image embeds (type=image).
    Returns thumbnail URL for GIFs (static frame for CLIP analysis).
    """
    from interactions.models.discord.enums import EmbedType

    embed_type = getattr(embed, 'type', None)

    if embed_type == EmbedType.GIFV:
        # GIF embeds (Tenor, Giphy) - use thumbnail for static CLIP analysis
        if embed.thumbnail and getattr(embed.thumbnail, 'url', None):
            return embed.thumbnail.url
        if embed.image and getattr(embed.image, 'url', None):
            return embed.image.url

    elif embed_type == EmbedType.IMAGE:
        # Direct image embeds
        if embed.image and getattr(embed.image, 'url', None):
            return embed.image.url
        if embed.thumbnail and getattr(embed.thumbnail, 'url', None):
            return embed.thumbnail.url

    return None


def _get_rag_image_desc(message_id: int) -> str:
    """
    Check if ChromaDB already has an image description for this message ID.
    Returns the description string or '' if not found / not available.
    Used to skip redundant CLIP scans for messages already in long-term memory.
    """
    if not RAG_AVAILABLE or not RAG_ENABLED:
        return ''
    try:
        from rag.retriever import MessageRetriever
        retriever = MessageRetriever()  # returns existing singleton (cheap)
        result = retriever.collection.get(ids=[str(message_id)], include=['metadatas'])
        if result['ids'] and result['metadatas'] and result['metadatas'][0]:
            return result['metadatas'][0].get('image_description', '') or ''
    except Exception:
        pass
    return ''


def _should_react_to_image(session: ChannelSession, author_id: int) -> bool:
    """
    Mood-gated check for whether to create an opportunity to respond to this user's image.
    Scanning always happens regardless; this gates whether Nadia will actually reply.

    LURKING: React to all images
    ENGAGED/BORED: Only react to engagement focus target, friends, opps, real_user
    HEATED: Only react to opps (roast material)
    """
    if not VISION_ENABLED or not VISION_AVAILABLE:
        return False

    user = session.users.get(author_id)
    classification = user.classification if user else "neutral"

    if session.mood == MoodState.LURKING:
        return True

    elif session.mood in (MoodState.ENGAGED, MoodState.BORED):
        if classification in ("friend", "opp", "real_user"):
            return True
        if session.is_focus_active() and session.is_focus_target(author_id):
            return True
        return False

    elif session.mood == MoodState.HEATED:
        return classification == "opp"

    return False

def _parse_image_type_tag(description: str) -> str:
    """
    Extract the [TYPE] tag from a combined pipeline description.

    Input:  "[MEME] Funko Pop figure... | Text: 'POP! TRANNERLAND'"
    Output: "meme"

    Falls back to "photo" if no tag found (e.g. legacy CLIP-only descriptions).
    """
    if description.startswith("["):
        end = description.find("]")
        if end > 0:
            return description[1:end].lower()
    return "photo"

def _detect_is_own_selfie(message_text: str) -> bool:
    """Return False if message text suggests the poster is showing someone else's image."""
    if not message_text:
        return True
    text = message_text.lower()
    third_person_hints = [
        "what gender is", "is she", "is he", "is this a", "is this girl",
        "is this guy", "look at them", "look at her", "look at him",
        "what do you think of her", "what do you think of him",
        "rate them", "rate her", "rate him", "what is this person",
        "who is this", "what are they",
    ]
    return not any(hint in text for hint in third_person_hints)


def _build_image_prompt_addition(
    description: str,
    reason: str,
    author_name: str = "",
    user_id: Optional[int] = None,
    message_text: str = "",
) -> str:
    """
    Build a context-appropriate prompt addition for an image-bearing message.

    Uses the image type classification from the combined pipeline to give
    Claude better instructions on how to react. Different image types get
    different reaction styles:

    - MEME: React to the humor/message, reference the text if present
    - SELFIE: React to how they look (honest, not hugboxy per system prompt)
    - FOOD: Engage naturally with food opinions
    - FASHION: Give outfit/style opinion
    - SCREENSHOT: Usually skip, but if reacting, comment on the content
    - PRODUCT: React to the item
    - PHOTO: General reaction

    Args:
        description: The combined bot description string (has [TYPE] prefix)
        reason: The opportunity reason ("image_roast", "meme_reaction", etc.)
        author_name: Who posted the image

    Returns:
        Prompt addition string for Claude's context
    """
    image_type = _parse_image_type_tag(description)
    poster = author_name or "someone"

    # Base context: always tell Claude what's in the image
    base = f"[{poster} posted an image: {description}]"

    # Type-specific reaction instructions
    # Selfie is handled separately below with friend/opp/own logic
    type_instructions = {
        "meme": (
            "React to the meme naturally. If it has text, engage with the actual joke or message. "
            "If it's funny say so briefly. If it's mid, overused, or cringe, call it out. "
            "Don't describe what you see - just react like a person would."
        ),
        "food": (
            "React to the food. You have opinions about restaurants and cuisines. "
            "Ask where it's from, comment on how it looks, share a food take."
        ),
        "fashion": (
            "React to the outfit/style. You care about fashion and have high standards. "
            "Give your honest take - cute, mid, try harder, where'd you get that, etc."
        ),
        "travel": (
            "React to the location. You travel and have opinions about places. "
            "Comment on the vibe, share your experience if you've been there, or ask about it."
        ),
        "product": (
            "React to the product/item naturally. Comment if it's interesting, "
            "roast if it's tacky, or engage if it connects to something you care about."
        ),
        "screenshot": (
            "This is a screenshot. React to the content shown in it if it's interesting. "
            "If it's boring or irrelevant, you don't have to comment."
        ),
        "photo": (
            "React to the image naturally. If it connects to something you care about "
            "(fashion, travel, money, lifestyle), give your take. Keep it brief."
        ),
    }

    if image_type == "selfie":
        is_own = _detect_is_own_selfie(message_text)
        classification = _get_user_classification(user_id)
        if not is_own:
            instruction = (
                "Someone shared a picture of another person. Use the image details to say "
                "something specific about what you see — looks, vibe, whatever stands out. "
                "Keep it brief and opinionated."
            )
        elif classification in ("friend", "real_user"):
            instruction = (
                "This is a friend posting their own selfie. Actually say something nice about "
                "how they look — use the specific visual details (hair, outfit, vibe) to make "
                "it feel real, not generic. This is one of the few times a genuine compliment "
                "is warranted."
            )
        elif classification == "opp":
            instruction = (
                "This is an opp posting their own selfie. Roast them based on the specific "
                "visual details in the image — hair, expression, outfit, background, whatever "
                "gives you material. Make it creative and funny, not just 'ugly'. If you know "
                "receipts on them from memory, this is the time."
            )
        else:
            instruction = (
                "React honestly to this selfie. Use the specific visual details (hair color, "
                "outfit, expression, setting) to say something concrete. Don't be warm or "
                "coddling — just your honest take."
            )
    else:
        instruction = type_instructions.get(image_type, type_instructions["photo"])

    # Override instruction for specific reasons (roast, etc.)
    if reason == "image_roast":
        instruction = (
            "Find something in this image to roast them about. Be creative and devastating. "
            "Use the visual details as ammunition."
        )

    return f"{base}\n{instruction}"

def _apply_user_treatment_new(session: ChannelSession, user_id: int, plan: NewActionPlan) -> NewActionPlan:
    """Apply friend/opp/real_user treatment to action plan."""
    user = session.users.get(user_id)
    if not user:
        return plan

    classification = user.classification

    if classification == "real_user":
        plan.treatment = "real_user"
        plan.prompt_additions.append("This is the queen herself. Be positive, flattering, empathic.")
    elif classification == "friend":
        plan.treatment = "friend"
        plan.prompt_additions.append("This person is a friend. Be positive or neutrally tolerant.")
    elif classification == "opp":
        opp_mode = random.choice(["neutral", "insult", "contradict"])
        plan.treatment = f"opp_{opp_mode}"
        if opp_mode == "neutral":
            plan.prompt_additions.append("Respond with cold neutrality.")
        elif opp_mode == "insult":
            plan.prompt_additions.append("Include a brief personal insult or read.")
        else:
            plan.prompt_additions.append("Disagree with or contradict what they said.")

    return plan


async def stage3_generate_content(session: ChannelSession, plan: NewActionPlan) -> str:
    """
    STAGE 3: CONTENT GENERATION

    Generate response content using Claude API with mood-based length limits.
    """
    if not plan.should_act:
        return ""

    # Handle diva read (unchanged)
    if plan.action_type == ActionType.DIVA_READ:
        context_msgs = [
            {"content": f"{m.author_name}: {m.content}"}
            for m in session.message_buffer if not m.is_bot
        ]
        return await generate_diva_read(
            plan.target_user_name,
            context_msgs[-5:],
            plan.diva_reason
        )

    # If the target message has a pending image task, await it before generating
    # This handles the race where @mention + image arrive on the same tick
    if plan.target_message and plan.target_message.message_id in session.pending_image_tasks:
        task = session.pending_image_tasks[plan.target_message.message_id]
        if not task.done():
            logger.info(f"Stage 3: Waiting for image interrogation on target message...")
            try:
                description = await asyncio.wait_for(task, timeout=VISION_TIMEOUT)
                if description:
                    plan.target_message.image_description = description
                    logger.info(f"Stage 3: Image ready: {description[:80]}...")
                    # Add image context to prompt if not already added by stage2
                    if f"posted an image:" not in "\n".join(plan.prompt_additions):
                        plan.prompt_additions.append(
                            _build_image_prompt_addition(
                                description,
                                reason=plan.reason,
                                author_name=plan.target_user_name,
                                user_id=plan.target_user_id,
                                message_text=plan.target_message.content if plan.target_message else "",
                            )
                        )
            except asyncio.TimeoutError:
                logger.warning("Stage 3: Image interrogation timed out, proceeding without it")
            except Exception as e:
                logger.warning(f"Stage 3: Image interrogation failed: {e}")
            session.pending_image_tasks.pop(plan.target_message.message_id, None)

    # If the target has no image but is a reply to a message that does, use that image.
    # Handles: "@Nadiabot does this look like a man?" replying to someone else's photo.
    if (plan.target_message
            and plan.target_message.reply_to_id
            and not plan.target_message.image_description
            and "posted an image:" not in "\n".join(plan.prompt_additions)):
        replied_id = plan.target_message.reply_to_id
        replied_msg = next(
            (m for m in session.message_buffer if m.message_id == replied_id), None
        )
        # author info for the replied-to message (from buffer or reply context fallback)
        ref_author_name = (
            replied_msg.author_name if replied_msg
            else (plan.target_message.reply_context_author or "someone")
        )
        ref_author_id = replied_msg.author_id if replied_msg else None

        if replied_msg and replied_msg.image_description:
            # Case 1: image task already completed and stored on the buffer message
            logger.info(
                f"Stage 3: Using image from replied-to message "
                f"({ref_author_name}): {replied_msg.image_description[:80]}..."
            )
            plan.prompt_additions.append(
                _build_image_prompt_addition(
                    replied_msg.image_description,
                    reason=plan.reason,
                    author_name=ref_author_name,
                    user_id=ref_author_id,
                    message_text=plan.target_message.content or "",
                )
            )
        elif replied_id in session.pending_image_tasks:
            # Case 2: image task in flight (either from original scan or on-demand)
            task = session.pending_image_tasks[replied_id]
            if not task.done():
                logger.info(
                    f"Stage 3: Waiting for image on replied-to message ({ref_author_name})..."
                )
                try:
                    description = await asyncio.wait_for(task, timeout=VISION_TIMEOUT)
                    if description:
                        if replied_msg:
                            replied_msg.image_description = description
                        logger.info(
                            f"Stage 3: Replied-to image ready: {description[:80]}..."
                        )
                        plan.prompt_additions.append(
                            _build_image_prompt_addition(
                                description,
                                reason=plan.reason,
                                author_name=ref_author_name,
                                user_id=ref_author_id,
                                message_text=plan.target_message.content or "",
                            )
                        )
                except asyncio.TimeoutError:
                    logger.warning(
                        "Stage 3: Replied-to image interrogation timed out"
                    )
                except Exception as e:
                    logger.warning(
                        f"Stage 3: Replied-to image interrogation failed: {e}"
                    )
                session.pending_image_tasks.pop(replied_id, None)

    # Build context from session
    context = session.get_context_for_claude(client.user.id)

    # Build user message
    if plan.target_message:
        msg_content = plan.target_message.content
        if not msg_content and plan.target_message.image_description:
            msg_content = "[posted an image with no text]"

        # Include reply context if target is replying to something outside the buffer
        if (plan.target_message.reply_context
                and plan.target_message.reply_to_id):
            buffer_ids = {m.message_id for m in session.message_buffer}
            if plan.target_message.reply_to_id not in buffer_ids:
                quote = plan.target_message.reply_context[:200]
                if len(plan.target_message.reply_context) > 200:
                    quote += "..."
                user_message = (
                    f'{plan.target_user_name} (replying to '
                    f'{plan.target_message.reply_context_author}: "{quote}"): {msg_content}'
                )
            else:
                user_message = f"{plan.target_user_name}: {msg_content}"
        else:
            user_message = f"{plan.target_user_name}: {msg_content}"
    else:
        user_message = "The chat has been active. Join in naturally with a brief comment."

    # Check if heated multi-user mode: allows rapid-fire quips to multiple people
    unique_users = set(m.author_name for m in session.message_buffer if not m.is_bot)
    use_heated_multi = (
        session.mood == MoodState.HEATED and
        len(unique_users) > 1
    )

    # Single-target focus prompt: prevents multi-person wall-of-text responses
    # Skip when heated multi-user mode is active (we want multiple targets)
    if plan.target_user_name and not use_heated_multi:
        # Explicitly name other active users to prevent Claude referencing them even when
        # their messages are visible in context (e.g. two triggers processed back-to-back)
        other_active = [
            u.display_name for uid, u in session.users.items()
            if uid != plan.target_user_id
            and u.is_active()
            and u.display_name != plan.target_user_name
        ]
        no_mention = f" Do NOT mention {', '.join(other_active)} by name." if other_active else ""
        focus_prompt = (
            f"Respond ONLY to {plan.target_user_name}. "
            f"Do NOT address other people in the chat.{no_mention} "
            "One topic only. Ignore what others said unless directly relevant to this person's message."
        )
    else:
        focus_prompt = None

    # Apply mood-based prompt modifications
    mood_prompts = _get_mood_prompts(session.mood, plan.reason)
    all_prompts = ([focus_prompt] if focus_prompt else []) + plan.prompt_additions + mood_prompts

    # Add energy-based modifications
    if session.metrics.energy > 0.8:
        all_prompts.append("You're feeling energetic - be more expressive!")
    elif session.metrics.energy < 0.3:
        all_prompts.append("You're feeling low energy")

    prompt_addition = "\n".join(all_prompts) if all_prompts else ""

    # Inject RAG context when available (bored_interjection with a memory hit, or image_reaction)
    if plan.reason == "bored_interjection" and plan.rag_context:
        prompt_addition += f"\n\n{plan.rag_context}"
        mood_max_tokens = MOOD_MAX_TOKENS.get(session.mood.value, MAX_TOKENS)
    elif plan.reason == "image_reaction" and plan.rag_context:
        # Image reaction with RAG context - inject past messages for richer response
        prompt_addition += f"\n\n{plan.rag_context}"
        mood_max_tokens = MOOD_MAX_TOKENS.get(session.mood.value, MAX_TOKENS)
    else:
        mood_max_tokens = MOOD_MAX_TOKENS.get(session.mood.value, MAX_TOKENS)
    
    # Log the generation parameters
    logger.info(
        f"Stage 3: Generating | mood={session.mood.value} | "
        f"max_tokens={mood_max_tokens} | energy={session.metrics.energy:.2f} | "
        f"temp={session.metrics.temperature:.2f} | reason={plan.reason}"
    )

    # Build context messages for multi-user mode parsing
    heated_context_msgs = buffered_to_context_messages(session.message_buffer) if use_heated_multi else None

    # Generate response with mood-based token limit
    # When heated + multiple users: use multi_user_mode for @Username: format
    response = await generate_response(
        user_message,
        context,
        prompt_addition,
        multi_user_mode=use_heated_multi,
        context_messages=heated_context_msgs,
        trigger_author=plan.target_user_name,
        max_tokens=mood_max_tokens,
        skip_rag=(plan.reason == "bored_interjection" and bool(plan.rag_context))
    )

    logger.info(f"Stage 3: Generated {len(response) if response else 0} chars for {plan.reason}")
    return response or ""


def _get_mood_prompts(mood: MoodState, reason: str = "") -> list[str]:
    """
    Get prompt additions based on mood and response reason.
    
    Key change: lurking/bored dismissiveness ("ok and?") is now reserved for
    opp_engagement. For other reasons (interesting_topic, random_engagement, etc.),
    the bot gives more substantive responses even at low energy.
    """
    # Opp-specific dismissive responses when lurking/bored
    if reason == "opp_engagement" and mood in (MoodState.LURKING, MoodState.BORED):
        return [
            "An opp is talking but you barely care. Be dismissive, cold, or cutting. "
            "Under 15 words. 'ok and?', 'nobody asked', 'that's crazy anyway' are valid."
        ]
    
    prompts = {
        MoodState.LURKING: [
            "Something caught your eye. One short take, then done. Don't try hard."
        ],
        MoodState.ENGAGED: [
            "You're in the conversation but still sardonic. 1-2 sentences max, "
            "natural back-and-forth rhythm."
        ],
        MoodState.HEATED: [
            "You're heated - SHORT and PUNCHY. 1 sentence. Concentrated venom, "
            "not paragraphs. The shorter the more devastating."
        ],
        MoodState.BORED: [
            "Drop one casual mean quip and leave it. One sentence."
        ],
    }
    return prompts.get(mood, [])


def format_mentions_in_content(
    content: str,
    session: ChannelSession,
    is_direct_reply: bool = False,
    reply_target_name: str = ""
) -> str:
    """
    Post-process Claude's output to convert plain-text @Name references
    to proper Discord <@user_id> mentions, using session's UserPresence data.
    
    For direct replies, strips the target's name prefix entirely since
    Discord's reply UI already shows who the message is directed at.
    
    Args:
        content: Generated response text (may contain "@lera" or "lera:" etc.)
        session: Current ChannelSession with user presence data
        is_direct_reply: Whether this will be sent as a Discord reply
        reply_target_name: Display name of the reply target (stripped for replies)
    """
    if not content:
        return content

    # Build name -> user_id lookup from all known session users
    name_to_id: dict[str, int] = {}
    for user_id, presence in session.users.items():
        name_lower = presence.display_name.lower()
        name_to_id[name_lower] = user_id
        # Also map simplified name (strips Unicode decorations like emojis)
        simple = simplify_display_name(presence.display_name).lower()
        if simple and simple != name_lower:
            name_to_id[simple] = user_id

    # For direct replies, strip the target's name prefix from the start of content.
    # Discord already shows who you're replying to, so "@lera exactly" -> "exactly"
    if is_direct_reply and reply_target_name:
        target_lower = reply_target_name.lower()
        target_simple = simplify_display_name(reply_target_name).lower()

        for prefix_name in [target_lower, target_simple]:
            for pattern_str in [
                f"@{prefix_name} ",     # @lera exactly
                f"@{prefix_name}, ",    # @lera, exactly
                f"@{prefix_name}: ",    # @lera: exactly
                f"{prefix_name}: ",     # lera: exactly
                f"{prefix_name}, ",     # lera, exactly
            ]:
                if content.lower().startswith(pattern_str):
                    content = content[len(pattern_str):]
                    break
            else:
                continue
            break  # Stop checking if we already stripped

    # Replace remaining @Name references with <@user_id> Discord mentions.
    # Sort by name length (longest first) to avoid partial matches.
    sorted_names = sorted(name_to_id.keys(), key=len, reverse=True)

    for name_lower in sorted_names:
        user_id = name_to_id[name_lower]
        # Match @Name (case insensitive) at word boundaries or end of string
        pattern = re.compile(
            r'@' + re.escape(name_lower) + r'(?=[\s,.:;!?\'")\]\}]|$)',
            re.IGNORECASE
        )
        content = pattern.sub(f'<@{user_id}>', content)

    return content


def truncate_multi_person_response(content: str) -> str:
    """
    Safety net: If Claude generated multi-person response despite instructions,
    truncate to just the first section.

    Detects patterns like:
    - Multiple @Name: or Name: prefixes at start of lines
    - Multiple paragraphs with different name prefixes
    """
    if not content:
        return content

    # Pattern: @Name: or Name: at start of line (multiple occurrences = multi-person)
    name_prefix_pattern = re.compile(r'^[@]?\w+:', re.MULTILINE)
    matches = list(name_prefix_pattern.finditer(content))

    if len(matches) > 1:
        # Multiple name prefixes found - truncate to first section
        return content[:matches[1].start()].strip()

    # Also check for double-newline separated sections that look like different topics
    paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
    if len(paragraphs) > 2:
        # More than 2 paragraphs might indicate multi-topic rambling
        return '\n\n'.join(paragraphs[:2])

    return content


def _strip_ai_image_artifacts(content: str) -> str:
    """
    Safety net: strip leaked vision pipeline labels and AI-ish image descriptions
    that Claude sometimes echoes from its context.

    Targets:
    - Bracketed image type tags: [MEME], [GIF], [SELFIE], [FOOD], etc.
    - Leaked context format: [attached image: ...]
    - Leaked prompt additions: [posted an image ...]
    - AI description hedging: "what appears to be", "the image shows", etc.
    """
    if not content:
        return content

    # Strip bracketed image type tags (standalone or at start of text)
    content = re.sub(
        r'\[(?:MEME|GIF|SELFIE|FOOD|FASHION|SCREENSHOT|PRODUCT|PHOTO)\]\s*',
        '', content
    )

    # Strip leaked context blocks: [attached image: ...] or [posted an image ...]
    content = re.sub(r'\[attached image:[^\]]*\]\s*', '', content)
    content = re.sub(r'\[posted an image[^\]]*\]\s*', '', content)

    # Strip AI description hedging phrases (only at sentence start / after punctuation)
    for phrase in [
        "what appears to be ",
        "which appears to be ",
        "the image shows ",
        "the image appears to show ",
        "the image is of ",
        "the image features ",
        "I can see that ",
        "Text in image: ",
    ]:
        content = re.sub(
            re.escape(phrase), '', content, flags=re.IGNORECASE
        )

    # Strip pipe-separated CLIP tag dumps (e.g. "| panaormic, classic chrome, googles")
    content = re.sub(r'\|\s*(?:[\w\s]+,\s*){2,}[\w\s]*$', '', content)

    return content.strip()


async def stage4_execute(
    session: ChannelSession,
    plan: NewActionPlan,
    content: str,
    override_target: Optional[ContextMessage] = None
) -> Optional[object]:
    """
    STAGE 4: EXECUTION

    Send the response and update session state.
    Post-processes content (mention formatting), sets engagement focus + suppression.

    Args:
        override_target: If provided, use this as the reply target instead of plan.target_message.
                        Used for heated multi-message mode where each part has its own target.
    """
    if not content:
        return None

    # Handle diva read execution
    if plan.execute_diva_mute and plan.target_message:
        await execute_diva_read(plan.target_message.message_obj, content, plan.diva_reason)
        session.metrics.last_bot_message_time = datetime.now().timestamp()
        session.metrics.bot_message_count += 1
        session.set_cooldown()
        session.set_post_response_suppression()
        # Track this message as responded to
        session.responded_to_message_ids.add(plan.target_message.message_id)
        # Track per-user response time
        if plan.target_user_id:
            session.last_response_to_user[plan.target_user_id] = datetime.now().timestamp()
        return None

    # Determine reply target: use override if provided, else plan's target
    reply_target = override_target if override_target else plan.target_message
    reply_target_name = (
        override_target.author_name if override_target
        else plan.target_user_name
    )

    # Determine if this is a direct reply (affects name prefix stripping)
    is_direct_reply = (
        plan.action_type == ActionType.REPLY
        and reply_target
        and reply_target.message_obj
    )

    # Post-process: convert @Name plain text to <@user_id> Discord mentions,
    # and strip the target's name prefix for direct replies (Discord shows reply context)
    content = format_mentions_in_content(
        content, session,
        is_direct_reply=is_direct_reply,
        reply_target_name=reply_target_name
    )

    # Safety net: truncate multi-person responses that slipped through
    content = truncate_multi_person_response(content)

    # Safety net: strip leaked vision pipeline labels and AI-ish image phrasing
    content = _strip_ai_image_artifacts(content)

    # Calculate typing delay with mood/energy modifiers
    base_delay = calculate_typing_delay(content)

    energy_modifier = 1.0 - (session.metrics.energy * 0.3)  # 0.7 to 1.0
    mood_modifiers = {
        MoodState.LURKING: 1.2,
        MoodState.ENGAGED: 0.9,
        MoodState.HEATED: 0.7,
        MoodState.BORED: 1.1,
    }
    mood_modifier = mood_modifiers.get(session.mood, 1.0)

    final_delay = base_delay * energy_modifier * mood_modifier
    final_delay = max(TYPING_MIN_DELAY, min(final_delay, TYPING_MAX_DELAY))

    channel = session.channel_obj

    try:
        async with channel.typing:
            await asyncio.sleep(final_delay)

        # Send message
        if is_direct_reply:
            sent = await reply_target.message_obj.reply(content, mention_author=False)
        else:
            sent = await channel.send(content)

        # Update session state
        session.metrics.last_bot_message_time = datetime.now().timestamp()
        session.metrics.bot_message_count += 1

        # "Letting off steam" - responding releases tension (mood-dependent)
        # Only ENGAGED/HEATED release steam; lurking/bored shouldn't drain energy
        # (responding while lurking would otherwise trap the bot at low energy)
        steam_release = {
            MoodState.HEATED: (0.12, 0.08),   # (energy_drop, temp_drop)
            MoodState.ENGAGED: (0.06, 0.03),
            MoodState.LURKING: (0.0, 0.0),
            MoodState.BORED: (0.0, 0.0),
        }
        energy_drop, temp_drop = steam_release.get(session.mood, (0.05, 0.03))
        session.metrics.energy = max(0.0, session.metrics.energy - energy_drop)
        session.metrics.temperature = max(0.0, session.metrics.temperature - temp_drop)

        # Add bot message to buffer
        bot_msg = BufferedMessage(
            message_id=sent.id,
            author_id=client.user.id,
            author_name=client.user.display_name,
            content=content,
            timestamp=datetime.now().timestamp(),
            is_bot=True,
            message_obj=sent
        )
        session.add_message(bot_msg)

        # Set cooldown + post-response suppression to let conversation breathe
        session.set_cooldown()
        session.set_post_response_suppression()

        # Set engagement focus to track which user drew the bot in
        if plan.target_user_id:
            session.set_engagement_focus(plan.target_user_id)

        # Track this message as responded to (prevents re-engaging same message)
        if plan.target_message:
            session.responded_to_message_ids.add(plan.target_message.message_id)

        # Track per-user response time (prevents responding to same user too frequently)
        if plan.target_user_id:
            session.last_response_to_user[plan.target_user_id] = datetime.now().timestamp()

        sent_preview = content[:80].replace('\n', ' ')
        if len(content) > 80:
            sent_preview += "..."
        logger.info(
            f"Stage 4: Sent ({len(content)} chars, {final_delay:.1f}s delay, mood={session.mood.value}) | "
            f"steam: -e{energy_drop:.2f} -t{temp_drop:.2f} -> e={session.metrics.energy:.2f} t={session.metrics.temperature:.2f}"
        )
        logger.info(f"  └─ sent: {sent_preview}")
        return sent

    except Exception as e:
        logger.error(f"Stage 4: Failed to send message: {e}")
        return None


async def presence_loop():
    """
    Main presence loop - runs continuously while bot is active.

    Tick-based: triggers every 3 seconds OR 3 messages, whichever comes first.
    """
    global active_session

    if active_session is None:
        logger.error("Presence loop started without active session")
        return

    logger.info(f"Presence loop started for channel {active_session.channel_id}")

    while True:
        try:
            # Wait for tick trigger
            triggered_by_messages = await active_session.wait_for_tick()

            # Log tick state
            trigger_type = "msgs" if triggered_by_messages else "time"
            processing_flag = " [BUSY]" if active_session.is_processing else ""
            logger.debug(
                f"Tick [{trigger_type}]{processing_flag} | mood={active_session.mood.value} | "
                f"temp={active_session.metrics.temperature:.2f} | "
                f"energy={active_session.metrics.energy:.2f} | "
                f"pending={len(active_session.pending_messages)} | "
                f"buffer={len(active_session.message_buffer)}"
            )

            # Check for session reset
            if active_session.should_reset():
                active_session.reset()
                continue

            # Skip if no pending messages and time-triggered
            if not triggered_by_messages and not active_session.pending_messages:
                continue

            # Skip action selection if already processing a response
            # (prevents race condition where new tick starts before previous response sends)
            if active_session.is_processing:
                logger.debug("Tick skipped: already processing a response")
                continue

            # Stage 1: Observation
            delta = await stage1_observe(active_session)

            # Stage 2: Action Selection
            plan = await stage2_select_action(active_session, delta)

            if plan.should_act:
                # Set processing lock before generation starts
                active_session.is_processing = True
                try:
                    # Wait if target user is still typing (avoid responding to partial message blocks)
                    if plan.target_user_id and plan.target_user_id in active_session.users_typing:
                        wait_start = datetime.now().timestamp()
                        while (datetime.now().timestamp() - wait_start) < active_session.TYPING_WAIT_MAX_SECONDS:
                            now = datetime.now().timestamp()
                            last_typed = active_session.users_typing.get(plan.target_user_id)
                            if last_typed is None or (now - last_typed) > active_session.TYPING_STALE_SECONDS:
                                break
                            await asyncio.sleep(0.5)
                        waited = datetime.now().timestamp() - wait_start
                        if waited > 0.5:
                            logger.info(f"Typing wait: {waited:.1f}s for {plan.target_user_name}")
                        # Flush any new messages that arrived during the wait into the buffer
                        if active_session.pending_messages:
                            bot_id = client.user.id
                            now = datetime.now().timestamp()
                            for msg in active_session.pending_messages:
                                buffered = BufferedMessage(
                                    message_id=msg.id,
                                    author_id=msg.author.id,
                                    author_name=msg.author.display_name,
                                    content=msg.content,
                                    timestamp=msg.created_at.timestamp() if hasattr(msg.created_at, 'timestamp') else now,
                                    is_bot=(msg.author.id == bot_id),
                                    reply_to_id=msg.message_reference.message_id if msg.message_reference else None,
                                    message_obj=msg
                                )
                                if buffered.reply_to_id:
                                    _resolve_reply_context(buffered, active_session, msg)
                                active_session.add_message(buffered)
                            active_session.pending_messages.clear()

                    # Stage 3: Content Generation
                    content = await stage3_generate_content(active_session, plan)

                    # Stage 4: Execution
                    if content:
                        # Check if heated multi-message mode
                        unique_users = set(m.author_name for m in active_session.message_buffer if not m.is_bot)
                        use_heated_multi = (
                            active_session.mood in (MoodState.HEATED, MoodState.ENGAGED) and
                            len(unique_users) > 1
                        )

                        if use_heated_multi:
                            # Parse into multiple parts and send sequentially
                            max_msgs = MOOD_MAX_RESPONSE_MESSAGES.get(active_session.mood.value, 1)
                            context_msgs = buffered_to_context_messages(active_session.message_buffer)
                            response_parts = parse_structured_response(content, context_msgs)[:max_msgs]

                            logger.info(f"Multi-message ({active_session.mood.value}): {len(response_parts)} parts from response")

                            for i, part in enumerate(response_parts):
                                if part.content:
                                    await stage4_execute(
                                        active_session, plan, part.content,
                                        override_target=part.target_message
                                    )
                                    # Brief delay between messages (heated = rapid-fire)
                                    if i < len(response_parts) - 1:
                                        await asyncio.sleep(0.5)
                        else:
                            # Normal single-message path
                            await stage4_execute(active_session, plan, content)

                        # Track bored interjection timing for rate limiting
                        if plan.reason == "bored_interjection":
                            active_session.last_bored_interjection_time = datetime.now().timestamp()
                finally:
                    # Always clear the lock, even on error
                    active_session.is_processing = False

        except Exception as e:
            logger.error(f"Presence loop error: {e}", exc_info=True)
            await asyncio.sleep(5)


# ============== EVENT HANDLERS ==============

@listen()
async def on_ready():
    """Called when the bot is ready."""
    global SYSTEM_PROMPT, active_session

    SYSTEM_PROMPT = load_system_prompt()
    init_anthropic()

    logger.info(f"Logged in as {client.user.display_name} (ID: {client.user.id})")
    logger.info(f"Persona: {PERSONA_NAME}")
    logger.info(f"Starting up with status: {bot_posting_enabled}")
    logger.info(f"Respond to mentions: {RESPOND_TO_MENTIONS}")
    logger.info(f"Respond to replies: {RESPOND_TO_REPLIES}")
    logger.info(f"Respond to name: {RESPOND_TO_NAME} (high: {TRIGGER_NAMES_HIGH}@{TRIGGER_CHANCE_HIGH*100:.0f}%, low: {TRIGGER_NAMES_LOW}@{TRIGGER_CHANCE_LOW*100:.0f}%)")
    logger.info(f"Random response chance: {RANDOM_RESPONSE_CHANCE*100}%")

    # Log RAG status
    if RAG_ENABLED and RAG_AVAILABLE:
        try:
            from rag.retriever import MessageRetriever
            retriever = MessageRetriever()
            logger.info(f"RAG enabled with {retriever.collection.count()} messages")
        except Exception as e:
            logger.warning(f"RAG initialization failed: {e}")
    elif RAG_ENABLED and not RAG_AVAILABLE:
        logger.warning("RAG enabled but not available - run 'python -m rag.embedder' first")
    else:
        logger.info("RAG disabled")

    # Pre-warm vision models in background so first image doesn't block
    if VISION_ENABLED and VISION_AVAILABLE:
        async def _warm_clip():
            try:
                from vision.interrogator import get_interrogator
                await asyncio.to_thread(get_interrogator()._ensure_loaded)
                logger.info("Vision: CLIP model pre-warmed successfully")
            except Exception as e:
                logger.warning(f"Vision: CLIP pre-warm failed (will load on first use): {e}")

        async def _warm_ocr():
            try:
                from vision.florence import get_florence
                await asyncio.to_thread(get_florence()._ensure_loaded)
                logger.info("Vision: OCR model pre-warmed successfully")
            except Exception as e:
                logger.warning(f"Vision: OCR pre-warm failed (will load on first use): {e}")

        asyncio.create_task(_warm_clip())
        asyncio.create_task(_warm_ocr())
    elif VISION_ENABLED and not VISION_AVAILABLE:
        logger.warning("Vision enabled but not available - check vision module imports")

    # Initialize presence loop for single channel (new stateful agent architecture)
    if MAIN_CHANNELS:
        target_channel_id = MAIN_CHANNELS[0]
        try:
            channel = await client.fetch_channel(target_channel_id)
            active_session = ChannelSession(
                channel_id=target_channel_id,
                channel_obj=channel
            )
            asyncio.create_task(presence_loop())
            logger.info(f"Presence loop started for channel {target_channel_id} ({channel.name})")
        except Exception as e:
            logger.error(f"Failed to initialize presence loop: {e}")


@listen()
async def on_message_create(event: MessageCreate):
    """
    Lightweight message collector for presence loop.

    Buffers messages for the presence loop to process on tick.
    Also embeds messages into ChromaDB for live RAG updates.
    """
    global active_session

    message = event.message

    # Basic filters
    if message.author.bot:
        return
    if message.channel.id in BLOCKED_CHANNELS:
        return

    # Live RAG embedding - runs regardless of bot posting state
    if RAG_AVAILABLE and RAG_ENABLED and message.content:
        try:
            ts = message.created_at.timestamp() if hasattr(message.created_at, 'timestamp') else datetime.now().timestamp()
            try:
                year_month = message.created_at.strftime('%Y-%m')
            except Exception:
                year_month = datetime.now().strftime('%Y-%m')

            reply_to_author = ''
            if hasattr(message, 'referenced_message') and message.referenced_message:
                try:
                    reply_to_author = message.referenced_message.author.display_name
                except Exception:
                    pass

            metadata = {
                'author_id': str(message.author.id),
                'author_name': message.author.display_name,
                'channel_name': getattr(message.channel, 'name', 'unknown'),
                'timestamp_unix': float(ts),
                'year_month': year_month,
                'is_persona': 1 if str(message.author.id) in PERSONA_AUTHOR_IDS else 0,
                'is_reply': 1 if message.message_reference else 0,
                'reply_to_author': reply_to_author,
                'char_length': len(message.content),
                'word_count': len(message.content.split()),
            }
            asyncio.create_task(embed_live_message(str(message.id), message.content, metadata))
        except Exception as e:
            logger.debug(f"Live embed scheduling failed: {e}")

    if not bot_posting_enabled:
        return

    # If no active session or wrong channel, ignore
    if active_session is None:
        return
    if message.channel.id != active_session.channel_id:
        return

    # Buffer the message for presence loop to process
    active_session.pending_messages.append(message)

    # Clear typing state - user finished typing and sent a message
    active_session.users_typing.pop(message.author.id, None)


@listen()
async def on_typing_start(event: TypingStart):
    """Track when users start typing to avoid responding to partial message blocks."""
    global active_session
    if active_session is None:
        return
    if event.channel.id != active_session.channel_id:
        return
    if event.author.bot:
        return
    active_session.users_typing[event.author.id] = datetime.now().timestamp()


# ============== SLASH COMMANDS (Optional) ==============

@slash_command(
    name="persona_status",
    description="Check the persona bot status",
    scopes=[GUILD_ID]
)
async def status_cmd(ctx: SlashContext):
    # Check permissions
    if not (ctx.author.has_role(ADMIN_ROLE_ID) or ctx.author.id == 1436260342475919365):
        await ctx.send("You don't have permission to use this command.", ephemeral=True)
        return
    
    """Show bot status."""
    embed = Embed(
        title=f"🎭 {PERSONA_NAME} Status {'✔ ON' if bot_posting_enabled else '✗ OFF'}",
        color=0x9c92d1
    )
    
    embed.add_field(
        name="Response Triggers",
        value=f"Mentions: {'✔' if RESPOND_TO_MENTIONS else '✗'}\n"
              f"Replies: {'✔' if RESPOND_TO_REPLIES else '✗'}\n"
              f"Name: {'✔' if RESPOND_TO_NAME else '✗'} (bot@{TRIGGER_CHANCE_HIGH*100:.0f}%, name@{TRIGGER_CHANCE_LOW*100:.0f}%)\n"
              f"Random: {RANDOM_RESPONSE_CHANCE*100:.1f}%",
        inline=True
    )
    
    embed.add_field(
        name="Diva Read System",
        value=f"Enabled: {'✔' if DIVA_READ_ENABLED else '✗'}\n"
              f"Threshold: {DIVA_READ_THRESHOLD} (warn @ {DIVA_READ_WARN_AT})\n"
              f"Timeout: {DIVA_READ_TIMEOUT}s\n"
              f"Active trackers: {len(diva_tracker)}",
        inline=True
    )
    
    embed.add_field(
        name="System",
        value=f"Posting: {'✔ ON' if bot_posting_enabled else '✗ OFF'}\n"
              f"Prompt: {len(SYSTEM_PROMPT)} chars\n"
              f"Model: RAG+Vader+Claude",
        inline=True
    )
    
    await ctx.send(embed=embed, ephemeral=True)


        
@slash_command(
    name="persona_disable",
    description="Disable the persona bot's message posting",
    scopes=[GUILD_ID]
)
async def disable_cmd(ctx: SlashContext):
    """Disable bot posting (admin/support only)."""
    global bot_posting_enabled

    # Check permissions
    if not (ctx.author.has_role(ADMIN_ROLE_ID) or ctx.author.id == 1436260342475919365):
        await ctx.send("You don't have permission to use this command.", ephemeral=True)
        return

    bot_posting_enabled = False
    save_bot_state(False)
    logger.info(f"Bot posting DISABLED by {ctx.author.display_name}")
    await ctx.send(f"Bot posting has been **disabled**. Use `/persona_enable` to re-enable.", ephemeral=True)


@slash_command(
    name="persona_enable",
    description="Enable the persona bot's message posting",
    scopes=[GUILD_ID]
)
async def enable_cmd(ctx: SlashContext):
    """Enable bot posting (admin/support only)."""
    global bot_posting_enabled

    # Check permissions
    if not (ctx.author.has_role(ADMIN_ROLE_ID) or ctx.author.id == 1436260342475919365):
        await ctx.send("You don't have permission to use this command.", ephemeral=True)
        return

    bot_posting_enabled = True
    save_bot_state(True)
    logger.info(f"Bot posting ENABLED by {ctx.author.display_name}")
    await ctx.send(f"Bot posting has been **enabled**.", ephemeral=True)


# ============== RUN ==============

if __name__ == "__main__":
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("=" * 50)
        print("ERROR: Please configure your bot token!")
        print("Edit persona_bot.py and set BOT_TOKEN")
        print("Or set the PERSONA_BOT_TOKEN environment variable")
        print("=" * 50)
        exit(1)
    
    if ANTHROPIC_API_KEY == "YOUR_API_KEY_HERE":
        print("=" * 50)
        print("ERROR: Please configure your Anthropic API key!")
        print("Edit persona_bot.py and set ANTHROPIC_API_KEY")
        print("Or set the ANTHROPIC_API_KEY environment variable")
        print("=" * 50)
        exit(1)
    
    print(f"Starting {PERSONA_NAME} persona bot...")
    print(f"Prompt file: {SYSTEM_PROMPT_PATH}")
    client.start()