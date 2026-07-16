"""
Galactic AI — Local Speech-to-Text (faster-whisper)
===================================================

Local-first transcription so voice never has to leave the machine. Used by:
  - the wake-word agent (skills/core/voice_agent.py), replacing cloud Google
  - the Control Deck push-to-talk endpoint (/api/stt), before the cloud APIs

faster-whisper (CTranslate2) runs the Whisper models locally on GPU or CPU.
If the package or a model can't load, every function degrades to returning
None so callers transparently fall back to their previous cloud path.

Model + device are configurable:
  env GALACTIC_WHISPER_MODEL  (default 'base.en')
  env GALACTIC_WHISPER_DEVICE ('cuda' | 'cpu' | 'auto', default 'auto')
"""

import os
import threading

_model = None
_model_lock = threading.Lock()
_unavailable = False       # set once if faster-whisper truly can't run
_loaded_desc = ""          # human-readable "size on device" for logging
_configured_size = None    # model size set from app config (overrides env default)


def configure(model_size=None):
    """Set the preferred model size before first load (from app config).
    No-op once a model is already loaded."""
    global _configured_size
    if model_size:
        _configured_size = str(model_size)


def _pick_device():
    """Prefer CUDA if torch reports a GPU; otherwise CPU."""
    pref = os.environ.get('GALACTIC_WHISPER_DEVICE', 'auto').lower()
    if pref == 'cpu':
        return 'cpu', 'int8'
    if pref == 'cuda':
        return 'cuda', 'int8_float16'
    try:
        import torch
        if torch.cuda.is_available():
            return 'cuda', 'int8_float16'
    except Exception:
        pass
    return 'cpu', 'int8'


def _get_model(model_size=None):
    """Lazily load (and cache) the WhisperModel. Returns None if unavailable."""
    global _model, _unavailable, _loaded_desc
    if _unavailable:
        return None
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from faster_whisper import WhisperModel
        except Exception:
            _unavailable = True
            return None
        size = model_size or _configured_size or os.environ.get('GALACTIC_WHISPER_MODEL', 'base.en')
        device, compute = _pick_device()
        try:
            _model = WhisperModel(size, device=device, compute_type=compute)
            _loaded_desc = f"{size} on {device} ({compute})"
        except Exception:
            # GPU load can fail (no CUDA libs, OOM) — retry once on CPU.
            try:
                _model = WhisperModel(size, device='cpu', compute_type='int8')
                _loaded_desc = f"{size} on cpu (int8) [gpu load failed]"
            except Exception:
                _unavailable = True
                return None
    return _model


def available():
    """True if local transcription can run (triggers a lazy load)."""
    return _get_model() is not None


def describe():
    return _loaded_desc or ("unavailable" if _unavailable else "not loaded")


def _run(audio, language='en'):
    model = _get_model()
    if model is None:
        return None
    try:
        segments, _info = model.transcribe(
            audio, language=language, beam_size=1, vad_filter=True
        )
        return "".join(seg.text for seg in segments).strip()
    except Exception:
        return None


def transcribe_path(path, language='en'):
    """Transcribe an audio file (wav/mp3/webm/ogg/mp4 — decoded via PyAV)."""
    if not path or not os.path.exists(path):
        return None
    return _run(path, language=language)


def transcribe_pcm16(raw_bytes, sample_rate=16000, language='en'):
    """Transcribe raw 16-bit mono PCM. Whisper wants 16 kHz — pass audio the
    caller already resampled to 16000 (speech_recognition can do this)."""
    if not raw_bytes:
        return None
    try:
        import numpy as np
    except Exception:
        return None
    if sample_rate != 16000:
        # faster-whisper assumes 16 kHz for raw arrays; refuse otherwise so we
        # don't feed it wrong-rate audio and get garbled text.
        return None
    audio = np.frombuffer(raw_bytes, dtype=np.int16).astype('float32') / 32768.0
    return _run(audio, language=language)
