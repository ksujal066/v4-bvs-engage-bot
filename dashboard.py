"""
Simple web dashboard for the Engage bot.
Run: python dashboard.py
Open: http://localhost:8080
Login with ADMIN_PASSWORD from .env
"""

import os
import time
import sqlite3
from functools import wraps
from datetime import datetime, timezone

from flask import (
    Flask, render_template_string, request, redirect,
    url_for, session, flash
)
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("DASHBOARD_SECRET", "change-me-to-a-random-string")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
DB_PATH = os.getenv("DB_PATH", "engage.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def fmt_time(ts):
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(ts)


# ---------- Templates ----------

BASE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }} · Engage Dashboard</title>
  <style>
    :root {
      --bg: #0f1117;
      --card: #1a1d27;
      --border: #2a2f3c;
      --text: #e8eaed;
      --muted: #9aa0a6;
      --accent: #1da1f2;
      --green: #3dd68c;
      --red: #f07178;
      --yellow: #ffcc66;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      min-height: 100vh;
    }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    nav {
      background: var(--card);
      border-bottom: 1px solid var(--border);
      padding: 12px 24px;
      display: flex;
      gap: 20px;
      align-items: center;
      flex-wrap: wrap;
    }
    nav .brand { font-weight: 700; color: var(--accent); margin-right: 12px; }
    nav a { color: var(--muted); font-size: 14px; }
    nav a:hover, nav a.active { color: var(--text); }
    .container { max-width: 1100px; margin: 0 auto; padding: 24px; }
    h1 { font-size: 22px; margin-bottom: 16px; }
    h2 { font-size: 16px; margin: 20px 0 10px; color: var(--muted); }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 24px;
    }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 16px;
    }
    .card .label { font-size: 12px; color: var(--muted); text-transform: uppercase; }
    .card .value { font-size: 24px; font-weight: 700; margin-top: 4px; }
    table {
      width: 100%;
      border-collapse: collapse;
      background: var(--card);
      border-radius: 10px;
      overflow: hidden;
      border: 1px solid var(--border);
      font-size: 13px;
    }
    th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); }
    th { background: #222632; color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: #1e222e; }
    .btn {
      display: inline-block;
      padding: 8px 14px;
      border-radius: 6px;
      border: none;
      cursor: pointer;
      font-size: 13px;
      font-weight: 600;
    }
    .btn-primary { background: var(--accent); color: #fff; }
    .btn-danger { background: var(--red); color: #fff; }
    .btn-ghost { background: transparent; border: 1px solid var(--border); color: var(--text); }
    input, select {
      background: var(--bg);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 14px;
      width: 100%;
    }
    .form-row { margin-bottom: 12px; }
    .form-row label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
    .flash {
      padding: 10px 14px;
      border-radius: 8px;
      margin-bottom: 16px;
      font-size: 14px;
    }
    .flash.ok { background: #1a3a2a; color: var(--green); }
    .flash.err { background: #3a1a1a; color: var(--red); }
    .login-box {
      max-width: 360px;
      margin: 80px auto;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 28px;
    }
    .muted { color: var(--muted); font-size: 12px; }
    .proof { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; }
  </style>
</head>
<body>
  {% if session.get('logged_in') %}
  <nav>
    <span class="brand">Engage Dashboard</span>
    <a href="{{ url_for('home') }}" class="{{ 'active' if request.endpoint == 'home' else '' }}">Overview</a>
    <a href="{{ url_for('leaderboard_page') }}">Leaderboard</a>
    <a href="{{ url_for('claims_page') }}">Claims</a>
    <a href="{{ url_for('quests_page') }}">Quests</a>
    <a href="{{ url_for('points_page') }}">Manage Points</a>
    <a href="{{ url_for('logout') }}" style="margin-left:auto">Logout</a>
  </nav>
  {% endif %}
  <div class="container">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% for cat, msg in messages %}
        <div class="flash {{ cat }}">{{ msg }}</div>
      {% endfor %}
    {% endwith %}
    {{ body|safe }}
  </div>
</body>
</html>
"""


def page(title, body):
    return render_template_string(BASE, title=title, body=body)


# ---------- Routes ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("home"))
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("home"))
        flash("Wrong password", "err")
    body = """
    <div class="login-box">
      <h1>Login</h1>
      <p class="muted" style="margin-bottom:16px">Engage Bot Dashboard</p>
      <form method="post">
        <div class="form-row">
          <label>Admin Password</label>
          <input type="password" name="password" autofocus required>
        </div>
        <button class="btn btn-primary" type="submit" style="width:100%;margin-top:8px">Login</button>
      </form>
    </div>
    """
    return page("Login", body)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def home():
    conn = get_db()
    try:
        stats = conn.execute(
            "SELECT COALESCE(SUM(total_tweets),0), COALESCE(SUM(total_claims),0), COALESCE(SUM(total_points_distributed),0) FROM guild_stats"
        ).fetchone()
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM tweets WHERE active=1 AND ends_at > ?", (time.time(),)
        ).fetchone()[0]
        recent = conn.execute(
            """SELECT c.user_id, c.twitter_handle, c.points_awarded, c.claimed_at, c.proof_url, c.tweet_db_id
               FROM claims c ORDER BY c.claimed_at DESC LIMIT 8"""
        ).fetchall()
    finally:
        conn.close()

    rows_html = ""
    for r in recent:
        proof = r["proof_url"] or "—"
        if proof != "—" and len(proof) > 40:
            proof_show = f'<a href="{proof}" target="_blank" class="proof">{proof[:37]}...</a>'
        elif proof != "—":
            proof_show = f'<a href="{proof}" target="_blank">{proof}</a>'
        else:
            proof_show = "—"
        rows_html += f"""
        <tr>
          <td>#{r['tweet_db_id']}</td>
          <td>{r['user_id']}</td>
          <td>@{r['twitter_handle'] or '—'}</td>
          <td>+{r['points_awarded']}</td>
          <td>{fmt_time(r['claimed_at'])}</td>
          <td>{proof_show}</td>
        </tr>"""

    body = f"""
    <h1>Overview</h1>
    <div class="cards">
      <div class="card"><div class="label">Total Quests</div><div class="value">{stats[0]}</div></div>
      <div class="card"><div class="label">Total Claims</div><div class="value">{stats[1]}</div></div>
      <div class="card"><div class="label">Points Distributed</div><div class="value">{stats[2]}</div></div>
      <div class="card"><div class="label">Users Tracked</div><div class="value">{users}</div></div>
      <div class="card"><div class="label">Active Quests</div><div class="value">{active}</div></div>
    </div>
    <h2>Recent Claims</h2>
    <table>
      <tr><th>Quest</th><th>User ID</th><th>Twitter</th><th>Points</th><th>When</th><th>Proof</th></tr>
      {rows_html or '<tr><td colspan="6">No claims yet</td></tr>'}
    </table>
    """
    return page("Overview", body)


@app.route("/leaderboard")
@login_required
def leaderboard_page():
    guild_id = request.args.get("guild_id", type=int)
    conn = get_db()
    try:
        guilds = conn.execute(
            "SELECT DISTINCT guild_id FROM users ORDER BY guild_id"
        ).fetchall()
        if not guild_id and guilds:
            guild_id = guilds[0]["guild_id"]
        rows = []
        if guild_id:
            rows = conn.execute(
                """SELECT user_id, points, total_earned, tweets_engaged, twitter_handle
                   FROM users WHERE guild_id=? ORDER BY points DESC LIMIT 50""",
                (guild_id,)
            ).fetchall()
    finally:
        conn.close()

    options = "".join(
        f'<option value="{g["guild_id"]}" {"selected" if g["guild_id"]==guild_id else ""}>{g["guild_id"]}</option>'
        for g in guilds
    )
    rows_html = ""
    for i, r in enumerate(rows, 1):
        rows_html += f"""
        <tr>
          <td>#{i}</td>
          <td>{r['user_id']}</td>
          <td>@{r['twitter_handle'] or '—'}</td>
          <td><strong>{r['points']}</strong></td>
          <td>{r['total_earned']}</td>
          <td>{r['tweets_engaged']}</td>
        </tr>"""

    body = f"""
    <h1>Leaderboard</h1>
    <form method="get" style="margin-bottom:16px;display:flex;gap:8px;align-items:end">
      <div class="form-row" style="margin:0;flex:1;max-width:280px">
        <label>Guild ID</label>
        <select name="guild_id" onchange="this.form.submit()">{options or '<option>No data</option>'}</select>
      </div>
    </form>
    <table>
      <tr><th>Rank</th><th>User ID</th><th>Twitter</th><th>Points</th><th>Total Earned</th><th>Engaged</th></tr>
      {rows_html or '<tr><td colspan="6">No users</td></tr>'}
    </table>
    """
    return page("Leaderboard", body)


@app.route("/claims")
@login_required
def claims_page():
    quest_id = request.args.get("quest_id", type=int)
    conn = get_db()
    try:
        if quest_id:
            rows = conn.execute(
                """SELECT * FROM claims WHERE tweet_db_id=? ORDER BY claimed_at DESC LIMIT 100""",
                (quest_id,)
            ).fetchall()
            title = f"Claims for Quest #{quest_id}"
        else:
            rows = conn.execute(
                """SELECT * FROM claims ORDER BY claimed_at DESC LIMIT 50"""
            ).fetchall()
            title = "All Recent Claims"
    finally:
        conn.close()

    rows_html = ""
    for r in rows:
        proof = r["proof_url"] or "—"
        if proof != "—":
            proof_show = f'<a href="{proof}" target="_blank" class="proof">{proof}</a>'
        else:
            proof_show = "—"
        rows_html += f"""
        <tr>
          <td>#{r['tweet_db_id']}</td>
          <td>{r['user_id']}</td>
          <td>@{r['twitter_handle'] or '—'}</td>
          <td>+{r['points_awarded']}</td>
          <td>{fmt_time(r['claimed_at'])}</td>
          <td>{proof_show}</td>
        </tr>"""

    body = f"""
    <h1>{title}</h1>
    <form method="get" style="margin-bottom:16px;display:flex;gap:8px;align-items:end">
      <div class="form-row" style="margin:0;width:160px">
        <label>Filter by Quest ID</label>
        <input type="number" name="quest_id" value="{quest_id or ''}" placeholder="e.g. 3">
      </div>
      <button class="btn btn-primary" type="submit">Filter</button>
      <a class="btn btn-ghost" href="{url_for('claims_page')}">Clear</a>
    </form>
    <table>
      <tr><th>Quest</th><th>User ID</th><th>Twitter</th><th>Points</th><th>When</th><th>Proof</th></tr>
      {rows_html or '<tr><td colspan="6">No claims</td></tr>'}
    </table>
    """
    return page("Claims", body)


@app.route("/quests")
@login_required
def quests_page():
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT * FROM tweets ORDER BY created_at DESC LIMIT 40"""
        ).fetchall()
    finally:
        conn.close()

    now = time.time()
    rows_html = ""
    for r in rows:
        status = "🟢 Active" if r["active"] and r["ends_at"] > now else "⚫ Ended"
        rows_html += f"""
        <tr>
          <td>#{r['id']}</td>
          <td>{status}</td>
          <td><a href="{r['tweet_url']}" target="_blank">Tweet</a></td>
          <td>{r['types']}</td>
          <td>{r['points']}</td>
          <td>{r['total_claims']}</td>
          <td>{fmt_time(r['ends_at'])}</td>
        </tr>"""

    body = f"""
    <h1>Quests</h1>
    <table>
      <tr><th>ID</th><th>Status</th><th>Tweet</th><th>Types</th><th>Points</th><th>Claims</th><th>Ends</th></tr>
      {rows_html or '<tr><td colspan="7">No quests</td></tr>'}
    </table>
    """
    return page("Quests", body)


@app.route("/points", methods=["GET", "POST"])
@login_required
def points_page():
    if request.method == "POST":
        try:
            guild_id = int(request.form["guild_id"])
            user_id = int(request.form["user_id"])
            amount = int(request.form["amount"])
            reason = request.form.get("reason", "")
        except (KeyError, ValueError):
            flash("Invalid input", "err")
            return redirect(url_for("points_page"))

        conn = get_db()
        try:
            row = conn.execute(
                "SELECT points FROM users WHERE user_id=? AND guild_id=?",
                (user_id, guild_id)
            ).fetchone()
            current = row["points"] if row else 0
            new_points = max(0, current + amount)
            conn.execute(
                """INSERT INTO users (user_id, guild_id, points)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, guild_id) DO UPDATE SET points = ?""",
                (user_id, guild_id, new_points, new_points)
            )
            conn.commit()
            action = "Added" if amount > 0 else "Removed"
            flash(f"{action} {abs(amount)} points → user {user_id}. New balance: {new_points}. {reason}", "ok")
        finally:
            conn.close()
        return redirect(url_for("points_page"))

    body = """
    <h1>Manage Points</h1>
    <div class="card" style="max-width:420px">
      <form method="post">
        <div class="form-row">
          <label>Guild ID</label>
          <input type="number" name="guild_id" required placeholder="Server ID">
        </div>
        <div class="form-row">
          <label>User ID (Discord snowflake)</label>
          <input type="number" name="user_id" required placeholder="Member Discord ID">
        </div>
        <div class="form-row">
          <label>Amount (+ add / − remove)</label>
          <input type="number" name="amount" required placeholder="50 or -20">
        </div>
        <div class="form-row">
          <label>Reason (optional)</label>
          <input type="text" name="reason" placeholder="Bonus / fake claim">
        </div>
        <button class="btn btn-primary" type="submit">Apply</button>
      </form>
      <p class="muted" style="margin-top:12px">
        Tip: enable Developer Mode in Discord → right‑click user → Copy User ID.
        Same for the server (right‑click server icon).
      </p>
    </div>
    """
    return page("Manage Points", body)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    print(f"Dashboard running on http://0.0.0.0:{port}")
    print(f"Login password: set ADMIN_PASSWORD in .env (default: admin123)")
    app.run(host="0.0.0.0", port=port, debug=False)
