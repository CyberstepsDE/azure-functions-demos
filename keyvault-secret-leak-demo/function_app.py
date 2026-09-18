import os
import subprocess

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

VAULT_URL = os.environ.get("KEY_VAULT_URL", "")
SECRET_NAME = os.environ.get("DB_SECRET_NAME", "db-password")


@app.route(route="db-status", methods=["GET"])
def db_status(req: func.HttpRequest) -> func.HttpResponse:
    """Legit use of the identity: fetch a secret server-side, never return it.

    This is how it's *supposed* to work — the Function's managed identity
    reads the secret to configure a downstream connection, and only a
    boolean/length ever leaves the process.
    """
    client = SecretClient(vault_url=VAULT_URL, credential=DefaultAzureCredential())
    secret = client.get_secret(SECRET_NAME)
    return func.HttpResponse(f"DB configured: True (secret length={len(secret.value)})")


@app.route(route="lookup", methods=["GET"])
def lookup(req: func.HttpRequest) -> func.HttpResponse:
    """Deliberately vulnerable: shells out with unsanitized input.

    A "hostname lookup" diagnostics endpoint that got shipped to prod.
    Try: ?host=127.0.0.1;<any command>
    """
    host = req.params.get("host", "127.0.0.1")
    result = subprocess.run(
        f"getent hosts {host}", shell=True, capture_output=True, text=True, timeout=15
    )
    return func.HttpResponse(result.stdout + result.stderr)
