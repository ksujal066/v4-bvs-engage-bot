import aiosqlite
import time
from typing import Optional, List, Dict, Any

DB_PATH = "engage.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                points INTEGER DEFAULT 0,
                total_earned INTEGER DEFAULT 0,
                tweets_engaged INTEGER DEFAULT 0,
                twitter_handle TEXT DEFAULT NULL,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        # Add twitter_handle column if the table already existed without it
        try:
            await db.execute("ALTER TABLE users ADD COLUMN twitter_handle TEXT DEFAULT NULL")
        except Exception:
            pass  # column already exists

        await db.execute("""
            CREATE TABLE IF NOT EXISTS tweets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                tweet_url TEXT NOT NULL,
                tweet_id TEXT,
                types TEXT NOT NULL,          -- comma separated: like,retweet,reply
                points INTEGER NOT NULL,
                duration_minutes INTEGER NOT NULL,
                created_at REAL NOT NULL,
                ends_at REAL NOT NULL,
                active INTEGER DEFAULT 1,
                total_claims INTEGER DEFAULT 0,
                created_by INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tweet_db_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                claimed_at REAL NOT NULL,
                points_awarded INTEGER NOT NULL,
                twitter_handle TEXT,
                proof_url TEXT,
                UNIQUE(tweet_db_id, user_id)
            )
        """)
        try:
            await db.execute("ALTER TABLE claims ADD COLUMN proof_url TEXT")
        except Exception:
            pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS guild_stats (
                guild_id INTEGER PRIMARY KEY,
                total_tweets INTEGER DEFAULT 0,
                total_claims INTEGER DEFAULT 0,
                total_points_distributed INTEGER DEFAULT 0
            )
        """)
        await db.commit()


async def get_user(user_id: int, guild_id: int) -> Dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            # Create user
            await db.execute(
                "INSERT INTO users (user_id, guild_id) VALUES (?, ?)",
                (user_id, guild_id)
            )
            await db.commit()
            return {
                "user_id": user_id,
                "guild_id": guild_id,
                "points": 0,
                "total_earned": 0,
                "tweets_engaged": 0,
                "twitter_handle": None
            }


async def set_twitter(user_id: int, guild_id: int, handle: str) -> None:
    """Link a Twitter/X handle to a Discord user (per guild)."""
    handle = handle.lstrip("@").lower().strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, guild_id, twitter_handle)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET twitter_handle = ?
        """, (user_id, guild_id, handle, handle))
        await db.commit()


async def get_twitter(user_id: int, guild_id: int) -> Optional[str]:
    user = await get_user(user_id, guild_id)
    return user.get("twitter_handle")


async def clear_twitter(user_id: int, guild_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET twitter_handle = NULL WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        await db.commit()


async def add_points(user_id: int, guild_id: int, amount: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, guild_id, points, total_earned, tweets_engaged)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET
                points = points + ?,
                total_earned = total_earned + ?,
                tweets_engaged = tweets_engaged + 1
        """, (user_id, guild_id, amount, amount, amount, amount))
        await db.commit()
        async with db.execute(
            "SELECT points FROM users WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else amount


async def set_points(user_id: int, guild_id: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, guild_id, points)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET points = ?
        """, (user_id, guild_id, amount, amount))
        await db.commit()


async def get_leaderboard(guild_id: int, limit: int = 10) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT user_id, points, total_earned, tweets_engaged
               FROM users WHERE guild_id = ?
               ORDER BY points DESC LIMIT ?""",
            (guild_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def create_tweet(
    guild_id: int,
    channel_id: int,
    tweet_url: str,
    types: str,
    points: int,
    duration_minutes: int,
    created_by: int,
    tweet_id: Optional[str] = None
) -> int:
    now = time.time()
    ends_at = now + (duration_minutes * 60)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO tweets
            (guild_id, channel_id, tweet_url, tweet_id, types, points,
             duration_minutes, created_at, ends_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (guild_id, channel_id, tweet_url, tweet_id, types, points,
              duration_minutes, now, ends_at, created_by))
        await db.commit()
        tweet_db_id = cursor.lastrowid

        # Update guild stats
        await db.execute("""
            INSERT INTO guild_stats (guild_id, total_tweets)
            VALUES (?, 1)
            ON CONFLICT(guild_id) DO UPDATE SET total_tweets = total_tweets + 1
        """, (guild_id,))
        await db.commit()
        return tweet_db_id


async def set_tweet_message_id(tweet_db_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tweets SET message_id = ? WHERE id = ?",
            (message_id, tweet_db_id)
        )
        await db.commit()


async def get_tweet(tweet_db_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tweets WHERE id = ?", (tweet_db_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_active_tweets(guild_id: int) -> List[Dict]:
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM tweets
               WHERE guild_id = ? AND active = 1 AND ends_at > ?
               ORDER BY created_at DESC""",
            (guild_id, now)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def has_claimed(tweet_db_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM claims WHERE tweet_db_id = ? AND user_id = ?",
            (tweet_db_id, user_id)
        ) as cursor:
            return await cursor.fetchone() is not None


async def claim_tweet(
    tweet_db_id: int,
    user_id: int,
    guild_id: int,
    points: int,
    twitter_handle: Optional[str] = None,
    proof_url: Optional[str] = None
) -> bool:
    """Returns True if claim was successful, False if already claimed or inactive."""
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        # Check if still active
        async with db.execute(
            "SELECT active, ends_at FROM tweets WHERE id = ?", (tweet_db_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row or not row[0] or row[1] < now:
                return False

        try:
            await db.execute(
                """INSERT INTO claims
                   (tweet_db_id, user_id, guild_id, claimed_at, points_awarded, twitter_handle, proof_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (tweet_db_id, user_id, guild_id, now, points, twitter_handle, proof_url)
            )
            await db.execute(
                "UPDATE tweets SET total_claims = total_claims + 1 WHERE id = ?",
                (tweet_db_id,)
            )
            await db.execute("""
                INSERT INTO guild_stats (guild_id, total_claims, total_points_distributed)
                VALUES (?, 1, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    total_claims = total_claims + 1,
                    total_points_distributed = total_points_distributed + ?
            """, (guild_id, points, points))
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            # Already claimed
            return False


async def get_guild_stats(guild_id: int) -> Dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM guild_stats WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return {
                "guild_id": guild_id,
                "total_tweets": 0,
                "total_claims": 0,
                "total_points_distributed": 0
            }


async def get_claims_for_tweet(tweet_db_id: int, limit: int = 25) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM claims
               WHERE tweet_db_id = ?
               ORDER BY claimed_at DESC
               LIMIT ?""",
            (tweet_db_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_recent_claims(guild_id: int, limit: int = 15) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT c.*, t.tweet_url, t.types, t.points as quest_points
               FROM claims c
               JOIN tweets t ON t.id = c.tweet_db_id
               WHERE c.guild_id = ?
               ORDER BY c.claimed_at DESC
               LIMIT ?""",
            (guild_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def deactivate_expired_tweets():
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tweets SET active = 0 WHERE ends_at < ? AND active = 1",
            (now,)
        )
        await db.commit()