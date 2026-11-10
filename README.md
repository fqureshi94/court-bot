# Islington indoor court bot — setup (about 10 minutes, no coding)

It checks every 10 minutes, for free, using GitHub. Claude isn't involved once it's set up, so it uses no credits.

## 1. Get the phone app (2 min)
1. Install **ntfy** on your phone (App Store / Google Play — it's free, no account needed).
2. Tap **+** and subscribe to a topic name only you know, e.g. `faizan-courts-7x9k2q`. Write it down. Anyone who guesses the name can read your alerts, so make it random.

## 2. Make a GitHub account and repo (4 min)
1. Sign up at github.com (free).
2. Top right **+** → **New repository** → name it `court-bot` → choose **Public** (keeps it free and unlimited; your passwords stay hidden as secrets) → **Create repository**.
3. On the next page, click **uploading an existing file** and drag in **everything in this folder**, including the `.github` folder. Tip: on a Mac, press Cmd+Shift+. in Finder to see the hidden `.github` folder. Then click **Commit changes**.

## 3. Add your secrets (3 min)
In the repo: **Settings → Secrets and variables → Actions → New repository secret**. Add three:

| Name | Value |
|---|---|
| `NTFY_TOPIC` | the topic from step 1 |
| `BETTER_EMAIL` | your Better login email |
| `BETTER_PASSWORD` | your Better password |

## 4. Turn it on
**Actions** tab → enable workflows if asked → **Check Islington courts** → **Run workflow**. A green tick means it's working.

## What it does
- Weekdays only. Slots starting 19:00, 20:00 or 21:00, from 25 Nov onwards.
- **Less than 4 hours away:** sends a "Court free" alert. Tap it to book.
- **4 or more hours away:** adds a court to your Better basket, which holds it so nobody else can take it, and sends an urgent "Court held — pay now" alert. Tap it and check out. It holds at most one court per evening.
- New days open at **22:00, six days ahead** (for example, 25 Nov opens at 22:00 on 19 Nov). Around that time it checks every 20 seconds.

## Change things later
Edit `.github/workflows/check.yml` on GitHub (pencil icon). Change `START_DATE`, `EARLIEST_START`, `LATEST_START` or `NOTIFY_ONLY_HOURS`. To get alerts only, with no basket holds, set `AUTOBOOK: "false"`.
To stop it: **Actions → Check Islington courts → ⋯ → Disable workflow**.
