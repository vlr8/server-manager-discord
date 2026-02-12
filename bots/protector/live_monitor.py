"""
Live Content Monitor
Real-time message monitoring and auto-moderation for Discord.

This module provides:
- Real-time message scanning using @listen() events
- Automatic deletion of violating content
- Censored message reposting
- Logging and audit trail
- Slash commands for configuration

Add to your bot1.py:
    from live_monitor import setup_live_monitor
    setup_live_monitor(client)
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Set

import interactions
from interactions import (
    Client,
    Embed,
    SlashContext,
    OptionType,
    SlashCommandChoice,
    auto_defer,
    slash_command,
    slash_option,
    listen,
)
from interactions.api.events import MessageCreate

# Local imports
import common.moderation_db as mdb
from content_analyzer import ContentAnalyzer, get_analyzer

# Import your constants - adjust path as needed
try:
    from common.consts import guild_id, admin_role, support_role, mod_log_channel_id
except ImportError:
    # Fallback for testing
    guild_id = None
    admin_role = None
    support_role = None
    mod_log_channel_id = None

logger = logging.getLogger("LiveMonitor")

# ============== CONFIGURATION ==============

class MonitorConfig:
    """Configuration for the live monitor."""
    
    # Whether the monitor is active
    ENABLED = True
    
    # Channels to always ignore (add IDs)
    IGNORED_CHANNELS: Set[str] = set()
    
    # Roles that are immune to auto-moderation (add IDs)
    IMMUNE_ROLES: Set[int] = set()
    
    # Whether to repost censored messages
    REPOST_CENSORED = True
    
    # Whether to auto-timeout repeat offenders
    AUTO_TIMEOUT_ENABLED = True
    
    # Timeout duration for auto-timeout (seconds)
    AUTO_TIMEOUT_DURATION = 600  # 10 minutes
    
    # Offenses before auto-timeout kicks in
    OFFENSES_BEFORE_TIMEOUT = 3
    
    # Whether to DM users when their message is deleted
    DM_ON_DELETE = False
    
    # Cooldown between processing same user's messages (seconds)
    USER_COOLDOWN = 1.0


# Track recently processed messages to avoid double-processing
_recently_processed: Set[str] = set()
_user_cooldowns: dict = {}


# ============== CORE MONITOR FUNCTION ==============

async def process_message(
    client: Client,
    message: interactions.Message,
    config: MonitorConfig = MonitorConfig()
) -> bool:
    """
    Process a message through the content analyzer.
    
    Returns True if message was flagged and handled.
    """
    # Skip if monitor is disabled
    if not config.ENABLED:
        return False
    
    # Skip bot messages
    if message.author.bot:
        return False
    
    # Skip empty messages
    if not message.content or not message.content.strip():
        return False
    
    # Skip if already processed
    if str(message.id) in _recently_processed:
        return False
    
    # Skip ignored channels
    if str(message.channel.id) in config.IGNORED_CHANNELS:
        return False
    
    # Check if channel is monitored (if monitoring is selective)
    monitored_channels = mdb.get_monitored_channels()
    if monitored_channels and str(message.channel.id) not in monitored_channels:
        return False
    
    # Check user cooldown
    user_id = str(message.author.id)
    now = datetime.now()
    if user_id in _user_cooldowns:
        if (now - _user_cooldowns[user_id]).total_seconds() < config.USER_COOLDOWN:
            return False
    _user_cooldowns[user_id] = now
    
    # Check immune roles
    if hasattr(message.author, 'roles'):
        for role in message.author.roles:
            if role.id in config.IMMUNE_ROLES:
                return False
    
    # Mark as processed
    _recently_processed.add(str(message.id))
    
    # Cleanup old processed messages (keep last 1000)
    if len(_recently_processed) > 1000:
        _recently_processed.clear()
    
    # Analyze the message
    analyzer = get_analyzer()
    result = analyzer.analyze(message.content, author_id=user_id)
    
    if not result.is_flagged:
        return False
    
    # Message is flagged - take action
    logger.info(f"Flagged message from {message.author.display_name}: {result.reasons}")
    
    try:
        # Log to database
        mdb.log_flagged_message(
            message_id=str(message.id),
            channel_id=str(message.channel.id),
            channel_name=getattr(message.channel, 'name', 'Unknown'),
            author_id=user_id,
            author_name=str(message.author.display_name),
            original_content=message.content,
            censored_content=result.censored_content,
            flag_reason=','.join(result.reasons),
            matched_patterns=result.matched_words + result.matched_patterns,
            sentiment_score=result.sentiment_score,
            toxicity_score=result.toxicity_score,
            action_taken='deleted' if result.should_delete else 'flagged',
            auto_deleted=result.should_delete
        )
        
        # Log user offense
        mdb.log_user_offense(
            user_id=user_id,
            offense_type=result.reasons[0] if result.reasons else 'unknown',
            message_id=str(message.id),
            channel_id=str(message.channel.id)
        )
        
        # Delete if needed
        if result.should_delete:
            # Save reference to channel before deletion
            channel = message.channel
            author_name = str(message.author.display_name)
            author_avatar = message.author.avatar_url
            censored = result.censored_content
            
            # Delete the message
            await message.delete()
            logger.info(f"Deleted message {message.id}")
            
            # Repost censored version
            if config.REPOST_CENSORED and censored.strip():
                embed = Embed(
                    description=censored,
                    color=0xff6b6b,
                    timestamp=datetime.now()
                )
                embed.set_author(name=f"{author_name} (censored)", icon_url=author_avatar)
                embed.set_footer(text="Message contained prohibited content")
                
                await channel.send(embed=embed)
            
            # Check for auto-timeout
            if config.AUTO_TIMEOUT_ENABLED:
                offense_count = mdb.get_user_offense_count(user_id, hours=24)
                if offense_count >= config.OFFENSES_BEFORE_TIMEOUT or result.should_timeout:
                    try:
                        # Calculate timeout end time
                        timeout_until = datetime.now() + timedelta(seconds=config.AUTO_TIMEOUT_DURATION)
                        
                        # Get guild member and timeout
                        guild = client.get_guild(message.guild.id)
                        member = guild.get_member(int(user_id))
                        if member:
                            await member.timeout(timeout_until)
                            logger.info(f"Auto-timed out {author_name} for {config.AUTO_TIMEOUT_DURATION}s")
                    except Exception as e:
                        logger.error(f"Failed to timeout user: {e}")
        
        # Log to mod channel
        if mod_log_channel_id:
            await log_to_mod_channel(client, message, result)
        
        return True
        
    except Exception as e:
        logger.error(f"Error processing flagged message: {e}")
        return False


async def log_to_mod_channel(client: Client, message: interactions.Message, result):
    """Log the moderation action to the mod log channel."""
    try:
        mod_channel = client.get_channel(mod_log_channel_id)
        if not mod_channel:
            return
        
        embed = Embed(
            title="🚨 Auto-Moderation Action",
            color=0xff0000 if result.should_delete else 0xffaa00,
            timestamp=datetime.now()
        )
        
        embed.set_author(
            name=str(message.author.display_name),
            icon_url=message.author.avatar_url
        )
        
        embed.add_field(name="Channel", value=f"<#{message.channel.id}>", inline=True)
        embed.add_field(name="Action", value="Deleted" if result.should_delete else "Flagged", inline=True)
        embed.add_field(name="Toxicity", value=f"{result.toxicity_score:.2f}", inline=True)
        embed.add_field(name="Reasons", value=', '.join(result.reasons) or "None", inline=False)
        embed.add_field(name="Original Content", value=f"||{message.content[:500]}||", inline=False)
        
        if result.matched_words:
            embed.add_field(name="Matched Words", value=', '.join(result.matched_words[:10]), inline=False)
        
        await mod_channel.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Failed to log to mod channel: {e}")


# ============== EVENT LISTENER ==============

def setup_live_monitor(client: Client, config: MonitorConfig = None):
    """
    Set up the live monitor on a client.
    Call this in your bot setup.
    
    Usage:
        from live_monitor import setup_live_monitor
        setup_live_monitor(client)
    """
    if config is None:
        config = MonitorConfig()
    
    # Initialize database
    mdb.init_moderation_db()
    
    @listen(MessageCreate)
    async def on_monitored_message(event: MessageCreate):
        """Listen for new messages and process them."""
        await process_message(client, event.message, config)
    
    # Register the listener
    client.add_listener(on_monitored_message)
    logger.info("Live monitor initialized and listening")
    
    return on_monitored_message


# ============== ALTERNATIVE: STANDALONE LISTENER ==============
# If you prefer to copy this directly into bot1.py

LIVE_MONITOR_CODE = '''
# Add this to your bot1.py imports:
import moderation_db as mdb
from content_analyzer import get_analyzer

# Add this listener to your bot1.py:
@listen(MessageCreate)
async def on_monitored_message(event: MessageCreate):
    """Live content monitoring."""
    message = event.message
    
    # Skip bots and empty messages
    if message.author.bot or not message.content:
        return
    
    # Get monitored channels (empty = monitor all)
    monitored = mdb.get_monitored_channels()
    if monitored and str(message.channel.id) not in monitored:
        return
    
    # Analyze
    analyzer = get_analyzer()
    result = analyzer.analyze(message.content, str(message.author.id))
    
    if not result.is_flagged:
        return
    
    # Log to database
    mdb.log_flagged_message(
        message_id=str(message.id),
        channel_id=str(message.channel.id),
        channel_name=message.channel.name,
        author_id=str(message.author.id),
        author_name=message.author.display_name,
        original_content=message.content,
        censored_content=result.censored_content,
        flag_reason=','.join(result.reasons),
        matched_patterns=result.matched_words + result.matched_patterns,
        sentiment_score=result.sentiment_score,
        toxicity_score=result.toxicity_score,
        action_taken='deleted' if result.should_delete else 'flagged'
    )
    
    mdb.log_user_offense(
        str(message.author.id), result.reasons[0] if result.reasons else 'unknown',
        str(message.id), str(message.channel.id)
    )
    
    if result.should_delete:
        channel = message.channel
        author_name = message.author.display_name
        author_avatar = message.author.avatar_url
        censored = result.censored_content
        
        await message.delete()
        
        # Repost censored
        embed = interactions.Embed(
            description=censored,
            color=0xff6b6b
        )
        embed.set_author(name=f"{author_name} (censored)", icon_url=author_avatar)
        embed.set_footer(text="Message contained prohibited content")
        await channel.send(embed=embed)
        
        # Log to mod channel
        mod_channel = client.get_channel(mod_log_channel_id)
        if mod_channel:
            log_embed = interactions.Embed(
                title="🚨 Auto-Moderation",
                color=0xff0000
            )
            log_embed.add_field(name="User", value=f"<@{message.author.id}>", inline=True)
            log_embed.add_field(name="Channel", value=f"<#{message.channel.id}>", inline=True)
            log_embed.add_field(name="Reasons", value=', '.join(result.reasons), inline=False)
            log_embed.add_field(name="Content", value=f"||{message.content[:200]}||", inline=False)
            await mod_channel.send(embed=log_embed)
'''


# ============== SLASH COMMANDS ==============

@slash_command(
    name="monitor_add",
    description="Add a channel to live monitoring.",
    scopes=[guild_id] if guild_id else []
)
@slash_option(name="channel", description="Channel to monitor", required=True, opt_type=OptionType.CHANNEL)
@slash_option(name="level", description="Monitoring level (1=normal, 2=strict, 3=max)", required=False, opt_type=OptionType.INTEGER)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def monitor_add_cmd(ctx: SlashContext, channel: interactions.GuildText, level: int = 1):
    """Add a channel to monitoring."""
    if not (ctx.author.has_role(admin_role) or ctx.author.has_role(support_role)):
        await ctx.send("❌ Permission denied.", ephemeral=True)
        return
    
    mdb.add_monitored_channel(str(channel.id), channel.name, level)
    await ctx.send(f"✅ Now monitoring {channel.mention} at level {level}", ephemeral=True)


@slash_command(
    name="monitor_remove",
    description="Remove a channel from live monitoring.",
    scopes=[guild_id] if guild_id else []
)
@slash_option(name="channel", description="Channel to stop monitoring", required=True, opt_type=OptionType.CHANNEL)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def monitor_remove_cmd(ctx: SlashContext, channel: interactions.GuildText):
    """Remove a channel from monitoring."""
    if not (ctx.author.has_role(admin_role) or ctx.author.has_role(support_role)):
        await ctx.send("❌ Permission denied.", ephemeral=True)
        return
    
    mdb.remove_monitored_channel(str(channel.id))
    await ctx.send(f"✅ Stopped monitoring {channel.mention}", ephemeral=True)


@slash_command(
    name="monitor_list",
    description="List all monitored channels.",
    scopes=[guild_id] if guild_id else []
)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def monitor_list_cmd(ctx: SlashContext):
    """List monitored channels."""
    if not (ctx.author.has_role(admin_role) or ctx.author.has_role(support_role)):
        await ctx.send("❌ Permission denied.", ephemeral=True)
        return
    
    channels = mdb.get_monitored_channels()
    
    if not channels:
        await ctx.send("No channels being monitored (monitoring all channels by default).", ephemeral=True)
        return
    
    channel_list = [f"<#{ch_id}> (level {level})" for ch_id, level in channels.items()]
    await ctx.send(f"**Monitored Channels:**\n" + "\n".join(channel_list), ephemeral=True)


@slash_command(
    name="badword_add",
    description="Add a bad word to the filter.",
    scopes=[guild_id] if guild_id else []
)
@slash_option(name="word", description="Word to add", required=True, opt_type=OptionType.STRING)
@slash_option(name="severity", description="Severity 1-5 (5=instant delete)", required=False, opt_type=OptionType.INTEGER)
@slash_option(name="category", description="Category for organization", required=False, opt_type=OptionType.STRING)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def badword_add_cmd(ctx: SlashContext, word: str, severity: int = 3, category: str = "general"):
    """Add a bad word."""
    if not (ctx.author.has_role(admin_role) or ctx.author.has_role(support_role)):
        await ctx.send("❌ Permission denied.", ephemeral=True)
        return
    
    severity = max(1, min(5, severity))  # Clamp to 1-5
    
    if mdb.add_bad_word(word, severity, category):
        # Reload analyzer
        get_analyzer().reload()
        await ctx.send(f"✅ Added `{word}` (severity: {severity}, category: {category})", ephemeral=True)
    else:
        await ctx.send(f"⚠️ `{word}` already exists", ephemeral=True)


@slash_command(
    name="badword_list",
    description="List bad words in the filter.",
    scopes=[guild_id] if guild_id else []
)
@slash_option(name="category", description="Filter by category", required=False, opt_type=OptionType.STRING)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def badword_list_cmd(ctx: SlashContext, category: str = None):
    """List bad words."""
    if not (ctx.author.has_role(admin_role) or ctx.author.has_role(support_role)):
        await ctx.send("❌ Permission denied.", ephemeral=True)
        return
    
    words = mdb.get_bad_words()
    
    if category:
        words = [w for w in words if w.get('category') == category]
    
    if not words:
        await ctx.send("No bad words configured.", ephemeral=True)
        return
    
    # Group by severity
    by_severity = {}
    for w in words:
        sev = w['severity']
        if sev not in by_severity:
            by_severity[sev] = []
        by_severity[sev].append(f"`{w['word']}` ({w['match_count']} matches)")
    
    embed = Embed(title="Bad Word List", color=0x9c92d1)
    for sev in sorted(by_severity.keys(), reverse=True):
        embed.add_field(
            name=f"Severity {sev}",
            value=", ".join(by_severity[sev][:20]) or "None",
            inline=False
        )
    
    await ctx.send(embed=embed, ephemeral=True)


@slash_command(
    name="modstats",
    description="View moderation statistics.",
    scopes=[guild_id] if guild_id else []
)
@slash_option(name="days", description="Number of days to look back", required=False, opt_type=OptionType.INTEGER)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def modstats_cmd(ctx: SlashContext, days: int = 7):
    """View moderation stats."""
    if not (ctx.author.has_role(admin_role) or ctx.author.has_role(support_role)):
        await ctx.send("❌ Permission denied.", ephemeral=True)
        return
    
    stats = mdb.get_moderation_stats(days)
    
    embed = Embed(title=f"📊 Moderation Stats (Last {days} Days)", color=0x9c92d1)
    embed.add_field(name="Total Flagged", value=str(stats.get('total_flagged', 0)), inline=True)
    embed.add_field(name="Unique Offenders", value=str(stats.get('unique_offenders', 0)), inline=True)
    
    if stats.get('by_reason'):
        reasons = [f"{r}: {c}" for r, c in list(stats['by_reason'].items())[:5]]
        embed.add_field(name="Top Reasons", value="\n".join(reasons) or "None", inline=False)
    
    if stats.get('top_triggered_words'):
        words = [f"`{w['word']}`: {w['match_count']}" for w in stats['top_triggered_words'][:5]]
        embed.add_field(name="Most Triggered Words", value="\n".join(words) or "None", inline=False)
    
    # Repeat offenders
    offenders = mdb.get_repeat_offenders(min_offenses=3, days=days)
    if offenders:
        offender_list = [f"<@{o['user_id']}>: {o['offense_count']} offenses" for o in offenders[:5]]
        embed.add_field(name="Repeat Offenders", value="\n".join(offender_list), inline=False)
    
    await ctx.send(embed=embed, ephemeral=True)


@slash_command(
    name="reload_filter",
    description="Reload bad words and patterns from database.",
    scopes=[guild_id] if guild_id else []
)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def reload_filter_cmd(ctx: SlashContext):
    """Reload the content analyzer."""
    if not (ctx.author.has_role(admin_role) or ctx.author.has_role(support_role)):
        await ctx.send("❌ Permission denied.", ephemeral=True)
        return
    
    analyzer = get_analyzer()
    analyzer.reload()
    
    await ctx.send(
        f"✅ Reloaded filter:\n"
        f"• {len(analyzer.bad_words)} bad words\n"
        f"• {len(analyzer.patterns)} learned patterns",
        ephemeral=True
    )
