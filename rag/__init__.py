"""RAG (Retrieval Augmented Generation) package for persona bot."""

from .retriever import (
    get_relevant_messages,
    get_formatted_context,
    get_formatted_context_rich,
    get_relevant_messages_filtered,
    get_smart_context,
    MessageRetriever,
    get_random_memory_samples,
    embed_live_message,
)

__all__ = [
    'get_relevant_messages',
    'get_formatted_context',
    'get_formatted_context_rich',
    'get_relevant_messages_filtered',
    'get_smart_context',
    'MessageRetriever',
    'get_random_memory_samples',
    'embed_live_message',
]
