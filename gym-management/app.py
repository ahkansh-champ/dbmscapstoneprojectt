"""Gym Management System - Flask JSON API + static front-end.

Run:   python app.py     ->  http://127.0.0.1:5000
"""
import datetime as dt
import os
import re
import sqlite3
from urllib.parse import urlparse

from flask import Flask, g, jsonify, request, send_from_directory

from db import BASE, DB_PATH, bmi_category, bmi_value, finalize_challenge, get_conn, init_schema

app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="/static")

ENTRY_POINTS = 10      # points for logging an activity in a challenge
CHECKIN_POINTS = 5     # points for a daily gym check-in


# ====================================================================
#  helpers
# ====================================================================

class ApiError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.msg, self.code = msg, code


@app.errorhandler(ApiError)
def _api_error(e):
    return jsonify(error=e.msg), e.code


@app.errorhandler(sqlite3.IntegrityError)
def _integrity_error(e):
    m = str(e)
    if "UNIQUE" in m:
        msg = "This record already exists."
    elif "FOREIGN KEY" in m:
        msg = "A related record was not found."
    elif "CHECK" in m:
        msg = "One of the values is outside the allowed range."
    elif "NOT NULL" in m:
        msg = "A required field is missing."
    else:
        msg = "The database rejected this change."
    return jsonify(error=msg), 409


@app.errorhandler(404)
def _not_found(e):
    if request.path.startswith("/api"):
        return jsonify(error="Not found"), 404
    return e


def db():
    if "db" not in g:
        g.db = get_conn()
    return g.db


@app.teardown_appcontext
def _close(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def q(sql, args=(), one=False):
    rows = [dict(r) for r in db().execute(sql, args).fetchall()]
    if one:
        return rows[0] if rows else None
    return rows


def today():
    return dt.date.today().isoformat()


def body():
    return request.get_json(silent=True) or {}


def label(key):
    return key.replace("_", " ").replace(" kg", "").replace(" cm", "").replace(" pct", " %").strip().capitalize()


def text(d, key, required=False, maxlen=200):
    v = d.get(key)
    v = "" if v is None else str(v).strip()
    if required and not v:
        raise ApiError(f"{label(key)} is required")
    if len(v) > maxlen:
        raise ApiError(f"{label(key)} is too long (max {maxlen} characters)")
    return v or None


def number(d, key, lo, hi, required=False):
    v = d.get(key)
    if v is None or str(v).strip() == "":
        if required:
            raise ApiError(f"{label(key)} is required")
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ApiError(f"{label(key)} must be a number")
    if not lo <= x <= hi:
        raise ApiError(f"{label(key)} must be between {lo:g} and {hi:g}")
    return x


def integer(d, key, required=False):
    v = d.get(key)
    if v is None or str(v).strip() == "":
        if required:
            raise ApiError(f"{label(key)} is required")
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ApiError(f"{label(key)} must be a whole number")


def date_(d, key, required=False):
    v = text(d, key, required, 10)
    if v is None:
        return None
    try:
        dt.date.fromisoformat(v)
    except ValueError:
        raise ApiError(f"{label(key)} must be a valid date (YYYY-MM-DD)")
    return v


def get_member(mid):
    m = q("SELECT * FROM members WHERE member_id = ?", (mid,), one=True)
    if not m:
        raise ApiError("Member not found", 404)
    return m


STATUS_SQL = """CASE WHEN c.finalized = 1 THEN 'completed'
                     WHEN :today < c.start_date THEN 'upcoming'
                     WHEN :today > c.end_date THEN 'ended'
                     ELSE 'active' END"""


def get_challenge(cid):
    c = q(f"""SELECT c.*, {STATUS_SQL} AS status, r.name AS winner_reward_name
              FROM challenges c LEFT JOIN rewards r ON r.reward_id = c.winner_reward_id
              WHERE c.challenge_id = :cid""", {"today": today(), "cid": cid}, one=True)
    if not c:
        raise ApiError("Challenge not found", 404)
    return c


def add_points(member_id, points, reason, challenge_id=None, on=None):
    db().execute("INSERT INTO points_ledger (member_id, points, reason, challenge_id, earned_on) VALUES (?,?,?,?,?)",
                 (member_id, points, reason, challenge_id, on or today()))


# ====================================================================
#  pages
# ====================================================================

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ====================================================================
#  lookups + dashboard
# ====================================================================

@app.get("/api/plans")
def plans():
    return jsonify(q("SELECT * FROM membership_plans ORDER BY duration_months"))


@app.get("/api/trainers")
def trainers():
    return jsonify(q("SELECT * FROM trainers ORDER BY full_name"))


@app.get("/api/dashboard")
def dashboard():
    t = today()
    month = t[:7]
    stats = q("""SELECT
        (SELECT COUNT(*) FROM members)                                       AS total_members,
        (SELECT COUNT(*) FROM members WHERE status = 'active')               AS active_members,
        (SELECT COUNT(*) FROM attendance WHERE day = :t)                     AS checkins_today,
        (SELECT COUNT(*) FROM attendance WHERE substr(day, 1, 7) = :m)       AS checkins_month,
        (SELECT COUNT(*) FROM challenges c WHERE c.finalized = 0 AND :t BETWEEN c.start_date AND c.end_date) AS active_challenges,
        (SELECT COALESCE(SUM(points), 0) FROM points_ledger WHERE points > 0) AS points_awarded""",
              {"t": t, "m": month}, one=True)
    active = q(f"""SELECT c.*, {STATUS_SQL} AS status,
                          (SELECT COUNT(*) FROM challenge_participants p WHERE p.challenge_id = c.challenge_id) AS participants
                   FROM challenges c WHERE c.finalized = 0 AND :today BETWEEN c.start_date AND c.end_date
                   ORDER BY c.end_date""", {"today": t})
    plan_mix = q("""SELECT COALESCE(p.name, 'No plan') AS plan, COUNT(*) AS members
                    FROM members m LEFT JOIN membership_plans p ON p.plan_id = m.plan_id
                    WHERE m.status = 'active' GROUP BY plan ORDER BY members DESC""")
    return jsonify(stats=stats, today=t, month=month, active_challenges=active,
                   top_performers=performers(month, 5), plan_mix=plan_mix)


# ====================================================================
#  members
# ====================================================================

MEMBER_LIST_SQL = """
    SELECT m.*, p.name AS plan_name, t.full_name AS trainer_name,
           COALESCE((SELECT SUM(points) FROM points_ledger WHERE member_id = m.member_id), 0) AS balance,
           (SELECT weight_kg FROM progress_logs WHERE member_id = m.member_id ORDER BY log_date DESC LIMIT 1) AS current_weight
    FROM members m
    LEFT JOIN membership_plans p ON p.plan_id = m.plan_id
    LEFT JOIN trainers t ON t.trainer_id = m.trainer_id"""


def decorate_member(m):
    if m.get("current_weight"):
        m["bmi"] = bmi_value(m["current_weight"], m["height_cm"])
        m["bmi_category"] = bmi_category(m["bmi"])
    else:
        m["bmi"] = m["bmi_category"] = None
    return m


@app.get("/api/members")
def list_members():
    return jsonify([decorate_member(m) for m in q(MEMBER_LIST_SQL + " ORDER BY m.full_name")])


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def member_fields(d, partial=False):
    out = {}
    if not partial or "full_name" in d:
        out["full_name"] = text(d, "full_name", True, 80)
    if not partial or "email" in d:
        email = (text(d, "email", True, 120) or "").lower()
        if not EMAIL_RE.match(email):
            raise ApiError("Enter a valid e-mail address")
        out["email"] = email
    if not partial or "height_cm" in d:
        out["height_cm"] = number(d, "height_cm", 100, 250, True)
    for key in ("phone",):
        if key in d or not partial:
            out[key] = text(d, key, False, 20)
    if "gender" in d or not partial:
        g_ = text(d, "gender")
        if g_ and g_ not in ("Male", "Female", "Other"):
            raise ApiError("Gender must be Male, Female or Other")
        out["gender"] = g_
    if "dob" in d or not partial:
        out["dob"] = date_(d, "dob")
    if "goal_weight_kg" in d or not partial:
        out["goal_weight_kg"] = number(d, "goal_weight_kg", 20, 300)
    if "plan_id" in d or not partial:
        out["plan_id"] = integer(d, "plan_id")
    if "trainer_id" in d or not partial:
        out["trainer_id"] = integer(d, "trainer_id")
    if "status" in d:
        if d["status"] not in ("active", "inactive"):
            raise ApiError("Status must be active or inactive")
        out["status"] = d["status"]
    return out


@app.post("/api/members")
def create_member():
    d = body()
    f = member_fields(d)
    start_w = number(d, "starting_weight_kg", 20, 300)
    f["join_date"] = date_(d, "join_date") or today()
    cols = ", ".join(f)
    cur = db().execute(f"INSERT INTO members ({cols}) VALUES ({','.join('?' * len(f))})", list(f.values()))
    mid = cur.lastrowid
    if start_w:    # the signup weight becomes the first entry of the progress tracker
        db().execute("INSERT INTO progress_logs (member_id, log_date, weight_kg, note) VALUES (?,?,?,?)",
                     (mid, f["join_date"], start_w, "Starting weight"))
    db().commit()
    return jsonify(get_member(mid)), 201


@app.get("/api/members/<int:mid>")
def member_detail(mid):
    get_member(mid)
    m = decorate_member(q(MEMBER_LIST_SQL + " WHERE m.member_id = ?", (mid,), one=True))
    earned = q("SELECT COALESCE(SUM(points), 0) AS n FROM points_ledger WHERE member_id = ? AND points > 0", (mid,), one=True)["n"]
    rewards = q("""SELECT r.name, r.kind, mr.source, mr.awarded_on, c.title AS challenge_title
                   FROM member_rewards mr JOIN rewards r ON r.reward_id = mr.reward_id
                   LEFT JOIN challenges c ON c.challenge_id = mr.challenge_id
                   WHERE mr.member_id = ? ORDER BY mr.awarded_on DESC, mr.id DESC""", (mid,))
    history = q(f"""SELECT c.challenge_id, c.title, c.metric, c.unit, lb.score, lb.rank_no, {STATUS_SQL} AS status
                    FROM challenge_leaderboard lb JOIN challenges c ON c.challenge_id = lb.challenge_id
                    WHERE lb.member_id = :mid ORDER BY c.start_date DESC""", {"mid": mid, "today": today()})
    attendance = q("SELECT COUNT(*) AS n FROM attendance WHERE member_id = ? AND substr(day,1,7) = ?", (mid, today()[:7]), one=True)["n"]
    return jsonify(member=m, points_earned=earned, rewards=rewards, challenge_history=history, checkins_this_month=attendance)


@app.put("/api/members/<int:mid>")
def update_member(mid):
    get_member(mid)
    f = member_fields(body(), partial=True)
    if not f:
        raise ApiError("Nothing to update")
    sets = ", ".join(f"{k} = ?" for k in f)
    db().execute(f"UPDATE members SET {sets} WHERE member_id = ?", list(f.values()) + [mid])
    db().commit()
    return jsonify(get_member(mid))


@app.delete("/api/members/<int:mid>")
def delete_member(mid):
    get_member(mid)
    db().execute("DELETE FROM members WHERE member_id = ?", (mid,))     # children are removed by ON DELETE CASCADE
    db().commit()
    return jsonify(ok=True)


@app.post("/api/members/<int:mid>/checkin")
def checkin(mid):
    get_member(mid)
    t = today()
    if q("SELECT 1 FROM attendance WHERE member_id = ? AND day = ?", (mid, t), one=True):
        raise ApiError("Already checked in today", 409)
    db().execute("INSERT INTO attendance (member_id, day) VALUES (?, ?)", (mid, t))
    add_points(mid, CHECKIN_POINTS, "Gym check-in")
    db().commit()
    return jsonify(ok=True, points=CHECKIN_POINTS), 201


# ====================================================================
#  FEATURE 1 - challenges, leaderboard, rewards
# ====================================================================

@app.get("/api/challenges")
def list_challenges():
    rows = q(f"""SELECT c.*, {STATUS_SQL} AS status, r.name AS winner_reward_name,
                        (SELECT COUNT(*) FROM challenge_participants p WHERE p.challenge_id = c.challenge_id) AS participants
                 FROM challenges c LEFT JOIN rewards r ON r.reward_id = c.winner_reward_id
                 ORDER BY c.start_date DESC, c.challenge_id DESC""", {"today": today()})
    return jsonify(rows)


@app.post("/api/challenges")
def create_challenge():
    d = body()
    title = text(d, "title", True, 80)
    metric = text(d, "metric", True, 40)
    unit = text(d, "unit", True, 20)
    start, end = date_(d, "start_date", True), date_(d, "end_date", True)
    if end < start:
        raise ApiError("End date cannot be before the start date")
    p1 = integer(d, "prize_points_1") if d.get("prize_points_1") not in (None, "") else 500
    p2 = integer(d, "prize_points_2") if d.get("prize_points_2") not in (None, "") else 300
    p3 = integer(d, "prize_points_3") if d.get("prize_points_3") not in (None, "") else 150
    if min(p1, p2, p3) < 0:
        raise ApiError("Prize points cannot be negative")
    reward_id = integer(d, "winner_reward_id")
    cur = db().execute(
        """INSERT INTO challenges (title, description, metric, unit, start_date, end_date,
                                   prize_points_1, prize_points_2, prize_points_3, winner_reward_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (title, text(d, "description", False, 300), metric, unit, start, end, p1, p2, p3, reward_id))
    db().commit()
    return jsonify(get_challenge(cur.lastrowid)), 201


@app.get("/api/challenges/<int:cid>")
def challenge_detail(cid):
    c = get_challenge(cid)
    board = q("""SELECT * FROM challenge_leaderboard WHERE challenge_id = ?
                 ORDER BY rank_no, full_name""", (cid,))
    recent = q("""SELECT e.entry_date, e.value, e.note, m.full_name FROM challenge_entries e
                  JOIN members m ON m.member_id = e.member_id
                  WHERE e.challenge_id = ? ORDER BY e.entry_date DESC, e.entry_id DESC LIMIT 8""", (cid,))
    winners = q("""SELECT l.points, l.reason, m.full_name FROM points_ledger l
                   JOIN members m ON m.member_id = l.member_id
                   WHERE l.challenge_id = ? AND l.points >= 100 AND l.reason LIKE '%place%'
                   ORDER BY l.points DESC""", (cid,)) if c["finalized"] else []
    return jsonify(challenge=c, leaderboard=board, recent_entries=recent, winners=winners)


@app.post("/api/challenges/<int:cid>/join")
def join_challenge(cid):
    c = get_challenge(cid)
    mid = integer(body(), "member_id", True)
    m = get_member(mid)
    if m["status"] != "active":
        raise ApiError("Only active members can join challenges")
    if c["status"] in ("ended", "completed"):
        raise ApiError("This challenge is already over")
    db().execute("INSERT INTO challenge_participants (challenge_id, member_id, joined_on) VALUES (?,?,?)",
                 (cid, mid, today()))
    db().commit()
    return jsonify(ok=True), 201


@app.post("/api/challenges/<int:cid>/entries")
def log_entry(cid):
    c = get_challenge(cid)
    d = body()
    mid = integer(d, "member_id", True)
    value = number(d, "value", 0.01, 100000, True)
    day = date_(d, "entry_date") or today()
    if c["finalized"] or c["status"] == "ended":
        raise ApiError("This challenge is closed")
    if day > today():
        raise ApiError("You cannot log activity for a future date")
    if not (c["start_date"] <= day <= c["end_date"]):
        raise ApiError(f"Date must fall between {c['start_date']} and {c['end_date']}")
    if not q("SELECT 1 FROM challenge_participants WHERE challenge_id = ? AND member_id = ?", (cid, mid), one=True):
        raise ApiError("Join the challenge before logging activity", 403)
    db().execute("INSERT INTO challenge_entries (challenge_id, member_id, entry_date, value, note) VALUES (?,?,?,?,?)",
                 (cid, mid, day, value, text(d, "note", False, 120)))
    add_points(mid, ENTRY_POINTS, f"Logged activity in {c['title']}", cid, day)
    db().commit()
    me = q("SELECT score, rank_no FROM challenge_leaderboard WHERE challenge_id = ? AND member_id = ?", (cid, mid), one=True)
    return jsonify(ok=True, points=ENTRY_POINTS, **me), 201


@app.post("/api/challenges/<int:cid>/finalize")
def finalize(cid):
    force = bool(body().get("force"))
    try:
        awarded = finalize_challenge(db(), cid, force=force)
    except ValueError as e:
        raise ApiError(str(e), 409)
    return jsonify(ok=True, awarded=awarded)


def performers(month=None, limit=20):
    """Top performers ranked by points EARNED (spending points in the shop never lowers your rank)."""
    extra, args = "", []
    if month:
        extra = "AND substr(l.earned_on, 1, 7) = ?"
        args.append(month)
    return q(f"""SELECT m.member_id, m.full_name,
                        COALESCE(SUM(l.points), 0) AS points,
                        RANK() OVER (ORDER BY COALESCE(SUM(l.points), 0) DESC) AS rank_no,
                        (SELECT COUNT(*) FROM member_rewards mr WHERE mr.member_id = m.member_id AND mr.source = 'challenge') AS wins
                 FROM members m
                 LEFT JOIN points_ledger l ON l.member_id = m.member_id AND l.points > 0 {extra}
                 WHERE m.status = 'active'
                 GROUP BY m.member_id
                 ORDER BY rank_no, m.full_name LIMIT ?""", args + [limit])


@app.get("/api/leaderboard")
def leaderboard():
    month = request.args.get("month")
    if month and not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ApiError("month must look like 2026-11")
    return jsonify(month=month, rows=performers(month, 20))


@app.get("/api/rewards")
def list_rewards():
    return jsonify(q("SELECT * FROM rewards ORDER BY (points_cost = 0), points_cost"))


@app.post("/api/rewards/<int:rid>/redeem")
def redeem(rid):
    mid = integer(body(), "member_id", True)
    get_member(mid)
    r = q("SELECT * FROM rewards WHERE reward_id = ?", (rid,), one=True)
    if not r:
        raise ApiError("Reward not found", 404)
    if r["points_cost"] <= 0:
        raise ApiError("This reward can only be won in a challenge")
    if r["stock"] <= 0:
        raise ApiError("Sorry, this reward is out of stock", 409)
    balance = q("SELECT balance FROM member_points WHERE member_id = ?", (mid,), one=True)["balance"]
    if balance < r["points_cost"]:
        raise ApiError(f"Not enough points - you have {balance}, this costs {r['points_cost']}", 409)
    add_points(mid, -r["points_cost"], f"Redeemed: {r['name']}")
    db().execute("UPDATE rewards SET stock = stock - 1 WHERE reward_id = ?", (rid,))
    db().execute("INSERT INTO member_rewards (member_id, reward_id, source, awarded_on) VALUES (?,?,?,?)",
                 (mid, rid, "redeemed", today()))
    db().commit()
    return jsonify(ok=True, balance=balance - r["points_cost"])


# ====================================================================
#  FEATURE 2 - social media
# ====================================================================

PLATFORM_HOSTS = {
    "Instagram": ["instagram.com"],
    "YouTube": ["youtube.com", "youtu.be"],
    "Facebook": ["facebook.com", "fb.com", "fb.watch"],
    "TikTok": ["tiktok.com"],
    "X": ["x.com", "twitter.com"],
}


def host_of(url):
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.netloc or " " in url:
        raise ApiError("Enter a valid link starting with http:// or https://")
    return u.netloc.lower().split(":")[0]


def host_matches(host, domains):
    return any(host == d or host.endswith("." + d) for d in domains)


def detect_platform(url):
    host = host_of(url)
    for name, domains in PLATFORM_HOSTS.items():
        if host_matches(host, domains):
            return name
    return "Other"


@app.get("/api/members/<int:mid>/social-links")
def get_links(mid):
    get_member(mid)
    return jsonify(q("SELECT * FROM social_links WHERE member_id = ? ORDER BY platform, link_id", (mid,)))


@app.post("/api/members/<int:mid>/social-links")
def add_link(mid):
    get_member(mid)
    d = body()
    platform = text(d, "platform", True, 20)
    if platform not in (*PLATFORM_HOSTS, "Other"):
        raise ApiError("Choose a platform from the list")
    url = text(d, "profile_url", True, 300)
    host = host_of(url)
    if platform != "Other" and not host_matches(host, PLATFORM_HOSTS[platform]):
        raise ApiError(f"This does not look like a {platform} link")
    handle = (text(d, "handle", False, 60) or "").lstrip("@") or None
    cur = db().execute("INSERT INTO social_links (member_id, platform, profile_url, handle) VALUES (?,?,?,?)",
                       (mid, platform, url, handle))
    db().commit()
    return jsonify(q("SELECT * FROM social_links WHERE link_id = ?", (cur.lastrowid,), one=True)), 201


@app.delete("/api/social-links/<int:lid>")
def delete_link(lid):
    if not q("SELECT 1 FROM social_links WHERE link_id = ?", (lid,), one=True):
        raise ApiError("Link not found", 404)
    db().execute("DELETE FROM social_links WHERE link_id = ?", (lid,))
    db().commit()
    return jsonify(ok=True)


@app.get("/api/members/<int:mid>/videos")
def get_videos(mid):
    get_member(mid)
    return jsonify(q("SELECT * FROM workout_videos WHERE member_id = ? ORDER BY created_at DESC, video_id DESC", (mid,)))


@app.post("/api/members/<int:mid>/videos")
def add_video(mid):
    get_member(mid)
    d = body()
    title = text(d, "title", True, 100)
    url = text(d, "video_url", True, 300)
    platform = detect_platform(url)
    cur = db().execute("INSERT INTO workout_videos (member_id, title, video_url, platform, description) VALUES (?,?,?,?,?)",
                       (mid, title, url, platform, text(d, "description", False, 300)))
    db().commit()
    return jsonify(q("SELECT * FROM workout_videos WHERE video_id = ?", (cur.lastrowid,), one=True)), 201


@app.delete("/api/videos/<int:vid>")
def delete_video(vid):
    if not q("SELECT 1 FROM workout_videos WHERE video_id = ?", (vid,), one=True):
        raise ApiError("Video not found", 404)
    db().execute("DELETE FROM workout_videos WHERE video_id = ?", (vid,))
    db().commit()
    return jsonify(ok=True)


@app.get("/api/videos")
def video_feed():
    return jsonify(q("""SELECT v.*, m.full_name FROM workout_videos v
                        JOIN members m ON m.member_id = v.member_id
                        ORDER BY v.created_at DESC, v.video_id DESC LIMIT 30"""))


# ====================================================================
#  FEATURE 3 - fitness progress tracker
# ====================================================================

def progress_summary(mid):
    m = get_member(mid)
    h = m["height_cm"]
    logs = q("SELECT * FROM progress_logs WHERE member_id = ? ORDER BY log_date", (mid,))
    healthy = {"min": round(18.5 * (h / 100) ** 2, 1), "max": round(24.9 * (h / 100) ** 2, 1)}
    base = {"member": {"member_id": mid, "full_name": m["full_name"], "height_cm": h,
                       "goal_weight_kg": m["goal_weight_kg"], "gender": m["gender"]},
            "healthy_range": healthy, "logs": logs, "monthly": [], "has_data": bool(logs)}
    if not logs:
        return base

    first, last = logs[0], logs[-1]

    def snap(row):
        b = bmi_value(row["weight_kg"], h)
        return {"date": row["log_date"], "weight_kg": row["weight_kg"], "bmi": b, "category": bmi_category(b)}

    change = round(last["weight_kg"] - first["weight_kg"], 1)
    goal = m["goal_weight_kg"]
    goal_pct = None
    if goal and first["weight_kg"] != goal:
        goal_pct = round(max(0.0, min(100.0, (first["weight_kg"] - last["weight_kg"]) / (first["weight_kg"] - goal) * 100)))
    months = {}
    for row in logs:
        months.setdefault(row["log_date"][:7], []).append(row)
    monthly, prev = [], first["weight_kg"]
    for key in sorted(months):
        rows = months[key]
        end_w = rows[-1]["weight_kg"]
        monthly.append({"month": key, "end_weight": end_w,
                        "avg_weight": round(sum(r["weight_kg"] for r in rows) / len(rows), 1),
                        "bmi": bmi_value(end_w, h), "change": round(end_w - prev, 1), "weigh_ins": len(rows)})
        prev = end_w
    base.update(start=snap(first), current=snap(last), change_kg=change,
                change_pct=round(change / first["weight_kg"] * 100, 1),
                goal_progress_pct=goal_pct,
                days_tracked=(dt.date.fromisoformat(last["log_date"]) - dt.date.fromisoformat(first["log_date"])).days,
                monthly=monthly)
    return base


@app.get("/api/members/<int:mid>/progress")
def get_progress(mid):
    return jsonify(progress_summary(mid))


@app.post("/api/members/<int:mid>/progress")
def add_progress(mid):
    get_member(mid)
    d = body()
    day = date_(d, "log_date") or today()
    if day > today():
        raise ApiError("You cannot log a weight for a future date")
    w = number(d, "weight_kg", 20, 300, True)
    fat = number(d, "body_fat_pct", 2, 70)
    waist = number(d, "waist_cm", 30, 250)
    db().execute(
        """INSERT INTO progress_logs (member_id, log_date, weight_kg, body_fat_pct, waist_cm, note)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT (member_id, log_date) DO UPDATE SET
               weight_kg = excluded.weight_kg, body_fat_pct = excluded.body_fat_pct,
               waist_cm = excluded.waist_cm, note = excluded.note""",
        (mid, day, w, fat, waist, text(d, "note", False, 120)))
    db().commit()
    return jsonify(progress_summary(mid)), 201


@app.delete("/api/progress/<int:lid>")
def delete_progress(lid):
    if not q("SELECT 1 FROM progress_logs WHERE log_id = ?", (lid,), one=True):
        raise ApiError("Entry not found", 404)
    db().execute("DELETE FROM progress_logs WHERE log_id = ?", (lid,))
    db().commit()
    return jsonify(ok=True)


# ====================================================================

def ensure_database():
    if not os.path.exists(DB_PATH):
        from seed import seed
        conn = get_conn()
        init_schema(conn)
        seed(conn)
        conn.close()
        print("Created", DB_PATH, "with demo data")


ensure_database()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=True)
