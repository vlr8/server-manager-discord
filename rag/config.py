"""RAG configuration constants."""
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent
CHATBOT_DATA_DIR = BASE_DIR / "chatbot_data"
MESSAGES_FILE = CHATBOT_DATA_DIR / "all_messages.txt"
CHROMA_PERSIST_DIR = CHATBOT_DATA_DIR / "chroma_db"

# SQLite source database (replaces flat text file for embedding)
SQLITE_DB_PATH = BASE_DIR / "discord_analytics.db"

# Persona author IDs to embed (main account + alt)
PERSONA_AUTHOR_IDS = ['881165097559527485', '1436260342475919365']

# Incremental embedding state
EMBED_STATE_FILE = CHATBOT_DATA_DIR / "embed_state.json"

# Embedding model - all-MiniLM-L6-v2 is fast and produces good quality embeddings
# 384 dimensions, ~80MB model size, ~80ms per batch
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# ChromaDB collection name
COLLECTION_NAME = "persona_messages_v2"

# Retrieval settings
TOP_K = 5                    # Number of messages to retrieve
MIN_MESSAGE_LENGTH = 15      # Skip very short messages (not enough semantic content)
MAX_MESSAGE_LENGTH = 500     # Skip overly long messages (likely pastes)
SIMILARITY_THRESHOLD = 0.3   # Minimum cosine similarity to include (0-1)
MIN_RAG_AGE_HOURS = 24       # Exclude messages newer than this (they're already in the buffer)

# Batch size for embedding
EMBEDDING_BATCH_SIZE = 512
