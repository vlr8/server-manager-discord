import os
import time
import requests
import common.consts as env
from datetime import datetime, timedelta
import datetime
import random
from dotenv import load_dotenv
load_dotenv()
SELF_TOKEN = os.environ['SELF_TOKEN']
BOT_TOKEN = os.environ['TRANNYVERSE_BOT_TOKEN']

headers = {
    'authorization': SELF_TOKEN,
}


def get_audit_log(guild_id, action_type, limit=100, before=None):
    resp = requests.get(f'https://discord.com/api/v9/guilds/{guild_id}/audit-logs?limit={limit}&action_type={action_type}', headers=headers)
    data = resp.json()

    return data


def parse_within_param(within_param):
    current_time = datetime.datetime.now()
    if within_param == "last hour":
        return current_time - timedelta(hours=1)
    elif within_param == "last 6 hours":
        return current_time - timedelta(hours=6)
    elif within_param == "last day":
        return current_time - timedelta(days=1)
    elif within_param == "last week":
        return current_time - timedelta(weeks=1)
    else:
        return None


def fetch_messages(channel_id, limit=100, fetch_all=False, within=None, usebot=False, before=None):
    if usebot:
        headers['authorization'] = f"Bot {BOT_TOKEN}"

    if within:
        within_time = parse_within_param(within)
        # Offset-aware the time
        within_time = within_time.replace(tzinfo=datetime.timezone.utc)

    messages = []
    params = {}

    while True:
        resp = requests.get(f'https://discord.com/api/v9/channels/{channel_id}/messages?limit={limit}', headers=headers, params=params)
        if resp.status_code == 429:
            retry_after = resp.json()['retry_after']
            if retry_after > 10:
                print(f'Rate limited, waiting {retry_after} seconds')
            time.sleep(retry_after)
            fetch_messages(channel_id, limit, fetch_all, within, usebot, before)

        elif resp.status_code != 200:
            print(f'Failed to fetch messages: {resp.status_code} {resp.text}')
            fetch_messages(channel_id, limit, fetch_all, within, usebot, before)

        data = resp.json()
        if not fetch_all or len(data) == 0:
            break

        messages += data
        # If last message is identical to the first message, we've reached the end
        if len(messages) > 0 and messages[-1]['id'] == data[0]['id']:
            break

        # If within is specified, check if the last message is within the time frame
        if within:
            last_message_time = parse_timestamp(messages[-1]['timestamp'])
            if last_message_time < within_time:
                break

        params['before'] = messages[-1]['id']
        before = messages[-1]['id']

    return messages


def parse_timestamp(timestamp):
    try:
        return datetime.datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%f%z')
    except ValueError:
        return datetime.datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S%z')


def fetch_onboarding_roles(guild_id, prompt_index='all'):
    resp = requests.get(f'https://discord.com/api/v9/guilds/{guild_id}/onboarding', headers=headers)
    data = resp.json()
    prompts = data["prompts"]

    if prompt_index != 'all':
        prompts = [prompts[prompt_index]]

    roles = []
    for prompt in prompts:
        for option in prompt['options']:
            roles += option['role_ids']

    return roles

def fetch_all_roles(guild_id):
    resp = requests.get(f'https://discord.com/api/v9/guilds/{guild_id}/roles', headers=headers)
    data = resp.json()
    
    roles = []
    for role in data:
        roles += role['id']

    return roles

def decimal_to_hex(decimal_color):
    hex_color = hex(decimal_color)[2:]  # This converts to hexadecimal.
    formatted_hex_color = '#' + hex_color.zfill(6)  # This formats it as a color string.
    return formatted_hex_color


# Checks if any from list1 is in list2 (if either is a string, it will check if the string is in the other list)
def any_in_list(list1, list2):
    for item in list1:
        if item in list2:
            return True
    return False


def calculate_disabled_until(duration_seconds):
    now = datetime.datetime.now()
    disabled_until = now + datetime.timedelta(seconds=duration_seconds)
    return disabled_until


def random_delay(start, end, unit='seconds'):
    if unit == 'seconds':
        delay = random.uniform(start, end)
    elif unit == 'minutes':
        delay = random.uniform(start * 60, end * 60)
    elif unit == 'hours':
        delay = random.uniform(start * 60 * 60, end * 60 * 60)
    else:
        raise ValueError("Invalid unit")

    return delay


def zipdir(path, ziph):
    for root, _, files in os.walk(path):
        for file in files:
            ziph.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), os.path.join(path, '..')))


def debug():
    import json
    # msgs = fetch_messages(1162817069566394518, fetch_all=True)
    # print(msgs[-1]['attachments'][0]['url'])
    # print(len(msgs))
    # Get audit logs for timeouts
    resp = get_audit_log(guild_id=env.guild_id, action_type=22, limit=100)
    print(json.dumps(resp, indent=4))


if __name__ == '__main__':
    debug()
