"""
Islington Tennis Centre indoor court watcher (Better / GLL).

- Checks weekday slots starting 19:00-21:00 from START_DATE onwards.
- Slot starts < 4h from now  -> push notification with a booking link.
- Slot starts >= 4h from now -> logs in and adds it to your Better basket
  (this reserves it for you), then pushes "pay now" with the checkout link.
  If anything in that step fails it falls back to a normal notification.
- Remembers what it already told you about (state.json) so you aren't spammed.

Only uses the Python standard library. Settings come from environment variables
(GitHub Actions secrets) - see README.md.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
API = "https://better-admin.org.uk/api"
SITE = "https://bookings.better.org.uk"
VENUE = "islington-tennis-centre"
ACTIVITY = "tennis-court-indoor"

START_DATE = date.fromisoformat(os.getenv("START_DATE", "2026-11-25"))
EARLIEST = os.getenv("EARLIEST_START", "19:00")   # inclusive
LATEST = os.getenv("LATEST_START", "21:00")       # inclusive
NOTIFY_ONLY_HOURS = float(os.getenv("NOTIFY_ONLY_HOURS", "4"))
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
BETTER_EMAIL = os.getenv("BETTER_EMAIL", "")
BETTER_PASSWORD = os.getenv("BETTER_PASSWORD", "")
AUTOBOOK = os.getenv("AUTOBOOK", "true").lower() == "true"
STATE_FILE = os.getenv("STATE_FILE", "state.json")

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": SITE,
    "Referer": SITE + "/",
    "User-Agent": "Mozilla/5.0 (court-watcher)",
}


def http(method, url, body=None, token=None, timeout=20):
    headers = dict(HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def as_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.values())
    return []


# ---------- availability ----------

def bookable_dates():
    status, j = http("GET", f"{API}/activities/venue/{VENUE}/activity-category/{ACTIVITY}/dates")
    if status != 200:
        raise RuntimeError(f"dates endpoint returned {status}")
    return [date.fromisoformat(d["raw"]) for d in as_list(j.get("data"))]


def wanted_slots(day):
    """Time slots on `day` in the wanted window that have free courts."""
    url = f"{API}/activities/venue/{VENUE}/activity/{ACTIVITY}/v2/times?date={day.isoformat()}"
    status, j = http("GET", url)
    if status != 200:
        return []
    out = []
    for s in as_list(j.get("data")):
        start = s["starts_at"]["format_24_hour"]
        if not (EARLIEST <= start <= LATEST):
            continue
        if (s.get("spaces") or 0) > 0 and (s.get("action_to_show") or {}).get("status") == "BOOK":
            out.append({"date": day.isoformat(), "start": start,
                        "end": s["ends_at"]["format_24_hour"], "spaces": s["spaces"],
                        "price": (s.get("price") or {}).get("formatted_amount", "")})
    return out


def court_slots(slot):
    """Individual court slots (with ids needed for the basket) for one time."""
    url = (f"{API}/activities/venue/{VENUE}/activity/{ACTIVITY}/v2/slots"
           f"?date={slot['date']}&start_time={slot['start']}&end_time={slot['end']}")
    status, j = http("GET", url)
    if status != 200:
        return []
    return [c for c in as_list(j.get("data"))
            if (c.get("spaces") or 0) > 0 and (c.get("action_to_show") or {}).get("status") == "BOOK"]


# ---------- booking (basket hold) ----------

_session = {}


def login():
    if "token" in _session:
        return _session["token"], _session["user_id"]
    status, j = http("POST", f"{API}/auth/customer/login",
                     {"username": BETTER_EMAIL, "password": BETTER_PASSWORD})
    token = j.get("token") or (j.get("data") or {}).get("token")
    if status != 200 or not token:
        raise RuntimeError(f"login failed ({status})")
    status, u = http("GET", f"{API}/auth/user", token=token)
    user_id = (u.get("data") or {}).get("id")
    _session.update(token=token, user_id=user_id)
    return token, user_id


def hold_in_basket(slot):
    token, user_id = login()
    for court in court_slots(slot):
        body = {
            "items": [{
                "id": court["id"],
                "type": court.get("cart_type", "activity"),
                "pricing_option_id": court.get("pricing_option_id"),
                "apply_benefit": True,
                "activity_restriction_ids": [],
            }],
            "membership_user_id": user_id,
            "selected_user_id": None,
        }
        status, j = http("POST", f"{API}/activities/cart/add", body, token=token)
        if status in (200, 201):
            return (court.get("location") or {}).get("name", "a court")
        print(f"  basket add failed for one court ({status}): {str(j)[:200]}")
    raise RuntimeError("no court could be added to the basket")


# ---------- notifications ----------

def notify(title, message, url, priority="default", tags="tennis"):
    print(f"NOTIFY: {title} | {message}")
    if not NTFY_TOPIC:
        return
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode(), method="POST",
        headers={"Title": title, "Priority": priority, "Tags": tags, "Click": url})
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"  ntfy failed: {e}")


# ---------- state ----------

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    today = date.today().isoformat()
    state = {k: v for k, v in state.items() if k[:10] >= today}  # drop past slots
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)


# ---------- main ----------

def check_once(state):
    now = datetime.now(LONDON)
    days = [d for d in bookable_dates() if d >= START_DATE and d.weekday() < 5]
    seen_now = set()
    for day in days:
        for slot in wanted_slots(day):
            key = f"{slot['date']} {slot['start']}"
            seen_now.add(key)
            starts = datetime.fromisoformat(f"{slot['date']}T{slot['start']}").replace(tzinfo=LONDON)
            hours_away = (starts - now).total_seconds() / 3600
            if hours_away <= 0:
                continue
            nice = starts.strftime("%a %d %b %H:%M")
            link = f"{SITE}/location/{VENUE}/{ACTIVITY}/{slot['date']}/by-time"

            if hours_away >= NOTIFY_ONLY_HOURS and AUTOBOOK and BETTER_EMAIL:
                if any(k.startswith(slot["date"]) and v == "held" for k, v in state.items()):
                    continue  # already holding a court that evening - one per day is enough
                try:
                    court = hold_in_basket(slot)
                    state[key] = "held"
                    notify(f"Court held: {nice}",
                           f"{court} is in your Better basket ({slot['price']}). "
                           f"Tap to check out and pay NOW before the hold expires.",
                           f"{SITE}/basket", priority="urgent", tags="tennis,rotating_light")
                    continue
                except Exception as e:
                    print(f"  autobook failed for {key}: {e} - notifying instead")
            if state.get(key) in ("notified", "held"):
                continue
            state[key] = "notified"
            notify(f"Court free: {nice}",
                   f"{slot['spaces']} indoor court(s) free at {slot['start']} ({slot['price']}). Tap to book.",
                   link, priority="high")
    # if a slot we notified about got taken, forget it so a later cancellation alerts again
    for k in [k for k, v in state.items() if v == "notified" and k not in seen_now]:
        del state[k]


def main():
    state = load_state()
    now = datetime.now(LONDON)
    # New days are released at 22:00 UK time. If this run starts shortly before,
    # keep polling every 20s until 22:05 so we catch the release instantly.
    release = now.replace(hour=22, minute=0, second=0, microsecond=0)
    snipe = timedelta(minutes=-20) <= (now - release) <= timedelta(minutes=5)
    deadline = release + timedelta(minutes=5) if snipe else now
    while True:
        try:
            check_once(state)
        except Exception as e:
            print(f"check failed: {e}")
        save_state(state)
        if datetime.now(LONDON) >= deadline:
            break
        time.sleep(20)


if __name__ == "__main__":
    sys.exit(main())
