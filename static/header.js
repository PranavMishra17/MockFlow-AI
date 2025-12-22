/**
 * MockFlow-AI Core Header Component
 * Generates consistent headers across all pages
 */

(function() {
    'use strict';

    var HeaderConfig = {
        sponsorUrl: 'https://github.com/sponsors/PranavMishra17',
        githubUrl: 'https://github.com/PranavMishra17/MockFlow-AI',
        devImage: '/static/me.jpg'
    };

    var Icons = {
        home: '<svg class="home-logo" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="24" cy="24" r="20" fill="#C8E6C9"/><circle cx="24" cy="24" r="12" fill="#81C784"/><circle cx="24" cy="24" r="6" fill="#4CAF50"/></svg><svg class="home-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>',
        
        info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
        
        github: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.840 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.430.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>',
        
        sponsor: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>',
        
        settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>',
        
        user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
        
        key: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>'
    };

    window.MockFlowHeader = {
        /**
         * Initialize header based on page configuration
         * @param {Object} config - Configuration object
         * @param {boolean} config.showHome - Show home button (default: true, except index)
         * @param {boolean} config.showInfo - Show info/developer button (default: true)
         * @param {boolean} config.showGithub - Show GitHub button (default: true)
         * @param {boolean} config.showSponsor - Show sponsor button (default: true)
         * @param {boolean} config.showSettings - Show settings button (default: true)
         * @param {boolean} config.showAuth - Show auth header on left (default: false, only index)
         */
        init: function(config) {
            config = config || {};
            
            var defaults = {
                showHome: true,
                showInfo: true,
                showGithub: true,
                showSponsor: true,
                showSettings: true,
                showAuth: false
            };

            for (var key in defaults) {
                if (config[key] === undefined) {
                    config[key] = defaults[key];
                }
            }

            this.config = config;
            this.renderActionButtons();
            
            if (config.showAuth) {
                this.renderAuthHeader();
            }

            this.initSettingsDropdown();
            this.injectDeveloperModal();
            this.injectSettingsModal();
        },

        renderActionButtons: function() {
            var container = document.getElementById('actionButtons');
            if (!container) {
                container = document.createElement('div');
                container.id = 'actionButtons';
                container.className = 'action-buttons';
                document.body.appendChild(container);
            }

            var html = '';

            if (this.config.showHome) {
                html += '<a href="/" class="action-btn action-btn-home" title="Home">' + Icons.home + '</a>';
            }

            if (this.config.showInfo) {
                html += '<button onclick="window.MockFlowHeader.openDeveloperModal()" class="action-btn" title="About Developer">' + Icons.info + '</button>';
            }

            if (this.config.showGithub) {
                html += '<a href="' + HeaderConfig.githubUrl + '" target="_blank" rel="noopener" class="action-btn action-btn-primary" title="View on GitHub">' + Icons.github + '</a>';
            }

            if (this.config.showSponsor) {
                html += '<a href="' + HeaderConfig.sponsorUrl + '" target="_blank" rel="noopener" class="action-btn action-btn-sponsor" title="Sponsor">' + Icons.sponsor + '</a>';
            }

            if (this.config.showSettings) {
                html += '<div class="settings-dropdown" id="settingsDropdown">';
                html += '<button class="action-btn" title="Settings" onclick="window.MockFlowHeader.toggleSettingsDropdown()">' + Icons.settings + '</button>';
                html += '<div class="settings-dropdown-menu" id="settingsDropdownMenu">';
                html += '<a href="/dashboard" class="settings-dropdown-item">' + Icons.user + '<span>Account</span></a>';
                html += '<a href="/api-keys" class="settings-dropdown-item">' + Icons.key + '<span>API Keys</span></a>';
                html += '</div>';
                html += '</div>';
            }

            container.innerHTML = html;
        },

        renderAuthHeader: function() {
            var container = document.getElementById('authHeader');
            if (!container) {
                container = document.createElement('div');
                container.id = 'authHeader';
                container.className = 'auth-header';
                document.body.appendChild(container);
            }

            this.updateAuthHeader();
        },

        updateAuthHeader: async function() {
            var container = document.getElementById('authHeader');
            if (!container) return;

            try {
                var response = await fetch('/api/auth/status');
                var data = await response.json();

                if (data.authenticated && data.user) {
                    var initial = (data.user.name || data.user.email || 'U').charAt(0).toUpperCase();
                    var displayName = this.escapeHtml(data.user.name || 'Account');
                    container.innerHTML = 
                        '<a href="/dashboard" class="auth-btn" style="display: flex; align-items: center; gap: 0.5rem;">' +
                            '<div style="width: 28px; height: 28px; border-radius: 50%; background: linear-gradient(135deg, #81C784, #4CAF50); display: flex; align-items: center; justify-content: center; color: white; font-size: 0.8125rem; font-weight: 600; flex-shrink: 0;">' + initial + '</div>' +
                            '<span>' + displayName + '</span>' +
                        '</a>';
                } else {
                    container.innerHTML = 
                        '<a href="/auth/login" class="auth-btn">Log In</a>' +
                        '<a href="/auth/login" class="auth-btn primary">Sign Up</a>';
                }
            } catch (e) {
                console.error('[HEADER] Auth status check failed:', e);
                container.innerHTML = 
                    '<a href="/auth/login" class="auth-btn">Log In</a>' +
                    '<a href="/auth/login" class="auth-btn primary">Sign Up</a>';
            }
        },

        initSettingsDropdown: function() {
            document.addEventListener('click', function(e) {
                var dropdown = document.getElementById('settingsDropdown');
                var menu = document.getElementById('settingsDropdownMenu');
                if (dropdown && menu && !dropdown.contains(e.target)) {
                    menu.classList.remove('visible');
                }
            });
        },

        toggleSettingsDropdown: function() {
            var menu = document.getElementById('settingsDropdownMenu');
            if (menu) {
                menu.classList.toggle('visible');
            }
        },

        injectDeveloperModal: function() {
            if (document.getElementById('developerModal')) return;

            var modalHtml = 
                '<div id="developerModal" class="modal-overlay">' +
                    '<div class="modal-container">' +
                        '<div class="modal-header">' +
                            '<h2 class="modal-title">About the <span class="highlight">Developer</span></h2>' +
                            '<button class="modal-close" onclick="window.MockFlowHeader.closeDeveloperModal()" aria-label="Close">&times;</button>' +
                        '</div>' +
                        '<div class="modal-content">' +
                            '<div class="dev-profile">' +
                                '<div class="dev-avatar"><img src="' + HeaderConfig.devImage + '" alt="Pranav Mishra"></div>' +
                                '<div class="dev-info"><h3>Pranav Mishra</h3><p>AI/ML Engineer & Full-Stack Dev</p></div>' +
                            '</div>' +
                            '<div class="social-links">' +
                                '<a href="https://portfolio-pranav-mishra-paranoid.vercel.app" target="_blank" class="social-link social-portfolio"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>Portfolio</a>' +
                                '<a href="https://www.linkedin.com/in/pranavgamedev/" target="_blank" class="social-link social-linkedin"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>LinkedIn</a>' +
                                '<a href="https://portfolio-pranav-mishra-paranoid.vercel.app/resume" target="_blank" class="social-link social-resume"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>Resume</a>' +
                                '<a href="https://www.youtube.com/@parano1dgames/featured" target="_blank" class="social-link social-youtube"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>YouTube</a>' +
                                '<a href="https://huggingface.co/Paranoiid" target="_blank" class="social-link social-huggingface"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm6 13.5c-1.5 1.5-3.5 2.5-6 2.5s-4.5-1-6-2.5c0-2 4-3.5 6-3.5s6 1.5 6 3.5z"/></svg>HuggingFace</a>' +
                                '<a href="https://scholar.google.com/citations?user=_Twn_owAAAAJ&hl=en&oi=sra" target="_blank" class="social-link social-scholar"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M5.242 13.769L0 9.5 12 0l12 9.5-5.242 4.269C17.548 11.249 14.978 9.5 12 9.5c-2.977 0-5.548 1.748-6.758 4.269zM12 10a7 7 0 1 0 0 14 7 7 0 0 0 0-14z"/></svg>Scholar</a>' +
                            '</div>' +
                            '<div class="project-info">' +
                                '<div class="section-title"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>About this project</div>' +
                                '<p>MockFlow-AI helps you practice for interviews with AI-powered mock interviews. Future updates will include interview analysis, detailed feedback, and conversation history to help you track your progress across different roles.</p>' +
                                '<div class="project-actions">' +
                                    '<a href="' + HeaderConfig.githubUrl + '" target="_blank" class="github-link"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.840 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.430.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>Star on GitHub</a>' +
                                    '<a href="' + HeaderConfig.githubUrl + '/issues" target="_blank" class="bug-link"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>Report Bug</a>' +
                                '</div>' +
                                '<p class="license-text">Open Source - SAOUL License</p>' +
                            '</div>' +
                        '</div>' +
                        '<div class="modal-footer">' +
                            '<button onclick="window.MockFlowHeader.closeDeveloperModal()" class="modal-btn">Close</button>' +
                        '</div>' +
                    '</div>' +
                '</div>';

            document.body.insertAdjacentHTML('beforeend', modalHtml);

            var modal = document.getElementById('developerModal');
            modal.addEventListener('click', function(e) {
                if (e.target === modal) {
                    window.MockFlowHeader.closeDeveloperModal();
                }
            });
        },

        injectSettingsModal: function() {
            // Settings modal is now replaced by dropdown, but keep for backward compatibility
            // Individual pages can still use window.SettingsModal if they have custom implementations
        },

        openDeveloperModal: function() {
            var modal = document.getElementById('developerModal');
            if (modal) {
                modal.classList.add('visible');
            }
        },

        closeDeveloperModal: function() {
            var modal = document.getElementById('developerModal');
            if (modal) {
                modal.classList.remove('visible');
            }
        },

        escapeHtml: function(text) {
            if (!text) return '';
            var div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
    };

    // Also expose DeveloperModal for backward compatibility
    window.DeveloperModal = {
        open: function() { window.MockFlowHeader.openDeveloperModal(); },
        close: function() { window.MockFlowHeader.closeDeveloperModal(); }
    };
})();