#!/bin/bash
# GCE startup script for the sysdx webapp.
#
# Runs on first boot (and every subsequent boot — steps are idempotent). It:
#   1. formats + mounts the attached persistent disk at /data
#   2. installs Docker
#   3. downloads the webapp source tarball from a GCS bucket
#   4. builds the image (webapp/Dockerfile — rust + node + python) on the VM itself,
#      where internet is direct (no TLS-intercepting proxy to break in-container git)
#   5. runs Postgres + the combined web/worker app container, publishing the app on :80
#
# Configuration is passed in via instance metadata attributes (see provision.py):
#   - bucket        : GCS bucket holding sysdx-src.tar.gz
#   - db-password   : Postgres password (kept out of this script + out of git)
#
# Progress is mirrored to gs://$BUCKET/deploy-status.txt so the deploy can be watched
# without SSH.
set -x
exec >> /var/log/sysdx-startup.log 2>&1

meta() { curl -s -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
token() { curl -s -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'; }

BUCKET="$(meta bucket)"
DBPASS="$(meta db-password)"
DBURL="postgresql://sysdx:${DBPASS}@sysdx-db:5432/sysdx"

STATUSFILE=/var/log/sysdx-status.log
status() {
  echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$STATUSFILE"
  local TOK; TOK="$(token)"
  [ -n "$TOK" ] && curl -s -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: text/plain" \
     --data-binary @"$STATUSFILE" \
     "https://storage.googleapis.com/upload/storage/v1/b/$BUCKET/o?uploadType=media&name=deploy-status.txt" >/dev/null || true
}

status "startup begin"

# ---- 1. mount persistent data disk at /data ----
DEV=/dev/disk/by-id/google-sysdx-data
for i in $(seq 1 30); do [ -e "$DEV" ] && break; sleep 2; done
if ! blkid "$DEV" >/dev/null 2>&1; then
  status "formatting data disk (first boot)"
  mkfs.ext4 -m 0 -F "$DEV"
fi
mkdir -p /data
mount -o discard,defaults "$DEV" /data || status "mount failed (maybe already mounted)"
grep -q "/data " /etc/fstab || echo "$DEV /data ext4 discard,defaults,nofail 0 2" >> /etc/fstab
mkdir -p /data/app /data/pgdata
status "data disk mounted: $(df -h /data | tail -1)"

# ---- 2. install docker ----
if ! command -v docker >/dev/null 2>&1; then
  status "installing docker"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl gnupg >/dev/null
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin >/dev/null
  systemctl enable --now docker
fi
status "docker: $(docker --version)"

# ---- 3. fetch source from GCS ----
status "downloading source"
mkdir -p /opt/sysdx-src
curl -s -H "Authorization: Bearer $(token)" -o /opt/sysdx-src.tar.gz \
  "https://storage.googleapis.com/storage/v1/b/$BUCKET/o/sysdx-src.tar.gz?alt=media"
tar xzf /opt/sysdx-src.tar.gz -C /opt/sysdx-src
status "source extracted: $(ls /opt/sysdx-src/webapp/Dockerfile)"

# ---- 4. build image (only if missing) ----
if ! docker image inspect sysdx:latest >/dev/null 2>&1; then
  status "building image (this takes several minutes: rust + node + python)"
  cd /opt/sysdx-src
  if docker build -t sysdx:latest -f webapp/Dockerfile . ; then
    status "image build OK"
  else
    status "IMAGE BUILD FAILED - see /var/log/sysdx-startup.log"
    exit 1
  fi
fi

# ---- 5. network + postgres ----
docker network create sysdx-net 2>/dev/null || true
if ! docker ps --format '{{.Names}}' | grep -q '^sysdx-db$'; then
  docker rm -f sysdx-db 2>/dev/null || true
  status "starting postgres"
  docker run -d --name sysdx-db --restart unless-stopped --network sysdx-net \
    -e POSTGRES_USER=sysdx -e POSTGRES_PASSWORD="$DBPASS" -e POSTGRES_DB=sysdx \
    -e PGDATA=/var/lib/postgresql/data/pgdata \
    -v /data/pgdata:/var/lib/postgresql/data \
    postgres:16
fi
status "waiting for postgres"
for i in $(seq 1 60); do
  docker exec sysdx-db pg_isready -U sysdx >/dev/null 2>&1 && { status "postgres ready"; break; }
  sleep 2
done

# ---- 6. app (web + worker combined) on port 80 ----
docker rm -f sysdx-app 2>/dev/null || true
status "starting app"
docker run -d --name sysdx-app --restart unless-stopped --network sysdx-net \
  -p 80:8000 \
  -e SYSDX_DATA_ROOT=/data \
  -e SYSDX_DATABASE_URL="$DBURL" \
  -e PORT=8000 \
  -v /data/app:/data \
  sysdx:latest

sleep 8
status "app container: $(docker ps --filter name=sysdx-app --format '{{.Status}}')"
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost/api/health || echo 000)
  status "health check attempt $i -> $code"
  [ "$code" = "200" ] && { status "DEPLOY COMPLETE - app healthy on port 80"; break; }
  sleep 4
done
status "startup script finished"
