"""Database helpers shared by the Flask app and the seed script."""
import datetime as dt
import os
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("GYM_DB", os.path.join(BASE, "gym.db"))
SCHEMA_PATH = os.path.join(BASE, "schema.sql")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")      # enforce FK + ON DELETE rules
    return conn


def init_schema(conn):
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())


# ---------------------------------------------------------------- BMI

def bmi_value(weight_kg, height_cm):
    """BMI = weight (kg) / height (m)^2, rounded to 1 decimal."""
    return round(weight_kg / ((height_cm / 100.0) ** 2), 1)


def bmi_category(bmi):
    if bmi < 18.5:
        return "Underweight"
    if bmi < 25:
        return "Normal"
    if bmi < 30:
        return "Overweight"
    return "Obese"


# ------------------------------------------------- challenge finalisation

def finalize_challenge(conn, challenge_id, force=False, on_date=None):
    """Close a challenge and reward the top 3 (ties share the same rank).

    Returns a list of dicts describing who got what.
    Raises ValueError with a user-friendly message on invalid state.
    """
    today = dt.date.today().isoformat()
    on_date = on_date or today
    c = conn.execute("SELECT * FROM challenges WHERE challenge_id = ?", (challenge_id,)).fetchone()
    if c is None:
        raise ValueError("Challenge not found")
    if c["finalized"]:
        raise ValueError("Winners were already awarded for this challenge")
    if c["start_date"] > today and not force:
        raise ValueError("This challenge has not started yet")
    if today <= c["end_date"] and not force:
        raise ValueError("Challenge is still running - end it manually to award winners now")

    winners = conn.execute(
        """SELECT member_id, full_name, score, rank_no
           FROM challenge_leaderboard
           WHERE challenge_id = ? AND rank_no <= 3 AND score > 0
           ORDER BY rank_no, full_name""",
        (challenge_id,),
    ).fetchall()

    awarded = []
    for w in winners:
        pts = c["prize_points_%d" % w["rank_no"]]
        place = {1: "1st", 2: "2nd", 3: "3rd"}[w["rank_no"]]
        if pts:
            conn.execute(
                "INSERT INTO points_ledger (member_id, points, reason, challenge_id, earned_on) VALUES (?,?,?,?,?)",
                (w["member_id"], pts, "%s place - %s" % (place, c["title"]), challenge_id, on_date),
            )
        badge = None
        if w["rank_no"] == 1 and c["winner_reward_id"]:
            conn.execute(
                "INSERT INTO member_rewards (member_id, reward_id, challenge_id, source, awarded_on) VALUES (?,?,?,?,?)",
                (w["member_id"], c["winner_reward_id"], challenge_id, "challenge", on_date),
            )
            badge = conn.execute("SELECT name FROM rewards WHERE reward_id = ?", (c["winner_reward_id"],)).fetchone()["name"]
        awarded.append({
            "member_id": w["member_id"], "full_name": w["full_name"], "rank": w["rank_no"],
            "score": w["score"], "points": pts, "badge": badge,
        })

    conn.execute("UPDATE challenges SET finalized = 1 WHERE challenge_id = ?", (challenge_id,))
    conn.commit()
    return awarded
