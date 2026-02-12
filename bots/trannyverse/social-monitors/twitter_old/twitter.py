from datetime import datetime
import traceback
import os
import requests, json, string, random
import common.proxies as proxies
import common.logger as logger
from selenium import webdriver
import time

# use_proxies = True
use_proxies = False
proxy_list = proxies.read_proxy_file("common/proxies.txt")
if len(proxy_list) == 0:
	use_proxies = False
	print("No proxies found, using local IP address")


def get_csrf():
	s = list("bc1qugrtknpjz52vc4m559q7zumkc4268kp7skrsee")
	random.shuffle(s)
	result = random.choice(string.ascii_lowercase) + random.choice(string.ascii_lowercase) + ''.join(s)
	
	return result


# Opens a headful browser to login to twitter and returns the cookies
def login_headful():
	# Set the path to your WebDriver
	driver = webdriver.Chrome()
	
	# Set the window size
	driver.set_window_size(900, 900)
	
	# Navigate to the Twitter login page
	driver.get("https://twitter.com/login")
	
	# Check if the address matches https://twitter.com/home
	while driver.current_url != "https://twitter.com/home":
		# Sleep for 1 second
		time.sleep(1)
	
	# Get cookies after login
	cookies = driver.get_cookies()
	
	# Close the browser
	driver.quit()
	
	# Return cookies
	return cookies


def disable_NSFW(session=None):
	global monitor_account_index
	try:
		session = monitor_accounts[monitor_account_index] if session is None else session
	
	except IndexError:
		monitor_account_index = 0
		session = monitor_accounts[monitor_account_index] if session is None else session
	
	headers = {
		'authority': 'twitter.com',
		'accept': '*/*',
		'accept-language': 'en-GB,en;q=0.9',
		'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
		'content-type': 'application/json',
		'dnt': '1',
		'referer': 'https://twitter.com/',
		'sec-ch-ua': '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
		'sec-ch-ua-mobile': '?0',
		'sec-ch-ua-platform': '"Windows"',
		'sec-fetch-dest': 'empty',
		'sec-fetch-mode': 'cors',
		'sec-fetch-site': 'same-origin',
		'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
		'x-csrf-token': session.cookies.get("ct0"),
		'x-twitter-active-user': 'yes',
		'x-twitter-client-language': 'en-GB',
	}
	
	json_data = {
		'optInFiltering': True,
		'optInBlocking': True,
	}
	
	session.post(
		'https://twitter.com/i/api/1.1/strato/column/User/1501575837090553865/search/searchSafety',
		headers=headers,
		json=json_data,
	)
	
	return session


def get_tweets(query, session=None, amount=20):
	global monitor_account_index
	try:
		session = monitor_accounts[monitor_account_index] if session is None else session
	
	except IndexError:
		monitor_account_index = 0
		session = monitor_accounts[monitor_account_index] if session is None else session
	
	session = disable_NSFW(session)
	
	headers = {
		'authority': 'twitter.com',
		'accept': '*/*',
		'accept-language': 'en-GB,en;q=0.9',
		'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
		'content-type': 'application/json',
		'dnt': '1',
		'referer': 'https://twitter.com/',
		'sec-ch-ua': '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
		'sec-ch-ua-mobile': '?0',
		'sec-ch-ua-platform': '"Windows"',
		'sec-fetch-dest': 'empty',
		'sec-fetch-mode': 'cors',
		'sec-fetch-site': 'same-origin',
		'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
		'x-csrf-token': session.cookies.get("ct0"),
		'x-twitter-active-user': 'yes',
		'x-twitter-client-language': 'en-GB',
	}
	
	params = {
		'variables': json.dumps({
			"rawQuery": query,
			"count": amount,
			"querySource": "typed_query",
			"product": "Top"
		}),
		'features': '{"rweb_lists_timeline_redesign_enabled":true,"responsive_web_graphql_exclude_directive_enabled":true,"verified_phone_label_enabled":false,"creator_subscriptions_tweet_preview_api_enabled":true,"responsive_web_graphql_timeline_navigation_enabled":true,"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,"tweetypie_unmention_optimization_enabled":true,"responsive_web_edit_tweet_api_enabled":true,"graphql_is_translatable_rweb_tweet_is_translatable_enabled":true,"view_counts_everywhere_api_enabled":true,"longform_notetweets_consumption_enabled":true,"responsive_web_twitter_article_tweet_consumption_enabled":false,"tweet_awards_web_tipping_enabled":false,"freedom_of_speech_not_reach_fetch_enabled":true,"standardized_nudges_misinfo":true,"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled":true,"longform_notetweets_rich_text_read_enabled":true,"longform_notetweets_inline_media_enabled":true,"responsive_web_media_download_video_enabled":false,"responsive_web_enhance_cards_enabled":false}',
		'fieldToggles': '{"withAuxiliaryUserLabels":false,"withArticleRichContentState":false}',
	}
	
	resp = session.get('https://twitter.com/i/api/graphql/KUnA_SzQ4DMxcwWuYZh9qg/SearchTimeline', headers=headers,
	                   params=params)
	try:
		data = resp.json()
	except requests.exceptions.JSONDecodeError:
		if 'Rate limit exceeded' in resp.text:
			print('Rate limit exceeded, rotating monitor account...')
			
			rotate_monitor_account()
			return []
	
	data = data['data']['search_by_raw_query']['search_timeline']['timeline']['instructions'][0]['entries']
	
	tweets = []
	for tweet in data:
		try:
			tweet_id = tweet['content']['itemContent']['tweet_results']['result']['legacy']['id_str']
			tweet_text = tweet['content']['itemContent']['tweet_results']['result']['legacy']['full_text']
			author_name = \
			tweet['content']['itemContent']['tweet_results']['result']['core']['user_results']['result']['legacy'][
				'name']
			author_handle = \
			tweet['content']['itemContent']['tweet_results']['result']['core']['user_results']['result']['legacy'][
				'screen_name']
			
			tweets.append({
				"id": tweet_id,
				"text": tweet_text,
				"author_name": author_name,
				"author_handle": author_handle,
			})
		
		except KeyError:
			if tweet['content']['entryType'] == 'TimelineTimelineCursor' or tweet['content'][
				'entryType'] == 'TimelineTimelineModule':
				pass
			
			elif 'Is this Tweet relevant to your search?' in str(tweet):
				pass
			
			else:
				print(traceback.format_exc())
				print(tweet)
	
	return tweets


class UserUnavailableError(Exception):
	def __init__(self, message, user_id):
		full_message = f"{message} User ID: {user_id}"
		super().__init__(full_message)
		self.user_id = user_id


def rotate_monitor_account():
	# we need a last_rotate time to prevent us from rotating too often. it should only rotate once every 1 minute
	global last_rotate
	if last_rotate is None:
		last_rotate = datetime.now()
	else:
		if (datetime.now() - last_rotate).total_seconds() < 60:
			print("Not rotating monitor account because it hasn't been 60 seconds yet")
			return
		
		print("Rotating monitor account")
		last_rotate = datetime.now()
	
	global monitor_account_index
	monitor_account_index += 1
	if monitor_account_index >= len(monitor_accounts):
		monitor_account_index = 0


def get_tweets_by_user(user_id, count=5, retweets=False, session=None):
	global monitor_account_index
	try:
		session = monitor_accounts[monitor_account_index] if session is None else session
	
	except IndexError:
		monitor_account_index = 0
		session = monitor_accounts[monitor_account_index] if session is None else session
	
	headers = {
		'authority': 'twitter.com',
		'accept': '*/*',
		'accept-language': 'en-GB,en;q=0.9',
		'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
		'content-type': 'application/json',
		'dnt': '1',
		'referer': 'https://twitter.com/',
		'sec-ch-ua': '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
		'sec-ch-ua-mobile': '?0',
		'sec-ch-ua-platform': '"Windows"',
		'sec-fetch-dest': 'empty',
		'sec-fetch-mode': 'cors',
		'sec-fetch-site': 'same-origin',
		'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
		'x-csrf-token': session.cookies.get("ct0"),
		'x-twitter-active-user': 'yes',
		'x-twitter-client-language': 'en-GB',
	}
	
	params = {
		'variables': '{"userId":"' + str(user_id) + '","count":' + str(
			count) + ',"includePromotedContent":true,"withQuickPromoteEligibilityTweetFields":true,"withVoice":true,"withV2Timeline":true}',
		'features': '{"rweb_lists_timeline_redesign_enabled":true,"responsive_web_graphql_exclude_directive_enabled":true,"verified_phone_label_enabled":false,"creator_subscriptions_tweet_preview_api_enabled":true,"responsive_web_graphql_timeline_navigation_enabled":true,"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,"tweetypie_unmention_optimization_enabled":true,"responsive_web_edit_tweet_api_enabled":true,"graphql_is_translatable_rweb_tweet_is_translatable_enabled":true,"view_counts_everywhere_api_enabled":true,"longform_notetweets_consumption_enabled":true,"tweet_awards_web_tipping_enabled":false,"freedom_of_speech_not_reach_fetch_enabled":true,"standardized_nudges_misinfo":true,"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled":false,"longform_notetweets_rich_text_read_enabled":true,"longform_notetweets_inline_media_enabled":false,"responsive_web_enhance_cards_enabled":false}',
	}
	
	resp = session.get(
		'https://twitter.com/i/api/graphql/NPgNFbBEhFTul68weP-tYg/UserTweets',
		params=params,
		headers=headers,
		proxies=random.choice(proxy_list) if use_proxies else None,
	)
	try:
		data = resp.json()
	except requests.exceptions.JSONDecodeError:
		if 'Rate limit exceeded' in resp.text:
			print('Rate limit exceeded, rotating monitor account...')
			
			rotate_monitor_account()
			return []
	
	try:
		# Try all indexes until returns data length above 0
		# Get the max index
		max_index = len(resp.json()['data']['user']['result']['timeline_v2']['timeline']['instructions'])
		
		for i in range(1, max_index):
			data = resp.json()['data']['user']['result']['timeline_v2']['timeline']['instructions'][i].get('entries',
			                                                                                               [])
			
			if len(data) > 0:
				break
	
	except (KeyError, IndexError):
		print(traceback.format_exc())
		error = resp.json()['data']['user']['result']['__typename']
		
		if error == 'UserUnavailable':
			raise UserUnavailableError('User is does not exist:', user_id)
		
		else:
			# No tweets found.
			return []
	
	formatted_data = []
	for tweet in data:
		try:
			text = tweet['content']['itemContent']['tweet_results']['result']['legacy']['full_text']
			urls = tweet['content']['itemContent']['tweet_results']['result']['legacy']['entities']['urls']
			media_urls = tweet['content']['itemContent']['tweet_results']['result']['legacy']['entities'].get('media',
			                                                                                                  [])
			
			# Remove all media urls from the text
			for url in media_urls:
				text = text.replace(url['url'], '')
			
			# print(text)
			if not retweets and 'RT @' in text:
				continue
			
			formatted_data.append({
				'id': tweet['content']['itemContent']['tweet_results']['result']['legacy']['id_str'],
				'text': text,
				'created_at': tweet['content']['itemContent']['tweet_results']['result']['legacy']['created_at'],
				'urls': urls,
			})
		
		except KeyError:
			# This is a "TimelineTimelineCursor" entry, which we can ignore.
			if tweet['content']['entryType'] == 'TimelineTimelineCursor' or tweet['content'][
				'entryType'] == 'TimelineTimelineModule':
				pass
			
			else:
				print(traceback.format_exc())
				print(tweet['content'])
				# print(tweet['content']['itemContent']['tweet_results']['result'])
	
	return formatted_data


def get_user_id(username, session=None):
	global monitor_account_index
	session = monitor_accounts[monitor_account_index] if session is None else session
	# cookies = {
	#     'guest_id': guest_creds['guest_id'],
	#     'gt': guest_creds['guest_token'],
	#     'ct0': 'aa947fa5f103a921c88ccb66a8160ec5',
	# }
	
	headers = {
		'authority': 'twitter.com',
		'accept': '*/*',
		'accept-language': 'en-GB,en;q=0.9',
		'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
		'content-type': 'application/json',
		'dnt': '1',
		'referer': 'https://twitter.com/',
		'sec-ch-ua': '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
		'sec-ch-ua-mobile': '?0',
		'sec-ch-ua-platform': '"Windows"',
		'sec-fetch-dest': 'empty',
		'sec-fetch-mode': 'cors',
		'sec-fetch-site': 'same-origin',
		'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
		'x-csrf-token': session.cookies.get("ct0"),
		# 'x-guest-token': guest_creds['guest_token'],
		'x-twitter-active-user': 'yes',
		'x-twitter-client-language': 'en-GB',
	}
	
	variables = {
		"screen_name": username
	}
	
	params = {
		'variables': json.dumps(variables),
	}
	
	resp = session.get(
		'https://twitter.com/i/api/graphql/9zwVLJ48lmVUk8u_Gh9DmA/ProfileSpotlightsQuery',
		params=params,
		# cookies=cookies,
		headers=headers,
		proxies=random.choice(proxy_list) if use_proxies else None,
	)
	try:
		data = resp.json()
	except requests.exceptions.JSONDecodeError:
		if 'Rate limit exceeded' in resp.text:
			print('Rate limit exceeded, rotating monitor account...')
			rotate_monitor_account()
			raise Exception('Rate limit exceeded')
		
		else:
			print(traceback.format_exc())
			print(resp, resp.text)
	
	try:
		user_id = data['data']['user_result_by_screen_name']['result']['rest_id']
		return user_id
	
	except (KeyError, IndexError):
		print(f"User not found: <{username}> Please remove from settings.")
		os._exit(0)


def get_user_session():
	cookies = login_headful()
	login_session = requests.session()
	
	# Update the session's cookies
	for cookie in cookies:
		login_session.cookies.set(cookie['name'], cookie['value'])
	
	return login_session


def debug():
	# tweets = get_tweets(
	# 	query='(tranny OR trannystranniespoonerboymode OR boymoder OR boymoding OR girlmode OR girlmoder OR girlmoding OR gigahon OR rapehon OR youngshit OR passoidsnoymoder OR soapcel OR trans girls) lang:en since:2023-07-11 -filter:replies min_faves:1',
	# 	amount=50
	# )
	tweets = get_tweets_by_user(1466811110439493646, retweets=True, count=50)
	print(json.dumps(tweets, indent=4))


# of tje twitter_session.jkspn file exists
if not os.path.exists("twitter/twitter_sessions.json"):
	num_accounts = input("How many Monitor accounts do you want to login with?")
	num_accounts = int(num_accounts)
	for i in range(num_accounts):
		# Login to Twitter
		monitor_session = get_user_session()
		
		# Check if the file exists
		if not os.path.exists("twitter/twitter_sessions.json"):
			with open("twitter/twitter_sessions.json", "w") as f:
				json.dump([], f, indent=4)
			
			accounts_file = []
		
		else:
			with open("twitter/twitter_sessions.json", "r") as f:
				accounts_file = json.load(f)
		
		# Save the cookies to the user_sessions file
		accounts_file.append(dict(monitor_session.cookies))
		
		with open("twitter/twitter_sessions.json", "w") as f:
			json.dump(accounts_file, f, indent=4)

# Load the user_sessions file and if it doesn't exist, create it
try:
	with open("twitter/twitter_sessions.json", "r") as f:
		accounts_file = json.load(f)

except FileNotFoundError:
	with open("twitter/twitter_sessions.json", "w") as f:
		json.dump([], f, indent=4)
	
	accounts_file = []

# Create a session for each monitor account
monitor_accounts = []
for account in accounts_file:
	user_session = requests.session()
	
	# Update the session's cookies
	for cookie in account:
		user_session.cookies.set(cookie, account[cookie])
	
	monitor_accounts.append(user_session)

monitor_account_index = 0
last_rotate = None

if __name__ == '__main__':
	debug()
