/**
 * MockFlow-AI Client-Side JavaScript
 * Handles form submission and candidate data collection
 */

// Form submission handler
document.addEventListener('DOMContentLoaded', function() {
    const candidateForm = document.getElementById('candidateForm');

    if (candidateForm) {
        candidateForm.addEventListener('submit', async function(e) {
            e.preventDefault();

            // Get form data
            const formData = new FormData(e.target);
            const data = {
                name: formData.get('name'),
                email: formData.get('email'),
                role: formData.get('role'),
                level: formData.get('level')
            };

            // Validate data
            if (!data.name || !data.email || !data.role || !data.level) {
                alert('Please fill in all required fields');
                return;
            }

            // Show loading state
            const loadingEl = document.querySelector('.loading');
            const submitBtn = e.target.querySelector('button[type="submit"]');

            if (loadingEl) {
                loadingEl.style.display = 'flex';
            }

            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = 'Connecting...';
            }

            try {
                // Build URL params for interview page
                const params = new URLSearchParams(data);

                // Redirect to interview room
                window.location.href = `/interview?${params.toString()}`;

            } catch (error) {
                console.error('[ERROR] Form submission failed:', error);
                alert('Failed to start interview. Please try again.');

                // Reset loading state
                if (loadingEl) {
                    loadingEl.style.display = 'none';
                }

                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Start Interview';
                }
            }
        });
    }

    // Add input validation for better UX
    const inputs = document.querySelectorAll('.form-input');
    inputs.forEach(input => {
        input.addEventListener('blur', function() {
            validateInput(this);
        });

        input.addEventListener('input', function() {
            // Remove error styling on input
            if (this.classList.contains('input-error')) {
                this.classList.remove('input-error');
            }
        });
    });
});

/**
 * Validate individual input field
 */
function validateInput(input) {
    const value = input.value.trim();

    // Email validation
    if (input.type === 'email') {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (value && !emailRegex.test(value)) {
            input.classList.add('input-error');
            return false;
        }
    }

    // Required field validation
    if (input.hasAttribute('required') && !value) {
        input.classList.add('input-error');
        return false;
    }

    input.classList.remove('input-error');
    return true;
}

/**
 * Add error styling to CSS dynamically
 */
const style = document.createElement('style');
style.textContent = `
    .input-error {
        border-color: #EF4444 !important;
    }

    .input-error:focus {
        border-color: #DC2626 !important;
    }
`;
document.head.appendChild(style);
