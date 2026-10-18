#!/bin/bash
# Runs the most recent debug build on the real engine, with every request counted and capped.
# The real engine is the app's default, so a plain launch uses it too. This script still sets
# INSTAGRAMPLUS_ENGINE=real, which wins over a dummy chosen in Settings for the next launch.
# Use --engine dummy or INSTAGRAMPLUS_ENGINE=dummy for the dummy.
#
#    run-real-engine.command bootstrap
#       Starts the interpreter and opens saved sessions only. Nothing may reach Instagram.
#    run-real-engine.command profile <capture.png>
#       Adopts the session in the repository's .env, opens the own Profile page, writes a
#       capture of the window to <capture.png> and quits. Only the profile capability may
#       reach Instagram. Keep the capture outside the repository, it shows live account data.
#    run-real-engine.command comments <post pk>
#       Adopts the session in the repository's .env and reads the first comments page of one
#       post. Only the comments capability may reach Instagram. Prints counts only.
#    run-real-engine.command inbox <capture.png>
#       Adopts the session in the repository's .env, opens Messages and reads the inbox's first
#       page, then writes a capture of the window to <capture.png>. Only the inbox capability
#       may reach Instagram. Under the default Behavior the first page is the inbox page load,
#       so the cap defaults to 32. Prints counts only. Keep the capture outside the repository.
#    run-real-engine.command events <capture.png>
#       Adopts the session in the repository's .env, starts the listener through the gateway,
#       drains it for EVENTS_SECONDS (default 20), stops it and writes a capture. Only the
#       events capability may reach Instagram. The cap defaults to 6. Prints counts only.
#    run-real-engine.command profile-tabs <capture.png>
#       Adopts the session in the repository's .env, opens the own Profile page, reads its posts
#       grid and highlights, then the reels, tagged and saved tabs, and writes a capture of the
#       window to <capture.png>. Only profile, profile-posts, highlights, profile-reels, tagged
#       and saved may reach Instagram, about six reads. The cap defaults to 9. Prints counts only.
#    run-real-engine.command stories <capture.png>
#       Adopts the session in the repository's .env and waits for the stories tray Home reads at
#       launch, one request, then writes a capture of Home. Only stories-tray may reach
#       Instagram. It never opens a reel, because under the default Behavior a reel read sends a
#       mark-seen write the story's author sees, and the app refuses this mode if story-reels is
#       allowed. The cap defaults to 3. Prints counts only.
#    run-real-engine.command search <capture.png>
#       Adopts the session in the repository's .env, opens Search, which reads the recent
#       searches and the first explore page, then searches one fixed term, IG_E2_SEARCH_QUERY
#       when set in the environment and "instagram" otherwise, and writes a capture. Only
#       search-non-personalised, recent-searches and explore may reach Instagram, so the search
#       sends the non-personalised typeahead. Three reads, plus a page load when the session
#       holds no page token. The cap defaults to 12. Prints counts only, never the term.
#    run-real-engine.command reels <capture.png>
#       Adopts the session in the repository's .env, opens Reels, reads the first page and one
#       more through its cursor, and writes a capture. Only reels may reach Instagram. The cap
#       defaults to 12. Prints counts only.
#    run-real-engine.command activity <capture.png>
#       Adopts the session in the repository's .env and opens Notifications, which reads the
#       activity feed and the follow requests, while Home reads the rail's suggestions at
#       launch. Only activity, follow-requests and suggestions may reach Instagram. Reading the
#       feed marks nothing seen. The cap defaults to 12. Prints counts only.
#    run-real-engine.command post-detail <capture.png>
#       Adopts the session in the repository's .env and opens the committed test post, pk
#       3879825181007222959, by the code engine/probes/phase3_cli_acceptance.py holds. The
#       overlay reads it through media.page, six requests under the default Behavior with its
#       first comments and the author's grid, and then the likes sheet's read runs once. Only
#       post-page and likers may reach Instagram. The cap defaults to 9. Prints counts only.
#    run-real-engine.command profile-extras <capture.png>
#       Adopts the session in the repository's .env, opens the own Profile page and reads the
#       saved collections, then the mutual followers and similar accounts of
#       PROFILE_EXTRAS_USER_ID when set in the environment and of the viewer otherwise. Only
#       profile, collections, mutual-followers and similar-accounts may reach Instagram, about
#       five reads. The cap defaults to 9. Prints counts only, never the id.
#
#    run-real-engine.command signin <capture.png>
#       The first-run path on a fresh sessions directory, with no saved session: reads the
#       cookies in the repository's .env as the setup screen's paste would, runs the form's
#       validation, verifies the account (one profile read), confirms it, and waits for the
#       first Home feed page. Only profile and feed may reach Instagram. The cap defaults to 16.
#       The sessions directory is printed and kept for the next mode.
#    run-real-engine.command resume <capture.png>
#       The relaunch of signin: the same sessions directory, no cookie input. Opens the saved
#       session and reads the first Home feed page. Only feed may reach Instagram. Deletes the
#       sessions directory afterwards, it holds a session. The cap defaults to 10.
#
# engine/probes/cli_request_counter records every request that leaves the process, by host,
# friendly name and status, into engine/logs/app-live-requests-<stamp>.jsonl, and refuses any
# request past REQUEST_CAP. The app's own output goes to engine/logs/app-live-<stamp>.log.
set -euo pipefail

mode="${1:?usage: run-real-engine.command bootstrap | signin <capture.png> | resume <capture.png> | profile <capture.png> | comments <post pk> | inbox <capture.png> | events <capture.png> | profile-tabs <capture.png> | stories <capture.png> | search <capture.png> | reels <capture.png> | activity <capture.png> | post-detail <capture.png> | profile-extras <capture.png>}"
app_dir="$(cd "$(dirname "$0")/.." && pwd)"
repo_dir="$(cd "$app_dir/.." && pwd)"
binary="$HOME/Library/Developer/Xcode/DerivedData/InstagramPlus-scripts/Build/Products/Debug/Instagram+.app/Contents/MacOS/Instagram+"
stamp="$(date +%Y-%m-%d-%H%M%S)"
app_log="$repo_dir/engine/logs/app-live-$stamp.log"
request_log="$repo_dir/engine/logs/app-live-requests-$stamp.jsonl"

case "$mode" in
   inbox) default_cap=32 ;;
   events) default_cap=6 ;;
   profile-tabs|post-detail|profile-extras) default_cap=9 ;;
   stories) default_cap=3 ;;
   search|reels|activity) default_cap=12 ;;
   signin) default_cap=16 ;;
   resume) default_cap=10 ;;
   *) default_cap=5 ;;
esac

request_cap="${REQUEST_CAP:-$default_cap}"

refuse_capture_inside_repository() {
   case "$(cd "$(dirname "$1")" && pwd)" in
      "$repo_dir"*)
         echo "refusing a capture path inside the repository"
         exit 1
         ;;
   esac
}

if [ ! -x "$binary" ]; then
   echo "no build at $binary, run build-app.command first"
   exit 1
fi

export INSTAGRAMPLUS_ENGINE=real
export INSTAGRAMPLUS_PYTHONPATH_PREPEND="$repo_dir/engine/probes/cli_request_counter"
export DUMPSTA_PROBE_REQUEST_LOG="$request_log"
export DUMPSTA_PROBE_REQUEST_CAP="$request_cap"
export DUMPSTA_PROBE_STEP="app-$mode"

app_arguments=()

case "$mode" in
   bootstrap)
      export INSTAGRAMPLUS_ENGINE_CAPABILITIES=""
      timeout_seconds=20
      ;;

   profile)
      capture_path="${2:?profile mode needs a capture path outside the repository}"
      refuse_capture_inside_repository "$capture_path"
      export INSTAGRAMPLUS_ENGINE_CAPABILITIES="profile"
      export INSTAGRAMPLUS_COOKIE_FILE="$repo_dir/.env"
      app_arguments=(--real-profile-capture "$capture_path")
      timeout_seconds=150
      ;;

   comments)
      post_pk="${2:?comments mode needs a post pk}"
      export INSTAGRAMPLUS_ENGINE_CAPABILITIES="comments"
      export INSTAGRAMPLUS_COOKIE_FILE="$repo_dir/.env"
      app_arguments=(--real-comments "$post_pk")
      timeout_seconds=60
      ;;

   inbox)
      capture_path="${2:?inbox mode needs a capture path outside the repository}"
      refuse_capture_inside_repository "$capture_path"
      export INSTAGRAMPLUS_ENGINE_CAPABILITIES="inbox"
      export INSTAGRAMPLUS_COOKIE_FILE="$repo_dir/.env"
      app_arguments=(--real-inbox-capture "$capture_path")
      timeout_seconds=150
      ;;

   events)
      capture_path="${2:?events mode needs a capture path outside the repository}"
      refuse_capture_inside_repository "$capture_path"
      events_seconds="${EVENTS_SECONDS:-20}"
      export INSTAGRAMPLUS_ENGINE_CAPABILITIES="events"
      export INSTAGRAMPLUS_COOKIE_FILE="$repo_dir/.env"
      export INSTAGRAMPLUS_EVENTS_SECONDS="$events_seconds"
      app_arguments=(--real-events-capture "$capture_path")
      timeout_seconds=$((events_seconds + 90))
      ;;

   profile-tabs)
      capture_path="${2:?profile-tabs mode needs a capture path outside the repository}"
      refuse_capture_inside_repository "$capture_path"
      export INSTAGRAMPLUS_ENGINE_CAPABILITIES="profile,profile-posts,highlights,profile-reels,tagged,saved"
      export INSTAGRAMPLUS_COOKIE_FILE="$repo_dir/.env"
      app_arguments=(--real-profile-tabs-capture "$capture_path")
      timeout_seconds=180
      ;;

   stories)
      capture_path="${2:?stories mode needs a capture path outside the repository}"
      refuse_capture_inside_repository "$capture_path"
      export INSTAGRAMPLUS_ENGINE_CAPABILITIES="stories-tray"
      export INSTAGRAMPLUS_COOKIE_FILE="$repo_dir/.env"
      app_arguments=(--real-stories-tray-capture "$capture_path")
      timeout_seconds=120
      ;;

   search)
      capture_path="${2:?search mode needs a capture path outside the repository}"
      refuse_capture_inside_repository "$capture_path"
      export INSTAGRAMPLUS_ENGINE_CAPABILITIES="search-non-personalised,recent-searches,explore"
      export INSTAGRAMPLUS_COOKIE_FILE="$repo_dir/.env"
      app_arguments=(--real-search-capture "$capture_path")
      timeout_seconds=150
      ;;

   reels)
      capture_path="${2:?reels mode needs a capture path outside the repository}"
      refuse_capture_inside_repository "$capture_path"
      export INSTAGRAMPLUS_ENGINE_CAPABILITIES="reels"
      export INSTAGRAMPLUS_COOKIE_FILE="$repo_dir/.env"
      app_arguments=(--real-reels-capture "$capture_path")
      timeout_seconds=150
      ;;

   activity)
      capture_path="${2:?activity mode needs a capture path outside the repository}"
      refuse_capture_inside_repository "$capture_path"
      export INSTAGRAMPLUS_ENGINE_CAPABILITIES="activity,follow-requests,suggestions"
      export INSTAGRAMPLUS_COOKIE_FILE="$repo_dir/.env"
      app_arguments=(--real-activity-capture "$capture_path")
      timeout_seconds=150
      ;;

   post-detail)
      capture_path="${2:?post-detail mode needs a capture path outside the repository}"
      refuse_capture_inside_repository "$capture_path"
      post_code="$(sed -n 's/^POST_CODE = "\(.*\)"$/\1/p' "$repo_dir/engine/probes/phase3_cli_acceptance.py")"

      if [ -z "$post_code" ]; then
         echo "no POST_CODE in engine/probes/phase3_cli_acceptance.py"
         exit 1
      fi

      export INSTAGRAMPLUS_ENGINE_CAPABILITIES="post-page,likers"
      export INSTAGRAMPLUS_COOKIE_FILE="$repo_dir/.env"
      export INSTAGRAMPLUS_PROBE_POST_CODE="$post_code"
      app_arguments=(--real-post-detail-capture "$capture_path")
      timeout_seconds=150
      ;;

   profile-extras)
      capture_path="${2:?profile-extras mode needs a capture path outside the repository}"
      refuse_capture_inside_repository "$capture_path"
      export INSTAGRAMPLUS_ENGINE_CAPABILITIES="profile,collections,mutual-followers,similar-accounts"
      export INSTAGRAMPLUS_COOKIE_FILE="$repo_dir/.env"
      export INSTAGRAMPLUS_PROBE_USER_ID="${PROFILE_EXTRAS_USER_ID:-}"
      app_arguments=(--real-profile-extras-capture "$capture_path")
      timeout_seconds=150
      ;;

   signin)
      capture_path="${2:?signin mode needs a capture path outside the repository}"
      refuse_capture_inside_repository "$capture_path"
      sessions_dir="$repo_dir/engine/logs/probe-sessions"
      rm -rf "$sessions_dir"
      mkdir -p "$sessions_dir"
      chmod 700 "$sessions_dir"
      echo "sessions directory $sessions_dir"
      export INSTAGRAMPLUS_SESSIONS_DIR="$sessions_dir"
      export INSTAGRAMPLUS_ENGINE_CAPABILITIES="profile,feed"
      export INSTAGRAMPLUS_PROBE_COOKIE_FILE="$repo_dir/.env"
      app_arguments=(--real-signin-capture "$capture_path")
      timeout_seconds=150
      ;;

   resume)
      capture_path="${2:?resume mode needs a capture path outside the repository}"
      refuse_capture_inside_repository "$capture_path"
      sessions_dir="$repo_dir/engine/logs/probe-sessions"
      [ -d "$sessions_dir" ] || { echo "no sessions directory, run signin first"; exit 1; }
      export INSTAGRAMPLUS_SESSIONS_DIR="$sessions_dir"
      export INSTAGRAMPLUS_ENGINE_CAPABILITIES="feed"
      app_arguments=(--real-resume-capture "$capture_path")
      timeout_seconds=150
      ;;

   *)
      echo "unknown mode $mode"
      exit 1
      ;;
esac

echo "mode $mode, request cap $request_cap, started $(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$app_log"

"$binary" "${app_arguments[@]+"${app_arguments[@]}"}" >> "$app_log" 2>&1 &
app_pid=$!

for _ in $(seq "$timeout_seconds"); do
   kill -0 "$app_pid" 2>/dev/null || break
   sleep 1
done

if kill -0 "$app_pid" 2>/dev/null; then
   echo "stopping the app after ${timeout_seconds}s" >> "$app_log"
   kill "$app_pid"
fi

wait "$app_pid" 2>/dev/null || true

request_count=0
[ -f "$request_log" ] && request_count="$(wc -l < "$request_log" | tr -d ' ')"
echo "requests on the wire: $request_count" >> "$app_log"

[ "$mode" = resume ] && rm -rf "$repo_dir/engine/logs/probe-sessions"

cat "$app_log"
echo "app log at $app_log"
[ -f "$request_log" ] && echo "request log at $request_log"
exit 0
