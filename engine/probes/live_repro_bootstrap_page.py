import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
ENV_PATH = Path(__file__).resolve().parents[3] / ".env"


def write_log(kind, payload):
   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   path = LOG_DIR / f"{kind}-{stamp}.json"
   path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
   return path


ORIGIN = "https://www.instagram.com"
THREAD_FBID = "17945046917948992"
DOC_ID = "27502152406082940"


def load_env(path):
   values = {}
   for raw_line in open(path, encoding="utf-8"):
      line = raw_line.strip()
      is_comment = line.startswith("#")
      has_assignment = "=" in line
      if line and not is_comment and has_assignment:
         key, _, value = line.partition("=")
         values[key.strip()] = value.strip().strip('"').strip("'")
   return values


env = load_env(ENV_PATH)

required = ["IG_SESSIONID", "IG_DS_USER_ID", "IG_CSRFTOKEN"]
missing = [k for k in required if not env.get(k)]
if missing:
   print("MISSING", missing)
   sys.exit(2)

user_agent = (
   env.get("IG_USER_AGENT")
   or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

cookies = {
   "sessionid": env["IG_SESSIONID"],
   "ds_user_id": env["IG_DS_USER_ID"],
   "csrftoken": env["IG_CSRFTOKEN"],
}
if env.get("IG_MID"):
   cookies["mid"] = env["IG_MID"]


def first(pattern, text, group=1):
   match = re.search(pattern, text)
   return match.group(group) if match else None


report = {}

with httpx.Client(cookies=cookies, timeout=30.0, follow_redirects=True) as client:
   t0 = time.time()
   bootstrap = client.get(
      f"{ORIGIN}/direct/inbox/",
      headers={
         "user-agent": user_agent,
         "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
         "accept-language": "en-US,en;q=0.9",
         "sec-fetch-site": "none",
         "sec-fetch-mode": "navigate",
         "sec-fetch-dest": "document",
      },
   )
   html = bootstrap.text
   bootstrap_ms = int((time.time() - t0) * 1000)

   fb_dtsg = first(r'"DTSGInitialData",\[\],\{"token":"(.*?)"', html)
   lsd = first(r'"LSD",\[\],\{"token":"(.*?)"', html)
   spin_r = first(r'"__spin_r":(\d+)', html)
   spin_b = first(r'"__spin_b":"(.*?)"', html)
   spin_t = first(r'"__spin_t":(\d+)', html)
   hsi = first(r'"hsi":"(.*?)"', html)
   haste_session = first(r'"haste_session":"(.*?)"', html)
   rev = first(r'"server_revision":(\d+)', html) or spin_r
   app_id = first(r'"X-IG-App-ID":"(\d+)"', html)
   user_ids = re.findall(r'"USER_ID":"(\d+)"', html)
   viewer_id = next((uid for uid in user_ids if uid != "0"), env["IG_DS_USER_ID"])

   report["bootstrap"] = {
      "status": bootstrap.status_code,
      "html_bytes": len(bootstrap.content),
      "elapsed_ms": bootstrap_ms,
      "fb_dtsg_len": len(fb_dtsg) if fb_dtsg else None,
      "lsd_len": len(lsd) if lsd else None,
      "app_id": app_id,
      "spin_r": spin_r,
      "spin_b": spin_b,
      "rev": rev,
      "hsi_present": bool(hsi),
      "haste_session_present": bool(haste_session),
      "user_id_matches": user_ids[:3],
      "viewer_id_equals_ds_user_id": viewer_id == env["IG_DS_USER_ID"],
      "logged_in_marker": '"USER_ID":"0"' not in html[:200000] or bool(fb_dtsg),
   }

   if not fb_dtsg:
      report["aborted"] = "no fb_dtsg, bootstrap unauthenticated or extraction broken"
      log_path = write_log("live-repro-failed", report)
      print(json.dumps(report, indent=2, default=str))
      print(f"log written to {log_path}")
      sys.exit(3)

   jazoest = "2" + str(sum(ord(ch) for ch in fb_dtsg))

   variables = {
      "after": None,
      "before": None,
      "first": 20,
      "last": None,
      "newer_than_message_id": None,
      "older_than_message_id": None,
      "id": THREAD_FBID,
      "__relay_internal__pv__IGDInitialMessagePageCountrelayprovider": 20,
   }

   body = {
      "av": viewer_id,
      "__d": "www",
      "__user": "0",
      "__a": "1",
      "__req": "1",
      "__hs": haste_session or "",
      "dpr": "2",
      "__ccg": "EXCELLENT",
      "__rev": rev or "",
      "__hsi": hsi or "",
      "__comet_req": "7",
      "fb_dtsg": fb_dtsg,
      "jazoest": jazoest,
      "lsd": lsd or "",
      "__spin_r": spin_r or "",
      "__spin_b": spin_b or "",
      "__spin_t": spin_t or "",
      "fb_api_caller_class": "RelayModern",
      "fb_api_req_friendly_name": "useIGDMessageListPaginationQuery",
      "server_timestamps": "true",
      "doc_id": DOC_ID,
      "variables": json.dumps(variables),
   }

   time.sleep(2.85)

   t1 = time.time()
   page = client.post(
      f"{ORIGIN}/api/graphql",
      data=body,
      headers={
         "content-type": "application/x-www-form-urlencoded",
         "sec-fetch-site": "same-origin",
         "sec-fetch-mode": "cors",
         "sec-fetch-dest": "empty",
         "user-agent": user_agent,
         "x-ig-app-id": app_id or "936619743392459",
         "x-csrftoken": env["IG_CSRFTOKEN"],
         "x-fb-lsd": lsd or "",
         "x-fb-friendly-name": "useIGDMessageListPaginationQuery",
         "x-asbd-id": "359341",
         "origin": ORIGIN,
         "referer": f"{ORIGIN}/direct/t/{THREAD_FBID}/",
         "accept": "*/*",
         "accept-language": "en-US,en;q=0.9",
      },
   )
   page_ms = int((time.time() - t1) * 1000)

   raw = page.text
   looks_like_html = raw.lstrip().startswith("<!DOCTYPE") or raw.lstrip().startswith("<html")

   parsed = None
   if not looks_like_html:
      cleaned = raw[len("for (;;);") :] if raw.startswith("for (;;);") else raw
      try:
         parsed = json.loads(cleaned)
      except json.JSONDecodeError:
         parsed = None

   result = {
      "status": page.status_code,
      "elapsed_ms": page_ms,
      "body_bytes": len(page.content),
      "returned_html_shell": looks_like_html,
      "json_parsed": parsed is not None,
   }

   if isinstance(parsed, dict):
      result["top_level_keys"] = sorted(parsed.keys())
      result["has_errors_array"] = "errors" in parsed
      result["error_field"] = parsed.get("error")
      result["error_summary"] = parsed.get("errorSummary")

      connection = parsed.get("data", {}).get("fetch__SlideThread", {}) or {}
      thread = (connection or {}).get("as_ig_direct_thread") or {}
      messages = thread.get("slide_messages") or {}
      edges = messages.get("edges") or []
      page_info = messages.get("page_info") or {}
      end_cursor = page_info.get("end_cursor")

      result["canonical_path_present"] = bool(messages)
      result["edge_count"] = len(edges)
      result["has_next_page"] = page_info.get("has_next_page")
      result["end_cursor_len"] = len(end_cursor) if end_cursor else None

      if edges:
         newest = edges[0].get("node") or {}
         result["newest_message_id"] = newest.get("id") or newest.get("message_id")
         result["newest_timestamp_us"] = newest.get("timestamp_us") or newest.get("timestamp")
         result["node_keys_sample"] = sorted(newest.keys())[:20]

   report["page"] = result

log_path = write_log("live-repro", report)
print(json.dumps(report, indent=2, default=str))
print(f"log written to {log_path}")
