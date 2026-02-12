"""
Message Retriever - Retrieves semantically similar messages for RAG.

This module provides a singleton retriever that loads the embedding model once
and provides fast retrieval of similar messages from ChromaDB.

Usage:
    from rag.retriever import get_relevant_messages, get_formatted_context

    # Get list of similar messages
    messages = get_relevant_messages("what do you think about NYC")

    # Get formatted string for prompt injection
    context = get_formatted_context("what do you think about NYC")
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional

from .config import (
    EMBEDDING_MODEL,
    CHROMA_PERSIST_DIR,
    COLLECTION_NAME,
    TOP_K,
    SIMILARITY_THRESHOLD,
    MIN_MESSAGE_LENGTH,
    MAX_MESSAGE_LENGTH,
    MIN_RAG_AGE_HOURS,
)

logger = logging.getLogger(__name__)


class MessageRetriever:
    """
    Retrieves semantically similar messages for RAG.

    Uses singleton pattern to ensure model is only loaded once.
    """

    _instance: Optional['MessageRetriever'] = None

    def __new__(cls):
        """Singleton pattern - only load model once."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        try:
            from sentence_transformers import SentenceTransformer
            import chromadb
        except ImportError as e:
            logger.error(f"Missing dependency: {e}")
            raise

        logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
        self.model = SentenceTransformer(EMBEDDING_MODEL)

        logger.info(f"Connecting to ChromaDB at: {CHROMA_PERSIST_DIR}")
        self.client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))

        try:
            self.collection = self.client.get_collection(COLLECTION_NAME)
            count = self.collection.count()
            logger.info(f"RAG initialized with {count} messages")
        except Exception as e:
            logger.error(f"Failed to get collection '{COLLECTION_NAME}': {e}")
            logger.error("Run 'python -m rag.embedder' first to create embeddings")
            raise

        self._initialized = True

    def retrieve(
        self,
        query: str,
        top_k: int = TOP_K,
        min_similarity: float = SIMILARITY_THRESHOLD,
        where: dict = None,
    ) -> list[str]:
        """
        Retrieve relevant messages for a query.

        Args:
            query: The user's message to find similar content for
            top_k: Maximum number of results
            min_similarity: Minimum cosine similarity (0-1)
            where: Optional ChromaDB where filter for metadata

        Returns:
            List of relevant message strings
        """
        if not query or not query.strip():
            return []

        # Embed the query
        query_embedding = self.model.encode(query).tolist()

        # Query ChromaDB
        kwargs = {
            'query_embeddings': [query_embedding],
            'n_results': top_k,
            'include': ['documents', 'distances'],
        }
        if where:
            kwargs['where'] = where

        results = self.collection.query(**kwargs)

        # Filter by similarity threshold
        # ChromaDB with cosine space returns distances where lower = more similar
        # For cosine: similarity = 1 - distance
        messages = []
        if results['documents'] and results['distances']:
            for doc, distance in zip(results['documents'][0], results['distances'][0]):
                similarity = 1 - distance
                if similarity >= min_similarity:
                    messages.append(doc)

        return messages

    def retrieve_with_metadata(
        self,
        query: str,
        top_k: int = TOP_K,
        min_similarity: float = SIMILARITY_THRESHOLD,
        where: dict = None,
    ) -> list[tuple[str, dict]]:
        """
        Retrieve messages with their metadata.

        Returns list of (text, metadata_dict) tuples.
        """
        if not query or not query.strip():
            return []

        query_embedding = self.model.encode(query).tolist()

        kwargs = {
            'query_embeddings': [query_embedding],
            'n_results': top_k,
            'include': ['documents', 'distances', 'metadatas'],
        }
        if where:
            kwargs['where'] = where

        results = self.collection.query(**kwargs)

        messages = []
        if results['documents'] and results['distances']:
            metadatas = results.get('metadatas', [[]])[0]
            for doc, distance, meta in zip(
                results['documents'][0],
                results['distances'][0],
                metadatas,
            ):
                similarity = 1 - distance
                if similarity >= min_similarity:
                    messages.append((doc, meta or {}))

        return messages

    def retrieve_formatted(
        self,
        query: str,
        top_k: int = TOP_K
    ) -> str:
        """
        Retrieve and format messages for injection into prompt.

        Returns formatted string ready for system prompt addition.
        """
        messages = self.retrieve(query, top_k)

        if not messages:
            return ""

        formatted = "## Past memories (use as personal knowledge — don't cite exact dates or acknowledge you're remembering):\n"
        for i, msg in enumerate(messages, 1):
            # Escape quotes in messages
            escaped = msg.replace('"', "'")
            formatted += f'{i}. "{escaped}"\n'

        return formatted

    def retrieve_formatted_rich(
        self,
        query: str,
        top_k: int = TOP_K,
        where: dict = None,
    ) -> str:
        """
        Retrieve and format messages with metadata for prompt injection.

        Includes channel and time context so the LLM can reason about
        when and where things were said.
        """
        results = self.retrieve_with_metadata(query, top_k, where=where)

        if not results:
            return ""

        formatted = "## Past memories (use as personal knowledge — don't cite exact dates or acknowledge you're remembering):\n"
        for i, (msg, meta) in enumerate(results, 1):
            escaped = msg.replace('"', "'")
            channel = meta.get('channel_name', '?')
            year_month = meta.get('year_month', '?')
            img_desc = meta.get('image_description', '') or ''
            line = f'{i}. [{year_month}, #{channel}] "{escaped}"'
            if img_desc:
                line += f' [image: {img_desc[:120]}]'
            formatted += line + '\n'

        return formatted

    def hybrid_retrieve_formatted(
        self,
        query: str,
        top_k: int = TOP_K,
        time_filter: Optional[dict] = None,
        author_name: Optional[str] = None,
    ) -> str:
        """
        Hybrid retrieval: ChromaDB semantic search + optional SQLite fallback.

        1. Build a ChromaDB where clause from time_filter and author_name
        2. Run semantic search on ChromaDB
        3. If results are thin (< top_k // 2), fall back to SQLite LIKE search
        4. Merge, deduplicate, and format
        """
        # --- Build ChromaDB where clause ---
        where_clauses = []
        if time_filter:
            where_clauses.append(time_filter)
        if author_name:
            where_clauses.append({"author_name": {"$eq": author_name}})

        where = None
        if len(where_clauses) == 1:
            where = where_clauses[0]
        elif len(where_clauses) > 1:
            where = {"$and": where_clauses}

        # --- ChromaDB semantic search ---
        chroma_results = self.retrieve_with_metadata(query, top_k, where=where)

        # --- SQLite fallback if results are thin ---
        thin_threshold = max(1, top_k // 2)
        sqlite_results = []

        if len(chroma_results) < thin_threshold:
            try:
                import sys
                from pathlib import Path
                # Ensure parent dir is on path for db import
                parent = str(Path(__file__).parent.parent)
                if parent not in sys.path:
                    sys.path.insert(0, parent)
                from common.db import search_messages

                raw = search_messages(query, limit=20)

                if author_name:
                    raw = [r for r in raw if author_name in r['author_name'].lower()]

                for row in raw[:top_k]:
                    content = row.get('content', '').strip()
                    if not content:
                        continue
                    meta = {
                        'channel_name': row.get('channel_name', '?'),
                        'year_month': row.get('timestamp', '?')[:7],
                    }
                    sqlite_results.append((content, meta))
            except Exception as e:
                logger.debug(f"SQLite fallback failed: {e}")

        # --- Merge and deduplicate ---
        seen = set()
        merged = []

        for text, meta in chroma_results:
            key = text.strip().lower()[:80]
            if key not in seen:
                seen.add(key)
                merged.append((text, meta))

        for text, meta in sqlite_results:
            key = text.strip().lower()[:80]
            if key not in seen:
                seen.add(key)
                merged.append((text, meta))

        merged = merged[:top_k]

        if not merged:
            return ""

        # --- Format (same as retrieve_formatted_rich) ---
        formatted = "## Past memories (use as personal knowledge — don't cite exact dates or acknowledge you're remembering):\n"
        for i, (msg, meta) in enumerate(merged, 1):
            escaped = msg.replace('"', "'")
            channel = meta.get('channel_name', '?')
            year_month = meta.get('year_month', '?')
            img_desc = meta.get('image_description', '') or ''
            line = f'{i}. [{year_month}, #{channel}] "{escaped}"'
            if img_desc:
                line += f' [image: {img_desc[:120]}]'
            formatted += line + '\n'

        return formatted

    def search_by_name(
        self,
        name: str,
        top_k: int = 10
    ) -> list[str]:
        """
        Search for messages that mention a specific name/username.

        Uses ChromaDB's where_document filter to find messages containing
        the name (case-insensitive search via lowercase matching).

        Args:
            name: The username/display name to search for
            top_k: Maximum number of results

        Returns:
            List of messages mentioning that name
        """
        if not name or not name.strip():
            return []

        name_lower = name.lower().strip()

        try:
            # ChromaDB where_document $contains is case-sensitive
            # We'll search for common variations
            results = self.collection.query(
                query_texts=[name_lower],  # Use name as semantic query too
                n_results=top_k * 3,  # Get more results to filter
                where_document={"$contains": name_lower},
                include=['documents']
            )

            messages = []
            if results['documents'] and results['documents'][0]:
                for doc in results['documents'][0]:
                    if name_lower in doc.lower():
                        messages.append(doc)
                        if len(messages) >= top_k:
                            break

            # If no exact matches, try just the semantic search
            if not messages:
                results = self.collection.query(
                    query_texts=[f"talking to {name} insulting {name} {name} is"],
                    n_results=top_k,
                    include=['documents']
                )
                if results['documents'] and results['documents'][0]:
                    messages = results['documents'][0]

            return messages

        except Exception as e:
            logger.warning(f"Error searching by name '{name}': {e}")
            return []

    def search_by_name_formatted(
        self,
        name: str,
        top_k: int = 10
    ) -> str:
        """
        Search for messages about a user and format for prompt injection.

        Args:
            name: The username/display name to search for
            top_k: Maximum number of results

        Returns:
            Formatted string with past messages about this user
        """
        messages = self.search_by_name(name, top_k)

        if not messages:
            return ""

        formatted = f"## Past messages mentioning or about {name}:\n"
        for i, msg in enumerate(messages, 1):
            escaped = msg.replace('"', "'")
            formatted += f'{i}. "{escaped}"\n'

        return formatted


# Module-level retriever instance (lazy loaded)
_retriever: Optional[MessageRetriever] = None


def _get_retriever() -> MessageRetriever:
    """Get or create the singleton retriever."""
    global _retriever
    if _retriever is None:
        _retriever = MessageRetriever()
    return _retriever


def get_relevant_messages(query: str, top_k: int = TOP_K) -> list[str]:
    """
    Get relevant messages for a query.

    Convenience function that handles retriever initialization.

    Args:
        query: The message to find similar content for
        top_k: Maximum number of results

    Returns:
        List of similar message strings
    """
    return _get_retriever().retrieve(query, top_k)


def get_formatted_context(query: str, top_k: int = TOP_K) -> str:
    """
    Get formatted context string for prompt injection.

    Convenience function that handles retriever initialization.

    Args:
        query: The message to find similar content for
        top_k: Maximum number of results

    Returns:
        Formatted string ready to append to system prompt
    """
    return _get_retriever().retrieve_formatted(query, top_k)


def search_messages_about_user(name: str, top_k: int = 10) -> list[str]:
    """
    Search for messages mentioning a specific user.

    Args:
        name: The username/display name to search for
        top_k: Maximum number of results

    Returns:
        List of messages mentioning that user
    """
    return _get_retriever().search_by_name(name, top_k)


def get_user_context(name: str, top_k: int = 10) -> str:
    """
    Get formatted context about a specific user for prompt injection.

    Args:
        name: The username/display name to search for
        top_k: Maximum number of results

    Returns:
        Formatted string with past messages about this user
    """
    return _get_retriever().search_by_name_formatted(name, top_k)


def get_formatted_context_rich(query: str, top_k: int = TOP_K, where: dict = None) -> str:
    """
    Get formatted context with metadata annotations (time, channel).

    Drop-in upgrade for get_formatted_context() that includes temporal
    and channel context so the LLM can distinguish recent vs old messages.
    """
    return _get_retriever().retrieve_formatted_rich(query, top_k, where=where)


def get_relevant_messages_filtered(
    query: str,
    top_k: int = TOP_K,
    persona_only: bool = False,
    after_timestamp: float = None,
    channel: str = None,
) -> list[str]:
    """
    Get relevant messages with optional metadata filters.

    Builds the ChromaDB where clause from simple parameters.
    """
    where_clauses = []
    if persona_only:
        where_clauses.append({"is_persona": {"$eq": 1}})
    if after_timestamp:
        where_clauses.append({"timestamp_unix": {"$gt": after_timestamp}})
    if channel:
        where_clauses.append({"channel_name": {"$eq": channel}})

    where = None
    if len(where_clauses) == 1:
        where = where_clauses[0]
    elif len(where_clauses) > 1:
        where = {"$and": where_clauses}

    return _get_retriever().retrieve(query, top_k, where=where)


def get_random_memory_samples(count: int = 5) -> list[str]:
    """
    Get random message samples from the RAG database.

    Useful for spontaneous messages when there's no recent context -
    provides actual memory content to reference rather than generating
    generic statements.

    Args:
        count: Number of random samples to retrieve

    Returns:
        List of random message strings from the database
    """
    import random as rand_module

    retriever = _get_retriever()
    try:
        # Get total count in collection
        total = retriever.collection.count()
        if total == 0:
            return []

        # Sample random IDs - ChromaDB uses string IDs
        # We'll get a larger sample and pick randomly from it
        sample_size = min(count * 10, total)

        # Use offset to get different parts of the collection
        results = retriever.collection.get(
            limit=sample_size,
            offset=rand_module.randint(0, max(0, total - sample_size)),
            include=['documents']
        )

        if results['documents']:
            # Randomly sample from results
            samples = rand_module.sample(
                results['documents'],
                min(count, len(results['documents']))
            )
            return samples
        return []

    except Exception as e:
        logger.warning(f"Error getting random memory samples: {e}")
        return []


# ============== QUERY DETECTION ==============

# Temporal keyword patterns → timedelta for recency cutoff
_RECENCY_PATTERNS: list[tuple[str, timedelta]] = [
    (r'\brecently\b', timedelta(days=30)),
    (r'\blately\b', timedelta(days=30)),
    (r'\blast week\b', timedelta(days=7)),
    (r'\bthis week\b', timedelta(days=7)),
    (r'\blast month\b', timedelta(days=30)),
    (r'\bthis month\b', timedelta(days=30)),
    (r'\bthis year\b', timedelta(days=365)),
    (r'\bnowadays\b', timedelta(days=60)),
    (r'\bthese days\b', timedelta(days=60)),
]

# Past patterns: (regex, *args) where args vary by type:
#   2-tuple with None  → extract year from capture group
#   3-tuple            → range filter (max_delta, min_delta) = "between X and Y ago"
#   2-tuple with delta → "older than X"
_PAST_PATTERNS: list[tuple] = [
    (r'\bback in (\d{4})\b', None),
    (r'\bin (\d{4})\b', None),
    (r'\blast year\b', timedelta(days=730), timedelta(days=365)),
    (r'\bused to\b', timedelta(days=365)),
    (r'\bremember when\b', timedelta(days=180)),
]

# Author query patterns: capture group 1 is the name
_AUTHOR_QUERY_PATTERNS = [
    r'what (?:did|was|does|has) (\w+) (?:say|said|argue|arguing|talk|talking|post|think|mean)',
    r"(\w+)'s? (?:take|opinion|views?|thoughts?) (?:on|about)",
    r'(?:when|where) (?:did|was) (\w+)',
    r'what (\w+) (?:thinks?|said|wrote|posted)',
]

_NOT_NAMES = frozenset({
    'you', 'she', 'he', 'they', 'we', 'someone', 'anyone',
    'everyone', 'i', 'u', 'it', 'that', 'this', 'the',
})


def detect_temporal_filter(query: str) -> Optional[dict]:
    """
    Detect temporal intent from a query and return a ChromaDB where clause.

    Returns None if no temporal signal is found.
    Returns a dict suitable for ChromaDB's `where` parameter.

    Examples:
        "what did she say recently" → {"timestamp_unix": {"$gt": <30d ago>}}
        "back in 2024"             → {"$and": [year_month >= "2024-01", <= "2024-12"]}
    """
    query_lower = query.lower()
    now = time.time()

    # Check recency patterns first (more common)
    for pattern, delta in _RECENCY_PATTERNS:
        if re.search(pattern, query_lower):
            cutoff = now - delta.total_seconds()
            return {"timestamp_unix": {"$gt": cutoff}}

    # Check past/historical patterns
    for entry in _PAST_PATTERNS:
        pattern = entry[0]
        match = re.search(pattern, query_lower)
        if not match:
            continue

        # Year extraction: "back in 2024", "in 2024"
        if entry[1] is None and match.lastindex and match.lastindex >= 1:
            year = int(match.group(1))
            if 2020 <= year <= datetime.now().year:
                return {"$and": [
                    {"year_month": {"$gte": f"{year}-01"}},
                    {"year_month": {"$lte": f"{year}-12"}},
                ]}
            continue

        # Range: "last year" → between 1-2 years ago
        if len(entry) == 3:
            max_delta, min_delta = entry[1], entry[2]
            return {"$and": [
                {"timestamp_unix": {"$gt": now - max_delta.total_seconds()}},
                {"timestamp_unix": {"$lt": now - min_delta.total_seconds()}},
            ]}

        # Simple "older than X": "used to", "remember when"
        delta = entry[1]
        return {"timestamp_unix": {"$lt": now - delta.total_seconds()}}

    return None


def detect_author_filter(query: str) -> Optional[str]:
    """
    Detect if a query is asking about a specific person's messages.

    Returns the extracted name (lowercase) or None.
    Does NOT validate that the name exists in the database —
    the caller should handle empty results gracefully.
    """
    query_lower = query.lower()
    for pattern in _AUTHOR_QUERY_PATTERNS:
        match = re.search(pattern, query_lower)
        if match:
            name = match.group(1).strip()
            if name not in _NOT_NAMES and len(name) > 1:
                return name
    return None


def get_smart_context(query: str, top_k: int = TOP_K) -> str:
    """
    Smart RAG retrieval with automatic temporal and author detection.

    Always excludes messages newer than MIN_RAG_AGE_HOURS (they're already
    in the conversation buffer). Additionally detects temporal keywords and
    author references in the query to apply fine-grained filters, and falls
    back to SQLite keyword search when semantic results are thin.
    """
    retriever = _get_retriever()

    time_filter = detect_temporal_filter(query)
    author = detect_author_filter(query)

    if time_filter:
        logger.info(f"RAG temporal filter detected: {time_filter}")
    if author:
        logger.info(f"RAG author filter detected: '{author}'")

    # Always exclude very recent messages — they're already in the buffer
    age_filter = {"timestamp_unix": {"$lt": time.time() - MIN_RAG_AGE_HOURS * 3600}}

    # Merge the age floor with any explicit temporal filter from the query
    if time_filter:
        effective_time_filter = {"$and": [age_filter, time_filter]}
    else:
        effective_time_filter = age_filter

    # Use hybrid search when temporal or author filters are active
    if time_filter or author:
        return retriever.hybrid_retrieve_formatted(
            query, top_k=top_k,
            time_filter=effective_time_filter,
            author_name=author,
        )

    # No author/time filters — fast pure-semantic path with age floor
    return retriever.retrieve_formatted_rich(query, top_k, where=effective_time_filter)


async def embed_live_message(message_id: str, content: str, metadata: dict) -> bool:
    """
    Embed a single message into ChromaDB in real-time.
    Called from on_message_create after inserting into live_messages.

    Uses asyncio.to_thread to avoid blocking the event loop since
    sentence-transformers encode() is CPU-bound.

    Args:
        message_id: Discord message snowflake ID as string
        content: Message text content
        metadata: Dict matching embedder schema (author_id, author_name,
                  channel_name, timestamp_unix, year_month, is_persona,
                  is_reply, reply_to_author, char_length, word_count)

    Returns:
        True if embedded successfully, False if filtered/skipped
    """
    text = content.strip()

    # Apply same filters as batch embedder (embedder.py lines 85-94)
    if not text:
        return False
    if len(text) < MIN_MESSAGE_LENGTH or len(text) > MAX_MESSAGE_LENGTH:
        return False
    if text.startswith(('http', '<http')):
        return False
    if re.match(r'^(<a?:\w+:\d+>\s*)+$', text):
        return False
    if text.startswith(('/', '.', '!')):
        return False
    if re.match(r'^(<@!?\d+>\s*)+$', text):
        return False

    try:
        retriever = _get_retriever()
    except Exception:
        return False

    def _encode_and_upsert():
        embedding = retriever.model.encode(text).tolist()
        retriever.collection.upsert(
            ids=[message_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata],
        )

    await asyncio.to_thread(_encode_and_upsert)
    logger.debug(f"Live embedded message {message_id}")
    return True
