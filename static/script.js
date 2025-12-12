/**
 * MockFlow-AI Client-Side JavaScript
 * Form handling and validation
 */

(function() {
    'use strict';
    
    document.addEventListener('DOMContentLoaded', init);
    
    function init() {
        initFormHandler();
        initInputValidation();
    }
    
    function initFormHandler() {
        const form = document.getElementById('candidateForm');
        if (!form) return;
        
        form.addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = new FormData(e.target);
            const data = {
                name: formData.get('name'),
                email: formData.get('email'),
                role: formData.get('role'),
                level: formData.get('level')
            };
            
            // Validate all fields
            let isValid = true;
            const inputs = form.querySelectorAll('.form-input');
            inputs.forEach(input => {
                if (!validateInput(input)) {
                    isValid = false;
                }
            });
            
            if (!isValid) {
                return;
            }
            
            // Show loading state
            const loadingEl = document.getElementById('loadingIndicator');
            const submitBtn = form.querySelector('button[type="submit"]');
            
            if (loadingEl) {
                loadingEl.classList.add('visible');
            }
            
            if (submitBtn) {
                submitBtn.disabled = true;
            }
            
            try {
                // Build URL params and redirect
                const params = new URLSearchParams(data);
                window.location.href = '/interview?' + params.toString();
                
            } catch (err) {
                console.error('[FORM] Submission error:', err);
                
                // Reset loading state
                if (loadingEl) {
                    loadingEl.classList.remove('visible');
                }
                
                if (submitBtn) {
                    submitBtn.disabled = false;
                }
            }
        });
    }
    
    function initInputValidation() {
        const inputs = document.querySelectorAll('.form-input');
        
        inputs.forEach(input => {
            input.addEventListener('blur', function() {
                validateInput(this);
            });
            
            input.addEventListener('input', function() {
                // Remove error on input
                this.classList.remove('input-error');
            });
        });
    }
    
    function validateInput(input) {
        const value = input.value.trim();
        
        // Email validation
        if (input.type === 'email' && value) {
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(value)) {
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
})();