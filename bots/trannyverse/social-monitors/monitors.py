import os
from pprint import pprint
import threading
import traceback
import time
import json
import common.discord as discord
import common.logger as logger

from fourchan.fourchan import Fourchan
from mumsnet.mumsnet import Mumsnet
from reddit.reddit import Reddit
from tumblr.tumblr import Tumblr
from instagram.instagram import Instagram
# from twitter.twitter import Twitter

logger = logger.get_logger('monitors')


def run_bot():
	global post_ids

	# initialization etc
	monitors = [
		# Fourchan(
		# 	name='fourchan',
		# 	board='lgbt',
		# 	post_ids=post_ids.get('fourchan', []),
		# 	channel_ids=[
		# 		1158203872423186456,  # trannerland
		# 		# 1128797444323426394,  # debug
		# 	],
		# ),

		# Mumsnet(
		# 	name='mumsnet',
		# 	queries=[
		# 		'trans',
		# 	],
		# 	keywords=[
		# 		'terf',
		# 		'trans',
		# 		'transexuals',
		# 		'transexual',
		# 		'transwomen',
		# 		'transwoman',
		# 		'transgender',
		# 		'nonbinary',
		# 		'non-binary',
		# 		'non binary',
		# 		'nonbinary',
		# 	],
		# 	post_ids=post_ids.get('mumsnet', []),
		# 	channel_ids=[
		# 		1158203872423186460,  # trannerland
		# 		# 1128797444323426394,  # debug
		# 	],
		# 	max_pages=399,
		# ),

		Reddit(
			name='reddit',
			queries=[
				'trans',
				'boymode'
			],
			subreddits=[
				#'egg_irl',
				#'asktransgender',
				# 'mtf',
				'transpositive',
				'Nestofeggs',
				'traaaaaaannnnnnnnnns',
				'traaaaaaannnnnnnnnns2'
			],
			post_ids=post_ids.get('reddit', []),
			channel_ids=[
				1158203872423186459,  # trannerland
				# 1158203872423186459,  # debug
			],
		),

		Instagram(
			name='instagram',
			usernames=[
				'chaseicon',
				'hunterschafer',
				#'thefakehazel',
				'lenacassandre',
				'aoife_bee_',
				'autogyniphiles_anonymous',
				'trans_misogynist',
				'trans__memes_',
				'transgirlhell',
				'transtrender666',
				'transgender.gamer.girl',
				'rhizomatic_memer',
				'trooncelfatale',
				'user_goes_to_kether',
				't.slur.memes'
				'attis.emasculate',
				#'oncloud.e',
				'doll.deranged',
				'based.transgirl',
				'sissy.allegations'
			],
			post_ids=post_ids.get('instagram', []),
			channel_ids=[
				1158203872423186461,  # trannerland
				# 1128797444323426394,  # debug
			],
		)

		# Tumblr(
		# 	name='tumblr',
		# 	queries=[
		# 		'trans',
		# 	],
		# 	post_ids=post_ids.get('tumblr', []),
		# 	channel_ids=[
		# 		1158203872423186458,  # trannerland
		# 		# 1128797444323426394,  # debug
		# 	],
		# ),
	]

	# Start each monitor in a separate thread
	threads = []
	for Monitor in monitors:
		thread = threading.Thread(target=repost_to_discord, args=(Monitor,))
		threads.append(thread)
		thread.start()

	# repost_to_discord()


def repost_to_discord(Monitor):
	while True:
		try:
			global post_ids

			# Fetch new posts
			posts = Monitor.fetch_posts()
			logger.info(f"Fetched {len(posts)} posts from {Monitor.name}")

			# Remove posts that have already been posted
			posts = [x for x in posts if x['id'] not in Monitor.post_ids]

			# Sort posts by date (oldest first)
			posts = sorted(posts, key=lambda x: x['date'])

			# Add the new posts to the list of posted posts
			# Monitor.post_ids += [post['id'] for post in posts]

			# Post the new posts to Discord
			for post in posts:
				if Monitor.url_only:
					discord.post(
						url_only=True,
						url=post['url'],
						channel_ids=Monitor.channel_ids,
					)

				else:
					discord.post(
						title=post['title'],
						description=post['description'],
						image=post.get('image'),
						thumbnail=post.get('thumbnail'),
						date=post['date'],
						url=post['url'],
						site_name=Monitor.webhook_name,
						site_icon=Monitor.webhook_icon,
						color_scheme=Monitor.color_scheme,
						channel_ids=Monitor.channel_ids,
					)
				Monitor.post_ids += post['id']

			# Save the new list of posted posts
			post_ids[Monitor.name] = Monitor.post_ids
			with open('post_ids.json', 'w') as f:
				json.dump(post_ids, f, indent=4)

			time.sleep(60)

		except:
			logger.error(traceback.format_exc())
			time.sleep(60)


def debug():
	global post_ids

	Monitor = Mumsnet(
		name='mumsnet',
		queries=[
			'trans',
		],
		keywords=[
			'terf',
			'trans',
			'transexuals',
			'transexual',
			'transwomen',
			'transwoman',
			'transgender',
			'nonbinary',
			'non-binary',
			'non binary',
			'nonbinary',
		],
		post_ids=post_ids.get('mumsnet', []),
		channel_ids=[
			# 1158203872423186460,  # trannerland
			1128797444323426394,  # debug
		],
		max_pages=10,
	)

	# posts = Monitor.fetch_posts()
	# pprint(posts)
	repost_to_discord(Monitor)


if __name__ == '__main__':
	# Open the post_ids file if it exists
	if os.path.exists('post_ids.json'):
		with open('post_ids.json', 'r') as f:
			post_ids = json.load(f)

	else:
		with open('post_ids.json', 'w') as f:
			json.dump({}, f)
			post_ids = {}

	run_bot()
	# debug()
