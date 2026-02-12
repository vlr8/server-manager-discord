import requests


def search(word, index=0):
	resp = requests.get(f'https://api.urbandictionary.com/v0/define?term={word}')
	data = resp.json()
	
	if len(data['list']) == 0:
		return None
	
	try:
		return data['list'][index]
	
	except IndexError:
		return None
	