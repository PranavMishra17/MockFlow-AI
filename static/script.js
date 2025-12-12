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
        updateButtonState();
    }
    
    function initFormHandler() {
        var form = document.getElementById('candidateForm');
        var submitBtn = document.getElementById('submitBtn');
        if (!form) return;
        
        // Handle form submission
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            handleSubmit();
        });
        
        // Also handle button click directly since button may be outside form
        if (submitBtn) {
            submitBtn.addEventListener('click', function(e) {
                e.preventDefault();
                if (!submitBtn.classList.contains('active')) {
                    console.log('[FORM] Button not active - fill all required fields');
                    return;
                }
                handleSubmit();
            });
        }
    }
    
    function handleSubmit() {
        var form = document.getElementById('candidateForm');
        var submitBtn = document.getElementById('submitBtn');
        
        if (!form) return;
        
        // Check if button is active
        if (submitBtn && !submitBtn.classList.contains('active')) {
            console.log('[FORM] Cannot submit - not all required fields filled');
            return;
        }
        
        var formData = new FormData(form);
        var data = {
            name: formData.get('name'),
            email: formData.get('email'),
            role: formData.get('role'),
            level: formData.get('level'),
            companyUrl: formData.get('companyUrl') || '',
            jobDescription: formData.get('jobDescription') || ''
        };
        
        // Validate required fields
        var isValid = true;
        var inputs = form.querySelectorAll('.form-input[required]');
        inputs.forEach(function(input) {
            if (!validateInput(input)) {
                isValid = false;
            }
        });
        
        if (!isValid) {
            console.log('[FORM] Validation failed');
            return;
        }
        
        console.log('[FORM] Submitting with data:', data);
        
        var loadingEl = document.getElementById('loadingIndicator');
        
        if (loadingEl) {
            loadingEl.classList.add('visible');
        }
        
        if (submitBtn) {
            submitBtn.disabled = true;
        }
        
        try {
            // Build URL params and redirect
            var params = new URLSearchParams({
                name: data.name,
                email: data.email,
                role: data.role,
                level: data.level,
                companyUrl: data.companyUrl
            });
            
            console.log('[FORM] Redirecting to interview page');
            window.location.href = '/interview?' + params.toString();
            
        } catch (err) {
            console.error('[FORM] Submission error:', err);
            
            if (loadingEl) {
                loadingEl.classList.remove('visible');
            }
            
            if (submitBtn) {
                submitBtn.disabled = false;
            }
        }
    }
    
    function initInputValidation() {
        var inputs = document.querySelectorAll('.form-input');
        
        inputs.forEach(function(input) {
            input.addEventListener('blur', function() {
                if (this.hasAttribute('required')) {
                    validateInput(this);
                }
            });
            
            input.addEventListener('input', function() {
                this.classList.remove('input-error');
                updateButtonState();
            });
            
            input.addEventListener('change', function() {
                updateButtonState();
            });
        });
    }
    
    function validateInput(input) {
        var value = input.value.trim();
        
        if (input.type === 'email' && value) {
            var emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(value)) {
                input.classList.add('input-error');
                return false;
            }
        }
        
        if (input.type === 'url' && value) {
            try {
                new URL(value);
            } catch (e) {
                input.classList.add('input-error');
                return false;
            }
        }
        
        if (input.hasAttribute('required') && !value) {
            input.classList.add('input-error');
            return false;
        }
        
        input.classList.remove('input-error');
        return true;
    }
    
    function updateButtonState() {
        var form = document.getElementById('candidateForm');
        var submitBtn = document.getElementById('submitBtn');
        if (!form || !submitBtn) return;
        
        var requiredInputs = form.querySelectorAll('.form-input[required]');
        var allFilled = true;
        
        requiredInputs.forEach(function(input) {
            if (!input.value.trim()) {
                allFilled = false;
            }
        });
        
        if (allFilled) {
            submitBtn.classList.add('active');
        } else {
            submitBtn.classList.remove('active');
        }
    }
})();