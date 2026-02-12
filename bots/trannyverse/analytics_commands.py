"""
Analytics Slash Commands Module
Add these commands to your bot1.py to display analytics in Discord.

Usage: Import and register with your existing bot client
"""

import interactions
from interactions import (
    slash_command,
    slash_option,
    SlashContext,
    OptionType,
    SlashCommandChoice,
    auto_defer,
    Embed,
)
from datetime import datetime
from common import db

# Import your guild_id and role IDs from consts
from common.consts import guild_id, admin_role, support_role


def create_bar_chart(values: list, max_width: int = 20) -> list:
    """Create simple text-based bar chart."""
    if not values:
        return []
    max_val = max(values)
    if max_val == 0:
        return ['░' * max_width for _ in values]
    return ['█' * int((v / max_val) * max_width) + '░' * (max_width - int((v / max_val) * max_width)) for v in values]


def format_number(n: int) -> str:
    """Format large numbers with K/M suffix."""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


# ============== SLASH COMMANDS ==============

""" @slash_command(name="server_stats", description="Show overall server statistics.", scopes=[guild_id])
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def server_stats_cmd(ctx: SlashContext):
    stats = db.get_server_overview()
    
    embed = Embed(
        title="📊 Server Statistics",
        color=0x9c92d1,
        timestamp=datetime.now()
    )
    
    # Main stats
    embed.add_field(
        name="📝 Messages",
        value=f"**{format_number(stats['total_messages'])}** total\n"
              f"**{format_number(stats['total_words'])}** words\n"
              f"**{format_number(stats['total_replies'])}** replies",
        inline=True
    )
    
    embed.add_field(
        name="👥 Users",
        value=f"**{stats['unique_users']}** unique chatters\n"
              f"**{stats['active_channels']}** active channels\n"
              f"**{format_number(stats['total_attachments'])}** attachments",
        inline=True
    )
    
    # Top performers
    if stats['top_channel']:
        embed.add_field(
            name="🏆 Most Active Channel",
            value=f"**{stats['top_channel']['channel_name']}**\n{format_number(stats['top_channel']['count'])} messages",
            inline=True
        )
    
    if stats['top_user']:
        embed.add_field(
            name="👑 Most Active User",
            value=f"**{stats['top_user']['author_name']}**\n{format_number(stats['top_user']['count'])} messages",
            inline=True
        )
    
    # Time range
    if stats['earliest_message'] and stats['latest_message']:
        embed.set_footer(text=f"Data from {stats['earliest_message'][:10]} to {stats['latest_message'][:10]}")
    
    await ctx.send(embed=embed)
 """

@slash_command(name="channel_stats", description="Show channel activity rankings.", scopes=[guild_id])
@slash_option(
    name="limit",
    description="Number of channels to show (default 10)",
    required=False,
    opt_type=OptionType.INTEGER
)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def channel_stats_cmd(ctx: SlashContext, limit: int = 10):
    """Display channel statistics."""
    channels = db.get_channel_stats(limit=min(limit, 25))
    
    if not channels:
        await ctx.send("No channel data available yet.", ephemeral=True)
        return
    
    embed = Embed(
        title="📊 Channel Activity Rankings",
        color=0x9c92d1,
        timestamp=datetime.now()
    )
    
    # Create the leaderboard
    bars = create_bar_chart([c['message_count'] for c in channels], max_width=15)
    
    description_lines = []
    for i, (channel, bar) in enumerate(zip(channels, bars), 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"`{i}.`"
        description_lines.append(
            f"{medal} **{channel['channel_name']}**\n"
            f"   `{bar}` {format_number(channel['message_count'])} msgs • {channel['unique_users']} users"
        )
    
    embed.description = "\n".join(description_lines)
    embed.set_footer(text=f"Showing top {len(channels)} channels")
    
    await ctx.send(embed=embed)


@slash_command(name="user_stats", description="Show most active users.", scopes=[guild_id])
@slash_option(
    name="limit",
    description="Number of users to show (default 10)",
    required=False,
    opt_type=OptionType.INTEGER
)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def user_stats_cmd(ctx: SlashContext, limit: int = 10):
    """Display user activity statistics."""
    users = db.get_user_stats(limit=min(limit, 25))
    
    if not users:
        await ctx.send("No user data available yet.", ephemeral=True)
        return
    
    embed = Embed(
        title="👥 Most Active Users",
        color=0x9c92d1,
        timestamp=datetime.now()
    )
    
    bars = create_bar_chart([u['message_count'] for u in users], max_width=12)
    
    description_lines = []
    for i, (user, bar) in enumerate(zip(users, bars), 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"`{i}.`"
        description_lines.append(
            f"{medal} **{user['author_name']}**\n"
            f"   `{bar}` {format_number(user['message_count'])} msgs • "
            f"~{user['avg_words_per_msg']} words/msg • {user['channels_active']} channels"
        )
    
    embed.description = "\n".join(description_lines)
    embed.set_footer(text=f"Showing top {len(users)} users")
    
    await ctx.send(embed=embed)


@slash_command(name="activity_hours", description="Show when the server is most active.", scopes=[guild_id])
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def activity_hours_cmd(ctx: SlashContext):
    """Display hourly activity heatmap."""
    hourly = db.get_hourly_activity()
    
    embed = Embed(
        title="🕐 Hourly Activity (UTC)",
        color=0x9c92d1,
        timestamp=datetime.now()
    )
    
    # Find peak hours
    max_activity = max(hourly.values()) if hourly else 0
    peak_hours = [h for h, v in hourly.items() if v == max_activity]
    
    # Create visual representation
    # Split into 4 rows of 6 hours each
    activity_blocks = []
    for hour in range(24):
        count = hourly.get(hour, 0)
        if max_activity > 0:
            intensity = count / max_activity
            if intensity > 0.75:
                block = "🟩"
            elif intensity > 0.5:
                block = "🟨"
            elif intensity > 0.25:
                block = "🟧"
            elif intensity > 0:
                block = "🟥"
            else:
                block = "⬛"
        else:
            block = "⬛"
        activity_blocks.append(block)
    
    # Format as grid
    grid_lines = [
        f"**00-05** {''.join(activity_blocks[0:6])}",
        f"**06-11** {''.join(activity_blocks[6:12])}",
        f"**12-17** {''.join(activity_blocks[12:18])}",
        f"**18-23** {''.join(activity_blocks[18:24])}",
    ]
    
    embed.description = "\n".join(grid_lines)
    embed.add_field(
        name="Legend",
        value="🟩 Peak • 🟨 High • 🟧 Medium • 🟥 Low • ⬛ None",
        inline=False
    )
    
    if peak_hours:
        embed.add_field(
            name="⚡ Peak Hour(s)",
            value=f"{', '.join(f'{h}:00' for h in peak_hours)} UTC",
            inline=True
        )
    
    total_msgs = sum(hourly.values())
    embed.add_field(
        name="📊 Total Messages",
        value=format_number(total_msgs),
        inline=True
    )
    
    await ctx.send(embed=embed)


@slash_command(name="user_profile", description="Show detailed stats for a specific user.", scopes=[guild_id])
@slash_option(
    name="user",
    description="The user to look up",
    required=True,
    opt_type=OptionType.USER
)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def user_profile_cmd(ctx: SlashContext, user: interactions.User):
    """Display detailed statistics for a specific user."""
    user_id = str(user.id)
    
    # Get user messages for stats
    messages = db.get_user_messages(user_id)
    
    if not messages:
        await ctx.send(f"No message data found for {user.mention}.", ephemeral=True)
        return
    
    # Calculate stats
    total_msgs = len(messages)
    total_words = sum(len(m['content'].split()) for m in messages)
    avg_words = total_words / total_msgs if total_msgs > 0 else 0
    
    # Channel distribution
    channel_counts = {}
    for msg in messages:
        ch = msg['channel_name']
        channel_counts[ch] = channel_counts.get(ch, 0) + 1
    
    top_channels = sorted(channel_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # Get vocabulary
    top_words = db.get_user_vocabulary(user_id, top_n=10)
    
    embed = Embed(
        title=f"📊 Profile: {user.display_name}",
        color=0x9c92d1,
        timestamp=datetime.now()
    )
    embed.set_thumbnail(url=user.avatar_url)
    
    embed.add_field(
        name="📝 Messages",
        value=f"**{format_number(total_msgs)}** total\n"
              f"**{format_number(total_words)}** words\n"
              f"**~{avg_words:.1f}** words/msg",
        inline=True
    )
    
    embed.add_field(
        name="📅 Active Period",
        value=f"First: {messages[0]['timestamp'][:10]}\n"
              f"Last: {messages[-1]['timestamp'][:10]}",
        inline=True
    )
    
    if top_channels:
        channel_text = "\n".join([f"• **{ch}**: {count}" for ch, count in top_channels])
        embed.add_field(
            name="📍 Top Channels",
            value=channel_text,
            inline=False
        )
    
    if top_words:
        word_text = ", ".join([f"`{word}`" for word, count in top_words])
        embed.add_field(
            name="💬 Common Words",
            value=word_text,
            inline=False
        )
    
    await ctx.send(embed=embed)


@slash_command(name="daily_activity", description="Show recent daily activity.", scopes=[guild_id])
@slash_option(
    name="days",
    description="Number of days to show (default 14)",
    required=False,
    opt_type=OptionType.INTEGER
)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def daily_activity_cmd(ctx: SlashContext, days: int = 14):
    """Display daily message activity."""
    daily = db.get_daily_activity(days=min(days, 30))
    
    if not daily:
        await ctx.send("No recent activity data available.", ephemeral=True)
        return
    
    embed = Embed(
        title=f"📈 Daily Activity (Last {len(daily)} days)",
        color=0x9c92d1,
        timestamp=datetime.now()
    )
    
    # Reverse to show oldest first
    daily = list(reversed(daily))
    
    bars = create_bar_chart([d['message_count'] for d in daily], max_width=15)
    
    description_lines = []
    for day, bar in zip(daily, bars):
        date_str = day['date'][5:] if day['date'] else "N/A"  # MM-DD format
        description_lines.append(
            f"`{date_str}` `{bar}` {format_number(day['message_count'])} ({day['unique_users']} users)"
        )
    
    embed.description = "\n".join(description_lines[-15:])  # Limit display
    
    # Summary stats
    total_msgs = sum(d['message_count'] for d in daily)
    avg_msgs = total_msgs / len(daily) if daily else 0
    
    embed.set_footer(text=f"Total: {format_number(total_msgs)} • Avg: {format_number(int(avg_msgs))}/day")
    
    await ctx.send(embed=embed)


@slash_command(name="export_user", description="Export a user's messages for chatbot training.", scopes=[guild_id])
@slash_option(
    name="user",
    description="The user to export",
    required=True,
    opt_type=OptionType.USER
)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def export_user_cmd(ctx: SlashContext, user: interactions.User):
    """Export a user's messages to a text file (admin only)."""
    # Check permissions
    if not (ctx.author.has_role(admin_role) or ctx.author.has_role(support_role)):
        await ctx.send("You don't have permission to use this command.", ephemeral=True)
        return
    
    user_id = str(user.id)
    output_path = f"user_corpus_{user_id}.txt"
    
    count = db.export_user_corpus(user_id, output_path)
    
    if count == 0:
        await ctx.send(f"No messages found for {user.mention}.", ephemeral=True)
        return
    
    await ctx.send(
        f"Exported **{count}** messages from {user.mention} to `{output_path}`.\n"
        f"You can use this file to train a chatbot or analyze their writing style.",
        ephemeral=True
    )


""" @slash_command(name="channel_compare", description="Compare activity between channels.", scopes=[guild_id])
@slash_option(name="channel1", description="First channel", required=True, opt_type=OptionType.CHANNEL)
@slash_option(name="channel2", description="Second channel", required=True, opt_type=OptionType.CHANNEL)
@slash_option(name="channel3", description="Third channel (optional)", required=False, opt_type=OptionType.CHANNEL)
@auto_defer(enabled=True, ephemeral=False, time_until_defer=0.0)
async def channel_compare_cmd(
    ctx: SlashContext, 
    channel1: interactions.BaseChannel, 
    channel2: interactions.BaseChannel,
    channel3: interactions.BaseChannel = None
):
    channel_ids = [str(channel1.id), str(channel2.id)]
    if channel3:
        channel_ids.append(str(channel3.id))
    
    channels = db.get_channel_activity_comparison(channel_ids)
    
    if not channels:
        await ctx.send("No data found for the specified channels.", ephemeral=True)
        return
    
    embed = Embed(
        title="📊 Channel Comparison",
        color=0x9c92d1,
        timestamp=datetime.now()
    )
    
    for ch in channels:
        reply_pct = ch['reply_percentage'] or 0
        embed.add_field(
            name=f"#{ch['channel_name']}",
            value=f"📝 **{format_number(ch['total_messages'])}** messages\n"
                  f"👥 **{ch['unique_users']}** users\n"
                  f"📏 **{ch['avg_msg_length']}** avg words\n"
                  f"💬 **{reply_pct:.1f}%** replies",
            inline=True
        )
    
    await ctx.send(embed=embed)


@slash_command(name="search_messages", description="Search for messages containing specific text.", scopes=[guild_id])
@slash_option(name="query", description="Text to search for", required=True, opt_type=OptionType.STRING)
@slash_option(name="limit", description="Max results (default 10)", required=False, opt_type=OptionType.INTEGER)
@auto_defer(enabled=True, ephemeral=True, time_until_defer=0.0)
async def search_messages_cmd(ctx: SlashContext, query: str, limit: int = 10):
    # Check permissions
    if not (ctx.author.has_role(admin_role) or ctx.author.has_role(support_role)):
        await ctx.send("You don't have permission to use this command.", ephemeral=True)
        return
    
    results = db.search_messages(query, limit=min(limit, 25))
    
    if not results:
        await ctx.send(f"No messages found containing '{query}'.", ephemeral=True)
        return
    
    embed = Embed(
        title=f"🔍 Search Results: '{query}'",
        color=0x9c92d1,
        timestamp=datetime.now()
    )
    
    description_lines = []
    for msg in results[:10]:
        content_preview = msg['content'][:100] + "..." if len(msg['content']) > 100 else msg['content']
        description_lines.append(
            f"**{msg['author_name']}** in #{msg['channel_name']}\n"
            f"> {content_preview}\n"
        )
    
    embed.description = "\n".join(description_lines)
    embed.set_footer(text=f"Found {len(results)} results")
    
    await ctx.send(embed=embed, ephemeral=True)
 """

# ============== BOT INTEGRATION FUNCTION ==============

def register_analytics_commands(client):
    """
    Call this function to register all analytics commands with your bot client.
    
    Usage in bot1.py:
        from analytics_commands import register_analytics_commands
        register_analytics_commands(client)
    """
    # The commands are already decorated, they just need the client to be aware of them
    # In interactions.py, commands are auto-registered when defined with @slash_command
    # So this function is mainly for documentation purposes
    
    # Initialize the database
    db.init_database()
    
    print("Analytics commands registered successfully!")
    print("Available commands: /server_stats, /channel_stats, /user_stats, /activity_hours,")
    print("                    /user_profile, /daily_activity, /export_user, /channel_compare,")
    print("                    /search_messages")
