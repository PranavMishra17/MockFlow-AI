/**
 * API Key Manager
 * Handles storage and validation of API keys in browser localStorage
 */

(function() {
    'use strict';

    window.APIKeyManager = {
        /**
         * Save API keys to localStorage
         */
        saveKeys: function(keys) {
            try {
                localStorage.setItem('mockflow_api_keys', JSON.stringify(keys));
                return true;
            } catch (e) {
                console.error('Failed to save API keys:', e);
                return false;
            }
        },

        /**
         * Load API keys from localStorage
         */
        loadKeys: function() {
            try {
                var keysStr = localStorage.getItem('mockflow_api_keys');
                return keysStr ? JSON.parse(keysStr) : null;
            } catch (e) {
                console.error('Failed to load API keys:', e);
                return null;
            }
        },

        /**
         * Clear all API keys from localStorage
         */
        clearKeys: function() {
            try {
                localStorage.removeItem('mockflow_api_keys');
                return true;
            } catch (e) {
                console.error('Failed to clear API keys:', e);
                return false;
            }
        },

        /**
         * Check if API keys are configured
         */
        hasKeys: function() {
            var keys = this.loadKeys();
            return keys &&
                   keys.livekitUrl &&
                   keys.livekitApiKey &&
                   keys.livekitApiSecret &&
                   keys.openaiApiKey &&
                   keys.deepgramApiKey;
        },

        /**
         * Validate API keys format
         */
        validateKeys: function(keys) {
            var errors = [];

            if (!keys.livekitUrl || !keys.livekitUrl.trim()) {
                errors.push('LiveKit URL is required');
            } else if (!keys.livekitUrl.startsWith('wss://') && !keys.livekitUrl.startsWith('ws://')) {
                errors.push('LiveKit URL must start with wss:// or ws://');
            }

            if (!keys.livekitApiKey || !keys.livekitApiKey.trim()) {
                errors.push('LiveKit API Key is required');
            }

            if (!keys.livekitApiSecret || !keys.livekitApiSecret.trim()) {
                errors.push('LiveKit API Secret is required');
            }

            if (!keys.openaiApiKey || !keys.openaiApiKey.trim()) {
                errors.push('OpenAI API Key is required');
            } else if (!keys.openaiApiKey.startsWith('sk-')) {
                errors.push('OpenAI API Key should start with sk-');
            }

            if (!keys.deepgramApiKey || !keys.deepgramApiKey.trim()) {
                errors.push('Deepgram API Key is required');
            }

            return {
                valid: errors.length === 0,
                errors: errors
            };
        }
    };
})();
