// Dashboard functionality

async function initDashboard() {
    try {
        const authData = await checkAuthStatus();

        if (!authData.authenticated || !authData.user) {
            window.location.href = '/auth/login';
            return;
        }

        const user = authData.user;

        // Populate user info
        document.getElementById('userName').textContent = user.name || user.email;
        document.getElementById('userEmail').textContent = user.email;

        // Set avatar placeholder with first letter
        const firstLetter = (user.name || user.email)[0].toUpperCase();
        document.getElementById('userAvatarPlaceholder').textContent = firstLetter;

        // Load API keys status
        await loadApiKeysStatus();
    } catch (error) {
        console.error('Dashboard initialization failed:', error);
    }
}

async function loadApiKeysStatus() {
    const statusDiv = document.getElementById('apiKeysStatus');

    try {
        const response = await fetch('/api/user/keys/status');
        const data = await response.json();

        if (data.has_keys) {
            statusDiv.innerHTML = `
                <div style="display: flex; align-items: center; gap: 0.75rem;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2">
                        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                        <polyline points="22 4 12 14.01 9 11.01"/>
                    </svg>
                    <div>
                        <p style="font-weight: 500; margin-bottom: 0.25rem;">API Keys Configured</p>
                        <p style="color: var(--text-muted); font-size: 0.8125rem;">All required keys are set</p>
                    </div>
                </div>
            `;
        } else {
            statusDiv.innerHTML = `
                <div style="display: flex; align-items: center; gap: 0.75rem;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--warning)" stroke-width="2">
                        <circle cx="12" cy="12" r="10"/>
                        <line x1="12" y1="8" x2="12" y2="12"/>
                        <line x1="12" y1="16" x2="12.01" y2="16"/>
                    </svg>
                    <div>
                        <p style="font-weight: 500; margin-bottom: 0.25rem;">API Keys Not Set</p>
                        <p style="color: var(--text-muted); font-size: 0.8125rem;">Configure your keys to start interviewing</p>
                    </div>
                </div>
            `;
        }
    } catch (error) {
        console.error('[DASHBOARD] Failed to load API keys status:', error);
        statusDiv.innerHTML = `
            <p style="color: var(--error); font-size: 0.875rem;">Failed to load API keys status</p>
        `;
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', initDashboard);
