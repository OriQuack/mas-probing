#!/bin/bash
# Crawl4AI page-reader service (from the previous pilot, unchanged): pinned image, rootless via Apptainer, CPU only, loopback only.
#   bash scripts/crawl4ai/ensure.sh     # start if needed (detached) and verify identity  <- normal use
#   bash scripts/crawl4ai/stop.sh       # stop the whole process group
# Identity (scripts/crawl4ai/IMAGE): the SIF executed must have the pinned sha256, else this refuses to start.
# The pgid file is written FIRST (outputs/servers/crawl4ai.pgid), so stop.sh can clean up even if startup
# fails; the endpoint file (mode 600: base_url, token, identity) only once /health returns HTTP 200 with the
# pinned version. If the service does not become healthy, this script kills its own group and exits 1.
# Container: --containall --cleanenv (no host files or variables), fresh scratch /tmp and home on /data2
# (a 64 MB tmpfs crashed Chromium), its own Redis port (the host runs one on 6379), random per-start Redis
# password and API token. supervisord is bypassed (it switches to user appuser, impossible rootless).
set -u
cd "$(dirname "$0")/../.."
SIF="${CRAWL4AI_SIF:-/data2/dohyun/containers/crawl4ai-0.9.4.sif}"
PORT="${CRAWL4AI_PORT:-18235}"
RPORT="${CRAWL4AI_REDIS_PORT:-16379}"
SERVERS="${CRAWL4AI_SERVERS_DIR:-outputs/servers}"; EP="$SERVERS/crawl4ai.json"
PGFILE="$SERVERS/crawl4ai.pgid"
mkdir -p "$SERVERS" logs
val() { grep -E "^$1=" scripts/crawl4ai/IMAGE | cut -d= -f2-; }
TAG=$(val tag); DIGEST=$(val docker_digest); SIF_SHA=$(val sif_sha256); VERSION=$(val version)
GOT_SHA=$(sha256sum "$SIF" 2>/dev/null | cut -d' ' -f1)
if [ "$GOT_SHA" != "$SIF_SHA" ]; then
    echo "refusing to start: $SIF sha256 $GOT_SHA != pinned $SIF_SHA (scripts/crawl4ai/IMAGE)"; exit 2
fi
if ss -ltn | grep -qE "127.0.0.1:($PORT|$RPORT)\b"; then
    echo "port $PORT or $RPORT already in use: stop the running instance first (scripts/crawl4ai/stop.sh)"; exit 1
fi
PGID="$(ps -o pgid= $$ | tr -d ' ')"
echo "$PGID" > "$PGFILE"
rm -f "$EP"
cleanup() { rm -f "$EP" "$PGFILE"; }
trap cleanup EXIT
PASS="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
SCRATCH="${CRAWL4AI_SCRATCH:-/data2/dohyun/containers/crawl4ai_scratch}"
rm -rf "$SCRATCH"; mkdir -p "$SCRATCH/work" "$SCRATCH/home"
apptainer exec --containall --writable-tmpfs --cleanenv \
    --workdir "$SCRATCH/work" --home "$SCRATCH/home:/home/dohyun" \
    --env "CRAWL4AI_API_TOKEN=$TOKEN,REDIS_PASSWORD=$PASS,REDIS_HOST=127.0.0.1,REDIS_PORT=$RPORT,ENABLE_GPU=false,CRAWL4AI_HOOKS_ENABLED=false,PYTHONUNBUFFERED=1" \
    --env "PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright" \
    "$SIF" bash -c "redis-server --bind 127.0.0.1 --port $RPORT --requirepass $PASS --dir /tmp --save '' & RP=\$!; \
        trap 'kill \$RP 2>/dev/null' EXIT INT TERM; sleep 1; kill -0 \$RP || exit 1; cd /app && \
        gunicorn --bind 127.0.0.1:$PORT --workers 1 --threads 4 --timeout 1800 --graceful-timeout 30 \
        --keep-alive 300 --log-level info --worker-class uvicorn.workers.UvicornWorker server:app" &
PID=$!
healthy() {  # HTTP 200 and the pinned version
    python3 - "$PORT" "$VERSION" <<'PY'
import json, sys, urllib.request
try:
    r = urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=10)
    sys.exit(0 if r.status == 200 and json.load(r).get("version") == sys.argv[2] else 1)
except Exception:
    sys.exit(1)
PY
}
for i in $(seq 1 90); do
    if healthy; then
        (umask 077; python3 - "$EP" <<PY
import json, sys
json.dump({"base_url": "http://127.0.0.1:$PORT", "token": "$TOKEN", "tag": "$TAG", "docker_digest": "$DIGEST",
           "sif_sha256": "$SIF_SHA", "version": "$VERSION", "sif": "$SIF", "pgid": $PGID}, open(sys.argv[1], "w"))
PY
)
        echo "crawl4ai up: version $VERSION, sif $SIF_SHA"
        wait $PID
        exit $?
    fi
    kill -0 $PID 2>/dev/null || { echo "crawl4ai exited during startup"; exit 1; }
    sleep 2
done
echo "crawl4ai not healthy after 180 s: stopping own process group"
cleanup
trap - EXIT
kill -TERM -- "-$PGID"
exit 1
