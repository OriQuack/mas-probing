#!/bin/bash
# Make sure the pinned Crawl4AI service is up and is the pinned one. Prints "running" (verified reuse) or
# "started"; exit 1 if it cannot be brought up. A service that fails the identity check is stopped and
# restarted. Session scripts call this before GPU jobs and stop the service at exit only if they started it.
cd "$(dirname "$0")/../.."
PY="${CRAWL4AI_CHECK_PYTHON:-$HOME/.conda/envs/doh_minpilot/bin/python}"
check() { "$PY" -m minpilot.tools.crawl4ai_service >/dev/null 2>&1; }
if check; then echo running; exit 0; fi
bash scripts/crawl4ai/stop.sh >/dev/null 2>&1
mkdir -p logs
setsid nohup bash scripts/crawl4ai/serve.sh > logs/crawl4ai.log 2>&1 < /dev/null &
for i in $(seq 1 70); do
    sleep 3
    if check; then echo started; exit 0; fi
    grep -qE "refusing to start|not healthy|exited during startup|already in use" logs/crawl4ai.log && break
done
echo "crawl4ai failed to start or failed the identity check; see logs/crawl4ai.log" >&2
bash scripts/crawl4ai/stop.sh >/dev/null 2>&1
exit 1
