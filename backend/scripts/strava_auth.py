"""
One-time Strava OAuth authorization-code flow.

Usage:
  1. Register app at https://www.strava.com/settings/api
     - Authorization Callback Domain: localhost
  2. Paste the client_id / client_secret into the strava-oauth secret
     (or run this script interactively and it will prompt).
  3. python3 backend/scripts/strava_auth.py
  4. Browser opens → click "Authorize" → tokens land in the strava-oauth secret.
"""
import argparse
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread


PORT = 8585
REDIRECT_URI = f"http://localhost:{PORT}"
SCOPE = "activity:read_all,profile:read_all"
TOKEN_URL = "https://www.strava.com/oauth/token"


def aws(args, profile, region, capture=True):
    cmd = ["aws", "--profile", profile, "--region", region] + args
    if capture:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            sys.exit(f"AWS error: {result.stderr}")
        return result.stdout.strip()
    return subprocess.run(cmd).returncode


def get_secret(profile, region):
    raw = aws(
        ["secretsmanager", "get-secret-value", "--secret-id", "strava-oauth",
         "--query", "SecretString", "--output", "text"],
        profile, region,
    )
    return json.loads(raw)


def put_secret(profile, region, payload):
    aws(
        ["secretsmanager", "put-secret-value", "--secret-id", "strava-oauth",
         "--secret-string", json.dumps(payload)],
        profile, region,
    )


class AuthHandler(BaseHTTPRequestHandler):
    code = None
    error = None

    def do_GET(self):
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        AuthHandler.code = (params.get("code") or [None])[0]
        AuthHandler.error = (params.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if AuthHandler.code:
            msg = "<h1>Strava authorized</h1><p>You can close this tab.</p>"
        else:
            msg = f"<h1>Authorization failed</h1><pre>{AuthHandler.error}</pre>"
        self.wfile.write(msg.encode())

    def log_message(self, format, *args):
        pass  # suppress


def run_server():
    server = HTTPServer(("localhost", PORT), AuthHandler)
    while AuthHandler.code is None and AuthHandler.error is None:
        server.handle_request()


def exchange_code(client_id, client_secret, code):
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--client-id", help="Override client_id (otherwise read from secret)")
    parser.add_argument("--client-secret", help="Override client_secret")
    args = parser.parse_args()

    secret = get_secret(args.profile, args.region)

    client_id = args.client_id or secret.get("client_id") or input("Strava client_id: ").strip()
    client_secret = args.client_secret or secret.get("client_secret") or input("Strava client_secret: ").strip()

    if not client_id or not client_secret:
        sys.exit("client_id and client_secret required")

    # Ensure they're saved before redirecting to Strava
    secret["client_id"] = client_id
    secret["client_secret"] = client_secret
    if not secret.get("verify_token"):
        secret["verify_token"] = "sv_" + secrets.token_urlsafe(16)
    put_secret(args.profile, args.region, secret)

    auth_url = (
        "https://www.strava.com/oauth/authorize?"
        + urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPE,
            "approval_prompt": "force",
        })
    )

    print(f"\nOpening browser to authorize…")
    print(f"If it doesn't open, paste this URL:\n  {auth_url}\n")
    Thread(target=run_server, daemon=True).start()
    webbrowser.open(auth_url)

    # Wait for callback (server sets AuthHandler.code)
    start = time.time()
    while AuthHandler.code is None and AuthHandler.error is None:
        if time.time() - start > 300:
            sys.exit("Timed out waiting for authorization (5 min)")
        time.sleep(0.5)

    if AuthHandler.error:
        sys.exit(f"Strava denied: {AuthHandler.error}")

    print("Got code, exchanging for tokens…")
    tokens = exchange_code(client_id, client_secret, AuthHandler.code)

    secret["access_token"] = tokens["access_token"]
    secret["refresh_token"] = tokens["refresh_token"]
    secret["expires_at"] = int(tokens.get("expires_at", int(time.time()) + int(tokens.get("expires_in", 21600))))
    if tokens.get("athlete"):
        secret["athlete_id"] = tokens["athlete"].get("id")

    put_secret(args.profile, args.region, secret)

    print(f"\n✓ Strava authorized.")
    print(f"  access_token: …{secret['access_token'][-6:]}")
    print(f"  refresh_token: …{secret['refresh_token'][-6:]}")
    print(f"  expires_at: {secret['expires_at']} ({time.ctime(secret['expires_at'])})")
    if secret.get("athlete_id"):
        print(f"  athlete_id: {secret['athlete_id']}")


if __name__ == "__main__":
    main()
