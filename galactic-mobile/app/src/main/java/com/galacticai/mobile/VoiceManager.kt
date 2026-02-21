package com.galacticai.mobile

import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaPlayer
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.webkit.WebView
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/**
 * Handles hands-free voice I/O for Galactic-AI Mobile.
 *
 * STT: Android SpeechRecognizer (on-device) with server-side Whisper fallback.
 * TTS: Server-side (ElevenLabs/edge-tts/gTTS) with on-device Android TTS fallback.
 */
class VoiceManager(
    private val context: Context,
    private val storage: SecureStorage
) : TextToSpeech.OnInitListener {

    interface VoiceCallback {
        fun onListeningStarted()
        fun onListeningStopped()
        fun onSpeechResult(text: String)
        fun onSpeechError(message: String)
        fun onTtsStarted()
        fun onTtsFinished()
    }

    private var speechRecognizer: SpeechRecognizer? = null
    private var localTts: TextToSpeech? = null
    private var localTtsReady = false
    private var mediaPlayer: MediaPlayer? = null
    private var audioManager: AudioManager? = null
    private var audioFocusRequest: AudioFocusRequest? = null
    var callback: VoiceCallback? = null
    var isListening = false
        private set

    init {
        audioManager = context.getSystemService(Context.AUDIO_SERVICE) as? AudioManager
        localTts = TextToSpeech(context, this)
    }

    override fun onInit(status: Int) {
        if (status == TextToSpeech.SUCCESS) {
            localTts?.language = Locale.US
            localTtsReady = true
        }
    }

    // ── Speech-to-Text ───────────────────────────────────────────────────────

    fun startListening() {
        if (isListening) return
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            callback?.onSpeechError("Speech recognition not available on this device")
            return
        }

        speechRecognizer = SpeechRecognizer.createSpeechRecognizer(context)
        speechRecognizer?.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) {
                isListening = true
                callback?.onListeningStarted()
            }
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) {}
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {
                isListening = false
                callback?.onListeningStopped()
            }
            override fun onError(error: Int) {
                isListening = false
                callback?.onListeningStopped()
                val msg = when (error) {
                    SpeechRecognizer.ERROR_NO_MATCH -> "No speech detected"
                    SpeechRecognizer.ERROR_NETWORK -> "Network error"
                    SpeechRecognizer.ERROR_AUDIO -> "Audio error"
                    else -> "Speech error ($error)"
                }
                callback?.onSpeechError(msg)
            }
            override fun onResults(results: Bundle?) {
                isListening = false
                callback?.onListeningStopped()
                val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                val text = matches?.firstOrNull() ?: ""
                if (text.isNotBlank()) {
                    callback?.onSpeechResult(text)
                }
            }
            override fun onPartialResults(partialResults: Bundle?) {}
            override fun onEvent(eventType: Int, params: Bundle?) {}
        })

        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 3000L)
        }
        speechRecognizer?.startListening(intent)
    }

    fun stopListening() {
        speechRecognizer?.stopListening()
        isListening = false
        callback?.onListeningStopped()
    }

    /**
     * Inject recognized speech text into the WebView chat input.
     */
    fun injectTextIntoChat(webView: WebView, text: String) {
        val escapedText = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        webView.evaluateJavascript(
            """
            (function() {
                var input = document.getElementById('chat-input');
                if (input) {
                    input.value = (input.value ? input.value + ' ' : '') + '$escapedText';
                    input.focus();
                }
            })();
            """.trimIndent(),
            null
        )
    }

    // ── Text-to-Speech ───────────────────────────────────────────────────────

    /**
     * Speak text using server-side TTS. Falls back to on-device TTS.
     */
    fun speak(text: String) {
        Thread {
            try {
                val audioData = fetchServerTts(text)
                if (audioData != null) {
                    playAudio(audioData)
                    return@Thread
                }
            } catch (_: Exception) {}

            // Fallback to local TTS
            speakLocal(text)
        }.start()
    }

    private fun fetchServerTts(text: String): ByteArray? {
        try {
            val url = URL("${storage.buildBaseUrl()}/api/tts")
            val conn = url.openConnection() as HttpURLConnection
            if (conn is HttpsURLConnection) {
                val trustAll = arrayOf<TrustManager>(object : X509TrustManager {
                    override fun checkClientTrusted(chain: Array<java.security.cert.X509Certificate>, t: String) {}
                    override fun checkServerTrusted(chain: Array<java.security.cert.X509Certificate>, t: String) {}
                    override fun getAcceptedIssuers() = arrayOf<java.security.cert.X509Certificate>()
                })
                val ctx = SSLContext.getInstance("TLS")
                ctx.init(null, trustAll, java.security.SecureRandom())
                conn.sslSocketFactory = ctx.socketFactory
                conn.hostnameVerifier = javax.net.ssl.HostnameVerifier { _, _ -> true }
            }

            conn.requestMethod = "POST"
            conn.setRequestProperty("Content-Type", "application/json")
            conn.setRequestProperty("Authorization", "Bearer ${storage.jwtToken}")
            conn.doOutput = true
            conn.connectTimeout = 15000
            conn.readTimeout = 30000

            val body = """{"text":"${text.take(5000).replace("\"", "\\\"")}","voice":"Guy"}"""
            conn.outputStream.use { it.write(body.toByteArray()) }

            if (conn.responseCode == 200 && conn.contentType?.contains("audio") == true) {
                return conn.inputStream.readBytes()
            }
        } catch (_: Exception) {}
        return null
    }

    private fun playAudio(data: ByteArray) {
        try {
            requestAudioFocus()
            val tempFile = File.createTempFile("tts_", ".mp3", context.cacheDir)
            FileOutputStream(tempFile).use { it.write(data) }

            mediaPlayer?.release()
            mediaPlayer = MediaPlayer().apply {
                setAudioAttributes(AudioAttributes.Builder()
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .build())
                setDataSource(tempFile.absolutePath)
                setOnPreparedListener {
                    callback?.onTtsStarted()
                    it.start()
                }
                setOnCompletionListener {
                    callback?.onTtsFinished()
                    abandonAudioFocus()
                    tempFile.delete()
                }
                prepareAsync()
            }
        } catch (e: Exception) {
            callback?.onSpeechError("Audio playback failed: ${e.message}")
        }
    }

    private fun speakLocal(text: String) {
        if (!localTtsReady) return
        callback?.onTtsStarted()
        localTts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "galactic_tts")
        // Note: local TTS doesn't have a reliable completion callback for all engines
        callback?.onTtsFinished()
    }

    private fun requestAudioFocus() {
        audioFocusRequest = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
            .setAudioAttributes(AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                .build())
            .build()
        audioManager?.requestAudioFocus(audioFocusRequest!!)
    }

    private fun abandonAudioFocus() {
        audioFocusRequest?.let { audioManager?.abandonAudioFocusRequest(it) }
    }

    fun destroy() {
        speechRecognizer?.destroy()
        localTts?.shutdown()
        mediaPlayer?.release()
        abandonAudioFocus()
    }
}
