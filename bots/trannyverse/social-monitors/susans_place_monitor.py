import time
from bs4 import BeautifulSoup
import common.utils as utils
import random
import common.discord as discord
import common.proxies as proxies
import common.logger as logger
import requests
from datetime import datetime
import os
import traceback
import json
from pprint import pprint


logger = logger.get_logger('susans_place')
use_proxies = False
proxy_list = proxies.read_proxy_file("common/proxies.txt")
if len(proxy_list) == 0:
    use_proxies = False
    logger.info("No proxies found, using local IP address")

excluded_boards = ['Birthdays']

def get_boards():
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-GB,en;q=0.9',
        'Cache-Control': 'max-age=0',
        'Connection': 'keep-alive',
        'If-Modified-Since': 'Fri, 20 Dec 2024 23:48:22 GMT',
        'Referer': 'https://www.google.com/',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'cross-site',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
    }

    response = requests.get('https://www.susans.org/', headers=headers)
    data = BeautifulSoup(response.text, 'html.parser')
    boards_elements = data.find_all('div', class_='info')

    boards = []
    for board_el in boards_elements:
        board = {
            'title': board_el.find('a', class_='subject').text.strip(),
            'url': board_el.find('a', class_='subject')['href']
        }
        boards.append(board)

        # check for sub boards
        sub_boards_list = board_el.parent.find('div', class_='children')
        if sub_boards_list:
            sub_boards = [{
                'title': x.text.strip(),
                'url': x['href']
            } for x in sub_boards_list.find_all('a')]

            boards += sub_boards

    return boards


def get_posts(board_url, board_name):
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-GB,en;q=0.9',
        'Cache-Control': 'max-age=0',
        'Connection': 'keep-alive',
        'If-Modified-Since': 'Sat, 21 Dec 2024 00:53:33 GMT',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
    }

    response = requests.get(board_url, headers=headers)
    data = BeautifulSoup(response.text, 'html.parser')
    posts_list = data.find('div', id='topic_container').find_all('div', class_='info info_block')

    post_containers = [x.find('a') for x in posts_list]

    posts = []
    for container in post_containers:
        url = container['href']
        ID = url.split(',')[1].split('.')[0]

        posts.append({
            'board': board_name,
            'id': ID,
            'title': container.text.strip(),
            'url': url,
        })

    return posts


def get_post(post_data):
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-GB,en;q=0.9',
        'Cache-Control': 'max-age=0',
        'Connection': 'keep-alive',
        'If-Modified-Since': 'Sat, 21 Dec 2024 01:02:22 GMT',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
    }

    response = requests.get(post_data['url'], headers=headers)
    data = BeautifulSoup(response.text, 'html.parser')
    postelement = data.find('div', id='forumposts').find('div', class_='post_wrapper')

    try:
        post_data['thumbnail'] = postelement.find('div', class_='poster').find('li', class_='avatar').find('img')['src']
    except:
        post_data['thumbnail'] = None

    post_data['description'] = postelement.find('div', class_='post').text
    post_data['date'] = postelement.find('div', class_='postinfo').find('a', class_='smalltext').text

    # date might have 'Yesterday' or 'Today' in it
    if 'Yesterday' in post_data['date']:
        post_data['date'] = post_data['date'].replace('Yesterday', datetime.now().strftime("%B %d, %Y"))
    elif 'Today' in post_data['date']:
        post_data['date'] = post_data['date'].replace('Today', datetime.now().strftime("%B %d, %Y"))

    # if the date has "at" in it
    if 'at' in post_data['date']:
        post_data['date'] = post_data['date'].replace(' at', ',')

    post_data['date'] = datetime.strptime(post_data['date'], "%B %d, %Y, %I:%M:%S %p")

    return post_data


class SusansPlace:
    def __init__(self, name, post_ids, channel_ids):
        self.name = name
        self.color_scheme = 16756180
        self.post_ids = post_ids
        self.channel_ids = channel_ids
        self.webhook_name = "Susans Place"
        self.webhook_icon = "https://i.imgur.com/v4UnpQL.png"

    def fetch_posts(self):
        posts = []

        # debugboards
        # debug_boards = get_boards()
        # random.shuffle(debug_boards)
        # debug_boards = debug_boards[:3]

        for board in get_boards():
            if board['title'] in excluded_boards:
                continue

            logger.info(f'Fetching posts for board: <{board["title"]}>')
            board_posts = get_posts(board['url'], board['title'])

            for post in board_posts:
                if post['id'] in self.post_ids:
                    continue

                post = get_post(post)
                posts.append(post)

        return posts



def run_bot():
    global post_ids

    Monitor = SusansPlace(
        name='susans_place',
        post_ids=post_ids.get('susans_place', []),
        channel_ids=[
            1319837463228846160,  # trannerland
        ],
    )

    repost_to_discord(Monitor)


def repost_to_discord(Monitor):
    while True:
        try:
            global post_ids

            # Fetch new posts
            posts = Monitor.fetch_posts()
            logger.info(f"Fetched {len(posts)} posts from {Monitor.name}")

            # Remove posts that have already been posted
            posts = [x for x in posts if x['id'] not in Monitor.post_ids]

            # Sort posts by date (oldest first)
            posts = sorted(posts, key=lambda x: x['date'])

            # Add the new posts to the list of posted posts
            Monitor.post_ids += [post['id'] for post in posts]

            # Post the new posts to Discord
            for post in posts:
                discord.post(
                    title=post['title'],
                    author=post['board'],
                    description=post['description'],
                    thumbnail=post.get('thumbnail'),
                    date=post['date'],
                    url=post['url'],
                    site_name=Monitor.webhook_name,
                    site_icon=Monitor.webhook_icon,
                    color_scheme=Monitor.color_scheme,
                    channel_ids=Monitor.channel_ids,
                )

            # Save the new list of posted posts
            post_ids[Monitor.name] = Monitor.post_ids
            with open('post_ids.json', 'w') as f:
                json.dump(post_ids, f, indent=4)

            time.sleep(1 * 3600)

        except:
            logger.error(traceback.format_exc())
            time.sleep(30 * 60)



def debug():
    # resp = get_boards()
    resp = get_posts('https://www.susans.org/index.php/board,43.0.html', 'General Discussions')

    for post in resp:
        post = get_post(post)
        pprint(post)


if __name__ == '__main__':
    # debug()
    # exit(0)

    # Open the post_ids file if it exists
    if os.path.exists('post_ids.json'):
        with open('post_ids.json', 'r') as pf:
            post_ids = json.load(pf)

    else:
        with open('post_ids.json', 'w') as pf:
            json.dump({}, pf)
            post_ids = {}

    run_bot()