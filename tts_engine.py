"""
Galactic AI — Shared TTS Synthesis
==================================

Single source of truth for turning text into an audio FILE, across every
engine: fish-speech, elevenlabs, edge-tts, gtts, piper, chatterbox.

Callers own playback (this module never plays audio):
  - skills/core/voice_agent.py  → plays the file locally via pygame (barge-in)
  - web_deck.py /api/tts        → returns the file bytes to the browser

`synthesize()` is synchronous/blocking so it works identically from the
voice agent's worker thread and, via asyncio.to_thread(), from the async web
handler. It returns {'path', 'engine', 'error'}. pyttsx3 is intentionally NOT
here — it speaks directly with no file, so voice_agent keeps it as an inline
last-resort fallback.
"""

import os
import re
import threading

# ── Voice tables (shared) ────────────────────────────────────────────────────

EDGE_VOICE_MAP = {
    'Guy': 'en-US-GuyNeural', 'Aria': 'en-US-AriaNeural',
    'Jenny': 'en-US-JennyNeural', 'Steffan': 'en-US-SteffanNeural',
    'Byte': 'en-US-GuyNeural', 'Nova': 'en-US-AriaNeural',
}

ELEVEN_VOICE_IDS = {
    'Rachel': '21m00Tcm4TlvDq8ikWAM', 'Clyde': '2EiwWnXFnvU5JabPnv8n',
    'Domi': 'AZnzlk1XvdvUeBnXmlld', 'Dave': 'CYw3kZ02Hs0563khs1Fj',
    'Fin': 'D38z5RcWu1voky8WS1ja', 'Bella': 'EXAVITQu4vr4xnSDxMaL',
    'Antoni': 'ErXwobaYiN019PkySvjV', 'Thomas': 'GBv7mTt0atIp3Br8iCZE',
    'Charlie': 'IKne3meq5aSn9XLyUdCD', 'Emily': 'LcfcRzaPAbqL2j3906Fv',
    'Elli': 'MF3mGyEYCl7XYWbV9V6O', 'Callum': 'N2lVS1w4EtoT3dr4eOWO',
    'Patrick': 'ODq5zmih8GrVes37Dizd', 'Harry': 'SOYHLrjzK2X1ezoPC6cr',
    'Liam': 'TX3OmvHk7fSAd5W0E1lD', 'Dorothy': 'ThT5KcBeYPX3keUQqHPh',
    'Josh': 'TxGEqnHWrfWFTfGW9XjX', 'Arnold': 'VR6AewLTigWG4xSOukaG',
    'Charlotte': 'XB0fDUnXU5scGQ27QkEI', 'Matilda': 'XrExE9yKIg1WjnnlVkGX',
    'Matthew': 'Yko7PKHZNXotIFUBG7I9', 'James': 'ZQe5CZNOzWyzOMcZhk83',
    'Joseph': 'Zlb1dXrM653N07zXTqiV', 'Jeremy': 'bVMeCyTHy58xNoL34h3p',
    'Michael': 'flq6f7yk4E4fJM5XTYuZ', 'Ethan': 'g5CIjZEefAph4nQFvHAz',
    'Gigi': 'jBpfuIE2acCO8z3wKNLl', 'Freya': 'jsCqWAovK2Mfza80P6rG',
    'Grace': 'oWAxZDx7w5VEj9dCyTzz', 'Daniel': 'onwK4e9ZLuTAKqWW03F9',
    'Serena': 'pMsXgVXv3BLzUgSXRplE', 'Adam': 'pNInz6obpgDQGcFmaJgB',
    'Nicole': 'piTKgcLEGmPE4e6mJC43', 'Jessie': 't0jbNlBVZ17f02VISSeL',
    'Ryan': 'wViXBPUzp2ZZixB1xQuM', 'Sam': 'yoZ06aBxZCGqiEDN1UOb',
    'Glinda': 'z9fAnlkpzviPz146aGWa', 'Mimi': 'zrHiDhphv9ZnVXBqUBnd',
    'Aria': '9BWtsMINqrJLrRacOk9x', 'Guy': 'ErXwobaYiN019PkySvjV',
    'Jenny': 'EXAVITQu4vr4xnSDxMaL', 'Steffan': 'TxGEqnHWrfWFTfGW9XjX',
    'Byte': 'pNInz6obpgDQGcFmaJgB',  # Adam
}

_chatterbox_model = None
_chatterbox_lock = threading.Lock()


def sanitize_text(text):
    """Strip emojis/markup and collapse repeated punctuation so cloning TTS
    engines don't buzz or glitch. Mirrors the cleanup both callers used."""
    t = text or ""
    t = re.sub(r'[^\w\s.,?!;:\"\'-]', '', t)
    t = re.sub(r'(\.\s*){2,}', '.', t)
    t = re.sub(r'!{2,}', '!', t)
    t = re.sub(r'\?{2,}', '?', t)
    t = re.sub(r',{2,}', ',', t)
    return t.replace('\n', ' ').replace('\r', ' ').strip()


# ── Per-engine synthesis (each returns the written path or raises) ────────────

def _synth_edge(text, voice, out_base, cfg):
    import asyncio
    import edge_tts
    voice_name = EDGE_VOICE_MAP.get(voice, 'en-US-AriaNeural')
    path = out_base + '.mp3'
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(edge_tts.Communicate(text, voice_name).save(path))
    finally:
        loop.close()
    return path


def _synth_gtts(text, voice, out_base, cfg):
    from gtts import gTTS
    path = out_base + '.mp3'
    gTTS(text=text, lang='en', slow=False).save(path)
    return path


def _synth_elevenlabs(text, voice, out_base, cfg):
    import requests
    api_key = (cfg.get('elevenlabs', {}) or {}).get('api_key', '')
    if not api_key:
        raise RuntimeError("ElevenLabs API key not set")
    voice_id = ELEVEN_VOICE_IDS.get(voice, ELEVEN_VOICE_IDS['Aria'])
    path = out_base + '.mp3'
    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"Accept": "audio/mpeg", "Content-Type": "application/json", "xi-api-key": api_key},
        json={"text": text, "model_id": "eleven_monolingual_v1",
              "voice_settings": {"stability": 0.5, "similarity_boost": 0.5}},
        timeout=60.0,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs HTTP {resp.status_code}: {resp.text[:200]}")
    with open(path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=1024):
            if chunk:
                f.write(chunk)
    return path


def _synth_fish(text, voice, out_base, cfg):
    import requests
    import msgpack
    va = cfg.get('voice_agent', {}) or {}
    api_key = va.get('fish_speech_api_key', '')
    if not api_key:
        raise RuntimeError("Fish Speech API key not set")
    path = out_base + '.mp3'
    body = {
        "text": text, "format": "mp3",
        "prosody": {"speed": va.get('fish_speech_speed', 0.85)},
    }
    reference_audio = va.get('reference_audio', '')
    if reference_audio:
        refs = []
        for r in (reference_audio if isinstance(reference_audio, list) else [reference_audio]):
            if os.path.exists(r):
                with open(r, 'rb') as f:
                    refs.append({"audio": f.read(), "text": "Yeah man I hear you"})
        if refs:
            body["references"] = refs
    resp = requests.post(
        "https://api.fish.audio/v1/tts",
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/msgpack",
                 "model": va.get('fish_speech_model', 's2.1-pro-free')},
        data=msgpack.packb(body), timeout=60.0,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Fish Speech HTTP {resp.status_code}: {resp.text[:200]}")
    with open(path, 'wb') as f:
        f.write(resp.content)
    return path


def _synth_piper(text, voice, out_base, cfg):
    import subprocess
    path = out_base + '.wav'
    model_path = os.path.join(os.getcwd(), "en_US-lessac-medium.onnx")
    txt_path = out_base + '_piper.txt'
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(text)
    subprocess.run(f'type "{txt_path}" | piper --model "{model_path}" --output_file "{path}"', shell=True)
    return path


def _synth_chatterbox(text, voice, out_base, cfg):
    global _chatterbox_model
    import soundfile as sf
    import subprocess
    va = cfg.get('voice_agent', {}) or {}
    ref = va.get('reference_audio', r"C:\Users\Chesley\Galactic AI\CHONG\voice_output_13.wav")
    if isinstance(ref, list):
        ref = next((r for r in ref if os.path.exists(r)), ref[0] if ref else '')
    if not ref or not os.path.exists(ref):
        raise RuntimeError(f"Reference audio not found: {ref}")
    with _chatterbox_lock:
        if _chatterbox_model is None:
            from chatterbox.tts import ChatterboxTTS
            _chatterbox_model = ChatterboxTTS.from_pretrained(device="cuda:1")
    wav = _chatterbox_model.generate(text, audio_prompt_path=ref)
    path = out_base + '.wav'
    sf.write(path, wav.squeeze().cpu().numpy(), _chatterbox_model.sr)
    # Slow ~50% so the clone doesn't talk too fast.
    slow = out_base + '_slow.wav'
    subprocess.run(f'ffmpeg -i "{path}" -filter:a "atempo=0.5" -y "{slow}"',
                   shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return slow if os.path.exists(slow) else path


_ENGINES = {
    'edge-tts': _synth_edge,
    'gtts': _synth_gtts,
    'elevenlabs': _synth_elevenlabs,
    'fish-speech': _synth_fish,
    'piper': _synth_piper,
    'chatterbox': _synth_chatterbox,
}

SUPPORTED_ENGINES = tuple(_ENGINES.keys())


def synthesize(text, config, engine='edge-tts', voice='Aria', out_dir='.', basename='tts_out'):
    """Synthesize `text` to an audio file. Returns {path, engine, error}.

    engine   — one of SUPPORTED_ENGINES (pyttsx3 handled by caller).
    voice    — voice name for edge/elevenlabs (ignored by fish/piper/chatterbox).
    out_dir  — directory for the output file.
    basename — filename stem (extension chosen by the engine).
    """
    clean = sanitize_text(text)
    if not clean:
        return {'path': None, 'engine': engine, 'error': 'empty text after sanitize'}
    engine = (engine or 'edge-tts').lower()
    fn = _ENGINES.get(engine)
    if fn is None:
        return {'path': None, 'engine': engine, 'error': f'unsupported engine: {engine}'}
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:
        pass
    out_base = os.path.join(out_dir, basename)
    try:
        path = fn(clean, voice, out_base, config)
        if not path or not os.path.exists(path):
            return {'path': None, 'engine': engine, 'error': 'engine produced no file'}
        return {'path': path, 'engine': engine, 'error': None}
    except Exception as e:
        return {'path': None, 'engine': engine, 'error': str(e)}


def boost_file(path, gain_db=15):
    """Apply a dB gain in place (used before local playback). Best-effort."""
    try:
        from pydub import AudioSegment
        if path.endswith('.wav'):
            seg = AudioSegment.from_wav(path)
        elif path.endswith('.mp3'):
            seg = AudioSegment.from_mp3(path)
        else:
            return
        (seg + gain_db).export(path, format='wav' if path.endswith('.wav') else 'mp3')
    except Exception:
        pass
