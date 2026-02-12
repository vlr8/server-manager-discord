import random
import time
import common.utils as utils
import common.proxies as proxies
import common.logger as logger
import requests, json
from datetime import datetime

logger = logger.get_logger('reddit')
use_proxies = True
proxy_list = proxies.read_proxy_file("common/proxies.txt")
if len(proxy_list) == 0:
    use_proxies = False
    logger.info("No proxies found, using local IP address")


def make_request(url: str, params=None):
    headers = {
        'authority': 'www.reddit.com',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8,de;q=0.7',
        'cache-control': 'max-age=0',
        'dnt': '1',
        'sec-ch-ua': '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'none',
        'sec-fetch-user': '?1',
        'upgrade-insecure-requests': '1',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
    }
    
    # proxies = utils.fetch_proxies()
    proxy = random.choice(proxy_list) if use_proxies else None
    
    resp = requests.get(url, params=params, headers=headers, proxies=proxy)
    if resp.status_code == 429:
        logger.error(f'Rate limited, retrying in 60 seconds, status code: {resp.status_code}')
        time.sleep(60)
        return make_request(url, params)
    return resp.json()


def get_subreddit(name, sortby='hot', query=None):
    posts = []
    params = {
        'raw_json': '1',
        'include_over_18': 'on',
    }
    if query:
        params['q'] = query
        params['restrict_sr'] = 'on'
        params['sort'] = 'relevance'
        params['t'] = 'week'

    data = make_request(f'https://www.reddit.com/r/{name}/{sortby}.json', params)
    try:
        data = data['data']['children']
        for post in data[2:12]:  # only get 10 high rated posts
            post = post['data']
            posts.append(get_post(post['id']))

    except Exception as e:
        logger.warn(f'could not retrieve subreddit posts for {name} ex: {e}')

    return posts


def search_posts(query, nsfw=False, timerange='week'):
    posts = []
    params = {
        'raw_json': '1',
        'include_over_18': 'on' if nsfw else 'off',
        'q': query,
        'restrict_sr': 'on',
        'sort': 'relevance',
        't': timerange,
    }
    data = make_request('https://www.reddit.com/search.json', params)

    try:
        data = data['data']['children']
        for post in data[2:12]:  # only get 10 results
            post = post['data']
            posts.append(get_post(post['id']))

    except Exception as e:
        logger.warn(f'could not retrieve reddit search posts for {query} ex: {e}')

    return posts


def get_post(ID):
    data = make_request(f'https://www.reddit.com/comments/{ID}.json')
    post = data[0]['data']['children'][0]['data']
    thumbnail = post.get('thumbnail')
    if 'http' not in thumbnail:
        thumbnail = None
    discordPost = {
        'id': post['id'],
        'subreddit': post['subreddit'],
        'title': post['title'],
        'description': post['selftext'],
        'date': datetime.fromtimestamp(post['created_utc']),
        'url': f"https://www.reddit.com{post['permalink']}",
        'image': None,
        'thumbnail': thumbnail
    }

    return discordPost


class Reddit:
    def __init__(self, name, queries, subreddits, post_ids, channel_ids):
        self.name = name
        self.color_scheme = 16721664
        self.subreddits = subreddits
        self.queries = queries
        self.post_ids = post_ids
        self.channel_ids = channel_ids
        self.webhook_name = "Reddit"
        self.webhook_icon = "https://i.imgur.com/88Bgpj2.png"

    def fetch_posts(self):
        posts = []
        for subreddit in self.subreddits:
            logger.info(f'Fetching posts from {subreddit}')
            posts += get_subreddit(subreddit)

            # Sleep for 2 minutes to avoid rate limiting
            time.sleep(2 * 60)

        for query in self.queries:
            logger.info(f'Fetching posts from search query: {query}')
            posts += search_posts(query)
            
            # Sleep for 2 minutes to avoid rate limiting
            time.sleep(2 * 60)

        return posts


def debug():
    # resp = get_subreddit('egg_irl')
    resp = search_posts('trans', nsfw=False)
    # random_id = random.choice(resp)['id']
    # resp = get_post(random_id)

    # resp = get_post('ttqyt')
    print(json.dumps(resp, indent=4))


if __name__ == '__main__':
    debug()
