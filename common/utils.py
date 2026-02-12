import string
import requests
from collections import Counter
#from sklearn.feature_extraction.text import TfidfVectorizer
#from sklearn.metrics.pairwise import cosine_similarity
from datetime import datetime


def mash_emojis(emoji1=None, emoji2=None):
    headers = {
        'accept': '*/*',
        'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8',
        'origin': 'https://www.google.com',
        'priority': 'u=1, i',
        'referer': 'https://www.google.com/',
        'sec-ch-ua': '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'cross-site',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
        'x-client-data': 'CJS2yQEIpbbJAQipncoBCOaEywEIk6HLAQiKo8sBCNqYzQEIhqDNAQj6184BCPzZzgEI/trOAQjV284BCIPdzgEI8d7OAQiL384BCJDfzgEI59/OARjw284BGO7czgE=',
    }

    params = {
        'key': 'AIzaSyACvEq5cnT7AcHpDdj64SE3TJZRhW-iHuo',
        'client_key': 'emoji_kitchen_funbox',
        'q': f'{emoji1}_{emoji2}',
        'collection': 'emoji_kitchen_v6',
        'contentfilter': 'high',
    }

    response = requests.get('https://tenor.googleapis.com/v2/featured', params=params, headers=headers)
    data = response.json()

    mashed_emoji = data['results'][0]['media_formats']["png_transparent"]['url']

    return mashed_emoji


def convert_discord_timestamp(timestamp):
    timestamp = str(timestamp)
    unix_timestamp = int(timestamp.strip("<t:>"))

    # Convert Unix timestamp to Python datetime object
    dt_object = datetime.utcfromtimestamp(unix_timestamp)

    return dt_object


def parse_duration_string(time_str):
    # Parses e.g 15s, 1m, 2h, 3d, 1w
    value = int(time_str[:-1])
    unit = time_str[-1]

    unit_to_seconds = {
        's': (1, 'seconds'),
        'm': (60, 'minutes'),
        'h': (3600, 'hours'),
        'd': (86400, 'days'),
        'w': (604800, 'weeks')
    }

    total_seconds, unit_name = unit_to_seconds[unit]
    return {
        "name": unit_name,
        "value": value * total_seconds,
    }




# def detect_duplicate_texts(text1, text2, threshold=0.9):
#     # Initialize a TF-IDF Vectorizer
#     vectorizer = TfidfVectorizer()

#     # Convert the texts into TF-IDF vectors
#     tfidf_matrix = vectorizer.fit_transform([text1, text2])

#     # Calculate the cosine similarity between the two texts
#     similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]

#     # Return True if similarity exceeds the threshold, else False
#     return similarity >= threshold


def detect_duplicate_phrases(message, n=5, threshold=10):
    # Remove punctuation from the message and normalize case
    translator = str.maketrans('', '', string.punctuation)
    message_cleaned = message.translate(translator).lower()

    # Split the message into words
    words = message_cleaned.split()

    # Generate n-grams (sequences of n words)
    ngrams = [' '.join(words[i:i + n]) for i in range(len(words) - n + 1)]

    # Count the frequency of each n-gram (phrase)
    ngram_counts = Counter(ngrams)

    # Find n-grams that appear more than the threshold
    duplicates = {ngram: count for ngram, count in ngram_counts.items() if count > threshold}

    return bool(duplicates)


def fetch_proxies():
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8',
        'origin': 'https://proxyscrape.com',
        'priority': 'u=1, i',
        'referer': 'https://proxyscrape.com/',
        'sec-ch-ua': '"Not)A;Brand";v="99", "Google Chrome";v="127", "Chromium";v="127"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    }
    
    params = {
        'request': 'getproxies',
        'protocol': 'http',
        'skip': '0',
        'proxy_format': 'protocolipport',
        'format': 'json',
        'limit': '15',
        'timeout': '500',
    }
    
    response = requests.get('https://api.proxyscrape.com/v3/free-proxy-list/get', params=params, headers=headers)
    data = response.json()['proxies']
    
    data_formatted = [
        {
            'http': x['proxy'],
        }
        for x in data]
    return data_formatted


def debug():
    # save to a file
    # proxies = fetch_proxies()
    # proxies_formatted_txt = '\n'.join([f"{x['http'].replace('http://', '')}" for x in proxies])
    # print(proxies_formatted_txt)

    # laugh and cry
    print(mash_emojis('😂', '😭'))


if __name__ == '__main__':
    debug()