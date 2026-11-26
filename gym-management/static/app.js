/* IronPulse Gym Management - front-end (vanilla JS, talks to the Flask JSON API) */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const iso = (d) => d.toLocaleDateString("en-CA");              // YYYY-MM-DD in local time
const TODAY = iso(new Date());
const MEDAL = { 1: "🥇", 2: "🥈", 3: "🥉" };
const state = { members: [], who: Number(localStorage.getItem("who")) || null, chart: "monthly", lbMonth: TODAY.slice(0, 7), height: 170 };
const views = {};

/* ------------------------------------------------------------- utils */
async function api(path, method = "GET", body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* empty body */ }
  if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
  return data;
}
async function act(fn, okMsg) {
  try { const r = await fn(); if (okMsg) toast(okMsg); return r === undefined ? true : r; }
  catch (e) { toast(e.message, true); return null; }
}
function toast(msg, bad) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 3600);
}
function openModal(html) { $("#modal-body").innerHTML = html; $("#modal").hidden = false; }
function closeModal() { $("#modal").hidden = true; }
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

const fdate = (d) => d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—";
const fshort = (d) => new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });
const fmonth = (m) => new Date(m + "-01T00:00:00").toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
const fmonthLong = (m) => new Date(m + "-01T00:00:00").toLocaleDateString("en-IN", { month: "long", year: "numeric" });
const num = (n) => Number(n).toLocaleString("en-IN", { maximumFractionDigits: 1 });
const inr = (n) => "₹" + Number(n).toLocaleString("en-IN");
const sign = (n) => (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(n).toFixed(1);
const daysBetween = (a, b) => Math.round((new Date(b + "T00:00:00") - new Date(a + "T00:00:00")) / 86400000);
const me = () => state.members.find((m) => m.member_id === state.who);
const bmiVal = (w, h) => Math.round((w / ((h / 100) ** 2)) * 10) / 10;
const bmiCat = (b) => (b < 18.5 ? "Underweight" : b < 25 ? "Normal" : b < 30 ? "Overweight" : "Obese");
const formObj = (form) => { const o = {}; new FormData(form).forEach((v, k) => { if (String(v).trim() !== "") o[k] = v; }); return o; };
const stat = (label, value, sub, accent) => `<div class="card stat ${accent ? "accent" : ""}"><span>${label}</span><b>${value}</b><small>${sub || ""}</small></div>`;
const noMember = () => `<div class="empty">Add a member first (Members page), then choose them in the “Viewing as” box.</div>`;
const STATUS = { active: "Live", upcoming: "Upcoming", ended: "Ended · awaiting winners", completed: "Completed" };
const PLAT_ICON = { Instagram: "📸", YouTube: "▶️", Facebook: "👍", TikTok: "🎵", X: "✖️", Other: "🔗" };

/* ------------------------------------------------------------ shared UI */
function leaderRows(rows) {
  if (!rows.length) return `<div class="empty">No activity yet</div>`;
  const max = Math.max(...rows.map((r) => r.points), 1);
  return rows.map((r) => `
    <div class="lead ${r.member_id === state.who ? "me" : ""}">
      <div class="rk">${MEDAL[r.rank_no] || r.rank_no}</div>
      <div><div class="nm">${esc(r.full_name)}${r.wins ? ` <small>🏅×${r.wins}</small>` : ""}</div>
        <div class="bar"><i style="width:${(r.points / max) * 100}%"></i></div></div>
      <div class="pts">${num(r.points)} pts</div>
    </div>`).join("");
}
function challengeCard(c) {
  const left = c.status === "active" ? `${Math.max(daysBetween(TODAY, c.end_date), 0)} days left` : `${fdate(c.start_date)} → ${fdate(c.end_date)}`;
  return `<a class="card ch" href="#/challenges/${c.challenge_id}">
    <div class="row between"><span class="badge ${c.status}">${STATUS[c.status]}</span><small>${left}</small></div>
    <h3>${esc(c.title)}</h3>
    <p class="muted">${esc(c.description || "")}</p>
    <div class="row between"><span>📊 ${esc(c.metric)} <small>(${esc(c.unit)})</small></span><span>👥 ${c.participants}</span></div>
    <div class="prizes">🥇 ${c.prize_points_1} · 🥈 ${c.prize_points_2} · 🥉 ${c.prize_points_3} pts${c.winner_reward_name ? ` · 🏅 ${esc(c.winner_reward_name)}` : ""}</div>
  </a>`;
}

/* --------------------------------------------------------------- router */
async function loadMembers() {
  state.members = await api("/api/members");
  if (!state.members.some((m) => m.member_id === state.who)) state.who = state.members[0]?.member_id ?? null;
  $("#who").innerHTML = state.members.map((m) => `<option value="${m.member_id}" ${m.member_id === state.who ? "selected" : ""}>${esc(m.full_name)}</option>`).join("");
}
$("#who").addEventListener("change", (e) => { state.who = Number(e.target.value); localStorage.setItem("who", state.who); route(); });

async function route() {
  const [, page = "dashboard", arg] = (location.hash || "#/dashboard").split("/");
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.page === page));
  const view = views[page] || views.dashboard;
  try {
    $("#view").innerHTML = await view(arg);
  } catch (e) {
    $("#view").innerHTML = `<div class="empty">⚠️ ${esc(e.message)}</div>`;
  }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);

/* ================================================================ DASHBOARD */
views.dashboard = async () => {
  const d = await api("/api/dashboard");
  const s = d.stats;
  const maxPlan = Math.max(...d.plan_mix.map((p) => p.members), 1);
  return `
  <div class="page-head"><div><h1>Dashboard</h1><p>${fdate(d.today)}</p></div></div>
  <div class="grid stats">
    ${stat("Active members", s.active_members, `${s.total_members} registered`, true)}
    ${stat("Check-ins today", s.checkins_today, `${s.checkins_month} this month`)}
    ${stat("Live challenges", s.active_challenges, "running right now")}
    ${stat("Points awarded", num(s.points_awarded), "all time")}
  </div>
  <div class="cols">
    <section class="card"><div class="row between"><h2>Live challenges</h2><a class="link" href="#/challenges">View all</a></div>
      ${d.active_challenges.map((c) => `<a class="mini" href="#/challenges/${c.challenge_id}">
          <div><b>${esc(c.title)}</b><br><small>${esc(c.metric)} · ${c.participants} participants</small></div>
          <small>${Math.max(daysBetween(d.today, c.end_date), 0)}d left</small></a>`).join("") || `<div class="empty">No challenge is running. Create one!</div>`}
    </section>
    <section class="card"><div class="row between"><h2>Top performers · ${fmonthLong(d.month)}</h2><a class="link" href="#/leaderboard">Full board</a></div>
      ${leaderRows(d.top_performers)}</section>
  </div>
  <section class="card"><h2>Active members by plan</h2>
    ${d.plan_mix.map((p) => `<div class="lead" style="grid-template-columns:120px 1fr auto"><div class="nm">${esc(p.plan)}</div><div class="bar"><i style="width:${(p.members / maxPlan) * 100}%"></i></div><div class="pts">${p.members}</div></div>`).join("")}
  </section>`;
};

/* ================================================================== MEMBERS */
views.members = async () => {
  const [members, plans, trainers] = await Promise.all([api("/api/members"), api("/api/plans"), api("/api/trainers")]);
  state.members = members;
  const opt = (rows, id, label) => rows.map((r) => `<option value="${r[id]}">${esc(r[label])}</option>`).join("");
  return `
  <div class="page-head"><div><h1>Members</h1><p>${members.length} registered</p></div></div>
  <details class="card"><summary>Register a new member</summary>
    <form onsubmit="return submitMember(event)" class="form-grid">
      <label class="f">Full name *<input name="full_name" required maxlength="80"></label>
      <label class="f">Email *<input name="email" type="email" required></label>
      <label class="f">Phone<input name="phone" maxlength="20"></label>
      <label class="f">Gender<select name="gender"><option value="">—</option><option>Male</option><option>Female</option><option>Other</option></select></label>
      <label class="f">Date of birth<input name="dob" type="date" max="${TODAY}"></label>
      <label class="f">Height (cm) *<input name="height_cm" type="number" step="0.1" min="100" max="250" required></label>
      <label class="f">Starting weight (kg)<input name="starting_weight_kg" type="number" step="0.1" min="20" max="300"></label>
      <label class="f">Goal weight (kg)<input name="goal_weight_kg" type="number" step="0.1" min="20" max="300"></label>
      <label class="f">Plan<select name="plan_id"><option value="">—</option>${opt(plans, "plan_id", "name")}</select></label>
      <label class="f">Trainer<select name="trainer_id"><option value="">—</option>${opt(trainers, "trainer_id", "full_name")}</select></label>
      <div class="wide"><button class="primary">Add member</button> <small>The starting weight becomes the first entry in the progress tracker.</small></div>
    </form></details>
  <div class="table-wrap"><table>
    <thead><tr><th>Member</th><th>Plan</th><th>Trainer</th><th class="num">Weight</th><th>BMI</th><th class="num">Points</th><th>Status</th><th></th></tr></thead>
    <tbody>${members.map((m) => `<tr>
      <td><button class="link" onclick="showMember(${m.member_id})">${esc(m.full_name)}</button><br><small>${esc(m.email)}</small></td>
      <td>${esc(m.plan_name || "—")}</td><td>${esc(m.trainer_name || "—")}</td>
      <td class="num">${m.current_weight ? m.current_weight + " kg" : "—"}</td>
      <td>${m.bmi ? `${m.bmi} <small class="cat-${m.bmi_category}">${m.bmi_category}</small>` : "—"}</td>
      <td class="num">${num(m.balance)}</td>
      <td><span class="badge ${m.status}">${m.status}</span></td>
      <td class="row"><button class="sm" onclick="checkIn(${m.member_id})">Check-in</button><button class="sm danger" onclick="removeMember(${m.member_id})" title="Delete member">✕</button></td>
    </tr>`).join("")}</tbody></table></div>`;
};
async function submitMember(e) {
  e.preventDefault();
  const r = await act(() => api("/api/members", "POST", formObj(e.target)), "Member added");
  if (r) { await loadMembers(); route(); }
  return false;
}
async function checkIn(id) {
  const r = await act(() => api(`/api/members/${id}/checkin`, "POST"), "Checked in · +5 points");
  if (r) { await loadMembers(); route(); }
}
async function removeMember(id) {
  const m = state.members.find((x) => x.member_id === id);
  if (!confirm(`Delete ${m.full_name}? Their progress, points, videos and challenge entries will be removed too.`)) return;
  if (await act(() => api(`/api/members/${id}`, "DELETE"), "Member deleted")) { await loadMembers(); route(); }
}
async function showMember(id) {
  const d = await act(() => api(`/api/members/${id}`));
  if (!d) return;
  const m = d.member;
  openModal(`
    <h2 style="font-size:1.4rem">${esc(m.full_name)}</h2>
    <p class="muted">${esc(m.plan_name || "No plan")} · Trainer: ${esc(m.trainer_name || "—")} · Joined ${fdate(m.join_date)}</p>
    <div class="grid" style="grid-template-columns:repeat(3,1fr);margin:16px 0">
      ${stat("Points", num(m.balance), `${num(d.points_earned)} earned`, true)}
      ${stat("Check-ins", d.checkins_this_month, "this month")}
      ${stat("BMI", m.bmi ?? "—", m.bmi_category || "")}
    </div>
    <h2>Rewards & badges</h2>
    <ul class="plain">${d.rewards.map((r) => `<li><span>${r.source === "challenge" ? "🏅" : "🎁"} ${esc(r.name)}${r.challenge_title ? ` <small>· ${esc(r.challenge_title)}</small>` : ""}</span><small>${fdate(r.awarded_on)}</small></li>`).join("") || `<li><small>None yet</small></li>`}</ul>
    <h2 style="margin-top:18px">Challenge history</h2>
    <ul class="plain">${d.challenge_history.map((h) => `<li><span>${esc(h.title)}</span><small>${MEDAL[h.rank_no] || "#" + h.rank_no} · ${num(h.score)} ${esc(h.unit)}</small></li>`).join("") || `<li><small>Not joined any challenge</small></li>`}</ul>`);
}

/* ================================================== FEATURE 1 · CHALLENGES */
views.challenges = async (id) => {
  if (id) return challengeDetail(id);
  const [list, rewards] = await Promise.all([api("/api/challenges"), api("/api/rewards")]);
  const group = (title, rows) => rows.length ? `<div class="section-title">${title}</div><div class="grid cards">${rows.map(challengeCard).join("")}</div>` : "";
  const end = iso(new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0));
  return `
  <div class="page-head"><div><h1>Challenges</h1><p>Compete, climb the leaderboard and win rewards.</p></div></div>
  <details class="card"><summary>Create a monthly challenge</summary>
    <form onsubmit="return submitChallenge(event)" class="form-grid">
      <label class="f wide">Title *<input name="title" required maxlength="80" placeholder="e.g. December Burn-Off"></label>
      <label class="f wide">Description<input name="description" maxlength="300"></label>
      <label class="f">Metric *<input name="metric" required list="metrics" placeholder="Workouts" maxlength="40"></label>
      <datalist id="metrics"><option>Workouts</option><option>Distance</option><option>Calories burned</option><option>Reps</option><option>Steps</option></datalist>
      <label class="f">Unit *<input name="unit" required placeholder="sessions / km / kcal" maxlength="20"></label>
      <label class="f">Start date *<input name="start_date" type="date" required value="${TODAY}"></label>
      <label class="f">End date *<input name="end_date" type="date" required value="${end}"></label>
      <label class="f">🥇 1st prize (pts)<input name="prize_points_1" type="number" min="0" value="500"></label>
      <label class="f">🥈 2nd prize (pts)<input name="prize_points_2" type="number" min="0" value="300"></label>
      <label class="f">🥉 3rd prize (pts)<input name="prize_points_3" type="number" min="0" value="150"></label>
      <label class="f">Winner badge<select name="winner_reward_id"><option value="">None</option>${rewards.filter((r) => r.kind === "badge").map((r) => `<option value="${r.reward_id}" selected>${esc(r.name)}</option>`).join("")}</select></label>
      <div class="wide"><button class="primary">Create challenge</button></div>
    </form></details>
  ${group("Live now", list.filter((c) => c.status === "active"))}
  ${group("Upcoming", list.filter((c) => c.status === "upcoming"))}
  ${group("Ended · awaiting winners", list.filter((c) => c.status === "ended"))}
  ${group("Completed", list.filter((c) => c.status === "completed"))}
  ${list.length ? "" : `<div class="empty">No challenges yet.</div>`}`;
};
async function submitChallenge(e) {
  e.preventDefault();
  const r = await act(() => api("/api/challenges", "POST", formObj(e.target)), "Challenge created");
  if (r && r.challenge_id) location.hash = `#/challenges/${r.challenge_id}`;
  return false;
}
async function challengeDetail(id) {
  const d = await api(`/api/challenges/${id}`);
  const c = d.challenge, lb = d.leaderboard;
  const mine = lb.find((r) => r.member_id === state.who);
  const open = c.status === "active" || c.status === "upcoming";
  const top = lb.filter((r) => r.rank_no <= 3 && r.score > 0);
  const best = Math.max(...lb.map((r) => r.score), 1);
  const who = me();
  return `
  <p><a class="link" href="#/challenges">← All challenges</a></p>
  <div class="page-head"><div>
      <span class="badge ${c.status}">${STATUS[c.status]}</span>
      <h1 style="margin-top:8px">${esc(c.title)}</h1>
      <p>${esc(c.description || "")}</p>
      <p>📅 ${fdate(c.start_date)} → ${fdate(c.end_date)} · 📊 ${esc(c.metric)} (${esc(c.unit)}) · 👥 ${lb.length} competing</p>
    </div>
    <div class="card" style="min-width:230px"><small>PRIZES</small><br>🥇 ${c.prize_points_1} pts${c.winner_reward_name ? ` + 🏅 ${esc(c.winner_reward_name)}` : ""}<br>🥈 ${c.prize_points_2} pts<br>🥉 ${c.prize_points_3} pts</div>
  </div>

  ${top.length ? `<div class="podium">${top.map((r) => `<div class="pod p${r.rank_no}"><div class="medal">${MEDAL[r.rank_no]}</div><b>${esc(r.full_name)}</b><div class="score">${num(r.score)}</div><small>${esc(c.unit)}</small></div>`).join("")}</div>` : ""}

  <div class="cols">
    <section class="card"><h2>Leaderboard</h2>
      ${lb.length ? `<div class="table-wrap" style="border:0"><table><thead><tr><th>#</th><th>Member</th><th class="num">Logs</th><th class="num">${esc(c.unit)}</th></tr></thead><tbody>
        ${lb.map((r) => `<tr class="${r.member_id === state.who ? "me" : ""}"><td>${MEDAL[r.rank_no] || r.rank_no}</td>
          <td>${esc(r.full_name)}<div class="bar"><i style="width:${(r.score / best) * 100}%"></i></div></td><td class="num">${r.entries}</td><td class="num"><b>${num(r.score)}</b></td></tr>`).join("")}
      </tbody></table></div>` : `<div class="empty">Nobody has joined yet. Be the first!</div>`}
    </section>
    <div>
      <section class="card"><h2>Your participation</h2>
        ${!who ? "Choose a member above." :
          mine ? (c.status === "active" ? `
            <p style="margin-bottom:12px">${esc(who.full_name)}: <b>#${mine.rank_no}</b> with <b>${num(mine.score)} ${esc(c.unit)}</b></p>
            <form onsubmit="return submitEntry(event, ${c.challenge_id})" class="form-grid" style="grid-template-columns:1fr 1fr">
              <label class="f">${esc(c.unit)} *<input name="value" type="number" step="0.1" min="0.1" required></label>
              <label class="f">Date<input name="entry_date" type="date" value="${TODAY}" min="${c.start_date}" max="${TODAY < c.end_date ? TODAY : c.end_date}"></label>
              <label class="f wide">Note<input name="note" maxlength="120"></label>
              <div class="wide"><button class="primary">Log activity · +10 pts</button></div>
            </form>` : `<p>${esc(who.full_name)} is #${mine.rank_no} with ${num(mine.score)} ${esc(c.unit)}.</p>`)
          : open ? `<p style="margin-bottom:12px">${esc(who.full_name)} has not joined this challenge.</p><button class="primary" onclick="joinChallenge(${c.challenge_id})">Join challenge</button>`
          : `<p class="muted">This challenge is closed.</p>`}
      </section>
      ${c.status === "active" || c.status === "ended" ? `<section class="card"><h2>Admin</h2>
        <p class="muted" style="margin-bottom:12px">${c.status === "ended" ? "The challenge is over. Award points and the winner badge to the top 3." : "Close the challenge early and award the top 3 right now."}</p>
        <button onclick="finalizeChallenge(${c.challenge_id}, ${c.status === "active"})">🏆 ${c.status === "ended" ? "Award winners" : "End now & award winners"}</button></section>` : ""}
      ${c.status === "completed" ? `<section class="card"><h2>Winners</h2><ul class="plain">
        ${d.winners.map((w) => `<li><span>${esc(w.reason.split(" - ")[0])} · ${esc(w.full_name)}</span><b>+${w.points}</b></li>`).join("") || "<li><small>No scores were recorded.</small></li>"}</ul></section>` : ""}
      <section class="card"><h2>Recent activity</h2><ul class="plain">
        ${d.recent_entries.map((e) => `<li><span>${esc(e.full_name)}</span><small>${num(e.value)} ${esc(c.unit)} · ${fshort(e.entry_date)}</small></li>`).join("") || "<li><small>No activity logged yet</small></li>"}</ul></section>
    </div>
  </div>`;
}
async function joinChallenge(id) {
  if (await act(() => api(`/api/challenges/${id}/join`, "POST", { member_id: state.who }), "You're in! Good luck 💪")) route();
}
async function submitEntry(e, id) {
  e.preventDefault();
  const r = await act(() => api(`/api/challenges/${id}/entries`, "POST", { ...formObj(e.target), member_id: state.who }));
  if (r) { toast(`Logged · +${r.points} pts · you are #${r.rank_no}`); route(); }
  return false;
}
async function finalizeChallenge(id, force) {
  if (!confirm(force ? "End this challenge now and award the winners? This cannot be undone." : "Award the winners now?")) return;
  const r = await act(() => api(`/api/challenges/${id}/finalize`, "POST", { force }));
  if (r) { toast(r.awarded.length ? "Awarded: " + r.awarded.map((a) => `${MEDAL[a.rank]} ${a.full_name}`).join(", ") : "Closed (no scores were logged)"); await loadMembers(); route(); }
}

/* ======================================== FEATURE 1 · LEADERBOARD + REWARDS */
views.leaderboard = async () => {
  const d = await api("/api/leaderboard" + (state.lbMonth ? `?month=${state.lbMonth}` : ""));
  return `
  <div class="page-head"><div><h1>Leaderboard</h1><p>Points come from challenge wins (500/300/150), logged activities (+10) and check-ins (+5).</p></div>
    <div class="row"><label class="f" style="margin:0">Month<input type="month" value="${state.lbMonth}" onchange="setMonth(this.value)"></label>
      <button class="${state.lbMonth ? "" : "primary"}" onclick="setMonth('')">All time</button></div></div>
  <section class="card"><h2>${state.lbMonth ? "Top performers · " + fmonthLong(state.lbMonth) : "Top performers · all time"}</h2>${leaderRows(d.rows)}</section>`;
};
function setMonth(v) { state.lbMonth = v; route(); }

views.rewards = async () => {
  const [rewards, detail] = await Promise.all([api("/api/rewards"), state.who ? api(`/api/members/${state.who}`) : null]);
  const m = detail && detail.member;
  const icon = { badge: "🏅", merchandise: "👕", discount: "🏷️", free_pass: "🎟️", free_month: "📆" };
  return `
  <div class="page-head"><div><h1>Rewards</h1><p>${m ? `${esc(m.full_name)} has <b style="color:var(--accent)">${num(m.balance)} points</b> to spend.` : "Choose a member above."}</p></div></div>
  <div class="grid cards">${rewards.map((r) => `<div class="card reward">
      <div class="kind">${icon[r.kind] || "🎁"}</div><h3>${esc(r.name)}</h3><p class="muted">${esc(r.description || "")}</p>
      ${r.points_cost > 0 ? `<div class="cost">${num(r.points_cost)} <small>pts</small></div><div class="row between"><small>${r.stock} left</small>
        <button class="primary sm" ${!m || m.balance < r.points_cost || r.stock <= 0 ? "disabled style=\"opacity:.45;cursor:not-allowed\"" : ""} onclick="redeem(${r.reward_id})">${r.stock <= 0 ? "Out of stock" : "Redeem"}</button></div>`
        : `<div class="cost" style="font-size:1rem">Challenge prize</div><small>Cannot be bought · win it!</small>`}
    </div>`).join("")}</div>
  ${detail ? `<div class="section-title">${esc(m.full_name)}'s collection</div><section class="card"><ul class="plain">
    ${detail.rewards.map((r) => `<li><span>${r.source === "challenge" ? "🏅" : "🎁"} ${esc(r.name)}${r.challenge_title ? ` <small>· won in ${esc(r.challenge_title)}</small>` : ""}</span><small>${fdate(r.awarded_on)}</small></li>`).join("") || "<li><small>Nothing yet - join a challenge!</small></li>"}</ul></section>` : ""}`;
};
async function redeem(id) {
  const r = await act(() => api(`/api/rewards/${id}/redeem`, "POST", { member_id: state.who }));
  if (r) { toast(`Redeemed! New balance: ${num(r.balance)} pts`); await loadMembers(); route(); }
}

/* ======================================================= FEATURE 2 · SOCIAL */
function ytThumb(url) {
  const m = /(?:v=|youtu\.be\/)([\w-]{6,15})/.exec(url);
  return m ? `<img src="https://img.youtube.com/vi/${m[1]}/mqdefault.jpg" alt="" loading="lazy" onerror="this.remove()">` : "";
}
function videoCard(v, mine) {
  return `<div class="card video">
    <a class="thumb" href="${esc(v.video_url)}" target="_blank" rel="noopener noreferrer" aria-label="Open video">${ytThumb(v.video_url)}<span>${PLAT_ICON[v.platform] || "🔗"}</span></a>
    <div style="min-width:0;flex:1">
      <div class="row between"><span class="plat ${esc(v.platform)}">${esc(v.platform)}</span>${mine ? `<button class="sm danger" onclick="deleteVideo(${v.video_id})">Remove</button>` : ""}</div>
      <h3 style="margin:8px 0 2px"><a href="${esc(v.video_url)}" target="_blank" rel="noopener noreferrer">${esc(v.title)}</a></h3>
      ${v.full_name ? `<small>by ${esc(v.full_name)} · </small>` : ""}<small>${fdate(v.created_at.slice(0, 10))}</small>
      ${v.description ? `<p class="muted" style="margin-top:4px">${esc(v.description)}</p>` : ""}
    </div></div>`;
}
views.social = async () => {
  if (!state.who) return noMember();
  const [links, vids, feed] = await Promise.all([api(`/api/members/${state.who}/social-links`), api(`/api/members/${state.who}/videos`), api("/api/videos")]);
  const who = me();
  return `
  <div class="page-head"><div><h1>Social media</h1><p>Link ${esc(who.full_name)}'s pages and share workout videos with the gym community.</p></div></div>
  <div class="cols">
    <section class="card"><h2>Social pages</h2>
      <form onsubmit="return submitLink(event)" class="form-grid" style="margin-bottom:14px;grid-template-columns:130px 1fr">
        <label class="f">Platform<select name="platform"><option>Instagram</option><option>YouTube</option><option>Facebook</option><option>TikTok</option><option>X</option><option>Other</option></select></label>
        <label class="f">Page / profile link *<input name="profile_url" type="url" required placeholder="https://www.instagram.com/yourname"></label>
        <label class="f">Handle<input name="handle" placeholder="@yourname" maxlength="60"></label>
        <div style="align-self:end"><button class="primary">Add page</button></div>
      </form>
      <ul class="plain">${links.map((l) => `<li><span><span class="plat ${esc(l.platform)}">${esc(l.platform)}</span> <a class="link" href="${esc(l.profile_url)}" target="_blank" rel="noopener noreferrer">${esc(l.handle ? "@" + l.handle : l.profile_url)}</a></span>
        <button class="sm danger" onclick="deleteLink(${l.link_id})">Remove</button></li>`).join("") || "<li><small>No pages added yet</small></li>"}</ul>
    </section>
    <section class="card"><h2>Share a workout video</h2>
      <form onsubmit="return submitVideo(event)" class="form-grid">
        <label class="f wide">Title *<input name="title" required maxlength="100" placeholder="Leg day finisher"></label>
        <label class="f wide">Video link * <small>(YouTube, Instagram, Facebook, TikTok, X…)</small><input name="video_url" type="url" required placeholder="https://..."></label>
        <label class="f wide">Description<input name="description" maxlength="300"></label>
        <div class="wide"><button class="primary">Post video</button></div>
      </form></section>
  </div>
  <div class="section-title">${esc(who.full_name)}'s videos</div>
  <div class="grid cards">${vids.map((v) => videoCard(v, true)).join("") || `<div class="empty">No videos yet</div>`}</div>
  <div class="section-title">Community feed</div>
  <div class="grid cards">${feed.map((v) => videoCard(v, false)).join("")}</div>`;
};
async function submitLink(e) {
  e.preventDefault();
  if (await act(() => api(`/api/members/${state.who}/social-links`, "POST", formObj(e.target)), "Page added")) route();
  return false;
}
async function submitVideo(e) {
  e.preventDefault();
  if (await act(() => api(`/api/members/${state.who}/videos`, "POST", formObj(e.target)), "Video posted")) route();
  return false;
}
async function deleteLink(id) { if (confirm("Remove this page?") && await act(() => api(`/api/social-links/${id}`, "DELETE"), "Removed")) route(); }
async function deleteVideo(id) { if (confirm("Remove this video?") && await act(() => api(`/api/videos/${id}`, "DELETE"), "Removed")) route(); }

/* ================================================= FEATURE 3 · PROGRESS */
function lineChart(pts, goal, band) {
  const W = 780, H = 300, L = 46, R = 24, T = 18, B = 38, n = pts.length;
  const vals = pts.map((p) => p.value).concat(goal ? [goal] : []);
  let min = Math.min(...vals), max = Math.max(...vals);
  const pad = Math.max((max - min) * 0.18, 1.5);
  min = Math.floor(min - pad); max = Math.ceil(max + pad);
  const x = (i) => (n === 1 ? L + (W - L - R) / 2 : L + (i * (W - L - R)) / (n - 1));
  const y = (v) => T + ((max - v) * (H - T - B)) / (max - min);
  let grid = "";
  for (let i = 0; i <= 5; i++) { const v = min + ((max - min) * i) / 5; grid += `<line class="gridl" x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/><text x="${L - 8}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${v.toFixed(0)}</text>`; }
  const path = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`).join(" ");
  const step = Math.ceil(n / 9);
  const shown = []; for (let i = 0; i < n; i += step) shown.push(i);
  if (shown[shown.length - 1] !== n - 1 && n - 1 - shown[shown.length - 1] >= Math.ceil(step / 2)) shown.push(n - 1);
  const labels = shown.map((i) => `<text x="${x(i).toFixed(1)}" y="${H - 14}" text-anchor="middle">${esc(pts[i].label)}</text>`).join("");
  let bandSvg = "";
  if (band) {
    const top = Math.max(T, y(Math.min(band.max, max))), bot = Math.min(H - B, y(Math.max(band.min, min)));
    if (bot > top) bandSvg = `<rect class="band" x="${L}" y="${top.toFixed(1)}" width="${W - L - R}" height="${(bot - top).toFixed(1)}"/><text x="${L + 8}" y="${(top + 14).toFixed(1)}" style="fill:#3ddc97">Healthy BMI range</text>`;
  }
  const goalSvg = goal ? `<line class="goal" x1="${L}" x2="${W - R}" y1="${y(goal).toFixed(1)}" y2="${y(goal).toFixed(1)}"/><text class="goal-t" x="${L + 8}" y="${(y(goal) - 6).toFixed(1)}">Goal ${goal} kg</text>` : "";
  const dots = pts.map((p, i) => `<circle class="dot" cx="${x(i).toFixed(1)}" cy="${y(p.value).toFixed(1)}" r="${n > 40 ? 2.5 : 4.5}"><title>${esc(p.tip)}</title></circle>`).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Weight progress chart">
    <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c6ff3d" stop-opacity=".25"/><stop offset="1" stop-color="#c6ff3d" stop-opacity="0"/></linearGradient></defs>
    ${bandSvg}${grid}${n > 1 ? `<path class="area" d="${path} L${x(n - 1).toFixed(1)} ${H - B} L${x(0).toFixed(1)} ${H - B} Z"/>` : ""}${goalSvg}
    <path class="line" d="${path}"/>${dots}${labels}</svg>`;
}
const scalePos = (b) => Math.max(1, Math.min(99, ((b - 15) / 25) * 100));

views.progress = async () => {
  if (!state.who) return noMember();
  const p = await api(`/api/members/${state.who}/progress`);
  state.height = p.member.height_cm;
  const logForm = `
    <section class="card"><h2>Log today's weigh-in</h2>
      <form onsubmit="return submitProgress(event)" class="form-grid">
        <label class="f">Date<input name="log_date" type="date" value="${TODAY}" max="${TODAY}"></label>
        <label class="f">Weight (kg) *<input name="weight_kg" type="number" step="0.1" min="20" max="300" required oninput="bmiPreview(this.value)"></label>
        <label class="f">Body fat %<input name="body_fat_pct" type="number" step="0.1" min="2" max="70"></label>
        <label class="f">Waist (cm)<input name="waist_cm" type="number" step="0.1" min="30" max="250"></label>
        <label class="f wide">Note<input name="note" maxlength="120"></label>
        <div class="wide row wrap"><button class="primary">Save entry</button><span id="bmi-live" class="muted">Height ${p.member.height_cm} cm · type your weight to preview BMI</span></div>
      </form></section>`;
  if (!p.has_data) return `<div class="page-head"><div><h1>Fitness progress</h1><p>${esc(p.member.full_name)}</p></div></div>
    <div class="empty" style="margin-bottom:16px">No weigh-ins yet. Add the starting weight below to begin tracking.</div>${logForm}`;

  const goal = p.member.goal_weight_kg;
  const loseGoal = goal ? goal < p.start.weight_kg : null;
  const good = loseGoal === null ? null : loseGoal ? p.change_kg < 0 : p.change_kg > 0;
  const dcls = p.change_kg === 0 ? "delta-flat" : good === null ? "delta-flat" : good ? "delta-down" : "delta-up";
  const pts = state.chart === "monthly"
    ? p.monthly.map((m) => ({ label: fmonth(m.month), value: m.end_weight, tip: `${fmonthLong(m.month)}: ${m.end_weight} kg (BMI ${m.bmi})` }))
    : p.logs.map((l) => ({ label: fshort(l.log_date), value: l.weight_kg, tip: `${fdate(l.log_date)}: ${l.weight_kg} kg` }));
  return `
  <div class="page-head"><div><h1>Fitness progress</h1><p>${esc(p.member.full_name)} · ${p.member.height_cm} cm · tracking for ${p.days_tracked} days</p></div></div>
  <div class="kpi">
    <div class="card"><small>STARTING WEIGHT</small><b>${p.start.weight_kg} kg</b><small>${fdate(p.start.date)}</small></div>
    <div class="card"><small>CURRENT WEIGHT</small><b>${p.current.weight_kg} kg</b><small class="${dcls}">${sign(p.change_kg)} kg (${sign(p.change_pct)}%) since start</small></div>
    <div class="card"><small>BMI NOW</small><b>${p.current.bmi}</b><small class="cat-${p.current.category}">${p.current.category}</small> <small>· was ${p.start.bmi} (${p.start.category})</small></div>
    <div class="card"><small>GOAL ${goal ? goal + " KG" : ""}</small>${p.goal_progress_pct === null ? `<b>—</b><small>Set a goal weight on the member profile</small>` :
      `<b>${p.goal_progress_pct}%</b><div class="meter"><i style="width:${p.goal_progress_pct}%"></i></div><small>${Math.abs(p.current.weight_kg - goal).toFixed(1)} kg to go</small>`}</div>
  </div>

  <section class="card"><div class="row between wrap"><h2 style="margin:0">Weight progress</h2>
      <div class="seg"><button class="${state.chart === "monthly" ? "on" : ""}" onclick="setChart('monthly')">Monthly</button><button class="${state.chart === "all" ? "on" : ""}" onclick="setChart('all')">All weigh-ins</button></div></div>
    <div style="margin-top:12px">${lineChart(pts, goal, p.healthy_range)}</div>
  </section>

  <div class="cols">
    <section class="card"><h2>BMI scale</h2>
      <div class="bmi-scale"><i class="start" style="left:${scalePos(p.start.bmi)}%" title="Start BMI ${p.start.bmi}"></i><i style="left:${scalePos(p.current.bmi)}%" title="Now BMI ${p.current.bmi}"></i></div>
      <div class="row between"><small>15</small><small>18.5</small><small>25</small><small>30</small><small>40</small></div>
      <p style="margin-top:12px" class="muted">Grey marker = start (${p.start.bmi}), white marker = now (${p.current.bmi}).<br>Healthy weight for ${p.member.height_cm} cm: <b style="color:var(--text)">${p.healthy_range.min}–${p.healthy_range.max} kg</b>.</p>
      <p class="muted" style="margin-top:8px">BMI = weight (kg) ÷ height (m)²</p>
    </section>
    ${logForm}
  </div>

  <div class="section-title">Monthly summary</div>
  <div class="table-wrap"><table><thead><tr><th>Month</th><th class="num">End weight</th><th class="num">Average</th><th class="num">BMI</th><th class="num">Change</th><th class="num">Weigh-ins</th></tr></thead><tbody>
    ${p.monthly.slice().reverse().map((m) => `<tr><td>${fmonthLong(m.month)}</td><td class="num">${m.end_weight} kg</td><td class="num">${m.avg_weight} kg</td><td class="num">${m.bmi}</td>
      <td class="num ${m.change === 0 ? "delta-flat" : (loseGoal === null ? "" : (loseGoal ? m.change < 0 : m.change > 0) ? "delta-down" : "delta-up")}">${sign(m.change)} kg</td><td class="num">${m.weigh_ins}</td></tr>`).join("")}
  </tbody></table></div>

  <div class="section-title">Recent entries</div>
  <div class="table-wrap"><table><thead><tr><th>Date</th><th class="num">Weight</th><th class="num">BMI</th><th class="num">Body fat</th><th class="num">Waist</th><th>Note</th><th></th></tr></thead><tbody>
    ${p.logs.slice(-10).reverse().map((l) => `<tr><td>${fdate(l.log_date)}</td><td class="num">${l.weight_kg} kg</td><td class="num">${bmiVal(l.weight_kg, p.member.height_cm)}</td>
      <td class="num">${l.body_fat_pct ?? "—"}${l.body_fat_pct ? "%" : ""}</td><td class="num">${l.waist_cm ?? "—"}</td><td>${esc(l.note || "")}</td>
      <td><button class="sm danger" onclick="deleteLog(${l.log_id})">✕</button></td></tr>`).join("")}
  </tbody></table></div>`;
};
function setChart(mode) { state.chart = mode; route(); }
function bmiPreview(w) {
  const el = $("#bmi-live"); if (!el) return;
  const x = parseFloat(w);
  if (!x) { el.textContent = `Height ${state.height} cm · type your weight to preview BMI`; return; }
  const b = bmiVal(x, state.height);
  el.innerHTML = `BMI <b>${b}</b> · <span class="cat-${bmiCat(b)}">${bmiCat(b)}</span>`;
}
async function submitProgress(e) {
  e.preventDefault();
  if (await act(() => api(`/api/members/${state.who}/progress`, "POST", formObj(e.target)), "Progress saved")) { await loadMembers(); route(); }
  return false;
}
async function deleteLog(id) { if (confirm("Delete this entry?") && await act(() => api(`/api/progress/${id}`, "DELETE"), "Entry deleted")) route(); }

/* ----------------------------------------------------------------- boot */
(async function init() {
  try { await loadMembers(); } catch (e) { $("#view").innerHTML = `<div class="empty">⚠️ Cannot reach the server: ${esc(e.message)}</div>`; return; }
  route();
})();
