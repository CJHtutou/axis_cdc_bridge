#!/usr/bin/env bash
# Create the GitHub repo and push.  Requires a PAT with `repo` scope:
#   GH_TOKEN=ghp_xxx ./scripts/publish_to_github.sh [repo-name]
set -euo pipefail

REPO_NAME="${1:-axis_cdc_bridge}"
: "${GH_TOKEN:?set GH_TOKEN=ghp_... first}"

API="https://api.github.com"
USER_JSON=$(curl -fsSL -H "Authorization: Bearer ${GH_TOKEN}" \
                       -H "Accept: application/vnd.github+json" "${API}/user")
OWNER=$(printf '%s' "$USER_JSON" | python3 -c 'import json,sys;print(json.load(sys.stdin)["login"])')
echo "authenticated as: ${OWNER}"

# create (ignore "already exists")
curl -fsSL -X POST -H "Authorization: Bearer ${GH_TOKEN}" \
     -H "Accept: application/vnd.github+json" \
     -d "{\"name\":\"${REPO_NAME}\",\"private\":false,\"description\":\"AXI4-Stream CDC bridge IP with APB3 control plane and cocotb verification\"}" \
     "${API}/user/repos" > /tmp/repo_create.json 2>/dev/null || echo "(repo may already exist)"

git remote remove origin 2>/dev/null || true
git remote add origin "https://x-access-token:${GH_TOKEN}@github.com/${OWNER}/${REPO_NAME}.git"
git push -u origin HEAD:main
echo "done: https://github.com/${OWNER}/${REPO_NAME}"
