# Galactic-AI Mobile

**Android companion app for Galactic AI Automation Suite.**

Connect to your Galactic-AI Control Deck from anywhere — LAN or internet — with enterprise-grade security.

## Features

- Full Control Deck access (all 10 tabs: Chat, Tools, Plugins, Models, Browser, Memory, Status, Settings, Logs, Thinking)
- CRT scanline effects, glow levels, and the full cyberpunk theme
- QR code pairing — scan from PC Settings tab to connect instantly
- Voice I/O — hands-free speech-to-text and text-to-speech
- Biometric/PIN lock for app access
- TLS encryption with certificate pinning (TOFU)
- JWT authentication with 24-hour token expiry
- Auto-reconnect on network changes
- Hardware-accelerated WebView for smooth rendering

## Requirements

- Android 8.0+ (API 26)
- Galactic-AI v1.0.0+ running on PC with `remote_access: true` in config.yaml

## Building

1. Open this folder in Android Studio
2. Sync Gradle
3. Build > Generate Signed APK (or Build > Build APK for debug)

### Signing for release

```bash
keytool -genkey -v -keystore galactic-mobile.jks -keyalg RSA -keysize 4096 -validity 10000
```

Then configure the keystore in `app/build.gradle.kts` under `signingConfigs`.

## Connecting

### Method 1: QR Code (Recommended)
1. On your PC, open Galactic-AI Control Deck > Settings tab
2. Scroll to "Mobile App Pairing" section
3. On your phone, open Galactic-AI Mobile > tap "Scan QR Code"
4. Enter your passphrase and tap Connect

### Method 2: Manual
1. Find your PC's IP address (e.g., `ipconfig` on Windows)
2. Open Galactic-AI Mobile
3. Enter the IP, port (17789), and passphrase
4. Toggle HTTPS on and tap Connect

## Security

| Layer | Protection |
|-------|-----------|
| Transport | TLS 1.2+ with auto-generated certificates |
| Auth | JWT tokens (HMAC-SHA256, 24h expiry) |
| Storage | AES-256 encrypted (Android Keystore) |
| Cert Trust | TOFU with SHA-256 fingerprint pinning |
| App Access | Optional biometric/PIN authentication |

## License

Same as Galactic-AI — see root LICENSE file.
