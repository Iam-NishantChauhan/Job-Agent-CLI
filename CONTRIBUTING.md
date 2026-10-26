# Contributing to JobAgent

Thanks for helping! The whole app is one file (`app.py`) on purpose, so it is easy to read and hack on.

## Quick start
1. Fork the repo and clone your fork.
2. Create a virtual environment (`python3 -m venv venv`, then `source venv/bin/activate` on macOS or Linux, `venv\Scripts\activate` on Windows)
3. `pip install -r requirements.txt`
4. `python app.py` and open http://localhost:5001

## Easy first contributions
- **Add companies**: put slugs into the `COMPANIES` dict or names into `CANDIDATES` (India-based product startups are very welcome).
- **Add a job source**: write a new branch in `fetch_co()` that returns jobs through the `J(...)` helper. Workable, Recruitee and BambooHR are good candidates.
- **Improve matching**: skill lists (`SKILLS`, `EXTRA`), title filters and the score formula live in `evaluate()`.
- **Fix a bug**: open an issue first with a screenshot of the "Last fetch" panel, it shows exactly why jobs were dropped.

## Rules
- Never commit `.env`, `agent.db`, resumes or tokens.
- No auto-apply, no scraping of LinkedIn, Naukri or Indeed. This project only uses public job-board APIs.
- Keep it dependency-light. Python standard library plus what is already in `requirements.txt` is preferred.
- Before a PR run `python3 -m py_compile app.py`.

## Pull requests
Small and focused is best. Describe what changed and, if you can, paste the "Last fetch" numbers before and after.