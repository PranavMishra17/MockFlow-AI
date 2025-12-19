# MIGRATION.md - Production Migration Plan

Phased migration to production with Supabase backend and BYOK architecture. Each phase is self-contained and can be completed independently.

**Core Principles:**
- Maintain existing UI theme, colors, fonts, and styling
- Reuse existing CSS classes, modals, and button effects
- Keep localStorage fallback for transcripts and feedback
- No new features (subscriptions, payments, etc.)
- Iterative approach - each phase is complete before next begins

---

## Phase 1: Backend Foundation - Supabase Integration

**Goal**: Set up backend infrastructure with Supabase client and database operations.

**Prerequisites**: Complete PREREQUISITES.md setup  - DONE

### Files to Create

#### 1.1 Create `supabase_client.py`
**Location**: Root directory

**Purpose**: Single source of truth for all Supabase operations

**Implementation**:
```python
import os
from supabase import create_client, Client
from cryptography.fernet import Fernet
from typing import Optional, Dict, Any, List
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class SupabaseClient:
    def __init__(self):
        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_SERVICE_KEY')
        
        if not url or not key:
            raise ValueError("Missing Supabase credentials in environment")
        
        self.client: Client = create_client(url, key)
        self.encryption_key = os.getenv('ENCRYPTION_KEY', '').encode()
        self.cipher = Fernet(self.encryption_key) if self.encryption_key else None
        
    def _encrypt(self, text: str) -> str:
        """Encrypt sensitive data"""
        if not self.cipher:
            raise ValueError("Encryption key not configured")
        return self.cipher.encrypt(text.encode()).decode()
    
    def _decrypt(self, encrypted_text: str) -> str:
        """Decrypt sensitive data"""
        if not self.cipher:
            raise ValueError("Encryption key not configured")
        return self.cipher.decrypt(encrypted_text.encode()).decode()
    
    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        try:
            response = self.client.table('users').select('*').eq('id', user_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error fetching user: {e}")
            return None
    
    def save_api_keys(self, user_id: str, openai_key: str, deepgram_key: str) -> bool:
        """Save encrypted API keys for user"""
        try:
            encrypted_openai = self._encrypt(openai_key)
            encrypted_deepgram = self._encrypt(deepgram_key)
            
            response = self.client.table('user_api_keys').upsert({
                'user_id': user_id,
                'openai_key_encrypted': encrypted_openai,
                'deepgram_key_encrypted': encrypted_deepgram,
                'encryption_salt': 'salt_v1'
            }).execute()
            
            return True
        except Exception as e:
            logger.error(f"Error saving API keys: {e}")
            return False
    
    def get_api_keys(self, user_id: str) -> Optional[Dict[str, str]]:
        """Get decrypted API keys for user"""
        try:
            response = self.client.table('user_api_keys').select('*').eq('user_id', user_id).execute()
            
            if not response.data:
                return None
            
            keys = response.data[0]
            return {
                'openai_key': self._decrypt(keys['openai_key_encrypted']),
                'deepgram_key': self._decrypt(keys['deepgram_key_encrypted'])
            }
        except Exception as e:
            logger.error(f"Error fetching API keys: {e}")
            return None
    
    def save_interview(self, user_id: str, interview_data: Dict[str, Any]) -> Optional[str]:
        """Save interview to database, returns interview_id"""
        try:
            data = {
                'user_id': user_id,
                'candidate_name': interview_data.get('candidateName'),
                'room_name': interview_data.get('roomName'),
                'job_role': interview_data.get('jobRole'),
                'experience_level': interview_data.get('experienceLevel'),
                'final_stage': interview_data.get('finalStage'),
                'ended_by': interview_data.get('endedBy'),
                'skipped_stages': interview_data.get('skippedStages', []),
                'has_resume': interview_data.get('hasResume', False),
                'has_jd': interview_data.get('hasJobDescription', False),
                'conversation': interview_data.get('conversation', []),
                'total_messages': interview_data.get('totalMessages', {}),
                'metadata': interview_data.get('metadata', {})
            }
            
            response = self.client.table('interviews').insert(data).execute()
            return response.data[0]['id'] if response.data else None
        except Exception as e:
            logger.error(f"Error saving interview: {e}")
            return None
    
    def get_user_interviews(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all interviews for user"""
        try:
            response = self.client.table('interviews').select('*').eq('user_id', user_id).order('interview_date', desc=True).limit(limit).execute()
            return response.data
        except Exception as e:
            logger.error(f"Error fetching interviews: {e}")
            return []
    
    def get_interview_by_room(self, room_name: str) -> Optional[Dict[str, Any]]:
        """Get interview by room name"""
        try:
            response = self.client.table('interviews').select('*').eq('room_name', room_name).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error fetching interview: {e}")
            return None
    
    def save_feedback(self, user_id: str, interview_id: str, feedback_data: Dict[str, Any]) -> bool:
        """Save feedback for interview"""
        try:
            response = self.client.table('feedback').insert({
                'user_id': user_id,
                'interview_id': interview_id,
                'feedback_data': feedback_data
            }).execute()
            return True
        except Exception as e:
            logger.error(f"Error saving feedback: {e}")
            return False
    
    def get_feedback(self, interview_id: str) -> Optional[Dict[str, Any]]:
        """Get feedback for interview"""
        try:
            response = self.client.table('feedback').select('*').eq('interview_id', interview_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error fetching feedback: {e}")
            return None

supabase_client = SupabaseClient()
```

### Files to Modify

#### 1.2 Update `app.py` - Import Supabase Client
**Changes**:
- Add import at top:
```python
from supabase_client import supabase_client
```
- Add logging configuration:
```python
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
```

### Tasks Checklist

- [x] Create `supabase_client.py` with all CRUD operations
- [x] Add error handling with try-catch blocks
- [x] Implement encryption/decryption for API keys
- [x] Add comprehensive logging
- [x] Test connection with `test_supabase.py` (from PREREQUISITES)
- [x] Verify all methods work with Supabase dashboard
- [x] Commit changes: "Phase 1: Add Supabase client foundation"

**Phase 1 Complete**: Backend can now communicate with Supabase - DONE

---

## Phase 2: Authentication Foundation - Supabase Auth

**Goal**: Implement Google OAuth authentication using Supabase's built-in auth. - We have already enabled Gauth via SUPABASE free tier and Google cloud, with all api n other stuuf added in .env.development file. WE just need to integrate the asme 

**Duration**: 2-3 days

**Dependencies**: Phase 1 complete

### Files to Create

#### 2.1 Create `auth_helpers.py`
**Location**: Root directory

**Purpose**: Authentication utilities and session management

**Implementation**:
```python
import os
from functools import wraps
from flask import session, redirect, url_for, request, jsonify
from supabase import create_client
import logging

logger = logging.getLogger(__name__)

url = os.getenv('SUPABASE_URL')
anon_key = os.getenv('SUPABASE_ANON_KEY')
supabase = create_client(url, anon_key)

def get_current_user():
    """Get current authenticated user from session"""
    try:
        access_token = session.get('access_token')
        if not access_token:
            return None
        
        user = supabase.auth.get_user(access_token)
        return user
    except Exception as e:
        logger.error(f"Error getting current user: {e}")
        return None

def require_auth(f):
    """Decorator to protect routes requiring authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            if request.is_json:
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_user_id():
    """Extract user_id from session"""
    user = get_current_user()
    return user.user.id if user else None

def is_authenticated():
    """Check if user is authenticated"""
    return get_current_user() is not None
```

### Files to Modify

#### 2.2 Update `app.py` - Add Auth Routes
**Location**: `app.py`

**Changes**:
```python
from auth_helpers import require_auth, get_current_user, get_user_id, is_authenticated

# Add session secret key
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-prod')

@app.route('/auth/login')
def login():
    """Redirect to Supabase Google OAuth"""
    try:
        redirect_url = f"{request.host_url}auth/callback"
        auth_url = f"{os.getenv('SUPABASE_URL')}/auth/v1/authorize?provider=google&redirect_to={redirect_url}"
        return redirect(auth_url)
    except Exception as e:
        logger.error(f"Login error: {e}")
        return "Login failed", 500

@app.route('/auth/callback')
def auth_callback():
    """Handle OAuth callback from Supabase"""
    try:
        access_token = request.args.get('access_token')
        refresh_token = request.args.get('refresh_token')
        
        if not access_token:
            return "Authentication failed", 400
        
        session['access_token'] = access_token
        session['refresh_token'] = refresh_token
        
        return redirect(url_for('dashboard'))
    except Exception as e:
        logger.error(f"Auth callback error: {e}")
        return "Authentication failed", 500

@app.route('/auth/logout')
def logout():
    """Clear session and logout"""
    session.clear()
    return redirect(url_for('index'))

@app.route('/api/auth/status')
def auth_status():
    """Check authentication status"""
    try:
        user = get_current_user()
        if user:
            return jsonify({
                'authenticated': True,
                'user': {
                    'id': user.user.id,
                    'email': user.user.email,
                    'name': user.user.user_metadata.get('full_name'),
                    'avatar': user.user.user_metadata.get('avatar_url')
                }
            })
        return jsonify({'authenticated': False})
    except Exception as e:
        logger.error(f"Auth status error: {e}")
        return jsonify({'authenticated': False})
```

### Tasks Checklist

- [x] Create `auth_helpers.py` with authentication utilities
- [x] Update `app.py` with auth routes
- [x] Add session management
- [ ] Test login flow locally
- [ ] Test logout functionality
- [ ] Test auth status endpoint
- [x] Add error handling for all auth operations
- [ ] Commit changes: "Phase 2: Add Supabase authentication"

**Phase 2 Complete**: Users can now authenticate with Google - DONE

---

## Phase 3: Authentication UI - Login & Dashboard

**Goal**: Create login page and user dashboard with existing UI theme.

**Duration**: 1-2 days

**Dependencies**: Phase 2 complete

**UI Theme Reference**: Use existing CSS from `static/style.css`:
- Background: `#0a0a0a`
- Primary color: `#00ff00` (lime green)
- Secondary: `#00e5ff` (cyan)
- Card background: `rgba(255, 255, 255, 0.05)`
- Fonts: 'Space Mono', monospace
- Buttons: `.primary-btn`, `.secondary-btn` classes
- Modals: Reuse existing modal styles

### Files to Create

#### 3.1 Create `templates/login.html`
**Purpose**: Landing page for unauthenticated users

**Implementation**: Use existing theme from `index.html`
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MockFlow AI - Login</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>MockFlow AI</h1>
            <p class="subtitle">AI-Powered Technical Interview Practice</p>
        </div>

        <div class="content-card" style="max-width: 500px; margin: 0 auto;">
            <h2>Sign In to Continue</h2>
            <p style="color: #888; margin-bottom: 2rem;">
                Practice technical interviews with an AI interviewer
            </p>

            <button class="primary-btn" onclick="loginWithGoogle()" style="width: 100%;">
                <svg style="width: 20px; height: 20px; margin-right: 10px;" viewBox="0 0 24 24">
                    <path fill="currentColor" d="M12.545,10.239v3.821h5.445c-0.712,2.315-2.647,3.972-5.445,3.972c-3.332,0-6.033-2.701-6.033-6.032s2.701-6.032,6.033-6.032c1.498,0,2.866,0.549,3.921,1.453l2.814-2.814C17.503,2.988,15.139,2,12.545,2C7.021,2,2.543,6.477,2.543,12s4.478,10,10.002,10c8.396,0,10.249-7.85,9.426-11.748L12.545,10.239z"/>
                </svg>
                Continue with Google
            </button>

            <p style="color: #666; font-size: 0.875rem; margin-top: 2rem; text-align: center;">
                By signing in, you agree to our Terms of Service
            </p>
        </div>
    </div>

    <script>
        function loginWithGoogle() {
            window.location.href = '/auth/login';
        }
    </script>
</body>
</html>
```

#### 3.2 Create `templates/dashboard.html`
**Purpose**: User dashboard after login

**Implementation**: Reuse card styles from existing templates
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard - MockFlow AI</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    <div class="container">
        <!-- Reuse existing navigation structure -->
        <div class="header">
            <h1>MockFlow AI</h1>
            <div class="user-info">
                <img id="userAvatar" class="avatar" src="" alt="">
                <span id="userName"></span>
                <button class="secondary-btn" onclick="logout()">Logout</button>
            </div>
        </div>

        <div class="content-card">
            <h2>Welcome back, <span id="userNameDisplay"></span></h2>
            
            <!-- API Keys Status -->
            <div class="status-card" id="apiKeysStatus">
                <h3>API Keys</h3>
                <p id="keysStatusText">Loading...</p>
                <button class="primary-btn" onclick="manageKeys()">Manage API Keys</button>
            </div>

            <!-- Quick Actions -->
            <div class="actions-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem; margin: 2rem 0;">
                <button class="action-card" onclick="startInterview()" id="startInterviewBtn" disabled>
                    <h3>Start New Interview</h3>
                    <p>Practice technical interviews with AI</p>
                </button>
                
                <button class="action-card" onclick="viewHistory()">
                    <h3>Interview History</h3>
                    <p>Review past interviews and feedback</p>
                </button>
            </div>

            <!-- Recent Interviews -->
            <div id="recentInterviews">
                <h3>Recent Interviews</h3>
                <div id="interviewsList"></div>
            </div>
        </div>
    </div>

    <script src="{{ url_for('static', filename='auth.js') }}"></script>
    <script src="{{ url_for('static', filename='dashboard.js') }}"></script>
</body>
</html>
```

### Files to Modify

#### 3.3 Update `app.py` - Add Dashboard Route
```python
@app.route('/')
def index():
    """Landing page - redirect to dashboard if authenticated"""
    if is_authenticated():
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/dashboard')
@require_auth
def dashboard():
    """User dashboard"""
    return render_template('dashboard.html')
```

#### 3.4 Update `static/style.css` - Add Auth Components
**Add these classes** (following existing theme):
```css
/* User Info */
.user-info {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    border: 2px solid var(--primary-color);
}

/* Status Card */
.status-card {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 1.5rem;
    margin: 2rem 0;
}

/* Action Cards */
.action-card {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 2rem;
    cursor: pointer;
    transition: all 0.3s ease;
    text-align: left;
}

.action-card:hover:not(:disabled) {
    border-color: var(--primary-color);
    background: rgba(0, 255, 0, 0.05);
    transform: translateY(-2px);
}

.action-card:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}
```

#### 3.5 Create `static/auth.js`
**Purpose**: Frontend auth utilities

```javascript
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

async function logout() {
    try {
        window.location.href = '/auth/logout';
    } catch (error) {
        console.error('Logout failed:', error);
    }
}

async function requireAuth() {
    const auth = await checkAuthStatus();
    if (!auth.authenticated) {
        window.location.href = '/login';
        return null;
    }
    return auth.user;
}
```

#### 3.6 Create `static/dashboard.js`
**Purpose**: Dashboard functionality

```javascript
document.addEventListener('DOMContentLoaded', async () => {
    try {
        const user = await requireAuth();
        if (!user) return;

        document.getElementById('userName').textContent = user.name || user.email;
        document.getElementById('userNameDisplay').textContent = user.name || user.email;
        document.getElementById('userAvatar').src = user.avatar || '/static/default-avatar.png';

        await checkApiKeys();
        await loadRecentInterviews();
    } catch (error) {
        console.error('Dashboard initialization failed:', error);
    }
});

async function checkApiKeys() {
    try {
        const response = await fetch('/api/user/keys/status');
        const data = await response.json();
        
        const statusText = document.getElementById('keysStatusText');
        const startBtn = document.getElementById('startInterviewBtn');
        
        if (data.has_keys) {
            statusText.textContent = 'API keys configured';
            statusText.style.color = '#00ff00';
            startBtn.disabled = false;
        } else {
            statusText.textContent = 'Please configure your API keys to start interviews';
            statusText.style.color = '#ff9800';
            startBtn.disabled = true;
        }
    } catch (error) {
        console.error('Failed to check API keys:', error);
    }
}

function manageKeys() {
    window.location.href = '/api-keys';
}

function startInterview() {
    window.location.href = '/form';
}

function viewHistory() {
    window.location.href = '/past-calls';
}

async function loadRecentInterviews() {
    try {
        const response = await fetch('/api/user/interviews?limit=5');
        const interviews = await response.json();
        
        const list = document.getElementById('interviewsList');
        if (interviews.length === 0) {
            list.innerHTML = '<p style="color: #666;">No interviews yet. Start your first one!</p>';
            return;
        }
        
        list.innerHTML = interviews.map(interview => `
            <div class="interview-card" onclick="viewInterview('${interview.id}')">
                <h4>${interview.job_role} - ${interview.experience_level}</h4>
                <p>${new Date(interview.interview_date).toLocaleDateString()}</p>
            </div>
        `).join('');
    } catch (error) {
        console.error('Failed to load interviews:', error);
    }
}

function viewInterview(id) {
    window.location.href = `/feedback?id=${id}`;
}
```

### Tasks Checklist

- [x] Create `templates/login.html` with existing theme (Simplified - Login redirects to Supabase OAuth)
- [x] Create `templates/dashboard.html` with card layouts
- [x] Update `static/style.css` with auth components
- [x] Create `static/auth.js` utilities
- [x] Create `static/dashboard.js` functionality
- [x] Update `app.py` routes
- [x] Test login flow end-to-end
- [x] Test dashboard displays user info
- [x] Verify existing CSS classes work properly
- [x] Add Google avatar to Account button
- [x] Fix OAuth fragment token handling
- [x] Commit changes: "Phase 2 & 3: Add Supabase authentication with UI"

**Phase 3 Complete**: Users can log in and access dashboard - FULLY TESTED & WORKING ✓

**Implementation Notes**:
- Login/Signup buttons in header on index.html (unauthenticated state)
- Account button with Google avatar when logged in (authenticated state)
- API keys management integrated into dashboard (no separate page needed)
- OAuth callback handles fragment-based tokens correctly with client-side extraction
- Comprehensive logging for debugging auth flow

---

## Phase 4: API Key Management - BYOK Implementation ✅ COMPLETED

**Goal**: Allow users to save and manage their API keys (LiveKit, OpenAI, Deepgram) with full BYOK model.

**Dependencies**: Phase 3 complete

**Status**: ✅ Fully implemented with enhanced UX and security features

### Files to Create

#### 4.1 Create `templates/api_keys.html`
**Purpose**: API key management page

**Implementation**: Use existing form and modal styles
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API Keys - MockFlow AI</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>API Keys Management</h1>
            <button class="secondary-btn" onclick="goBack()">Back to Dashboard</button>
        </div>

        <div class="content-card">
            <div class="info-box">
                <h3>About API Keys (BYOK)</h3>
                <p>MockFlow AI uses your own API keys to conduct interviews. Your keys are encrypted and stored securely.</p>
                <ul>
                    <li>OpenAI API key: Used for LLM and text-to-speech</li>
                    <li>Deepgram API key: Used for speech-to-text</li>
                </ul>
            </div>

            <form id="apiKeysForm">
                <div class="form-group">
                    <label for="openaiKey">OpenAI API Key</label>
                    <input type="password" id="openaiKey" class="form-input" placeholder="sk-proj-..." required>
                    <small>Get your key from <a href="https://platform.openai.com/api-keys" target="_blank">OpenAI Platform</a></small>
                </div>

                <div class="form-group">
                    <label for="deepgramKey">Deepgram API Key</label>
                    <input type="password" id="deepgramKey" class="form-input" placeholder="..." required>
                    <small>Get your key from <a href="https://console.deepgram.com/" target="_blank">Deepgram Console</a></small>
                </div>

                <div class="button-group">
                    <button type="button" class="secondary-btn" onclick="testKeys()">Test Keys</button>
                    <button type="submit" class="primary-btn">Save Keys</button>
                </div>
            </form>

            <div id="currentKeys" style="margin-top: 2rem;">
                <h3>Current Keys</h3>
                <p id="keysStatus">Loading...</p>
            </div>
        </div>
    </div>

    <!-- Reuse existing modal styles -->
    <div id="messageModal" class="modal">
        <div class="modal-content">
            <h3 id="modalTitle"></h3>
            <p id="modalMessage"></p>
            <button class="primary-btn" onclick="closeModal()">OK</button>
        </div>
    </div>

    <script src="{{ url_for('static', filename='auth.js') }}"></script>
    <script src="{{ url_for('static', filename='apikeys.js') }}"></script>
</body>
</html>
```

#### 4.2 Create `static/apikeys.js` - file is already there - but the code there is non-implmeneted / leftover 

**Purpose**: API key management logic

```javascript
document.addEventListener('DOMContentLoaded', async () => {
    await requireAuth();
    await loadCurrentKeys();
});

async function loadCurrentKeys() {
    try {
        const response = await fetch('/api/user/keys/status');
        const data = await response.json();
        
        const status = document.getElementById('keysStatus');
        if (data.has_keys) {
            status.innerHTML = `
                <p style="color: #00ff00;">✓ Keys configured</p>
                <p style="font-size: 0.875rem; color: #666;">
                    OpenAI: ${data.openai_masked}<br>
                    Deepgram: ${data.deepgram_masked}
                </p>
            `;
        } else {
            status.innerHTML = '<p style="color: #ff9800;">No keys configured</p>';
        }
    } catch (error) {
        console.error('Failed to load keys status:', error);
    }
}

function validateKeys() {
    const openaiKey = document.getElementById('openaiKey').value.trim();
    const deepgramKey = document.getElementById('deepgramKey').value.trim();
    
    if (!openaiKey.startsWith('sk-')) {
        showModal('Invalid Key', 'OpenAI key should start with "sk-"');
        return false;
    }
    
    if (deepgramKey.length < 10) {
        showModal('Invalid Key', 'Deepgram key appears too short');
        return false;
    }
    
    return true;
}

async function testKeys() {
    if (!validateKeys()) return;
    
    const openaiKey = document.getElementById('openaiKey').value.trim();
    const deepgramKey = document.getElementById('deepgramKey').value.trim();
    
    try {
        const response = await fetch('/api/user/keys/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ openai_key: openaiKey, deepgram_key: deepgramKey })
        });
        
        const result = await response.json();
        
        if (result.valid) {
            showModal('Success', 'API keys are valid!');
        } else {
            showModal('Invalid Keys', result.message || 'One or more keys are invalid');
        }
    } catch (error) {
        console.error('Key validation failed:', error);
        showModal('Error', 'Failed to validate keys. Please try again.');
    }
}

document.getElementById('apiKeysForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    if (!validateKeys()) return;
    
    const openaiKey = document.getElementById('openaiKey').value.trim();
    const deepgramKey = document.getElementById('deepgramKey').value.trim();
    
    try {
        const response = await fetch('/api/user/keys', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ openai_key: openaiKey, deepgram_key: deepgramKey })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showModal('Success', 'API keys saved successfully!', () => {
                window.location.href = '/dashboard';
            });
        } else {
            showModal('Error', result.message || 'Failed to save keys');
        }
    } catch (error) {
        console.error('Failed to save keys:', error);
        showModal('Error', 'Failed to save keys. Please try again.');
    }
});

function showModal(title, message, callback = null) {
    document.getElementById('modalTitle').textContent = title;
    document.getElementById('modalMessage').textContent = message;
    document.getElementById('messageModal').style.display = 'flex';
    
    if (callback) {
        window.modalCallback = callback;
    }
}

function closeModal() {
    document.getElementById('messageModal').style.display = 'none';
    if (window.modalCallback) {
        window.modalCallback();
        window.modalCallback = null;
    }
}

function goBack() {
    window.location.href = '/dashboard';
}
```

### Files to Modify

#### 4.3 Update `app.py` - Add API Key Endpoints
```python
@app.route('/api-keys')
@require_auth
def api_keys_page():
    """API keys management page"""
    return render_template('api_keys.html')

@app.route('/api/user/keys/status')
@require_auth
def get_keys_status():
    """Check if user has API keys configured"""
    try:
        user_id = get_user_id()
        keys = supabase_client.get_api_keys(user_id)
        
        if keys:
            return jsonify({
                'has_keys': True,
                'openai_masked': f"sk-...{keys['openai_key'][-4:]}",
                'deepgram_masked': f"...{keys['deepgram_key'][-4:]}"
            })
        
        return jsonify({'has_keys': False})
    except Exception as e:
        logger.error(f"Failed to get keys status: {e}")
        return jsonify({'has_keys': False})

@app.route('/api/user/keys', methods=['POST'])
@require_auth
def save_user_keys():
    """Save user's API keys (encrypted)"""
    try:
        user_id = get_user_id()
        data = request.json
        
        openai_key = data.get('openai_key')
        deepgram_key = data.get('deepgram_key')
        
        if not openai_key or not deepgram_key:
            return jsonify({'error': 'Both keys required'}), 400
        
        success = supabase_client.save_api_keys(user_id, openai_key, deepgram_key)
        
        if success:
            return jsonify({'message': 'Keys saved successfully'})
        
        return jsonify({'error': 'Failed to save keys'}), 500
    except Exception as e:
        logger.error(f"Failed to save keys: {e}")
        return jsonify({'error': 'Internal error'}), 500

@app.route('/api/user/keys/validate', methods=['POST'])
@require_auth
def validate_keys():
    """Test API keys validity"""
    try:
        data = request.json
        openai_key = data.get('openai_key')
        deepgram_key = data.get('deepgram_key')
        
        # Quick validation - just check format and basic connectivity
        # Full validation happens during actual interview
        
        if not openai_key.startswith('sk-'):
            return jsonify({'valid': False, 'message': 'Invalid OpenAI key format'})
        
        if len(deepgram_key) < 10:
            return jsonify({'valid': False, 'message': 'Invalid Deepgram key format'})
        
        return jsonify({'valid': True})
    except Exception as e:
        logger.error(f"Key validation failed: {e}")
        return jsonify({'valid': False, 'message': 'Validation error'}), 500
```

### Implementation Summary

**What Was Actually Built** (beyond the original plan):

#### Core Features
- ✅ **Full BYOK Implementation**: All 5 API keys (LiveKit URL, LiveKit API Key, LiveKit API Secret, OpenAI, Deepgram)
- ✅ **Dedicated API Keys Page**: Professional UI with custom styling matching app theme
- ✅ **Encrypted Storage**: Fernet encryption (AES-128-CBC + HMAC) at application layer
- ✅ **Smart Database Operations**: INSERT for new keys, UPDATE for existing (no upsert conflicts)

#### Enhanced UX Features
- ✅ **Masked Keys Display**: Shows `••••••` for existing keys with disabled form
- ✅ **Smart Button States**: "Save Keys" vs "Update Keys", enabled only when modified
- ✅ **Interactive Edit Mode**: Click any field to clear mask and enable editing
- ✅ **Proper Feedback Modals**: Success (green), Error (red), with auto-redirect
- ✅ **Status Indicators**: Visual badges showing key configuration status
- ✅ **Loading States**: "Saving..." button text during operations

#### Security & Validation
- ✅ **Client-Side Validation**: Format checks before API calls
- ✅ **Server-Side Validation**: Additional checks in backend
- ✅ **Test Keys Feature**: Validate key formats without saving
- ✅ **Secure Display**: Masked values in status, never show full keys
- ✅ **Detailed Security Info**: User-friendly explanation of encryption method

#### Settings Modal Enhancement
- ✅ **Smart Modal**: Shows different content based on auth status
  - **Authenticated Users**: Buttons to Dashboard and API Keys page
  - **Guest Users**: Full localStorage-based API keys form
- ✅ **Seamless Integration**: No breaking changes to existing guest flow

#### Technical Improvements
- ✅ **Added `requireAuth()`**: Missing function in auth.js
- ✅ **Modal System Fix**: Changed from inline styles to CSS classes
- ✅ **Initialization Safety**: Waits for dependencies, handles race conditions
- ✅ **Comprehensive Logging**: Debug logs at every step
- ✅ **Error Handling**: Graceful degradation with user-friendly messages

#### Database Schema
- ✅ **Migration SQL**: Added 3 new encrypted columns to `user_api_keys` table
- ✅ **Documentation**: Comments on table structure and encryption

### Files Created/Modified

#### Created
1. **`templates/api_keys.html`** - Dedicated API keys management page
2. **`static/apikeys.js`** - Full UX logic with validation and feedback
3. **`add_livekit_keys_migration.sql`** - Database migration script

#### Modified
1. **`templates/dashboard.html`** - Removed inline modal, added link to API keys page
2. **`templates/index.html`** - Enhanced settings modal with auth-aware content
3. **`static/dashboard.js`** - Updated API endpoints and simplified status display
4. **`static/auth.js`** - Added missing `requireAuth()` function
5. **`static/modal.js`** - Added auth check and view toggling for settings modal
6. **`app.py`** - Added 4 new endpoints (page route, status, save, validate)
7. **`supabase_client.py`** - Extended to handle all 5 API keys with INSERT/UPDATE logic

### API Endpoints Implemented

```
GET  /api-keys                    - API keys management page (protected)
GET  /api/user/keys/status        - Get keys status with masked values
POST /api/user/keys               - Save/update encrypted keys
POST /api/user/keys/validate      - Validate key formats
```

### Testing Checklist

- ✅ Create `templates/api_keys.html` with professional UI
- ✅ Create `static/apikeys.js` with full UX logic
- ✅ Update `app.py` with all key management endpoints
- ✅ Update `supabase_client.py` for 5 keys + INSERT/UPDATE
- ✅ Add `requireAuth()` to `auth.js`
- ✅ Fix modal display system (CSS classes)
- ✅ Test key saving (first time - INSERT)
- ✅ Test key updating (existing - UPDATE, no 409 error)
- ✅ Test key encryption (Fernet encryption working)
- ✅ Test key retrieval (decryption working)
- ✅ Test key masking (shows `•••` on reload)
- ✅ Test edit mode (click field clears mask, enables form)
- ✅ Test save button states (disabled until modified)
- ✅ Test validation (format checks working)
- ✅ Test success modal (green title, auto-redirect)
- ✅ Test error modal (red title, clear messages)
- ✅ Test dashboard status display (shows "configured")
- ✅ Test settings modal (authenticated vs guest views)
- ✅ Test initialization (waits for auth.js, handles errors)
- ✅ Run SQL migration on Supabase database

### User Experience Flow

**First Time Setup:**
1. User navigates to Dashboard → Manage Keys
2. Page loads with empty form, "Save Keys" button enabled
3. User enters all 5 API keys (LiveKit URL/Key/Secret, OpenAI, Deepgram)
4. User clicks "Test Keys" (optional) - validates formats
5. User clicks "Save Keys" → Button shows "Saving..."
6. Success modal appears (green) → Auto-redirects to dashboard
7. Dashboard shows "API Keys Configured ✓"

**Updating Keys:**
1. User navigates to Dashboard → Manage Keys
2. Page loads with masked `••••••` values, form disabled
3. Status shows "API Keys Configured ✓"
4. Button says "Update Keys" (disabled)
5. User clicks any field → Mask clears, form enables
6. User modifies key(s) → Button becomes enabled
7. User saves → Success modal → Redirect

**Settings Modal (Index Page):**
- **Guest**: Shows full API keys form (localStorage)
- **Authenticated**: Shows "Go to Dashboard" and "Manage API Keys" buttons

### Security Implementation

**Encryption**: Fernet (symmetric encryption)
- **Algorithm**: AES-128-CBC with HMAC for authentication
- **Key Derivation**: From `ENCRYPTION_KEY` environment variable
- **Encryption Layer**: Application-level (before database)
- **Storage**: Only encrypted ciphertext stored in Supabase
- **Transmission**: Keys encrypted before sending to DB

**Display Security**:
- Never show full keys in UI after saving
- Masked display: `••••••••••••••••••••••••••`
- Status shows minimal info: "API Keys Configured"

### Known Limitations

None - all features working as expected with comprehensive error handling and user feedback.

**Phase 4 Complete**: Users can save and manage API keys

---

## Phase 5: Interview Database Integration

**Goal**: Save interviews and feedback to Supabase, maintain localStorage fallback.

**Dependencies**: Phase 4 complete

### Files to Modify

#### 5.1 Update `app.py` - Interview Storage Endpoints
```python
@app.route('/api/user/interviews')
@require_auth
def get_user_interviews():
    """Get user's interview history"""
    try:
        user_id = get_user_id()
        limit = request.args.get('limit', 50, type=int)
        
        interviews = supabase_client.get_user_interviews(user_id, limit)
        return jsonify(interviews)
    except Exception as e:
        logger.error(f"Failed to fetch interviews: {e}")
        return jsonify([])

@app.route('/api/interview/save', methods=['POST'])
@require_auth
def save_interview():
    """Save interview to database (with localStorage fallback)"""
    try:
        user_id = get_user_id()
        data = request.json
        
        # Try to save to database
        interview_id = supabase_client.save_interview(user_id, data)
        
        if interview_id:
            logger.info(f"Interview saved to database: {interview_id}")
            return jsonify({
                'success': True,
                'interview_id': interview_id,
                'saved_to': 'database'
            })
        else:
            # Database save failed, rely on localStorage fallback
            logger.warning("Database save failed, using localStorage fallback")
            return jsonify({
                'success': False,
                'message': 'Database save failed, data saved locally',
                'saved_to': 'localStorage'
            }), 500
    except Exception as e:
        logger.error(f"Interview save error: {e}")
        return jsonify({
            'success': False,
            'message': str(e),
            'saved_to': 'localStorage'
        }), 500

@app.route('/api/feedback/save', methods=['POST'])
@require_auth
def save_feedback_endpoint():
    """Save feedback to database (with localStorage fallback)"""
    try:
        user_id = get_user_id()
        data = request.json
        
        interview_id = data.get('interview_id')
        feedback_data = data.get('feedback')
        
        if not interview_id:
            return jsonify({'error': 'interview_id required'}), 400
        
        success = supabase_client.save_feedback(user_id, interview_id, feedback_data)
        
        if success:
            return jsonify({
                'success': True,
                'saved_to': 'database'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Database save failed, using localStorage',
                'saved_to': 'localStorage'
            }), 500
    except Exception as e:
        logger.error(f"Feedback save error: {e}")
        return jsonify({
            'success': False,
            'message': str(e),
            'saved_to': 'localStorage'
        }), 500

@app.route('/api/feedback/<interview_id>')
@require_auth
def get_feedback(interview_id):
    """Get feedback for interview"""
    try:
        user_id = get_user_id()
        
        # First check database
        feedback = supabase_client.get_feedback(interview_id)
        
        if feedback:
            # Verify user owns this interview
            interview = supabase_client.get_interview_by_room(interview_id)
            if interview and interview['user_id'] == user_id:
                return jsonify(feedback['feedback_data'])
        
        # Fallback to localStorage will be handled by frontend
        return jsonify({}), 404
    except Exception as e:
        logger.error(f"Feedback fetch error: {e}")
        return jsonify({}), 500
```

#### 5.2 Update `templates/interview.html` - Add Save Logic
**Add at end of file before closing `</body>`**:

```javascript
// Save interview after completion
async function saveInterviewData(interviewData) {
    try {
        // First, try to save to database
        const response = await fetch('/api/interview/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(interviewData)
        });
        
        const result = await response.json();
        
        if (result.success && result.saved_to === 'database') {
            console.log('Interview saved to database:', result.interview_id);
            
            // Also save to localStorage as backup
            const roomName = interviewData.roomName;
            localStorage.setItem(`interview_${roomName}`, JSON.stringify(interviewData));
            
            return result.interview_id;
        } else {
            // Database failed, rely on localStorage
            console.warn('Database save failed, using localStorage fallback');
            const roomName = interviewData.roomName;
            localStorage.setItem(`interview_${roomName}`, JSON.stringify(interviewData));
            return null;
        }
    } catch (error) {
        console.error('Failed to save interview:', error);
        
        // Always save to localStorage as fallback
        const roomName = interviewData.roomName;
        localStorage.setItem(`interview_${roomName}`, JSON.stringify(interviewData));
        return null;
    }
}

// Hook into existing disconnect handler
const originalOnDisconnect = room.on('disconnected', async () => {
    // ... existing code ...
    
    // Save interview data
    const interviewData = {
        candidateName: '{{ name }}',
        roomName: roomName,
        jobRole: '{{ role }}',
        experienceLevel: '{{ level }}',
        conversation: conversation,
        // ... other fields ...
    };
    
    await saveInterviewData(interviewData);
});
```

#### 5.3 Update `templates/feedback.html` - Database Integration
**Add at start of `<script>` section**:

```javascript
async function loadFeedback() {
    const urlParams = new URLSearchParams(window.location.search);
    const interviewId = urlParams.get('id');
    const roomName = urlParams.get('room');
    
    if (!interviewId && !roomName) {
        showError('No interview specified');
        return;
    }
    
    try {
        // Try to load from database first
        if (interviewId) {
            const response = await fetch(`/api/feedback/${interviewId}`);
            if (response.ok) {
                const feedback = await response.json();
                displayFeedback(feedback);
                return;
            }
        }
        
        // Fallback to localStorage
        if (roomName) {
            const localData = localStorage.getItem(`feedback_${roomName}`);
            if (localData) {
                const feedback = JSON.parse(localData);
                displayFeedback(feedback);
                return;
            }
        }
        
        showError('Feedback not found');
    } catch (error) {
        console.error('Failed to load feedback:', error);
        
        // Try localStorage fallback
        if (roomName) {
            const localData = localStorage.getItem(`feedback_${roomName}`);
            if (localData) {
                const feedback = JSON.parse(localData);
                displayFeedback(feedback);
                return;
            }
        }
        
        showError('Failed to load feedback');
    }
}

// Call on page load
document.addEventListener('DOMContentLoaded', loadFeedback);
```

#### 5.4 Update `templates/past_calls.html` - Database Integration
**Replace existing localStorage code**:

```javascript
async function loadInterviews() {
    try {
        // Try to load from database
        const response = await fetch('/api/user/interviews?limit=50');
        
        if (response.ok) {
            const interviews = await response.json();
            
            if (interviews.length > 0) {
                displayInterviews(interviews, 'database');
                
                // Also check localStorage for any not in database
                mergeLocalStorageInterviews(interviews);
                return;
            }
        }
        
        // Fallback to localStorage only
        loadLocalStorageInterviews();
    } catch (error) {
        console.error('Failed to load interviews:', error);
        loadLocalStorageInterviews();
    }
}

function displayInterviews(interviews, source) {
    const container = document.getElementById('interviewsList');
    
    if (interviews.length === 0) {
        container.innerHTML = '<p style="color: #666;">No interviews yet.</p>';
        return;
    }
    
    container.innerHTML = interviews.map(interview => `
        <div class="interview-card" onclick="viewInterview('${interview.id}', '${interview.room_name}')">
            <div class="interview-header">
                <h3>${interview.job_role}</h3>
                <span class="badge">${interview.experience_level}</span>
            </div>
            <p class="interview-date">${new Date(interview.interview_date).toLocaleDateString()}</p>
            <p class="interview-meta">
                Final Stage: ${interview.final_stage} | 
                ${interview.conversation?.length || 0} messages
            </p>
            ${source === 'localStorage' ? '<span class="local-badge">Local Only</span>' : ''}
        </div>
    `).join('');
}

function mergeLocalStorageInterviews(dbInterviews) {
    const dbRoomNames = new Set(dbInterviews.map(i => i.room_name));
    const localInterviews = [];
    
    // Check localStorage for interviews not in database
    for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key.startsWith('interview_')) {
            try {
                const data = JSON.parse(localStorage.getItem(key));
                if (!dbRoomNames.has(data.roomName)) {
                    localInterviews.push({
                        ...data,
                        id: null,
                        room_name: data.roomName,
                        interview_date: data.timestamp || new Date().toISOString()
                    });
                }
            } catch (e) {
                console.error('Failed to parse local interview:', e);
            }
        }
    }
    
    if (localInterviews.length > 0) {
        const allInterviews = [...dbInterviews, ...localInterviews];
        displayInterviews(allInterviews, 'mixed');
    }
}

function loadLocalStorageInterviews() {
    const interviews = [];
    
    for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key.startsWith('interview_')) {
            try {
                const data = JSON.parse(localStorage.getItem(key));
                interviews.push({
                    ...data,
                    id: null,
                    room_name: data.roomName,
                    interview_date: data.timestamp || new Date().toISOString()
                });
            } catch (e) {
                console.error('Failed to parse local interview:', e);
            }
        }
    }
    
    displayInterviews(interviews, 'localStorage');
}

function viewInterview(id, roomName) {
    if (id) {
        window.location.href = `/feedback?id=${id}`;
    } else {
        window.location.href = `/feedback?room=${roomName}`;
    }
}

// Load on page load
document.addEventListener('DOMContentLoaded', loadInterviews);
```

### Tasks Checklist

- [ ] Update `app.py` with interview/feedback endpoints
- [ ] Modify `templates/interview.html` to save to database
- [ ] Update `templates/feedback.html` with fallback logic
- [ ] Update `templates/past_calls.html` with merge logic
- [ ] Test database save success case
- [ ] Test localStorage fallback when database fails
- [ ] Test loading from both sources
- [ ] Test merge logic for mixed data
- [ ] Add CSS for "Local Only" badge
- [ ] Commit changes: "Phase 5: Add database storage with fallback"

**Phase 5 Complete**: Interviews save to database with localStorage fallback

---

## Phase 6: Agent BYOK Integration

**Goal**: Modify agent to use user-provided API keys from participant attributes.

**Duration**: 2-3 days

**Dependencies**: Phase 5 complete

### Files to Modify

#### 6.1 Update `app.py` - Token Generation with Keys
**Modify `/api/token` endpoint**:

```python
@app.route("/api/token", methods=["POST"])
@require_auth
def api_token():
    """Generate LiveKit token with user's API keys"""
    try:
        user_id = get_user_id()
        data = request.json
        
        room_name = data.get("roomName")
        participant_name = data.get("participantName")
        
        if not room_name or not participant_name:
            return jsonify({"error": "Missing required fields"}), 400
        
        # Get user's API keys
        keys = supabase_client.get_api_keys(user_id)
        
        if not keys:
            return jsonify({"error": "Please configure your API keys first"}), 400
        
        # Create token with API keys in participant attributes
        token = api.AccessToken(
            os.getenv("LIVEKIT_API_KEY"),
            os.getenv("LIVEKIT_API_SECRET")
        )
        
        token.with_identity(participant_name)
        token.with_name(participant_name)
        token.with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
        ))
        
        # Add user's API keys to participant attributes
        token.with_attributes({
            "user_id": user_id,
            "openai_api_key": keys['openai_key'],
            "deepgram_api_key": keys['deepgram_key'],
            "job_role": data.get("jobRole", ""),
            "experience_level": data.get("experienceLevel", ""),
        })
        
        jwt_token = token.to_jwt()
        
        logger.info(f"Token generated for user {user_id} in room {room_name}")
        
        return jsonify({"token": jwt_token})
    except Exception as e:
        logger.error(f"Token generation failed: {e}")
        return jsonify({"error": "Token generation failed"}), 500
```

#### 6.2 Update `agent.py` - Extract Keys from Attributes
**Modify at the start of `entrypoint()` function** (around line 482):

```python
async def entrypoint(ctx: JobContext):
    try:
        logger.info("[ENTRY] Starting agent job")
        
        # Connect to room
        await ctx.connect()
        
        # Get participant attributes with API keys
        participant = await ctx.wait_for_participant()
        attrs = participant.attributes
        
        # Extract user's API keys from participant attributes
        openai_api_key = attrs.get('openai_api_key')
        deepgram_api_key = attrs.get('deepgram_api_key')
        user_id = attrs.get('user_id')
        
        logger.info(f"[BYOK] User ID: {user_id}")
        logger.info(f"[BYOK] OpenAI key present: {bool(openai_api_key)}")
        logger.info(f"[BYOK] Deepgram key present: {bool(deepgram_api_key)}")
        
        # Validate keys are present
        if not openai_api_key or not deepgram_api_key:
            logger.error("[BYOK] Missing API keys in participant attributes")
            await ctx.room.disconnect()
            return
        
        # Override environment variables for this session
        os.environ['OPENAI_API_KEY'] = openai_api_key
        os.environ['DEEPGRAM_API_KEY'] = deepgram_api_key
        
        logger.info("[BYOK] API keys injected for this session")
        
        # Continue with existing agent logic...
```

**Remove module-level API key loading** (around lines 43-73):
```python
# DELETE THESE LINES:
# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
# if not OPENAI_API_KEY or not DEEPGRAM_API_KEY:
#     raise ValueError("API keys not found")
```

#### 6.3 Update `agent.py` - Save Interview to Database
**Modify `finalize_and_disconnect()` function**:

```python
async def finalize_and_disconnect(ctx: JobContext, participant, interview_data, user_id):
    """Save interview to database before disconnecting"""
    try:
        logger.info("[FINALIZE] Saving interview to database")
        
        # Import here to avoid circular dependency
        from supabase_client import supabase_client
        
        # Save to database
        interview_id = supabase_client.save_interview(user_id, interview_data)
        
        if interview_id:
            logger.info(f"[FINALIZE] Interview saved: {interview_id}")
        else:
            logger.warning("[FINALIZE] Database save failed, data will be in localStorage fallback")
        
        # Generate and save feedback if interview completed
        if interview_data.get('finalStage') == 'completed':
            feedback = generate_feedback(interview_data)
            supabase_client.save_feedback(user_id, interview_id, feedback)
            logger.info("[FINALIZE] Feedback saved")
        
    except Exception as e:
        logger.error(f"[FINALIZE] Error saving interview: {e}")
    finally:
        # Always disconnect
        await ctx.room.disconnect()
        logger.info("[FINALIZE] Disconnected from room")
```

### Tasks Checklist

- [ ] Update `app.py` token generation with API keys
- [ ] Remove module-level API keys from `agent.py`
- [ ] Add key extraction from participant attributes
- [ ] Add per-session key injection
- [ ] Update interview saving to database
- [ ] Add feedback saving to database
- [ ] Test BYOK flow end-to-end
- [ ] Test key isolation between sessions
- [ ] Verify database saves work
- [ ] Test fallback when database fails
- [ ] Add logging for debugging
- [ ] Commit changes: "Phase 6: Implement BYOK in agent"

**Phase 6 Complete**: Agent uses user-provided API keys per session

---

## Phase 7: Final Integration & Testing

**Goal**: End-to-end testing, bug fixes, and production readiness.

**Duration**: 2-3 days

**Dependencies**: Phases 1-6 complete

### Testing Checklist

#### 7.1 Authentication Flow
- [ ] Test Google OAuth login
- [ ] Test session persistence
- [ ] Test logout functionality
- [ ] Test protected routes redirect to login
- [ ] Test auth status API endpoint

#### 7.2 API Key Management
- [ ] Test key saving and encryption
- [ ] Test key retrieval and masking
- [ ] Test key validation
- [ ] Test UI shows correct status
- [ ] Test error messages display correctly

#### 7.3 Interview Flow
- [ ] Test starting interview with configured keys
- [ ] Test interview blocks without keys
- [ ] Test agent receives keys correctly
- [ ] Test interview saves to database
- [ ] Test localStorage fallback works
- [ ] Test feedback generation
- [ ] Test feedback saves to database

#### 7.4 Data Display
- [ ] Test dashboard shows user info
- [ ] Test dashboard shows key status
- [ ] Test past interviews load from database
- [ ] Test past interviews merge with localStorage
- [ ] Test feedback displays correctly
- [ ] Test interview details display correctly

#### 7.5 Error Handling
- [ ] Test database connection failures
- [ ] Test invalid API keys
- [ ] Test network errors
- [ ] Test missing participant attributes
- [ ] Test concurrent sessions with different keys

#### 7.6 UI Consistency
- [ ] Verify all pages use consistent theme
- [ ] Verify buttons match existing styles
- [ ] Verify modals reuse existing CSS
- [ ] Verify forms match existing design
- [ ] Verify color scheme is consistent

### Bug Fixes Checklist
- [ ] Fix any auth edge cases
- [ ] Fix any database query issues
- [ ] Fix any UI inconsistencies
- [ ] Fix any error handling gaps
- [ ] Fix any logging issues

### Performance Testing
- [ ] Test with multiple concurrent users
- [ ] Test database query performance
- [ ] Test encryption/decryption speed
- [ ] Test page load times
- [ ] Test interview latency

### Security Audit
- [ ] Verify RLS policies work
- [ ] Verify keys are encrypted
- [ ] Verify service key not exposed
- [ ] Verify session security
- [ ] Verify CORS settings
- [ ] Verify input validation

### Documentation Updates
- [ ] Update README with new setup steps
- [ ] Add BYOK explanation
- [ ] Document environment variables
- [ ] Add troubleshooting section
- [ ] Update architecture diagrams

### Deployment Preparation
- [ ] Create `.env.production`
- [ ] Test production build
- [ ] Verify all migrations applied
- [ ] Test with production Supabase
- [ ] Configure production LiveKit
- [ ] Set up monitoring/logging

### Final Tasks
- [ ] Code cleanup and comments
- [ ] Remove debug logging
- [ ] Optimize database queries
- [ ] Run security scan
- [ ] Final commit: "Phase 7: Production ready"

**Phase 7 Complete**: Application ready for production deployment

---

## Deployment Commands

### Local Testing
```bash
# Load development environment
source .env.development

# Start Flask app
python app.py

# In another terminal, start agent worker
python agent.py
```

### Production Deployment
```bash
# Load production environment
source .env.production

# Apply Supabase migrations
supabase db push

# Build and deploy (adjust for your hosting)
docker build -t mockflow-ai-web .
docker build -t mockflow-ai-agent -f Dockerfile.agent .

# Deploy to your hosting platform
# (Kubernetes, Heroku, AWS, etc.)
```

---

## Post-Migration Verification

After completing all phases:

1. **User Flow**:
   - [ ] User can sign in with Google
   - [ ] User can configure API keys
   - [ ] User can start interview
   - [ ] Interview data saves to database
   - [ ] Feedback generates correctly
   - [ ] User can view past interviews
   - [ ] User can view feedback reports

2. **Technical**:
   - [ ] Database has all expected data
   - [ ] RLS policies enforced
   - [ ] API keys encrypted
   - [ ] localStorage fallback works
   - [ ] All endpoints return correct status codes
   - [ ] Logs show no errors

3. **UI/UX**:
   - [ ] All pages use consistent theme
   - [ ] Navigation works smoothly
   - [ ] Loading states display correctly
   - [ ] Error messages are helpful
   - [ ] Mobile responsive

---

## Success Criteria

Migration is complete when:
- ✅ All 7 phases completed
- ✅ All tests passing
- ✅ No console errors
- ✅ Database properly configured
- ✅ BYOK working correctly
- ✅ localStorage fallback functional
- ✅ UI theme consistent throughout
- ✅ Production environment ready

---

## Rollback Plan

If issues arise:

1. **Phase 7 Issues**: Revert to Phase 6 commit
2. **Database Issues**: Use localStorage-only mode
3. **Auth Issues**: Temporarily disable auth (dev only)
4. **Critical Bugs**: Revert entire migration

Always keep backups of:
- Database schema
- Environment variables
- Working code commits

---

## Support & Maintenance

After deployment:

1. **Monitor**:
   - Database performance
   - API key usage
   - Error rates
   - User feedback

2. **Regular Tasks**:
   - Review logs weekly
   - Update dependencies monthly
   - Backup database daily
   - Rotate encryption keys quarterly

3. **User Support**:
   - Document common issues
   - Create FAQ section
   - Provide email support
   - Monitor user feedback