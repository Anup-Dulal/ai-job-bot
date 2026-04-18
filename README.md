# AI Job Bot

An autonomous multi-agent job search assistant that scrapes job listings from LinkedIn, Naukri, Glassdoor, and Adzuna, scores them against your resume using a hybrid rule-based + LLM approach, and notifies you via Telegram — all on a configurable schedule.

---

## How It Works

```
Job Sources          Scoring Pipeline         You
─────────────        ────────────────         ───
LinkedIn      ──┐
Naukri        ──┤──▶ Pre-filter ──▶ Rule-based score ──▶ LLM score ──▶ Shortlist ──▶ Telegram
Glassdoor     ──┤                                                                       │
Adzuna        ──┘                                                                       ▼
                                                                              APPLY / REJECT / SKIP
                                                                                       │
                                                                                       ▼
                                                                          Resume tailoring + Cover letter
```

1. **Scraper Agent** — fetches jobs across 4 sources using LLM-generated or configured keywords
2. **Scoring Agent** — scores each job on skill match, experience fit, role similarity, and bonus keywords; blends rule-based (70%) and LLM (30%) scores
3. **Notification Agent** — sends a ranked shortlist to Telegram with inline APPLY / REJECT / SKIP buttons
4. **Resume Optimizer Agent** — when you choose APPLY, tailors your resume and generates a cover letter
5. **Storage** — persists all jobs, decisions, and pipeline run history in a local SQLite database

---

## Features

- Scrapes **LinkedIn, Naukri, Glassdoor, and Adzuna** in a single run
- **LLM-powered keyword generation** via Groq (falls back to sensible defaults)
- **Hybrid scoring**: skill overlap, experience range, role title similarity, bonus keywords
- **Telegram notifications** with job cards and reply keyboard for decisions
- **Resume tailoring** and **cover letter generation** on APPLY
- **Rule-based Q&A engine** for common application form questions
- **SQLite persistence** — deduplication, notified-at tracking, run history
- **FastAPI REST API** for manual triggers and webhook integration
- **Configurable entirely via environment variables** — no code changes needed
- Deployable as a **Render worker** or any Python host

---

## Project Structure

```
ai-job-bot/
├── main.py              # FastAPI app — REST endpoints
├── pipeline.py          # Multi-agent workflow orchestration
├── storage.py           # SQLite persistence layer
├── naukri_fetcher.py    # Job scrapers (LinkedIn, Naukri, Glassdoor, Adzuna)
├── notifier.py          # Telegram notifications and command parsing
├── qa_engine.py         # Rule-based answers for application form questions
├── resume_profile.py    # Candidate profile loaded from env / JSON file
├── agent.py             # LLM-based job scoring agent
├── llm_client.py        # Groq LLM client wrapper
├── pre_filter.py        # Fast pre-filter before deep scoring
├── scheduler.py         # Runs the pipeline once or in a loop
├── render.yaml          # Render deployment config
├── .env.example         # All supported environment variables
└── data/
    └── job_bot.db       # SQLite database (auto-created)
```

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/Anup-Dulal/ai-job-bot.git
cd ai-job-bot
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your values
```

At minimum you need:

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | Groq API key for LLM scoring ([console.groq.com](https://console.groq.com)) |
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |

### 3. Run

**Scheduled loop (default):**
```bash
python scheduler.py
```

**Single run:**
```bash
RUN_MODE=once python scheduler.py
```

**API server:**
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## Environment Variables

### Core

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | — | Groq API key (required) |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token (required for notifications) |
| `TELEGRAM_CHAT_ID` | — | Telegram chat ID (required for notifications) |
| `RUN_MODE` | `loop` | `loop` for scheduled runs, `once` for a single run |
| `SCHEDULE_MINUTES` | `60` | Interval between pipeline runs |
| `PORT` | `8000` | Port for the FastAPI server |

### Job Search

| Variable | Default | Description |
|---|---|---|
| `SEARCH_KEYWORDS` | LLM-generated | Comma-separated job search keywords |
| `SEARCH_LOCATIONS` | From profile | Comma-separated target locations |
| `MAX_JOBS_PER_RUN` | `50` | Max jobs to fetch per run |
| `MIN_FIT_SCORE` | `60` | Minimum score (0–100) to shortlist a job |
| `TOP_JOBS_TO_NOTIFY` | `5` | Number of top jobs to send via Telegram |

### Optional Job Sources

| Variable | Description |
|---|---|
| `ADZUNA_APP_ID` | Adzuna API app ID ([developer.adzuna.com](https://developer.adzuna.com)) |
| `ADZUNA_APP_KEY` | Adzuna API key |

### Candidate Profile

All profile fields can be set via environment variables. See `.env.example` for the full list. Key ones:

| Variable | Description |
|---|---|
| `PROFILE_NAME` | Your full name |
| `PROFILE_EMAIL` | Your email |
| `PROFILE_TITLE` | Your job title |
| `PROFILE_EXP_YEARS` | Years of experience |
| `PROFILE_NOTICE` | Notice period |
| `PROFILE_CTC_EXP` | Expected CTC |
| `PROFILE_SKILLS_*` | Comma-separated skills per category |
| `PROFILE_JSON_PATH` | Path to a full profile JSON file (overrides individual vars) |

---

## Telegram Commands

Once the bot sends you a job card, reply with:

```
APPLY <job_id>    — Triggers resume tailoring and cover letter generation
REJECT <job_id>   — Marks the job as rejected
SKIP <job_id>     — Skips the job for now
```

---

## REST API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Health check and integration status |
| `POST` | `/pipeline/run` | Trigger a pipeline run |
| `GET` | `/pipeline/pending` | List jobs awaiting a decision |
| `POST` | `/pipeline/decision` | Submit APPLY / REJECT / SKIP |
| `GET` | `/pipeline/runs` | Recent pipeline run history |
| `GET` | `/pipeline/action/{job_id}` | Get action status for a job |
| `POST` | `/telegram/webhook` | Telegram webhook endpoint |
| `POST` | `/process` | Score a single job |
| `POST` | `/batch` | Score a batch of jobs |

---

## Deployment on Render

The repo includes a `render.yaml` for one-click deployment as a background worker.

1. Push to GitHub
2. Create a new **Background Worker** on [render.com](https://render.com) and connect the repo
3. Set the required environment variables in the Render dashboard
4. Deploy — the scheduler will start automatically

---

## Customising Your Profile

The easiest way is via environment variables in `.env`. For a richer profile, create a JSON file matching the structure in `resume_profile.py` and point to it with `PROFILE_JSON_PATH`.

---

## License

MIT
