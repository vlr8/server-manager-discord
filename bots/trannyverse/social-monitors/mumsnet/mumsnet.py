import time
import traceback
import requests
import random
import common.proxies as proxies
import common.logger as logger
import re
from datetime import datetime

logger = logger.get_logger('mumsnet')
use_proxies = False
proxy_list = proxies.read_proxy_file("mumsnet/proxies.txt")
if len(proxy_list) == 0:
    use_proxies = False
    logger.info("No proxies found, using local IP address")


def generate_client_id():
    hex_characters = '0123456789abcdef'
    random_hex_string = ''.join(random.choice(hex_characters) for _ in range(32))
    return str(random_hex_string)


def search(query, page=1):
    headers = {
        'Host': 'www.mumsnet.com',
        'accept': '*/*',
        'client-id': generate_client_id(),
        'user-agent': 'Mumsnet Talk/44.24 (com.mumsnet.app; build:279; iOS 16.3.1) Alamofire/44.24',
        'accept-language': 'en-DE;q=1.0, zh-Hans-DE;q=0.9, de-DE;q=0.8',
    }

    params = {
        'keywords': query,
        'page': f'{page}',
        'per_page': f'{25}',
    }

    resp = requests.get('https://www.mumsnet.com/api/v1/forums/threads/search',
                        params=params, headers=headers, timeout=20,
                        proxies=random.choice(proxy_list) if use_proxies else None,
                        )
    logger.info(f"Searched {query} {page} {resp.status_code}")
    if resp.status_code == 429:
        logger.warning('Ratelimited, retrying in 60 seconds')
        time.sleep(60)
        return search(query, page)

    elif resp.status_code != 200:
        logger.info(f'Error getting page {resp.status_code} {page}')

    data = resp.json()['data']

    posts = []
    for post in data:
        post_content = get_thread(post['id'])['posts'][0]['post']['post']
        # Format the content in markdown
        post_content = post_content.replace('^', '*')
        # Search for URLs within [[ and ]] and replace them with discord friendly format
        post_content = re.sub(r'\[\[(https://[^\s]+)\s+(.*?)\]\]', r'[\2](\1)', post_content)
        # Remove 'https://' from the string part inside the square brackets because discord doesn't like it
        post_content = re.sub(r'\[https://', r'[', post_content)

        posts.append({
            'id': post['id'],
            'title': post['attributes']['name'],
            'description': post_content,
            'date': datetime.strptime(post['attributes']['created'], '%Y-%m-%dT%H:%M:%S%z'),
            'url': f"https://www.mumsnet.com/talk/{post['relationships']['topic']['data']['links']['self']}/{post['links']['self']}",
        })

    return posts


def get_thread(thread_id):
    headers = {
        'Host': 'www.mumsnet.com',
        'accept': '*/*',
        'client-id': generate_client_id(),
        'user-agent': 'Mumsnet Talk/44.24 (com.mumsnet.app; build:279; iOS 16.3.1) Alamofire/44.24',
        'accept-language': 'en-DE;q=1.0, zh-Hans-DE;q=0.9, de-DE;q=0.8',
    }
    params = {
        'page': '1',
        'per': '25',
        'thread_direction': '1',
        'thread_id': f'{thread_id}',
    }

    resp = requests.get('https://www.mumsnet.com/api/v1/forums/posts',
                        params=params, headers=headers, timeout=20,
                        proxies=random.choice(proxy_list) if use_proxies else None,
                        )
    if resp.status_code == 429:
        logger.warning('Ratelimited, retrying in 60 seconds')
        time.sleep(60)
        return get_thread(thread_id)

    elif resp.status_code != 200:
        logger.info(f'Error getting thread {resp.status_code} {thread_id}')

    logger.info(f"Fetched thread {thread_id} {resp.status_code}")
    data = resp.json()

    return data


class Mumsnet:
    def __init__(self, name, queries, keywords, post_ids, channel_ids, max_pages=399):
        self.name = name
        self.queries = queries
        self.keywords = keywords
        self.post_ids = post_ids
        self.channel_ids = channel_ids
        self.webhook_name = "Mumsnet"
        self.webhook_icon = "https://i.imgur.com/tBn4saa.png"
        self.color_scheme = 6311830
        self.url_only = False
        self.max_pages = max_pages

    def fetch_posts(self):
        posts = []
        for query in self.queries:
            logger.info(f'Query: {query}')
            for page in range(1, self.max_pages+1):
                logger.info(f'Page: {page}')
                try:
                    posts.extend(search(query, page))

                except:
                    logger.info(traceback.format_exc())
                    continue

                time.sleep(60)

        # If any query word is not in the title or content, skip
        filtered_posts = []
        for post in posts:
            pattern = r'\b(?:' + '|'.join(re.escape(word) for word in self.keywords) + r')\b'
            if not re.search(pattern, post['title'].lower()) and not re.search(pattern, post['description'].lower()):
                # Remove the post from the list of posts
                continue

            filtered_posts.append(post)

        return filtered_posts


def debug():
    import json

    res = search('trans')
    logger.info(json.dumps(res, indent=4))


# postres = get_thread(res[0]['id'])
# print(json.dumps(postres, indent=4))


if __name__ == '__main__':
    debug()
