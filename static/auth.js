// Authentication utilities and UI management

async function checkAuthStatus() {
    try {
        const response = await fetch('/api/auth/status');
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Auth check failed:', error);
        return { authenticated: false };
    }
}

async function requireAuth() {
    const authData = await checkAuthStatus();
    if (!authData.authenticated) {
        window.location.href = '/auth/login';
        throw new Error('Not authenticated');
    }
    return authData;
}

async function logout() {
    try {
        window.location.href = '/auth/logout';
    } catch (error) {
        console.error('Logout failed:', error);
    }
}

function renderAuthHeader(authData) {
    const authHeader = document.getElementById('authHeader');
    if (!authHeader) return;

    if (authData.authenticated && authData.user) {
        // User is logged in - show Account button with first letter avatar
        const userName = authData.user.name || authData.user.email;
        const firstLetter = userName.charAt(0).toUpperCase();

        authHeader.innerHTML = `
            <a href="/dashboard" class="auth-btn account-btn">
                <div class="auth-avatar-placeholder">${firstLetter}</div>
                <span>Account</span>
            </a>
        `;
    } else {
        // User is not logged in - show Login/Signup buttons
        authHeader.innerHTML = `
            <a href="/auth/login" class="auth-btn login-btn">
                <span>Log In</span>
            </a>
            <a href="/auth/login" class="auth-btn signup-btn">
                <span>Sign Up</span>
            </a>
        `;
    }
}

// Initialize auth header on page load
document.addEventListener('DOMContentLoaded', async () => {
    const authData = await checkAuthStatus();
    renderAuthHeader(authData);
});
