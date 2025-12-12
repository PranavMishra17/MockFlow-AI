/**
 * Modal Management for Settings and Developer modals
 */

(function() {
    'use strict';

    // Settings Modal
    window.SettingsModal = {
        open: function() {
            var modal = document.getElementById('settingsModal');
            if (modal) {
                modal.classList.add('visible');
                this.loadSavedKeys();
            }
        },

        close: function() {
            var modal = document.getElementById('settingsModal');
            if (modal) {
                modal.classList.remove('visible');
                this.clearMessages();
            }
        },

        loadSavedKeys: function() {
            var keys = window.APIKeyManager.loadKeys();
            if (keys) {
                document.getElementById('livekitUrl').value = keys.livekitUrl || '';
                document.getElementById('livekitApiKey').value = keys.livekitApiKey || '';
                document.getElementById('livekitApiSecret').value = keys.livekitApiSecret || '';
                document.getElementById('openaiApiKey').value = keys.openaiApiKey || '';
                document.getElementById('deepgramApiKey').value = keys.deepgramApiKey || '';
            }
        },

        save: function() {
            var keys = {
                livekitUrl: document.getElementById('livekitUrl').value.trim(),
                livekitApiKey: document.getElementById('livekitApiKey').value.trim(),
                livekitApiSecret: document.getElementById('livekitApiSecret').value.trim(),
                openaiApiKey: document.getElementById('openaiApiKey').value.trim(),
                deepgramApiKey: document.getElementById('deepgramApiKey').value.trim()
            };

            // Validate
            var validation = window.APIKeyManager.validateKeys(keys);
            if (!validation.valid) {
                this.showError(validation.errors.join('<br>'));
                return;
            }

            // Save
            if (window.APIKeyManager.saveKeys(keys)) {
                this.showSuccess('API keys saved successfully! You can now start interviews.');
                setTimeout(function() {
                    window.SettingsModal.close();
                }, 2000);
            } else {
                this.showError('Failed to save API keys. Please try again.');
            }
        },

        clear: function() {
            if (confirm('Are you sure you want to clear all saved API keys?')) {
                window.APIKeyManager.clearKeys();
                document.getElementById('livekitUrl').value = '';
                document.getElementById('livekitApiKey').value = '';
                document.getElementById('livekitApiSecret').value = '';
                document.getElementById('openaiApiKey').value = '';
                document.getElementById('deepgramApiKey').value = '';
                this.showSuccess('All API keys have been cleared.');
            }
        },

        showError: function(message) {
            var errorEl = document.getElementById('settingsError');
            if (errorEl) {
                errorEl.innerHTML = message;
                errorEl.classList.add('visible');
            }
            var successEl = document.getElementById('settingsSuccess');
            if (successEl) {
                successEl.classList.remove('visible');
            }
        },

        showSuccess: function(message) {
            var successEl = document.getElementById('settingsSuccess');
            if (successEl) {
                successEl.textContent = message;
                successEl.classList.add('visible');
            }
            var errorEl = document.getElementById('settingsError');
            if (errorEl) {
                errorEl.classList.remove('visible');
            }
        },

        clearMessages: function() {
            var errorEl = document.getElementById('settingsError');
            if (errorEl) {
                errorEl.classList.remove('visible');
            }
            var successEl = document.getElementById('settingsSuccess');
            if (successEl) {
                successEl.classList.remove('visible');
            }
        }
    };

    // Developer Modal
    window.DeveloperModal = {
        open: function() {
            var modal = document.getElementById('developerModal');
            if (modal) {
                modal.classList.add('visible');
            }
        },

        close: function() {
            var modal = document.getElementById('developerModal');
            if (modal) {
                modal.classList.remove('visible');
            }
        }
    };

    // Initialize on page load
    document.addEventListener('DOMContentLoaded', function() {
        // Settings modal event listeners
        var settingsModal = document.getElementById('settingsModal');
        if (settingsModal) {
            var closeBtn = settingsModal.querySelector('.modal-close');
            if (closeBtn) {
                closeBtn.addEventListener('click', function() {
                    window.SettingsModal.close();
                });
            }

            var cancelBtn = document.getElementById('settingsCancel');
            if (cancelBtn) {
                cancelBtn.addEventListener('click', function() {
                    window.SettingsModal.close();
                });
            }

            var saveBtn = document.getElementById('settingsSave');
            if (saveBtn) {
                saveBtn.addEventListener('click', function() {
                    window.SettingsModal.save();
                });
            }

            var clearBtn = document.getElementById('settingsClear');
            if (clearBtn) {
                clearBtn.addEventListener('click', function() {
                    window.SettingsModal.clear();
                });
            }

            // Close on overlay click
            settingsModal.addEventListener('click', function(e) {
                if (e.target === settingsModal) {
                    window.SettingsModal.close();
                }
            });
        }

        // Developer modal event listeners
        var devModal = document.getElementById('developerModal');
        if (devModal) {
            var closeBtn = devModal.querySelector('.modal-close');
            if (closeBtn) {
                closeBtn.addEventListener('click', function() {
                    window.DeveloperModal.close();
                });
            }

            var closeFooterBtn = document.getElementById('devClose');
            if (closeFooterBtn) {
                closeFooterBtn.addEventListener('click', function() {
                    window.DeveloperModal.close();
                });
            }

            // Close on overlay click
            devModal.addEventListener('click', function(e) {
                if (e.target === devModal) {
                    window.DeveloperModal.close();
                }
            });
        }
    });
})();
