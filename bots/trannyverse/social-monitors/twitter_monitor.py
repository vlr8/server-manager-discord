import re
import time
import traceback
import requests
from twitter_old import twitter
import json


def send_webhook(text=""):
    data = {
        "content": text,
        "username": "Trannyverse",
        "avatar_url": "https://i.imgur.com/qnuE4sH.png"
    }

    for url in webhook_urls:
        resp = requests.post(url, json=data)
        if resp.status_code != 204:
            print(f"Error sending webhook: {resp.status_code}")


def monitor():
    global search_keywords

    tweets = []
    for query in queries:
        print('Query:', query)
        tweets += twitter.get_tweets(
            query=query,
            amount=50
        )
        time.sleep(1 * 60)

    for tweet in tweets:
        if tweet['id'] in pinged:
            continue

        # If none of the keywords are in the tweet text or author's name or authors handle, skip
        if not any([keyword.lower() in tweet['text'].lower() for keyword in content_keywords]) and \
                not any([keyword.lower() in tweet['author_name'].lower() for keyword in content_keywords]) and \
                not any([keyword.lower() in tweet['author_handle'].lower() for keyword in content_keywords]):
            print('Filtering tweet:', tweet['text'])
            continue

        print('New Tweet:', tweet['text'])
        send_webhook(f"https://fxtwitter.com/_/status/{tweet['id']}")
        pinged.append(tweet['id'])

    time.sleep(delay)
    # Save pinged to file
    with open('pinged.json', 'w') as f:
        json.dump(pinged, f, indent=4)


if __name__ == '__main__':
    search_keywords = [
        'tranny',
        'trannys',
        'trannies',
        'pooner',
        'boymode',
        'boymoder',
        'boymoding',
        'girlmode',
        'girlmoder',
        'girlmoding',
        'gigahon',
        'rapehon',
        'youngshit',
        'passoid',
        'snoymoder',
        'soapcel',
        'trans girls',
        'trans boys',
        'trans women',
        'trans men',
        'trans guys',
        'estrogenized',
        'transcel'
        'tranners',
        'twinkhon',
        'twinkmode',
        'malebrained',
        'fembrained',
        '4tran',
        'brainworm',
        'transbian',
        'agp'
    ]

    two_days_ago = time.strftime("%Y-%m-%d", time.localtime(time.time() - 172800))
    queries = [
        f"({' OR '.join(search_keywords)}) lang:en since:{two_days_ago} -filter:replies min_faves:1",
        f'(from:lgbt_takes) since:{two_days_ago} -filter:replies',
        f'(from:ASTEROIDNlGHTS) since:{two_days_ago} -filter:replies',
        f'(from:goldenhourtrain) since:{two_days_ago} -filter:replies',
        f'(from:oncloud_e) since:{two_days_ago} -filter:replies',
        f'(from:SlayzKiana) since:{two_days_ago} -filter:replies',
        f'(from:junefembug) since:{two_days_ago} -filter:replies',
        f'(from:fairyruuti) since:{two_days_ago} -filter:replies',
        f'(from:Eefah_Bee) since:{two_days_ago} -filter:replies',
        f'(from:Aoife_Bee_) since:{two_days_ago} -filter:replies',
        f'(from:halomancer1) since:{two_days_ago} -filter:replies',
        f'(from:fayemikah) since:{two_days_ago} -filter:replies',
        f'(from:wifekisser303) since:{two_days_ago} -filter:replies',
        f'(from:BABYWOLFx420) since:{two_days_ago} -filter:replies',
        f'(from:loserbent) since:{two_days_ago} -filter:replies',
        f'(from:boymoderology) since:{two_days_ago} -filter:replies',
        f'(from:girlcel_) since:{two_days_ago} -filter:replies',
        f'(from:debrainwormer) since:{two_days_ago} -filter:replies',
        f'(from:HRTFRG) since:{two_days_ago} -filter:replies',
        f'(from:KNOTAFAGGOT) since:{two_days_ago} -filter:replies',
        f'(from:boygrrI) since:{two_days_ago} -filter:replies',
        f'(from:twinkmoder) since:{two_days_ago} -filter:replies',
        f'(from:0OO0Q0O) since:{two_days_ago} -filter:replies',
        f'(from:hitsujigoods) since:{two_days_ago} -filter:replies',
        f'(from:rzrbladewyl) since:{two_days_ago} -filter:replies',
        f'(from:angelrightsnow) since:{two_days_ago} -filter:replies',
        f'(from:halomancer1) since:{two_days_ago} -filter:replies',
        f'(from:brainwormsssss) since:{two_days_ago} -filter:replies',
    ]

    # Filter out all usernames in (from:username) and add them to the search keywords
    username_keywords = re.findall(r'\(from:(.*?)\)', ' '.join(queries))

    content_keywords = username_keywords + search_keywords + [
        'trans',
        'women',
        'woman',
        'man',
        'men',
        'boy',
        'girl'
        'gender',
        'estrogen',
        'testosterone'
        'hon',
        'hrt',
    ]

    # Load pinged from file if it exists
    try:
        with open('pinged.json', 'r') as f:
            pinged = json.load(f)
    except:
        pinged = []

    delay = 10 * 60
    webhook_urls = [
        # 'https://discord.com/api/webhooks/1128797456444952646/pccI_UV-i1hUz7mFHasAUYBkC4ELFsyz0aMspzOcD3JrEeIgSJVb8pxF_U_4NoAlOEje'  # test
        'https://discord.com/api/webhooks/1164816226732740669/aPTM9aCMvYpek244UphmRg8EE8RSwChuU_7aDcDzg9RNdctri9hkEsA1IrCwHkmcruxx'
    ]

    while True:
        try:
            monitor()

        except:
            print(traceback.format_exc())
            time.sleep(delay)
