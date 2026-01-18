/**
 * Tennis Match Tracker - Frontend Application
 *
 * Handles user authentication, player search, and following.
 */

// Configuration - Update this with your Cloud Function URL
const API_BASE = window.location.hostname === 'localhost'
    ? 'http://localhost:8080'
    : 'https://us-central1-sportswatcher-tennis.cloudfunctions.net/api_gateway';

// State
let authToken = null;
let currentUser = null;
let searchTimeout = null;

// ==================== Initialization ====================

document.addEventListener('DOMContentLoaded', () => {
    initializeApp();
});

function initializeApp() {
    // Check for auth token in URL (OAuth callback)
    const urlParams = new URLSearchParams(window.location.search);
    const tokenFromUrl = urlParams.get('token');
    const error = urlParams.get('error');

    if (error) {
        showToast(`Login failed: ${error}`, 'error');
        window.history.replaceState({}, '', '/');
    } else if (tokenFromUrl) {
        authToken = tokenFromUrl;
        localStorage.setItem('authToken', tokenFromUrl);
        window.history.replaceState({}, '', '/');
        onAuthenticated();
    } else {
        // Check for existing token in localStorage
        authToken = localStorage.getItem('authToken');
        if (authToken) {
            onAuthenticated();
        }
    }

    updateUI();
}

async function onAuthenticated() {
    try {
        await loadUserProfile();
        await loadFollowedPlayers();
    } catch (error) {
        console.error('Authentication failed:', error);
        logout();
    }
}

// ==================== Authentication ====================

function initiateLogin() {
    // Redirect to OAuth flow
    window.location.href = `${API_BASE}/auth/google`;
}

function logout() {
    // Call logout endpoint
    if (authToken) {
        fetch(`${API_BASE}/auth/logout`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${authToken}` }
        }).catch(() => {});
    }

    // Clear local state
    authToken = null;
    currentUser = null;
    localStorage.removeItem('authToken');

    updateUI();
    showToast('Logged out successfully');
}

// ==================== User Profile ====================

async function loadUserProfile() {
    const response = await fetch(`${API_BASE}/user/profile`, {
        headers: { 'Authorization': `Bearer ${authToken}` }
    });

    if (!response.ok) {
        throw new Error('Failed to load profile');
    }

    currentUser = await response.json();
    updateUI();
}

// ==================== Player Search ====================

function debounceSearch(query) {
    clearTimeout(searchTimeout);

    const loadingEl = document.getElementById('search-loading');
    const resultsEl = document.getElementById('search-results');

    if (query.length < 2) {
        resultsEl.innerHTML = '';
        loadingEl.classList.add('hidden');
        return;
    }

    loadingEl.classList.remove('hidden');

    searchTimeout = setTimeout(() => searchPlayers(query), 300);
}

async function searchPlayers(query) {
    const loadingEl = document.getElementById('search-loading');
    const resultsEl = document.getElementById('search-results');

    try {
        const headers = authToken ? { 'Authorization': `Bearer ${authToken}` } : {};
        const response = await fetch(`${API_BASE}/players?q=${encodeURIComponent(query)}`, {
            headers
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Search failed');
        }

        renderSearchResults(data.players);
    } catch (error) {
        console.error('Search error:', error);
        resultsEl.innerHTML = `<p class="empty-state">Search failed: ${error.message}</p>`;
    } finally {
        loadingEl.classList.add('hidden');
    }
}

function renderSearchResults(players) {
    const container = document.getElementById('search-results');

    if (!players || players.length === 0) {
        container.innerHTML = '<p class="empty-state">No players found. Try a different search.</p>';
        return;
    }

    container.innerHTML = players.map(player => {
        const isFollowing = player.is_following || false;
        const buttonClass = isFollowing ? 'btn-unfollow' : 'btn-follow';
        const buttonText = isFollowing ? 'Following' : '+ Follow';
        const buttonAction = isFollowing
            ? `unfollowPlayer('${player.player_key}')`
            : `followPlayer('${player.player_key}', '${escapeHtml(player.name)}')`;
        const disabled = !authToken ? 'disabled' : '';

        return `
            <div class="player-card" data-player-key="${player.player_key}">
                <img src="${player.image_url || 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22%3E%3Ccircle cx=%2250%22 cy=%2250%22 r=%2240%22 fill=%22%23e9ecef%22/%3E%3C/svg%3E'}"
                     alt="${escapeHtml(player.name)}"
                     class="player-image"
                     onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22%3E%3Ccircle cx=%2250%22 cy=%2250%22 r=%2240%22 fill=%22%23e9ecef%22/%3E%3C/svg%3E'">
                <div class="player-info">
                    <h3>${escapeHtml(player.name)}</h3>
                    <p class="player-meta">
                        ${escapeHtml(player.country || '')} | ${player.tour || 'ATP'} #${player.ranking || 'NR'}
                    </p>
                </div>
                <button class="btn ${buttonClass}" onclick="${buttonAction}" ${disabled}>
                    ${buttonText}
                </button>
            </div>
        `;
    }).join('');
}

// ==================== Following Players ====================

async function followPlayer(playerKey, playerName) {
    if (!authToken) {
        showToast('Please sign in to follow players', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/players/follow`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ player_key: playerKey })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to follow player');
        }

        showToast(`Now following ${playerName}`, 'success');
        await loadFollowedPlayers();

        // Update search results to reflect new state
        const searchInput = document.getElementById('player-search');
        if (searchInput.value) {
            await searchPlayers(searchInput.value);
        }
    } catch (error) {
        showToast(`Failed to follow: ${error.message}`, 'error');
    }
}

async function unfollowPlayer(playerKey) {
    if (!authToken) return;

    try {
        const response = await fetch(`${API_BASE}/players/follow/${playerKey}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${authToken}` }
        });

        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Failed to unfollow');
        }

        showToast('Player unfollowed', 'success');
        await loadFollowedPlayers();

        // Update search results
        const searchInput = document.getElementById('player-search');
        if (searchInput.value) {
            await searchPlayers(searchInput.value);
        }
    } catch (error) {
        showToast(`Failed to unfollow: ${error.message}`, 'error');
    }
}

async function loadFollowedPlayers() {
    if (!authToken) return;

    try {
        const response = await fetch(`${API_BASE}/players/followed`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to load followed players');
        }

        renderFollowedPlayers(data.players);
    } catch (error) {
        console.error('Load followed players error:', error);
    }
}

function renderFollowedPlayers(players) {
    const container = document.getElementById('followed-players');

    if (!players || players.length === 0) {
        container.innerHTML = '<p class="empty-state">No players followed yet. Use the search above to find players.</p>';
        return;
    }

    container.innerHTML = players.map(player => `
        <div class="player-card followed" data-player-key="${player.player_key}">
            <div class="player-info">
                <h3>${escapeHtml(player.name)}</h3>
                <p class="follow-date">Following since ${formatDate(player.added_at)}</p>
            </div>
            <button class="btn btn-unfollow" onclick="unfollowPlayer('${player.player_key}')">
                Unfollow
            </button>
        </div>
    `).join('');
}

// ==================== Sync ====================

async function triggerManualSync() {
    if (!authToken) return;

    showToast('Syncing matches...', 'success');

    // In production, this would trigger a sync for the current user
    // For now, just reload followed players
    await loadFollowedPlayers();

    showToast('Sync complete!', 'success');
}

// ==================== UI Updates ====================

function updateUI() {
    const loginBtn = document.getElementById('login-btn');
    const userInfo = document.getElementById('user-info');
    const heroSection = document.getElementById('hero-section');
    const searchSection = document.getElementById('search-section');
    const followedSection = document.getElementById('followed-section');
    const syncSection = document.getElementById('sync-section');

    if (authToken && currentUser) {
        // Logged in
        loginBtn.classList.add('hidden');
        userInfo.classList.remove('hidden');
        heroSection.classList.add('hidden');
        searchSection.classList.remove('hidden');
        followedSection.classList.remove('hidden');
        syncSection.classList.remove('hidden');

        // Update user info
        document.getElementById('user-name').textContent = currentUser.display_name || currentUser.email;
        const avatar = document.getElementById('user-avatar');
        if (currentUser.picture) {
            avatar.src = currentUser.picture;
        }

        // Update last sync time
        if (currentUser.last_sync) {
            document.getElementById('last-sync').textContent = formatDate(currentUser.last_sync);
        }
    } else {
        // Not logged in
        loginBtn.classList.remove('hidden');
        userInfo.classList.add('hidden');
        heroSection.classList.remove('hidden');
        searchSection.classList.add('hidden');
        followedSection.classList.add('hidden');
        syncSection.classList.add('hidden');
    }
}

// ==================== Utilities ====================

function showToast(message, type = '') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type} show`;

    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

function formatDate(dateString) {
    if (!dateString) return 'Never';

    try {
        const date = new Date(dateString);
        return date.toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        });
    } catch {
        return dateString;
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
