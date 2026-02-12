import warnings
from datetime import datetime
import pprint
import random
import requests
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning
import common.utils as utils

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)


class Fourchan:
    def __init__(self, name, board, post_ids, channel_ids):
        self.name = name
        self.board = board
        self.post_ids = post_ids
        self.channel_ids = channel_ids
        self.webhook_name = f"/{board}/"
        self.webhook_icon = "https://i.imgur.com/qCdjRTa.png"
        self.color_scheme = 7903522
        self.url_only = False

    def fetch_posts(self):
        proxies = utils.fetch_proxies()
        proxy = random.choice(proxies)
        
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8',
            'priority': 'u=0, i',
            'sec-ch-ua': '"Not)A;Brand";v="99", "Google Chrome";v="127", "Chromium";v="127"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'none',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
        }
        resp = requests.get(f"https://a.4cdn.org/{self.board}/catalog.json", proxies=proxy, headers=headers)
        posts = resp.json()

        posts = [thread for x in posts for thread in x['threads']]

        formatted_posts = []
        # Clean the Data of HTML trash
        for post in posts:
            # If the post has text
            if post.get("com"):
                # Replace <br> tags with newline characters
                text = BeautifulSoup(post['com'], 'html.parser')
                for br in text.find_all("br"):
                    br.replace_with("\n")

                post['com'] = text.text

            # if the post has a subject
            if post.get("sub"):
                subject = post['sub']
                subject = BeautifulSoup(post['sub'], 'html.parser').text
                post['sub'] = subject

            # If the posts has no subject but has a comment
            elif post.get("com") and not post.get("sub"):
                # Get the first sentence of the post
                subject = post['com'].split('.')[0].split('\n')[0]

            # If the post has no subject or comment
            else:
                subject = "Post"

            # Get the image
            if post.get('tim'):
                filetype = post['ext'].replace('.', '').replace('jpeg', 'jpg')
                filename = f"{post['tim']}.{filetype}"

                # if filetype is not image
                if filetype not in ['jpg', 'png', 'gif']:
                    filename = f"{post['tim']}s.jpg"

                image = f"https://i.4cdn.org/lgbt/{filename}"

            else:
                image = None

            formatted_posts.append({
                'id': post['no'],
                'title': subject,
                'description': post['com'] if post.get('com') else None,
                'thumbnail': image,
                'date': datetime.strptime(post['now'], "%m/%d/%y(%a)%H:%M:%S"),
                'url': f"https://trannyverse.vercel.app/lgbt/thread/{post['no']}",
            })

        return formatted_posts


def debug():
    pass
    # posts = fetch_posts('lgbt')
    # pprint.pprint(posts, indent=4)


if __name__ == "__main__":
    debug()
