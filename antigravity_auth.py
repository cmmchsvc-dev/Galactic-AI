import os
import json
import base64
import hashlib
import urllib.parse
import urllib.request
import webbrowser
import http.server
import socketserver
import time


def _load_antigravity_client():
    """OAuth client id/secret for the installed-app Antigravity flow. Real
    values live in the gitignored config.local.yaml overlay
    (antigravity.client_id / antigravity.client_secret) — never hardcode
    them here. Env vars are also honored for non-Galactic-AI deployments."""
    client_id = os.environ.get('ANTIGRAVITY_CLIENT_ID', '')
    client_secret = os.environ.get('ANTIGRAVITY_CLIENT_SECRET', '')
    if client_id and client_secret:
        return client_id, client_secret
    try:
        import config_loader
        cfg = config_loader.load_config()
        ag = cfg.get('antigravity', {}) or {}
        return ag.get('client_id', client_id), ag.get('client_secret', client_secret)
    except Exception:
        return client_id, client_secret


CLIENT_ID, CLIENT_SECRET = _load_antigravity_client()
REDIRECT_URI = "http://127.0.0.1:51121/callback"
SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs"
]

TOKEN_FILE = os.path.join(os.path.dirname(__file__), "config", "antigravity_token.json")

def generate_pkce():
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).decode('utf-8').rstrip('=')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('utf-8')).digest()
    ).decode('utf-8').rstrip('=')
    return code_verifier, code_challenge

def encode_state(verifier):
    state = json.dumps({"verifier": verifier, "projectId": ""})
    return base64.urlsafe_b64encode(state.encode('utf-8')).decode('utf-8').rstrip('=')

class OAuthHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        
        if 'code' in params:
            self.server.auth_code = params['code'][0]
            self.wfile.write(b"<html><body><h1>Authentication successful!</h1><p>You can close this window now.</p></body></html>")
        else:
            self.wfile.write(b"<html><body><h1>Authentication failed.</h1></body></html>")

def authenticate():
    verifier, challenge = generate_pkce()
    state = encode_state(verifier)

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={CLIENT_ID}&"
        "response_type=code&"
        f"redirect_uri={urllib.parse.quote(REDIRECT_URI)}&"
        f"scope={urllib.parse.quote(' '.join(SCOPES))}&"
        f"code_challenge={challenge}&"
        "code_challenge_method=S256&"
        f"state={state}&"
        "access_type=offline&"
        "prompt=consent"
    )

    print("Opening browser for Google Authentication...")
    webbrowser.open(auth_url)

    print("Waiting for callback on port 51121...")
    with socketserver.TCPServer(("127.0.0.1", 51121), OAuthHandler) as httpd:
        httpd.auth_code = None
        while not httpd.auth_code:
            httpd.handle_request()
        code = httpd.auth_code

    print("Exchanging code for token...")
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier
    }).encode('utf-8')

    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    try:
        with urllib.request.urlopen(req) as response:
            token_data = json.loads(response.read().decode('utf-8'))
            
            # Save token
            os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
            with open(TOKEN_FILE, 'w') as f:
                json.dump(token_data, f, indent=2)
            print(f"Token saved to {TOKEN_FILE}")
            return token_data
    except Exception as e:
        print(f"Failed to get token: {e}")

if __name__ == "__main__":
    authenticate()
