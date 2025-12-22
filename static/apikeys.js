// API Keys Management for authenticated users
// Handles loading, saving, and validating API keys stored in Supabase

let hasExistingKeys = false;
let keysModified = false;
let originalKeyData = {};

document.addEventListener('DOMContentLoaded', async () => {
    try {
        console.log('[APIKEYS] Initializing API keys page...');

        // Wait for requireAuth to be available
        let retries = 0;
        while (typeof requireAuth === 'undefined' && retries < 10) {
            console.log('[APIKEYS] Waiting for auth.js to load...');
            await new Promise(resolve => setTimeout(resolve, 100));
            retries++;
        }

        if (typeof requireAuth === 'undefined') {
            console.error('[APIKEYS] requireAuth not available after waiting');
            window.location.href = '/auth/login';
            return;
        }

        await requireAuth();
        console.log('[APIKEYS] User authenticated, loading keys...');

        await loadCurrentKeys();
        setupFormListeners();
    } catch (error) {
        console.error('[APIKEYS] Initialization error:', error);
        if (error.message === 'Not authenticated') {
            // Already redirecting in requireAuth
            return;
        }
        const status = document.getElementById('keysStatus');
        if (status) {
            status.innerHTML = `
                <p style="color: var(--error); font-size: 0.875rem;">Failed to initialize. Please refresh the page.</p>
            `;
        }
    }
});

async function loadCurrentKeys() {
    const status = document.getElementById('keysStatus');

    try {
        console.log('[APIKEYS] Loading current keys status...');
        const response = await fetch('/api/user/keys/status');

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        console.log('[APIKEYS] Keys status loaded:', data);

        hasExistingKeys = data.has_keys;

        if (data.has_keys) {
            status.innerHTML = `
                <div style="display: flex; align-items: center; gap: 0.75rem; color: var(--success);">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                        <polyline points="22 4 12 14.01 9 11.01"/>
                    </svg>
                    <div>
                        <p style="font-weight: 500; margin-bottom: 0.25rem;">API Keys Configured</p>
                        <p style="color: var(--text-muted); font-size: 0.8125rem;">All required keys are set and encrypted</p>
                    </div>
                </div>
            `;

            // Fill form with masked values
            document.getElementById('livekitUrl').value = '••••••••••••••••••••••••••';
            document.getElementById('livekitApiKey').value = '••••••••••••••••';
            document.getElementById('livekitApiSecret').value = '••••••••••••••••';
            document.getElementById('openaiKey').value = '••••••••••••••••••••••••••';
            document.getElementById('deepgramKey').value = '••••••••••••••••••••••••••';

            // Disable form initially
            setFormState(false);

            // Show update button instead
            document.getElementById('saveBtn').textContent = 'Update Keys';
            document.getElementById('saveBtn').disabled = true;

        } else {
            status.innerHTML = `
                <div style="display: flex; align-items: center; gap: 0.75rem; color: var(--warning);">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"/>
                        <line x1="12" y1="8" x2="12" y2="12"/>
                        <line x1="12" y1="16" x2="12.01" y2="16"/>
                    </svg>
                    <div>
                        <p style="font-weight: 500; margin-bottom: 0.25rem;">API Keys Not Set</p>
                        <p style="color: var(--text-muted); font-size: 0.8125rem;">Configure your keys below to start interviewing</p>
                    </div>
                </div>
            `;
            setFormState(true);
        }
    } catch (error) {
        console.error('[APIKEYS] Failed to load keys status:', error);
        if (status) {
            status.innerHTML = `
                <p style="color: var(--error); font-size: 0.875rem;">Failed to load API keys status</p>
            `;
        }
    }
}

function setFormState(enabled) {
    const inputs = ['livekitUrl', 'livekitApiKey', 'livekitApiSecret', 'openaiKey', 'deepgramKey'];
    inputs.forEach(id => {
        const input = document.getElementById(id);
        if (input) {
            input.disabled = !enabled;
            if (!enabled) {
                input.style.backgroundColor = 'var(--bg-warm)';
                input.style.cursor = 'not-allowed';
            } else {
                input.style.backgroundColor = '';
                input.style.cursor = '';
            }
        }
    });
}

function setupFormListeners() {
    const inputs = ['livekitUrl', 'livekitApiKey', 'livekitApiSecret', 'openaiKey', 'deepgramKey'];
    inputs.forEach(id => {
        const input = document.getElementById(id);
        if (input) {
            input.addEventListener('input', () => {
                if (hasExistingKeys) {
                    keysModified = true;
                    document.getElementById('saveBtn').disabled = false;
                }
            });
            input.addEventListener('focus', () => {
                if (hasExistingKeys && input.value.includes('•')) {
                    input.value = '';
                    setFormState(true);
                }
            });
        }
    });
}

function validateKeys() {
    const livekitUrl = document.getElementById('livekitUrl').value.trim();
    const livekitApiKey = document.getElementById('livekitApiKey').value.trim();
    const livekitApiSecret = document.getElementById('livekitApiSecret').value.trim();
    const openaiKey = document.getElementById('openaiKey').value.trim();
    const deepgramKey = document.getElementById('deepgramKey').value.trim();

    // Skip validation if fields are masked and not modified
    if (hasExistingKeys && !keysModified) {
        return true;
    }

    if (livekitUrl.includes('•') || livekitApiKey.includes('•') ||
        livekitApiSecret.includes('•') || openaiKey.includes('•') || deepgramKey.includes('•')) {
        showModal('Invalid Input', 'Please enter actual values, not masked placeholders');
        return false;
    }

    if (!livekitUrl.startsWith('wss://') && !livekitUrl.startsWith('ws://')) {
        showModal('Invalid Input', 'LiveKit URL must start with wss:// or ws://');
        return false;
    }

    if (!livekitApiKey || livekitApiKey.length < 5) {
        showModal('Invalid Input', 'Please enter a valid LiveKit API Key');
        return false;
    }

    if (!livekitApiSecret || livekitApiSecret.length < 10) {
        showModal('Invalid Input', 'Please enter a valid LiveKit API Secret');
        return false;
    }

    if (!openaiKey.startsWith('sk-')) {
        showModal('Invalid Input', 'OpenAI key should start with "sk-"');
        return false;
    }

    if (deepgramKey.length < 10) {
        showModal('Invalid Input', 'Deepgram key appears too short');
        return false;
    }

    return true;
}

async function testKeys() {
    if (!validateKeys()) return;

    const livekitUrl = document.getElementById('livekitUrl').value.trim();
    const livekitApiKey = document.getElementById('livekitApiKey').value.trim();
    const livekitApiSecret = document.getElementById('livekitApiSecret').value.trim();
    const openaiKey = document.getElementById('openaiKey').value.trim();
    const deepgramKey = document.getElementById('deepgramKey').value.trim();

    // Find test button and show loading state
    const testBtn = event.target;
    const originalText = testBtn.textContent;
    testBtn.disabled = true;
    testBtn.textContent = 'Testing...';

    try {
        const response = await fetch('/api/user/keys/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                livekit_url: livekitUrl,
                livekit_api_key: livekitApiKey,
                livekit_api_secret: livekitApiSecret,
                openai_key: openaiKey,
                deepgram_key: deepgramKey
            })
        });

        const result = await response.json();

        if (result.valid) {
            showModal('✅ Validation Success', 'All API keys have valid formats and are ready to use!', 'success');
        } else {
            showModal('❌ Validation Failed', result.message || 'One or more keys have invalid formats', 'error');
        }
    } catch (error) {
        console.error('[APIKEYS] Key validation failed:', error);
        showModal('⚠️ Validation Error', 'Failed to validate keys. Please try again.', 'error');
    } finally {
        // Restore button state
        testBtn.disabled = false;
        testBtn.textContent = originalText;
    }
}

document.getElementById('apiKeysForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (!validateKeys()) return;

    const livekitUrl = document.getElementById('livekitUrl').value.trim();
    const livekitApiKey = document.getElementById('livekitApiKey').value.trim();
    const livekitApiSecret = document.getElementById('livekitApiSecret').value.trim();
    const openaiKey = document.getElementById('openaiKey').value.trim();
    const deepgramKey = document.getElementById('deepgramKey').value.trim();

    // Disable save button to prevent double-submit
    const saveBtn = document.getElementById('saveBtn');
    const originalText = saveBtn.textContent;
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    try {
        const response = await fetch('/api/user/keys', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                livekit_url: livekitUrl,
                livekit_api_key: livekitApiKey,
                livekit_api_secret: livekitApiSecret,
                openai_key: openaiKey,
                deepgram_key: deepgramKey
            })
        });

        const result = await response.json();

        if (response.ok && result.success) {
            showModal(
                hasExistingKeys ? '✅ Keys Updated Successfully' : '✅ Keys Configured Successfully',
                'Your API keys have been encrypted and saved securely. You can now start interviews! Redirecting to dashboard...',
                'success',
                () => {
                    setTimeout(() => {
                        window.location.href = '/dashboard';
                    }, 1500);
                }
            );
        } else {
            saveBtn.disabled = false;
            saveBtn.textContent = originalText;
            showModal('❌ Save Failed', result.error || result.message || 'Failed to save keys', 'error');
        }
    } catch (error) {
        console.error('[APIKEYS] Failed to save keys:', error);
        saveBtn.disabled = false;
        saveBtn.textContent = originalText;
        showModal('⚠️ Network Error', 'Failed to save keys. Please check your connection and try again.', 'error');
    }
});

function showModal(title, message, type = 'info', callback = null) {
    const modal = document.getElementById('messageModal');
    const titleEl = document.getElementById('modalTitle');
    const messageEl = document.getElementById('modalMessage');

    titleEl.textContent = title;
    messageEl.textContent = message;

    // Add color based on type
    if (type === 'success') {
        titleEl.style.color = 'var(--success)';
    } else if (type === 'error') {
        titleEl.style.color = 'var(--error)';
    } else {
        titleEl.style.color = '';
    }

    // Show modal - must override inline style and add visible class
    modal.style.display = 'flex';
    modal.classList.add('visible');

    if (callback) {
        window.modalCallback = callback;
    }
}

function closeModal() {
    const modal = document.getElementById('messageModal');
    modal.style.display = 'none';
    modal.classList.remove('visible');
    if (window.modalCallback) {
        window.modalCallback();
        window.modalCallback = null;
    }
}

// Close modal when clicking outside
window.addEventListener('click', (e) => {
    const modal = document.getElementById('messageModal');
    if (e.target === modal) {
        closeModal();
    }
});
