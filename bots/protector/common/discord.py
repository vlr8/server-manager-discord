import common.consts as consts
import common.logger as logger
from datetime import datetime
import requests
import time
import os
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN = os.environ['TRANNYVERSE_BOT_TOKEN']
logger = logger.get_logger('discord')


def post(
        channel_ids: list,
        title: str = '',
        author: str = None,
        color_scheme: int = 15335543,
        date: datetime = datetime.utcnow(),
        url: str = None,
        site_name: str = ' ',
        site_icon: str = None,
        description: str = ' ',
        image: str = None,
        thumbnail: str = None,
        url_only=False,
):
    payload = {
        "username": "Trannyverse",
        "avatar_url": "https://i.imgur.com/qnuE4sH.png",
        "embeds": [
            {
                "title": title[:256],
                "description": description[0:2000] if description else "",
                "color": color_scheme,
                "image": {
                    "url": image
                },
                "thumbnail": {
                    "url": thumbnail
                },
                "footer": {
                    "text": "discord.gg/tranners",
                    "icon_url": "https://cdn.discordapp.com/icons/1158203871554961579/98c8eff9b386918ff33535cc68476979.webp"
                },
                "timestamp": date.isoformat(),
                "url": url,
                "author": {
                    "name": author if author else site_name,
                    "icon_url": site_icon
                },
            }
        ]
    }
    if url_only:
        del payload['embeds']
        payload['content'] = f'{url}'

    for channel_id in channel_ids:
        headers = {
            'authorization': 'Bot ' + BOT_TOKEN,
        }

        resp = requests.post(
            f'https://discord.com/api/v9/channels/{channel_id}/messages',
            headers=headers,
            json=payload,
        )
        logger.info(f'posting {url} to {site_name}')
        if resp.status_code == 429:
            logger.warning('Rate limited, retrying in 5 seconds')
            time.sleep(5)
            post(title=title, color_scheme=color_scheme, date=date, url=url, site_name=site_name,
                 site_icon=site_icon, channel_ids=channel_ids, description=description, image=image,
                 thumbnail=thumbnail)

        elif resp.status_code != 200:
            logger.error(f'Error sending webhook: {resp.status_code}\n{resp.text}\n{payload}')
