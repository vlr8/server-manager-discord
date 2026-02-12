import time
import traceback
from datetime import datetime, timedelta
import random
import requests
import os
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN = os.environ['TRANNYVERSE_BOT_TOKEN']

def send_post(data):
    for channel_id in post_to_channels:
        headers = {
            'authorization': 'Bot ' + BOT_TOKEN,
        }

        data['content'] = "Post of the Day :crown:"

        resp = requests.post(
            f'https://discord.com/api/v9/channels/{channel_id}/messages',
            headers=headers,
            json=data,
        )
        if resp.status_code != 200:
            print('Error sending webhook', resp.text, data)


def fetch_posts(channel_id):
    headers = {
        'authorization': 'Bot ' + BOT_TOKEN,
    }

    resp = requests.get(f"https://discord.com/api/v9/channels/{channel_id}/messages?limit=50", headers=headers)
    data = resp.json()

    return data


def pick_random_time(x, y):
    # Current time
    now = datetime.now()

    # Next day's 0:00
    next_day = datetime(year=now.year, month=now.month, day=now.day) + timedelta(days=1)

    if y < x:  # if y is on the next day
        y += 24

    # Seconds range from x to y
    seconds_in_range = (y - x) * 60 * 60

    # Add a random number of seconds from the defined range
    post_time = next_day + timedelta(seconds=random.randint(0, seconds_in_range))

    # If post_time falls into the range from 0:00 to x:00, shift it to start from x:00
    if post_time.hour < x:
        post_time = post_time + timedelta(hours=x)

    # Ensure the time returned is within a single day (24 hours)
    post_time = post_time.replace(day=now.day + 1)

    return post_time


def main():
    # Pick a random time of the day to post. between 10am and 2am
    # post_time = pick_random_time(10, 2)
    # pick 23:00
    post_time = datetime.now().replace(hour=23, minute=0, second=0, microsecond=0)
    print("Next post time: " + post_time.strftime("%m/%d/%Y, %H:%M:%S"))

    # Pick now to debug
    # post_time = datetime.now()

    # Sleep until the next post time
    time.sleep((post_time - datetime.now()).total_seconds())

    # Fetch posts from the channels
    social_medias = []
    for channel_id in fetch_from_channels:
        social_medias.append(fetch_posts(channel_id))

    # Pick a random social media
    media = random.choice(social_medias)
    # Pick a random post from the social media
    post = random.choice(media)

    # Send the post to the channels
    send_post(post)


if __name__ == "__main__":
    fetch_from_channels = [
        1158203872423186456,
        1158203872423186460,
        1158203872423186457,
    ]


    post_to_channels = [
        # 1128797444323426394,  #  debug
        1158681076504469514,  # boymoder #all
    ]

    while True:
        try:
            main()

        except:
            print(traceback.format_exc())
