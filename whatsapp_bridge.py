# Galactic AI - WhatsApp Bridge (Cloud API)
import asyncio
import hashlib
import hmac
import httpx
import json
import os
import tempfile
import time


class WhatsAppBridge:
    """WhatsApp Cloud API bridge for Galactic AI — mirrors TelegramBridge patterns."""

    def __init__(self, core):
        self.core = core
        self.config = core.config.get('whatsapp', {})
        self.phone_number_id = self.config.get('phone_number_id', '')
        self.access_token = self.config.get('access_token', '')
        self.verify_token = self.config.get('verify_token', '')
        self.webhook_secret = self.config.get('webhook_secret', '')
        self.api_version = self.config.get('api_version', 'v21.0')
        self.api_url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}"
        self.client = httpx.AsyncClient(timeout=60.0)
        self.start_time = time.time()
        self._processing = set()  # (phone, text) pairs currently in-flight — prevents duplicate sends
        self._seen_message_ids = set()  # WhatsApp message wamids already handled
        self._seen_max = 5000  # Trim threshold for _seen_message_ids
        self._component = "WhatsApp"

    async def _log(self, message, priority=3):
        """Route logs to the WhatsApp component log file."""
        await self.core.log(message, priority=priority, component=self._component)

    # ──────────────────────────────────────────────
    #  Webhook verification (GET) & incoming (POST)
    # ──────────────────────────────────────────────

    async def handle_verify(self, request):
        """GET /webhook/whatsapp — Meta webhook verification challenge."""
        mode = request.query.get('hub.mode', '')
        token = request.query.get('hub.verify_token', '')
        challenge = request.query.get('hub.challenge', '')

        if mode == 'subscribe' and token == self.verify_token:
            await self._log("[WhatsApp] Webhook verified successfully.", priority=1)
            from aiohttp import web
            return web.Response(text=challenge, content_type='text/plain')
        await self._log("[WhatsApp] Webhook verification failed — token mismatch.", priority=1)
        from aiohttp import web
        return web.Response(status=403, text='Forbidden')

    async def handle_incoming(self, request):
        """POST /webhook/whatsapp — receive incoming messages from Meta."""
        from aiohttp import web

        # ── Signature verification ──
        body_bytes = await request.read()
        if self.webhook_secret:
            sig_header = request.headers.get('X-Hub-Signature-256', '')
            if not self._verify_signature(body_bytes, sig_header):
                await self._log("[WhatsApp] Invalid webhook signature — dropping payload.", priority=1)
                return web.Response(status=403, text='Invalid signature')

        # Always respond 200 quickly so Meta doesn't retry
        try:
            payload = json.loads(body_bytes)
        except json.JSONDecodeError:
            return web.Response(status=200, text='OK')

        # Process asynchronously — don't block the webhook response
        asyncio.create_task(self._process_webhook_payload(payload))
        return web.Response(status=200, text='OK')

    def _verify_signature(self, body: bytes, signature_header: str) -> bool:
        """Verify X-Hub-Signature-256 from Meta."""
        if not signature_header:
            return False
        try:
            _, sig = signature_header.split('=', 1)
            expected = hmac.new(
                self.webhook_secret.encode('utf-8'),
                body,
                hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(sig, expected)
        except Exception:
            return False

    # ──────────────────────────────────────────────
    #  Webhook payload processing
    # ──────────────────────────────────────────────

    async def _process_webhook_payload(self, payload):
        """Parse the Cloud API webhook structure and route messages."""
        try:
            for entry in payload.get('entry', []):
                for change in entry.get('changes', []):
                    value = change.get('value', {})

                    # Handle message status updates (delivered, read, etc.)
                    if 'statuses' in value:
                        continue  # Ignore status updates

                    messages = value.get('messages', [])
                    for msg in messages:
                        await self._route_message(msg, value)
        except Exception as e:
            await self._log(f"[WhatsApp] Webhook processing error: {e}", priority=1)

    async def _route_message(self, msg, value):
        """Route an individual incoming WhatsApp message by type."""
        msg_id = msg.get('id', '')
        msg_type = msg.get('type', '')
        sender = msg.get('from', '')  # Phone number (e.g. '15551234567')

        # Dedup by message ID (WhatsApp may redeliver)
        if msg_id in self._seen_message_ids:
            return
        self._seen_message_ids.add(msg_id)
        if len(self._seen_message_ids) > self._seen_max:
            # Trim oldest half
            trim = list(self._seen_message_ids)[:self._seen_max // 2]
            for t in trim:
                self._seen_message_ids.discard(t)

        # Extract sender name from contacts array if available
        contacts = value.get('contacts', [])
        sender_name = ''
        if contacts:
            profile = contacts[0].get('profile', {})
            sender_name = profile.get('name', '')

        if msg_type == 'text':
            text = msg.get('text', {}).get('body', '')
            if text:
                await self._handle_text(sender, text, sender_name)

        elif msg_type == 'image':
            await self._handle_image(sender, msg, sender_name)

        elif msg_type in ('audio', 'voice'):
            # WhatsApp sends voice notes as type 'audio' with voice=true
            await self._handle_audio(sender, msg, sender_name)

        elif msg_type == 'document':
            await self._handle_document(sender, msg, sender_name)

        elif msg_type == 'location':
            loc = msg.get('location', {})
            lat = loc.get('latitude', '')
            lon = loc.get('longitude', '')
            text = f"[Location shared: {lat}, {lon}]"
            if loc.get('name'):
                text += f" — {loc['name']}"
            await self._handle_text(sender, text, sender_name)

        elif msg_type == 'contacts':
            # Forward as text summary
            shared = msg.get('contacts', [])
            parts = []
            for c in shared[:5]:
                name = c.get('name', {}).get('formatted_name', 'Unknown')
                phones = [p.get('phone', '') for p in c.get('phones', [])]
                parts.append(f"{name}: {', '.join(phones)}")
            text = "[Shared contacts]\n" + "\n".join(parts)
            await self._handle_text(sender, text, sender_name)

        else:
            await self._log(f"[WhatsApp] Unsupported message type '{msg_type}' from {sender}", priority=3)

    # ──────────────────────────────────────────────
    #  Message handlers (text, image, audio, doc)
    # ──────────────────────────────────────────────

    async def _handle_text(self, sender, text, sender_name=''):
        """Handle incoming text message — same dedup + process_and_respond pattern as Telegram."""
        key = (sender, text)
        if key in self._processing:
            return  # Already in-flight
        self._processing.add(key)
        await self.send_typing(sender)
        asyncio.create_task(self.process_and_respond(sender, text, sender_name=sender_name, _key=key))

    async def _handle_image(self, sender, msg, sender_name=''):
        """Download image from WhatsApp, analyze via vision, respond."""
        typing_task = None
        response = None
        try:
            typing_task = asyncio.create_task(self.keep_typing(sender))
            image_data = msg.get('image', {})
            media_id = image_data.get('id', '')
            caption = image_data.get('caption', '')
            mime_type = image_data.get('mime_type', 'image/jpeg')

            # Download media from WhatsApp
            raw = await self._download_media(media_id)
            if not raw:
                await self.send_message(sender, "Could not download that image. Please try again.")
                return

            await self._log(f"[WhatsApp] Image received from {sender} ({len(raw)} bytes)", priority=2)

            # Vision analysis
            import base64
            image_b64 = base64.b64encode(raw).decode('utf-8')
            vision_prompt = caption if caption else "Describe this image in detail. Include any text you see."
            vision_result = await self.core.gateway._analyze_image_b64(image_b64, mime_type, vision_prompt)

            if caption:
                speak_msg = f"[Image Analysis Result]\n{vision_result}\n\nUser's caption/question: {caption}"
            else:
                speak_msg = f"[Image Analysis Result]\n{vision_result}"

            response = await asyncio.wait_for(
                self.core.gateway.speak(speak_msg, chat_id=f"wa:{sender}"),
                timeout=self._get_speak_timeout()
            )
        except asyncio.TimeoutError:
            response = "Took too long analyzing that image. Please try again."
        except Exception as e:
            await self._log(f"[WhatsApp] Image error: {e}", priority=1)
            response = f"Error processing image: {str(e)}"
        finally:
            if typing_task and not typing_task.done():
                typing_task.cancel()
                try:
                    await typing_task
                except (asyncio.CancelledError, Exception):
                    pass
            # Relay to Web UI
            try:
                await self.core.relay.emit(2, "chat_from_whatsapp", {
                    "user": sender,
                    "data": f"[image] {caption or 'image'}",
                    "response": response,
                })
            except Exception:
                pass
            if response:
                await self.send_message(sender, response)

    async def _handle_audio(self, sender, msg, sender_name=''):
        """Download audio/voice from WhatsApp, transcribe, process, respond."""
        typing_task = None
        temp_file_path = None
        response = ""
        voice_reply_sent = False
        try:
            typing_task = asyncio.create_task(self.keep_typing(sender))
            audio_data = msg.get('audio', {})
            media_id = audio_data.get('id', '')
            mime_type = audio_data.get('mime_type', 'audio/ogg')

            # Download media
            raw = await self._download_media(media_id)
            if not raw:
                await self.send_message(sender, "Could not download that voice message. Please try again.")
                return

            # Determine file extension
            ext = '.ogg' if 'ogg' in mime_type else '.mp4' if 'mp4' in mime_type else '.mp3'

            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(raw)
                temp_file_path = tmp.name

            await self._log(f"[WhatsApp] Audio received from {sender} ({len(raw)} bytes, {mime_type})", priority=2)

            # Transcribe using the same pipeline as Telegram
            transcription = await self._transcribe_audio(temp_file_path)

            if not transcription:
                has_openai = bool(self.core.config.get('providers', {}).get('openai', {}).get('apiKey', ''))
                has_groq = bool(self.core.config.get('providers', {}).get('groq', {}).get('apiKey', ''))
                if not has_openai and not has_groq:
                    no_key_msg = (
                        "Voice received, but I can't transcribe it yet.\n\n"
                        "To enable voice messages, add an OpenAI or Groq API key in the Control Deck.\n\n"
                        "Groq transcription is free: https://console.groq.com/keys"
                    )
                else:
                    no_key_msg = "Got your voice message, but transcription failed. Please try again."
                voice_reply_sent = True
                await self.send_message(sender, no_key_msg)
                return

            full_msg = f"[Voice message from user]: {transcription}"
            response = await asyncio.wait_for(
                self.core.gateway.speak(full_msg, chat_id=f"wa:{sender}"),
                timeout=self._get_speak_timeout()
            )

            # Voice-in -> Voice-out (auto-TTS)
            if transcription and hasattr(self.core, 'gateway'):
                try:
                    tts_result = await self.core.gateway.tool_text_to_speech({
                        'text': response,
                        'voice': 'Byte'
                    })
                    if '[VOICE]' in str(tts_result):
                        import re
                        m = re.search(r'Generated speech.*?:\s*(.+\.mp3)', str(tts_result))
                        if m:
                            voice_path = m.group(1).strip()
                            if os.path.exists(voice_path):
                                await self.send_audio(sender, voice_path)
                                voice_reply_sent = True
                except Exception as e:
                    await self._log(f"[WhatsApp] Auto-TTS error: {e}", priority=2)

        except asyncio.TimeoutError:
            response = "Took too long processing that voice message. Please try again."
        except Exception as e:
            await self._log(f"[WhatsApp] Audio error: {e}", priority=1)
            response = f"Error processing voice message: {str(e)}"
        finally:
            if typing_task and not typing_task.done():
                typing_task.cancel()
                try:
                    await typing_task
                except (asyncio.CancelledError, Exception):
                    pass
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            # Relay to Web UI
            try:
                await self.core.relay.emit(2, "chat_from_whatsapp", {
                    "user": sender,
                    "data": "[voice message]",
                    "response": response,
                })
            except Exception:
                pass
            if not voice_reply_sent and response:
                await self.send_message(sender, response)

    async def _handle_document(self, sender, msg, sender_name=''):
        """Download document from WhatsApp, read text, pass to AI."""
        typing_task = None
        response = ""
        try:
            typing_task = asyncio.create_task(self.keep_typing(sender))
            doc_data = msg.get('document', {})
            media_id = doc_data.get('id', '')
            filename = doc_data.get('filename', 'unnamed')
            caption = doc_data.get('caption', '')

            raw = await self._download_media(media_id)
            if not raw:
                await self.send_message(sender, f"Could not download '{filename}'. Please try again.")
                return

            # Reject large files (5 MB)
            if len(raw) > 5 * 1024 * 1024:
                await self.send_message(sender, f"'{filename}' is too large ({len(raw) // 1024}KB). Max 5 MB.")
                return

            try:
                text_content = raw.decode('utf-8', errors='replace')
            except Exception:
                text_content = '[Binary file — could not decode as text]'

            if len(text_content) > 100000:
                text_content = text_content[:100000] + '\n\n... [truncated — file exceeds 100K characters]'

            full_msg = f"[Attached file: {filename}]\n---\n{text_content}\n---"
            if caption:
                full_msg += f"\n\n{caption}"

            await self._log(f"[WhatsApp] Document received from {sender}: {filename} ({len(raw)} bytes)", priority=2)

            response = await asyncio.wait_for(
                self.core.gateway.speak(full_msg, chat_id=f"wa:{sender}"),
                timeout=self._get_speak_timeout()
            )
        except asyncio.TimeoutError:
            response = "Took too long processing that file. Please try again."
        except Exception as e:
            await self._log(f"[WhatsApp] Document error: {e}", priority=1)
            response = f"Error processing document: {str(e)}"
        finally:
            if typing_task and not typing_task.done():
                typing_task.cancel()
                try:
                    await typing_task
                except (asyncio.CancelledError, Exception):
                    pass
            try:
                await self.core.relay.emit(2, "chat_from_whatsapp", {
                    "user": sender,
                    "data": f"[document] {filename}",
                    "response": response,
                })
            except Exception:
                pass
            if response:
                await self.send_message(sender, response)

    # ──────────────────────────────────────────────
    #  Core process_and_respond (mirrors Telegram)
    # ──────────────────────────────────────────────

    def _get_speak_timeout(self) -> float:
        """Return timeout scaled for active model provider (Ollama gets more time)."""
        wa_cfg = self.core.config.get('whatsapp', {})
        is_ollama = (
            hasattr(self.core, 'gateway') and
            self.core.gateway.llm.provider == 'ollama'
        )
        if is_ollama:
            return float(wa_cfg.get('ollama_timeout_seconds', 600))
        return float(wa_cfg.get('timeout_seconds', 120))

    async def process_and_respond(self, sender, text, sender_name='', _key=None):
        """Process a text message through the AI and send the response back via WhatsApp."""
        typing_task = None
        response = ""
        try:
            typing_task = asyncio.create_task(self.keep_typing(sender))
            response = await asyncio.wait_for(
                self.core.gateway.speak(text, chat_id=f"wa:{sender}"),
                timeout=self._get_speak_timeout()
            )
        except asyncio.TimeoutError:
            provider = getattr(self.core.gateway.llm, 'provider', 'unknown')
            model = getattr(self.core.gateway.llm, 'model', 'unknown')
            t = self._get_speak_timeout()
            await self._log(
                f"[WhatsApp] speak() timed out after {t:.0f}s for {sender} "
                f"(provider={provider}, model={model})",
                priority=1
            )
            response = (
                f"Timed out after {t:.0f}s using {provider}/{model}.\n\n"
                f"The model is running slowly. Try a simpler question."
            )
        except Exception as e:
            await self._log(f"[WhatsApp] Processing error: {e}", priority=1)
            response = f"Error: {str(e)}"
        finally:
            # Release dedup lock
            if _key:
                self._processing.discard(_key)
            # Cancel typing
            if typing_task and not typing_task.done():
                typing_task.cancel()
                try:
                    await typing_task
                except (asyncio.CancelledError, Exception):
                    pass
            # Relay to Web UI
            try:
                await self.core.relay.emit(2, "chat_from_whatsapp", {
                    "user": sender,
                    "name": sender_name,
                    "data": text,
                    "response": response,
                })
            except Exception:
                pass
            # Deliver TTS audio if generated
            voice_file = getattr(self.core.gateway, 'last_voice_file', None)
            if voice_file and os.path.exists(voice_file):
                try:
                    await self.send_audio(sender, voice_file)
                    self.core.gateway.last_voice_file = None
                except Exception as e:
                    await self._log(f"[WhatsApp] TTS delivery error: {e}", priority=1)
            # Deliver generated image if present
            image_file = getattr(self.core.gateway, 'last_image_file', None)
            if image_file and os.path.exists(image_file):
                try:
                    await self.send_image(sender, image_file)
                    self.core.gateway.last_image_file = None
                except Exception as e:
                    await self._log(f"[WhatsApp] Image delivery error: {e}", priority=1)
            # Send text response
            if response:
                try:
                    await self.send_message(sender, response)
                except Exception as e:
                    await self._log(f"[WhatsApp] Send error: {e}", priority=1)

    # ──────────────────────────────────────────────
    #  Outbound API — send_message, send_image, send_audio, send_typing
    # ──────────────────────────────────────────────

    async def send_message(self, to, text):
        """Send a text message via WhatsApp Cloud API."""
        try:
            # WhatsApp max message length is ~4096 chars; chunk if needed
            chunks = self._chunk_text(text, 4096)
            for chunk in chunks:
                payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": to,
                    "type": "text",
                    "text": {"preview_url": True, "body": chunk}
                }
                r = await self.client.post(
                    f"{self.api_url}/messages",
                    json=payload,
                    headers=self._auth_headers()
                )
                if r.status_code != 200:
                    await self._log(f"[WhatsApp] send_message failed ({r.status_code}): {r.text}", priority=1)
        except Exception as e:
            await self._log(f"[WhatsApp] send_message error: {e}", priority=1)

    async def send_image(self, to, image_path, caption=None):
        """Upload and send an image via WhatsApp Cloud API."""
        try:
            # Step 1: Upload media
            media_id = await self._upload_media(image_path, 'image/png')
            if not media_id:
                await self._log("[WhatsApp] Image upload failed — no media_id returned.", priority=1)
                return

            # Step 2: Send image message
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "image",
                "image": {"id": media_id}
            }
            if caption:
                payload["image"]["caption"] = caption[:1024]

            r = await self.client.post(
                f"{self.api_url}/messages",
                json=payload,
                headers=self._auth_headers()
            )
            if r.status_code != 200:
                await self._log(f"[WhatsApp] send_image failed ({r.status_code}): {r.text}", priority=1)
        except Exception as e:
            await self._log(f"[WhatsApp] send_image error: {e}", priority=1)

    async def send_audio(self, to, audio_path):
        """Upload and send an audio file via WhatsApp Cloud API."""
        try:
            # Determine mime type
            ext = os.path.splitext(audio_path)[1].lower()
            mime_map = {'.mp3': 'audio/mpeg', '.ogg': 'audio/ogg', '.m4a': 'audio/mp4',
                        '.wav': 'audio/wav', '.amr': 'audio/amr'}
            mime = mime_map.get(ext, 'audio/mpeg')

            media_id = await self._upload_media(audio_path, mime)
            if not media_id:
                await self._log("[WhatsApp] Audio upload failed — no media_id returned.", priority=1)
                return

            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "audio",
                "audio": {"id": media_id}
            }
            r = await self.client.post(
                f"{self.api_url}/messages",
                json=payload,
                headers=self._auth_headers()
            )
            if r.status_code != 200:
                await self._log(f"[WhatsApp] send_audio failed ({r.status_code}): {r.text}", priority=1)
        except Exception as e:
            await self._log(f"[WhatsApp] send_audio error: {e}", priority=1)

    async def send_typing(self, to):
        """Send typing indicator via WhatsApp Cloud API (composing status)."""
        try:
            # Cloud API v18+ supports sending a "typing" status to show composing indicator
            await self.client.post(
                f"{self.api_url}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "status": "typing",
                    "to": to,
                },
                headers=self._auth_headers()
            )
        except Exception:
            pass  # Non-critical — typing indicator is best-effort

    async def mark_as_read(self, message_id):
        """Mark a message as read (shows blue ticks)."""
        try:
            await self.client.post(
                f"{self.api_url}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": message_id,
                },
                headers=self._auth_headers()
            )
        except Exception:
            pass

    async def keep_typing(self, to):
        """Keep sending typing indicator every 4 seconds — mirrors TelegramBridge.keep_typing."""
        max_duration = int(self._get_speak_timeout()) + 30
        start_time = time.time()
        try:
            while True:
                if time.time() - start_time > max_duration:
                    await self._log(f"[WhatsApp] Typing indicator timeout after {max_duration}s", priority=1)
                    break
                await self.send_typing(to)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self._log(f"[WhatsApp] Typing indicator error: {e}", priority=1)

    # ──────────────────────────────────────────────
    #  Media helpers (download & upload)
    # ──────────────────────────────────────────────

    async def _download_media(self, media_id) -> bytes | None:
        """Download media from WhatsApp Cloud API (two-step: get URL, then download)."""
        try:
            # Step 1: Get download URL
            r = await self.client.get(
                f"https://graph.facebook.com/{self.api_version}/{media_id}",
                headers=self._auth_headers()
            )
            if r.status_code != 200:
                await self._log(f"[WhatsApp] Media metadata fetch failed: {r.text}", priority=1)
                return None
            media_url = r.json().get('url', '')
            if not media_url:
                return None

            # Step 2: Download binary
            r = await self.client.get(media_url, headers=self._auth_headers())
            if r.status_code == 200:
                return r.content
            await self._log(f"[WhatsApp] Media download failed ({r.status_code})", priority=1)
            return None
        except Exception as e:
            await self._log(f"[WhatsApp] Media download error: {e}", priority=1)
            return None

    async def _upload_media(self, file_path, mime_type) -> str | None:
        """Upload a file to WhatsApp Cloud API and return the media_id."""
        try:
            upload_url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/media"
            with open(file_path, 'rb') as f:
                r = await self.client.post(
                    upload_url,
                    headers={'Authorization': f'Bearer {self.access_token}'},
                    data={'messaging_product': 'whatsapp', 'type': mime_type},
                    files={'file': (os.path.basename(file_path), f, mime_type)}
                )
            if r.status_code == 200:
                return r.json().get('id')
            await self._log(f"[WhatsApp] Media upload failed ({r.status_code}): {r.text}", priority=1)
            return None
        except Exception as e:
            await self._log(f"[WhatsApp] Media upload error: {e}", priority=1)
            return None

    # ──────────────────────────────────────────────
    #  Audio transcription (reuse Telegram's pipeline)
    # ──────────────────────────────────────────────

    async def _transcribe_audio(self, audio_path):
        """Transcribe audio using OpenAI Whisper or Groq Whisper — same as TelegramBridge."""
        # Try OpenAI Whisper API
        openai_key = self.core.config.get('providers', {}).get('openai', {}).get('apiKey', '')
        if openai_key:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    with open(audio_path, 'rb') as f:
                        r = await client.post(
                            'https://api.openai.com/v1/audio/transcriptions',
                            headers={'Authorization': f'Bearer {openai_key}'},
                            files={'file': (os.path.basename(audio_path), f, 'audio/ogg')},
                            data={'model': 'whisper-1'}
                        )
                    if r.status_code == 200:
                        text = r.json().get('text', '').strip()
                        if text:
                            await self._log(f"[WhatsApp STT] Whisper: {text[:80]}...", priority=2)
                            return text
            except Exception as e:
                await self._log(f"[WhatsApp] Whisper STT error: {e}", priority=2)

        # Try Groq Whisper
        groq_key = self.core.config.get('providers', {}).get('groq', {}).get('apiKey', '')
        if groq_key:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    with open(audio_path, 'rb') as f:
                        r = await client.post(
                            'https://api.groq.com/openai/v1/audio/transcriptions',
                            headers={'Authorization': f'Bearer {groq_key}'},
                            files={'file': (os.path.basename(audio_path), f, 'audio/ogg')},
                            data={'model': 'whisper-large-v3'}
                        )
                    if r.status_code == 200:
                        text = r.json().get('text', '').strip()
                        if text:
                            await self._log(f"[WhatsApp STT] Groq Whisper: {text[:80]}...", priority=2)
                            return text
            except Exception as e:
                await self._log(f"[WhatsApp] Groq STT error: {e}", priority=2)

        return None

    # ──────────────────────────────────────────────
    #  Utilities
    # ──────────────────────────────────────────────

    def _auth_headers(self):
        """Standard authorization headers for WhatsApp Cloud API."""
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }

    @staticmethod
    def _chunk_text(text, max_len=4096):
        """Split text into chunks that fit WhatsApp's message length limit."""
        if not text:
            return ['']
        if len(text) <= max_len:
            return [text]
        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            # Try to split at a newline
            split_idx = text.rfind('\n', 0, max_len)
            if split_idx == -1:
                # No newline found — split at space
                split_idx = text.rfind(' ', 0, max_len)
            if split_idx == -1:
                split_idx = max_len
            chunks.append(text[:split_idx])
            text = text[split_idx:].lstrip()
        return chunks

    def is_configured(self) -> bool:
        """Return True if WhatsApp bridge has minimum viable configuration."""
        return bool(self.phone_number_id and self.access_token and self.verify_token)
