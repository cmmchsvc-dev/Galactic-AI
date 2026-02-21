# Galactic AI - Gmail Bridge
# IMAP/SMTP integration for reading and sending email via Gmail App Passwords
import asyncio
import email
import email.header
import email.utils
import imaplib
import smtplib
import ssl
import json
import os
import time
import traceback
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class GmailBridge:
    """Gmail integration for Galactic AI -- polls inbox, sends email, searches messages."""

    IMAP_HOST = "imap.gmail.com"
    IMAP_PORT = 993
    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 587

    def __init__(self, core):
        self.core = core
        self.config = core.config.get('gmail', {})
        self.email_address = self.config.get('email', '')
        self.app_password = self.config.get('app_password', '')
        self.check_interval = int(self.config.get('check_interval', 60))
        self.notify_telegram = self.config.get('notify_telegram', True)
        self.running = True
        self._seen_uids: set[str] = set()
        self._imap: imaplib.IMAP4_SSL | None = None
        self._last_connect_attempt = 0.0

    # ── IMAP connection management ────────────────────────────────────────

    def _imap_connect(self) -> imaplib.IMAP4_SSL:
        """Open (or reuse) an authenticated IMAP connection."""
        if self._imap is not None:
            try:
                self._imap.noop()
                return self._imap
            except Exception:
                # Stale connection -- reconnect
                try:
                    self._imap.logout()
                except Exception:
                    pass
                self._imap = None

        ctx = ssl.create_default_context()
        conn = imaplib.IMAP4_SSL(self.IMAP_HOST, self.IMAP_PORT, ssl_context=ctx)
        conn.login(self.email_address, self.app_password)
        self._imap = conn
        return conn

    def _imap_disconnect(self):
        if self._imap is not None:
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _decode_header(raw: str) -> str:
        """Decode RFC 2047 encoded header value into a plain string."""
        if not raw:
            return ""
        parts = email.header.decode_header(raw)
        decoded = []
        for fragment, charset in parts:
            if isinstance(fragment, bytes):
                decoded.append(fragment.decode(charset or 'utf-8', errors='replace'))
            else:
                decoded.append(fragment)
        return " ".join(decoded)

    @staticmethod
    def _extract_body(msg: email.message.Message) -> str:
        """Extract the plain-text body from an email message (multipart-aware)."""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))
                if content_type == "text/plain" and "attachment" not in disposition:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        return payload.decode(charset, errors='replace')
            # Fallback: try text/html if no plain text
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        return f"[HTML]\n{payload.decode(charset, errors='replace')}"
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or 'utf-8'
                return payload.decode(charset, errors='replace')
        return "[No readable body]"

    def _parse_message(self, msg_data: bytes, uid: str = "") -> dict:
        """Parse raw email bytes into a structured dict."""
        msg = email.message_from_bytes(msg_data)
        subject = self._decode_header(msg.get("Subject", ""))
        from_addr = self._decode_header(msg.get("From", ""))
        to_addr = self._decode_header(msg.get("To", ""))
        date_str = msg.get("Date", "")
        message_id = msg.get("Message-ID", "")
        body = self._extract_body(msg)

        # Collect attachment filenames
        attachments = []
        if msg.is_multipart():
            for part in msg.walk():
                filename = part.get_filename()
                if filename:
                    attachments.append(self._decode_header(filename))

        return {
            "uid": uid,
            "message_id": message_id,
            "from": from_addr,
            "to": to_addr,
            "subject": subject,
            "date": date_str,
            "body": body[:10000],  # Cap body to prevent context overflows
            "attachments": attachments,
            "has_attachments": len(attachments) > 0,
        }

    # ── Core Features ─────────────────────────────────────────────────────

    async def check_inbox(self) -> list[dict]:
        """Poll for new unread emails via IMAP. Returns list of new message dicts."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._check_inbox_sync)

    def _check_inbox_sync(self) -> list[dict]:
        """Synchronous inbox check (run in executor to avoid blocking the event loop)."""
        new_messages = []
        try:
            conn = self._imap_connect()
            conn.select("INBOX")
            status, data = conn.search(None, "UNSEEN")
            if status != "OK":
                return []

            uids = data[0].split()
            for uid_bytes in uids:
                uid = uid_bytes.decode()
                if uid in self._seen_uids:
                    continue

                status, msg_data = conn.fetch(uid_bytes, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue

                raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
                if not isinstance(raw, bytes):
                    continue

                parsed = self._parse_message(raw, uid=uid)
                new_messages.append(parsed)
                self._seen_uids.add(uid)

        except Exception as e:
            # Force reconnect on next poll
            self._imap = None
            raise RuntimeError(f"IMAP check_inbox failed: {e}") from e

        return new_messages

    async def send_email(self, to: str, subject: str, body: str, html: bool = False) -> str:
        """Send an email via SMTP with App Password authentication."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._send_email_sync, to, subject, body, html)

    def _send_email_sync(self, to: str, subject: str, body: str, html: bool = False) -> str:
        """Synchronous SMTP send (run in executor)."""
        try:
            msg = MIMEMultipart("alternative") if html else MIMEText(body, "plain")
            if html:
                msg.attach(MIMEText(body, "plain"))
                msg.attach(MIMEText(body, "html"))

            msg["From"] = self.email_address
            msg["To"] = to
            msg["Subject"] = subject
            msg["Date"] = email.utils.formatdate(localtime=True)

            with smtplib.SMTP(self.SMTP_HOST, self.SMTP_PORT) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(self.email_address, self.app_password)
                server.sendmail(self.email_address, [to], msg.as_string())

            return f"Email sent to {to}: \"{subject}\""
        except Exception as e:
            return f"SMTP send failed: {e}"

    async def read_email(self, msg_uid: str) -> dict:
        """Fetch a specific email by UID."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._read_email_sync, msg_uid)

    def _read_email_sync(self, msg_uid: str) -> dict:
        """Synchronous single-message fetch."""
        try:
            conn = self._imap_connect()
            conn.select("INBOX")
            status, msg_data = conn.fetch(msg_uid.encode(), "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                return {"error": f"Message UID {msg_uid} not found"}
            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
            if not isinstance(raw, bytes):
                return {"error": "Could not read message data"}
            return self._parse_message(raw, uid=msg_uid)
        except Exception as e:
            self._imap = None
            return {"error": f"Failed to read email: {e}"}

    async def search_emails(self, query: str, folder: str = "INBOX", limit: int = 20) -> list[dict]:
        """Search emails using IMAP search criteria.

        The query can be:
        - A simple string: searches Subject and From fields
        - IMAP search syntax: e.g. 'FROM "alice@example.com"', 'SINCE "01-Jan-2025"'
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._search_emails_sync, query, folder, limit)

    def _search_emails_sync(self, query: str, folder: str = "INBOX", limit: int = 20) -> list[dict]:
        """Synchronous email search."""
        results = []
        try:
            conn = self._imap_connect()
            conn.select(folder, readonly=True)

            # Detect if the user passed raw IMAP search syntax
            imap_keywords = {"FROM", "TO", "SUBJECT", "SINCE", "BEFORE", "ON",
                             "SEEN", "UNSEEN", "FLAGGED", "ALL", "BODY", "TEXT",
                             "HEADER", "LARGER", "SMALLER", "ANSWERED", "DELETED"}
            first_word = query.strip().split()[0].upper() if query.strip() else ""

            if first_word in imap_keywords:
                search_criteria = query
            else:
                # Smart search: match subject OR from
                safe = query.replace('"', '\\"')
                search_criteria = f'(OR SUBJECT "{safe}" FROM "{safe}")'

            status, data = conn.search(None, search_criteria)
            if status != "OK":
                return [{"error": f"IMAP search failed: {status}"}]

            uids = data[0].split()
            # Take the most recent messages (last N UIDs)
            uids = uids[-limit:]
            uids.reverse()  # newest first

            for uid_bytes in uids:
                uid = uid_bytes.decode()
                # Fetch headers + a small preview (BODY.PEEK to avoid marking as read)
                status, msg_data = conn.fetch(uid_bytes, "(BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.2000>)")
                if status != "OK" or not msg_data:
                    continue

                # Reconstruct enough of the message for parsing
                raw_parts = []
                for part in msg_data:
                    if isinstance(part, tuple) and isinstance(part[1], bytes):
                        raw_parts.append(part[1])

                raw = b"\r\n".join(raw_parts) if raw_parts else b""
                if not raw:
                    continue

                parsed = self._parse_message(raw, uid=uid)
                # Truncate body for search results (just a preview)
                parsed["body"] = parsed["body"][:500]
                results.append(parsed)

        except Exception as e:
            self._imap = None
            return [{"error": f"Search failed: {e}"}]

        return results

    async def list_recent_emails(self, count: int = 10, folder: str = "INBOX") -> list[dict]:
        """List the N most recent emails (read or unread)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._list_recent_sync, count, folder)

    def _list_recent_sync(self, count: int = 10, folder: str = "INBOX") -> list[dict]:
        """Synchronous recent-email listing."""
        results = []
        try:
            conn = self._imap_connect()
            conn.select(folder, readonly=True)
            status, data = conn.search(None, "ALL")
            if status != "OK":
                return [{"error": f"IMAP search failed: {status}"}]

            uids = data[0].split()
            uids = uids[-count:]  # last N
            uids.reverse()  # newest first

            for uid_bytes in uids:
                uid = uid_bytes.decode()
                status, msg_data = conn.fetch(uid_bytes, "(BODY.PEEK[HEADER])")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue

                raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
                if not isinstance(raw, bytes):
                    continue

                msg = email.message_from_bytes(raw)
                subject = self._decode_header(msg.get("Subject", ""))
                from_addr = self._decode_header(msg.get("From", ""))
                date_str = msg.get("Date", "")

                results.append({
                    "uid": uid,
                    "from": from_addr,
                    "subject": subject,
                    "date": date_str,
                })

        except Exception as e:
            self._imap = None
            return [{"error": f"List recent failed: {e}"}]

        return results

    # ── Background Polling Loop ───────────────────────────────────────────

    async def poll_loop(self):
        """Background loop that checks for new emails and dispatches notifications."""
        await self.core.log("[Gmail] Bridge online -- polling inbox...", priority=1)

        # Seed the seen set on startup so we don't re-notify old unreads
        try:
            await self._seed_seen_uids()
        except Exception as e:
            await self.core.log(f"[Gmail] Seed failed (will retry): {e}", priority=2)

        while self.running and self.core.running:
            try:
                new_messages = await self.check_inbox()
                for msg in new_messages:
                    await self._on_new_email(msg)
            except Exception as e:
                await self.core.log(f"[Gmail] Poll error: {e}", priority=2)
                self._imap_disconnect()

            await asyncio.sleep(self.check_interval)

        self._imap_disconnect()
        await self.core.log("[Gmail] Bridge stopped.", priority=2)

    async def _seed_seen_uids(self):
        """Mark all current UNSEEN UIDs as 'seen' so we only notify on truly new arrivals."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._seed_seen_uids_sync)

    def _seed_seen_uids_sync(self):
        conn = self._imap_connect()
        conn.select("INBOX")
        status, data = conn.search(None, "UNSEEN")
        if status == "OK" and data[0]:
            for uid_bytes in data[0].split():
                self._seen_uids.add(uid_bytes.decode())

    async def _on_new_email(self, msg: dict):
        """Handle a newly detected email -- log + notify."""
        sender = msg.get("from", "Unknown")
        subject = msg.get("subject", "(no subject)")
        preview = msg.get("body", "")[:200]

        await self.core.log(f"[Gmail] New email from {sender}: {subject}", priority=1)

        # Notify Control Deck (Web UI)
        try:
            await self.core.relay.emit(2, "gmail_new_email", {
                "from": sender,
                "subject": subject,
                "preview": preview,
                "uid": msg.get("uid", ""),
                "date": msg.get("date", ""),
            })
        except Exception:
            pass

        # Notify Telegram (if enabled and bridge exists)
        if self.notify_telegram and hasattr(self.core, 'telegram'):
            try:
                admin_chat_id = self.core.config.get('telegram', {}).get('admin_chat_id', '')
                if admin_chat_id:
                    tg_text = (
                        f"*New Email*\n"
                        f"*From:* `{sender}`\n"
                        f"*Subject:* `{subject}`\n"
                        f"*Preview:* {preview[:300]}"
                    )
                    await self.core.telegram.send_message(admin_chat_id, tg_text)
            except Exception as e:
                await self.core.log(f"[Gmail] Telegram notification failed: {e}", priority=3)

    # ── Gateway Tool Wrappers ─────────────────────────────────────────────
    # These are called by the LLM tool registry in gateway_v2.py

    async def tool_send_email(self, args: dict) -> str:
        to = args.get("to", "")
        subject = args.get("subject", "")
        body = args.get("body", "")
        html = args.get("html", False)
        if not to:
            return "[ERROR] 'to' address is required."
        if not subject:
            return "[ERROR] 'subject' is required."
        result = await self.send_email(to, subject, body, html=html)
        await self.core.log(f"[Gmail] Tool: send_email -> {to}: {subject}", priority=2)
        return result

    async def tool_read_email(self, args: dict) -> str:
        uid = args.get("uid", "")
        if not uid:
            return "[ERROR] 'uid' is required. Use list_recent_emails or search_emails to find UIDs."
        msg = await self.read_email(str(uid))
        if "error" in msg:
            return f"[ERROR] {msg['error']}"
        return json.dumps(msg, indent=2, ensure_ascii=False)

    async def tool_search_emails(self, args: dict) -> str:
        query = args.get("query", "")
        folder = args.get("folder", "INBOX")
        limit = int(args.get("limit", 20))
        if not query:
            return "[ERROR] 'query' is required."
        results = await self.search_emails(query, folder=folder, limit=limit)
        if results and "error" in results[0]:
            return f"[ERROR] {results[0]['error']}"
        return json.dumps(results, indent=2, ensure_ascii=False)

    async def tool_list_recent_emails(self, args: dict) -> str:
        count = int(args.get("count", 10))
        folder = args.get("folder", "INBOX")
        results = await self.list_recent_emails(count=count, folder=folder)
        if results and "error" in results[0]:
            return f"[ERROR] {results[0]['error']}"
        return json.dumps(results, indent=2, ensure_ascii=False)

    # ── Tool Definitions (for gateway_v2.py registration) ─────────────────

    def get_tool_definitions(self) -> dict:
        """Return tool definitions dict matching the gateway_v2.py tools format."""
        return {
            "send_email": {
                "description": "Send an email via Gmail. Requires 'to', 'subject', and 'body'. Uses the configured Gmail account with App Password authentication.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to":      {"type": "string", "description": "Recipient email address"},
                        "subject": {"type": "string", "description": "Email subject line"},
                        "body":    {"type": "string", "description": "Email body text"},
                        "html":    {"type": "boolean", "description": "Send body as HTML (default: false)"},
                    },
                    "required": ["to", "subject", "body"]
                },
                "fn": self.tool_send_email
            },
            "read_email": {
                "description": "Read a specific email by its UID. Returns full message with from, to, subject, date, body, and attachment list. Use list_recent_emails or search_emails first to find UIDs.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "uid": {"type": "string", "description": "Email UID from list_recent_emails or search_emails results"},
                    },
                    "required": ["uid"]
                },
                "fn": self.tool_read_email
            },
            "search_emails": {
                "description": "Search emails in Gmail. Accepts a simple text query (searches Subject and From) or raw IMAP syntax (e.g. 'FROM \"alice@example.com\"', 'SINCE \"01-Jan-2025\"', 'UNSEEN'). Returns matching messages with previews.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query":  {"type": "string", "description": "Search query (text or IMAP syntax)"},
                        "folder": {"type": "string", "description": "IMAP folder to search (default: INBOX)"},
                        "limit":  {"type": "integer", "description": "Max results to return (default: 20)"},
                    },
                    "required": ["query"]
                },
                "fn": self.tool_search_emails
            },
            "list_recent_emails": {
                "description": "List the most recent emails in the inbox (or another folder). Returns subject, from, date, and UID for each message. Use read_email with a UID to see the full message.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "count":  {"type": "integer", "description": "Number of recent emails to list (default: 10)"},
                        "folder": {"type": "string", "description": "IMAP folder (default: INBOX). Others: SENT, DRAFTS, TRASH, etc."},
                    },
                    "required": []
                },
                "fn": self.tool_list_recent_emails
            },
        }
