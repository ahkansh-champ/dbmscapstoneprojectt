

CREATE TABLE membership_plans (
    plan_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL UNIQUE,
    price            REAL    NOT NULL CHECK (price >= 0),
    duration_months  INTEGER NOT NULL CHECK (duration_months > 0)
);

CREATE TABLE trainers (
    trainer_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name       TEXT NOT NULL,
    specialization  TEXT,
    phone           TEXT
);

CREATE TABLE members (
    member_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name       TEXT    NOT NULL,
    email           TEXT    NOT NULL UNIQUE,
    phone           TEXT,
    gender          TEXT    CHECK (gender IN ('Male', 'Female', 'Other')),
    dob             TEXT,
    height_cm       REAL    NOT NULL CHECK (height_cm BETWEEN 100 AND 250),
    goal_weight_kg  REAL    CHECK (goal_weight_kg BETWEEN 20 AND 300),
    join_date       TEXT    NOT NULL DEFAULT (date('now')),
    plan_id         INTEGER REFERENCES membership_plans(plan_id) ON DELETE SET NULL,
    trainer_id      INTEGER REFERENCES trainers(trainer_id)      ON DELETE SET NULL,
    status          TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive'))
);

CREATE TABLE attendance (
    attendance_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id       INTEGER NOT NULL REFERENCES members(member_id) ON DELETE CASCADE,
    day             TEXT    NOT NULL,
    check_in_time   TEXT    NOT NULL DEFAULT (time('now', 'localtime')),
    UNIQUE (member_id, day)                 -- one check-in per member per day
);

-- ---------- FEATURE 1 : Challenges, leaderboard, rewards --------------

CREATE TABLE rewards (
    reward_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL UNIQUE,
    description  TEXT,
    kind         TEXT    NOT NULL CHECK (kind IN ('badge', 'merchandise', 'discount', 'free_pass', 'free_month')),
    points_cost  INTEGER NOT NULL DEFAULT 0 CHECK (points_cost >= 0),   -- 0 = cannot be bought (badge)
    stock        INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0)
);

CREATE TABLE challenges (
    challenge_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    title             TEXT    NOT NULL,
    description       TEXT,
    metric            TEXT    NOT NULL,              -- e.g. Workouts, Distance, Calories burned
    unit              TEXT    NOT NULL,              -- e.g. sessions, km, kcal
    start_date        TEXT    NOT NULL,
    end_date          TEXT    NOT NULL,
    prize_points_1    INTEGER NOT NULL DEFAULT 500 CHECK (prize_points_1 >= 0),
    prize_points_2    INTEGER NOT NULL DEFAULT 300 CHECK (prize_points_2 >= 0),
    prize_points_3    INTEGER NOT NULL DEFAULT 150 CHECK (prize_points_3 >= 0),
    winner_reward_id  INTEGER REFERENCES rewards(reward_id) ON DELETE SET NULL,
    finalized         INTEGER NOT NULL DEFAULT 0 CHECK (finalized IN (0, 1)),
    CHECK (end_date >= start_date)
);

CREATE TABLE challenge_participants (
    challenge_id  INTEGER NOT NULL REFERENCES challenges(challenge_id) ON DELETE CASCADE,
    member_id     INTEGER NOT NULL REFERENCES members(member_id)       ON DELETE CASCADE,
    joined_on     TEXT    NOT NULL DEFAULT (date('now')),
    PRIMARY KEY (challenge_id, member_id)
);

CREATE TABLE challenge_entries (
    entry_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    challenge_id  INTEGER NOT NULL REFERENCES challenges(challenge_id) ON DELETE CASCADE,
    member_id     INTEGER NOT NULL REFERENCES members(member_id)       ON DELETE CASCADE,
    entry_date    TEXT    NOT NULL,
    value         REAL    NOT NULL CHECK (value > 0),
    note          TEXT
);

-- Every point ever earned (+) or spent (-) lives here.
CREATE TABLE points_ledger (
    ledger_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id     INTEGER NOT NULL REFERENCES members(member_id) ON DELETE CASCADE,
    points        INTEGER NOT NULL CHECK (points <> 0),
    reason        TEXT    NOT NULL,
    challenge_id  INTEGER REFERENCES challenges(challenge_id) ON DELETE SET NULL,
    earned_on     TEXT    NOT NULL DEFAULT (date('now'))
);

CREATE TABLE member_rewards (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id     INTEGER NOT NULL REFERENCES members(member_id) ON DELETE CASCADE,
    reward_id     INTEGER NOT NULL REFERENCES rewards(reward_id) ON DELETE CASCADE,
    challenge_id  INTEGER REFERENCES challenges(challenge_id) ON DELETE SET NULL,
    source        TEXT    NOT NULL CHECK (source IN ('challenge', 'redeemed')),
    awarded_on    TEXT    NOT NULL DEFAULT (date('now'))
);

-- ---------- FEATURE 2 : Social media -----------------------------------

CREATE TABLE social_links (
    link_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id    INTEGER NOT NULL REFERENCES members(member_id) ON DELETE CASCADE,
    platform     TEXT    NOT NULL CHECK (platform IN ('Instagram', 'YouTube', 'Facebook', 'TikTok', 'X', 'Other')),
    profile_url  TEXT    NOT NULL,
    handle       TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (member_id, profile_url)
);

CREATE TABLE workout_videos (
    video_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id    INTEGER NOT NULL REFERENCES members(member_id) ON DELETE CASCADE,
    title        TEXT    NOT NULL,
    video_url    TEXT    NOT NULL,
    platform     TEXT    NOT NULL,
    description  TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (member_id, video_url)
);

-- ---------- FEATURE 3 : Fitness progress tracker -------------------------

CREATE TABLE progress_logs (
    log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id     INTEGER NOT NULL REFERENCES members(member_id) ON DELETE CASCADE,
    log_date      TEXT    NOT NULL,
    weight_kg     REAL    NOT NULL CHECK (weight_kg BETWEEN 20 AND 300),
    body_fat_pct  REAL    CHECK (body_fat_pct BETWEEN 2 AND 70),
    waist_cm      REAL    CHECK (waist_cm BETWEEN 30 AND 250),
    note          TEXT,
    UNIQUE (member_id, log_date)             -- one weigh-in per day (re-saving updates it)
);

-- ---------- Indexes --------------------------------------------------------

CREATE INDEX idx_entries_challenge_member ON challenge_entries (challenge_id, member_id);
CREATE INDEX idx_ledger_member_date       ON points_ledger (member_id, earned_on);
CREATE INDEX idx_progress_member_date     ON progress_logs (member_id, log_date);
CREATE INDEX idx_attendance_day           ON attendance (day);
CREATE INDEX idx_videos_created           ON workout_videos (created_at);

-- ---------- Views ----------------------------------------------------------

-- Live ranking inside each challenge (ties share a rank).
CREATE VIEW challenge_leaderboard AS
SELECT  p.challenge_id,
        p.member_id,
        m.full_name,
        COALESCE(SUM(e.value), 0)  AS score,
        COUNT(e.entry_id)          AS entries,
        RANK() OVER (PARTITION BY p.challenge_id
                     ORDER BY COALESCE(SUM(e.value), 0) DESC) AS rank_no
FROM challenge_participants p
JOIN members m ON m.member_id = p.member_id
LEFT JOIN challenge_entries e
       ON e.challenge_id = p.challenge_id AND e.member_id = p.member_id
GROUP BY p.challenge_id, p.member_id;

-- Spendable point balance of every member.
CREATE VIEW member_points AS
SELECT  m.member_id,
        COALESCE(SUM(l.points), 0) AS balance
FROM members m
LEFT JOIN points_ledger l ON l.member_id = m.member_id
GROUP BY m.member_id;
