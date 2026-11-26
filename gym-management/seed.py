import datetime as dt
import os
import random

from db import DB_PATH, finalize_challenge, get_conn, init_schema


def month_bounds(ref, offset):
    y, m = ref.year, ref.month + offset
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    first = dt.date(y, m, 1)
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return first, dt.date(ny, nm, 1) - dt.timedelta(days=1)


def seed(conn):
    random.seed(7)
    today = dt.date.today()
    iso = lambda d: d.isoformat()

    # ---- plans, trainers, rewards ------------------------------------
    conn.executemany("INSERT INTO membership_plans (name, price, duration_months) VALUES (?,?,?)",
                     [("Monthly", 1500, 1), ("Quarterly", 4000, 3), ("Half-Yearly", 7000, 6), ("Annual", 12000, 12)])
    conn.executemany("INSERT INTO trainers (full_name, specialization, phone) VALUES (?,?,?)",
                     [("Rajesh Kumar", "Strength & Conditioning", "9810000001"),
                      ("Meera Joshi", "Yoga & Mobility", "9810000002"),
                      ("Imran Khan", "Fat Loss & HIIT", "9810000003"),
                      ("Deepa Nambiar", "Nutrition & Cardio", "9810000004")])
    conn.executemany("INSERT INTO rewards (name, description, kind, points_cost, stock) VALUES (?,?,?,?,?)", [
        ("Monthly Champion Badge", "Awarded to the winner of a monthly challenge", "badge", 0, 9999),
        ("Protein Shaker", "Branded 700 ml shaker bottle", "merchandise", 300, 20),
        ("Protein Bar Box", "Box of 12 protein bars", "merchandise", 500, 12),
        ("Gym T-Shirt", "Dry-fit gym t-shirt", "merchandise", 600, 15),
        ("1-Week Free Pass", "Gift a week of free access to a friend", "free_pass", 800, 10),
        ("Personal Training Session", "One free 1-on-1 session with a trainer", "discount", 1200, 5),
        ("Free Month Membership", "One month added to your plan", "free_month", 2500, 2),
    ])

    # ---- members -----------------------------------------------------
    # name, email, phone, gender, dob, height, goal_w, start_w, plan, trainer, joined_days_ago, dedication, status
    people = [
        ("Aarav Sharma", "aarav@example.com", "9876500001", "Male", "1999-04-12", 176, 72, 88, 3, 3, 190, 0.90, "active"),
        ("Priya Verma", "priya@example.com", "9876500002", "Female", "1997-09-03", 162, 55, 68, 4, 4, 185, 0.85, "active"),
        ("Rohan Mehta", "rohan@example.com", "9876500003", "Male", "2001-01-25", 180, 78, 70, 2, 1, 170, 0.80, "active"),
        ("Sneha Gupta", "sneha@example.com", "9876500004", "Female", "1995-07-19", 158, 52, 63, 1, 2, 160, 0.60, "active"),
        ("Vikram Singh", "vikram@example.com", "9876500005", "Male", "1992-11-30", 174, 75, 92, 3, 3, 175, 0.70, "active"),
        ("Ananya Iyer", "ananya@example.com", "9876500006", "Female", "2000-03-08", 165, 58, 71, 4, 4, 150, 0.75, "active"),
        ("Karan Malhotra", "karan@example.com", "9876500007", "Male", "1998-06-21", 182, 80, 74, 2, 1, 140, 0.65, "active"),
        ("Neha Kapoor", "neha@example.com", "9876500008", "Female", "1993-12-14", 160, 54, 66, 2, 2, 120, 0.50, "active"),
        ("Arjun Reddy", "arjun@example.com", "9876500009", "Male", "1996-02-02", 178, 76, 85, 1, 3, 100, 0.55, "active"),
        ("Simran Kaur", "simran@example.com", "9876500010", "Female", "2002-08-27", 163, 56, 64, 1, 4, 70, 0.70, "active"),
        ("Rahul Yadav", "rahul@example.com", "9876500011", "Male", "1990-05-05", 170, 70, 80, 1, 1, 12, 0.80, "active"),
        ("Pooja Nair", "pooja@example.com", "9876500012", "Female", "1994-10-10", 161, None, None, 1, 2, 40, 0.30, "inactive"),
    ]
    members = []
    for i, p in enumerate(people, start=1):
        name, email, phone, gender, dob, h, goal, start_w, plan, trainer, ago, ded, status = p
        joined = today - dt.timedelta(days=ago)
        conn.execute(
            """INSERT INTO members (full_name, email, phone, gender, dob, height_cm, goal_weight_kg,
                                    join_date, plan_id, trainer_id, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (name, email, phone, gender, dob, h, goal, iso(joined), plan, trainer, status))
        members.append({"id": i, "joined": joined, "ded": ded, "status": status})

        # ---- progress logs: roughly weekly weigh-ins -----------------
        if start_w:
            weeks_to_goal = random.uniform(24, 34)
            rate = (goal - start_w) / weeks_to_goal                 # kg per week (negative = loss)
            d, w0 = joined, float(start_w)
            first = True
            while d <= today:
                weeks = (d - joined).days / 7.0
                w = start_w + rate * weeks + random.uniform(-0.4, 0.4)
                if (rate < 0 and w < goal - 0.5) or (rate > 0 and w > goal + 0.5):
                    w = goal + random.uniform(-0.3, 0.3)
                if first:
                    w, first = float(start_w), False
                fat = round(max(8, 30 - (start_w - w) * 0.6 + random.uniform(-0.5, 0.5)), 1) if gender == "Male" else \
                      round(max(14, 36 - (start_w - w) * 0.6 + random.uniform(-0.5, 0.5)), 1)
                conn.execute(
                    "INSERT INTO progress_logs (member_id, log_date, weight_kg, body_fat_pct, waist_cm, note) VALUES (?,?,?,?,?,?)",
                    (i, iso(d), round(w, 1), fat, round(78 - (start_w - w) * 0.9 + random.uniform(-0.6, 0.6), 1),
                     "Starting weight" if d == joined else None))
                d += dt.timedelta(days=random.randint(6, 9))

    # ---- attendance (+5 pts each) ------------------------------------
    for m in members:
        for back in range(0, 36):
            day = today - dt.timedelta(days=back)
            if day < m["joined"] or m["status"] != "active":
                continue
            if random.random() < m["ded"] * 0.6:
                conn.execute("INSERT INTO attendance (member_id, day, check_in_time) VALUES (?,?,?)",
                             (m["id"], iso(day), "%02d:%02d:00" % (random.randint(6, 20), random.choice([0, 15, 30, 45]))))
                conn.execute("INSERT INTO points_ledger (member_id, points, reason, earned_on) VALUES (?,?,?,?)",
                             (m["id"], 5, "Gym check-in", iso(day)))

    # ---- challenges ----------------------------------------------------
    p_first, p_last = month_bounds(today, -1)
    c_first, c_last = month_bounds(today, 0)
    n_first, n_last = month_bounds(today, 1)
    challenges = [
        (f"{p_first:%B} Distance Dash", "Run, walk or cycle - every kilometre counts.", "Distance", "km", p_first, p_last),
        (f"{c_first:%B} Workout Warrior", "Log the most workout sessions this month.", "Workouts", "sessions", c_first, c_last),
        ("30-Day Calorie Crusher", "Burn the most calories before the month ends.", "Calories burned", "kcal", c_first, c_last),
        (f"{n_first:%B} Plank & Push-up Showdown", "Total reps of planks and push-ups over the month.", "Reps", "reps", n_first, n_last),
    ]
    for title, desc, metric, unit, s, e in challenges:
        conn.execute(
            """INSERT INTO challenges (title, description, metric, unit, start_date, end_date,
                                       prize_points_1, prize_points_2, prize_points_3, winner_reward_id)
               VALUES (?,?,?,?,?,?,500,300,150,1)""", (title, desc, metric, unit, iso(s), iso(e)))

    def value_for(metric):
        if metric == "Workouts":
            return 1
        if metric == "Distance":
            return round(random.uniform(2, 9), 1)
        if metric == "Calories burned":
            return random.randint(250, 700)
        return random.randint(30, 120)

    def fill(cid, metric, start, end, who, until=None):
        last = min(end, until or end)
        for m in who:
            conn.execute("INSERT OR IGNORE INTO challenge_participants (challenge_id, member_id, joined_on) VALUES (?,?,?)",
                         (cid, m["id"], iso(max(start - dt.timedelta(days=3), m["joined"]))))
            d = start
            while d <= last:
                if d >= m["joined"] and random.random() < m["ded"] * 0.55:
                    conn.execute("INSERT INTO challenge_entries (challenge_id, member_id, entry_date, value) VALUES (?,?,?,?)",
                                 (cid, m["id"], iso(d), value_for(metric)))
                    conn.execute("INSERT INTO points_ledger (member_id, points, reason, challenge_id, earned_on) VALUES (?,?,?,?,?)",
                                 (m["id"], 10, "Logged activity in " + challenges[cid - 1][0], cid, iso(d)))
                d += dt.timedelta(days=1)

    active = [m for m in members if m["status"] == "active"]
    fill(1, "Distance", p_first, p_last, [m for m in active if m["joined"] <= p_last])
    fill(2, "Workouts", c_first, c_last, active, until=today)
    fill(3, "Calories burned", c_first, c_last, random.sample(active, 8), until=today)
    for m in active[:4]:                                   # upcoming challenge: a few early sign-ups
        conn.execute("INSERT INTO challenge_participants (challenge_id, member_id) VALUES (4,?)", (m["id"],))
    conn.commit()

    # last month's challenge is over -> award winners (points + champion badge)
    finalize_challenge(conn, 1, on_date=iso(p_last))

    # ---- a couple of redemptions so the shop has history ---------------
    conn.execute("INSERT INTO points_ledger (member_id, points, reason, earned_on) VALUES (1,-300,'Redeemed: Protein Shaker',?)", (iso(today - dt.timedelta(days=9)),))
    conn.execute("INSERT INTO member_rewards (member_id, reward_id, source, awarded_on) VALUES (1,2,'redeemed',?)", (iso(today - dt.timedelta(days=9)),))
    conn.execute("UPDATE rewards SET stock = stock - 1 WHERE reward_id = 2")

    # ---- social links + videos (fake demo URLs) ------------------------
    links = [
        (1, "Instagram", "https://www.instagram.com/aarav.lifts", "aarav.lifts"),
        (1, "YouTube", "https://www.youtube.com/@aaravfitness", "aaravfitness"),
        (2, "Instagram", "https://www.instagram.com/priya.moves", "priya.moves"),
        (3, "YouTube", "https://www.youtube.com/@rohangains", "rohangains"),
        (3, "TikTok", "https://www.tiktok.com/@rohangains", "rohangains"),
        (6, "Instagram", "https://www.instagram.com/ananya.fit", "ananya.fit"),
        (7, "Facebook", "https://www.facebook.com/karan.fitness", "karan.fitness"),
    ]
    conn.executemany("INSERT INTO social_links (member_id, platform, profile_url, handle) VALUES (?,?,?,?)", links)
    videos = [
        (1, "Deadlift PR - 160 kg", "https://www.youtube.com/watch?v=demo_deadlift01", "YouTube", "New personal record after 4 months of training."),
        (1, "Full-body HIIT in 20 minutes", "https://www.instagram.com/reel/demo_hiit_01/", "Instagram", "No equipment needed."),
        (2, "Morning mobility routine", "https://www.instagram.com/reel/demo_mobility_01/", "Instagram", "10 minutes to start the day."),
        (3, "Push day for mass", "https://www.youtube.com/watch?v=demo_pushday02", "YouTube", "Chest, shoulders and triceps session."),
        (3, "Bench press form check", "https://www.tiktok.com/@rohangains/video/demo_bench03", "TikTok", None),
        (6, "Leg day finisher", "https://www.instagram.com/reel/demo_legday_04/", "Instagram", "Burnout set - not for the faint hearted!"),
        (7, "Pull-up progression", "https://www.facebook.com/watch/?v=demo_pullup05", "Facebook", "From 0 to 12 reps."),
    ]
    for k, v in enumerate(videos):
        conn.execute("INSERT INTO workout_videos (member_id, title, video_url, platform, description, created_at) VALUES (?,?,?,?,?,?)",
                     (*v[:5], iso(today - dt.timedelta(days=3 * k + 1)) + " 18:30:00"))
    conn.commit()


if __name__ == "__main__":
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    connection = get_conn()
    init_schema(connection)
    seed(connection)
    connection.close()
    print("Database created with demo data ->", DB_PATH)
