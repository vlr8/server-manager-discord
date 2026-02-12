import time
import common.consts as env
import requests
import discord.helpers as helpers
import os
from dotenv import load_dotenv
load_dotenv()
token = os.environ["SELF_TOKEN"]

def bump():
	headers = {
		'authority': 'discord.com',
		'accept': '*/*',
		'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8',
		'authorization': token,
		'content-type': 'multipart/form-data; boundary=----WebKitFormBoundaryfrKIF73VAnYhQySx',
		'dnt': '1',
		'origin': 'https://discord.com',
		'referer': 'https://discord.com/channels/1086159781284298822/1122292278208245864',
		'sec-ch-ua': '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
		'sec-ch-ua-mobile': '?0',
		'sec-ch-ua-platform': '"macOS"',
		'sec-fetch-dest': 'empty',
		'sec-fetch-mode': 'cors',
		'sec-fetch-site': 'same-origin',
		'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
		'x-debug-options': 'bugReporterEnabled',
		'x-discord-locale': 'en-US',
		'x-discord-timezone': 'Europe/Berlin',
		'x-super-properties': 'eyJvcyI6Ik1hYyBPUyBYIiwiYnJvd3NlciI6IkNocm9tZSIsImRldmljZSI6IiIsInN5c3RlbV9sb2NhbGUiOiJlbi1HQiIsImJyb3dzZXJfdXNlcl9hZ2VudCI6Ik1vemlsbGEvNS4wIChNYWNpbnRvc2g7IEludGVsIE1hYyBPUyBYIDEwXzE1XzcpIEFwcGxlV2ViS2l0LzUzNy4zNiAoS0hUTUwsIGxpa2UgR2Vja28pIENocm9tZS8xMTQuMC4wLjAgU2FmYXJpLzUzNy4zNiIsImJyb3dzZXJfdmVyc2lvbiI6IjExNC4wLjAuMCIsIm9zX3ZlcnNpb24iOiIxMC4xNS43IiwicmVmZXJyZXIiOiIiLCJyZWZlcnJpbmdfZG9tYWluIjoiIiwicmVmZXJyZXJfY3VycmVudCI6Imh0dHBzOi8vZGlzY29yZC5jb20vbG9naW4iLCJyZWZlcnJpbmdfZG9tYWluX2N1cnJlbnQiOiJkaXNjb3JkLmNvbSIsInJlbGVhc2VfY2hhbm5lbCI6InN0YWJsZSIsImNsaWVudF9idWlsZF9udW1iZXIiOjIyNjc1OCwiY2xpZW50X2V2ZW50X3NvdXJjZSI6bnVsbH0=',
	}
	
	data = '------WebKitFormBoundaryfrKIF73VAnYhQySx\r\nContent-Disposition: form-data; name="payload_json"\r\n\r\n{"type":2,"application_id":"302050872383242240","guild_id":"1158203871554961579","channel_id":"1158203871982792788","session_id":"21af87a961427c1aa8fd578f03d12675","data":{"version":"1051151064008769576","id":"947088344167366698","name":"bump","type":1,"options":[],"application_command":{"id":"947088344167366698","application_id":"302050872383242240","version":"1051151064008769576","default_member_permissions":null,"type":1,"nsfw":false,"name":"bump","description":"Pushes your server to the top of all your server\'s tags and the front page","description_localized":"Bump this server.","dm_permission":true,"contexts":null,"integration_types":[0]},"attachments":[]},"nonce":"1156921360958619648"}\r\n------WebKitFormBoundaryfrKIF73VAnYhQySx--\r\n'
	resp = requests.post('https://discord.com/api/v9/interactions', headers=headers, data=data)
	if resp.status_code in (401, 400):
		print(resp.text)
	
	return resp.status_code


def main():
	# Bump every 2 hours
	while True:
		status_code = bump()
		print('Bumped', status_code)
		# SLeep for random between 2.11 and 2.43 hours
		random_time = helpers.random_delay(2.13, 2.41, unit='hours')
		print('Sleeping for', random_time / 60 / 60)
		time.sleep(random_time)


if __name__ == '__main__':
	main()
