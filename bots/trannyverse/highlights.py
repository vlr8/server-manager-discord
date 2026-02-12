"""
Highlights System Module

Tracks popular messages and reposts them to a highlights channel.
Triggers:
- 5+ replies to a message
- 5+ unique reactions to a message
"""

import asyncio
import re
import aiohttp

import interactions
from interactions import Button, ButtonStyle, listen
from interactions.api.events import MessageReactionAdd

import analytics_db as db
from common.consts import (
    excluded_highlight_channels,
    highlights_channel_id,
    guild_id,
    basicheaders,
)

# Lock to prevent race conditions when processing highlights
processing_highlights = set()

# Reply threshold for highlights
REPLY_THRESHOLD = 4  # More than 4 replies (i.e., 5+)
REACTION_THRESHOLD = 5  # 5 unique reactions


async def handle_message_reply(client, ctx):
    """
    Handle reply tracking and highlight creation for message replies.

    Call this from on_message_create when a message is a reply.
    """
    global processing_highlights

    # Skip if not a reply or in excluded channels
    if not ctx.message.message_reference:
        return
    if ctx.message.channel.id in excluded_highlight_channels:
        return

    original_message_id = ctx.message.message_reference.message_id

    # Retry if the message is already being processed
    retries = 5
    while original_message_id in processing_highlights and retries > 0:
        await asyncio.sleep(0.5)
        retries -= 1

    if retries == 0:
        print(f"Highlight processing still busy for message ID {original_message_id}, skipping...")
        return

    # Add to processing cache
    processing_highlights.add(original_message_id)

    try:
        # Check if the original message has already been highlighted
        existing_highlight = db.get_highlight_by_original(original_message_id)

        if existing_highlight:
            # Edit reposted message embed to include the new reply
            highlights_channel = client.get_channel(highlights_channel_id)
            highlight_msg = await highlights_channel.fetch_message(existing_highlight['highlight_id'])

            # Check field limit
            if len(highlight_msg.embeds[0].fields) >= 25:
                return

            # Get reply author
            guild = await client.fetch_guild(guild_id)
            reply_author = guild.get_member(ctx.message.author.id)

            # Add the reply to the embed
            highlight_embed = highlight_msg.embeds[0]
            highlight_embed.add_field(
                name=f"↳ {str(reply_author.display_name)}",
                value=str(ctx.message.content),
                inline=False
            )
            await highlight_msg.edit(embed=highlight_embed)
            return

        # Track the reply in DB
        db.insert_reply_tracking(
            reply_id=ctx.message.id,
            original_message_id=original_message_id,
            author_id=ctx.message.author.id,
            content=str(ctx.message.content)
        )

        # Check reply count
        reply_count = db.count_replies_to_message(original_message_id)

        if reply_count > REPLY_THRESHOLD:
            # Create highlight
            await create_reply_highlight(client, ctx, original_message_id)

    finally:
        processing_highlights.discard(original_message_id)


async def create_reply_highlight(client, ctx, original_message_id):
    """Create a highlight from a message that has enough replies."""
    # Fetch the original message
    original_channel = await client.fetch_channel(ctx.message.channel.id)
    original_message = await original_channel.fetch_message(original_message_id)

    # Build embed
    embed = interactions.Embed()
    embed.set_author(
        name=str(original_message.author.display_name),
        icon_url=original_message.author.avatar_url,
        url=f"https://discord.com/users/{original_message.author.id}"
    )
    embed.title = "Jump to message"
    embed.url = original_message.jump_url
    embed.description = original_message.content

    # Add all replies as fields
    replies = db.get_replies_to_message(original_message_id)
    guild = await client.fetch_guild(guild_id)

    for reply in replies:
        reply_author = guild.get_member(reply['author_id'])
        author_name = reply_author.display_name if reply_author else "Unknown"
        embed.add_field(
            name=f"↳ {author_name}",
            value=reply['reply_content'],
            inline=False
        )

    # Handle embedded content
    if original_message.embeds:
        embed.description = ""
        orig_embed = original_message.embeds[0]
        if orig_embed.author and orig_embed.author.name:
            embed.description += orig_embed.author.name + "\n"
        if orig_embed.title:
            embed.description += orig_embed.title + "\n"
        if orig_embed.description:
            embed.description += orig_embed.description + "\n"

    # Set thumbnail from attachments
    embed.thumbnail = original_message.attachments[0].url if original_message.attachments else None

    # Handle media URLs in content
    check_url = original_message.content.split("?")[0] if original_message.content else ""

    if check_url.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
        embed.thumbnail = check_url
        embed.description = None
    elif "tenor.com" in check_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(check_url + ".gif", headers=basicheaders) as response:
                    tenor_url_text = await response.text()
                    tenor_gif_url = re.findall(r'src=\"(https?://[^\"]+)\"', tenor_url_text)[0]
                    embed.thumbnail = tenor_gif_url
                    embed.description = None
        except Exception:
            pass

    # Post to highlights channel
    highlights_channel = client.get_channel(highlights_channel_id)
    highlight_msg = await highlights_channel.send(
        embed=embed,
        components=[[Button(style=ButtonStyle.DANGER, emoji="🗑️", custom_id="delete_highlight")]]
    )

    # React with star
    await highlight_msg.add_reaction("⭐")

    # Notify original author
    await original_message.reply(
        f"Your message has made it to <#{highlights_channel_id}>! <:society:1158917736534134834>",
        ephemeral=True
    )

    # Log to database
    db.insert_highlight(
        highlight_id=highlight_msg.id,
        original_message_id=original_message_id,
        author_id=original_message.author.id
    )


async def handle_reaction_highlight(client, event: MessageReactionAdd):
    """
    Handle reaction-based highlights.

    Call this from on_reaction when reaction_count reaches threshold.
    """
    global processing_highlights

    # Only trigger at exactly REACTION_THRESHOLD reactions
    if event.reaction_count != REACTION_THRESHOLD:
        return

    # Skip bot reactions
    if event.author.bot:
        return

    # Skip excluded channels
    if event.message.channel.id in excluded_highlight_channels:
        return

    message_id = event.message.id

    # Retry if already being processed
    retries = 5
    while message_id in processing_highlights and retries > 0:
        await asyncio.sleep(0.5)
        retries -= 1

    if retries == 0:
        print(f"Highlight processing still busy for message ID {message_id}, skipping...")
        return

    processing_highlights.add(message_id)

    try:
        # Check if already highlighted
        if db.get_highlight_by_original(message_id):
            return

        # Build embed
        embed = interactions.Embed()
        embed.set_author(
            name=event.message.author.display_name,
            icon_url=event.message.author.avatar_url,
            url=f"https://discord.com/users/{event.message.author.id}"
        )
        embed.title = "Jump to message"
        embed.url = event.message.jump_url
        embed.description = event.message.content

        # Handle embedded content
        if len(event.message.embeds) > 0:
            orig_embed = event.message.embeds[0]
            embed.description = ""
            if orig_embed.author and orig_embed.author.name:
                embed.description += orig_embed.author.name + "\n"
            if orig_embed.title:
                embed.description += orig_embed.title + "\n"
            if orig_embed.description:
                embed.description += orig_embed.description + "\n"
            if not embed.description.strip():
                embed.description = "[Embed with no text content]"

        # Set image from attachments
        embed.image = event.message.attachments[0].url if event.message.attachments else None

        # Handle media URLs in content
        check_url = event.message.content.split("?")[0] if event.message.content else ""

        if check_url.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
            embed.image = check_url
            embed.thumbnail = None
            embed.description = None
        elif "tenor.com" in check_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(check_url + ".gif", headers=basicheaders) as response:
                        tenor_url_text = await response.text()
                        tenor_gif_url = re.findall(r'src=\"(https?://[^\"]+)\"', tenor_url_text)[0]
                        embed.image = tenor_gif_url
                        embed.thumbnail = None
                        embed.description = None
            except Exception:
                pass

        # Post to highlights channel
        highlights_channel = client.get_channel(highlights_channel_id)
        highlight_msg = await highlights_channel.send(
            embed=embed,
            components=[[Button(style=ButtonStyle.DANGER, emoji="🗑️", custom_id="delete_highlight")]]
        )

        # Notify original author
        await event.message.reply(
            f"Your message has made it to <#{highlights_channel_id}>! <:society:1158917736534134834>",
            ephemeral=True
        )

        # Log to database
        db.insert_highlight(
            highlight_id=highlight_msg.id,
            original_message_id=message_id,
            author_id=event.message.author.id
        )

        # Copy original reactions to highlight
        for reaction in event.message.reactions:
            await highlight_msg.add_reaction(reaction.emoji)

    finally:
        processing_highlights.discard(message_id)
