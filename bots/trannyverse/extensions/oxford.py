import json
import time
import requests
from bs4 import BeautifulSoup


def search(query):
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8,de;q=0.7',
        'Cache-Control': 'max-age=0',
        'Connection': 'keep-alive',
        'If-None-Match': '"0846a6bc5929cc0374354776dac98dbc4-gzip"',
        'Referer': 'https://www.oxfordlearnersdictionaries.com/spellcheck/english/?q=elektra+complex',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        'dnt': '1',
        'sec-ch-ua': '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
    }
    query = query.replace(' ', '-')
    url = f'https://www.oxfordlearnersdictionaries.com/definition/english/{query}'
    
    resp = requests.get(
        # Dont encode the query it will ruin the url
        url,
        headers=headers,
    )
    data = BeautifulSoup(resp.text, 'html.parser')

    if 'Word not found in the dictionary' in data.text:
        return None
    
    # Get the definition
    container = data.find('div', {'class': 'entry'})
    
    try:
        headword = container.find('h1', {'class': 'headword'}).text
    except AttributeError:
        headword = None
    
    try:
        pos = container.find('span', {'class': 'pos'}).text
    except AttributeError:
        pos = None
    
    try:
        grammar = container.find('span', {'class': 'grammar'}).text
    except AttributeError:
        grammar = None
    
    try:
        subj = container.find('span', {'class': 'subj'}).text
    except AttributeError:
        subj = None
    
    try:
        phonetic = container.find('span', {'class': 'phon'}).text
    except AttributeError:
        phonetic = None
    
    try:
        definition = container.find('span', {'class': 'def'}).text
    except AttributeError:
        definition = None
    
    try:
        reference = container.find('span', {'class': 'xr-g'}).text
    except AttributeError:
        reference = None
    
    return {
        'headword': headword,
        'url': url,
        'pos': pos,
        'grammar': grammar,
        'subj': subj,
        'phonetic': phonetic,
        'definition': definition,
        'reference': reference,
    }
    

def debug():
    x = search('house')
    print(json.dumps(x, indent=4))


if __name__ == '__main__':
    debug()
