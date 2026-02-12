"""
Shared data models used across multiple bots.

These dataclasses provide typed contracts for data passed between
modules, making the codebase more AI-collaboration friendly by
documenting expected fields explicitly.
"""

from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime


@dataclass
class LiveMessageData:
    """
    Data for a live Discord message heading into insert_live_message().

    This standardizes the dict that all bots construct in on_message_create
    so the field names are consistent everywhere. Bots can either pass
    this as a dict via asdict() or use it for type-checking.

    Usage:
        from common.models import LiveMessageData
        from dataclasses import asdict

        msg = LiveMessageData(
            message_id=str(event.message.id),
            channel_id=str(event.message.channel.id),
            ...
        )
        insert_live_message(asdict(msg))
    """
    message_id: str
    channel_id: str
    author_id: str
    content: str = ""
    author_name: Optional[str] = None
    author_nickname: Optional[str] = None
    author_avatar_url: Optional[str] = None
    timestamp: Optional[str] = None
    timestamp_edited: Optional[str] = None
    is_pinned: bool = False
    is_reply: bool = False
    reply_to_message_id: Optional[str] = None
    attachments: List[dict] = field(default_factory=list)
    embeds: List[dict] = field(default_factory=list)
    reactions: List[dict] = field(default_factory=list)
    mentions: List[dict] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())


@dataclass
class EmbeddingMetadata:
    """
    Metadata stored alongside each embedded message in ChromaDB.

    ChromaDB metadata values must be str, int, float, or bool.
    No nested dicts or lists allowed. This dataclass documents
    the exact fields the RAG embedder produces and the retriever
    expects when filtering.

    Usage:
        from common.models import EmbeddingMetadata
        from dataclasses import asdict

        meta = EmbeddingMetadata(
            author_id="1436260342475919365",
            author_name="nadia",
            channel_name="general",
            timestamp_unix=1697868023.576,
            year_month="2023-10",
            is_persona=1,
        )
        collection.upsert(ids=[msg_id], metadatas=[asdict(meta)], ...)
    """
    author_id: str = ""
    author_name: str = ""
    channel_name: str = ""
    timestamp_unix: float = 0.0
    year_month: str = ""          # "YYYY-MM" for easy equality/range filters
    is_persona: int = 0           # 1 if this is the persona user's message
    is_reply: int = 0
    reply_to_author: str = ""     # who they were replying to
    mentions: str = ""            # comma-separated mentioned usernames
    char_length: int = 0
    word_count: int = 0
