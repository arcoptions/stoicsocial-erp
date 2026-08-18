#!/usr/bin/env bash
#
# Deploy BoldERP to the WHM production server.
#
#   ./deploy.sh              # deploy origin/main
#   ./deploy.sh --dry-run    # show what would be deployed, change nothing
#   ./deploy.sh --force      # redeploy/restart even when there is nothing new
#
# What it does, in order: fetch -> refuse if the incoming diff touches runtime state ->
# back up the SQLite DB -> merge -> migrate -> collectstatic -> restart -> verify.
#
# See DEPLOYMENT.md Part 10 for the server layout and the manual equivalent.

set -euo pipefail

SSH_HOST="${BOLDERP_SSH_HOST:-bolderp}"
APP_DIR="${BOLDERP_APP_DIR:-/opt/bolderp/app}"
VENV_PY="${BOLDERP_PYTHON:-/opt/bolderp/venv/bin/python}"
BACKUP_DIR="${BOLDERP_BACKUP_DIR:-/opt/bolderp/runtime/backups}"
SERVICE="${BOLDERP_SERVICE:-bolderp}"
RUN_AS="${BOLDERP_RUN_AS:-bolderp}"
BRANCH="${BOLDERP_BRANCH:-main}"
PUBLIC_URL="${BOLDERP_URL:-https://erp.boldanditalic.in/}"

# The repo has an empty .gitignore, so these live-state paths are tracked in git.
# A commit that changes any of them would overwrite the production database, the
# production secrets or uploaded files with a stale snapshot from a developer's machine.
PROTECTED_PATHS="db.sqlite3 .env media/ staticfiles/"

DRY_RUN=0
FORCE=0
ALLOW_RUNTIME_PATHS=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)              DRY_RUN=1 ;;
    --force)                FORCE=1 ;;
    --allow-runtime-paths)  ALLOW_RUNTIME_PATHS=1 ;;
    -h|--help)              sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)                      echo "deploy.sh: unknown option '$1'" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[31mdeploy.sh: %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- local pre-flight

if git rev-parse --git-dir >/dev/null 2>&1; then
  local_head=$(git rev-parse HEAD)
  if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    echo "note: you have uncommitted local changes; only what is on origin/$BRANCH deploys."
  fi
  if git rev-parse --verify --quiet "origin/$BRANCH" >/dev/null; then
    if [ "$local_head" != "$(git rev-parse "origin/$BRANCH")" ] \
       && git merge-base --is-ancestor "origin/$BRANCH" HEAD 2>/dev/null; then
      die "local HEAD is ahead of origin/$BRANCH — push first, the server deploys from the remote."
    fi
  fi
fi

say "Deploying origin/$BRANCH to $SSH_HOST:$APP_DIR"

# ---------------------------------------------------------------- remote

remote() {
  # Config first (locally expanded and shell-quoted), then the body verbatim.
  cat <<PREAMBLE
APP_DIR=$(printf '%q' "$APP_DIR")
VENV_PY=$(printf '%q' "$VENV_PY")
BACKUP_DIR=$(printf '%q' "$BACKUP_DIR")
SERVICE=$(printf '%q' "$SERVICE")
RUN_AS=$(printf '%q' "$RUN_AS")
BRANCH=$(printf '%q' "$BRANCH")
PUBLIC_URL=$(printf '%q' "$PUBLIC_URL")
PROTECTED_PATHS=$(printf '%q' "$PROTECTED_PATHS")
DRY_RUN=$DRY_RUN
FORCE=$FORCE
ALLOW_RUNTIME_PATHS=$ALLOW_RUNTIME_PATHS
PREAMBLE
  cat <<'REMOTE'
set -euo pipefail
say() { printf '\n\033[1m--- %s\033[0m\n' "$*"; }
die() { printf '\n\033[31mdeploy: %s\033[0m\n' "$*" >&2; exit 1; }
asapp() { sudo -u "$RUN_AS" "$@"; }

cd "$APP_DIR" || die "no such directory: $APP_DIR"

# 1. Fetch. The explicit refspec is required: plain `git fetch origin main` only moves
#    FETCH_HEAD, leaving refs/remotes/origin/main stale and the merge a silent no-op.
say "Fetching origin/$BRANCH"
asapp git fetch origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"

before=$(asapp git rev-parse HEAD)
target=$(asapp git rev-parse "origin/$BRANCH")

if [ "$before" = "$target" ] || asapp git merge-base --is-ancestor "$target" "$before"; then
  echo "Server already contains origin/$BRANCH ($(echo "$target" | cut -c1-8))."
  if [ "$FORCE" != "1" ]; then
    echo "Nothing to deploy. Use --force to migrate/collectstatic/restart anyway."
    exit 0
  fi
  echo "--force given: continuing."
else
  say "Incoming commits"
  asapp git --no-pager log --oneline --no-decorate "$before..$target" | sed 's/^/  /'
fi

# 2. Guard. Refuse to pull commits that rewrite live runtime state.
say "Checking the incoming diff for runtime state"
changed=$(asapp git diff --name-only "$before" "$target" || true)
hits=""
for p in $PROTECTED_PATHS; do
  case "$p" in
    */) match=$(printf '%s\n' "$changed" | grep -E "^${p}" || true) ;;
    *)  match=$(printf '%s\n' "$changed" | grep -Fx "$p"      || true) ;;
  esac
  [ -n "$match" ] && hits="$hits$match"$'\n'
done

if [ -n "${hits//[$'\n' ]/}" ]; then
  printf '%s\n' "$hits" | sed '/^$/d;s/^/  /' >&2
  if [ "$ALLOW_RUNTIME_PATHS" != "1" ]; then
    die "the incoming commits modify tracked runtime state (above).
Merging would overwrite the live database, secrets or uploads with a stale snapshot.
Drop those files from the commits, or re-run with --allow-runtime-paths if you are
certain that is what you want."
  fi
  echo "WARNING: --allow-runtime-paths given; proceeding anyway."
fi
echo "  clean — no runtime state in this diff"

if [ "$DRY_RUN" = "1" ]; then
  say "Dry run: stopping before any change"
  exit 0
fi

# 3. Back up the live SQLite database using the online-backup API, which is safe
#    to run against a database gunicorn is actively serving.
say "Backing up the database"
sudo mkdir -p "$BACKUP_DIR"
sudo chown "$RUN_AS":"$RUN_AS" "$BACKUP_DIR"
stamp=$(date +%Y%m%d-%H%M%S)
asapp "$VENV_PY" - "$APP_DIR/db.sqlite3" "$BACKUP_DIR/db-$stamp.sqlite3" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(src); d = sqlite3.connect(dst)
with d:
    s.backup(d)
d.close(); s.close()
print("  wrote", dst)
PY
asapp cp -p "$APP_DIR/.env" "$BACKUP_DIR/env-$stamp.bak"
echo "  wrote $BACKUP_DIR/env-$stamp.bak"

# 4. Merge. Never reset/checkout — that restores tracked runtime state from a commit.
say "Merging origin/$BRANCH"
if ! asapp git merge --no-edit "origin/$BRANCH"; then
  die "merge failed or conflicted. Resolve on the server, then re-run.
The database backup above is intact; the service was NOT restarted.
For a conflict on a file that is identical upstream:
  git diff <server-sha> origin/$BRANCH -- <file>   # empty means identical
  git checkout origin/$BRANCH -- <file> && git add <file> && git commit --no-edit"
fi

# 5. Apply
say "Migrating"
asapp "$VENV_PY" manage.py migrate --noinput
say "Collecting static files"
asapp "$VENV_PY" manage.py collectstatic --noinput
say "Restarting $SERVICE"
sudo systemctl restart "$SERVICE"

# 6. Verify
say "Verifying"
sleep 3
systemctl is-active --quiet "$SERVICE" || die "$SERVICE is not active after restart.
  journalctl -u $SERVICE -n 50 --no-pager"
echo "  $SERVICE: active"

# Do not curl 127.0.0.1:8010 — ALLOWED_HOSTS rejects a bare IP with a 400.
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$PUBLIC_URL" || echo "000")
echo "  $PUBLIC_URL -> HTTP $code"
case "$code" in
  200|301|302) ;;
  *) die "unexpected status from $PUBLIC_URL. Check: journalctl -u $SERVICE -n 50 --no-pager" ;;
esac

errors=$(journalctl -u "$SERVICE" --since "-2m" --no-pager 2>/dev/null \
         | grep -Ei 'traceback|internal server error' || true)
if [ -n "$errors" ]; then
  echo "  WARNING: errors in the log since restart:"
  printf '%s\n' "$errors" | tail -n 20 | sed 's/^/    /'
fi

echo
echo "Deployed $(asapp git rev-parse --short HEAD) — rollback backup: $BACKUP_DIR/db-$stamp.sqlite3"
REMOTE
}

remote | ssh "$SSH_HOST" bash -s

if [ "$DRY_RUN" = "1" ]; then
  say "Dry run complete — nothing was changed."
else
  say "Done."
fi
