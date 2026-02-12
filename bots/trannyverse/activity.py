import asyncio
import datetime
import json
import interactions
from interactions import Intents
from common.consts import *
from extensions import helpers
import os
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN = os.environ['TRANNYVERSE_BOT_TOKEN']

client = interactions.Client(token=BOT_TOKEN, default_scope=guild_id,
                             # intents=Intents.GUILDS | Intents.GUILD_MEMBERS | Intents.GUILD_MESSAGES | Intents.GUILD_MESSAGE_REACTIONS | Intents.MESSAGE_CONTENT | Intents.DIRECT_MESSAGES | Intents.DIRECT_MESSAGE_REACTIONS
                             intents=Intents.ALL
                             )
tab_space = '‎ ‎ ‎ ‎ ‎ '


async def fetch_messages():
    # Get all chatting channels
    guild = client.get_guild(guild_id)
    chat_categories = (1158203872674840576, 1262258334401040476, 1262257916665397279)
    blacklisted_channels = [
        1220844022780657674,  # nsfw
        1158203872674840585,  # nsfw
        1262267477774041158,  # nsfw
    ]
    channels = [channel for channel in guild.channels if channel.type == 0 and channel.category.id in chat_categories and channel.id not in blacklisted_channels]
    
    # Now get all messages up until n days ago
    fetch_before = (datetime.datetime.now() - datetime.timedelta(days=7)).timestamp()
    
    messages = {
        **{channel.name: [] for channel in channels},
    }
    for channel in channels:
        print('Fetching messages for: #' + channel.name)
        
        last_message = None
        while True:
            # Fetch messages
            # fetched_messages = await channel.history(limit=0, before=last_message.id if last_message else None).fetch()
            fetched_messages = helpers.fetch_messages(channel.id, limit=100, fetch_all=True, within='last week', usebot=True)
            
            if not len(fetched_messages) == 0:
                last_message = fetched_messages[-1]

            # Format messages and add them to the list
            for message in fetched_messages:
                messages[channel.name].append({
                    'author': message.author.id,
                    'content': message.content,
                    'attachments': [attachment.url for attachment in message.attachments],
                    'created_at': message.created_at.timestamp(),
                    'channel': channel.id,
                    'id': message.id,
                    'reply_to': message.message_reference.message_id if message.message_reference else None,
                })
            
            # Check if we should stop
            last_message_date = last_message.created_at.timestamp()
            if last_message_date < fetch_before:
                break
            
            print('\r' + f"Fetched {len(messages[channel.name])} messages so far...", end='')
        
        print('Fetched ' + str(len(fetched_messages)) + ' messages in total for: #' + channel.name)
    
    # Save messages to file
    with open('discord/activity_files/messages.json', 'w') as f:
        json.dump(messages, f, indent=4)


async def evaluate_messages():
    with open('discord/activity_files/messages.json', 'r') as f:
        channels = json.load(f)
    
    guild = client.get_guild(guild_id)
    members = [member for member in guild.members if not member.bot]
    print('Found ' + str(len(members)) + ' members')
    
    most_replied_to = []
    for channel in channels:
        channel = channels[channel]
        for message in [x for x in channel if x['reply_to']]:
            if not any(x['message'] == message['reply_to'] for x in most_replied_to):
                most_replied_to.append({
                    'channel': int(message['channel']),
                    'message': int(message['reply_to']),
                    'replies': [{
                        'content': x['content'],
                        'author': x['author'],
                    } for x in channel if x['reply_to'] == message['reply_to']],
                })
    
    # Sort by most replies
    most_replied_to = sorted(most_replied_to, key=lambda x: len(x['replies']), reverse=True)
    
    # Fetch the top 10 most replied to messages
    formatted_most_replied_to = []
    for message in most_replied_to[:10]:
        channel = client.get_channel(message['channel'])
        fetched_message = await channel.fetch_message(message['message'])
        
        if not fetched_message:
            continue
            
        try:
            author_name = fetched_message.author.nickname
            if not author_name:
                raise AttributeError
        except:
            try:
                author_name = fetched_message.author.display_name
                if not author_name:
                    raise AttributeError
            except:
                author_name = fetched_message.author.username
                if not author_name:
                    raise AttributeError
            
        formatted_most_replied_to.append({
            **message,
            'content': fetched_message.content.replace('@', '@ '),
            'attachments': [attachment.url for attachment in
                            fetched_message.attachments] if fetched_message.attachments else [],
            'author': {
                'id': fetched_message.author.id,
                'name': author_name,
                'avatar': fetched_message.author.avatar_url,
            }
        })
    
    # Save to file
    with open('discord/activity_files/most_replied_to.json', 'w') as f:
        json.dump(formatted_most_replied_to, f, indent=4)


async def evaluate_activity():
    with open('discord/activity_files/messages.json', 'r') as f:
        channels = json.load(f)
    
    guild = client.get_guild(guild_id)
    members = [member for member in guild.members if not member.bot]
    print('Found ' + str(len(members)) + ' members')
    
    # Find the least active members
    member_activity = []
    for member in members:
        member_messages = 0
        for channel in channels:
            channel = channels[channel]
            for message in channel:
                if message['author'] == member.id:
                    member_messages += 1
        
        member_activity.append({
            'member': member.id,
            'messages': member_messages,
        })
    
    # Sort by most messages
    member_activity = sorted(member_activity, key=lambda x: x['messages'], reverse=False)
    
    # For visualizing
    # print(json.dumps(member_activity, indent=4))
    
    # Save to file
    with open('discord/activity_files/member_activity.json', 'w') as f:
        json.dump(member_activity, f, indent=4)


async def generate_highlights(inactivity_threshold=0, debug=False):
    with open('discord/activity_files/member_activity.json', 'r') as f:
        member_activity = json.load(f)
    
    guild = client.get_guild(guild_id)
    
    # Find the least active members
    inactive_members = [member for member in member_activity if member['messages'] <= inactivity_threshold]
    
    # Create the highlights embed
    with open('discord/activity_files/most_replied_to.json', 'r') as f:
        most_replied_to = json.load(f)
    
    embeds = []
    for message in most_replied_to:
        embed = interactions.Embed(
            title='',
            description=f"[{message['content']}](https://discord.com/channels/{guild_id}/{message['channel']}/{message['message']})",
            thumbnail=message['attachments'][0] if message['attachments'] else None,
            color=0x00ff00,
        )
        embed.set_author(name=message['author']['name'][0:32], icon_url=message['author']['avatar'])
        
        for reply in message['replies']:
            if 'http' in reply:
                continue
            
            author = guild.get_member(reply['author'])
            if not author:
                continue
            author_name = author.nick if author.nick else author.display_name
            message_content = reply['content'].replace('\n', '\n' + tab_space)
            embed.add_field(name=f"↳ {author_name}", value=f"{tab_space}{message_content}", inline=False)
        
        embeds.append(embed)
    
    if not debug:
        # Post the embeds in the highlights channel
        highlights_channel = client.get_channel(highlights_channel_id)
        
        # Send the embeds in the highlights channel
        # await highlights_channel.send(content=f"@everyone")  # dont ping i think
        for embed in embeds:
            msg = await highlights_channel.send(embed=embed)
            # Add a star reaction to the embed
            await msg.add_reaction('⭐')
            
    
    # DM inactive members
    for member in inactive_members:
        member_id = member['member']
        member = guild.get_member(member_id)
        if not member:
            continue
        
        if debug:
            member = guild.get_member(1052263609452994581)  # robotbabe
        
        print('DMing', member)
        try:
            await member.send(embeds=embeds)
            await member.send(content="here's what u've been missing this week\nu should consider coming back <a:heartUmji:1162551252438229002>\ndiscord.gg/tranners")
            if debug:
                return
        except:
            print('Failed to DM member', member)


async def debug():
    # Fetches all messages from the last week
    await fetch_messages()
    
    # Finds the most replied to messages
    await evaluate_messages()
    
    # Finds the least active members
    await evaluate_activity()
    
    # DMs inactive members
    await generate_highlights(inactivity_threshold=0, debug=True)


async def main():
    while True:
        # Wait until Thursday 21:00:00
        post_time = datetime.datetime.now().replace(hour=21, minute=0, second=0, microsecond=0)
        
        # Sleep until the next post time
        await asyncio.sleep((post_time - datetime.datetime.now()).total_seconds())
        
        # Fetches all messages from the last week
        await fetch_messages()
        
        # Finds the most replied to messages
        await evaluate_messages()
        
        # Finds the least active members
        await evaluate_activity()
        
        # DMs inactive members
        await generate_highlights(inactivity_threshold=0)
        
        # Sleep 24 hours
        print('Sleeping until next Friday.')
        await asyncio.sleep(60 * 60 * 24)


@interactions.listen()
async def on_startup():
    await debug()
    # await main()


client.start()
