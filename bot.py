import os
import re
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional, List

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

import database as db

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("=" * 50)
    print("ERROR: DISCORD_TOKEN is missing!")
    print("Set the DISCORD_TOKEN environment variable.")
    print("On Railway/Render/etc: go to Variables and add DISCORD_TOKEN")
    print("=" * 50)
    raise SystemExit("DISCORD_TOKEN not found")

# --------------- Helpers ---------------

TWEET_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/\w+/status/(\d+)",
    re.IGNORECASE
)


def extract_tweet_id(url: str) -> Optional[str]:
    match = TWEET_URL_PATTERN.search(url)
    return match.group(1) if match else None


def format_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"{hours}h"
    return f"{hours}h {mins}m"


def format_timestamp(ts: float) -> str:
    return f"<t:{int(ts)}:R>"


async def fetch_tweet_preview(username: str, tweet_id: str) -> dict:
    """
    Fetch tweet text, avatar, and image via public vxtwitter API (no X API key).
    Returns dict with keys: text, author, avatar, image (may be None).
    """
    import aiohttp

    url = f"https://api.vxtwitter.com/{username}/status/{tweet_id}"
    result = {"text": None, "author": username, "avatar": None, "image": None}
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"User-Agent": "EngageBot/1.0"}) as resp:
                if resp.status != 200:
                    return result
                data = await resp.json()
    except Exception as e:
        print(f"Tweet preview fetch failed: {e}")
        return result

    result["text"] = data.get("text") or data.get("tweet") or None
    result["author"] = data.get("user_name") or data.get("username") or username

    # Avatar
    result["avatar"] = (
        data.get("user_profile_image_url")
        or data.get("profile_image_url")
        or data.get("user_profile_image_url_https")
    )
    if result["avatar"] and "_normal" in result["avatar"]:
        result["avatar"] = result["avatar"].replace("_normal", "_400x400")

    # Image / thumbnail
    media_ext = data.get("media_extended") or []
    if media_ext and isinstance(media_ext, list):
        first = media_ext[0]
        result["image"] = first.get("thumbnail_url") or first.get("url")
    if not result["image"]:
        media_urls = data.get("mediaURLs") or []
        if media_urls:
            # Prefer image over video mp4 for embed thumbnail
            for m in media_urls:
                if any(m.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
                    result["image"] = m
                    break
            if not result["image"]:
                result["image"] = media_urls[0]

    return result


# --------------- Views / Buttons ---------------

def extract_twitter_username_from_url(url: str) -> Optional[str]:
    """Extract @username from an x.com or twitter.com status URL."""
    match = re.search(
        r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/([^/]+)/status/",
        url,
        re.IGNORECASE
    )
    if match:
        username = match.group(1).lower()
        if username not in ("i", "intent", "share"):
            return username
    return None


class ClaimModal(discord.ui.Modal, title="Prove You Completed the Tasks"):
    def __init__(self, tweet_db_id: int, points: int, ends_at: float, types: str):
        super().__init__()
        self.tweet_db_id = tweet_db_id
        self.points = points
        self.ends_at = ends_at
        self.types = types or ""
        self.requires_reply = "reply" in self.types

        self.confirmation = discord.ui.TextInput(
            label="Type YES to confirm you did ALL tasks",
            placeholder="YES",
            required=True,
            max_length=10
        )
        self.add_item(self.confirmation)

        # Always ask for proof when reply is required.
        # For like/retweet-only we still ask for optional proof but make reply mandatory only if needed.
        if self.requires_reply:
            self.proof_link = discord.ui.TextInput(
                label="Paste link to YOUR reply on the tweet",
                placeholder="https://x.com/YourUsername/status/123456789",
                required=True,
                max_length=250,
                style=discord.TextStyle.short
            )
            self.add_item(self.proof_link)
        else:
            # Optional proof for like/retweet (helps admins review)
            self.proof_link = discord.ui.TextInput(
                label="Optional: paste any proof link (reply/RT)",
                placeholder="https://x.com/... (optional but recommended)",
                required=False,
                max_length=250,
                style=discord.TextStyle.short
            )
            self.add_item(self.proof_link)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if time.time() > self.ends_at:
            await interaction.followup.send("❌ This quest has expired.", ephemeral=True)
            return

        if self.confirmation.value.strip().upper() != "YES":
            await interaction.followup.send(
                "❌ You must type **YES** to confirm you completed the tasks.",
                ephemeral=True
            )
            return

        twitter = await db.get_twitter(interaction.user.id, interaction.guild_id)
        if not twitter:
            await interaction.followup.send(
                "❌ Link your Twitter first with `/set twitter your_username`",
                ephemeral=True
            )
            return

        twitter = twitter.lower().lstrip("@")
        proof_url = None
        if hasattr(self, "proof_link") and self.proof_link.value:
            proof_url = self.proof_link.value.strip()

        # Strict check when reply is required
        if self.requires_reply:
            if not proof_url:
                await interaction.followup.send(
                    "❌ You must paste the link to **your own reply**.",
                    ephemeral=True
                )
                return

            if "x.com/" not in proof_url.lower() and "twitter.com/" not in proof_url.lower():
                await interaction.followup.send(
                    "❌ Invalid link. Paste a full X/Twitter status link.",
                    ephemeral=True
                )
                return

            link_username = extract_twitter_username_from_url(proof_url)
            if not link_username:
                await interaction.followup.send(
                    "❌ Could not read the username from that link.\n"
                    "Use a link like: `https://x.com/YourUsername/status/123456`",
                    ephemeral=True
                )
                return

            if link_username != twitter:
                await interaction.followup.send(
                    f"❌ The reply link belongs to **@{link_username}**, "
                    f"but your linked account is **@{twitter}**.\n\n"
                    f"You must reply with the same account you linked using `/set twitter`.",
                    ephemeral=True
                )
                return

        # Optional proof for non-reply quests: if provided, still check username match
        elif proof_url:
            if "x.com/" in proof_url.lower() or "twitter.com/" in proof_url.lower():
                link_username = extract_twitter_username_from_url(proof_url)
                if link_username and link_username != twitter:
                    await interaction.followup.send(
                        f"❌ Proof link is from **@{link_username}**, "
                        f"but you linked **@{twitter}**. Use the same account.",
                        ephemeral=True
                    )
                    return

        tweet = await db.get_tweet(self.tweet_db_id)
        if not tweet or not tweet["active"]:
            await interaction.followup.send("❌ This quest is no longer active.", ephemeral=True)
            return

        already = await db.has_claimed(self.tweet_db_id, interaction.user.id)
        if already:
            await interaction.followup.send("❌ You already claimed this quest.", ephemeral=True)
            return

        success = await db.claim_tweet(
            self.tweet_db_id,
            interaction.user.id,
            interaction.guild_id,
            self.points,
            twitter_handle=twitter,
            proof_url=proof_url
        )

        if not success:
            await interaction.followup.send("❌ Could not claim. Try again later.", ephemeral=True)
            return

        new_balance = await db.add_points(
            interaction.user.id,
            interaction.guild_id,
            self.points
        )

        msg = (
            f"✅ **+{self.points} points** claimed!\n"
            f"Linked Twitter: **@{twitter}**\n"
            f"New balance: **{new_balance}** points"
        )
        if proof_url:
            msg += "\n📎 Proof link saved for admin review."

        await interaction.followup.send(msg, ephemeral=True)

        # Update claims counter
        try:
            if interaction.message and interaction.message.embeds:
                embed = interaction.message.embeds[0]
                tweet = await db.get_tweet(self.tweet_db_id)
                for i, field in enumerate(embed.fields):
                    if field.name == "📊 Claims":
                        embed.set_field_at(
                            i, name="📊 Claims",
                            value=str(tweet["total_claims"]), inline=True
                        )
                        await interaction.message.edit(embed=embed)
                        break
        except Exception:
            pass


class ClaimView(discord.ui.View):
    def __init__(self, tweet_db_id: int, points: int, ends_at: float, types: str = ""):
        super().__init__(timeout=None)
        self.tweet_db_id = tweet_db_id
        self.points = points
        self.ends_at = ends_at
        self.types = types
        self.claim_button.custom_id = f"claim_{tweet_db_id}"

    @discord.ui.button(label="Collect Reward", style=discord.ButtonStyle.green, emoji="✅", row=0)
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Quick checks before opening modal
        if time.time() > self.ends_at:
            await interaction.response.send_message("❌ This quest has expired.", ephemeral=True)
            return

        twitter = await db.get_twitter(interaction.user.id, interaction.guild_id)
        if not twitter:
            await interaction.response.send_message(
                "❌ You must link your Twitter/X account first!\n"
                "Use `/set twitter your_username` (without @)",
                ephemeral=True
            )
            return

        already = await db.has_claimed(self.tweet_db_id, interaction.user.id)
        if already:
            await interaction.response.send_message("❌ You already claimed this quest.", ephemeral=True)
            return

        # Open confirmation / proof modal
        modal = ClaimModal(self.tweet_db_id, self.points, self.ends_at, self.types or "")
        await interaction.response.send_modal(modal)


# --------------- Bot ---------------

class EngageBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await db.init_db()
        self.cleanup_task.start()
        # Global sync (can be slow). Guild sync is done in on_ready for instant update.
        try:
            await self.tree.sync()
            print("Global slash commands synced.")
        except Exception as e:
            print(f"Global sync warning: {e}")

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")

        # Instant guild-specific sync so new commands appear immediately
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                print(f"Synced {len(synced)} commands to guild: {guild.name} ({guild.id})")
            except Exception as e:
                print(f"Failed to sync guild {guild.name}: {e}")

        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="tweet engagement|/help_engage"
        )
        await self.change_presence(activity=activity)

    @tasks.loop(minutes=5)
    async def cleanup_task(self):
        await db.deactivate_expired_tweets()


bot = EngageBot()


# --------------- Slash Commands ---------------

@bot.tree.command(name="tweet", description="Create a tweet engagement quest")
@app_commands.describe(
    link="The full X/Twitter post URL",
    type="What users must do on the tweet",
    duration="How long the quest lasts",
    points="Points awarded when all tasks are completed",
    ping_role="Optional role to ping"
)
@app_commands.choices(type=[
    app_commands.Choice(name="Like", value="like"),
    app_commands.Choice(name="Comment (Reply)", value="reply"),
    app_commands.Choice(name="Like + Comment", value="like,reply"),
])
@app_commands.choices(duration=[
    app_commands.Choice(name="30 minutes", value=30),
    app_commands.Choice(name="1 hour", value=60),
    app_commands.Choice(name="3 hours", value=180),
    app_commands.Choice(name="6 hours", value=360),
    app_commands.Choice(name="12 hours", value=720),
    app_commands.Choice(name="24 hours", value=1440),
    app_commands.Choice(name="48 hours", value=2880),
])
@app_commands.default_permissions(manage_messages=True)
async def tweet_command(
    interaction: discord.Interaction,
    link: str,
    type: app_commands.Choice[str],
    duration: app_commands.Choice[int],
    points: app_commands.Range[int, 1, 10000],
    ping_role: Optional[discord.Role] = None
):
    """Admin command to post a tweet quest (Engage-style layout)."""
    await interaction.response.defer()

    tweet_id = extract_tweet_id(link)
    if not tweet_id:
        await interaction.followup.send(
            "❌ Invalid X/Twitter URL. Use a full post link like:\n"
            "`https://x.com/username/status/1234567890`",
            ephemeral=True
        )
        return

    username_match = re.search(r"(?:twitter\.com|x\.com)/([^/]+)/status/", link, re.IGNORECASE)
    username = username_match.group(1) if username_match else "Unknown"
    clean_url = f"https://x.com/{username}/status/{tweet_id}"

    types = type.value
    duration_min = duration.value

    tweet_db_id = await db.create_tweet(
        guild_id=interaction.guild_id,
        channel_id=interaction.channel_id,
        tweet_url=clean_url,
        types=types,
        points=points,
        duration_minutes=duration_min,
        created_by=interaction.user.id,
        tweet_id=tweet_id
    )

    ends_at = time.time() + (duration_min * 60)

    if duration_min < 60:
        expires_text = f"in {duration_min} minutes"
    elif duration_min == 60:
        expires_text = "in an hour"
    elif duration_min < 1440:
        expires_text = f"in {duration_min // 60} hours"
    elif duration_min == 1440:
        expires_text = "in a day"
    else:
        expires_text = f"in {duration_min // 1440} days"

    # ---- Message text (matches real Engage layout) ----
    content_lines = [
        f"**{username}** just posted :",
        clean_url,
        "",
        "**Engage to collect your points**",
        f"Expires **{expires_text}**",
        "",
        f"•  `{points} points` will be given only if all tasks are completed!"
    ]
    if ping_role:
        content_lines.append(ping_role.mention)
    content = "\n".join(content_lines)

    # ---- Fetch real tweet text + image thumbnail ----
    preview = await fetch_tweet_preview(username, tweet_id)

    tasks_bits = []
    if "like" in types:
        tasks_bits.append("❤️ Like")
    if "reply" in types:
        tasks_bits.append("💬 Comment")
    tasks_line = " · ".join(tasks_bits) if tasks_bits else types

    # Build description like a real tweet card
    tweet_text = preview.get("text") or ""
    if len(tweet_text) > 400:
        tweet_text = tweet_text[:397] + "..."

    desc_parts = []
    if tweet_text:
        desc_parts.append(tweet_text)
    desc_parts.append(f"\n[Open this post on X]({clean_url})")
    desc_parts.append(f"\n**Tasks:** {tasks_line}")
    desc_parts.append(f"**Reward:** `{points} points`")
    desc_parts.append(f"**Ends:** {format_timestamp(ends_at)}")
    desc_parts.append(f"**Quest ID:** `#{tweet_db_id}`")

    embed = discord.Embed(
        description="\n".join(desc_parts),
        color=0x1DA1F2
    )

    author_name = preview.get("author") or username
    avatar = preview.get("avatar") or (
        "https://abs.twimg.com/sticky/default_profile_images/default_profile_400x400.png"
    )
    embed.set_author(
        name=f"{author_name}",
        url=f"https://x.com/{username}",
        icon_url=avatar
    )

    # Big thumbnail / image from the X post
    if preview.get("image"):
        embed.set_image(url=preview["image"])

    embed.set_footer(text=f"Quest #{tweet_db_id} · Powered by Engage Bot")

    # ---- Buttons: Like / Comment (open tweet) + Collect ----
    view = ClaimView(tweet_db_id, points, ends_at, types=types)

    view.add_item(discord.ui.Button(
        style=discord.ButtonStyle.link,
        label="Like",
        url=clean_url,
        emoji="❤️",
        row=1
    ))
    view.add_item(discord.ui.Button(
        style=discord.ButtonStyle.link,
        label="Comment",
        url=clean_url,
        emoji="💬",
        row=1
    ))

    # Rename claim button label to "Collect Reward"
    for item in view.children:
        if isinstance(item, discord.ui.Button) and item.style == discord.ButtonStyle.green:
            item.label = "Collect Reward"
            item.emoji = "✅"
            break

    msg = await interaction.followup.send(
        content=content,
        embed=embed,
        view=view,
        allowed_mentions=discord.AllowedMentions(roles=True)
    )
    await db.set_tweet_message_id(tweet_db_id, msg.id)

    # Confirmation only visible to the admin
    try:
        await interaction.followup.send(
            f"✅ Quest **#{tweet_db_id}** created successfully!",
            ephemeral=True
        )
    except Exception:
        pass


@bot.tree.command(name="set", description="Link your Twitter/X account")
@app_commands.describe(
    platform="What to set",
    value="Your Twitter/X username (without @)"
)
@app_commands.choices(platform=[
    app_commands.Choice(name="twitter", value="twitter"),
])
async def set_command(
    interaction: discord.Interaction,
    platform: app_commands.Choice[str],
    value: str
):
    """Link your Twitter/X username so you can claim points."""
    if platform.value != "twitter":
        await interaction.response.send_message("Only Twitter is supported right now.", ephemeral=True)
        return

    handle = value.lstrip("@").strip()
    if not handle or len(handle) > 15 or " " in handle:
        await interaction.response.send_message(
            "❌ Invalid Twitter username.\nExample: `/set twitter elonmusk`",
            ephemeral=True
        )
        return

    # Basic character check
    if not re.match(r"^[A-Za-z0-9_]+$", handle):
        await interaction.response.send_message(
            "❌ Twitter usernames can only contain letters, numbers and underscores.",
            ephemeral=True
        )
        return

    await db.set_twitter(interaction.user.id, interaction.guild_id, handle)

    embed = discord.Embed(
        title="✅ Twitter Linked",
        description=f"Your account is now linked to **@{handle}**",
        color=0x1DA1F2
    )
    embed.add_field(
        name="Next step",
        value="You can now click **Claim Points** on tweet quests.",
        inline=False
    )
    embed.set_footer(text="You can change it anytime by running /set twitter again")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="balance", description="Check your points balance")
@app_commands.describe(user="User to check (leave empty for yourself)")
async def balance_command(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    target = user or interaction.user
    data = await db.get_user(target.id, interaction.guild_id)

    twitter = data.get("twitter_handle")
    twitter_text = f"@{twitter}" if twitter else "*Not linked* — use `/set twitter`"

    embed = discord.Embed(
        title=f"💰 {target.display_name}'s Balance",
        color=0x57F287
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="Current Points", value=f"**{data['points']}**", inline=True)
    embed.add_field(name="Total Earned", value=f"{data['total_earned']}", inline=True)
    embed.add_field(name="Tweets Engaged", value=f"{data['tweets_engaged']}", inline=True)
    embed.add_field(name="Twitter / X", value=twitter_text, inline=False)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard", description="Show the points leaderboard")
async def leaderboard_command(interaction: discord.Interaction):
    rows = await db.get_leaderboard(interaction.guild_id, limit=10)

    if not rows:
        await interaction.response.send_message("No one has points yet. Be the first!", ephemeral=True)
        return

    description = []
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(rows):
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        user = interaction.guild.get_member(row["user_id"])
        name = user.display_name if user else f"User {row['user_id']}"
        description.append(
            f"{medal} **{name}** — `{row['points']}` pts "
            f"(engaged: {row['tweets_engaged']})"
        )

    embed = discord.Embed(
        title="🏆 Engagement Leaderboard",
        description="\n".join(description),
        color=0xFEE75C
    )
    embed.set_footer(text="Top 10 by current points")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="stats", description="Show server engagement stats")
async def stats_command(interaction: discord.Interaction):
    gstats = await db.get_guild_stats(interaction.guild_id)
    active = await db.get_active_tweets(interaction.guild_id)

    embed = discord.Embed(
        title="📈 Server Engage Stats",
        color=0xEB459E
    )
    embed.add_field(name="Total Quests Created", value=str(gstats["total_tweets"]), inline=True)
    embed.add_field(name="Total Claims", value=str(gstats["total_claims"]), inline=True)
    embed.add_field(name="Points Distributed", value=str(gstats["total_points_distributed"]), inline=True)
    embed.add_field(name="Active Quests", value=str(len(active)), inline=True)

    if active:
        active_list = "\n".join(
            f"• Quest #{t['id']} — {t['points']} pts — ends {format_timestamp(t['ends_at'])}"
            for t in active[:5]
        )
        embed.add_field(name="Currently Active", value=active_list, inline=False)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="active", description="List currently active tweet quests")
async def active_command(interaction: discord.Interaction):
    active = await db.get_active_tweets(interaction.guild_id)
    if not active:
        await interaction.response.send_message("No active quests right now.", ephemeral=True)
        return

    embeds = []
    for t in active[:5]:
        type_display = t["types"].replace(",", " + ")
        embed = discord.Embed(
            title=f"Quest #{t['id']}",
            description=f"[Open Tweet]({t['tweet_url']})",
            color=0x1DA1F2
        )
        embed.add_field(name="Required", value=type_display, inline=True)
        embed.add_field(name="Points", value=str(t["points"]), inline=True)
        embed.add_field(name="Claims", value=str(t["total_claims"]), inline=True)
        embed.add_field(name="Ends", value=format_timestamp(t["ends_at"]), inline=True)
        embeds.append(embed)

    await interaction.response.send_message(embeds=embeds)


@bot.tree.command(name="claims", description="Admin: view recent claims and proof links")
@app_commands.describe(
    quest_id="Optional quest ID to filter (leave empty for recent claims)"
)
@app_commands.default_permissions(manage_messages=True)
async def claims_command(
    interaction: discord.Interaction,
    quest_id: Optional[int] = None
):
    """Show who claimed, their Twitter, and proof links."""
    await interaction.response.defer(ephemeral=True)

    if quest_id is not None:
        tweet = await db.get_tweet(quest_id)
        if not tweet or tweet["guild_id"] != interaction.guild_id:
            await interaction.followup.send("❌ Quest not found in this server.", ephemeral=True)
            return
        rows = await db.get_claims_for_tweet(quest_id, limit=25)
        title = f"Claims for Quest #{quest_id}"
    else:
        rows = await db.get_recent_claims(interaction.guild_id, limit=15)
        title = "Recent Claims (last 15)"

    if not rows:
        await interaction.followup.send("No claims found.", ephemeral=True)
        return

    lines = []
    for r in rows:
        user = interaction.guild.get_member(r["user_id"])
        name = user.display_name if user else f"User {r['user_id']}"
        handle = f"@{r['twitter_handle']}" if r.get("twitter_handle") else "—"
        proof = r.get("proof_url") or "No proof"
        when = format_timestamp(r["claimed_at"]) if r.get("claimed_at") else "?"
        qid = r.get("tweet_db_id", quest_id)
        pts = r.get("points_awarded", r.get("quest_points", "?"))

        # Truncate long proof links for display
        if proof and proof != "No proof" and len(proof) > 45:
            proof_display = proof[:42] + "..."
        else:
            proof_display = proof

        lines.append(
            f"**#{qid}** | {name} | `{handle}` | +{pts} pts | {when}\n"
            f"└ Proof: {proof_display}"
        )

    # Discord embed description limit ~4096
    description = "\n\n".join(lines)
    if len(description) > 4000:
        description = description[:4000] + "\n\n… (truncated)"

    embed = discord.Embed(
        title=f"📋 {title}",
        description=description,
        color=0x5865F2
    )
    embed.set_footer(text=f"{len(rows)} claim(s) shown • Use /claims quest_id:X for one quest")
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="adjustpoints", description="Admin: add or remove points from a user")
@app_commands.describe(
    user="The user to adjust",
    amount="Positive to add, negative to remove",
    reason="Optional reason"
)
@app_commands.default_permissions(administrator=True)
async def adjustpoints_command(
    interaction: discord.Interaction,
    user: discord.Member,
    amount: int,
    reason: Optional[str] = None
):
    if amount == 0:
        await interaction.response.send_message("Amount cannot be zero.", ephemeral=True)
        return

    data = await db.get_user(user.id, interaction.guild_id)
    new_points = max(0, data["points"] + amount)
    await db.set_points(user.id, interaction.guild_id, new_points)

    action = "Added" if amount > 0 else "Removed"
    embed = discord.Embed(
        title="⚙️ Points Adjusted",
        description=f"{action} **{abs(amount)}** points {'to' if amount > 0 else 'from'} {user.mention}",
        color=0x5865F2
    )
    embed.add_field(name="New Balance", value=str(new_points), inline=True)
    if reason:
        embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text=f"By {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="sync", description="Force refresh all slash commands (Admin only)")
@app_commands.default_permissions(administrator=True)
async def sync_command(interaction: discord.Interaction):
    """Force Discord to reload all slash commands (instant for this server)."""
    await interaction.response.defer(ephemeral=True)
    try:
        # Instant guild sync
        bot.tree.copy_global_to(guild=interaction.guild)
        synced = await bot.tree.sync(guild=interaction.guild)

        # Also try global (optional)
        try:
            await bot.tree.sync()
        except Exception:
            pass

        cmd_names = [cmd.name for cmd in synced]
        await interaction.followup.send(
            f"✅ Synced **{len(synced)}** commands to this server!\n"
            f"Commands: `{', '.join(cmd_names)}`\n\n"
            f"Type `/` again — you should now see **/set**",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(
            f"❌ Failed to sync commands:\n```{e}```",
            ephemeral=True
        )


@bot.tree.command(name="help_engage", description="How to use the Engage bot")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Engage Bot — Help",
        description="Reward your community for engaging with tweets!",
        color=0x1DA1F2
    )
    embed.add_field(
        name="📢 For Admins / Mods",
        value=(
            "`/tweet` — Create a new tweet quest\n"
            "Options: **link**, **type**, **duration**, **points**, **ping_role**\n\n"
            "`/claims` — View claims + proof links\n"
            "`/adjustpoints` — Manually add/remove points\n"
            "`/stats` — Server-wide engagement stats\n"
            "`/active` — List running quests\n"
            "`/sync` — Refresh slash commands"
        ),
        inline=False
    )
    embed.add_field(
        name="👤 For Members",
        value=(
            "**1.** Link your Twitter first:\n"
            "`/set twitter your_username`\n\n"
            "**2.** Do the required action(s) on the tweet\n"
            "**3.** Click **✅ Claim Points**\n\n"
            "`/balance` — Check your points + linked Twitter\n"
            "`/leaderboard` — See top engagers"
        ),
        inline=False
    )
    embed.add_field(
        name="⚠️ Note",
        value=(
            "You **must** link your Twitter/X account with `/set twitter` before claiming.\n"
            "This helps track who is engaging.\n"
            "True automatic like verification is no longer possible on X."
        ),
        inline=False
    )
    embed.set_footer(text="Made to feel like Engage bot")
    await interaction.response.send_message(embed=embed)


# --------------- Persistent view recovery (basic) ---------------
# After restart, buttons still work if we re-add the view with the same custom_id

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data.get("custom_id", "")
        if custom_id.startswith("claim_"):
            try:
                tweet_db_id = int(custom_id.split("_")[1])
                tweet = await db.get_tweet(tweet_db_id)
                if tweet:
                    view = ClaimView(
                        tweet_db_id,
                        tweet["points"],
                        tweet["ends_at"],
                        types=tweet.get("types", "")
                    )
                    # Re-dispatch the button logic manually
                    await view.claim_button.callback(interaction)
                    return
            except Exception as e:
                print(f"Error handling persistent claim: {e}")
    # Let normal handling continue
    # (discord.py will still process registered views)


if __name__ == "__main__":
    bot.run(TOKEN)
