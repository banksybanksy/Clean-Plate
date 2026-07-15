#!/usr/bin/env python3
"""
SF Restaurant Health Score Lookup: local server.

Zero-dependency (Python standard library only). Serves the frontend from
./static, caches DataSF health-inspection data in ./data/inspections.db,
and exposes a small JSON API.

Data source: DataSF "Health Inspection Scores (2024-Present)"
https://data.sfgov.org/d/tvy3-wexg  (SODA resource: tvy3-wexg)

Run:  python3 app.py          then open http://localhost:8000
"""

import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "inspections.db")

DATASET_ID = "tvy3-wexg"
DATASET_NAME = "Health Inspection Scores (2024-Present)"
DATASET_PAGE = f"https://data.sfgov.org/d/{DATASET_ID}"
SODA_URL = f"https://data.sfgov.org/resource/{DATASET_ID}.json"
PAGE_SIZE = 5000
FETCH_FIELDS = [
    "inspection_date", "permit_number", "dba", "permit_type",
    "street_address", "inspection_type", "facility_rating_status",
    "violation_count", "violation_codes", "inspection_notes",
    "suspension_notes", "analysis_neighborhood", "supervisor_district",
    "latitude", "longitude", "data_as_of",
]

PORT = int(os.environ.get("PORT", "8000"))
APP_TOKEN = os.environ.get("DATASF_APP_TOKEN", "")  # optional, raises rate limits

# ---------------------------------------------------------------------------
# Database

SCHEMA = """
CREATE TABLE IF NOT EXISTS inspections (
    id INTEGER PRIMARY KEY,
    permit_number TEXT,
    dba TEXT,
    permit_type TEXT,
    street_address TEXT,
    analysis_neighborhood TEXT,
    supervisor_district TEXT,
    inspection_date TEXT,
    inspection_type TEXT,
    facility_rating_status TEXT,
    violation_count INTEGER,
    violation_codes TEXT,
    inspection_notes TEXT,
    suspension_notes TEXT,
    latitude REAL,
    longitude REAL,
    data_as_of TEXT
);
CREATE INDEX IF NOT EXISTS idx_permit ON inspections(permit_number);
CREATE INDEX IF NOT EXISTS idx_dba ON inspections(dba);
CREATE INDEX IF NOT EXISTS idx_hood ON inspections(analysis_neighborhood);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


def get_meta(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


# One shared CTE that rolls inspection rows up to one row per restaurant
# (permit). Identity fields come from the most recent inspection; the current
# status comes from the most recent inspection that actually carries a
# facility rating (some inspection types are never rated).
RESTAURANTS_CTE = """
WITH info AS (
    SELECT permit_number, dba, permit_type, street_address,
           analysis_neighborhood, supervisor_district,
           inspection_date AS latest_date, inspection_type AS latest_type
    FROM (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY permit_number
            ORDER BY inspection_date DESC, id DESC) AS rn
        FROM inspections
    ) WHERE rn = 1
),
counts AS (
    SELECT permit_number, COUNT(*) AS inspection_count
    FROM inspections GROUP BY permit_number
),
rated AS (
    SELECT permit_number,
           facility_rating_status AS status,
           inspection_date AS status_date,
           inspection_type AS status_type,
           COALESCE(violation_count, 0) AS status_violations
    FROM (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY permit_number
            ORDER BY inspection_date DESC, id DESC) AS rn
        FROM inspections
        WHERE facility_rating_status IS NOT NULL
    ) WHERE rn = 1
),
restaurants AS (
    SELECT info.*, counts.inspection_count,
           rated.status, rated.status_date, rated.status_type,
           rated.status_violations
    FROM info
    JOIN counts USING (permit_number)
    LEFT JOIN rated USING (permit_number)
)
"""

# ---------------------------------------------------------------------------
# Refresh (pull from DataSF into SQLite)

refresh_lock = threading.Lock()
refresh_state = {"running": False, "progress": "", "error": None}


def soda_get(params):
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{SODA_URL}?{qs}",
        headers={"User-Agent": "sf-healthscore-local/1.0"},
    )
    if APP_TOKEN:
        req.add_header("X-App-Token", APP_TOKEN)
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"DataSF request failed after 3 attempts: {last_err}")


def do_refresh():
    """Fetch the full dataset and replace the local cache atomically."""
    refresh_state.update(running=True, progress="starting", error=None)
    try:
        rows, offset = [], 0
        while True:
            refresh_state["progress"] = f"fetched {len(rows):,} rows..."
            page = soda_get({
                "$select": ",".join(FETCH_FIELDS),
                "$order": ":id",
                "$limit": PAGE_SIZE,
                "$offset": offset,
            })
            rows.extend(page)
            if len(page) < PAGE_SIZE:
                break
            offset += PAGE_SIZE

        refresh_state["progress"] = f"writing {len(rows):,} rows to cache..."
        conn = connect()
        try:
            with conn:  # single transaction: readers see old data until commit
                conn.execute("DELETE FROM inspections")
                conn.executemany(
                    """INSERT INTO inspections
                       (permit_number, dba, permit_type, street_address,
                        analysis_neighborhood, supervisor_district,
                        inspection_date, inspection_type,
                        facility_rating_status, violation_count,
                        violation_codes, inspection_notes, suspension_notes,
                        latitude, longitude, data_as_of)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [(
                        r.get("permit_number"), r.get("dba"),
                        r.get("permit_type"), r.get("street_address"),
                        r.get("analysis_neighborhood"),
                        r.get("supervisor_district"),
                        r.get("inspection_date"), r.get("inspection_type"),
                        r.get("facility_rating_status"),
                        int(float(r["violation_count"]))
                        if r.get("violation_count") else None,
                        r.get("violation_codes"), r.get("inspection_notes"),
                        r.get("suspension_notes"),
                        float(r["latitude"]) if r.get("latitude") else None,
                        float(r["longitude"]) if r.get("longitude") else None,
                        r.get("data_as_of"),
                    ) for r in rows],
                )
                set_meta(conn, "last_refresh",
                         datetime.now(timezone.utc).isoformat())
                set_meta(conn, "row_count", str(len(rows)))
        finally:
            conn.close()
        refresh_state["progress"] = "done"
        print(f"[refresh] cached {len(rows):,} inspection records")
    except Exception as e:  # surface any failure to the UI
        refresh_state["error"] = str(e)
        print(f"[refresh] ERROR: {e}", file=sys.stderr)
    finally:
        refresh_state["running"] = False


def start_refresh():
    if refresh_lock.acquire(blocking=False):
        try:
            t = threading.Thread(target=lambda: (do_refresh(),
                                                 refresh_lock.release()),
                                 daemon=True)
            refresh_state["running"] = True
            t.start()
            return True
        except Exception:
            refresh_lock.release()
            raise
    return False  # already running


# ---------------------------------------------------------------------------
# Violation parsing
#
# The dataset stores each inspection's violations as one text blob:
#   "<codes> - <description>., <codes> - <description>., ..."
# where <codes> is a comma-separated list of CA Health & Safety Code
# sections. Entries are separated by a sentence-ending period followed by
# ", " (periods inside code numbers, e.g. 113953.3, are followed by a
# digit, so we only split where the period follows a letter/paren).

VIOL_SPLIT = re.compile(r"(?<=[A-Za-z)\]])\.\s*,\s+")
CODE_LIKE = re.compile(r"\b\d{5,6}\b")


def parse_violations(text):
    if not text:
        return []
    items = []
    for part in VIOL_SPLIT.split(text):
        part = part.strip().strip(",").strip()
        if not part:
            continue
        codes, desc = "", part
        if part.startswith("- "):
            desc = part[2:].strip()
        else:
            head, sep, tail = part.partition(" - ")
            if sep and CODE_LIKE.search(head) and len(head) <= 250:
                codes, desc = head.strip(), tail.strip()
        is_closure = bool(re.search(
            r"PERMIT SUSPENSION|CLOSURE", desc[:120], re.IGNORECASE))
        items.append({
            "codes": [c.strip() for c in codes.split(",") if c.strip()],
            "description": desc,
            "closure_notice": is_closure,
        })
    return items


# ---------------------------------------------------------------------------
# API handlers

def esc_like(term):
    return term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def api_status(conn, _params):
    total = conn.execute("SELECT COUNT(*) c FROM inspections").fetchone()["c"]
    restaurants = conn.execute(
        "SELECT COUNT(DISTINCT permit_number) c FROM inspections"
    ).fetchone()["c"]
    # a handful of source rows are future-dated typos; skip them for the stat
    newest = conn.execute(
        "SELECT MAX(inspection_date) d FROM inspections "
        "WHERE inspection_date <= datetime('now', '+1 day')").fetchone()["d"]
    return {
        "dataset_id": DATASET_ID,
        "dataset_name": DATASET_NAME,
        "dataset_page": DATASET_PAGE,
        "rows": total,
        "restaurants": restaurants,
        "newest_inspection": newest,
        "last_refresh": get_meta(conn, "last_refresh"),
        "refreshing": refresh_state["running"],
        "refresh_progress": refresh_state["progress"],
        "refresh_error": refresh_state["error"],
    }


def api_search(conn, params):
    q = (params.get("q") or "").strip()
    if len(q) < 2:
        return {"query": q, "results": []}
    tokens = q.split()[:6]
    where, args = [], []
    for t in tokens:
        where.append(
            "(dba LIKE ? ESCAPE '\\' OR street_address LIKE ? ESCAPE '\\' "
            "OR analysis_neighborhood LIKE ? ESCAPE '\\')")
        args.extend([f"%{esc_like(t)}%"] * 3)
    sql = (RESTAURANTS_CTE +
           f"SELECT * FROM restaurants WHERE {' AND '.join(where)} LIMIT 400")
    rows = [dict(r) for r in conn.execute(sql, args)]

    ql = q.lower()

    def rank(r):
        name = (r["dba"] or "").lower()
        if name.startswith(ql):
            return (0, name)
        if re.search(r"\b" + re.escape(ql), name):
            return (1, name)
        if ql in name:
            return (2, name)
        return (3, name)

    rows.sort(key=rank)
    return {"query": q, "results": rows[:25]}


def api_restaurant(conn, params):
    permit = (params.get("permit") or "").strip()
    if not permit:
        return {"error": "missing permit"}, 400
    rows = conn.execute(
        "SELECT * FROM inspections WHERE permit_number=? "
        "ORDER BY inspection_date DESC, id DESC", (permit,)).fetchall()
    if not rows:
        return {"error": "not found"}, 404
    summary = conn.execute(
        RESTAURANTS_CTE + "SELECT * FROM restaurants WHERE permit_number=?",
        (permit,)).fetchone()
    inspections = []
    for r in rows:
        d = dict(r)
        d["violations"] = parse_violations(d.pop("violation_codes"))
        inspections.append(d)
    return {"restaurant": dict(summary), "inspections": inspections}


def api_neighborhoods(conn, _params):
    sql = RESTAURANTS_CTE + """
        SELECT COALESCE(analysis_neighborhood, '(Unknown)') AS neighborhood,
               COUNT(*) AS restaurants,
               SUM(status = 'Pass') AS pass,
               SUM(status = 'Conditional Pass') AS conditional,
               SUM(status = 'Closure') AS closure,
               SUM(status IS NULL) AS unrated
        FROM restaurants
        GROUP BY neighborhood
        ORDER BY restaurants DESC
    """
    return {"neighborhoods": [dict(r) for r in conn.execute(sql)]}


BROWSE_SORTS = {
    "name": "dba COLLATE NOCASE",
    "neighborhood": "analysis_neighborhood COLLATE NOCASE",
    "date": "latest_date",
    "status": ("CASE status WHEN 'Closure' THEN 0 "
               "WHEN 'Conditional Pass' THEN 1 WHEN 'Pass' THEN 2 "
               "ELSE 3 END"),
    "violations": "status_violations",
}


def api_browse(conn, params):
    where, args = [], []
    hood = (params.get("neighborhood") or "").strip()
    if hood:
        if hood == "(Unknown)":
            where.append("analysis_neighborhood IS NULL")
        else:
            where.append("analysis_neighborhood = ?")
            args.append(hood)
    status = (params.get("status") or "").strip()
    if status:
        if status == "none":
            where.append("status IS NULL")
        else:
            where.append("status = ?")
            args.append(status)
    sort = BROWSE_SORTS.get(params.get("sort", "name"), BROWSE_SORTS["name"])
    direction = "DESC" if params.get("dir") == "desc" else "ASC"
    limit = min(int(params.get("limit", "200") or 200), 500)
    offset = max(int(params.get("offset", "0") or 0), 0)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(
        RESTAURANTS_CTE + f"SELECT COUNT(*) c FROM restaurants {where_sql}",
        args).fetchone()["c"]
    rows = conn.execute(
        RESTAURANTS_CTE +
        f"SELECT * FROM restaurants {where_sql} "
        f"ORDER BY {sort} {direction}, dba COLLATE NOCASE ASC "
        f"LIMIT {limit} OFFSET {offset}",
        args).fetchall()
    return {"total": total, "offset": offset,
            "results": [dict(r) for r in rows]}


ROUTES = {
    "/api/status": api_status,
    "/api/search": api_search,
    "/api/restaurant": api_restaurant,
    "/api/neighborhoods": api_neighborhoods,
    "/api/browse": api_browse,
}

# ---------------------------------------------------------------------------
# HTTP server

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC_DIR, **kw)

    def log_message(self, fmt, *args):
        pass  # keep the console quiet

    def send_json(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ROUTES:
            params = {k: v[0] for k, v in
                      urllib.parse.parse_qs(parsed.query).items()}
            conn = connect()
            try:
                result = ROUTES[parsed.path](conn, params)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
                return
            finally:
                conn.close()
            if isinstance(result, tuple):
                self.send_json(result[0], result[1])
            else:
                self.send_json(result)
            return
        super().do_GET()

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path == "/api/refresh":
            started = start_refresh()
            self.send_json({"started": started,
                            "refreshing": refresh_state["running"]})
            return
        self.send_error(404)


def main():
    init_db()
    with connect() as conn:
        empty = conn.execute(
            "SELECT COUNT(*) c FROM inspections").fetchone()["c"] == 0
    if empty:
        print("[startup] cache is empty, pulling data from DataSF "
              "in the background (~30s)...")
        start_refresh()

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"SF Restaurant Health Scores → http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
