import os
from pprint import pprint
import traceback
import time
import json
import common.discord as discord
import common.logger as logger
from reddit.reddit import Reddit

logger = logger.get_logger('reddit_monitor')


def run_bot():
    global post_ids

    Monitor = Reddit(
        name='reddit',
        queries=[
            'trans',
            'boymode',
            '4tran'
            'am i trans'
        ],
        subreddits=[
            'egg_irl',
            '4tran4',
            '4tran',
            'asktransgender',
            'mtf',
            'transpositive',
            'Nestofeggs',
            'traaaaaaannnnnnnnnns',
            'traaaaaaannnnnnnnnns2'
        ],
        post_ids=post_ids.get('reddit', []),
        channel_ids=[
            1158203872423186459,  # trannerland
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
                    author=post['subreddit'],
                    description=post['description'],
                    image=post.get('image'),
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

            time.sleep(2 * 3600)

        except:
            logger.error(traceback.format_exc())
            time.sleep(30 * 60)


def debug():
    global post_ids
    pass


if __name__ == '__main__':
    # Open the post_ids file if it exists
    if os.path.exists('post_ids.json'):
        with open('post_ids.json', 'r') as pf:
            post_ids = json.load(pf)

    else:
        with open('post_ids.json', 'w') as pf:
            json.dump({}, pf)
            post_ids = {}

    run_bot()
