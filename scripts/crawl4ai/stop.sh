#!/bin/bash
# Stop the Crawl4AI service: TERM (then KILL) to the process group recorded by serve.sh. Works from the pgid
# file even when startup failed and no endpoint file exists.
cd "$(dirname "$0")/../.."
SERVERS="${CRAWL4AI_SERVERS_DIR:-outputs/servers}"; PGFILE="$SERVERS/crawl4ai.pgid"
EP="$SERVERS/crawl4ai.json"
PGID=""
[ -f "$PGFILE" ] && PGID=$(cat "$PGFILE")
[ -z "$PGID" ] && [ -f "$EP" ] && PGID=$(python3 -c "import json;print(json.load(open('$EP'))['pgid'])")
if [ -z "$PGID" ]; then echo "no pgid/endpoint file: service not running (or started by hand)"; exit 0; fi
kill -TERM -- "-$PGID" 2>/dev/null
for i in $(seq 1 30); do
    if ! kill -0 -- "-$PGID" 2>/dev/null; then rm -f "$PGFILE" "$EP"; echo "stopped (pgid $PGID)"; exit 0; fi
    sleep 1
done
kill -KILL -- "-$PGID" 2>/dev/null; rm -f "$PGFILE" "$EP"; echo "killed (pgid $PGID)"
