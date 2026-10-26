"""JobAgent - upload resume, get matched jobs daily. Run: python app.py  ->  http://localhost:5001"""
import html, io, json, os, re, sqlite3, threading, time, datetime
from concurrent.futures import ThreadPoolExecutor
import requests
from flask import Flask, request, jsonify, render_template_string, redirect

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent.db")


def _load_env(path=".env"):
    """Read KEY=value lines from a local .env file (git-ignored) so secrets never go in the code."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    if not os.path.exists(p): return
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

def _load_env():
    """Read KEY=value lines from a .env file next to app.py (real environment variables still win)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path): return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
DAILY_HOUR = int(os.getenv("DAILY_HOUR", "7"))  # auto-fetch every day at 7 AM while app is running
TG_TOKEN, TG_CHAT = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT")  # set in .env
app = Flask(__name__)

SKILLS = ("python,java,javascript,typescript,react,angular,vue,node,express,django,flask,fastapi,spring,golang,go,rust,"
          "c++,c#,.net,sql,mysql,postgres,mongodb,redis,kafka,rabbitmq,aws,azure,gcp,docker,kubernetes,terraform,jenkins,"
          "git,microservices,graphql,rest,html,css,tailwind,next.js,redux,spark,airflow,elasticsearch,linux,ci/cd,"
          "machine learning,kotlin,swift,android,ios,php,laravel,system design,dsa,data structures,algorithms").split(",")
TITLES = [r"\bsde\b", r"software (engineer|developer)", r"\bswe\b", r"full.?stack", r"back.?end", r"front.?end",
          r"member of technical staff", r"\bmts\b", r"\bdeveloper\b", r"\bengineer (i|ii|1|2)\b", r"\bsde.?(1|2|i|ii)\b",
          r"web developer", r"application engineer", r"platform engineer"]
EXTRA = ("llm,rag,langchain,openai,pytorch,tensorflow,scala,ruby,rails,elixir,haskell,perl,matlab,unity,solidity,blockchain,computer vision,"
         "nlp,deep learning,data science,pandas,numpy,dbt,hadoop,flink,cassandra,dynamodb,grpc,websocket,flutter,react native,svelte,nestjs,"
         "asp.net,objective-c,embedded,cuda").split(",")
ALLSK = list(dict.fromkeys(SKILLS + EXTRA))
LOCS = "india,bangalore,bengaluru,hyderabad,pune,mumbai,gurgaon,gurugram,noida,delhi,chennai,remote".split(",")
COMPANIES = {  # product companies only. Slugs are checked automatically; see "Companies tracked" in the app.
    "greenhouse": "stripe airbnb databricks cloudflare coinbase twilio postman groww phonepe razorpaysoftwareprivatelimited "
                  "gitlab elastic mongodb datadog okta pinterest zscaler thoughtspot browserstack sprinklr chargebee".split(),
    "lever": "cred meesho paytm upgrad freshworks".split(),
    "ashby": "notion ramp linear openai snowflake zapier retool deel rippling".split(),
    "smartrecruiters": [],
}
COMPANIES["greenhouse"] += "figma discord reddit dropbox instacart lyft duolingo vercel webflow mixpanel amplitude gusto asana intercom".split()
COMPANIES["ashby"] += "supabase clickhouse posthog".split()
COMPANIES["greenhouse"] += ("airtable brex mercury scaleai anthropic cockroachlabs temporal fivetran plaid chime "
    "carta lattice faire flexport gofundme hashicorp grafanalabs sentry newrelic launchdarkly squarespace toast verkada bitgo "
    "juspay zepto swiggy lenskart slice jupiter navi khatabook sharechat dream11 unacademy "
    "clevertap moengage innovaccer whatfix hasura rudderstack druva icertis").split()
COMPANIES["lever"] += "rapido pocketfm kuku dunzo spotify".split()
COMPANIES["ashby"] += "cursor perplexity mistral elevenlabs resend clerk neon mintlify dub hex modal replit".split()
TIER1 = set("stripe airbnb databricks cloudflare coinbase openai notion ramp figma snowflake datadog mongodb postman cred phonepe groww meesho "
            "razorpaysoftwareprivatelimited discord linear vercel supabase rippling".split())
SERVICE = set("tcs infosys wipro cognizant accenture capgemini hcl hcltech techmahindra ltimindtree mphasis hexaware genpact "
              "deloitte kpmg pwc ey persistent zensar coforge virtusa epam globant cgi ibm".split())  # service firms are never fetched
GENERIC = set("git,rest,css,html,sql,ci/cd,linux,algorithms,data structures,dsa,system design,go".split(","))
FOREIGN = r"\b(us|usa|united states|canada|uk|united kingdom|emea|europe|germany|poland|brazil|mexico|australia|singapore|japan|ireland|france|spain|netherlands)\b"


def q(sql, args=(), one=False):
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,company,title,location,url,score REAL,salary,hits,status DEFAULT 'new',seen REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS kv(k PRIMARY KEY,v)")
    c.execute("CREATE TABLE IF NOT EXISTS co(platform,slug,PRIMARY KEY(platform,slug))")
    c.execute("CREATE TABLE IF NOT EXISTS jd(id PRIMARY KEY,t)")
    r = c.execute(sql, args); out = r.fetchone() if one else r.fetchall(); c.commit(); c.close(); return out


def kget(k, d=None):
    r = q("SELECT v FROM kv WHERE k=?", (k,), True); return json.loads(r["v"]) if r else d


def kset(k, v): q("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, json.dumps(v)))


def resume_text(f):
    data, name = f.read(), f.filename.lower()
    try:
        if name.endswith(".pdf"):
            from pypdf import PdfReader
            return " ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
        if name.endswith(".docx"):
            import docx
            return " ".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)
    except Exception as e:
        print("resume parse error", e)
    return data.decode("utf-8", "ignore")


def parse_resume(text):
    t = text.lower()
    skills = [s for s in ALLSK if re.search(r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9+#])", t)]
    yrs = [float(x) for x in re.findall(r"(\d{1,2}(?:\.\d)?)\+?\s*(?:years|yrs)", t) if float(x) < 20]
    return skills, max(yrs) if yrs else 0.0


def strip(t): return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(t or "")))


def get(url):
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "jobagent/2.0"}); return r.json() if r.ok else None
    except Exception: return None


def ts(v):
    try:
        if isinstance(v, (int, float)): return v / 1000 if v > 1e11 else float(v)
        return datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp() if v else None
    except Exception: return None


def J(src, co, i, title, loc, url, desc, posted=None): return dict(id=f"{src}:{co}:{i}", company=co, title=title or "", location=loc or "", url=url, desc=strip(desc), posted=ts(posted))


def fetch_co(p_s):
    p, s = p_s
    if p == "greenhouse":
        d = get(f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs?content=true") or {}
        return [J(p, s, j["id"], j["title"], (j.get("location") or {}).get("name"), f"https://job-boards.greenhouse.io/{s}/jobs/{j['id']}", j.get("content"), j.get("first_published") or j.get("updated_at")) for j in d.get("jobs", [])]
    if p == "lever":
        return [J(p, s, j["id"], j["text"], j.get("categories", {}).get("location"), j["hostedUrl"], j.get("descriptionPlain"), j.get("createdAt")) for j in (get(f"https://api.lever.co/v0/postings/{s}?mode=json") or [])]
    if p == "ashby":
        d = get(f"https://api.ashbyhq.com/posting-api/job-board/{s}") or {}
        return [J(p, s, j["id"], j["title"], j.get("location"), j["jobUrl"], j.get("descriptionPlain"), j.get("publishedAt")) for j in d.get("jobs", [])]
    if p == "remotive":
        d = get("https://remotive.com/api/remote-jobs?category=software-dev&limit=300") or {}
        return [J(p, j["company_name"], j["id"], j["title"], "Remote - " + (j.get("candidate_required_location") or "Worldwide"), j["url"], j.get("description"), j.get("publication_date")) for j in d.get("jobs", [])]
    if p == "remoteok":
        d = get("https://remoteok.com/api") or []
        return [J(p, j.get("company", ""), j["id"], j.get("position", ""), "Remote - " + (j.get("location") or "Worldwide"), j.get("url", ""), j.get("description"), j.get("date")) for j in d if isinstance(j, dict) and j.get("id")]
    if p == "smartrecruiters":
        d = get(f"https://api.smartrecruiters.com/v1/companies/{s}/postings?country=in&limit=100") or {}
        return [J(p, s, j["id"], j["name"], j.get("location", {}).get("city", "India"), f"https://jobs.smartrecruiters.com/{s}/{j['id']}", "", j.get("releasedDate")) for j in d.get("content", [])]
    if p == "workday": return fetch_workday(s)
    return []



# ---------- Workday (slug format: tenant|wdN|site, e.g. fnz|wd3|fnz_careers) ----------
WD_H = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json", "Accept": "application/json"}


def wd_age(txt):
    """'Posted 3 Days Ago' -> 3, 'Posted Today' -> 0, '30+ Days Ago' -> 30, unknown -> None."""
    t = (txt or "").lower()
    if "today" in t: return 0
    if "yesterday" in t: return 1
    m = re.search(r"(\d+)\+?\s*day", t)
    return int(m.group(1)) if m else None


def wd_ok(s):
    """True if this tenant|wd|site really is a Workday job board."""
    try:
        t, wd, site = s.split("|")
        r = requests.post(f"https://{t}.{wd}.myworkdayjobs.com/wday/cxs/{t}/{site}/jobs", json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}, headers=WD_H, timeout=12)
        return r.ok and "jobPostings" in r.json()
    except Exception: return False


def wd_probe(name):
    """Best-effort guess: open https://<name>.wdN.myworkdayjobs.com/ and read the site name it redirects to."""
    n = name.lower().replace("-", "")
    for wd in ("wd1", "wd3", "wd5", "wd12", "wd103"):
        try: r = requests.get(f"https://{n}.{wd}.myworkdayjobs.com/", timeout=6, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True)
        except Exception: continue
        m = re.search(r"myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)", r.url)
        if r.ok and m and m.group(1) != "wday" and wd_ok(f"{n}|{wd}|{m.group(1)}"): return [("workday", f"{n}|{wd}|{m.group(1)}")]
    return []


def fetch_workday(s):
    import hashlib
    try: t, wd, site = s.split("|")
    except ValueError: return []
    P = kget("profile") or {}
    maxd = P.get("max_days", 7)
    base = f"https://{t}.{wd}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{t}/{site}"
    posts, ENGT = {}, re.compile(r"engineer|developer|\bswe\b|\bsde\b|programmer|technical staff|\bmts\b|software|full.?stack|back.?end|front.?end|founding", re.I)
    for term in ("software engineer", "developer"):
        total = None
        for off in range(0, 300, 20):
            try:
                r = requests.post(api + "/jobs", json={"appliedFacets": {}, "limit": 20, "offset": off, "searchText": term}, headers=WD_H, timeout=20)
                d = r.json() if r.ok else {}
            except Exception: break
            batch = d.get("jobPostings") or []
            if off == 0: total = d.get("total", 0)
            for b in batch:
                if b.get("externalPath"): posts[b["externalPath"]] = b
            if not batch or (total is not None and off + 20 >= total): break
    keep = []
    for path, b in posts.items():
        age = wd_age(b.get("postedOn"))
        if not ENGT.search(b.get("title", "")): continue
        if age is not None and age > maxd + 1: continue
        loc = b.get("locationsText", "")
        if P.get("locs") and not re.match(r"\s*\d+\s+locations?", loc, re.I) and not loc_ok(loc, P): continue
        keep.append((path, b, age))

    def det(item):
        path, b, age = item
        try:
            r = requests.get(api + path, headers=WD_H, timeout=20)
            info = r.json().get("jobPostingInfo", {}) if r.ok else {}
        except Exception: info = {}
        loc = ", ".join(x for x in [info.get("location")] + list(info.get("additionalLocations") or []) if x) or b.get("locationsText", "")
        posted = info.get("startDate") or (time.time() - age * 86400 if age is not None else None)
        return J("workday", t, hashlib.md5(path.encode()).hexdigest()[:10], b.get("title"), loc, f"{base}/en-US/{site}{path}", info.get("jobDescription") or "", posted)
    with ThreadPoolExecutor(6) as ex: return list(ex.map(det, keep[:60]))


def lpa(text):
    v = [float(m) for m in re.findall(r"(\d{1,3}(?:\.\d+)?)\s*(?:lpa|lakhs?|lacs?)", text.lower())]; return max(v) if v else None


def loc_ok(loc, P):
    l = loc.lower()
    if any(x in l for x in P["locs"] if x != "remote"): return True
    return "remote" in P["locs"] and "remote" in l and not re.search(FOREIGN, l)


from collections import Counter
WHY = Counter()


def R(k): WHY[k] += 1


def has(blob, s): return re.search(r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9+#])", blob)


def evaluate(j, P):
    t = j["title"].lower()
    if set(re.sub(r"[^a-z]", " ", j["company"].lower()).split()) & (SERVICE | {"consulting", "staffing", "outsourcing", "services"}): return R("service company")
    ENG = r"engineer|developer|\bswe\b|\bsde\b|programmer|technical staff|\bmts\b|software|full.?stack|back.?end|front.?end|web dev|founding"
    BAD = r"intern\b|manager|director|head of|vp\b|\bhr\b|sales|marketing|recruit|designer|account|counsel|legal|finance|accountant|writer|customer|support|success|analyst|scientist|researcher|\bqa\b|quality|test engineer|sdet|devops|\bsre\b|reliability|security|solutions|sales engineer|data engineer|machine learning|ml engineer|hardware|mechanical|electrical|manufactur|operations|program manager|product manager|partner"
    if P["years"] < 5: BAD += r"|senior|sr\.|staff|principal|\blead\b|\b(iii|iv|3|4|5)\b|architect"
    if not re.search(ENG, t): return R("not an engineering title")
    if re.search(BAD, t): return R("title is non-dev, QA, devops, data or too senior")
    if not loc_ok(j["location"], P): return R("location not India/remote-friendly")
    if j["posted"] and time.time() - j["posted"] > P.get("max_days", 7) * 86400: return R("older than max job age")
    sal = lpa(j["desc"])
    if sal is not None and sal < P["min_lpa"]: return R("salary below minimum")
    blob = t + " " + j["desc"].lower()
    mine = set(P["skills"])
    need = [x for x in sorted(set(ALLSK) | mine) if x not in GENERIC and has(blob, x)]   # core skills the posting mentions anywhere
    core = [x for x in need if x in mine]
    if len(core) < min(2, len([x for x in mine if x not in GENERIC])): return R("fewer than 2 of your skills in the job")
    pct = min(100, round(100 * len(core) / min(len(need), 8))) if need else 0   # a posting listing 15 techs is not judged on all 15
    pct = min(100, pct + (10 if any(has(t, x) for x in core) else 0))   # bonus when your skill is in the job title
    if pct < P.get("min_pct", 40): return R("match % below your slider")
    hits = core + [x for x in P["skills"] if x in GENERIC and has(blob, x)]
    j.update(salary=f"{sal:g} LPA" if sal else "not listed", hits=", ".join(hits[:8]), score=pct, jd=j["desc"][:6000])
    return j


def tg(msg):
    """Send a Telegram message. Returns (ok, explanation) so problems are visible."""
    if not (TG_TOKEN and TG_CHAT):
        return False, "TELEGRAM_TOKEN or TELEGRAM_CHAT is missing. Put both in the .env file next to app.py (see .env.example), then restart the app."
    try:
        r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json={"chat_id": TG_CHAT, "text": msg[:4000]}, timeout=15)
        d = r.json()
        if d.get("ok"): return True, "Sent. Check your Telegram."
        desc = d.get("description", str(d))
        hint = ""
        if "Unauthorized" in desc or r.status_code == 401: hint = " The token is wrong. Copy the full token from BotFather again (the number, colon and letters)."
        elif "chat not found" in desc: hint = " The chat ID is wrong, or you have not sent Start to your bot yet. Open your bot in Telegram, press Start, and use the number from userinfobot."
        elif "bot was blocked" in desc: hint = " You blocked the bot. Unblock it in Telegram."
        print("Telegram error:", desc)
        return False, f"Telegram said: {desc}.{hint}"
    except Exception as e:
        print("Telegram error:", e)
        return False, f"Could not reach Telegram: {e}"



# Big candidate list of product companies (India-focused startups + global). Names are only GUESSES at ATS slugs;
# the "Discover companies" button tries each one on Greenhouse/Lever/Ashby/SmartRecruiters and keeps the ones that respond.
CANDIDATES = ("""
razorpay cred phonepe groww zerodha meesho swiggy zomato zepto dunzo blinkit slice jupiter fi navi paytm mobikwik freecharge
juspay cashfree pinelabs billdesk payu instamojo setu decentro signzy perfios open money opencash khatabook okcredit vyapar
dream11 mpl games24x7 nazara winzo sharechat moj josh dailyhunt inshorts pratilipi kuku pocketfm headout
unacademy physicswallah byjus vedantu upgrad scaler coding-ninjas masaischool simplilearn eruditus toppr doubtnut cuemath
cleartax zoho freshworks chargebee postman browserstack hasura druva sprinklr clevertap moengage webengage netcore
whatfix leadsquared yellowai gupshup exotel knowlarity ozonetel kaleyra servify uniphore observeai
ola olaelectric ather rapido uber lyft bluesmart zoomcar yulu vogo bounce
nykaa myntra flipkart lenskart purplle licious urbancompany urbanclap pepperfry bigbasket country-delight milkbasket
healthifyme cure-fit curefit pharmeasy tata1mg 1mg practo innovaccer qure-ai mfine medikabazaar
delhivery shadowfax xpressbees shiprocket porter loadshare blackbuck rivigo vamaship
ofbusiness udaan zetwerk infra-market moglix bizongo jumbotail agrim dehaat cropin
lendingkart indifi zestmoney kreditbee moneyview navi-technologies earlysalary slice-it uni-cards
upstox angelone smallcase kuvera scripbox wint-wealth indmoney
postman hackerearth hackerrank codechef geeksforgeeks interviewbit
atlan thoughtspot rudderstack mindsdb tensorlake gramener fractal tredence
sarvam krutrim gnani wadhwani
turing deel remote oysterhr rippling gusto papaya-global
stripe airbnb databricks cloudflare coinbase openai notion ramp figma snowflake datadog mongodb
anthropic vercel supabase linear retool airtable mercury brex plaid chime robinhood
atlassian canva github gitlab hashicorp elastic confluent twilio okta samsara
uber lyft doordash instacart pinterest reddit discord snap
sentry grafana grafanalabs posthog amplitude mixpanel segment launchdarkly pagerduty newrelic
algolia contentful sanity strapi prismic storyblok
rubrik nutanix cohesity pure-storage netskope zscaler crowdstrike sentinelone
wiz snyk 1password bitwarden tailscale
thoughtworks nagarro epam
""").split()


def probe(name):
    """Try a company name on each ATS. Returns list of (platform, slug) that return jobs or a valid empty board."""
    out = []
    for slug in {name.lower(), name.lower().replace("-", ""), name.lower().replace("-", "_")}:
        for p in ("greenhouse", "lever", "ashby", "smartrecruiters"):
            try:
                if probe_ok(p, slug): out.append((p, slug))
            except Exception: pass
    try: out += wd_probe(name)
    except Exception: pass
    return out


def probe_ok(p, s):
    """True only if the board really exists (not just an empty reply)."""
    urls = dict(greenhouse=f"https://boards-api.greenhouse.io/v1/boards/{s}", lever=f"https://api.lever.co/v0/postings/{s}?mode=json&limit=1",
                ashby=f"https://api.ashbyhq.com/posting-api/job-board/{s}", smartrecruiters=f"https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=1")
    try:
        r = requests.get(urls[p], timeout=10)
        if r.status_code != 200: return False
        d = r.json()
        if p == "lever": return isinstance(d, list) and len(d) > 0
        if p == "smartrecruiters": return d.get("totalFound", 0) > 0
        return bool(d)
    except Exception: return False


DISC = {"running": False, "done": 0, "total": 0, "found": 0}


def discover(names):
    DISC.update(running=True, done=0, total=len(names), found=0)
    known = {(r["platform"], r["slug"]) for r in q("SELECT * FROM co")} | {(p, s) for p, l in COMPANIES.items() for s in l}
    def one(n):
        try:
            for h in probe(n):
                if h not in known: q("INSERT OR IGNORE INTO co VALUES(?,?)", h); DISC["found"] += 1
        finally: DISC["done"] += 1
    try:
        with ThreadPoolExecutor(12) as ex: list(ex.map(one, names))
    finally: DISC["running"] = False


LOCK = threading.Lock()
STAT = {}


def fetch_all():
    P = kget("profile")
    if not P or not LOCK.acquire(blocking=False): return -1
    try:
        cos = {(p, s) for p, l in COMPANIES.items() for s in l} | {(r["platform"], r["slug"]) for r in q("SELECT * FROM co")}
        if P.get("world", True): cos |= {("remotive", "all"), ("remoteok", "all")}
        cos = sorted(c for c in cos if c[1].lower() not in SERVICE)
        with ThreadPoolExecutor(16) as ex: res = list(ex.map(fetch_co, cos))
        kset("cos", {(p if s == "all" else s.split("|")[0]): len(r) for (p, s), r in zip(cos, res)})
        raw = [j for r in res for j in r]; WHY.clear()
        new = []
        STAT["raw"] = len(raw)
        for j in [j for j in (evaluate(j, P) for j in raw) if j]:
            if not q("SELECT 1 FROM jobs WHERE id=?", (j["id"],), True):
                q("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,'new',?)", (j["id"], j["company"], j["title"], j["location"], j["url"], j["score"], j["salary"], j["hits"], j.get("posted") or time.time()))
                q("INSERT OR REPLACE INTO jd VALUES(?,?)", (j["id"], j["jd"])); new.append(j)
        kset("last", time.time()); kset("why", dict(WHY, _raw=len(raw), _kept=len([1 for _ in new])))
        new.sort(key=lambda j: -j["score"])
        if new: tg(f"{len(new)} new jobs\n" + "\n".join(f"{j['company']} - {j['title']} ({j['location']})\n{j['url']}" for j in new[:10]))
        return len(new)
    finally: LOCK.release()


def scheduler():
    while True:
        time.sleep(60)
        n = datetime.datetime.now(); last = kget("last", 0)
        if kget("profile") and (time.time() - last > 86400 or (n.hour == DAILY_HOUR and time.time() - last > 3600 * 6)): fetch_all()


PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>JobAgent</title>
<style>
:root{--ink:#3d3752;--mute:#8d87a3;--line:#ece8f5;--lav:#e8e2fb;--mint:#d9f3e6;--peach:#ffe6d9;--sky:#dcefff;--rose:#fde0e9;--acc:#8b7cf6}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:var(--ink);background:linear-gradient(135deg,#f6f3fb,#eef6fb 50%,#fdf1f4) fixed;min-height:100vh}
.w{max-width:1000px;margin:auto;padding:24px 16px 80px}
.top{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:18px}
h1{margin:0;font-size:28px;background:linear-gradient(90deg,#8b7cf6,#f08fb0);-webkit-background-clip:text;background-clip:text;color:transparent}
.sub{color:var(--mute);font-size:13px}
.btn{border:0;border-radius:12px;padding:9px 16px;font:inherit;font-weight:600;cursor:pointer;transition:.15s}
.btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px #8b7cf633}
.p{background:var(--acc);color:#fff}.m{background:var(--mint);color:#256b4a}.r{background:var(--rose);color:#a23b5d}.l{background:var(--lav);color:#5a4bc4}.s{background:var(--sky);color:#2b6a9c}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px}
.st{border-radius:18px;padding:14px 16px}.st b{display:block;font-size:26px}.st span{font-size:12px;color:#5d5775}
.card{background:#ffffffcc;border:1px solid var(--line);border-radius:18px;padding:14px 16px;margin-bottom:14px;box-shadow:0 2px 10px #8b7cf614;backdrop-filter:blur(6px)}
summary{cursor:pointer;font-weight:600}
.fg{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:12px}
.fg .wide{grid-column:1/-1}
label.f{display:block;font-size:12px;color:var(--mute)}
input[type=text],input:not([type]),textarea,input[type=file]{width:100%;font:inherit;padding:8px 12px;border:1px solid var(--line);border-radius:12px;background:#fff;color:var(--ink)}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
.pill-f{border:0;border-radius:999px;padding:7px 14px;background:#fff;color:var(--ink);cursor:pointer;font:inherit;border:1px solid var(--line)}
.pill-f.on{background:var(--lav);border-color:#cfc5f7;font-weight:600}.pill-f b{color:var(--acc)}
#f{flex:1;min-width:140px;max-width:260px;border-radius:999px}
.job{display:grid;grid-template-columns:48px 1fr auto;gap:14px;align-items:center;background:#fff;border:1px solid var(--line);border-radius:18px;padding:14px 16px;margin-bottom:10px;box-shadow:0 2px 10px #8b7cf614;transition:.15s}
.job:hover{box-shadow:0 6px 18px #8b7cf626}
.job.applied,.job.skip{opacity:.5}
.av{width:48px;height:48px;border-radius:50%;display:grid;place-items:center;font-weight:700;font-size:18px}
.ti{font-weight:650;font-size:15px;color:var(--ink);text-decoration:none}.ti:hover{color:var(--acc)}
.meta{color:var(--mute);font-size:12.5px;margin-top:2px}
.chips{margin-top:7px;display:flex;flex-wrap:wrap;gap:5px}
.chip{background:var(--sky);color:#2b6a9c;border-radius:999px;padding:2px 10px;font-size:11.5px}
.chip:nth-child(3n+2){background:var(--peach);color:#a65a2c}.chip:nth-child(3n){background:var(--mint);color:#256b4a}
.badge{display:inline-block;border-radius:999px;padding:1px 9px;font-size:12px;font-weight:700;margin-right:6px}
.hi{background:var(--mint);color:#256b4a}.md{background:var(--lav);color:#5a4bc4}.lo{background:var(--peach);color:#a65a2c}
.pill{font-size:11.5px;border-radius:999px;padding:1px 9px;background:var(--lav);color:#5a4bc4;margin-left:6px}
.acts{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
#empty{text-align:center;color:var(--mute);padding:40px;display:none}
#cf{position:fixed;inset:0;background:#3d375255;display:none;place-items:center;z-index:9;padding:16px}
#cf .box{background:#fff;border-radius:22px;padding:22px;max-width:520px;width:100%;max-height:80vh;overflow:auto}
.ck{display:flex;gap:10px;padding:8px 10px;border-radius:12px;background:#faf8ff;margin:6px 0;cursor:pointer}
@media(max-width:640px){.stats{grid-template-columns:repeat(2,1fr)}.job{grid-template-columns:40px 1fr}.acts{grid-column:1/-1;justify-content:flex-start}.av{width:40px;height:40px}}
.skbox{display:flex;flex-wrap:wrap;gap:6px;padding:8px;border:1px solid var(--line);border-radius:12px;background:#fff}
.sk{background:var(--lav);color:#5a4bc4;border-radius:999px;padding:3px 10px;font-size:12.5px}.sk b{cursor:pointer;margin-left:4px;color:#a23b5d}
.skbox input{border:0!important;outline:0;flex:1;min-width:110px;padding:3px 6px!important}
#tm{position:fixed;inset:0;background:#3d375255;display:none;place-items:center;z-index:9;padding:16px}
#tm .box{background:#fff;border-radius:22px;padding:22px;max-width:640px;width:100%;max-height:85vh;overflow:auto}
#toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#fff;border:1px solid var(--line);border-radius:18px;padding:12px 16px;box-shadow:0 10px 30px #8b7cf644;display:none;gap:10px;align-items:center;flex-wrap:wrap;z-index:9;max-width:94vw}
</style><div class=w>
<div class=top><div><h1>JobAgent</h1><div class=sub>Last fetch: {{last}} · fresh jobs matched to your resume</div></div>
<div class=acts><button class="btn s" onclick="discoverCos(this)">Discover companies</button><button class="btn l" onclick="tgTest(this)">Test Telegram</button><button class="btn p" onclick="fetchNow(this)">Fetch new jobs</button></div></div>
<div class=stats><div class=st style="background:var(--mint)"><b id=s1>0</b><span>To apply</span></div>
<div class=st style="background:var(--lav)"><b id=s3>0</b><span>Applied</span></div>
<div class=st style="background:var(--peach)"><b id=s4>0</b><span>Skipped</span></div></div>
{% if why %}<div class=card><b>Last fetch:</b> looked at {{why.get('_raw',0)}} job postings, kept {{why.get('_kept',0)}} new matches. <span class=sub>Removed because:</span>
<div class=chips>{% for k,v in why.items() if not k.startswith('_') %}<span class=chip>{{k}}: {{v}}</span>{% endfor %}</div></div>{% endif %}
<div id=sv class=card style="display:none;background:var(--mint)">Profile saved. Refreshing jobs with your new settings; this page reloads automatically in 45 seconds.</div>
<details class=card {% if not P.skills %}open{% endif %}><summary>Your profile &amp; settings</summary>
<form method=post action=/profile enctype=multipart/form-data><div class=fg>
<div class=wide><label class=f>Upload resume (PDF / DOCX / TXT): skills and experience are auto-detected</label><input type=file name=resume accept=".pdf,.docx,.txt"></div>
<div class=wide><label class=f>Your skills, read from your resume. Click × to remove; type a skill and press Enter to add.</label><div id=sk class=skbox></div><input type=hidden name=skills id=skv></div>
<div><label class=f>Experience (years)</label><input name=years value="{{P.years}}"></div>
<div><label class=f>Min salary (LPA)</label><input name=min_lpa value="{{P.min_lpa}}"></div>
<div><label class=f>Max job age (days)</label><input name=max_days value="{{P.max_days or 7}}"></div>
<div class=wide><label class=f>Minimum match: <b id=mpv>{{(P.min_pct or 40)|int}}</b>% of the skills a job asks for must be in your resume</label><input type=range name=min_pct min=30 max=100 step=5 value="{{P.min_pct or 40}}" oninput="mpv.textContent=this.value" style="padding:0"></div>
<div class=wide><label class=f><input type=checkbox name=world value=1 {% if P.world is not defined or P.world %}checked{% endif %} style="width:auto"> Also include remote jobs from around the world (Remotive, RemoteOK)</label></div>
<div class=wide><label class=f>Locations</label><input name=locs value="{{P.locs|join(', ')}}"></div>
<div><button class="btn p">Save profile</button></div></div></form>
<form method=post action=/company style="display:flex;gap:8px;margin-top:14px"><input name=url placeholder="Add product companies: type a name (e.g. razorpay) or paste careers page URLs"><button class="btn m">Add</button></form>
{% if am and am.added %}<div class=meta style="margin-top:10px;color:#256b4a">Added: {{am.added|join(', ')}}. Click Fetch new jobs to load its openings.</div>{% endif %}
{% if am and am.bad %}<div class=meta style="margin-top:10px;color:#a23b5d">Could not find a supported job board for: {{am.bad|join(', ')}}. That company probably uses its own career site, which this app cannot read. Try pasting the page where individual jobs are listed.</div>{% endif %}
<div class=meta style="margin-top:12px">{{ok}} of {{cos|length}} tracked companies are returning jobs.</div>
<details style="margin-top:6px"><summary class=meta>Show company list</summary><div class=meta style="margin-top:6px">{% for c,n in cos %}{{c}} ({{n}}){{ ', ' if not loop.last }}{% endfor %}</div></details>
</details>
<div class=bar>
<button class=pill-f data-f=todo onclick="pick(this)">To apply <b>0</b></button>
<button class=pill-f data-f=applied onclick="pick(this)">Applied <b>0</b></button><button class=pill-f data-f=skip onclick="pick(this)">Not interested <b>0</b></button>
<input id=f placeholder="Search company, role, skill..." oninput="ref()"></div>
<div id=list>{% for r in rows %}{% set d=((now - r.seen)/86400)|int %}
<div class="job {{r.status}}" data-id="{{r.id}}" data-u="{{r.url}}" data-s="{{r.status}}" data-co="{{r.company}}" data-t="{{r.title}}">
<div class=av data-n="{{r.company}}">{{r.company[:1]|upper}}</div>
<div><a class=ti href="{{r.url}}" onclick="ap(this);return false">{{r.title}}</a>
<div class=meta><span class="badge {{'hi' if r.score>=80 else ('md' if r.score>=65 else 'lo')}}">{{r.score|int}}% match</span>{{ '⭐ ' if r.company in tier else '' }}{{r.company}} · {{r.location}} · {{r.salary}} · {{'today' if d==0 else d~'d ago'}}</div>
{% if r.hits %}<div class=chips>{% for h in r.hits.split(', ') %}<span class=chip>{{h}}</span>{% endfor %}</div>{% endif %}</div>
<div class=acts><button class="btn p" onclick="ap(this)">Apply ↗</button><button class="btn s" onclick="tailor(this)">Tailor resume</button><button class="btn m" onclick="set(this.closest('.job'),'applied')">I applied ✓</button><button class="btn r" onclick="set(this.closest('.job'),'skip')">Not interested</button></div></div>{% endfor %}</div>
<div id=empty>Nothing here yet. Save your profile, then click <b>Fetch jobs</b>.</div></div>
<div id=tm><div class=box><h3 style="margin-top:0" id=tmt>Tailored resume</h3><div id=tmn class=sub></div>
<div class=meta style="margin-top:8px">Already in your resume</div><div class=chips id=tmh></div>
<div class=meta style="margin-top:8px">Job asks for these, but they are not in your resume (add only if you truly have them)</div><div class=chips id=tmm></div>
<textarea id=tmx rows=14 style="margin-top:10px;display:none"></textarea>
<div class=acts style="margin-top:12px"><button class="btn l" onclick="tm.style.display='none'">Close</button><button class="btn m" id=tmc style="display:none" onclick="navigator.clipboard.writeText(tmx.value)">Copy</button><button class="btn p" id=tmd style="display:none" onclick="dl()">Download .txt</button></div></div></div>
<div id=toast><span>Did you apply to <b id=tt></b>?</span><button class="btn m" onclick="ans('applied')">Yes, applied</button><button class="btn l" onclick="ans(null)">Not yet</button><button class="btn r" onclick="ans('skip')">Not interested</button></div>
<script>
let SK={{P.skills|tojson}},F='todo',cur=null;const $=s=>document.querySelector(s),A=s=>[...document.querySelectorAll(s)];
const post=(id,s)=>fetch('/mark',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,s})});
function set(j,s){j.dataset.s=s;j.className='job '+s;post(j.dataset.id,s);ref()}
function ap(el){cur=el.closest('.job');window.open(cur.dataset.u,'_blank')}
function pick(b){F=b.dataset.f;A('[data-f]').forEach(x=>x.classList.toggle('on',x==b));ref()}
function ref(){const q=$('#f').value.toLowerCase(),n={todo:0,applied:0,skip:0};let any=false;
A('.job').forEach(e=>{const k=e.dataset.s=='new'?'todo':e.dataset.s;n[k]=(n[k]||0)+1;const ok=k==F&&e.textContent.toLowerCase().includes(q);e.style.display=ok?'':'none';if(ok)any=true});
A('[data-f]').forEach(b=>b.querySelector('b').textContent=n[b.dataset.f]||0);
$('#s1').textContent=n.todo;$('#s3').textContent=n.applied;$('#s4').textContent=n.skip;$('#empty').style.display=any?'none':'block'}
function back(){if(!document.hidden&&cur&&cur.dataset.s=='new'){$('#tt').textContent=cur.dataset.t+' at '+cur.dataset.co;$('#toast').style.display='flex'}}
function ans(s){$('#toast').style.display='none';if(s&&cur)set(cur,s);cur=null}
document.addEventListener('visibilitychange',back);window.addEventListener('focus',back);
async function discoverCos(b){if(!confirm('This checks about 250 company names on Greenhouse, Lever, Ashby and SmartRecruiters and adds the ones that have job boards. Takes a few minutes. Start?'))return;
const r=await (await fetch('/discover',{method:'POST'})).json();alert(r.msg);if(!r.ok)return;
const t=setInterval(async()=>{const d=await (await fetch('/discover_status')).json();b.textContent=d.running?`Checking ${d.done}/${d.total} (found ${d.found})`:'Discover companies';
if(!d.running){clearInterval(t);alert('Done. Found '+d.found+' new companies. Now tracking '+d.tracked+'. Click Fetch new jobs.')}},3000)}
async function tgTest(b){b.textContent='Sending...';const r=await (await fetch('/tgtest',{method:'POST'})).json();b.textContent='Test Telegram';alert((r.ok?'OK: ':'PROBLEM: ')+r.msg)}
async function fetchNow(b){b.textContent='Fetching... (30-60s)';const r=await (await fetch('/fetch',{method:'POST'})).json();
alert(r.noprofile?'Save your profile first (upload resume, then Save).':r.n+' new jobs (checked '+r.raw+' postings)');location.reload()}
A('.av').forEach(a=>{let h=0;for(const c of a.dataset.n)h=(h*31+c.charCodeAt(0))%360;a.style.background='hsl('+h+',70%,90%)';a.style.color='hsl('+h+',40%,35%)'});
function drawSK(){const b=$('#sk');b.innerHTML='';SK.forEach((s,i)=>{const c=document.createElement('span');c.className='sk';c.textContent=s+' ';const x=document.createElement('b');x.textContent='×';x.onclick=()=>{SK.splice(i,1);drawSK()};c.appendChild(x);b.appendChild(c)});
const n=document.createElement('input');n.placeholder='+ add skill';n.onkeydown=e=>{if(e.key=='Enter'||e.key==','){e.preventDefault();const v=n.value.trim().toLowerCase();if(v&&!SK.includes(v)){SK.push(v);drawSK();$('#sk input').focus()}}};b.appendChild(n);$('#skv').value=SK.join(', ')}
async function tailor(b){const j=b.closest('.job');tm.style.display='grid';tmt.textContent='Tailoring for '+j.dataset.t+' at '+j.dataset.co;tmn.textContent='Working... (AI takes about 20s)';tmh.innerHTML=tmm.innerHTML='';tmx.style.display=tmc.style.display=tmd.style.display='none';
const r=await (await fetch('/tailor?id='+encodeURIComponent(j.dataset.id))).json();tmn.textContent=r.note||r.error||'';
const chips=(el,l,c)=>l.forEach(s=>{const e=document.createElement('span');e.className='chip';e.style.background=c;e.style.color='#3d3752';e.textContent=s;el.appendChild(e)});chips(tmh,r.matched||[],'var(--mint)');chips(tmm,r.missing||[],'var(--rose)');
if(r.text){tmx.value=r.text;tmx.style.display=tmc.style.display=tmd.style.display=''}else if(r.prompt){tmx.value=r.prompt;tmx.style.display=tmc.style.display='';tmc.textContent='Copy prompt'}}
function dl(){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([tmx.value],{type:'text/plain'}));a.download='tailored_resume.txt';a.click()}
drawSK();if(location.search.includes('saved=1')){$('#sv').style.display='block';setTimeout(()=>location.href='/',45000)}
pick($('[data-f=todo]'));
</script>
"""


@app.route("/")
def index():
    P = kget("profile", dict(skills=[], years=0, min_lpa=10, locs=LOCS, max_days=7)); l = kget("last"); cos = sorted(kget("cos", {}).items(), key=lambda x: -x[1]); why = kget("why", {}); am = kget("addmsg", {}) if request.args.get("added") else {}
    return render_template_string(PAGE, P=P, now=time.time(), am=am, why=why, tier=TIER1, cos=cos, ok=sum(1 for _, n in cos if n), rows=q("SELECT * FROM jobs ORDER BY score DESC, seen DESC LIMIT 600"),
                                  last=datetime.datetime.fromtimestamp(l).strftime("%d %b %H:%M") if l else "never")


@app.route("/profile", methods=["POST"])
def profile():
    f, F = request.files.get("resume"), request.form
    sk, yrs = [x.strip().lower() for x in F["skills"].split(",") if x.strip()], float(F.get("years") or 0)
    if f and f.filename:
        txt = resume_text(f); kset("resume_text", txt[:20000]); sk, yrs = parse_resume(txt)
    kset("profile", dict(skills=sk, years=yrs, min_pct=float(F.get("min_pct") or 40), min_lpa=float(F.get("min_lpa") or 10),
                         max_days=float(F.get("max_days") or 7), world=bool(F.get("world")),
                         locs=[x.strip().lower() for x in F["locs"].split(",") if x.strip()] or LOCS))
    q("DELETE FROM jobs WHERE status='new'"); q("DELETE FROM jd WHERE id NOT IN (SELECT id FROM jobs)")  # new settings apply to everything
    threading.Thread(target=fetch_all, daemon=True).start()
    return redirect("/?saved=1")


@app.route("/tailor")
def tailor():
    jid, P, rt = request.args["id"], kget("profile"), kget("resume_text", "")
    j, jd = q("SELECT * FROM jobs WHERE id=?", (jid,), True), q("SELECT t FROM jd WHERE id=?", (jid,), True)
    if not (j and P): return jsonify(error="Job or profile missing")
    jdt = jd["t"] if jd else ""
    blob = (j["title"] + " " + jdt).lower()
    need = [x for x in sorted(set(ALLSK) | set(P["skills"])) if has(blob, x)]
    out = dict(matched=[x for x in need if x in P["skills"]], missing=[x for x in need if x not in P["skills"]], text="", note="")
    prompt = ("You are an expert ATS resume editor. Rewrite the RESUME below, tailored to the JOB. Rules: use ONLY facts already in the resume; "
              "never invent skills, tools, employers, dates or metrics; reorder and rephrase bullets to put the most relevant experience first; "
              "use the job's exact terminology only where it truthfully describes what the candidate did; output plain single-column text with "
              "standard headings (Summary, Skills, Experience, Projects, Education) so ATS parsers read it; put the most relevant skills first. "
              "At the very end add a section 'NOT IN RESUME (add only if true):' listing job keywords the candidate lacks.\n\n"
              f"JOB: {j['title']} at {j['company']}\n{jdt[:5000]}\n\nRESUME:\n{rt[:12000]}")
    key = os.getenv("ANTHROPIC_API_KEY")
    if not rt: out["note"] = "Upload your resume once (Save profile) so it can be tailored."
    elif not key: out["note"] = "No API key, so no automatic rewrite. Click Copy prompt, then paste it into any free chatbot (ChatGPT, Gemini or Claude) to get your tailored resume."; out["prompt"] = prompt
    else:
        try:
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=120,
                              headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                              json={"model": os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"), "max_tokens": 3000, "messages": [{"role": "user", "content": prompt}]})
            d = r.json(); out["text"] = "".join(b.get("text", "") for b in d.get("content", []))
            if not out["text"]: out["note"] = "AI error: " + str(d.get("error", d))[:200]
        except Exception as e: out["note"] = f"AI call failed: {e}"
    return jsonify(out)


ATS = dict(greenhouse=r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)", lever=r"jobs\.lever\.co/([\w-]+)",
           ashby=r"jobs\.ashbyhq\.com/([\w%.-]+)", smartrecruiters=r"smartrecruiters\.com/([\w-]+)")


@app.route("/company", methods=["POST"])
def company():
    added, bad = [], []
    for tok in request.form["url"].replace(",", " ").split():
        hit = []
        if tok.startswith("http") or "." in tok:
            url = tok if tok.startswith("http") else "https://" + tok
            for src in (url,):
                try: page = requests.get(src, timeout=15, headers={"User-Agent": "Mozilla/5.0"}).text
                except Exception: page = ""
                mw = re.search(r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)", src + " " + page)
                if mw and mw.group(3) != "wday" and wd_ok(f"{mw.group(1)}|{mw.group(2)}|{mw.group(3)}"): hit.append(("workday", f"{mw.group(1)}|{mw.group(2)}|{mw.group(3)}"))
                for p, r in ATS.items():
                    m = re.search(r, src + " " + page)
                    if m: hit.append((p, m.group(1)))
        else: hit = [(p, tok.lower()) for p in ("greenhouse", "lever", "ashby") if fetch_co((p, tok.lower()))]
        if hit:
            for h in hit[:1]: q("INSERT OR IGNORE INTO co VALUES(?,?)", h); added.append(f"{tok} via {h[0]}")
        else: bad.append(tok)
    kset("addmsg", dict(added=added, bad=bad))
    return redirect("/?added=1")



@app.route("/discover", methods=["POST"])
def discover_route():
    if DISC["running"]: return jsonify(ok=0, msg="Discovery is already running.")
    extra = [t.strip().lower() for t in request.form.get("names", "").replace(",", " ").split() if t.strip()]
    names = sorted(set(CANDIDATES) | set(extra))
    threading.Thread(target=discover, args=(names,), daemon=True).start()
    return jsonify(ok=1, msg=f"Checking {len(names)} company names in the background.")


@app.route("/discover_status")
def discover_status(): return jsonify(dict(DISC, tracked=len(q("SELECT 1 FROM co")) + sum(len(v) for v in COMPANIES.values())))


@app.route("/mark", methods=["POST"])
def mark(): d = request.json; q("UPDATE jobs SET status=? WHERE id=?", (d["s"], d["id"])); return jsonify(ok=1)


@app.route("/tgtest", methods=["POST"])
def tgtest():
    ok, msg = tg("JobAgent test: Telegram alerts are working.")
    return jsonify(ok=ok, msg=msg)


@app.route("/fetch", methods=["POST"])
def fetch():
    if not kget("profile"): return jsonify(n=0, raw=0, noprofile=True)
    n = fetch_all(); return jsonify(n=max(n, 0), raw=STAT.get("raw", 0), noprofile=False)


if __name__ == "__main__":
    if not kget("mig2"):  # one-time reset so the stricter filters apply and old 'opened' marks disappear
        q("DELETE FROM jobs WHERE status IN ('new','opened')"); kset("last", 0); kset("mig2", 1)
    if not kget("mig3"):
        q("DELETE FROM jobs WHERE status IN ('new','opened')"); kset("last", 0); kset("mig3", 1)
    threading.Thread(target=scheduler, daemon=True).start()
    print("Open http://localhost:5001"); app.run(port=5001)