import requests, json
from bs4 import BeautifulSoup


class ImageDownloadError(Exception):
    def __init__(self, message="Can't download image"):
        self.message = message
        super().__init__(self.message)


def upload(image_url):
    headers = {
        'authority': 'yandex.com',
        'accept': '*/*',
        'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8,de;q=0.7',
        'device-memory': '8',
        'dnt': '1',
        'downlink': '10',
        'dpr': '1',
        'ect': '4g',
        'referer': 'https://yandex.com/images/?lr=87&redircnt=1581287547.1',
        'rtt': '50',
        'sec-ch-ua': '"Chromium";v="116", "Not)A;Brand";v="24", "Google Chrome";v="116"',
        'sec-ch-ua-arch': '"x86"',
        'sec-ch-ua-bitness': '"64"',
        'sec-ch-ua-full-version': '"116.0.5845.98"',
        'sec-ch-ua-full-version-list': '"Chromium";v="116.0.5845.98", "Not)A;Brand";v="24.0.0.0", "Google Chrome";v="116.0.5845.98"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-model': '""',
        'sec-ch-ua-platform': '"Windows"',
        'sec-ch-ua-platform-version': '"10.0.0"',
        'sec-ch-ua-wow64': '?0',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
        'viewport-width': '2262',
        'x-requested-with': 'XMLHttpRequest',
        'x-retpath-y': 'https://yandex.com/images/search?rpt=imageview&url=https%3A%2F%2Fimages-ext-1.discordapp.net%2Fexternal%2FG8A9NhchpxNFoW6_DIoBRxrZqrNZcYRSq4_cW-FeIcA%2F%253Fsize%253D4096%2Fhttps%2Fcdn.discordapp.com%2Favatars%2F1142139490643750912%2F7b61ac6d511bf2bcb80a55266a361d14.png',
    }

    params = {
        'url': image_url,
        'cbird': '111',
        'images_avatars_size': 'preview',
        'images_avatars_namespace': 'images-cbir',
    }

    resp = requests.get('https://yandex.com/images-apphost/image-download', params=params, headers=headers)
    if "Can't download image" in resp.text:
        raise ImageDownloadError("Can't download image")

    elif resp.status_code != 200:
        raise Exception(f"Failed to upload image: {resp.status_code} {resp.text}")
    
    data = resp.json()
    return data


def search(url, ID):
    headers = {
        'authority': 'yandex.com',
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8,de;q=0.7',
        'device-memory': '8',
        'dnt': '1',
        'downlink': '10',
        'dpr': '1',
        'ect': '4g',
        'referer': 'https://yandex.com/images/search',
        'rtt': '50',
        'sec-ch-ua': '"Chromium";v="116", "Not)A;Brand";v="24", "Google Chrome";v="116"',
        'sec-ch-ua-arch': '"x86"',
        'sec-ch-ua-bitness': '"64"',
        'sec-ch-ua-full-version': '"116.0.5845.98"',
        'sec-ch-ua-full-version-list': '"Chromium";v="116.0.5845.98", "Not)A;Brand";v="24.0.0.0", "Google Chrome";v="116.0.5845.98"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-model': '""',
        'sec-ch-ua-platform': '"Windows"',
        'sec-ch-ua-platform-version': '"10.0.0"',
        'sec-ch-ua-wow64': '?0',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
        'viewport-width': '2262',
        'x-requested-with': 'XMLHttpRequest',
    }

    params = {
        'cbir_id': ID,
        'lr': '87',
        'rpt': 'imageview',
        'url': url,
        'tmpl_version': 'releases/frontend/images/v1.1134.0#7e0c951d00bea6d0312b191d4bb8093af2b5384f',
        'format': 'json',
        'request': '{"blocks":[{"block":"extra-content","params":{},"version":2},{"block":"i-global__params:ajax","params":{},"version":2},{"block":"cbir-intent__image-link","params":{},"version":2},{"block":"content_type_search-by-image","params":{},"version":2},{"block":"serp-controller","params":{},"version":2},{"block":"cookies_ajax","params":{},"version":2},{"block":"advanced-search-block","params":{},"version":2}],"metadata":{"bundles":{"lb":"I-X-{jCFsi<X120"},"assets":{"las":"justifier-height=1;justifier-setheight=1;fitimages-height=1;justifier-fitincuts=1;react-with-dom=1;220.0=1;196.0=1;ecb81c.0=1;1283d2.0=1;76.0=1;84.0=1;2b2077.0=1;116.0=1;356.0=1;332.0=1;108.0=1;132.0=1;340.0=1;100.0=1;316.0=1;4c3524.0=1;bc6e5b.0=1;6131b0.0=1;70d23b.0=1;09442a.0=1;50e57d.0=1;715ff4.0=1;46dc94.0=1"},"extraContent":{"names":["i-react-ajax-adapter"]}}}',
        'yu': '3162331311678394046',
        'uinfo': 'sw-3440-sh-1440-ww-2262-wh-714-pd-1-wp-16x10_2560x1600',
        'source-serpid': 'xTOxntBZ8e1JP2W3rfBBtw',
    }

    resp = requests.get('https://yandex.com/images/search', params=params, headers=headers)
    data = resp.json()['blocks']
    data = [x for x in data if x['name']['block'] == "content_type_search-by-image"]
    data = BeautifulSoup(data[0]['html'], 'html.parser')
    data = data.find_all('div', {'class': 'CbirSites-ItemTitle'})

    formatted_data = []
    for element in data:
        formatted_data.append({
            'title': element.text,
            'url': element.find('a')['href'],
            'thumbnail': element.parent.parent.find('a')['href']
        })

    return formatted_data


def debug():
    upload_data = upload(
        # 'https://m.media-amazon.com/images/M/MV5BZDAwMzA3MzktNGRhYy00ZDRmLWFjODQtMDI5MDRhZGQxNWVjXkEyXkFqcGdeQWRpZWdtb25n._V1_.jpg'
        'https://disboard.org/images/bot-command-image-bump.png'
    )
    search_result = search(
        url=upload_data['url'],
        ID=f"{upload_data['image_shard']}/{upload_data['image_id']}"
    )
    print(json.dumps(search_result, indent=4))


if __name__ == '__main__':
    debug()