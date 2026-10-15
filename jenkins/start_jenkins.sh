#!/usr/bin/env bash
# Start Jenkins in this Codespace.   Run from the repo root:   bash jenkins/start_jenkins.sh
# Needs (export first): DOCKERHUB_USERNAME, DOCKERHUB_TOKEN
# Optional:             RENDER_DEPLOY_HOOK, RENDER_API_URL   (without them the pipeline stops after the Docker Hub push)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
fail() { echo "ERROR: $*" >&2; exit 1; }

[ -f "$REPO/Jenkinsfile" ]    || fail "Jenkinsfile not found in $REPO - unzip voyage-jenkins.zip in the repo root"
[ -f "$REPO/api/Dockerfile" ] || fail "api/Dockerfile not found in $REPO"
[ -n "${DOCKERHUB_USERNAME:-}" ] || fail "DOCKERHUB_USERNAME is not set - run: export DOCKERHUB_USERNAME=<your Docker Hub username>"
[ -n "${DOCKERHUB_TOKEN:-}" ]    || fail "DOCKERHUB_TOKEN is not set - run: export DOCKERHUB_TOKEN=<your Docker Hub access token>"
[ -S /var/run/docker.sock ]      || fail "Docker socket not found - is Docker running in this Codespace?"

# Repository Jenkins builds from (GitHub). Codespaces provides GITHUB_REPOSITORY, GITHUB_USER and GITHUB_TOKEN.
if [ -z "${REPO_URL:-}" ]; then
  if [ -n "${GITHUB_REPOSITORY:-}" ]; then
    REPO_URL="https://github.com/${GITHUB_REPOSITORY}.git"
  else
    REPO_URL="$(git -C "$REPO" remote get-url origin)"
  fi
fi
[ -n "${GITHUB_TOKEN:-}" ] || echo "Note: GITHUB_TOKEN is not set - this only works if the GitHub repo is public"

# Render deploy (optional)
RENDER_API_URL="${RENDER_API_URL:-}"
RENDER_API_URL="${RENDER_API_URL%/}"
if [ -n "${RENDER_DEPLOY_HOOK:-}" ] && [ -n "$RENDER_API_URL" ]; then
  RENDER_DEPLOY_ENABLED=true
else
  RENDER_DEPLOY_ENABLED=false
  echo "Note: RENDER_DEPLOY_HOOK and/or RENDER_API_URL not set - the pipeline will push to Docker Hub but skip the Render stages"
fi

# Admin password: reuse the saved one so it stays the same across restarts
PASS_FILE="$HERE/.admin_password"
if [ -z "${JENKINS_ADMIN_PASSWORD:-}" ]; then
  if [ -s "$PASS_FILE" ]; then
    JENKINS_ADMIN_PASSWORD="$(cat "$PASS_FILE")"
  else
    JENKINS_ADMIN_PASSWORD="$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
  fi
fi
printf '%s\n' "$JENKINS_ADMIN_PASSWORD" > "$PASS_FILE"
chmod 600 "$PASS_FILE"

# Address of port 8090 in the browser (Codespaces forwards it to a *.app.github.dev URL)
if [ -n "${CODESPACE_NAME:-}" ] && [ -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
  JENKINS_PUBLIC_URL="https://${CODESPACE_NAME}-8090.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}/"
else
  JENKINS_PUBLIC_URL="http://localhost:8090/"
fi

echo "Building the Jenkins image (first time takes 3-5 minutes)..."
docker build -t voyage-jenkins:local "$HERE"

docker network inspect voyage-ci >/dev/null 2>&1 || docker network create voyage-ci >/dev/null
docker rm -f jenkins >/dev/null 2>&1 || true

export JENKINS_ADMIN_PASSWORD REPO_URL RENDER_API_URL RENDER_DEPLOY_ENABLED JENKINS_PUBLIC_URL
docker run -d --name jenkins \
  -p 8090:8080 \
  --network voyage-ci \
  --group-add "$(stat -c %g /var/run/docker.sock)" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v jenkins_home:/var/jenkins_home \
  -e JENKINS_ADMIN_PASSWORD -e REPO_URL -e GITHUB_USER -e GITHUB_TOKEN \
  -e DOCKERHUB_USERNAME -e DOCKERHUB_TOKEN \
  -e RENDER_DEPLOY_HOOK -e RENDER_API_URL -e RENDER_DEPLOY_ENABLED \
  -e JENKINS_PUBLIC_URL -e CI_NETWORK=voyage-ci \
  voyage-jenkins:local >/dev/null

printf 'Starting Jenkins'
for _ in $(seq 1 90); do
  code="$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8090/login || true)"
  [ "$code" = "200" ] && break
  printf '.'
  sleep 2
done
echo
[ "$code" = "200" ] || fail "Jenkins did not start - check: docker logs jenkins"

docker exec jenkins docker version --format 'Jenkins can use Docker {{.Server.Version}}' \
  || fail "Jenkins cannot reach Docker - check: docker logs jenkins"

cat <<MSG

Jenkins is running.
  Open : Ports tab -> port 8090 (or $JENKINS_PUBLIC_URL)
  User : admin
  Pass : $JENKINS_ADMIN_PASSWORD      (also saved in jenkins/.admin_password)
  Job  : "Voyage API - CI/CD"  building $REPO_URL (main)
  Render deploy stages: $RENDER_DEPLOY_ENABLED
MSG
