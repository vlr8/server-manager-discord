# Standard library imports
import asyncio
import atexit
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import random
import re
import signal
import sys
import time
import traceback
import aiohttp
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN = os.environ['TRANNYVERSE_BOT_TOKEN']

# Third-party imports
import emoji
import interactions
import matplotlib.pyplot as plt
import seaborn as sns
from interactions import (
    AutoShardedClient,
    Button,
    ButtonStyle,
    Intents,
    OptionType,
    SlashCommandChoice,
    auto_defer,
    component_callback,
    listen,
    slash_command,
    slash_option,
)
from interactions.api.events import *
from tinydb import Query, TinyDB, where

# Local imports
from common import utils
from common.consts import *
from .extensions import helpers
from .extensions import oxford
from .extensions import profanity
from .extensions import urban
from .extensions import yandex
# for analytics and data exporting
from common.db import insert_live_message
from common import db
from .analytics_commands import *
# for mass purging user messages
from .purge_commands import *
# highlights system module
from . import highlights

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger("BotLogger")

# Suppress noisy matplotlib font warnings
logging.getLogger('matplotlib.font_manager').setLevel(logging.WARNING)

client = AutoShardedClient(
    token=BOT_TOKEN,
    default_scope=guild_id,
    shard_ids=[0],
    intents=Intents.GUILDS | Intents.GUILD_MEMBERS | Intents.GUILD_MODERATION | Intents.GUILD_INVITES | Intents.GUILD_MESSAGES |
            Intents.GUILD_MESSAGE_REACTIONS | Intents.MESSAGE_CONTENT | Intents.DEFAULT | Intents.PRIVILEGED
)

all_emojis = [emj for emj in emoji.EMOJI_DATA]


#db = TinyDB('bots/trannyverse/db.json')
invites_table_db = TinyDB('bots/trannyverse/invites_table_db.json')
invites_table = invites_table_db.table('invites')

ban_table_db = TinyDB('bots/trannyverse/ban_table_db.json')
ban_table = ban_table_db.table("bans")
BAN_LIMIT = 2  # Max bans allowed in the timeframe
TIME_FRAME = 21600  # Timeframe in seconds

diva_mute_table_db = TinyDB('bots/trannyverse/diva_mute_table_db.json')
diva_mute_table = diva_mute_table_db.table("diva_mute")
DIVA_DAILTY_MUTE_LIMIT = 8  # Max of 2-hour mutes allowed in a day
# DIVA_MUTE_TIME_FRAME = 86400  # should be 24 hours

# db = TinyDB('bots/trannyverse/db.json')
sensitive_invites_db = TinyDB('bots/trannyverse/sensitive_invites_db.json')
sensitive_invites = sensitive_invites_db.table('sensitive_invites')

forced_nicknames_table_db = TinyDB('bots/trannyverse/forced_nicknames_table_db.json')
forced_nicknames_table = forced_nicknames_table_db.table('forced_nicknames')

slowed_members_table_db = TinyDB('bots/trannyverse/slowed_members_table_db.json')
slowed_members_table = slowed_members_table_db.table('slowed_members')

activity_log_table_db = TinyDB('bots/trannyverse/activity_log_table_db.json')
activity_log_table = activity_log_table_db.table('activity_log')

doomers_table_db = TinyDB('bots/trannyverse/doomers_table_db.json')
doomers_table = doomers_table_db.table('doomers')

gagged_table_db = TinyDB('bots/trannyverse/gagged_table_db.json')
gagged_table = gagged_table_db.table('gagged')

forced_gender_table_db = TinyDB('bots/trannyverse/forced_gender_table_db.json')
forced_gender_table = forced_gender_table_db.table('forced_gender')

member_roles_table_db = TinyDB('bots/trannyverse/member_roles_table_db.json')
member_roles_table = member_roles_table_db.table('member_roles')  # log member roles in case of leaves

deathmatch_table_db = TinyDB('bots/trannyverse/deathmatch_table_db.json')
deathmatch_table = deathmatch_table_db.table('deathmatch')  # logging deathmatches

spammers_table_tb = TinyDB('bots/trannyverse/spammers_table_tb.json')
spammers_table = spammers_table_tb.table('spammers')  # logging spammers

# highlights_table and message_replies moved to SQLite via db module

male_prohibited_roles = [
    enbymoder_role, enby_role, lesbian_role, twinkhon_role, tranner_role, female_role, pooner_role
]
gender_roles = [male_role, female_role, tranner_role, pooner_role, enby_role]


# Check if the bot is ready
@client.listen()
async def on_startup():
    logger.info(f"We're online!")

    # Initialize analytics database
    db.init_database()
    logger.info("Analytics database ready")

    # Set presence
    await client.change_presence(
        status=interactions.Status.ONLINE,
        activity=interactions.Activity(
            name="discord.gg/tranners",
            type=interactions.ActivityType.WATCHING,
        )
    )

    # Set up the database
    guild = client.get_guild(guild_id)
    logger.info(f"guild here is ! {guild}")
    guild_invites = await guild.fetch_invites()
    for invite in guild_invites:
        # This will update the invite in the DB or insert it if it doesn't exist
        logger.info(f"invite code is! {str(invite.code)} and uses is {invite.uses}")
        invites_table.upsert({'code': str(invite.code), 'uses': invite.uses, 'guild_id': str(guild.id)}, Query().code == str(invite.code))

    # Start expired gags checker
    asyncio.create_task(check_expired_gags_task())
    logger.info("Expired gags checker task started")

    # Restore gag state from database
    current_time = time.time()
    expired_count = 0
    active_count = 0

    gagged_role = guild.get_role(gagged_role_id)

    for gag_record in gagged_table.all():
        if current_time >= gag_record['expires_at']:
            # Clean up expired gags
            try:
                member = guild.get_member(gag_record['user_id'])
                if member and member.has_role(gagged_role_id):
                    await member.remove_role(gagged_role)
            except Exception as e:
                logger.error(f"Failed to remove expired gag on startup: {e}")
            gagged_table.remove(where('user_id') == gag_record['user_id'])
            expired_count += 1
        else:
            # Restore active gags
            try:
                member = guild.get_member(gag_record['user_id'])
                if member and not member.has_role(gagged_role_id):
                    await member.add_role(gagged_role)
                    logger.info(f"Restored gag role to user {member.id}")
            except Exception as e:
                logger.error(f"Failed to restore gag role on startup: {e}")
            active_count += 1

    logger.info(f"Gag state restored: {active_count} active, {expired_count} expired and removed")


async def check_expired_gags_task():
    """Background task that checks for expired gags every 60 seconds"""
    await client.wait_until_ready()
    logger.info("Starting expired gags checker task")

    while True:
        try:
            current_time = time.time()
            guild = client.get_guild(guild_id)
            gagged_role = guild.get_role(gagged_role_id)

            # Get all active gags
            all_gags = gagged_table.all()

            for gag_record in all_gags:
                if current_time >= gag_record['expires_at']:
                    user_id = gag_record['user_id']

                    # Try to remove the role
                    try:
                        member = guild.get_member(user_id)
                        if member and member.has_role(gagged_role_id):
                            await member.remove_role(gagged_role)
                            logger.info(f"Removed gag from user {user_id} (expired)")
                    except Exception as e:
                        logger.error(f"Failed to remove gag role from {user_id}: {e}")

                    # Remove from database regardless of role removal success
                    gagged_table.remove(where('user_id') == user_id)

        except Exception as e:
            logger.error(f"Error in check_expired_gags_task: {e}")

        # Sleep for 60 seconds before next check
        await asyncio.sleep(60)


# Error handling
@client.listen(CommandError)
async def on_command_error(event: CommandError):
    error = "".join(traceback.format_exception(event.error))
    logger.error(error)
    await event.ctx.send("An error occured. Please try again.", ephemeral=True)


# Audit log listener
@client.listen(GuildAuditLogEntryCreate)
async def on_auditlog(event: GuildAuditLogEntryCreate):
    entry = event.audit_log_entry

    mod = entry.user_id
    target = entry.target_id

    try:
        action = entry.changes[0]
    except TypeError:
        return

    # If the action is a timeout
    if action.key == 'communication_disabled_until':
        # Get the mod and the target
        mod = await event.guild.fetch_member(mod)
        target = await event.guild.fetch_member(target)

        # Timeout time
        timeout_time = target.communication_disabled_until
        mod_log_channel = client.get_channel(mod_log_channel_id)

        # Log the timeout
        embed = interactions.Embed(
            title="Member Timeout",
            color=0x9c92d1
        )
        mod_display_name = str(mod.display_name).encode('cp1252', errors='replace').decode('cp1252')
        target_display_name = str(target.display_name).encode('cp1252', errors='replace').decode('cp1252')
        embed.set_author(name=str(mod.display_name), icon_url=mod.avatar_url)
        if timeout_time:
            logger.info(
                f"@{mod_display_name} timed out @{target_display_name} until {utils.convert_discord_timestamp(timeout_time)}")
            embed.description = f"{mod.mention} timed out {target.mention} until {timeout_time}"

        else:
            logger.info(f"@{mod_display_name} removed timeout from @{target_display_name}")
            embed.description = f"{mod.mention} removed timeout from {target.mention}"

        await mod_log_channel.send(embed=embed)


# Delete highlight button
@component_callback("delete_highlight")
async def delete_highlight(event: interactions.ComponentContext):
    # Check if the user is the author of the message
    highlight = highlights_table.get(where('highlight_id') == event.message.id)

    # If the highlight is immortalized return
    if highlight.get('immortalized'):
        return

    if highlight['author_id'] == event.author.id:
        # Ask the user if they are sure
        await event.respond("Are you sure you want to delete your highlight?", ephemeral=True, components=[
            [
                # Pass the highlight msg id as well
                Button(style=ButtonStyle.DANGER, label="Yes", custom_id=f"confirm_delete_highlight:{event.message.id}"),
                Button(style=ButtonStyle.SECONDARY, label="No", custom_id=f"cancel_delete_highlight:{event.message.id}")
            ]
        ])

    else:
        await event.respond("You are not the author of this highlight.", ephemeral=True)


# Confirm delete highlight button
@component_callback(re.compile(r"^confirm_delete_highlight:"))
async def confirm_delete_highlight(event: interactions.ComponentContext):
    # Parse the highlight id from the custom id
    highlight_msg_id = int(event.custom_id.split(":")[1])

    # Check if the user is the author of the message
    highlight = highlights_table.get(where('highlight_id') == highlight_msg_id)
    if highlight['author_id'] == event.author.id:
        # Delete the highlight message
        highlight_channel = client.get_channel(highlights_channel_id)
        highlight_msg = await highlight_channel.fetch_message(highlight_msg_id)
        await highlight_msg.delete()

        # Delete the entry from the highlights table
        highlights_table.remove(where('highlight_id') == highlight_msg_id)
        await event.edit_origin(content="Your highlight has been deleted.", components=[])

    else:
        await event.respond("You are not the author of this highlight.", ephemeral=True)


# Cancel delete highlight button
@component_callback(re.compile(r"^cancel_delete_highlight:"))
async def cancel_delete_highlight(event: interactions.ComponentContext):
    # Remove the buttons on the replied to msg
    await event.edit_origin(content="Deletion cancelled.", components=[])


# On invite create
@client.listen(InviteCreate)
async def on_invite_create(event: InviteCreate):
    invite = event.invite
    # Add the invite to the database
    invites_table.upsert({'code': invite.code, 'uses': invite.uses, 'guild_id': str(invite.guild.id)}, Query().code == invite.code)
    logger.info(f"Invite created: {invite.code}")


# Member role change
_role_update_in_progress = set()  # guards against re-entrant cascades

@client.listen(MemberUpdate)
async def on_member_role_change(event: MemberUpdate):
    member = event.after

    # Skip if the bot is already processing a role change for this member
    # (our own add_role / remove_role calls fire new MemberUpdate events)
    if member.id in _role_update_in_progress:
        return
    _role_update_in_progress.add(member.id)
    try:
        await _handle_role_change(event, member)
    finally:
        _role_update_in_progress.discard(member.id)


async def _handle_role_change(event, member):
    # new user setting roles for first time
    # before_roles = getattr(event.before, 'roles', None) if event.before else None
    # if before_roles is not None and len(before_roles) == 0 and len(member.roles) > 0:


    ##### the rest is for when they already have roles that need to be forced or reset

    # if the user was new before but now they got verified, introduce them to monkey chat 1360707963718996088 after_verified_role_id
    # if (event.before.has_role(new_trans_member_role_id) and not member.has_role(new_trans_member_role_id)):
    #     await member.add_role(event.guild.get_role(after_new_member_role_id))after_verified_role_id

    # Prevent deathmatch from getting new roles
    if member.has_role(deathmatch_role_id):
        # If member only has doomer or only has deathmatch role, dont do anything
        if len(member.roles) == 1 and member.has_role(deathmatch_role_id):
            return

        deathmatch_role = event.guild.get_role(deathmatch_role_id)

        # Remove all roles except the deathmatch role
        await member.edit(roles=[])
        await member.add_role(deathmatch_role)

    # If the member is in forced_gender list, remove the new gender role and assign the previous one
    if forced_gender_table.get(where('user_id') == member.id):
        # Identify the previous and current gender roles
        gender_role_before = forced_gender_table.get(where('user_id') == member.id)['role_id']
        gender_role_now = None
        for role in member.roles:
            if role.id in gender_roles:  # Match roles from the `gender_roles` set
                gender_role_now = role.id
                break  # Stop after finding the first match

        # If the roles are identical, return
        if gender_role_before == gender_role_now:
            return

        # If this update already matches the enforced role, assume it was bot-triggered
        if gender_role_now == gender_role_before:
            logger.info(f"Role update matches enforced role; skipping handling for {member.display_name}.")
            return

        if gender_role_now:
            # Otherwise, enforce the correct role
            logger.info(f"Forced gender member {member.display_name} tried picking "
                        f"{member.guild.get_role(gender_role_now).name} and was set back to "
                        f"{member.guild.get_role(gender_role_before).name}")

        # Remove all gender roles
        roles_to_remove = [role.id for role in member.roles if role.id in gender_roles]
        if roles_to_remove:
            await member.remove_roles(roles_to_remove)

        # Enforce roles
        await member.add_role(gender_role_before)

    # Prevent male role from picking trans roles
    if member.has_role(male_role):
        # use the any function to check if the member has any of the girl roles
        if any(role.id in male_prohibited_roles for role in member.roles):
            # Remove the not allowed role
            for role in member.roles:
                if role.id in male_prohibited_roles:
                    logger.info(f"{member.mention} tried to pick prohibited role: {role.name}, removing it.")
                    await member.remove_role(role)
    # Add verified tier roles for people to control channel visibility
    if member.has_role(selfies_role):
        if member.has_role(tranner_role) or member.has_role(pooner_role) or member.has_role(enby_role):
            if member.has_role(doll_role_id) or member.has_role(doll2_role_id) or member.has_role(diva_role_id):
                if member.has_role(nice_girl_id):
                    await member.add_role(event.guild.get_role(verified_trans_role_id))
                    await member.add_role(event.guild.get_role(verified_doll_role_id))
                else:
                    await member.add_role(event.guild.get_role(verified_doll_role_id))
                    await member.remove_role(event.guild.get_role(verified_trans_role_id))
            else:
                await member.add_role(event.guild.get_role(verified_trans_role_id))
                await member.remove_role(event.guild.get_role(verified_doll_role_id))

    if member.has_role(doomer_role_id):
        # If member only has doomer or only has deathmatch role, dont do anything
        if len(member.roles) == 1 and member.has_role(doomer_role_id):
            return

        doomer_role = event.guild.get_role(doomer_role_id)

        # Remove all roles except the doomer role
        await member.edit(roles=[])
        await member.add_role(doomer_role)


# Member joins
@client.listen(MemberAdd)
async def on_guild_join(event: MemberAdd):
    sensitive = False
    logger.info(f"on_guild_join {event.member.display_name}")
    # Check if the member is a bot
    if event.member.bot:
        # Send a message to the log channel
        invite_log_channel = client.get_channel(invite_log_channel_id)
        await invite_log_channel.send(f"Bot added: <@{event.member.id}>")
        return
    
    # Check if the member has a forced nickname
    forced_nicknames = forced_nicknames_table.all()
    forced_nicknames = [item['user_id'] for item in forced_nicknames]
    if event.member.id in forced_nicknames:
        nickname = forced_nicknames_table.get(where('user_id') == event.member.id)['nickname']
        await event.member.edit(nickname=str(nickname))

    # To edit the member count channel
    human_members = [member for member in event.guild.members if not member.bot]

    # Check if the member had any roles before leaving
    try:
        member_roles = member_roles_table.get(where('user_id') == event.member.id)
    except json.decoder.JSONDecodeError as e:
        logger.error(f"member_roles_table_db.json is corrupted: {e}")
        member_roles = None
    if member_roles:
        roles = member_roles['roles']
        for role in roles:
            try:
                await event.member.add_role(event.guild.get_role(role))
            except:
                logger.error(f"Failed to add role {role} to {event.member.display_name}:")
                logger.error(traceback.format_exc())
        # set up announcement message
        logger.info(f"user {event.member.display_name} rejoined the server!")
        # by default send to verification channel
        send_channel = client.get_channel(unverified_channel_id)
        # add unverified role if they dont have public or selfies roles
        if not (event.member.has_role(public_all_role) or event.member.has_role(verified_doll_role_id) or event.member.has_role(verified_trans_role_id)):
            await event.member.add_role(event.guild.get_role(unverified_role_id))
            await send_channel.send(
                f"Welcome back <@{event.member.id}> !\nPlease wait until <@&{support_role}> helps you in <:society:1158917736534134834>")
        else:
            # Set up welcome message in main public chat
            send_channel = client.get_channel(monkey_channel_id)
            avatar_url = event.member.avatar_url
            embed = interactions.Embed(
                title=f"Member #{len(human_members)}",
                color=0x9c92d1,
            )
            embed.set_image(url=avatar_url)
            await send_channel.send(embed=embed, content=f"<@{event.member.id}> Rejoined the server!! <:society:1158917736534134834>")
    else:
        logger.info(f"user {event.member.display_name} joined for the first time!")
        # by default send to verification channel
        send_channel = client.get_channel(unverified_channel_id) 
        await event.member.add_role(event.guild.get_role(unverified_role_id))
        await send_channel.send(
            f"### Welcome to Trannerland <@{event.member.id}> !!\n"
            f"Please answer the following questions and <@&{support_role}> will help you in:\n"
            f"1) Where did you join from?\n"
            f"2) What is 1 thing you like about trans people? <:society:1158917736534134834>")

    # Create the join embed
    embed = interactions.Embed(
        color=0x9c92d1
    )
    embed.set_author(
        name=str(event.member.display_name),
        icon_url=event.member.avatar_url
    )
    embed.set_thumbnail(url=event.member.avatar_url)

    # Check which invite was used
    guild = client.get_guild(guild_id)
    invite_log_channel = client.get_channel(invite_log_channel_id)
    new_invites = await guild.fetch_invites()
    Invite = Query()
    for new_invite in new_invites:
        # Search for the invite in the database
        search = invites_table.search(Invite.code == new_invite.code)
        if search:
            old_uses = search[0]['uses']
            if new_invite.uses > old_uses:
                # Update the uses in the database
                invites_table.update({'uses': new_invite.uses}, Invite.code == new_invite.code)

                # if the invite is in sensitive_invites, give the new member role
                if sensitive_invites.search(Invite.code == new_invite.code):
                    sensitive = True
                    await event.member.add_role(event.guild.get_role(new_sus_member_role))
                    embed.description = f"<@{event.member.id}> joined from flagged invite: **{new_invite.code}**, assigned new member role, invited by <@{new_invite.inviter.id}>"
                    await invite_log_channel.send(embed=embed)

                else:
                    logger.info(f"<@{event.member.id}> joined from invite: {new_invite.code}")
                    embed.description = f"<@{event.member.id}> joined from invite: **{new_invite.code}, invited by <@{new_invite.inviter.id}>**"
                    await invite_log_channel.send(embed=embed)

                break
    else:
        logger.info(f"<@{event.member.id}> joined from vanity url")
        embed.description = f"<@{event.member.id}> joined from vanity url"
        await invite_log_channel.send(embed=embed)

    # Edit the member count channel
    member_count_channel = client.get_channel(member_count_channel_id)
    await member_count_channel.edit(name=f"Members: {len(human_members)}")

    # If member joined from a sensitive invite
    # if sensitive:
    #     # Wait 32 hours
    #     await asyncio.sleep(60 * 60 * 32)

    #     # Remove the new member role
    #     await event.member.remove_role(event.guild.get_role(new_sus_member_role))


# On member leave
@client.listen(MemberRemove)
async def on_guild_leave(event: MemberRemove):
    # Check if the member is a bot
    if event.member.bot:
        return

    # Log the members roles
    if event.member.roles:
        try:
            member_roles_table.insert({
            'user_id': event.member.id,
            'roles': [role.id for role in event.member.roles]
        })
        except json.decoder.JSONDecodeError as e:
            logger.error(f"member_roles_table_db.json is corrupted, cannot save roles: {e}")

    # Clean up gag table if user was gagged
    gagged_table.remove(where('user_id') == event.member.id)

    human_members = [member for member in event.guild.members if not member.bot]

    # Log the member leave in the invite log channel
    invite_log_channel = client.get_channel(invite_log_channel_id)
    embed = interactions.Embed(
        description=f"<@{event.member.id}> left the server.",
        color=0xff0000
    )
    embed.set_author(
        name=str(event.member.display_name),
        icon_url=event.member.avatar_url
    )
    embed.set_thumbnail(url=event.member.avatar_url)
    await invite_log_channel.send(embed=embed)

    # Edit the member count channel
    member_count_channel = client.get_channel(member_count_channel_id)
    await member_count_channel.edit(name=f"Members: {len(human_members)}")


# Member changes their nickname
@client.listen(MemberUpdate)
async def on_nickname_change(event: MemberUpdate):
    # check if the user is in forced_nicknames list from db
    forced_nicknames = forced_nicknames_table.all()
    forced_nicknames = [item['user_id'] for item in forced_nicknames]

    if event.after.id in forced_nicknames:
        nickname = forced_nicknames_table.get(where('user_id') == event.after.id)['nickname']
        if event.after.nick == nickname:
            # If the nickname was changed back to the forced nickname, do nothing
            return

        # Check if the nickname was changed within the last 1 minute
        mod_log_channel = client.get_channel(mod_log_channel_id)
        await mod_log_channel.send(
            f"<@{event.after.id}> tried to change their nickname to **{str(event.after.nick)}** but was reverted to **{str(nickname)}**. 😹")

        # Edit the nickname back to the specified nickname
        member = client.get_member(event.after.id, guild_id)
        await member.edit(nickname=str(nickname))


# All Slash Commands:
# Role Stats
@slash_command(name="demographic", description="See the demographic of the server.", scopes=[guild_id])
@slash_option(
    name="category",
    description="The type of demographic to get.",
    required=True,
    opt_type=OptionType.INTEGER,
    choices=[
        SlashCommandChoice(name="Gender", value=0),
        SlashCommandChoice(name="Sexuality", value=1),
        SlashCommandChoice(name="Archetype", value=3),
        SlashCommandChoice(name="Trans presentation", value=2),
        SlashCommandChoice(name="Time on HRT", value=6),
        SlashCommandChoice(name="Region", value=4),
    ]
)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def demographic_resp(ctx: interactions.SlashContext, category: int):
    # Fetch the onboarding roles
    role_ids = helpers.fetch_onboarding_roles(ctx.guild.id, prompt_index=category)

    # Get the corresponding name of each role
    roles = []
    for role in role_ids:
        # if no members in role skip
        member_count = len(ctx.guild.get_role(role).members)
        if member_count == 0:
            continue

        roles.append({
            "name": ctx.guild.get_role(role).name,
            "id": role,
            "color": helpers.decimal_to_hex(ctx.guild.get_role(role).color.value),
            "count": member_count
        })

    # Get all member objects for each role
    members = []
    for role in roles:
        members += ctx.guild.get_role(role["id"]).members

    # Now remove all duplicates
    members = list(dict.fromkeys(members))

    # Get the total number of members
    total_members = len(members)

    # Get the percentage of each role
    for role in roles:
        role['percentage'] = round((role['count'] / total_members) * 100, 2)

    # Sort the roles by percentage
    role_percentage = sorted(roles, key=lambda k: k['percentage'], reverse=True)

    # Create a cake chart
    sns.set(style="whitegrid")

    # Extract the names and percentages from the data
    labels = [item['name'] for item in role_percentage]
    sizes = [item['percentage'] for item in role_percentage]
    colors = [item['color'] for item in role_percentage]

    # Create a new figure object
    plt.figure(figsize=(10, 10))

    # Create the pie chart
    patches, texts, autotexts = plt.pie(
        sizes,
        labels=labels,
        autopct='%1.1f%%',
        startangle=140,
        colors=colors,
        textprops={'fontsize': 20, 'color': 'white', 'weight': 'bold'}  # Adjust the font properties here
    )

    # Equal aspect ratio ensures that pie is drawn as a circle
    plt.axis('equal')

    # Increase the size of the labels and percentages
    for text in texts:
        text.set_size(20)
    for autotext in autotexts:
        autotext.set_size(27)

    filename = "demographic.png"
    plt.savefig(filename, transparent=True)

    # Send the image in an embed
    embed = interactions.Embed(
        title="Demographic",
        color=0x9c92d1
    )
    embed.set_image(url="attachment://demographic.png")
    await ctx.send(embed=embed, file=interactions.File(filename, "demographic.png"), ephemeral=False)


# 1vs1
@slash_command(name="deathmatch", description="Create a deathmatch between two users.", scopes=[guild_id])
@slash_option(name="time", description="The time in minutes.", required=True, opt_type=OptionType.NUMBER)
@slash_option(name="user1", description="The first user.", required=True, opt_type=OptionType.USER)
@slash_option(name="user2", description="The second user.", required=True, opt_type=OptionType.USER)
@slash_option(name="user3", description="The third user.", required=False, opt_type=OptionType.USER)
@slash_option(name="user4", description="The fourth user.", required=False, opt_type=OptionType.USER)
@slash_option(name="user5", description="The fifth user.", required=False, opt_type=OptionType.USER)
async def deathmatch_resp(
        ctx: interactions.SlashContext,
        time: float,
        user1: interactions.User,
        user2: interactions.User,
        user3: interactions.User = None,
        user4: interactions.User = None,
        user5: interactions.User = None,
):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        try:
            await ctx.defer()

            # Generate a unique id for the deathmatch
            deathmatch_id = random.randint(100000, 999999)

            # Fetch the deathmatch role
            deathmatch_role = ctx.guild.get_role(deathmatch_role_id)
            users = [user for user in [user1, user2, user3, user4, user5] if user is not None]
            poll_reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

            for user in users:
                # Log the members roles in the deathmatch table
                deathmatch_table.insert({
                    'id': user.id,
                    'roles': [role.id for role in user.roles],  # log the roles of the user before the deathmatch
                    'deathmatch_id': deathmatch_id
                })

                # Remove all their roles
                await user.edit(roles=[])

                # Give them the deathmatch role
                await user.add_role(deathmatch_role)

            # Create a dynamic sentence based on the number of users (account for no comma before the last user)
            sentence = ", ".join([user.mention for user in users[:-1]]) + (
                " and " if len(users) > 1 else "") + users[-1].mention

            # Send the message
            embed = interactions.Embed(
                title="Deathmatch",
                description=f"{sentence} are now frotting for {time} minutes in {ctx.channel.mention}.",
                color=0x000000
            )
            # Add a button to end the deathmatch prematurely
            components = [
                [
                    Button(style=ButtonStyle.SECONDARY, emoji="❌", custom_id="end_deathmatch")
                ]
            ]
            deathmatch_msg = await ctx.send(embed=embed, components=components)
            #

            # Replace the deathmatch ID in the table with the message ID
            deathmatch_table.update({'deathmatch_id': deathmatch_msg.id}, where('deathmatch_id') == deathmatch_id)

            # Send the message in the deathmatch channel
            mod_log_channel = client.get_channel(mod_log_channel_id)
            await mod_log_channel.send(f"{ctx.author.mention} called a deathmatch {sentence} <a:plink:1158901270342541362>")

            # Send the message in the deathmatch channel
            deathmatch_channel = client.get_channel(deathmatch_channel_id)
            await deathmatch_channel.send(f"Fight {sentence} <a:plink:1158901270342541362>")

            # Sleep for the specified time
            await asyncio.sleep(time * 60)

            for user in users:
                # Remove the deathmatch role
                await user.remove_role(deathmatch_role)

                # Get the roles from the table
                user_roles = deathmatch_table.get(where('id') == user.id)['roles']

                # Filter the booster role because it causes missing permissions
                user_roles = [role for role in user_roles if role != booster_role]

                # Give them their previous roles back
                logger.info(f"User roles: {user_roles}")
                await user.edit(roles=user_roles)

            # Get the channel of the interaction
            channel = client.get_channel(ctx.channel_id)

            # Create the poll
            poll = await channel.send(
                embed=interactions.Embed(
                    title="Frotmatch Winner",
                    # All users in the poll
                    description=f"Who won the frotmatch?\n\n" + "\n\n".join(
                        [f"{poll_reactions[i]} {user.mention}" for i, user in enumerate(users)]),
                    color=0x9c92d1
                ),
            )
            for i, user in enumerate(users):
                await poll.add_reaction(poll_reactions[i])

            # Remove the entries for the deathmatch ID in the table
            deathmatch_table.remove(where('deathmatch_id') == deathmatch_id)

        except:
            logger.error(f"Error in deathmatch command:\n{traceback.format_exc()}")

    else:
        await ctx.send("You don't have the permission to use this command.", ephemeral=True)


# End deathmatch prematurely button
@component_callback("end_deathmatch")
async def end_deathmatch(ctx: interactions.ComponentContext):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        await ctx.defer()

        # Get the deathmatch ID
        deathmatch_id = deathmatch_table.get(where('deathmatch_id') == ctx.message.id)['deathmatch_id']

        deathmatch_role = ctx.guild.get_role(deathmatch_role_id)
        poll_reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

        # Get the users from the deathmatch table (the message id is the deathmatch id)
        users = deathmatch_table.search(where('deathmatch_id') == ctx.message.id)
        logger.info(f"Deathmatch users: {users}")

        # Edit the users roles
        for user_data in users:  # Renamed for clarity
            # Fetch user
            user = ctx.guild.get_member(user_data['id'])  # Access `id` as a dictionary key

            if user:  # Ensure the user exists in the guild
                # Remove the deathmatch role
                await user.remove_role(deathmatch_role)

                # Get the roles from the table
                user_roles = deathmatch_table.get(where('id') == user.id)['roles']

                # Filter the booster role because it causes missing permissions
                user_roles = [role for role in user_roles if role != booster_role]

                # Give them their previous roles back
                logger.info(f"User roles: {user_roles}")
                await user.edit(roles=user_roles)

        # Create the poll
        channel = client.get_channel(ctx.channel_id)
        poll = await channel.send(
            embed=interactions.Embed(
                title="Frotmatch Winner",
                # All users in the poll
                description=f"Who won the frotmatch?\n\n" +
                            "\n\n".join(
                                [f"{poll_reactions[i]} <@{user_data['id']}>" for i, user_data in enumerate(users)]),
                color=0x9c92d1
            ),
        )
        for i, user in enumerate(users):
            await poll.add_reaction(poll_reactions[i])

        # Remove the entries for the deathmatch ID in the table
        deathmatch_table.remove(where('deathmatch_id') == deathmatch_id)

    else:
        await ctx.send("You don't have the permission to use this command.", ephemeral=True)


@slash_command(name="tagteam", description="Toss another poster into the fight.", scopes=[guild_id])
@slash_option(name="time", description="The time in minutes.", required=True, opt_type=OptionType.NUMBER)
@slash_option(name="user", description="The user to join frot arena.", required=True, opt_type=OptionType.USER)
async def tagteam_resp(
        ctx: interactions.SlashContext,
        time: float,
        user: interactions.User
):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        try:
            await ctx.defer()

            # Fetch the deathmatch role
            deathmatch_role = ctx.guild.get_role(deathmatch_role_id)

            # save their existing roles
            old_roles = [role.id for role in user.roles]

            # Remove all their roles
            await user.edit(roles=[])

            # Give them the deathmatch role
            await user.add_role(deathmatch_role)

            # Create a dynamic sentence based on the number of users (account for no comma before the last user)
            sentence = f"{user.mention} has joined the fight!"

            # Send the message in the deathmatch channel
            mod_log_channel = client.get_channel(mod_log_channel_id)
            await mod_log_channel.send(f"{ctx.author.mention} added {user.mention} to the deathmatch <a:plink:1158901270342541362>")

            # Send the message in the deathmatch channel
            deathmatch_channel = client.get_channel(deathmatch_channel_id)
            await deathmatch_channel.send(f" {sentence} <a:plink:1158901270342541362>")

            await ctx.send(f"{user.mention} has been added to the deathmatch for {time} minutes.", ephemeral=True)
            # Sleep for the specified time
            await asyncio.sleep(time * 60)

            # Remove the deathmatch role
            await user.remove_role(deathmatch_role)

            # Filter the booster role because it causes missing permissions
            old_roles = [role for role in old_roles if role != booster_role]

            # Give them their previous roles back
            logger.info(f"User roles: {old_roles}")
            await user.edit(roles=old_roles)

        except:
            logger.error(f"Error in deathmatch command:\n{traceback.format_exc()}")

    else:
        await ctx.send("You don't have the permission to use this command.", ephemeral=True)




# Media time out members
@slash_command(name="mutemedia", description="Media timeout a user.", scopes=[guild_id])
@slash_option(name="user", description="The user to timeout.", required=True, opt_type=OptionType.USER)
@slash_option(name="time", description="The time in minutes.", required=True, opt_type=OptionType.NUMBER)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def mutemedia_resp(ctx: interactions.SlashContext, user: interactions.User, time: float):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        await ctx.defer(ephemeral=True)

        # Give the user the timeout role
        await user.add_role(ctx.guild.get_role(media_timeout_role))
        await ctx.send(f"{user.mention} has been media timed out for {time} minutes.", ephemeral=True)
        await asyncio.sleep(time * 60)
        await user.remove_role(ctx.guild.get_role(media_timeout_role))

    else:
        await ctx.send("You don't have the permission to use this command.", ephemeral=True)


# Convert feet to meters or meters to feet
@slash_command(name="height", description="Convert height to meters or to feet.", scopes=[guild_id])
@slash_option(name="value", description="The feet or centimeters to convert. E.g: 5'10 or 177cm",
              required=True, opt_type=OptionType.STRING)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def height_resp(ctx: interactions.SlashContext, value: str):
    if "'" in value:  # Feet and inches input
        feet, inches = map(int, value.split("'"))
        total_inches = feet * 12 + inches
        cm = total_inches * 2.54

        await ctx.send(f"{value} feet is {cm}cm", ephemeral=False)

    # if regex numbers
    elif re.match(r"^\d+cm$", value):
        cm_value = float(value.split("cm")[0])
        total_inches = cm_value / 2.54
        feet = int(total_inches // 12)
        inches = round(total_inches % 12)  # Rounding the inches

        await ctx.send(f"{value} is {feet}'{inches}", ephemeral=False)

    else:
        await ctx.send("Invalid input format", ephemeral=True)


# Inch to cm
@slash_command(name="inch_to_cm", description="Convert inches to centimeters.", scopes=[guild_id])
@slash_option(name="inch", description="The inches to convert.", required=True, opt_type=OptionType.NUMBER)
async def inch_to_cm_resp(ctx: interactions.SlashContext, inch: float):
    # Convert inches to cm
    cm = inch * 2.54
    # Round it
    cm = round(cm, 2)
    await ctx.send(f"{inch} inches is {cm}cm", ephemeral=False)


# cm to inch
@slash_command(name="cm_to_inch", description="Convert centimeters to inches.", scopes=[guild_id])
@slash_option(name="cm", description="The centimeters to convert.", required=True, opt_type=OptionType.NUMBER)
async def cm_to_inch_resp(ctx: interactions.SlashContext, cm: float):
    # Convert cm to inches
    inch = cm / 2.54
    # Round it
    inch = round(inch, 2)
    await ctx.send(f"{cm}cm is {inch} inches", ephemeral=False)


# Convert kg to lbs or lbs to kg
@slash_command(name="weight", description="Convert weight to kg or to lbs.", scopes=[guild_id])
@slash_option(name="value", description="The kg or lbs to convert. Example: 70kg or 154lbs", required=True,
              opt_type=OptionType.STRING)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def weight_resp(ctx: interactions.SlashContext, value: str):
    if "kg" in value:
        kg = float(value.split('kg')[0])
        lbs = kg * 2.205
        # Round it
        lbs = round(lbs, 2)
        await ctx.send(f"{value} is {lbs}lbs", ephemeral=False)

    elif "lbs" in value:
        lbs = float(value.split('lbs')[0])
        kg = lbs / 2.205
        # Round it
        kg = round(kg, 2)
        await ctx.send(f"{value} is {kg}kg", ephemeral=False)


# Give recommended hormone ranges
# https://transfemscience.org/articles/transfem-intro/#normal-hormone-levels
# https://upload.wikimedia.org/wikipedia/commons/d/db/Blood_values_for_print.png
@slash_command(name="hormone_ranges", description="Show recommended range for sex hormones during transition",
               scopes=[guild_id])
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def hormone_ranges(ctx: interactions.SlashContext):
    output = (
            "**Trans women**\n" +
            "Estradiol: 100 to 200 pg/mL (367-734 pmol/L)\n" +
            "Estradiol monotherapy: 200 to 300 (734-1101 pmol/L)\n" +
            "Testosterone (total): <50 ng/dL (1.7 nmol/L)\n\n" +
            "**Trans men**\n" +
            "Testosterone (total): 400 to 1000 ng/dL (13.8-34.6 nmol/L)\n"
    )

    embed = interactions.Embed(
        title="Hormone Ranges",
        description=output,
        color=0x9c92d1
    )
    file = interactions.File("common/Blood_values_sorted_by_mass_and_molar_concentration.jpg")
    embed.add_image(image="attachment://Blood_values_sorted_by_mass_and_molar_concentration.jpg")

    await ctx.send(embed=embed, files=[file])


# Convert common sex hormone measurements
# pg/mL is pico-gram per milli-liter which is weight/volume
# pmol/L is pico-mole per liter which is moles/volume aka molarity
# supports converting from any combination to any combination
@slash_command(name="hormone_convert", description="Convert weight or moles per volume measurement to different units",
               scopes=[guild_id])
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
@slash_option(
    name="hormone",
    description="which sex hormone to calculate",
    required=True,
    opt_type=OptionType.STRING,
    choices=[
        SlashCommandChoice(name="estrogen (e2)", value="estradiol"),
        SlashCommandChoice(name="testosterone", value="testosterone"),
        SlashCommandChoice(name="progesterone (p4)", value="progesterone"),
        SlashCommandChoice(name="DHT", value="dht")
    ]
)
@slash_option(
    name="initial_number",
    description="numeric value of the initial measurement",
    required=True,
    opt_type=OptionType.NUMBER
)
@slash_option(
    name="convert_from",
    description="weight or moles per volume unit you start with",
    required=True,
    opt_type=OptionType.STRING,
    choices=[
        SlashCommandChoice(name="pmol/L", value="pmol/L"),
        SlashCommandChoice(name="nmol/L", value="nmol/L"),
        SlashCommandChoice(name="umol/L", value="umol/L"),
        SlashCommandChoice(name="pg/mL", value="pg/mL"),
        SlashCommandChoice(name="ng/L", value="ng/L"),
        SlashCommandChoice(name="ng/mL", value="ng/mL"),
        SlashCommandChoice(name="ng/dL", value="ng/dL"),
        SlashCommandChoice(name="ug/L", value="ug/L"),
        SlashCommandChoice(name="ug/dL", value="ug/dL")
    ]
)
@slash_option(
    name="convert_to",
    description="weight or moles per volume unit you are converting to",
    required=True,
    opt_type=OptionType.STRING,
    choices=[
        SlashCommandChoice(name="pmol/L", value="pmol/L"),
        SlashCommandChoice(name="nmol/L", value="nmol/L"),
        SlashCommandChoice(name="umol/L", value="umol/L"),
        SlashCommandChoice(name="pg/mL", value="pg/mL"),
        SlashCommandChoice(name="ng/L", value="ng/L"),
        SlashCommandChoice(name="ng/mL", value="ng/mL"),
        SlashCommandChoice(name="ng/dL", value="ng/dL"),
        SlashCommandChoice(name="ug/L", value="ug/L"),
        SlashCommandChoice(name="ug/dL", value="ug/dL")
    ]
)
async def convert_hormone_measurement(ctx: interactions.SlashContext, hormone: str, initial_number: float,
                                      convert_from: str, convert_to: str):
    molecular_weights = {
        'estradiol': 272.38,
        'testosterone': 288.42,
        'progesterone': 314.46,
        'dht': 290.44
    }
    volume_conversion = {
        'L': 1,
        'dL': 1e-1,
        'mL': 1e-3,
        'uL': 1e-6
    }
    weight_conversion = {
        'pg': 1e-12,
        'ng': 1e-9,
        'ug': 1e-6,
        'mg': 1e-3,
        'g': 1
    }
    mole_conversion = {
        'pmol': 1e-12,
        'nmol': 1e-9,
        'umol': 1e-6,
        'mmol': 1e-3,
        'mol': 1
    }

    convert_from_unit = convert_from.split("/")[0]
    convert_from_volume = convert_from.split("/")[1]
    convert_to_unit = convert_to.split("/")[0]
    convert_to_volume = convert_to.split("/")[1]

    # Convert initial value to moles
    if convert_from_unit in weight_conversion:
        initial_moles = ((float(initial_number) * weight_conversion[convert_from_unit]) / molecular_weights[hormone]) / \
                        volume_conversion[convert_from_volume]
    else:
        initial_moles = float(initial_number) * mole_conversion[convert_from_unit]

    # Calculate final value in specified unit
    if convert_to_unit in weight_conversion:
        final_value = (initial_moles * molecular_weights[hormone]) / (
                weight_conversion[convert_to_unit] / volume_conversion[convert_to_volume])
    else:
        final_value = round((initial_moles * volume_conversion[convert_to_volume]) / mole_conversion[convert_to_unit], 2)

    await ctx.send(
        f"{hormone} in {initial_number} {convert_from_unit}/{convert_from_volume} is {final_value} {convert_to_unit}/{convert_to_volume}",
        ephemeral=False)


# Urban dictionary with buttons
@slash_command(name="urban", description="Search the urban dictionary.", scopes=[guild_id])
@slash_option(name="term", description="The term to search.", required=True, opt_type=OptionType.STRING)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def urban_resp(ctx: interactions.SlashContext, term: str):
    # Get the results
    result = urban.search(term, index=0)

    # If there is no definition
    if result is None:
        await ctx.send(f"No definition found for {term}", ephemeral=True)
        return

    # Create the embed
    embed = interactions.Embed(
        title=term,
        url=result['permalink'],
        description=result['definition'] + '\n\n' + result.get('example', ''),
        color=0x9c92d1
    )
    embed.set_footer(text=f"ðŸ‘ {result['thumbs_up']} | ðŸ‘Ž {result['thumbs_down']} | Result {1}")

    # Add the next and previous buttons
    components = [
        [
            Button(style=ButtonStyle.PRIMARY, emoji="â¬…ï¸", custom_id="previous", disabled=True),
            Button(style=ButtonStyle.PRIMARY, emoji="âž¡ï¸", custom_id="next")
        ]
    ]

    # Send the embed
    await ctx.send(embed=embed, components=components)


# Urban dictionary buttons
@component_callback("previous")
async def previous_callback(ctx: interactions.ComponentContext):
    # Only let the user who sent the command use the buttons
    if ctx.author.id != ctx.message.interaction.user.id:
        await ctx.respond(content="You can't use this button.", ephemeral=True)
        return

    # Get the results
    term = ctx.message.embeds[0].title
    index = int(ctx.message.embeds[0].footer.text.split('| Result ')[-1]) - 2
    result = urban.search(term, index=index)

    # If there is no definition
    if result is None:
        await ctx.respond(content=f"No more definitions found for {term}", ephemeral=True)
        return

    # Create the embed
    embed = interactions.Embed(
        title=term,
        url=result['permalink'],
        description=result['definition'] + '\n\n' + result.get('example', ''),
        color=0x9c92d1
    )
    embed.set_footer(text=f"ðŸ‘ {result['thumbs_up']} | ðŸ‘Ž {result['thumbs_down']} | Result {index + 1}")

    # Add the next and previous buttons
    components = [
        [
            Button(style=ButtonStyle.PRIMARY, emoji="â¬…ï¸", custom_id="previous", disabled=True if index == 0 else False),
            Button(style=ButtonStyle.PRIMARY, emoji="âž¡ï¸", custom_id="next")
        ]
    ]

    # Send the embed
    await ctx.edit_origin(embed=embed, components=components)


# Urban dictionary buttons
@component_callback("next")
async def next_callback(ctx: interactions.ComponentContext):
    # Only let the user who sent the command use the buttons
    if ctx.author.id != ctx.message.interaction.user.id:
        await ctx.respond(content="You can't use this button.", ephemeral=True)
        return

    # Get the results
    term = ctx.message.embeds[0].title
    index = int(ctx.message.embeds[0].footer.text.split('| Result ')[-1])
    result = urban.search(term, index=index)

    # If there is no definition
    if result is None:
        await ctx.respond(content=f"No more definitions found for {term}", ephemeral=True)
        return

    # Create the embed
    embed = interactions.Embed(
        title=term,
        url=result['permalink'],
        description=result['definition'] + '\n\n' + result.get('example', ''),
        color=0x9c92d1
    )
    embed.set_footer(text=f"👍 {result['thumbs_up']} | 👎 {result['thumbs_down']} | Result {index + 1}")

    # Add the next and previous buttons
    components = [
        [
            Button(style=ButtonStyle.PRIMARY, emoji="⬅️", custom_id="previous"),
            Button(style=ButtonStyle.PRIMARY, emoji="➡️", custom_id="next")
        ]
    ]

    # Send the embed
    await ctx.edit_origin(embed=embed, components=components)

# Remove a user from the slowed list
@slash_command(name="unslow", description="Unslow a member.", scopes=[guild_id])
@slash_option(name="user", description="The member to unslow.", required=True, opt_type=OptionType.USER)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def unslow_resp(ctx: interactions.SlashContext, user: interactions.Member):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        # If the user is not slowed
        if not slowed_members_table.get(where('user_id') == user.id):
            await ctx.send(f"{user.mention} is not slowed", ephemeral=True)
            return

        # Remove the user from the slowed list
        slowed_members_table.remove(where('user_id') == user.id)

        # Send the message
        await ctx.send(f"{user.mention} is no longer slowed.", ephemeral=True)
        logger.info(f"{user.username} has been unslowed.")


@slash_command(name="sauce", description="Reverse image search.", scopes=[guild_id])
@slash_option(name="image_url", description="The url of the image.", required=False, opt_type=OptionType.STRING)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def sauce_resp(ctx: interactions.SlashContext, image_url: str = None):
    await ctx.defer(ephemeral=False)

    # If there is no image url provided take the last attachment in the channel
    if not image_url:
        channel_id = ctx.channel_id
        channel = client.get_channel(channel_id)
        messages = await channel.fetch_messages()

        # Get all messages with an image
        try:
            for message in messages:
                if message.attachments:
                    image_url = message.attachments[0].url
                    break

                elif message.embeds:
                    if message.embeds[0].image:
                        image_url = message.embeds[0].image.url
                        break

                    elif message.embeds[0].thumbnail:
                        image_url = message.embeds[0].thumbnail.url
                        break

        except:
            pass

    # print('Found image url: ', image_url)
    # If there is still no image url
    if not image_url:
        await ctx.send("Please provide an image url or attach an image.", ephemeral=True)
        return

    try:
        upload_data = yandex.upload(
            image_url
        )
        search_result = yandex.search(
            url=upload_data['url'],
            ID=f"{upload_data['image_shard']}/{upload_data['image_id']}"
        )

    except yandex.ImageDownloadError:
        await ctx.send("Failed to download image. Please download the image and upload it directly.", ephemeral=True)
        return
    except:
        await ctx.send("An error occured. Please try again.", ephemeral=True)
        return

    # Create an embed for each result
    embeds = []
    for result in search_result[:6]:
        embed = interactions.Embed(
            title=result['title'],
            description=result['url'],
            thumbnail=result['thumbnail'],
            color=0x9c92d1
        )
        embeds.append(embed)

    await ctx.send(content=f"**Image Search Results**", embeds=embeds, ephemeral=False)

# Slow down a user
@slash_command(name="slow", description="Lets a member to only send messages within a specific interval.",
               scopes=[guild_id])
@slash_option(name="user", description="The member to slow.", required=True, opt_type=OptionType.USER)
@slash_option(name="minutes", description="How long the member will be slowed for. (minutes)", required=True,
              opt_type=OptionType.INTEGER)
@slash_option(name="interval", description="How long between each message. (seconds)", required=True,
              opt_type=OptionType.INTEGER)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def slow_resp(ctx: interactions.SlashContext, user: interactions.Member, minutes: int, interval: int):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        # If the user is already slowed
        if slowed_members_table.get(where('user_id') == user.id):
            await ctx.send(f"{user.mention} is already slowed", ephemeral=True)
            return

        # Add the user to the slowed table
        slowed_members_table.insert({
            "user_id": user.id,
            "duration_minutes": minutes,
            "interval_seconds": interval,
        })

        # Send the message
        await ctx.send(
            f"{user.mention} is now slowed for **{minutes} minutes** with a **{interval} second** interval between each message.",
            ephemeral=True)

        # Wait the duration
        await asyncio.sleep(minutes * 60)

        # Remove the user from the slowed list
        slowed_members_table.remove(where('user_id') == user.id)


# oxford dictionary with buttons
@slash_command(name="definition", description="Search the oxford dictionary.", scopes=[guild_id])
@slash_option(name="term", description="The term to search.", required=True, opt_type=OptionType.STRING)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def oxford_resp(ctx: interactions.SlashContext, term: str):
    # Get the results
    result = oxford.search(term)

    # If there is no definition
    if result is None:
        await ctx.send(f"No definition found for {term}", ephemeral=True)
        return

    # Create the embed
    formatted_description = f"# [{result['headword']}]({result['url']})"
    if result['pos']:
        formatted_description += f"\n*{result['pos']}*"
    if result['phonetic']:
        formatted_description += f"\n{result['phonetic']}"
    if result['grammar']:
        formatted_description += f"\n{result['grammar']}"
    if result['subj']:
        formatted_description += f" (*{result['subj']}*)"
    if result['definition']:
        formatted_description += f"\n**{result['definition']}**"
    if result['reference']:
        formatted_description += f"\nSimilar to: {result['reference']}"

    embed = interactions.Embed(
        # title=f"# {result['headword']} {result['pos']}",
        url=result['url'],
        description=formatted_description,
        color=0x9c92d1
    )
    # embed.set_footer(text=f"ðŸ‘ {result['thumbs_up']} | ðŸ‘Ž {result['thumbs_down']} | Result {1}")

    # Send the embed
    await ctx.send(embed=embed, ephemeral=False)


# Add an invite code to sensitive invites in db
@slash_command(name="flag_invite", description="Add an invite code to the flagged invites list.", scopes=[guild_id])
@slash_option(name="code", description="The invite code to add.", required=True, opt_type=OptionType.STRING)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def flag_invite_resp(ctx: interactions.SlashContext, code: str):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        # Add the invite code to the database
        sensitive_invites.insert({'code': code})

        logger.info(f"Added {code} to the sensitive invite list.")
        await ctx.send(f"**{code}** has been added to the sensitive invite list.", ephemeral=True)


# Command to add user to forced_nicknames
@slash_command(name="force_nickname", description="Prevent a user from changing their nickname.", scopes=[guild_id])
@slash_option(name="user", description="The user to add.", required=True, opt_type=OptionType.USER)
@slash_option(name="nickname", description="The nickname to give the user.", required=True, opt_type=OptionType.STRING)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def force_nickname_resp(ctx: interactions.SlashContext, user: interactions.Member, nickname: str):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        # If the user is already in the database
        if forced_nicknames_table.contains(where('user_id') == user.id):
            # If the nickname is different than the one in the database update it
            if forced_nicknames_table.get(where('user_id') == user.id)['nickname'] != nickname:
                forced_nicknames_table.update({'nickname': str(nickname)}, where('user_id') == user.id)
                logger.info(f"Updated {user.id} in the forced nicknames list with nickname {nickname}.")
                # Rename the user
                await user.edit(nickname=str(nickname))
                await ctx.send(
                    f"{user.mention} has been updated in the forced nicknames list with nickname **{str(nickname)}**.",
                    ephemeral=True)
                return

            else:
                await ctx.send(f"{user.mention} is already in the forced nicknames list.", ephemeral=True)
                return

        # Add the user to the database
        forced_nicknames_table.insert({'user_id': user.id, 'nickname': str(nickname)})

        logger.info(f"Added {user.id} to the forced nicknames list with nickname {nickname}.")
        # Rename the user
        await user.edit(nickname=nickname)
        await ctx.send(f"{user.mention} has been added to the forced nicknames list with nickname **{nickname}**.",
                       ephemeral=True)


# Command to remove user from forced_nicknames
@slash_command(name="unforce_nickname", description="Allow a user to change their nickname.", scopes=[guild_id])
@slash_option(name="user", description="The user to remove.", required=True, opt_type=OptionType.USER)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def unforce_nickname_resp(ctx: interactions.SlashContext, user: interactions.Member):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        # Remove the user from the database
        removed = forced_nicknames_table.remove(where('user_id') == user.id)
        if not removed:
            await ctx.send(f"{user.mention} is not in the forced nicknames list.", ephemeral=True)
            return

        logger.info(f"Removed {user.id} from the forced nicknames list.")
        # Remove the nickname
        await user.edit(nickname=None)
        await ctx.send(f"{user.mention} has been removed from the forced nicknames list.", ephemeral=True)


# Restricts someone to dooming channel only.
@slash_command(name="restrictdoomer", description="Restricts someone to dooming channel only.", scopes=[guild_id])
@slash_option(name="user", description="The user to restrict.", required=True, opt_type=OptionType.USER)
@slash_option(name="duration", description="The duration of the restriction in minutes.", required=True,
              opt_type=OptionType.INTEGER)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def restrict_doomer_resp(ctx: interactions.SlashContext, user: interactions.Member, duration: int):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        # If the user is already restricted
        if doomers_table.contains(where('user_id') == user.id):
            await ctx.send(f"{user.mention} is already restricted to <#{dooming_channel_id}>.", ephemeral=True)
            return

        doomer_role = ctx.guild.get_role(doomer_role_id)

        user_roles = []
        # Save the current roles of the user
        user_roles += [role.id for role in user.roles]

        # Remove all their roles
        for role in user.roles:
            try:
                await user.remove_role(role)
            except:
                logger.error(f"Error removing role {role} from {user.mention}")

        # Give them the doomer role
        await user.add_role(doomer_role)

        # Add the user to the restricted doomers list
        doomers_table.insert({'user_id': user.id, 'duration': duration, 'roles': user_roles})

        # Send the message
        await ctx.send(f"{user.mention} is now imprisoned in <#{dooming_channel_id}> channel for {duration} minutes.",
                       ephemeral=False)

        # Wait the duration
        await asyncio.sleep(duration * 60)

        # Remove the user from the restricted doomers list
        doomers_table.remove(where('user_id') == user.id)

        # Remove the doomer role and restore previous roles
        # The user may have left the server during the sleep, so wrap in try-except
        try:
            await user.remove_role(doomer_role)

            # Filter the booster role because it causes missing permissions
            user_roles = [role for role in user_roles if role != booster_role]

            # Give them their previous roles back
            for role_id in user_roles:
                try:
                    role = ctx.guild.get_role(role_id)
                    await user.add_role(role)

                except:
                    logger.error(f"Error adding role {role_id} back to {user.mention}")
        except Exception as e:
            logger.warning(f"Could not restore roles for user {user.id} (they may have left the server): {e}")


@slash_command(name="unrestrictdoomer", description="Unrestricts someone from dooming channel only.", scopes=[guild_id])
@slash_option(name="user", description="The user to unrestrict.", required=True, opt_type=OptionType.USER)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def unrestrict_doomer_resp(ctx: interactions.SlashContext, user: interactions.Member):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        # If the user is not restricted
        if not doomers_table.get(where('user_id') == user.id):
            await ctx.send(f"{user.mention} is not restricted to <#{dooming_channel_id}>.", ephemeral=True)
            return

        # Remove the user from the restricted doomers list
        doomers_table.remove(where('user_id') == user.id)

        # Remove the doomer role
        doomer_role = ctx.guild.get_role(doomer_role_id)
        await user.remove_role(doomer_role)

        user_roles = doomers_table.get(where('user_id') == user.id)['roles']

        # Filter the booster role because it causes missing permissions
        user_roles = [role for role in user_roles if role != booster_role]

        # Give them their previous roles back
        for role_id in user_roles:
            try:
                role = ctx.guild.get_role(role_id)
                await user.add_role(role)

            except:
                logger.error(f"Error adding role {role_id} back to {user.mention}")

        logger.info(f"{user.username} has been freed from <#{dooming_channel_id}>.")


# Verify command for mods
@slash_command(name="verify", description="Verify a user.", scopes=[guild_id])
@slash_option(name="user", description="The user to verify.", required=True, opt_type=OptionType.USER)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def verify_resp(ctx: interactions.SlashContext, user: interactions.Member):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        # If the user is already verified
        if user in ctx.guild.get_role(public_all_role).members:
            await ctx.send(f"{user.mention} already has access", ephemeral=True)
            return
        
        # Always give the public/cis/all verified role
        await user.add_role(ctx.guild.get_role(public_all_role))
        if user.has_role(tranner_role) or user.has_role(pooner_role) or user.has_role(enby_role):
            # Give the trans specific verified role
            await user.add_role(ctx.guild.get_role(public_trans_role))    
        
        # Remove the unverified role
        if user in ctx.guild.get_role(unverified_role_id).members:
            await user.remove_role(ctx.guild.get_role(unverified_role_id))

        # Determine if user is new or returning
        # Users only get added to member_roles_table when they leave, so if they're in it they're returning
        is_returning_user = member_roles_table.get(where('user_id') == user.id) is not None

        # Set up welcome message
        avatar_url = user.avatar_url
        human_members = [member for member in ctx.guild.members if not member.bot]
        embed = interactions.Embed(
            title=f"Member #{len(human_members)}",
            color=0x9c92d1,
        )
        embed.set_image(url=avatar_url)
        send_channel = client.get_channel(monkey_channel_id)

        if is_returning_user:
            await send_channel.send(embed=embed, content=f"Welcome back <@{user.id}> ! <:society:1158917736534134834>")
        else:
            await send_channel.send(embed=embed, content=f"### Welcome new member <@{user.id}> !! <:society:1158917736534134834>\n"
                                    f"grab more roles and channels here <id:customize>")

        # Send the log message
        await ctx.send(f"{user.mention} now has access to the server", ephemeral=True)
        logger.info(f"{user.username} now has access to the server")
    else:
        await ctx.send(f"You can't use the verify command!", ephemeral=True)
        logger.info(f"{user.username} non-moderator user tried to use verify command")

# Command to make a highlight not deletable even by the original author
@slash_command(name="immortalize_highlight", description="Make a highlight not deletable.", scopes=[guild_id])
@slash_option(name="highlight_id", description="The message id of the highlight.", required=True,
              opt_type=OptionType.STRING)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def immortalize_highlight_resp(ctx: interactions.SlashContext, highlight_id: str):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        # Convert the highlight id to int
        highlight_id = int(highlight_id)

        # Check if the highlight exists
        if not highlights_table.get(where('highlight_id') == highlight_id):
            await ctx.send("The highlight does not exist.", ephemeral=True)
            return

        # Check in the highlights table if immortalized
        if highlights_table.get(where('highlight_id') == highlight_id).get('immortalized'):
            await ctx.send("The highlight is already immortalized.", ephemeral=True)
            return

        # Edit the highlight in the highlights table
        highlights_table.update({'immortalized': True}, where('highlight_id') == highlight_id)

        # Remove the components on the highlight message
        channel = client.get_channel(highlights_channel_id)
        message = await channel.fetch_message(highlight_id)
        await message.edit(components=[])

        # Send the message
        await ctx.send(
            f"Immortalized highlight https://discord.com/channels/{guild_id}/{highlights_channel_id}/{highlight_id}",
            ephemeral=True)
        logger.info(
            f"Immortalized highlight https://discord.com/channels/{guild_id}/{highlights_channel_id}/{highlight_id}")


# Forced gender command - adds a user to the forced gender table
@slash_command(name="force_gender", description="Prevents a member from changing their gender role.", scopes=[guild_id])
@slash_option(name="user", description="The member.", required=True, opt_type=OptionType.USER)
@slash_option(name="role", description="The gender to force on the member.", required=True, opt_type=OptionType.ROLE)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def force_role_resp(ctx: interactions.SlashContext, user: interactions.Member, role: interactions.Role):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        # Check if the role is a gender role
        if role.id not in gender_roles:
            await ctx.send(f"{role.mention} is not a gender role!", ephemeral=True)

        # If the user is already in the forced gender table
        if forced_gender_table.get(where('user_id') == user.id):
            await ctx.send(f"{user.mention} is already in the forced gender list.", ephemeral=True)
            return

        # Add the user to the forced gender table
        forced_gender_table.insert({'user_id': user.id, 'role_id': role.id})

        # Send the message
        await ctx.send(f"{user.mention} has been added to the forced gender list.", ephemeral=True)


# Remove a user from the forced gender list
@slash_command(name="unforce_gender", description="Allow a user to change their gender again.", scopes=[guild_id])
@slash_option(name="user", description="The member.", required=True, opt_type=OptionType.USER)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def unforce_role_resp(ctx: interactions.SlashContext, user: interactions.Member):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        # If the user is not in the forced gender table
        if not forced_gender_table.contains(where('user_id') == user.id):
            await ctx.send(f"{user.mention} is not in the forced gender list.", ephemeral=True)
            return

        # Remove the user from the forced gender table
        forced_gender_table.remove(where('user_id') == user.id)
        await ctx.send(f"{user.mention} has been removed from the forced gender list.", ephemeral=True)


# For all users, if they have role A, give them role B
@slash_command(name="add_role_if_role", description="For all users if have 1st role, give them 2nd role",
               scopes=[guild_id])
@slash_option(name="role1", description="the 1st role", required=True, opt_type=OptionType.ROLE)
@slash_option(name="role2", description="the new role to assign", required=True, opt_type=OptionType.ROLE)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def add_role_if_role(ctx: interactions.SlashContext, role1: interactions.Role, role2: interactions.Role):
    if ctx.author.has_role(admin_role):
        # Get all member objects for each role
        members = ctx.guild.get_role(role1.id).members
        for member in members:
            await member.add_role(role2)

    else:
        await ctx.send("Admin-only action", ephemeral=True)
        return


# For all users, if they have both roles A *and* B, give them role C
@slash_command(name="add_role_if_combo", description="For all users if have 1st and 2nd role, give 3rd role",
               scopes=[guild_id])
@slash_option(name="role1", description="the 1st role", required=True, opt_type=OptionType.ROLE)
@slash_option(name="role2", description="the 2nd role", required=True, opt_type=OptionType.ROLE)
@slash_option(name="role3", description="the new role to assign", required=True, opt_type=OptionType.ROLE)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def add_role_if_combo(ctx: interactions.SlashContext, role1: interactions.Role, role2: interactions.Role,
                            role3: interactions.Role):
    if ctx.author.has_role(admin_role):
        # Get all member objects for each role
        members = ctx.guild.get_role(role1.id).members
        for member in members:
            if member.has_role(role2.id):
                await member.add_role(role3)

    else:
        await ctx.send("Admin-only action", ephemeral=True)
        return


# Command to highlight a message manually
@slash_command(name="highlight", description="Highlight a message.", scopes=[guild_id])
@slash_option(name="message_id", description="The message to highlight.", required=True, opt_type=OptionType.STRING)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def highlight_message(ctx: interactions.SlashContext, message_id: str):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        # Convert the message id to int
        message_id = int(message_id)

        # Check if the message exists
        try:
            message = await ctx.channel.fetch_message(message_id)
        except:
            await ctx.send("The message does not exist.", ephemeral=True)
            return

        # Check if the message is already highlighted
        if highlights_table.get(where('highlight_id') == message_id):
            await ctx.send("The message is already highlighted.", ephemeral=True)
            return

        # Add the message to the highlights table
        highlights_table.insert({'highlight_id': message_id, 'immortalized': False})

        # Add the components to the message
        components = [
            Button(style=ButtonStyle.DANGER, label="Delete", custom_id="delete_highlight"),
            Button(style=ButtonStyle.PRIMARY, label="Immortalize", custom_id="immortalize_highlight")
        ]
        await message.edit(components=components)

        # Send the message
        await ctx.send(f"Highlighted message https://discord.com/channels/{guild_id}/{ctx.channel_id}/{message_id}",
                       ephemeral=True)
        logger.info(f"Highlighted message https://discord.com/channels/{guild_id}/{ctx.channel_id}/{message_id}")


# bmi calculator with metric and imperial units
@slash_command(name="bmi", description="Calculate your BMI.", scopes=[guild_id])
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
@slash_option(name="weight", description="Your weight. (e.g. 70/140)", required=True, opt_type=OptionType.INTEGER)
@slash_option(name="height", description="Your height. (e.g. 6'2/187)", required=True, opt_type=OptionType.STRING)
@slash_option(name="unit", description="The unit of measurement.", required=True, opt_type=OptionType.STRING,
              choices=[
                  SlashCommandChoice(name="metric", value="metric"),
                  SlashCommandChoice(name="imperial", value="imperial")
              ])
async def bmi_calc(ctx: interactions.SlashContext, weight: int, height: str, unit: str):
    if unit == "metric":
        height = int(height)
        bmi = weight / ((height / 100) ** 2)
    else:
        # parse the height e.g 6'2 to inches

        # split by any symbol except numbers
        height = re.split(r'\D+', height)

        feet = int(height[0])
        inches = 0
        if len(height) > 1:
            inches = int(height[1])
        height = (feet * 12) + inches

        bmi = (weight / (height ** 2)) * 703

    await ctx.send(f"**{bmi:.2f}**")


@slash_command(name="mash_emojis", description="Mashes up two emojis.", scopes=[guild_id])
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
@slash_option(name="emoji1", description="The first emoji.", required=False, opt_type=OptionType.STRING)
@slash_option(name="emoji2", description="The second emoji.", required=False, opt_type=OptionType.STRING)
@slash_option(name="use_random", description="Use random emojis?", required=False, opt_type=OptionType.BOOLEAN)
async def mash_emojis(ctx: interactions.SlashContext, emoji1: str = None, emoji2: str = None, use_random: bool = False):
    if use_random:
        emoji1 = random.choice(all_emojis)
        emoji2 = random.choice(all_emojis)

    if not emoji1 or not emoji2:
        await ctx.send("Please provide two emojis or use the random option.", ephemeral=True)
        return

    # Make any skin tone emojis into the base emoji
    emoji1 = re.compile("[\U0001F3FB-\U0001F3FF]").sub('', emoji1)
    emoji2 = re.compile("[\U0001F3FB-\U0001F3FF]").sub('', emoji2)

    # mash them up with google
    print(f"Mashing up {emoji1} and {emoji2}")
    mashed_emoji_url = utils.mash_emojis(emoji1, emoji2)

    await ctx.send(mashed_emoji_url)

#temporarily mutes someone and restricts to trans channel
@slash_command(name="diva_read", description="mutes someone for 10 mins", scopes=[guild_id])
@slash_option(name="user", description="The user to gag", required=True, opt_type=OptionType.USER)
@slash_option(name="read_msg", description="say what to expose them with!", required=True, opt_type=OptionType.STRING)
@slash_option(name="duration", description="Duration in minutes (default 5, max 720)", required=False, opt_type=OptionType.INTEGER)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def restrict_diva_resp(ctx: interactions.SlashContext, user: interactions.Member, read_msg: str, duration: int = 5):
    if ctx.author.has_role(diva_role_id) or ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        # Validate duration
        if duration < 1:
            await ctx.send("❌ Duration must be at least 1 minute", ephemeral=True)
            return
        if duration > 600:  # 10 hours max
            await ctx.send("❌ Duration cannot exceed 10 hours (600 minutes)", ephemeral=True)
            return

        diva_id = ctx.author.id
        # Get today's date in YYYY-MM-DD format
        current_date = datetime.now().strftime("%Y-%m-%d")
        DivaQuery = Query()
        record = diva_mute_table.get(DivaQuery.diva_id == diva_id)
        if user.has_role(admin_role) or user.has_role(support_role):
            await ctx.send(f"❌ you can't mute a mod!", ephemeral=True)
            return

        if user.has_role(diva_role_id):
            await ctx.send(f"❌ you can't mute another diva!", ephemeral=True)
            return

        # Check if there's a record for this diva
        if not record:
            # First mute by this diva, create a new record
            diva_mute_table.insert({"diva_id": diva_id, "date": current_date, "count": 1})
            mute_count = 1
        else:
            # Check if the record is for today
            if record.get("date") == current_date:
                # Same day, increment count
                mute_count = record.get("count", 0) + 1
                diva_mute_table.update({"count": mute_count}, DivaQuery.diva_id == diva_id)
            else:
                # New day, reset count
                mute_count = 1
                diva_mute_table.update({"date": current_date, "count": mute_count}, DivaQuery.diva_id == diva_id)

        # Check if the diva exceeded the daily mute limit
        if mute_count > DIVA_DAILTY_MUTE_LIMIT:
            await ctx.send(f"❌ diva mute is on cooldown... {DIVA_DAILTY_MUTE_LIMIT} times per day (resets midnight EST)", ephemeral=True)
            logger.warning(f"{str(ctx.author.username)} diva is clocking too hard!")
            mod_log_channel = client.get_channel(mod_log_channel_id)
            await mod_log_channel.send(
                embed=interactions.Embed(
                    title="diva is clocking too hard!",
                    description=f"{str(ctx.author.mention)} used diva_read mute {mute_count} times today",
                    color=0x9c92d1
                )
            )
            return

        # If the user is already restricted
        if gagged_table.contains(where('user_id') == user.id):
            await ctx.send(f"❌ {user.mention} is already gagged", ephemeral=True)
            return

        gagged_role = ctx.guild.get_role(gagged_role_id)
        # Simply add the vibe checked role without removing other roles
        await user.add_role(gagged_role)

        # Calculate expiration timestamp
        expires_at = time.time() + (duration * 60)

        # Store in database
        gagged_table.insert({
            'user_id': user.id,
            'diva_id': ctx.author.id,
            'read_msg': read_msg,
            'expires_at': expires_at,
            'issued_at': time.time()
        })

        # Send the message read_msg
        await ctx.send(embed=interactions.Embed(
                title=f"🚨 Diva alert!",
                description=f"{str(user.mention)} got clocked and read for {duration} minutes\n{str(ctx.author.mention)}: {str(read_msg)}",
                color=0x9c92d1
                ),
                ephemeral=False)
        # Send another message to side chat reminding them they can type there
        trans_channel = client.get_channel(trans_channel_id)
        await trans_channel.send(embed=interactions.Embed(
                title=f"diva gagged for {duration} minutes",
                description=f"{str(user.mention)} you can still use the chat here",
                color=0x9c92d1
                ),
                ephemeral=False)
        mod_log_channel = client.get_channel(mod_log_channel_id)
        await mod_log_channel.send(
            embed=interactions.Embed(
                title=f"diva_read mute used",
                description=f"{str(ctx.author.mention)} gagged {str(user.mention)} for {duration} minutes with message: {str(read_msg)}",
                color=0x9c92d1
            )
        )
        return
    await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
    return

# Manual ungag command
@slash_command(name="ungag", description="Manually remove gag from user", scopes=[guild_id])
@slash_option(name="user", description="The user to ungag", required=True, opt_type=OptionType.USER)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def ungag_user(ctx: interactions.SlashContext, user: interactions.Member):
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role) or ctx.author.has_role(diva_role_id):
        gag_record = gagged_table.get(where('user_id') == user.id)
        if not gag_record:
            await ctx.send(f"❌ {user.mention} is not gagged", ephemeral=True)
            return

        # Remove from database
        gagged_table.remove(where('user_id') == user.id)

        # Remove role
        gagged_role = ctx.guild.get_role(gagged_role_id)
        if user.has_role(gagged_role_id):
            await user.remove_role(gagged_role)

        await ctx.send(f"❌ Removed gag from {user.mention}")

        # Log to mod channel
        mod_log_channel = client.get_channel(mod_log_channel_id)
        await mod_log_channel.send(
            embed=interactions.Embed(
                title="Manual ungag",
                description=f"{ctx.author.mention} manually ungagged {user.mention}",
                color=0x9c92d1
            )
        )
        logger.info(f"{ctx.author.username} manually ungagged {user.username}")
    else:
        await ctx.send("âŒ You don't have permission to use this command.", ephemeral=True)

# Ban command with anti nuke protection
@slash_command(name="ban", description="Bans a member.", scopes=[guild_id])
@slash_option(name="user", description="The member to ban.", required=True, opt_type=OptionType.USER)
@slash_option(name="reason", description="The reason for the ban.", required=True, opt_type=OptionType.STRING)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def ban_member(ctx: interactions.SlashContext, user: interactions.Member, reason: str = None):
    # Check if user has permission to ban
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        logger.info(f"{ctx.author.username} is trying to ban {user.username}")
    else:
        await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
        
    # Check if the user is already banned
    is_banned = await ctx.guild.fetch_ban(user)
    if is_banned:
        await ctx.send(f"{user.mention} is already banned.", ephemeral=False)
        return

    mod_id = ctx.author.id
    current_time = time.time()

    # Get ban history from the database
    ModQuery = Query()
    record = ban_table.get(ModQuery.mod_id == mod_id)
    
    # 122154761066643456  1052263609452994581
    if (user.id == 122154761066643456 or user.id == 1052263609452994581):
        logger.warning(f"{ctx.author.username} tried to ban admins!!!")
        await ctx.send(f"no chance you actually tried that", ephemeral=True)
        return # don't ban them
    if user.has_role(admin_role) or user.has_role(support_role):
        await ctx.send(f"you can't ban {user.mention}", ephemeral=False)
        logger.info(f"{ctx.author.username} has tried to ban mod {user.username}!!")
        return # don't ban them

    # If no record exists, create one
    if not record:
        ban_table.insert({"mod_id": mod_id, "bans": [current_time]})
        ban_history = [current_time]
    else:
        # Clean up old timestamps
        ban_history = [t for t in record["bans"] if current_time - t < TIME_FRAME]
        ban_history.append(current_time)
        ban_table.update({"bans": ban_history}, ModQuery.mod_id == mod_id)

    # Check if the mod exceeded the ban limit by 2 two many (as a buffer)
    if len(ban_history) >= BAN_LIMIT + 1:
        await ctx.send(f"⚠️ Ban limit exceeded, please wait {TIME_FRAME / 60 / 60} hours.", ephemeral=False)

        try:
            # Remove mod permissions (Example: Remove their role)
            mod_member = ctx.guild.get_member(mod_id)
            mod_role = ctx.guild.get_role(admin_role)  # Adjust this based on your role structure
            await mod_member.remove_role(mod_role)

        except:
            logger.error(f"Failed to remove role from {mod_member}")

        # Log the event and alert other admins
        logger.warning(f"🚨 {ctx.author.username} attempted mass banning!")

        mod_log_channel = client.get_channel(mod_log_channel_id)
        await mod_log_channel.send(
            embed=interactions.Embed(
                title="🚨 Potential compromise detected!",
                description=f"{ctx.author.mention} exceeded the ban limit and had their permissions revoked.",
                color=0x9c92d1
            )
        )
        return

    # if the ban limit is exactly reached
    elif len(ban_history) == BAN_LIMIT:
        await ctx.send("⚠️ Ban limit reached!", ephemeral=False)
        return  # Do not ban the user

    # Check if user has permission to ban
    if ctx.author.has_role(admin_role) or ctx.author.has_role(support_role):
        await ctx.guild.ban(user, reason=reason)
        await ctx.send(f"{user.mention} has been banned.", ephemeral=False)
        logger.info(f"{user.username} has been banned.")
        mod_log_channel = client.get_channel(mod_log_channel_id)
        await mod_log_channel.send(
            embed=interactions.Embed(
                title=f"user banned by mod",
                description=f"{str(ctx.author.mention)} banned {str(user.mention)} with reason {reason}",
                color=0x9c92d1
            )
        )

    else:
        await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)


# Message listener
@client.listen()
async def on_message_create(ctx):
    # Do not respond to messages from the bot itself
    if ctx.message.author.id == client.user.id:
        return

    # Do not respond to bots
    if ctx.message.author.bot:
        return

    # Store message to SQLite if not in excluded channels
    if ctx.message.channel.id not in excluded_highlight_channels:
        db.insert_live_message({
            'message_id': ctx.message.id,
            'channel_id': ctx.message.channel.id,
            'author_id': ctx.message.author.id,
            'author_name': ctx.message.author.username,
            'author_nickname': ctx.message.author.display_name,
            'author_avatar_url': str(ctx.message.author.avatar_url) if ctx.message.author.avatar_url else None,
            'content': ctx.message.content,
            'timestamp': datetime.now().isoformat(),
            'is_pinned': False,
            'is_reply': bool(ctx.message.message_reference),
            'reply_to_message_id': ctx.message.message_reference.message_id if ctx.message.message_reference else None,
            'attachments': [{'id': str(a.id), 'url': a.url, 'filename': a.filename} for a in ctx.message.attachments],
            'embeds': [],
            'reactions': [],
            'mentions': [],  # interactions library doesn't expose mentions directly
        })

    # Handle reply-based highlights
    if ctx.message.message_reference:
        await highlights.handle_message_reply(client, ctx)

    # Mute command - Format: .mute @user reason duration
    if ctx.message.content.startswith(".mute"):
        if ctx.message.author.has_role(admin_role) or ctx.message.author.has_role(support_role):
            # Parse the parameters
            params = ctx.message.content.split(" ")
            if len(params) < 4:
                await ctx.message.reply("Invalid format. Format: .mute @user reason duration")
                return

            duration_string = params[3]
            duration = utils.parse_duration_string(duration_string)
            duration_seconds, duration_name = duration['value'], duration['name']
            member_id = int(params[1][2:-1])
            reason = params[2]

            # Time out the member
            guild = await client.fetch_guild(guild_id)
            member = await guild.fetch_member(member_id)
            await member.timeout(helpers.calculate_disabled_until(duration_seconds))

            await ctx.message.reply(
                f"Muted {params[1]} for {duration_string[:-1]} {duration_name}. **Reason:** {reason} <:joyMonkeymale:1292911064492544103>")

    # If any word in the message is in the blacklist
    if profanity.contains_bad_word(ctx.message.content):
        logger.info(f'Bad word detected in message: {ctx.message.content}, author: {ctx.message.author}')

        log_channel = client.get_channel(message_log_channel_id)
        # Log the message
        embed = interactions.Embed(
            title="Bad Word Detected",
            description=f"||{ctx.message.content}||",
            color=0x9c92d1
        )
        embed.set_author(name=ctx.message.author.display_name, icon_url=ctx.message.author.avatar_url)
        await log_channel.send(f'Bad word detected in message: ||{ctx.message.content}||, author: {ctx.message.author}')

        # Time the member out for 10 minutes
        await ctx.message.author.timeout(helpers.calculate_disabled_until(60 * 10))
        # Delete the message
        await ctx.message.delete()
        return

    # If member has the media timeout role
    if ctx.message.author.has_role(media_timeout_role) or ctx.message.author.has_role(new_sus_member_role):
        # If there is a url in the message
        if ctx.message.attachments or 'http' in ctx.message.content.lower():
            # Reply to the message with a warning
            # await ctx.message.reply("You are media timed out. Please wait until the timeout is over.", ephemeral=True)
            # If the link leads to a channel dont delete the message
            if f'https://discord.com/channels/{guild_id}' in ctx.message.content.lower():
                return

            await ctx.message.delete()

    # Slowdown handler
    if slowed_members_table.get(where('user_id') == ctx.message.author.id):
        # Get the interval
        slowed_user_data = slowed_members_table.get(where('user_id') == ctx.message.author.id)
        interval = slowed_user_data['interval_seconds']

        # Time them out so they cant send a message while the interval is not over
        await ctx.message.author.timeout(helpers.calculate_disabled_until(interval))

    # React to messages with attachments in selfie channel
    # if ctx.message.channel.id == selfie_channel_id and ctx.message.attachments:
    #     await ctx.message.add_reaction(f"â¤")

    if helpers.any_in_list(['rah mode', 'rahmode'], ctx.message.content.lower()):
        await ctx.message.add_reaction(f"<a:rahmode:1158917623959015454>")

    # Anti spam
    if utils.detect_duplicate_phrases(ctx.message.content):
        # Ignore bot messages
        if ctx.message.author.bot:
            return

        # Warn the member and delete the message
        await ctx.message.reply(
            f"Please do not spam buddy. <:angryMonkeymale:1292909963030691902> {ctx.message.author.mention}")
        await ctx.message.delete()

        # Log the message
        log_channel = client.get_channel(mod_log_channel_id)
        embed = interactions.Embed(
            description=ctx.message.content[:1999],
            color=0x9c92d1
        )
        embed.set_author(name=f"Spam Warning for {str(ctx.message.author.display_name)}",
                         icon_url=ctx.message.author.avatar_url)
        embed.add_field(name="User", value=ctx.message.author.mention, inline=True)
        embed.add_field(name="Channel", value=ctx.message.channel.mention, inline=True)
        await log_channel.send(embed=embed)

        # Log the spammer in the db
        spammers_table.insert({
            'user_id': ctx.message.author.id,
            'message_id': ctx.message.id,
            'channel_id': ctx.message.channel.id,
            'timestamp': datetime.now().isoformat(),
            'message': str(ctx.message.content),
        })

        # If the user is a previously logged spammer, time them out after 3 offenses within the last hour
        spammer_offenses = spammers_table.search(where('user_id') == ctx.message.author.id)
        if len(spammer_offenses) >= 3 and (datetime.now() - datetime.fromisoformat(
                spammer_offenses[-1]['timestamp'])).seconds < 3600:
            # Time the member out for 10 minutes
            await ctx.message.author.timeout(helpers.calculate_disabled_until(60 * 10))
            await log_channel.send(f"{ctx.message.author.mention} has been timed out for 10 minutes for spamming.")
            logger.info(f"{ctx.message.author.mention} has been timed out for spamming.")


# On reaction - delegate to highlights module
@client.listen(MessageReactionAdd)
async def on_reaction(event: MessageReactionAdd):
    await highlights.handle_reaction_highlight(client, event)


# ============== PROCESS MANAGEMENT ==============

PID_FILE = Path("bot.pid")


def check_already_running():
    """Check if another instance is already running."""
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            # Check if process is actually running
            os.kill(old_pid, 0)
            logger.error(f"Bot already running (PID {old_pid})")
            sys.exit(1)
        except (OSError, ValueError):
            # Process not running or invalid PID, stale file
            logger.info("Removing stale PID file")
            PID_FILE.unlink(missing_ok=True)


def write_pid():
    """Write current PID to file."""
    PID_FILE.write_text(str(os.getpid()))
    logger.info(f"Bot started with PID {os.getpid()}")


def cleanup():
    """Clean up PID file and resources."""
    logger.info("Cleaning up...")
    PID_FILE.unlink(missing_ok=True)


def handle_shutdown(signum, frame):
    """Handle shutdown signals gracefully."""
    sig_name = signal.Signals(signum).name
    logger.info(f"Received {sig_name}, shutting down gracefully...")
    cleanup()
    sys.exit(0)


# Transient network errors that warrant an automatic restart
RESTARTABLE_EXCEPTIONS = (
    aiohttp.ClientConnectorDNSError,
    aiohttp.ClientConnectorError,
    aiohttp.ClientOSError,
    aiohttp.ServerDisconnectedError,
    ConnectionResetError,
    OSError,
)

MAX_BACKOFF_SECONDS = 300  # 5 minute cap


# ============== MAIN ENTRY POINT ==============

if __name__ == "__main__":
    # Check for duplicate process
    check_already_running()

    # Write PID file
    write_pid()

    # Register cleanup handlers
    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    # Initialize database before starting
    db.init_database()
    logger.info("Database initialized")

    # Supervisor loop: restart on transient network failures
    consecutive_failures = 0
    while True:
        try:
            logger.info("Starting bot...")
            client.start()
            # client.start() returned cleanly — treat as intentional shutdown
            logger.info("Bot stopped cleanly, exiting.")
            break
        except RESTARTABLE_EXCEPTIONS as exc:
            consecutive_failures += 1
            backoff = min(2 ** consecutive_failures, MAX_BACKOFF_SECONDS)
            logger.warning(
                f"Bot crashed with transient error ({type(exc).__name__}: {exc}). "
                f"Restarting in {backoff}s (attempt #{consecutive_failures})..."
            )
            time.sleep(backoff)
            # Re-create the event loop since the old one is closed after start()
            asyncio.set_event_loop(asyncio.new_event_loop())
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt, exiting.")
            break
        except SystemExit:
            raise
        except Exception as exc:
            consecutive_failures += 1
            backoff = min(2 ** consecutive_failures, MAX_BACKOFF_SECONDS)
            logger.error(
                f"Bot crashed with unexpected error ({type(exc).__name__}: {exc}). "
                f"Restarting in {backoff}s (attempt #{consecutive_failures})...",
                exc_info=True,
            )
            time.sleep(backoff)
            asyncio.set_event_loop(asyncio.new_event_loop())