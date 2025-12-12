/**
 * API Key Management
 * Handles secure storage and retrieval of API keys in browser localStorage
 */

(function() {
    'use strict';

    // Simple hash function for basic obfuscation (NOT cryptographically secure)
    function simpleHash(str) {
        var hash = 0;
        for (var i = 0; i < str.length; i++) {
            var char = str.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash; // Convert to 32bit integer
        }
        return btoa(hash.toString());
    }

    // XOR cipher for basic obfuscation
    function xorCipher(str, key) {
        var result = '';
        for (var i = 0; i < str.length; i++) {
            result += String.fromCharCode(str.charCodeAt(i) ^ key.charCodeAt(i % key.length));
        }
        return btoa(result);
    }

    function xorDecipher(encoded, key) {
        try {
            var str = atob(encoded);
            var result = '';
            for (var i = 0; i < str.length; i++) {
                result += String.fromCharCode(str.charCodeAt(i) ^ key.charCodeAt(i % key.length));
            }
            return result;
        } catch (e) {
            return null;
        }
    }

    // Storage key for the cipher key
    var CIPHER_KEY_STORAGE = 'mkfl_ck';
    var API_KEYS_STORAGE = 'mkfl_keys';

    // Get or create cipher key
    function getCipherKey() {
        var key = localStorage.getItem(CIPHER_KEY_STORAGE);
        if (!key) {
            key = btoa(Math.random().toString(36).substring(2) + Date.now());
            localStorage.setItem(CIPHER_KEY_STORAGE, key);
        }
        return key;
    }

    window.APIKeyManager = {
        /**
         * Save API keys to localStorage with basic obfuscation
         */
        saveKeys: function(keys) {
            try {
                var cipherKey = getCipherKey();
                var encoded = xorCipher(JSON.stringify(keys), cipherKey);
                localStorage.setItem(API_KEYS_STORAGE, encoded);
                console.log('[API_KEYS] Keys saved successfully');
                return true;
            } catch (e) {
                console.error('[API_KEYS] Failed to save keys:', e);
                return false;
            }
        },

        /**
         * Load API keys from localStorage
         */
        loadKeys: function() {
            try {
                var encoded = localStorage.getItem(API_KEYS_STORAGE);
                if (!encoded) {
                    return null;
                }
                var cipherKey = getCipherKey();
                var decoded = xorDecipher(encoded, cipherKey);
                if (!decoded) {
                    return null;
                }
                return JSON.parse(decoded);
            } catch (e) {
                console.error('[API_KEYS] Failed to load keys:', e);
                return null;
            }
        },

        /**
         * Check if all required keys are configured
         */
        areKeysConfigured: function() {
            var keys = this.loadKeys();
            if (!keys) {
                return false;
            }
            return !!(
                keys.livekitUrl &&
                keys.livekitApiKey &&
                keys.livekitApiSecret &&
                keys.openaiApiKey &&
                keys.deepgramApiKey
            );
        },

        /**
         * Clear all stored keys
         */
        clearKeys: function() {
            localStorage.removeItem(API_KEYS_STORAGE);
            console.log('[API_KEYS] Keys cleared');
        },

        /**
         * Validate key format
         */
        validateKeys: function(keys) {
            var errors = [];

            if (!keys.livekitUrl || !keys.livekitUrl.startsWith('wss://')) {
                errors.push('LiveKit URL must start with wss://');
            }

            if (!keys.livekitApiKey || keys.livekitApiKey.length < 10) {
                errors.push('LiveKit API Key appears invalid');
            }

            if (!keys.livekitApiSecret || keys.livekitApiSecret.length < 10) {
                errors.push('LiveKit API Secret appears invalid');
            }

            if (!keys.openaiApiKey || !keys.openaiApiKey.startsWith('sk-')) {
                errors.push('OpenAI API Key must start with sk-');
            }

            if (!keys.deepgramApiKey || keys.deepgramApiKey.length < 10) {
                errors.push('Deepgram API Key appears invalid');
            }

            return {
                valid: errors.length === 0,
                errors: errors
            };
        }
    };
})();
