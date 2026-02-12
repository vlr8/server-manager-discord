from datetime import datetime

class DiscordPost:
	def __init__(self,
				id: str,
				title: str,
				description: str,
				date: datetime,
				url: str,
				image: str = None,
				thumbnail: str = None):
		self.id = id
		self.title = title
		self.description = description
		self.date = date
		self.url = url
		self.image = image
		self.thumbnail = thumbnail

	def __getitem__(self, key):
		return self[key]

	def __setitem__(self, key, value):
		setattr(self, key, value)
