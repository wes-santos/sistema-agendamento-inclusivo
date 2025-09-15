#!/bin/sh
set -eu

# Install cron if missing (Debian-based image)
if ! command -v cron >/dev/null 2>&1; then
  apt-get update >/dev/null
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends cron >/dev/null
  rm -rf /var/lib/apt/lists/*
fi

# Ensure Poetry is available
if ! command -v poetry >/dev/null 2>&1; then
  pip install --no-cache-dir poetry >/dev/null
fi

# Install app deps (main only)
poetry install --only main --no-root >/dev/null

# Prepare cron entry
mkdir -p /etc/cron.d
CRON_FILE=/etc/cron.d/reminders
echo "0 9 * * * cd /app && poetry run python -m app.jobs.remind_t24 >> /var/log/reminders.log 2>&1" > "$CRON_FILE"
chmod 0644 "$CRON_FILE"
crontab "$CRON_FILE"

# Ensure log exists
touch /var/log/reminders.log

exec /usr/sbin/cron -f

