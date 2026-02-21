"""
remote_access.py — Galactic AI Remote Access Security Module

Provides TLS certificate generation, JWT authentication, rate limiting,
and aiohttp middleware for secure remote access to the Control Deck.

v1.0.0
"""

import os
import ssl
import time
import hmac
import json
import hashlib
import base64
import secrets
from collections import defaultdict
from aiohttp import web


# ── JWT Implementation (no external deps) ────────────────────────────────────

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += '=' * padding
    return base64.urlsafe_b64decode(s)

def create_jwt(password_hash: str, secret: str, ttl: int = 86400) -> tuple:
    """Create a JWT token with HMAC-SHA256 signature.

    Returns (token_string, expiry_timestamp).
    """
    now = int(time.time())
    exp = now + ttl

    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_encode(json.dumps({
        "sub": password_hash[:16],
        "iat": now,
        "exp": exp
    }).encode())

    signing_input = f"{header}.{payload}"
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)

    return f"{signing_input}.{sig_b64}", exp

def verify_jwt(token: str, secret: str) -> bool:
    """Verify a JWT token's signature and expiry."""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return False

        signing_input = f"{parts[0]}.{parts[1]}"
        expected_sig = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
        actual_sig = _b64url_decode(parts[2])

        if not hmac.compare_digest(expected_sig, actual_sig):
            return False

        payload = json.loads(_b64url_decode(parts[1]))
        if payload.get('exp', 0) < int(time.time()):
            return False

        return True
    except Exception:
        return False


def generate_api_secret() -> str:
    """Generate a cryptographically secure 64-character hex secret."""
    return secrets.token_hex(32)


# ── TLS Certificate Generation ───────────────────────────────────────────────

def generate_self_signed_cert(cert_dir: str = 'certs') -> tuple:
    """Generate a self-signed TLS certificate and private key.

    Returns (cert_path, key_path, fingerprint_sha256).
    Uses Python's built-in ssl module for generation when possible,
    falls back to subprocess call to openssl.
    """
    os.makedirs(cert_dir, exist_ok=True)
    cert_path = os.path.join(cert_dir, 'cert.pem')
    key_path = os.path.join(cert_dir, 'key.pem')

    if os.path.exists(cert_path) and os.path.exists(key_path):
        fingerprint = _get_cert_fingerprint(cert_path)
        return cert_path, key_path, fingerprint

    # Try using cryptography library (commonly available)
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from datetime import datetime, timedelta, timezone
        import ipaddress

        key = rsa.generate_private_key(public_exponent=65537, key_size=4096)

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "Galactic AI Control Deck"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Galactic AI"),
        ])

        # Include common LAN addresses as SANs
        san_list = [
            x509.DNSName("localhost"),
            x509.DNSName("*.local"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            x509.IPAddress(ipaddress.IPv4Address("0.0.0.0")),
        ]

        # Try to detect local IP for SAN
        try:
            import socket
            local_ip = socket.gethostbyname(socket.gethostname())
            if local_ip and local_ip != "127.0.0.1":
                san_list.append(x509.IPAddress(ipaddress.IPv4Address(local_ip)))
        except Exception:
            pass

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
            .sign(key, hashes.SHA256())
        )

        with open(key_path, 'wb') as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))

        with open(cert_path, 'wb') as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        fingerprint = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
        return cert_path, key_path, fingerprint

    except ImportError:
        pass

    # Fallback: openssl command line
    import subprocess
    subprocess.run([
        'openssl', 'req', '-x509', '-newkey', 'rsa:4096',
        '-keyout', key_path, '-out', cert_path,
        '-days', '3650', '-nodes',
        '-subj', '/CN=Galactic AI Control Deck/O=Galactic AI'
    ], check=True, capture_output=True)

    fingerprint = _get_cert_fingerprint(cert_path)
    return cert_path, key_path, fingerprint


def _get_cert_fingerprint(cert_path: str) -> str:
    """Get SHA-256 fingerprint of a PEM certificate."""
    try:
        with open(cert_path, 'rb') as f:
            pem_data = f.read()
        # Extract DER from PEM
        from cryptography.x509 import load_pem_x509_certificate
        cert = load_pem_x509_certificate(pem_data)
        from cryptography.hazmat.primitives.serialization import Encoding
        der = cert.public_bytes(Encoding.DER)
        return hashlib.sha256(der).hexdigest()
    except Exception:
        # Fallback: hash the raw PEM (less standard but functional)
        with open(cert_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()


def create_ssl_context(cert_path: str, key_path: str) -> ssl.SSLContext:
    """Create an SSL context for the aiohttp server."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert_path, key_path)
    return ctx


# ── Rate Limiter ──────────────────────────────────────────────────────────────

class RateLimiter:
    """Per-IP sliding-window rate limiter."""

    def __init__(self, general_limit: int = 60, login_limit: int = 5, window: int = 60):
        self.general_limit = general_limit
        self.login_limit = login_limit
        self.window = window
        self._requests = defaultdict(list)     # ip -> [timestamps]
        self._login_attempts = defaultdict(list)  # ip -> [timestamps]

    def _clean(self, timestamps: list) -> list:
        cutoff = time.time() - self.window
        return [t for t in timestamps if t > cutoff]

    def check_general(self, ip: str) -> bool:
        """Returns True if request is allowed, False if rate-limited."""
        self._requests[ip] = self._clean(self._requests[ip])
        if len(self._requests[ip]) >= self.general_limit:
            return False
        self._requests[ip].append(time.time())
        return True

    def check_login(self, ip: str) -> bool:
        """Returns True if login attempt is allowed, False if rate-limited."""
        self._login_attempts[ip] = self._clean(self._login_attempts[ip])
        if len(self._login_attempts[ip]) >= self.login_limit:
            return False
        self._login_attempts[ip].append(time.time())
        return True

    def retry_after(self, ip: str, is_login: bool = False) -> int:
        """Seconds until the oldest request in the window expires."""
        timestamps = self._login_attempts[ip] if is_login else self._requests[ip]
        if not timestamps:
            return 0
        oldest = min(timestamps)
        return max(1, int(self.window - (time.time() - oldest)))


# ── Auth Middleware ───────────────────────────────────────────────────────────

EXEMPT_ROUTES = {
    ('GET', '/'),
    ('POST', '/login'),
    ('GET', '/api/check_setup'),
    ('POST', '/api/setup'),
}


def create_auth_middleware(password_hash: str, jwt_secret: str, rate_limiter: RateLimiter):
    """Create aiohttp middleware that enforces JWT auth and rate limiting on all /api/* routes."""

    @web.middleware
    async def auth_middleware(request, handler):
        method = request.method
        path = request.path

        # Get client IP
        ip = request.remote or '127.0.0.1'
        peername = request.transport.get_extra_info('peername')
        if peername:
            ip = peername[0]

        # Exempt routes skip auth (but still rate-limited)
        is_exempt = (method, path) in EXEMPT_ROUTES

        # Rate limiting
        if path == '/login' and method == 'POST':
            if not rate_limiter.check_login(ip):
                retry = rate_limiter.retry_after(ip, is_login=True)
                return web.json_response(
                    {'error': 'Too many login attempts. Try again later.'},
                    status=429,
                    headers={'Retry-After': str(retry)}
                )
        elif path.startswith('/api/'):
            if not rate_limiter.check_general(ip):
                retry = rate_limiter.retry_after(ip)
                return web.json_response(
                    {'error': 'Rate limit exceeded.'},
                    status=429,
                    headers={'Retry-After': str(retry)}
                )

        # Skip auth for exempt routes and WebSocket (WS auth handled in handler)
        if is_exempt or path == '/stream':
            return await handler(request)

        # Require auth for all /api/* routes
        if path.startswith('/api/'):
            auth_header = request.headers.get('Authorization', '')
            token = None

            if auth_header.startswith('Bearer '):
                token = auth_header[7:]
            else:
                # Also check query param for backward compatibility
                token = request.query.get('token')

            if not token:
                return web.json_response({'error': 'Unauthorized'}, status=401)

            # Accept either JWT or legacy password hash
            if token == password_hash:
                pass  # Legacy token — valid
            elif not verify_jwt(token, jwt_secret):
                return web.json_response({'error': 'Unauthorized'}, status=401)

        return await handler(request)

    return auth_middleware


# ── CORS Middleware ───────────────────────────────────────────────────────────

def create_cors_middleware(allowed_origins: list):
    """Create aiohttp middleware that adds CORS headers."""

    @web.middleware
    async def cors_middleware(request, handler):
        origin = request.headers.get('Origin', '')

        # Handle preflight
        if request.method == 'OPTIONS':
            resp = web.Response(status=204)
        else:
            resp = await handler(request)

        # Set CORS headers if origin is allowed
        if allowed_origins and origin:
            if origin in allowed_origins or '*' in allowed_origins:
                resp.headers['Access-Control-Allow-Origin'] = origin
                resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
                resp.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
                resp.headers['Access-Control-Max-Age'] = '3600'
        elif not allowed_origins:
            # No whitelist configured — allow same-origin only (no header = browser blocks)
            pass

        return resp

    return cors_middleware


# ── QR Code Pairing ──────────────────────────────────────────────────────────

def generate_pairing_qr(host: str, port: int, cert_fingerprint: str = '') -> bytes:
    """Generate a QR code PNG containing pairing info for the mobile app.

    Returns PNG bytes, or None if qrcode library isn't available.
    """
    try:
        import qrcode
        from io import BytesIO

        pairing_data = json.dumps({
            "host": host,
            "port": port,
            "fingerprint": cert_fingerprint,
            "app": "galactic-ai"
        }, separators=(',', ':'))

        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
        qr.add_data(pairing_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#00f3ff", back_color="#04050d")

        buf = BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    except ImportError:
        # qrcode not installed — return a simple JSON response instead
        return None
