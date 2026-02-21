package com.galacticai.mobile

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import com.google.zxing.integration.android.IntentIntegrator
import org.json.JSONObject

/**
 * Connection setup screen — cyberpunk themed.
 * User enters server address + password, or scans QR code from PC Control Deck.
 */
class ConnectActivity : AppCompatActivity() {

    private lateinit var storage: SecureStorage
    private lateinit var connectionManager: ConnectionManager

    private lateinit var hostInput: EditText
    private lateinit var portInput: EditText
    private lateinit var passwordInput: EditText
    private lateinit var httpsToggle: CheckBox
    private lateinit var biometricToggle: CheckBox
    private lateinit var autoSpeakToggle: CheckBox
    private lateinit var connectBtn: Button
    private lateinit var scanQrBtn: Button
    private lateinit var statusDot: View
    private lateinit var statusText: TextView
    private lateinit var errorText: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_connect)

        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.statusBarColor = 0xFF0a0b18.toInt()
        window.navigationBarColor = 0xFF04050d.toInt()

        storage = SecureStorage(this)
        connectionManager = ConnectionManager(storage)

        hostInput = findViewById(R.id.input_host)
        portInput = findViewById(R.id.input_port)
        passwordInput = findViewById(R.id.input_password)
        httpsToggle = findViewById(R.id.toggle_https)
        biometricToggle = findViewById(R.id.toggle_biometric)
        autoSpeakToggle = findViewById(R.id.toggle_auto_speak)
        connectBtn = findViewById(R.id.btn_connect)
        scanQrBtn = findViewById(R.id.btn_scan_qr)
        statusDot = findViewById(R.id.status_dot)
        statusText = findViewById(R.id.status_text)
        errorText = findViewById(R.id.error_text)

        // Pre-fill from stored values
        if (storage.serverHost.isNotBlank()) {
            hostInput.setText(storage.serverHost)
            portInput.setText(storage.serverPort.toString())
            httpsToggle.isChecked = storage.useHttps
            biometricToggle.isChecked = storage.biometricEnabled
            autoSpeakToggle.isChecked = storage.autoSpeak
        }

        connectBtn.setOnClickListener { attemptConnect() }
        scanQrBtn.setOnClickListener { scanQrCode() }
    }

    private fun attemptConnect() {
        val host = hostInput.text.toString().trim()
        val portStr = portInput.text.toString().trim()
        val password = passwordInput.text.toString()

        if (host.isBlank()) {
            showError("Enter server address")
            return
        }
        if (password.isBlank()) {
            showError("Enter passphrase")
            return
        }

        val port = portStr.toIntOrNull() ?: 17789
        val useHttps = httpsToggle.isChecked

        connectBtn.isEnabled = false
        connectBtn.text = "CONNECTING..."
        errorText.visibility = View.GONE
        statusDot.setBackgroundResource(R.drawable.status_dot_connecting)
        statusText.text = "Connecting..."

        connectionManager.login(host, port, useHttps, password,
            object : ConnectionManager.ConnectionCallback {
                override fun onConnected(token: String, expires: Long) {
                    // Save connection details
                    storage.serverHost = host
                    storage.serverPort = port
                    storage.useHttps = useHttps
                    storage.jwtToken = token
                    storage.tokenExpiry = expires
                    storage.biometricEnabled = biometricToggle.isChecked
                    storage.autoSpeak = autoSpeakToggle.isChecked

                    statusDot.setBackgroundResource(R.drawable.status_dot_online)
                    statusText.text = "Connected"

                    // Launch main activity
                    startActivity(Intent(this@ConnectActivity, MainActivity::class.java))
                    finish()
                    overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out)
                }

                override fun onError(message: String) {
                    showError(message)
                    connectBtn.isEnabled = true
                    connectBtn.text = "CONNECT"
                    statusDot.setBackgroundResource(R.drawable.status_dot_offline)
                    statusText.text = "Offline"
                }

                override fun onHealthCheck(online: Boolean, model: String?) {}
            }
        )
    }

    private fun scanQrCode() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.CAMERA), RC_CAMERA)
            return
        }
        launchQrScanner()
    }

    private fun launchQrScanner() {
        try {
            IntentIntegrator(this)
                .setDesiredBarcodeFormats(IntentIntegrator.QR_CODE)
                .setPrompt("Scan QR code from Galactic-AI Settings tab")
                .setCameraId(0)
                .setBeepEnabled(false)
                .setOrientationLocked(true)
                .initiateScan()
        } catch (e: Exception) {
            showError("Failed to open QR scanner: ${e.message}")
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        val result = IntentIntegrator.parseActivityResult(requestCode, resultCode, data)
        if (result != null && result.contents != null) {
            try {
                val json = JSONObject(result.contents)
                if (json.optString("app") == "galactic-ai") {
                    hostInput.setText(json.getString("host"))
                    portInput.setText(json.getInt("port").toString())
                    httpsToggle.isChecked = false  // Server uses plain HTTP on LAN

                    val fingerprint = json.optString("fingerprint", "")
                    if (fingerprint.isNotBlank()) {
                        storage.certFingerprint = fingerprint
                    }

                    Toast.makeText(this, "QR scanned! Enter your passphrase to connect.", Toast.LENGTH_LONG).show()
                    passwordInput.requestFocus()
                } else {
                    showError("Invalid QR code — not a Galactic-AI pairing code")
                }
            } catch (e: Exception) {
                showError("Invalid QR code format")
            }
        } else {
            super.onActivityResult(requestCode, resultCode, data)
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == RC_CAMERA && grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            launchQrScanner()
        }
    }

    private fun showError(message: String) {
        errorText.text = message
        errorText.visibility = View.VISIBLE
    }

    companion object {
        private const val RC_CAMERA = 1001
    }
}
