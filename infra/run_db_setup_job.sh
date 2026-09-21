#!/usr/bin/env bash
# One-time: creates an ACA Manual job that provisions a scoped least-privilege
# Postgres user ("agentregistry_app") on zaf-postgres-01 for the agentregistry
# database, using the zafadmin credential only inside this one-off job.
#
# Rewritten to fill a YAML manifest (db-setup-job.yaml) instead of passing the
# script as --args — the original --args approach broke on the script's
# embedded newlines ("unrecognized arguments"). The filled-in temp file with
# real secrets is written to a private temp dir and removed when this exits.
set -euo pipefail

cd "$(dirname "$0")"

TMP_YAML="$(mktemp -t agentregistry-db-setup-XXXXXX).yaml"
trap 'rm -f "$TMP_YAML"' EXIT

PYSCRIPT_B64=$(base64 -i provision_pg.py | tr -d '\n')
ADMIN_PW=$(grep "^PG_ADMIN_URL=" ../backend/.env | sed -E 's#.*zafadmin:([^@]+)@.*#\1#')
ACR_USER=$(az acr credential show --name zafacr --query username -o tsv)
ACR_PASS=$(az acr credential show --name zafacr --query 'passwords[0].value' -o tsv)

sed -e "s|__ACR_USER__|${ACR_USER}|" \
    -e "s|__ACR_PASS__|${ACR_PASS}|" \
    -e "s|__PG_ADMIN_PW__|${ADMIN_PW}|" \
    -e "s|__PYSCRIPT_B64__|${PYSCRIPT_B64}|" \
    db-setup-job.yaml > "$TMP_YAML"

az containerapp job create \
  --name agentregistry-db-setup \
  --resource-group Zenlabs-Agent-Foundry \
  --yaml "$TMP_YAML" \
  --only-show-errors -o none

echo "Job created. Starting execution..."
az containerapp job start --name agentregistry-db-setup --resource-group Zenlabs-Agent-Foundry --only-show-errors -o none
echo "Started. Tell Claude to continue — it will poll for completion and read the result."
