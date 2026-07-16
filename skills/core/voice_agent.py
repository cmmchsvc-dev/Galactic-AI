import asyncio
import threading
import traceback
import time
import pyttsx3
import speech_recognition as sr
from skills.base import GalacticSkill

class VoiceAgentSkill(GalacticSkill):
    skill_name = "voice_agent"
    display_name = "Voice Agent"
    version = "1.0.0"
    author = "cmmchsvc"
    description = "True Jarvis Experience: Wake-word listening and local TTS spoken responses."
    category = "voice"
    icon = "🎙️"
    
    def __init__(self, core):
        super().__init__(core)
        self.listening = False
        self.awaiting_command = False
        self.processing_audio = False
        self.stop_listening_fn = None
        self.recognizer = sr.Recognizer()
        self.recognizer.pause_threshold = 1.0  # Wait for 1.0 second of silence before cutting off
        self.recognizer.non_speaking_duration = 0.5 # Ensure it captures the trailing silence
        self.recognizer.dynamic_energy_threshold = True # Allow adjusting to room ambient noise level
        
        # We don't init the mic here because it can block or cause issues before start
        self.mic = None
        self.chatterbox_model = None
        
        self.tts_lock = threading.Lock()
        
    async def run(self):
        """Starts the background listening loop."""
        if self.listening: return
        if not self.core.config.get('voice_agent', {}).get('wake_word_enabled', True):
            await self.core.log("🙉 Voice Agent: wake-word listening is OFF — mic stays closed. Toggle it in the Control Deck (👂 button or Settings → Voice).", priority=3)
            return
        self.listening = True
        # Generation counter: a rapid OFF→ON toggle spawns a new thread before the
        # old one notices; stale threads see a newer gen and exit instead of doubling up.
        self._listen_gen = getattr(self, '_listen_gen', 0) + 1
        gen = self._listen_gen

        def _start_listening():
            self._first_start = True
            # Warm the local STT model now (blocking here is fine — we're in a
            # background thread) so the first wake word isn't lost to a cold load.
            stt_backend = "cloud Google"
            va_cfg = self.core.config.get('voice_agent', {})
            if va_cfg.get('local_stt', True):
                try:
                    import local_stt
                    local_stt.configure(va_cfg.get('stt_model'))
                    if local_stt.available():
                        stt_backend = f"local faster-whisper ({local_stt.describe()})"
                except Exception:
                    pass
            while self.listening and self._listen_gen == gen:
                try:
                    self.mic = sr.Microphone()
                    with self.mic as source:
                        self.recognizer.adjust_for_ambient_noise(source, duration=1)

                        if getattr(self, '_first_start', True):
                            # Log success to the event loop
                            asyncio.run_coroutine_threadsafe(
                                self.core.log(f"🎙️ Voice Agent listening for 'Computer' / 'Chong'... [STT: {stt_backend}]", priority=3),
                                self.core.loop
                            )
                            # Say a quick hello
                            self.speak("Voice interface initialized.")
                            self._first_start = False
                            
                        # Continuous listening loop
                        # NOTE: we keep listening while TTS plays so the user can
                        # barge in with a wake word to interrupt (see _audio_callback).
                        while self.listening and self._listen_gen == gen:
                            try:
                                if getattr(self, 'processing_audio', False):
                                    time.sleep(0.1)
                                    continue
                                audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=None)
                                if self.listening and self._listen_gen == gen and not getattr(self, 'processing_audio', False):
                                    self.processing_audio = True
                                    threading.Thread(
                                        target=self._run_audio_callback_safe,
                                        args=(self.recognizer, audio),
                                        daemon=True
                                    ).start()
                            except sr.WaitTimeoutError:
                                pass
                            except Exception as e:
                                if self.listening:
                                    asyncio.run_coroutine_threadsafe(
                                        self.core.log(f"⚠️ Voice stream error (device changed?). Reconnecting... ({e})", priority=2),
                                        self.core.loop
                                    )
                                break # break the inner loop to re-init the microphone
                except Exception as e:
                    if self.listening:
                        asyncio.run_coroutine_threadsafe(
                            self.core.log(f"❌ Voice Agent mic error, retrying in 3s: {e}", priority=1),
                            self.core.loop
                        )
                        time.sleep(3)

        # Start the mic init in a background thread so it doesn't block the startup
        threading.Thread(target=_start_listening, daemon=True).start()

    def stop(self):
        self.listening = False
        self.awaiting_command = False
        asyncio.run_coroutine_threadsafe(
            self.core.log("🎙️ Voice Agent stopped — mic released.", priority=2),
            self.core.loop
        )

    def _run_audio_callback_safe(self, recognizer, audio):
        try:
            self._audio_callback(recognizer, audio)
        finally:
            self.processing_audio = False

    def _transcribe(self, recognizer, audio):
        """Local-first STT. Uses faster-whisper when available (audio stays on
        this machine); falls back to cloud Google only if local can't run."""
        use_local = self.core.config.get('voice_agent', {}).get('local_stt', True)
        if use_local:
            try:
                import local_stt
                if local_stt.available():
                    pcm16 = audio.get_raw_data(convert_rate=16000, convert_width=2)
                    text = local_stt.transcribe_pcm16(pcm16, sample_rate=16000)
                    if text is not None:
                        if not text:
                            # Local model ran but heard nothing intelligible —
                            # mirror recognize_google's "empty" contract.
                            raise sr.UnknownValueError()
                        return text
            except sr.UnknownValueError:
                raise
            except Exception:
                pass  # fall through to cloud
        return recognizer.recognize_google(audio)

    def _audio_callback(self, recognizer, audio):
        try:
            text = self._transcribe(recognizer, audio)
            text_lower = text.lower()

            # Wake word detection
            wake_words = ["computer", "chong", "peter", "puter", "commuter"]
            is_wake_word = any(w in text_lower for w in wake_words)

            # ── Barge-in: audio heard while TTS is playing ──────────────
            if getattr(self, 'is_speaking', False):
                if not is_wake_word:
                    return  # ignore non-wake chatter (incl. our own voice) during playback
                # Self-echo guard: if what we "heard" is mostly words we're
                # currently SAYING (e.g. the TTS said "I'm Chong"), ignore it.
                # Token overlap instead of substring — transcription never
                # matches the TTS text verbatim.
                import re as _re
                spoken = (getattr(self, '_current_tts_text', '') or '').lower()
                spoken_tokens = set(_re.sub(r'[^a-z0-9 ]+', ' ', spoken).split())
                heard_tokens = [t for t in _re.sub(r'[^a-z0-9 ]+', ' ', text_lower).split() if t]
                if spoken_tokens and heard_tokens:
                    overlap = sum(1 for t in heard_tokens if t in spoken_tokens) / len(heard_tokens)
                    if overlap >= 0.8:
                        return
                # Real interruption: kill playback and process the command
                self._abort_speaking = True
                self._current_speak_run = getattr(self, '_current_speak_run', 0) + 1
                asyncio.run_coroutine_threadsafe(
                    self.core.log("🎙️ Barge-in: playback interrupted by wake word.", priority=2),
                    self.core.loop
                )

            if self.awaiting_command or is_wake_word:
                if is_wake_word:
                    command = text_lower
                    for w in wake_words:
                        command = command.replace(w, "")
                    command = command.strip()
                else:
                    command = text_lower.strip()
                    
                if not command:
                    # They just said the wake word and nothing else
                    self.awaiting_command = True
                    self.speak("Yes?")
                    
                    # 10-second timeout so it doesn't get stuck listening forever
                    def timeout_listener():
                        import time
                        time.sleep(10)
                        self.awaiting_command = False
                    
                    import threading
                    threading.Thread(target=timeout_listener, daemon=True).start()
                    return
                
                # We got a command, reset the flag
                self.awaiting_command = False
                
                # Check for engine swap command
                if command.startswith("switch voice engine to"):
                    engine_name = command.replace("switch voice engine to", "").strip()
                    if "edge" in engine_name:
                        self.core.config.setdefault('voice_agent', {})['engine'] = 'edge-tts'
                        self.speak("Voice engine switched to Microsoft Edge.")
                    elif "piper" in engine_name:
                        self.core.config.setdefault('voice_agent', {})['engine'] = 'piper'
                        self.speak("Voice engine switched to Piper.")
                    elif "fallback" in engine_name or "pyttsx" in engine_name:
                        self.core.config.setdefault('voice_agent', {})['engine'] = 'pyttsx3'
                        self.speak("Voice engine switched to standard fallback.")
                    elif "eleven" in engine_name:
                        self.core.config.setdefault('voice_agent', {})['engine'] = 'elevenlabs'
                        self.speak("Voice engine switched to ElevenLabs.")
                    elif "xtts" in engine_name or "clone" in engine_name:
                        self.core.config.setdefault('voice_agent', {})['engine'] = 'xtts'
                        self.speak("Voice engine switched to XTTS Voice Cloning. Please place a voice_clone.wav file in the directory.")
                    else:
                        self.speak("I do not recognize that voice engine.")
                    return
                
                # Check for personality swap command
                import re
                m = re.search(r"(?:change|switch|swap)(?:\s+the)?\s+(?:personality|persona|character)\s+(?:to\s+)?([a-z0-9_ -]+)[.!]*", command, re.IGNORECASE)
                if m:
                    target_mode = m.group(1).strip().lower()
                    if 'homer' in target_mode: target_mode = 'homer'
                    elif 'generic' in target_mode: target_mode = 'generic'
                    elif 'byte' in target_mode or 'bite' in target_mode: target_mode = 'byte'
                    else: target_mode = target_mode.replace(" ", "_")
                    
                    pers = self.core.config.get('personality')
                    if not isinstance(pers, dict):
                        pers = {}
                        self.core.config['personality'] = pers
                    pers['mode'] = target_mode
                    try:
                        self.core.save_config()  # persists to the gitignored overlay
                    except Exception:
                        pass
                    
                    asyncio.run_coroutine_threadsafe(
                        self.core.log(f"🎙️ Intercepted command: Switched personality to {target_mode}", priority=2), 
                        self.core.loop
                    )
                    
                    if hasattr(self.core, 'gateway'):
                        from personality import GalacticPersonality
                        self.core.gateway.personality = GalacticPersonality(
                            self.core.config, self.core.config.get('paths', {}).get('workspace')
                        )
                    self.speak(f"Acknowledged. Personality matrix successfully swapped to {target_mode}.")
                    return
                
                asyncio.run_coroutine_threadsafe(
                    self.core.log(f"🎙️ [Voice Input]: {command}", priority=3), 
                    self.core.loop
                )
                if hasattr(self.core, 'relay'):
                    asyncio.run_coroutine_threadsafe(
                        self.core.relay.emit(3, "chat_from_voice", {"data": command}),
                        self.core.loop
                    )
                
                # Forward to gateway to process
                if hasattr(self.core, 'gateway'):
                    async def process_voice_command():
                        try:
                            # Screen Awareness Interception
                            img_list = None
                            cmd_lower = command.lower()
                            if "look at my screen" in cmd_lower or "what is on my screen" in cmd_lower or "read my screen" in cmd_lower:
                                await self.core.log("👁️ Capturing screen for vision analysis...", priority=3)
                                # Fetch the Screen Awareness skill
                                screen_skill = next((s for s in self.core.skills if getattr(s, 'skill_name', '') == 'screen_awareness'), None)
                                if screen_skill:
                                    b64_img = await screen_skill._tool_take_screenshot({})
                                    if b64_img and not b64_img.startswith("[ERROR]"):
                                        img_list = [{"name": "screenshot.jpg", "mime": "image/jpeg", "b64": b64_img}]
                                        await self.core.log("✅ Screen captured and attached to prompt.", priority=5)
                                    else:
                                        await self.core.log(f"❌ Screen capture failed: {b64_img}", priority=1)
                                else:
                                    await self.core.log("❌ Screen Awareness skill not found.", priority=1)

                            response = await self.core.gateway.speak(command, images=img_list)
                            if response:
                                await self.core.log(f"[Core] {getattr(self.core.gateway.personality, 'display_name', self.core.gateway.personality.name)}: {response}", priority=2)
                                self.speak(response)
                        except Exception as e:
                            await self.core.log(f"🎙️ Gateway error processing voice command: {e}", priority=1)
                            
                    asyncio.run_coroutine_threadsafe(
                        process_voice_command(),
                        self.core.loop
                    )
            else:
                # Log what was heard for debugging/visibility
                asyncio.run_coroutine_threadsafe(
                    self.core.log(f"🎙️ [Voice Heard]: \"{text}\" (no wake word)", priority=3),
                    self.core.loop
                )
        except sr.UnknownValueError:
            asyncio.run_coroutine_threadsafe(
                self.core.log("🎙️ [Voice Input]: (audio detected but not intelligible)", priority=3),
                self.core.loop
            )
        except sr.RequestError as e:
            asyncio.run_coroutine_threadsafe(
                self.core.log(f"🎙️ Voice recognition error: {e}", priority=1),
                self.core.loop
            )
        except Exception as e:
            pass
            
    def speak(self, text):
        """Speaks the text in a background thread so we don't block the loop."""
        if not text: return
        self.is_speaking = True
        
        current_run = getattr(self, '_current_speak_run', 0) + 1
        self._current_speak_run = current_run
        
        # Clean up markdown/emoji/symbols via the shared sanitizer (same one
        # tts_engine applies) so cloning engines don't buzz or glitch.
        import tts_engine
        clean_text = tts_engine.sanitize_text(text)

        # Remember what we're saying so the barge-in echo guard can tell the
        # user's voice apart from our own TTS coming back through the mic.
        self._current_tts_text = clean_text

        self._abort_speaking = False
        
        def _run_speak():
            try:
                with self.tts_lock:
                    engine_choice = self.core.config.get('voice_agent', {}).get('engine', 'edge-tts').lower()
                    
                    import asyncio
                    import os
                    import pygame
                    import time
                    
                    def _play_audio_with_boost(path):
                        if not os.path.exists(path): return
                        try:
                            from pydub import AudioSegment
                            if path.endswith('.wav'):
                                audio = AudioSegment.from_wav(path)
                                audio = audio + 15  # Normal 15dB boost
                                audio.export(path, format="wav")
                            elif path.endswith('.mp3'):
                                audio = AudioSegment.from_mp3(path)
                                audio = audio + 15
                                audio.export(path, format="mp3")
                        except Exception as e:
                            pass
                        pygame.mixer.init()
                        pygame.mixer.music.load(path)
                        pygame.mixer.music.play()
                        while pygame.mixer.music.get_busy():
                            if getattr(self, '_abort_speaking', False) or getattr(self, '_current_speak_run', 0) != current_run:
                                pygame.mixer.music.stop()
                                break
                            pygame.time.Clock().tick(10)
                        pygame.mixer.quit()
                    
                    # ── Synthesis via the shared tts_engine ──────────────
                    engine_choice = self.core.config.get('voice_agent', {}).get('engine', 'edge-tts').lower()
                    voice_setting = self.core.config.get('elevenlabs', {}).get('voice', 'Aria')

                    if engine_choice != 'pyttsx3':
                        import tts_engine
                        result = tts_engine.synthesize(
                            clean_text, self.core.config,
                            engine=engine_choice, voice=voice_setting,
                            out_dir=os.getcwd(), basename='temp_speech')
                        # Skip playback if a newer utterance already superseded this one.
                        if getattr(self, '_abort_speaking', False) or getattr(self, '_current_speak_run', 0) != current_run:
                            return
                        if result.get('path'):
                            _play_audio_with_boost(result['path'])
                            return
                        asyncio.run_coroutine_threadsafe(
                            self.core.log(f"[Voice Error] {engine_choice} TTS failed: {result.get('error')} - using system voice.", priority=2),
                            self.core.loop
                        )

                    # Fallback: pyttsx3 (speaks directly, produces no file)
                    import pythoncom
                    import pyttsx3
                    pythoncom.CoInitialize()
                    engine = pyttsx3.init()
                    voices = engine.getProperty('voices')
                    for v in voices:
                        if "zira" in v.name.lower() or "female" in v.name.lower():
                            engine.setProperty('voice', v.id)
                            break
                    engine.setProperty('rate', 185)
                    engine.say(clean_text)
                    engine.runAndWait()
                    pythoncom.CoUninitialize()
                    
            except Exception as e:
                err_msg = f"[Voice Error] TTS Failed: {e}"
                print(err_msg)
                if hasattr(self.core, 'loop') and hasattr(self.core, 'log'):
                    self.core.loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(self.core.log(err_msg, priority=1))
                    )
            finally:
                self.is_speaking = False
            
        threading.Thread(target=_run_speak, daemon=True).start()

    def get_tools(self):
        return {
            "voice_speak": {
                "description": "Speak text aloud to the user.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to speak aloud."}
                    },
                    "required": ["text"]
                },
                "fn": self._tool_voice_speak
            }
        }
        
    async def _tool_voice_speak(self, args):
        text = args.get('text')
        self.speak(text)
        return f"[VOICE] Spoke: {text}"
