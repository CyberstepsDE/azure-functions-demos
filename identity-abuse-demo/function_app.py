import subprocess

import azure.functions as func

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@app.route(route="check", methods=["GET"])
def check(req: func.HttpRequest) -> func.HttpResponse:
    """Deliberately vulnerable: shells out to `curl` with unsanitized user input.

    Classic command-injection pattern (a "is this URL reachable?" diagnostics
    endpoint that got shipped to prod). Try: ?url=example.com;<any command>
    """
    url = req.params.get("url", "https://example.com")
    result = subprocess.run(
        f"curl -s -m 5 {url}", shell=True, capture_output=True, text=True, timeout=15
    )
    return func.HttpResponse(result.stdout + result.stderr)
