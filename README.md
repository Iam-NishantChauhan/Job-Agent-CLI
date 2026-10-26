<h1 align="center">Job Search Agent</h1>

<p align="center"><strong>A local, open-source job finder for software engineers.</strong><br>
It reads company career boards directly, keeps only the roles that fit your resume,<br>
and pings your phone the day they are posted.</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/flask-local%20web%20app-000000?style=flat-square&logo=flask" alt="Flask">
  <img src="https://img.shields.io/badge/runs%20on-macOS%20%7C%20Linux%20%7C%20Windows-8b7cf6?style=flat-square" alt="Cross-platform">
  <img src="https://img.shields.io/badge/alerts-Telegram-26A5E4?style=flat-square&logo=telegram&logoColor=white" alt="Telegram">
  <img src="https://img.shields.io/badge/license-MIT-2ea44f?style=flat-square" alt="MIT">
  <img src="https://img.shields.io/badge/you%20press-Submit-f4a261?style=flat-square" alt="You press Submit">
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#features">Features</a> ·
  <a href="#how-matching-works">How matching works</a> ·
  <a href="#faq">FAQ</a> ·
  <a href="CONTRIBUTING.md">Contribute</a>
</p>

<!-- Add a screenshot or GIF: save it as docs/demo.png (or demo.gif) and uncomment the next line -->
<!-- <p align="center"><img src="docs/demo.png" alt="JobAgent dashboard" width="800"></p> -->

---

## The problem

Job alerts from the big boards arrive a day or two late, and they point at postings that already have hundreds of applicants. Meanwhile most product companies publish the same job on their own career board the moment it opens.

JobAgent watches those boards for you. You upload your resume once. Every day it pulls fresh postings, throws away what does not fit, and shows the rest in one place, sorted by how well they match your skills.

> **Find fast. Apply yourself.** JobAgent never submits an application for you. Every company's form is different and bots get flagged. You open the job, you press Submit.

## What it does for you

| Question | What JobAgent does |
|---|---|
| **Is it new?** | Filters by posting date. Set "max job age" to 3 days and stale roles never reach you. |
| **Is it a product company?** | Known service and consulting firms are blocked. |
| **Does it fit me?** | Reads your resume, finds your skills, and scores each job against the whole description. |
| **Is it in my city?** | Matches your location list. Foreign-only "remote" roles are dropped unless you ask for worldwide remote. |
| **How do I know about it?** | New matches arrive on Telegram. |
| **What should I change on my resume?** | Shows matched and missing skills per job and builds a ready prompt for tailoring. |
| **Where does my data go?** | Nowhere. Everything stays in one local SQLite file. |

## Features

- **Resume-driven matching.** Upload a PDF, DOCX or TXT. Skills and years of experience are read from it. Click the skill chips to remove or add your own.
- **Five job-board types.** Greenhouse, Lever, Ashby, SmartRecruiters and Workday, plus optional worldwide remote jobs from Remotive and RemoteOK.
- **Discover companies.** One button tries a few hundred company names on every supported board and keeps the ones that have jobs.
- **Add any company.** Type a name (`razorpay`) or paste a careers link, Workday links included. It finds the board for you and remembers it.
- **Filters you control.** Locations, max job age, minimum salary (when a posting lists one) and minimum match percentage.
- **A fetch report that explains itself.** After every run you see how many postings were checked and exactly why the rest were dropped (title, location, age, skills). No guessing why you got zero results.
- **Apply flow.** The Apply button opens the job in a new tab. When you come back, the app asks "Did you apply?" and tracks it as To apply, Applied or Not interested.
- **Resume tailoring.** Gets the job's requirements and your resume into one prompt. Paste it into any AI chatbot. The prompt tells the AI to reorder and rephrase only what is already there, never to invent experience.
- **Telegram alerts.** Top matches from each fetch land on your phone.
- **Daily auto-fetch** while the app is running.

## Quick start

You need **Python 3.9 or newer** and a Telegram account. No Docker, no database server, no API keys.

### 1. Get the code

```bash
git clone https://github.com/YOUR-USERNAME/jobagent.git
cd jobagent
```

### 2. Install

**macOS and Linux**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

**Windows (PowerShell)**

```powershell
py -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

**Windows (Command Prompt)**

```bat
py -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt
copy .env.example .env
```

> If PowerShell blocks the activate script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

### 3. Set up Telegram (required)

Alerts are the whole point, so do this before the first run. It takes two minutes.

1. In Telegram open **@BotFather**, send `/newbot`, follow the prompts, and copy the token. It looks like `123456789:AAH...` and **includes the colon**.
2. Open your new bot and press **Start**. A bot cannot message you until you do.
3. Open **@userinfobot**, press Start, and copy the number it shows as `Id`. It is a number, not your username.
4. Open the `.env` file in the project folder and replace exactly these two lines:

```
TELEGRAM_TOKEN=123456789:AAH...your-full-token...
TELEGRAM_CHAT=your-numeric-id
```

`.env` is in `.gitignore`, so your token is never committed. Never paste it into `app.py` and never share a screenshot of it. If it leaks, send `/revoke` to @BotFather.

### 4. Run

```bash
python app.py
```

Open **http://localhost:5001** (or `http://127.0.0.1:5001`). Use `python3` instead of `python` if your system needs it.

### 5. First-time flow

1. Upload your resume and check the skill chips.
2. Press **Save profile**.
3. Press **Test Telegram**. A message should arrive on your phone. If it does not, the app tells you whether the token or the chat ID is wrong.
4. Press **Discover companies** once. It runs in the background and takes a few minutes.
5. Press **Fetch new jobs**.

**Tip:** do one backfill with max job age at 30 days to see what is open right now, then set it to 3 for daily use.

## Usage

| Control | What it does |
|---|---|
| **Save profile** | Saves your skills and filters, clears old unreviewed jobs and fetches again with the new settings. |
| **Fetch new jobs** | Pulls every tracked company and shows only jobs the app has not seen before. |
| **Discover companies** | Tests a built-in list of company names on every supported job board and adds the ones that exist. |
| **Add** (company box) | Add one company by name or by careers-page link. Added companies are saved permanently. |
| **Test Telegram** | Sends a test message so you know alerts work. |
| **Tailor resume** | Opens a page with matched and missing skills and a copy-ready AI prompt for that job. |
| **Last fetch panel** | The funnel: postings checked, jobs kept, and why each of the rest was removed. |

The app fetches automatically once a day (default 7 AM, change `DAILY_HOUR` in `.env`), but only while it is running. Leave it open in a terminal, or press **Fetch new jobs** each morning.

## How matching works

A job is kept only if every check passes.

| Check | Rule |
|---|---|
| **Company** | Not on the service and consulting blocklist. |
| **Title** | Looks like a software engineering role. Sales, QA, devops, data, security and management titles are dropped. Senior and staff titles are dropped if you have under 5 years of experience. |
| **Location** | Matches your location list. |
| **Age** | Posted within your max-days setting. |
| **Salary** | Above your minimum, only when the posting actually lists one. Postings without a salary are kept and marked "not listed". |
| **Skills** | At least 2 of your skills appear anywhere in the full job description. |
| **Match %** | Your matching skills divided by the skills the posting lists (capped at 8), plus a small bonus when one of your skills is in the title. Must be above your slider. |

Matching is driven only by your resume. If a skill is not on it, it is never added for you.

## Supported sources

| Source | How it is read | Notes |
|---|---|---|
| Greenhouse | Public job-board API | Full descriptions |
| Lever | Public postings API | Full descriptions |
| Ashby | Public job-board API | Full descriptions |
| SmartRecruiters | Public postings API | India-filtered |
| Workday | Public career-site JSON | Needs the careers link. Detail pages are fetched only for roles that pass the title, age and location checks |
| Remotive, RemoteOK | Public APIs | Optional worldwide remote |

**Not supported on purpose:** LinkedIn, Naukri and Indeed. They have no public API and scraping risks account bans. Keep their native alerts on alongside JobAgent.

**Not supported yet:** companies on their own custom career site, and boards such as Workable, Recruitee, BambooHR, Darwinbox and Keka. See [CONTRIBUTING.md](CONTRIBUTING.md) if you want to add one.

## Project structure

```
jobagent/
├── app.py              The whole app: Flask server, fetchers, matcher, UI
├── requirements.txt    flask, requests, pypdf, python-docx
├── .env.example        Copy to .env and add your Telegram details
├── .gitignore          Keeps .env, agent.db and venv out of git
├── CONTRIBUTING.md
├── LICENSE
└── agent.db            Created on first run (your profile and jobs, git-ignored)
```

The app is one file on purpose, so it is easy to read and change.

## Tech stack

Python, Flask, SQLite, `requests`, `pypdf`, `python-docx`. The interface is plain HTML, CSS and a little JavaScript served by Flask. No build step.

## FAQ

**Does it apply to jobs for me?**
No. It finds and tracks. You submit. That is a design decision, not a missing feature.

**Will it work on Windows and Linux?**
Yes. It is plain Python and Flask with no OS-specific code. It is developed on macOS, so if you hit a problem on another system, please open an issue.

**Why did I get zero jobs?**
Open the **Last fetch** panel. It lists how many postings were checked and why each was dropped. The usual causes are max job age too low, locations too narrow, or a very short skill list. Try max age 30 once.

**Why are there not many India roles at big companies?**
Large global companies publish few India-specific openings. Press **Discover companies** and add Indian product startups with the company box.

**Do I need a paid AI key?**
No. Tailoring gives you a prompt to paste into any chatbot you already use.

**Is my resume uploaded anywhere?**
No. It is parsed on your machine and stored in `agent.db`. The only outbound traffic is to the public job-board APIs and to Telegram.

**Can I share it with a friend?**
Yes. Send them the repository, never your `agent.db` or `.env`. They upload their own resume and get their own database.

**It stopped sending alerts.**
The app only fetches while it is running. If the laptop slept or the terminal closed, nothing runs. Also check **Test Telegram**.

## Known limits

- Fetching happens only while the app is running. It is not a background service.
- Some boards only expose "last updated", so an old posting that was edited can look newer than it is.
- Company discovery works by guessing names, so some companies will be missed. Add them by link.
- Workday support reads the public career-site data and may not work for every tenant.

## Contributing

Pull requests are welcome, especially new job sources and more Indian product companies. Start with [CONTRIBUTING.md](CONTRIBUTING.md). If you report a bug, include a screenshot of the **Last fetch** panel.

## Disclaimer

JobAgent reads publicly available job-board data for personal use. It is not affiliated with any company or job board it reads. Be a good citizen: do not run it in a tight loop, and do not use it to spam applications. You are responsible for what you submit.

## License

[MIT](LICENSE) © 2026 Nishant Chauhan

<p align="center"><sub>If JobAgent helped you land an interview, a ⭐ helps the next person find it.</sub></p>
