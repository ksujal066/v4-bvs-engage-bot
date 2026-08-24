# Engage-Style Discord Bot

A clean Discord bot inspired by **Engage** (engages.io) focused on:

- Tweet engagement quests
- Points system
- Tweet stats + server engage stats
- `/tweet` command with `link`, `type`, `duration`, `points`

## Features

| Feature | Description |
|---------|-------------|
| `/tweet` | Create a quest (link + type + duration + points) |
| Claim Button | Users click after engaging → get points |
| `/balance` | Check your (or someone else's) points |
| `/leaderboard` | Top engagers |
| `/stats` | Server-wide stats (total quests, claims, points distributed) |
| `/active` | List currently running quests |
| `/adjustpoints` | Admin tool to manually change points |
| Persistent DB | SQLite (survives restarts) |
| Auto-expire | Quests automatically become inactive after duration |

### Supported Quest Types
- Like
- Retweet
- Reply
- Like + Retweet
- All (Like + RT + Reply)

### Duration Options
30m • 1h • 3h • 6h • 12h • 24h • 48h

---

## Important Limitation

**X (Twitter) made likes private in 2024.**  
True automatic verification of who liked a post is no longer possible via public API.

This bot uses a **Claim button** (honor system) — the same approach many engagement bots use.  
You can later add:
- Twitter account linking
- Retweet / Reply verification via API
- Browser-based checking (more complex)

---

## Setup (5 minutes)

### 1. Create a Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. **New Application** → name it
3. Go to **Bot** → **Add Bot**
4. Enable these **Privileged Gateway Intents**:
   - Message Content Intent
   - Server Members Intent (optional but useful)
5. Copy the **Bot Token**

### 2. Invite the Bot

OAuth2 → URL Generator:

- Scopes: `bot`, `applications.commands`
- Permissions: `Send Messages`, `Embed Links`, `Use Slash Commands`, `Manage Messages`, `Read Message History`

Invite it to your server.

### 3. Install & Run

```bash
# Clone / download this folder
cd engage-bot

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env and paste your bot token:
# DISCORD_TOKEN=your_token_here

# Start the bot
python bot.py
```

You should see:
```
Logged in as YourBot#1234 (ID: ...)
Slash commands synced.
```

---

## Commands

### Admin / Mod (Manage Messages or Admin)

| Command | Description |
|---------|-------------|
| `/tweet` | Create a new engagement quest |
| `/adjustpoints` | Add or remove points from a user |
| `/stats` | Full server engagement statistics |
| `/active` | List running quests |

### Everyone

| Command | Description |
|---------|-------------|
| `/balance [user]` | Check points |
| `/leaderboard` | Top 10 |
| `/help_engage` | How the bot works |

---

## How a Quest Works

1. Admin runs `/tweet` with a tweet link + type + duration + points
2. Bot posts a nice embed with a green **✅ Claim Points** button
3. Members do the action(s) on X
4. They come back and click **Claim**
5. Points are added instantly
6. Quest auto-expires after the chosen duration

---

## Database

Uses SQLite (`engage.db`). Tables:

- `users` — points, total earned, tweets engaged
- `tweets` — all quests
- `claims` — who claimed what (prevents double claiming)
- `guild_stats` — aggregate server stats

---

## Future Improvements (easy to add)

- [ ] Twitter account linking (`/set twitter @handle`)
- [ ] Automatic retweet verification via X API
- [ ] Role rewards at point thresholds
- [ ] Daily claim / streak system
- [ ] Marketplace / shop with points
- [ ] Raffle system
- [ ] Voice activity points
- [ ] Multi-server dashboard

---

## License

MIT — do whatever you want with it.

---

Made to feel like the real **Engage** bot.  
Feel free to extend it!