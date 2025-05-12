// Authentication state management
let currentUser = null;

function initializeAuth() {
    const authToken = localStorage.getItem('authToken');
    const userData = localStorage.getItem('user');
    
    if (authToken && userData) {
        currentUser = JSON.parse(userData);
        updateUIForLoggedInUser();
    } else {
        updateUIForGuest();
    }
}

function updateUIForLoggedInUser() {
    // Update navigation
    document.querySelectorAll('.guest-only').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.user-only').forEach(el => el.style.display = 'block');
    document.getElementById('username-display').textContent = currentUser.name;
}

function updateUIForGuest() {
    document.querySelectorAll('.guest-only').forEach(el => el.style.display = 'block');
    document.querySelectorAll('.user-only').forEach(el => el.style.display = 'none');
}

function handleLogout() {
    localStorage.removeItem('authToken');
    localStorage.removeItem('user');
    currentUser = null;
    updateUIForGuest();
    window.location.href = '/login.html';
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', initializeAuth);