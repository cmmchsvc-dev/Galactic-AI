package com.galacticai.mobile

import android.content.Context
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity

/**
 * Handles optional biometric/PIN authentication for app access.
 * Uses AndroidX Biometric library — supports fingerprint, face, and device PIN.
 */
class BiometricHelper(private val activity: FragmentActivity) {

    interface AuthCallback {
        fun onSuccess()
        fun onFailure(message: String)
        fun onNotAvailable()
    }

    fun isAvailable(): Boolean {
        val manager = BiometricManager.from(activity)
        return manager.canAuthenticate(
            BiometricManager.Authenticators.BIOMETRIC_STRONG or
            BiometricManager.Authenticators.DEVICE_CREDENTIAL
        ) == BiometricManager.BIOMETRIC_SUCCESS
    }

    fun authenticate(callback: AuthCallback) {
        if (!isAvailable()) {
            callback.onNotAvailable()
            return
        }

        val executor = ContextCompat.getMainExecutor(activity)

        val biometricPrompt = BiometricPrompt(activity, executor,
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    callback.onSuccess()
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    if (errorCode == BiometricPrompt.ERROR_USER_CANCELED ||
                        errorCode == BiometricPrompt.ERROR_NEGATIVE_BUTTON) {
                        callback.onFailure("Authentication cancelled")
                    } else {
                        callback.onFailure(errString.toString())
                    }
                }

                override fun onAuthenticationFailed() {
                    // Called on each failed attempt — don't close, let user retry
                }
            }
        )

        val promptInfo = BiometricPrompt.PromptInfo.Builder()
            .setTitle("Galactic AI Mobile")
            .setSubtitle("Authenticate to access Control Deck")
            .setAllowedAuthenticators(
                BiometricManager.Authenticators.BIOMETRIC_STRONG or
                BiometricManager.Authenticators.DEVICE_CREDENTIAL
            )
            .build()

        biometricPrompt.authenticate(promptInfo)
    }
}
