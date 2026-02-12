"""
Message Purge Commands
Add these to your bot1.py for mass-deleting messages from specific users.

Usage in bot1.py:
    from purge_commands import *
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import interactions
from interactions import (
    slash_command,
    slash_option,
    SlashContext,
    OptionType,
    SlashCommandChoice,
    ChannelType,
    Embed,
    Button,
    ButtonStyle,
    component_callback,
    auto_defer,
)

# Import from your consts
from common.consts import guild_id, admin_role, support_role

logger = logging.getLogger("PurgeCommands")

# Track active purge operations (to allow cancellation)
active_purges = {}

# Directory to store archived messages
ARCHIVE_DIR = "./purge_archives"
Path(ARCHIVE_DIR).mkdir(exist_ok=True)


def archive_message(message, archive_data: list):
    """Add a message to the archive list."""
    archive_data.append({
        "message_id": str(message.id),
        "channel_id": str(message.channel.id),
        "channel_name": message.channel.name if hasattr(message.channel, 'name') else "unknown",
        "author_id": str(message.author.id),
        "author_name": message.author.display_name,
        "content": message.content,
        "timestamp": message.created_at.isoformat() if message.created_at else None,
        "attachments": [{"url": a.url, "filename": a.filename} for a in message.attachments] if message.attachments else [],
    })


def save_archive(user_id: str, username: str, archive_data: list, channel_name: str = "server"):
    """Save archived messages to a JSON file."""
    if not archive_data:
        return None
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{ARCHIVE_DIR}/purged_{username}_{channel_name}_{timestamp}.json"
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump({
            "user_id": user_id,
            "username": username,
            "purge_date": datetime.now().isoformat(),
            "message_count": len(archive_data),
            "messages": archive_data
        }, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Archived {len(archive_data)} messages to {filename}")
    return filename


@slash_command(name="purge_user", description="Delete all messages from a user in a specific channel", scopes=[guild_id])
@slash_option(name="user", description="The user whose messages to delete", required=True, opt_type=OptionType.USER)
@slash_option(name="channel", description="The channel to purge (defaults to current channel)", required=False, opt_type=OptionType.CHANNEL, channel_types=[ChannelType.GUILD_TEXT])
@slash_option(name="limit", description="Max messages to scan (default 10000, increase for inactive users)", required=False, opt_type=OptionType.INTEGER)
@slash_option(
    name="age_filter",
    description="Which messages to delete based on age",
    required=False,
    opt_type=OptionType.STRING,
    choices=[
        SlashCommandChoice(name="All messages", value="all"),
        SlashCommandChoice(name="Only old (>14 days)", value="old_only"),
        SlashCommandChoice(name="Only recent (<14 days)", value="recent_only"),
        SlashCommandChoice(name="Older than 30 days", value="30_days"),
        SlashCommandChoice(name="Older than 90 days", value="90_days"),
    ]
)
@slash_option(name="archive", description="Save messages locally before deleting (default: True)", required=False, opt_type=OptionType.BOOLEAN)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def purge_user_channel(ctx: SlashContext, user: interactions.User, channel = None, limit: int = 10000, age_filter: str = "all", archive: bool = True):
    """Delete all messages from a user in a specific channel."""
    
    # Check permissions
    if not (ctx.author.has_role(admin_role) or ctx.author.has_role(support_role)):
        await ctx.send("You don't have permission to use this command.", ephemeral=True)
        return
    
    # Default to current channel if none specified
    target_channel = channel or ctx.channel
    
    limit = min(limit, 1000000)  # Cap at 1 million
    
    age_descriptions = {
        "all": "all messages",
        "old_only": "only messages older than 14 days",
        "recent_only": "only messages from the last 14 days",
        "30_days": "only messages older than 30 days",
        "90_days": "only messages older than 90 days",
    }
    
    # Confirmation embed
    embed = Embed(
        title="⚠️ Confirm Purge",
        description=f"This will delete **{age_descriptions[age_filter]}** from {user.mention} in {target_channel.mention}.\n\n"
                    f"Scanning up to **{limit}** messages.\n"
                    f"Archive before delete: **{'Yes' if archive else 'No'}**\n\n"
                    f"This action cannot be undone.",
        color=0xff6b6b
    )
    
    components = [
        Button(style=ButtonStyle.DANGER, label="Delete Messages", custom_id=f"confirm_purge:{user.id}:{target_channel.id}:{limit}:{age_filter}:{archive}"),
        Button(style=ButtonStyle.SECONDARY, label="Cancel", custom_id="cancel_purge")
    ]
    
    await ctx.send(embed=embed, components=components, ephemeral=True)


@slash_command(name="purge_user_server", description="Delete all messages from a user across the ENTIRE server", scopes=[guild_id])
@slash_option(name="user", description="The user whose messages to delete", required=True, opt_type=OptionType.USER)
@slash_option(name="limit_per_channel", description="Max messages to scan per channel (default 500)", required=False, opt_type=OptionType.INTEGER)
@slash_option(
    name="age_filter",
    description="Which messages to delete based on age",
    required=False,
    opt_type=OptionType.STRING,
    choices=[
        SlashCommandChoice(name="All messages", value="all"),
        SlashCommandChoice(name="Only old (>14 days)", value="old_only"),
        SlashCommandChoice(name="Only recent (<14 days)", value="recent_only"),
        SlashCommandChoice(name="Older than 30 days", value="30_days"),
        SlashCommandChoice(name="Older than 90 days", value="90_days"),
    ]
)
@slash_option(name="archive", description="Save messages locally before deleting (default: True)", required=False, opt_type=OptionType.BOOLEAN)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def purge_user_server(ctx: SlashContext, user: interactions.User, limit_per_channel: int = 500, age_filter: str = "all", archive: bool = True):
    """Delete all messages from a user across the entire server."""
    
    # Admin only for server-wide purge
    if not ctx.author.has_role(admin_role):
        await ctx.send("Only admins can use server-wide purge.", ephemeral=True)
        return
    
    limit_per_channel = min(limit_per_channel, 2000)
    
    # Count text channels
    text_channels = [ch for ch in ctx.guild.channels if hasattr(ch, 'history')]
    
    age_descriptions = {
        "all": "all messages",
        "old_only": "only messages older than 14 days",
        "recent_only": "only messages from the last 14 days",
        "30_days": "only messages older than 30 days",
        "90_days": "only messages older than 90 days",
    }
    
    embed = Embed(
        title="⚠️ SERVER-WIDE PURGE",
        description=f"This will scan **{len(text_channels)} channels** and delete **{age_descriptions[age_filter]}** from {user.mention}.\n\n"
                    f"Scanning up to **{limit_per_channel}** messages per channel.\n"
                    f"Archive before delete: **{'Yes' if archive else 'No'}**\n\n"
                    f"**This can take a LONG time and cannot be undone.**",
        color=0xff0000
    )
    
    components = [
        Button(style=ButtonStyle.DANGER, label="⚠️ Delete From Entire Server", custom_id=f"confirm_server_purge:{user.id}:{limit_per_channel}:{age_filter}:{archive}"),
        Button(style=ButtonStyle.SECONDARY, label="Cancel", custom_id="cancel_purge")
    ]
    
    await ctx.send(embed=embed, components=components, ephemeral=True)


@component_callback("cancel_purge")
async def cancel_purge(ctx: interactions.ComponentContext):
    await ctx.edit_origin(content="Purge cancelled.", embed=None, components=[])


@component_callback(re.compile(r"^confirm_purge:"))
async def confirm_purge(ctx: interactions.ComponentContext):
    """Execute single-channel purge with improved rate limiting."""
    
    # Parse parameters from custom_id
    parts = ctx.custom_id.split(":")
    user_id = int(parts[1])
    target_channel_id = int(parts[2])
    limit = int(parts[3])
    age_filter = parts[4] if len(parts) > 4 else "all"
    should_archive = parts[5].lower() == "true" if len(parts) > 5 else True
    
    # Get the target channel (may be different from ctx.channel)
    target_channel = ctx.guild.get_channel(target_channel_id)
    if not target_channel:
        await ctx.edit_origin(content="Target channel not found.", embed=None, components=[])
        return
    
    # Set up cancellation
    purge_key = f"{target_channel_id}:{user_id}"
    active_purges[purge_key] = True
    
    # Get user info for archive filename
    try:
        user = await ctx.guild.fetch_member(user_id)
        username = user.display_name if user else str(user_id)
    except:
        username = str(user_id)
    
    # Acknowledge the button click
    try:
        await ctx.edit_origin(
            embed=Embed(
                title="🔄 Purge Started",
                description=f"Purging messages from **{username}** in {target_channel.mention}...\n\nProgress updates below.",
                color=0x9c92d1
            ),
            components=[]
        )
    except:
        pass
    
    # Send progress message in the COMMAND channel (where the slash command was run)
    progress_msg = await ctx.channel.send(
        embed=Embed(
            title="🔄 Channel Purge Progress",
            description=f"**Target:** {target_channel.mention}\n**User:** {username}\nStarting scan...",
            color=0x9c92d1
        )
    )
    
    deleted_count = 0
    scanned_count = 0
    skipped_count = 0
    found_count = 0  # Messages found from target user (before filtering)
    errors = 0
    archive_data = []
    
    now = datetime.now(timezone.utc)
    fourteen_days_ago = now - timedelta(days=14)
    thirty_days_ago = now - timedelta(days=30)
    ninety_days_ago = now - timedelta(days=90)
    
    bulk_delete_queue = []
    last_update_time = datetime.now()
    current_delay = 1.0  # Start with 1 second delay for old messages
    
    logger.info(f"[PURGE] Starting purge in #{target_channel.name} for user {username} (ID: {user_id}, type: {type(user_id)}) (limit: {limit}, age_filter: {age_filter})")

    try:
        async for message in target_channel.history(limit=limit):
            # Log first few message authors to debug matching
            if scanned_count < 5:
                logger.info(f"[PURGE] Sample msg author: {message.author.id} (type: {type(message.author.id)}), looking for: {user_id}")
            # Check if cancelled
            if not active_purges.get(purge_key, False):
                logger.info(f"[PURGE] Cancelled by user")
                break

            scanned_count += 1

            # Add delay every 100 messages to avoid hammering the API
            if scanned_count % 100 == 0:
                await asyncio.sleep(0.5)
                if scanned_count % 1000 == 0:
                    logger.info(f"[PURGE] Scanned {scanned_count:,} messages, found {found_count} from target user so far...")
            
            if message.author.id == user_id:
                found_count += 1
                if found_count <= 5:
                    logger.info(f"[PURGE] Found message #{found_count} from target user: {message.id}")
                # Get message age
                msg_time = message.created_at
                if msg_time.tzinfo is None:
                    msg_time = msg_time.replace(tzinfo=timezone.utc)
                
                is_old = msg_time < fourteen_days_ago
                is_30_days_old = msg_time < thirty_days_ago
                is_90_days_old = msg_time < ninety_days_ago
                
                # Check age filter
                should_delete = False
                if age_filter == "all":
                    should_delete = True
                elif age_filter == "old_only" and is_old:
                    should_delete = True
                elif age_filter == "recent_only" and not is_old:
                    should_delete = True
                elif age_filter == "30_days" and is_30_days_old:
                    should_delete = True
                elif age_filter == "90_days" and is_90_days_old:
                    should_delete = True
                
                if not should_delete:
                    skipped_count += 1
                    if skipped_count <= 3:
                        logger.info(f"[PURGE] Skipping message {message.id} due to age_filter={age_filter}, msg_age={msg_time}, is_old={is_old}")
                    continue
                
                # Archive before deleting
                if should_archive:
                    archive_message(message, archive_data)
                
                if not is_old:
                    # Can bulk delete (message is recent)
                    bulk_delete_queue.append(message)
                    
                    # Bulk delete when we have 100 (Discord's limit)
                    if len(bulk_delete_queue) >= 100:
                        try:
                            await target_channel.delete_messages(bulk_delete_queue)
                            deleted_count += len(bulk_delete_queue)
                            logger.info(f"[PURGE] Bulk deleted {len(bulk_delete_queue)} recent messages, total: {deleted_count}")
                        except Exception as e:
                            errors += len(bulk_delete_queue)
                            logger.error(f"[PURGE] Bulk delete error: {e}")
                        bulk_delete_queue = []
                else:
                    # Old message - delete individually with adaptive rate limiting
                    try:
                        await message.delete()
                        deleted_count += 1
                        current_delay = max(1.0, current_delay * 0.95)  # Slowly reduce delay on success
                        
                        if deleted_count % 25 == 0:
                            logger.info(f"[PURGE] Deleted {deleted_count} messages, scanned {scanned_count}...")
                            
                    except Exception as e:
                        error_str = str(e).lower()
                        if "rate" in error_str or "429" in error_str:
                            # Rate limited - increase delay and retry
                            current_delay = min(5.0, current_delay * 1.5)
                            logger.warning(f"[PURGE] Rate limited, increasing delay to {current_delay:.1f}s")
                            await asyncio.sleep(current_delay * 2)
                            try:
                                await message.delete()
                                deleted_count += 1
                            except:
                                errors += 1
                        else:
                            errors += 1
                            logger.error(f"[PURGE] Delete error: {e}")
                    
                    await asyncio.sleep(current_delay)
            
            # Update progress every 10 seconds
            if (datetime.now() - last_update_time).seconds >= 10:
                try:
                    await progress_msg.edit(
                        embed=Embed(
                            title="🔄 Channel Purge Progress",
                            description=f"**Target:** {target_channel.mention}\n"
                                        f"**User:** {username}\n"
                                        f"**Scanned:** {scanned_count:,}\n"
                                        f"**Deleted:** {deleted_count:,}\n"
                                        f"**Skipped:** {skipped_count:,}\n"
                                        f"**Errors:** {errors}\n"
                                        f"**Rate:** {current_delay:.1f}s delay",
                            color=0x9c92d1
                        )
                    )
                    last_update_time = datetime.now()
                except:
                    pass
        
        # Delete remaining bulk queue
        if bulk_delete_queue:
            try:
                if len(bulk_delete_queue) == 1:
                    await bulk_delete_queue[0].delete()
                else:
                    await target_channel.delete_messages(bulk_delete_queue)
                deleted_count += len(bulk_delete_queue)
                logger.info(f"[PURGE] Final bulk delete: {len(bulk_delete_queue)} messages")
            except Exception as e:
                errors += len(bulk_delete_queue)
                logger.error(f"[PURGE] Final bulk delete error: {e}")
    
    except Exception as e:
        logger.error(f"[PURGE] Fatal error: {e}")
    
    finally:
        active_purges.pop(purge_key, None)
    
    # Save archive
    archive_file = None
    if should_archive and archive_data:
        archive_file = save_archive(str(user_id), username, archive_data, target_channel.name)
    
    # Final report
    logger.info(f"[PURGE] Complete! Scanned: {scanned_count}, Found from user: {found_count}, Deleted: {deleted_count}, Skipped: {skipped_count}, Errors: {errors}")
    
    archive_info = f"\n**Archived:** `{archive_file}`" if archive_file else ""
    
    final_embed = Embed(
        title="✅ Purge Complete",
        description=f"**Channel:** {target_channel.mention}\n"
                    f"**User:** {username}\n"
                    f"**Scanned:** {scanned_count:,} messages\n"
                    f"**Found from user:** {found_count:,}\n"
                    f"**Deleted:** {deleted_count:,} messages\n"
                    f"**Skipped:** {skipped_count:,} (didn't match filter)\n"
                    f"**Errors:** {errors}"
                    f"{archive_info}",
        color=0x00ff00 if errors == 0 else 0xffaa00
    )
    
    try:
        await progress_msg.edit(embed=final_embed)
    except:
        await ctx.channel.send(embed=final_embed)


@component_callback(re.compile(r"^confirm_server_purge:"))
async def confirm_server_purge(ctx: interactions.ComponentContext):
    """Execute server-wide purge."""
    
    parts = ctx.custom_id.split(":")
    user_id = int(parts[1])
    limit_per_channel = int(parts[2])
    age_filter = parts[3] if len(parts) > 3 else "all"
    should_archive = parts[4].lower() == "true" if len(parts) > 4 else True
    
    purge_key = f"server:{user_id}"
    active_purges[purge_key] = True
    
    text_channels = [ch for ch in ctx.guild.channels if hasattr(ch, 'history') and hasattr(ch, 'delete_messages')]
    
    total_deleted = 0
    total_scanned = 0
    total_skipped = 0
    channels_done = 0
    errors = 0
    archive_data = []
    
    # Get user info for archive filename
    try:
        user = await ctx.guild.fetch_member(user_id)
        username = user.display_name if user else str(user_id)
    except:
        username = str(user_id)
    
    # Acknowledge the interaction immediately
    await ctx.edit_origin(
        embed=Embed(
            title="🔄 Server-Wide Purge Started",
            description=f"Processing {len(text_channels)} channels...\n\nProgress updates will be posted below.",
            color=0x9c92d1
        ),
        components=[]
    )
    
    # Send a regular message for progress updates (won't expire)
    progress_msg = await ctx.channel.send(
        embed=Embed(
            title="🔄 Purge Progress",
            description=f"Starting... (0/{len(text_channels)} channels)",
            color=0x9c92d1
        )
    )
    
    now = datetime.now(timezone.utc)
    fourteen_days_ago = now - timedelta(days=14)
    thirty_days_ago = now - timedelta(days=30)
    ninety_days_ago = now - timedelta(days=90)
    
    last_update = datetime.now()
    
    for channel in text_channels:
        if not active_purges.get(purge_key, False):
            break
        
        logger.info(f"[PURGE] Starting channel #{channel.name}...")
        
        try:
            channel_deleted = 0
            bulk_queue = []
            
            async for message in channel.history(limit=limit_per_channel):
                if not active_purges.get(purge_key, False):
                    break
                
                total_scanned += 1
                
                if message.author.id == user_id:
                    # Get message age
                    msg_time = message.created_at
                    if msg_time.tzinfo is None:
                        msg_time = msg_time.replace(tzinfo=timezone.utc)
                    
                    is_old = msg_time < fourteen_days_ago
                    is_30_days_old = msg_time < thirty_days_ago
                    is_90_days_old = msg_time < ninety_days_ago
                    
                    # Check age filter
                    should_delete = False
                    if age_filter == "all":
                        should_delete = True
                    elif age_filter == "old_only" and is_old:
                        should_delete = True
                    elif age_filter == "recent_only" and not is_old:
                        should_delete = True
                    elif age_filter == "30_days" and is_30_days_old:
                        should_delete = True
                    elif age_filter == "90_days" and is_90_days_old:
                        should_delete = True
                    
                    if not should_delete:
                        total_skipped += 1
                        continue
                    
                    try:
                        # Archive before deleting
                        if should_archive:
                            archive_message(message, archive_data)
                        
                        if not is_old:
                            bulk_queue.append(message)
                            
                            if len(bulk_queue) >= 100:
                                await channel.delete_messages(bulk_queue)
                                channel_deleted += len(bulk_queue)
                                bulk_queue = []
                        else:
                            await message.delete()
                            channel_deleted += 1
                            # Log every 10 old message deletions
                            if channel_deleted % 10 == 0:
                                logger.info(f"[PURGE] #{channel.name}: deleted {channel_deleted} old messages so far...")
                            await asyncio.sleep(1.2)  # Rate limit for old messages
                    except Exception as e:
                        errors += 1
                        logger.error(f"Delete error in #{channel.name}: {e}")
            
            # Clear remaining queue
            if bulk_queue:
                try:
                    if len(bulk_queue) == 1:
                        await bulk_queue[0].delete()
                    else:
                        await channel.delete_messages(bulk_queue)
                    channel_deleted += len(bulk_queue)
                except Exception as e:
                    errors += len(bulk_queue)
                    logger.error(f"Bulk delete error in #{channel.name}: {e}")
            
            total_deleted += channel_deleted
            channels_done += 1
            
            # Log each channel completion
            logger.info(f"[PURGE] #{channel.name}: found {channel_deleted} messages, total deleted: {total_deleted}, errors: {errors}")
            
            # Update progress every 5 seconds max (to avoid rate limits on editing)
            if (datetime.now() - last_update).seconds >= 5:
                try:
                    await progress_msg.edit(
                        embed=Embed(
                            title="🔄 Purge Progress",
                            description=f"**Progress:** {channels_done}/{len(text_channels)} channels\n"
                                        f"**Current:** #{channel.name}\n"
                                        f"**Deleted:** {total_deleted} messages\n"
                                        f"**Skipped:** {total_skipped}\n"
                                        f"**Errors:** {errors}",
                            color=0x9c92d1
                        )
                    )
                    last_update = datetime.now()
                except:
                    pass  # Ignore edit failures, keep deleting
            
        except Exception as e:
            logger.error(f"Error in channel {channel.name}: {e}")
            channels_done += 1
    
    active_purges.pop(purge_key, None)
    
    # Save archive
    archive_file = None
    if should_archive and archive_data:
        archive_file = save_archive(str(user_id), username, archive_data, "server")
    
    archive_info = f"\n**Archived:** {archive_file}" if archive_file else ""
    
    # Final update
    final_embed = Embed(
        title="✅ Server Purge Complete",
        description=f"**Channels scanned:** {channels_done}\n"
                    f"**Messages deleted:** {total_deleted}\n"
                    f"**Skipped:** {total_skipped}\n"
                    f"**Errors:** {errors}"
                    f"{archive_info}",
        color=0x00ff00
    )
    
    try:
        await progress_msg.edit(embed=final_embed)
    except:
        # If we can't edit, send a new message
        await ctx.channel.send(embed=final_embed)


@component_callback(re.compile(r"^stop_purge:"))
async def stop_purge(ctx: interactions.ComponentContext):
    """Stop an active purge."""
    purge_key = ctx.custom_id.replace("stop_purge:", "")
    active_purges[purge_key] = False
    await ctx.send("Stopping purge...", ephemeral=True)