import requests
from datetime import datetime
import re
import common.logger as logger

logger = logger.get_logger('tumblr')

def safe_access(lst, start, end):
	if start < 0 or end > len(lst):
		return
	return lst[start:end]


def search(query, limit=20):
	headers = {
		'authority': 'www.tumblr.com',
		'accept': 'application/json;format=camelcase',
		'accept-language': 'en-us',
		'authorization': 'Bearer aIcXSOoTtqrzR8L8YEIOmBeW94c3FmbSNSWAUbxsny9KKx5VFh',
		'dnt': '1',
		'referer': 'https://www.tumblr.com/',
		'sec-ch-ua': '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
		'sec-ch-ua-mobile': '?0',
		'sec-ch-ua-platform': '"macOS"',
		'sec-fetch-dest': 'empty',
		'sec-fetch-mode': 'cors',
		'sec-fetch-site': 'same-origin',
		'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
		'x-ad-blocker-enabled': '1',
		'x-version': 'redpop/3/0//redpop/',
	}

	params = {
		'limit': str(limit),
		'days': '0',
		'query': query,
		'mode': 'top',
		'timeline_type': 'post',
		'skip_component': 'related_tags,blog_search',
		'reblog_info': 'true',
		'fields[blogs]': 'name,avatar,title,url,blog_view_url,is_adult,?is_member,description_npf,uuid,can_be_followed,?followed,?advertiser_name,theme,?primary,?is_paywall_on,?paywall_access,?subscription_plan,tumblrmart_accessories,?live_now,can_show_badges,share_following,share_likes,ask',
		# 'cursor': 'VJU3-Muf-4nczNQ_W6_WzWA4NP_FIqYhDelac94_1-cxa2ttbzZCbDZsQTZvc1Z5SS9EaXlSYUczSEF1Vk1SR1V2MGdOUFZRUVNPaHMyYytJdHNtZjQ4a1hTVEd3SUd6cUFWRVU4RWhFSkpqYzZva094elNWUXZLRDVpT3loYldwUXpoMUN5cFA0SEJLais1VDFGRWpBZjRzRUdiK1NJUTh1bDQ1YVY5UTl3MGU1NUwxNkVQUVVTQnpWYUU0V0h6aWVyUjJCM0dpTjBtVGt4WUNVeFJqdGJ1R1ZyMm14ZFJvNWhjTVNRMUMvQzBDSzg4RjI2ZnJGdmlIYzFlQWlIa2gyRG85MU56eWRFQ1JRVG9QdytwUC9wZ2JQbWJtdzFlWmpRTTAza29ZeFErUFRJTjZLTVF3R0sveC85QkhlTTNhSEVwRWNxNjVDRG1ZQ2dEZy9EZjIrRENMWkJ2ay9YMzJxWnJZM3BBZHFET1RPc2xkbmI4akdjSDF6dVBMV01UNk1tNC9tcTUweElYVEdZUEZ4SlcxVnNBNGdTcEJpY3VwY2lsUzNhSjgyMTkzT29nQ0E0Z0RpSEREWGx0bDlUUFovYXBJbGxFZzQ5NkVzOXpFU3ZJR3dlc1hVUmRuSEJTY3RCWDRXNnVmRWpjb05NVmRNcjFXaWRBRHR4ODk0SG9va3I3OEZNV3hJeFBpK2hSdVlyd1lINnZXenBwWDBEZ2xDZ0thaWt2QkNTcTZYaVlPQVJGWnJaME54KzFlYnpwT05hcHF1R25pay9qNDdDNEp4eEdYYTdxNWloTjB0bmxsT2RxbzlmdlIyRTFQY3IvUVFtRkp4Nk1DYnozbHY2dUhXM2RoaHRONG04K1NFa1Mrc3V4d1c2clRBUFI4Y2MxZg..',
	}

	resp = requests.get('https://www.tumblr.com/api/v2/timeline/search', params=params, headers=headers)
	data = resp.json()['response']['timeline']['elements']

	posts = []
	for post in data:
		try:
			# Get the first 4 images
			images = [x for x in post['content'] if x['type'] == 'image'][:4]
			images = [x['media'][0]['url'] for x in images]

		except (KeyError, IndexError):
			images = None

		if safe_access(images, 0, 1):
			image = images[0]
			if re.match(r'^https?://', image):
				image = image

		description = [x for x in post['content'] if x['type'] == 'text' and 'Submitted' not in x['text']]
		if description:
			description = description[0]['text']

		posts.append({
			'id': post['id'],
			'title': post.get('summary', ''),
			'description': description if description else None,
			'image': images[0] if images else None,
			'url': post['shortUrl'],
			'date': datetime.fromtimestamp(post['timestamp']),
		})

	return posts



class Tumblr:
	def __init__(self, name, queries, post_ids, channel_ids):
		self.name = name
		self.queries = queries
		self.post_ids = post_ids
		self.channel_ids = channel_ids
		self.webhook_name = 'Tumblr'
		self.webhook_icon = 'https://i.imgur.com/2oxBM2b.png'
		self.color_scheme = 6711
		self.url_only = False

	def fetch_posts(self):
		posts = []
		for query in self.queries:
			posts += search(query, limit=1000)

		return posts


def debug():
	pass


if __name__ == '__main__':
	token = "aIcXSOoTtqrzR8L8YEIOmBeW94c3FmbSNSWAUbxsny9KKx5VFh"
	debug()
