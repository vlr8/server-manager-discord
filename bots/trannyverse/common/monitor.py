from abc import ABC, abstractmethod
from typing import List
"""
Abstract class for monitoring website

Methods:
initialize/sign_in
search/get_posts
get_discord_post

Configuration:
amount of posts per batch
time delay between each retrieval

specific accounts/keywords to be defined in specific modules
"""

class AbstractMonitor(ABC):
    def __init__(self,
				name: str,
				channel_ids: List[str],
				post_ids: List[str],
				webhook_name: str,
				webhook_icon: str,
				color_scheme: int,
				url_only=False) -> None:
        self.name = name
        self.channel_ids = channel_ids
        self.post_ids = post_ids
        self.webhook_name = webhook_name
        self.webhook_icon = webhook_icon
        self.color_scheme = color_scheme
        self.url_only = url_only

    def fetch_posts(self):
        pass