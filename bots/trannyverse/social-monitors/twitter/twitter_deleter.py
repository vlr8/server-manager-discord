import twitter


while True:
	tweets = twitter.get_tweets_by_user(1466811110439493646, retweets=True, count=50)
	
	ids = [x['id'] for x in tweets]
	
	for ID in ids:
		import requests
		
		cookies = {
			'kdt': '3Bc4fFhhqzNBI6TuoGMmOpG4p7S4vRnlkNjW3vxR',
			'lang': 'en',
			'd_prefs': 'MjoxLGNvbnNlbnRfdmVyc2lvbjoyLHRleHRfdmVyc2lvbjoxMDAw',
			'des_opt_in': 'Y',
			'ads_prefs': '"HBERAAA="',
			'auth_multi': '"1480711808218509314:9c5cf583355875c5b1df02dc8cebcd660b5d6356|1501575837090553865:29887e6dd7abab8639d3db2330e31a7a119ec535|1071054060537700353:b57644e236e0edf7540fe687f8cccea6761efbb8|1145040584790482944:bd7ba347f2f259a870e5c3f1b3e164a130901f4f"',
			'auth_token': '55641e19d7893812f7da210cdc36ab865c1a5c76',
			'guest_id': 'v1%3A168930265402644138',
			'ct0': 'd3e59112287d80fbb6b1f4cc60b793060d3ef3276d421c6d8936ebf5c827913917881159b4f0ddf566df4e33843d77fd030b442a77533a15c04f4da8f98303e8619b994c5d5072d47115a727aa6a9ed0',
			'twid': 'u%3D1466811110439493646',
			'_twitter_sess': 'BAh7CSIKZmxhc2hJQzonQWN0aW9uQ29udHJvbGxlcjo6Rmxhc2g6OkZsYXNo%250ASGFzaHsABjoKQHVzZWR7ADoPY3JlYXRlZF9hdGwrCOJoSVKJAToMY3NyZl9p%250AZCIlOTg1ZTRjMzk5ZmQxNDQwOWQyOTI4ZDlkMWJlZjk1MjY6B2lkIiVjMTVk%250ANTY3ZWZlNDk2MzBjZTFiZmUwZWM0Y2Y3MmY0OA%253D%253D--cd7422400c5a859f558516993cd735d14d382210',
			'eu_cn': '1',
		}
		
		headers = {
			'authority': 'twitter.com',
			'accept': '*/*',
			'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8,de;q=0.7',
			'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
			'content-type': 'application/json',
			# 'cookie': 'kdt=3Bc4fFhhqzNBI6TuoGMmOpG4p7S4vRnlkNjW3vxR; lang=en; d_prefs=MjoxLGNvbnNlbnRfdmVyc2lvbjoyLHRleHRfdmVyc2lvbjoxMDAw; des_opt_in=Y; ads_prefs="HBERAAA="; auth_multi="1480711808218509314:9c5cf583355875c5b1df02dc8cebcd660b5d6356|1501575837090553865:29887e6dd7abab8639d3db2330e31a7a119ec535|1071054060537700353:b57644e236e0edf7540fe687f8cccea6761efbb8|1145040584790482944:bd7ba347f2f259a870e5c3f1b3e164a130901f4f"; auth_token=55641e19d7893812f7da210cdc36ab865c1a5c76; guest_id=v1%3A168930265402644138; ct0=d3e59112287d80fbb6b1f4cc60b793060d3ef3276d421c6d8936ebf5c827913917881159b4f0ddf566df4e33843d77fd030b442a77533a15c04f4da8f98303e8619b994c5d5072d47115a727aa6a9ed0; twid=u%3D1466811110439493646; _twitter_sess=BAh7CSIKZmxhc2hJQzonQWN0aW9uQ29udHJvbGxlcjo6Rmxhc2g6OkZsYXNo%250ASGFzaHsABjoKQHVzZWR7ADoPY3JlYXRlZF9hdGwrCOJoSVKJAToMY3NyZl9p%250AZCIlOTg1ZTRjMzk5ZmQxNDQwOWQyOTI4ZDlkMWJlZjk1MjY6B2lkIiVjMTVk%250ANTY3ZWZlNDk2MzBjZTFiZmUwZWM0Y2Y3MmY0OA%253D%253D--cd7422400c5a859f558516993cd735d14d382210; eu_cn=1',
			'dnt': '1',
			'origin': 'https://twitter.com',
			'referer': 'https://twitter.com/burgaci',
			'sec-ch-ua': '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
			'sec-ch-ua-mobile': '?0',
			'sec-ch-ua-platform': '"macOS"',
			'sec-fetch-dest': 'empty',
			'sec-fetch-mode': 'cors',
			'sec-fetch-site': 'same-origin',
			'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
			'x-client-transaction-id': 'rMGVmBsMSped/aPbT6jVQgzVJzvBkxi4KEooNpN0Jh3T086iG3az+fW14DZzLkCFed1XYQCl8/q+MbU1WQUbBl58ZkZU',
			'x-client-uuid': 'f6b9cf9d-535a-4311-afb8-6e5ea0aa60fd',
			'x-csrf-token': 'd3e59112287d80fbb6b1f4cc60b793060d3ef3276d421c6d8936ebf5c827913917881159b4f0ddf566df4e33843d77fd030b442a77533a15c04f4da8f98303e8619b994c5d5072d47115a727aa6a9ed0',
			'x-twitter-active-user': 'yes',
			'x-twitter-auth-type': 'OAuth2Session',
			'x-twitter-client-language': 'en',
		}
		
		json_data = {
			'variables': {
				'tweet_id': ID,
				'dark_request': False,
			},
			'queryId': 'VaenaVgh5q5ih7kvyVjgtg',
		}
		
		response = requests.post(
			'https://twitter.com/i/api/graphql/VaenaVgh5q5ih7kvyVjgtg/DeleteTweet',
			cookies=cookies,
			headers=headers,
			json=json_data,
		)
		
		print(response.text)
