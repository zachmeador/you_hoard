// Main JavaScript for You Hoard application

class YouHoard {
    constructor() {
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.setupActiveNavigation();
    }

    setupEventListeners() {
        // Add Video Modal
        const addVideoBtn = document.getElementById('add-video-btn');
        const addVideoModal = document.getElementById('add-video-modal');
        const closeModal = document.getElementById('close-modal');
        const cancelAdd = document.getElementById('cancel-add');
        const addVideoForm = document.getElementById('add-video-form');

        if (addVideoBtn) {
            addVideoBtn.addEventListener('click', () => this.showModal('add-video-modal'));
        }

        if (closeModal) {
            closeModal.addEventListener('click', () => this.hideModal('add-video-modal'));
        }

        if (cancelAdd) {
            cancelAdd.addEventListener('click', () => this.hideModal('add-video-modal'));
        }

        if (addVideoForm) {
            addVideoForm.addEventListener('submit', (e) => this.handleAddVideo(e));
        }

        // User Menu Dropdown
        const userMenuBtn = document.getElementById('user-menu-btn');
        const userDropdown = document.getElementById('user-dropdown');

        if (userMenuBtn) {
            userMenuBtn.addEventListener('click', () => this.toggleDropdown('user-dropdown'));
        }

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.user-menu')) {
                this.hideDropdown('user-dropdown');
            }
        });

        // Close modal when clicking outside
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('modal')) {
                this.hideModal(e.target.id);
            }
        });
    }

    setupActiveNavigation() {
        const currentPath = window.location.pathname;
        const navLinks = document.querySelectorAll('.nav-link');
        
        navLinks.forEach(link => {
            if (link.getAttribute('href') === currentPath) {
                link.classList.add('active');
            }
        });
    }

    // Modal Management
    showModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('show');
        }
    }

    hideModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('show');
            // Reset form if it exists
            const form = modal.querySelector('form');
            if (form) {
                form.reset();
            }
        }
    }

    // Dropdown Management
    toggleDropdown(dropdownId) {
        const dropdown = document.getElementById(dropdownId);
        if (dropdown) {
            dropdown.classList.toggle('show');
        }
    }

    hideDropdown(dropdownId) {
        const dropdown = document.getElementById(dropdownId);
        if (dropdown) {
            dropdown.classList.remove('show');
        }
    }

    // Toast Notifications
    showToast(message, type = 'info', duration = 5000) {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `
            <div>${message}</div>
        `;

        container.appendChild(toast);

        // Auto remove after duration
        setTimeout(() => {
            toast.remove();
        }, duration);
    }

    // API Helper
    async apiCall(url, options = {}) {
        const defaults = {
            headers: {
                'Content-Type': 'application/json',
            },
        };

        const config = { ...defaults, ...options };
        
        try {
            const response = await fetch(url, config);
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            return await response.json();
        } catch (error) {
            console.error('API call failed:', error);
            this.showToast(`Error: ${error.message}`, 'error');
            throw error;
        }
    }

    // Add Video Handler
    async handleAddVideo(event) {
        event.preventDefault();
        
        const form = event.target;
        const formData = new FormData(form);
        
        const videoData = {
            url: formData.get('url'),
            quality: formData.get('quality')
        };

        try {
            // Show loading state
            const submitBtn = form.querySelector('button[type="submit"]');
            const originalText = submitBtn.textContent;
            submitBtn.innerHTML = '<span class="spinner"></span>Adding...';
            submitBtn.disabled = true;

            const result = await this.apiCall('/api/videos', {
                method: 'POST',
                body: JSON.stringify(videoData)
            });

            this.showToast('Video added successfully!', 'success');
            this.hideModal('add-video-modal');
            
            // Refresh page or update video list if on videos page
            if (window.location.pathname === '/videos') {
                window.location.reload();
            }

        } catch (error) {
            this.showToast('Failed to add video', 'error');
        } finally {
            // Reset button
            const submitBtn = form.querySelector('button[type="submit"]');
            submitBtn.textContent = originalText;
            submitBtn.disabled = false;
        }
    }

    // Format file size
    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    // Format duration
    formatDuration(seconds) {
        if (!seconds) return 'Unknown';
        
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        
        if (hours > 0) {
            return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        }
        return `${minutes}:${secs.toString().padStart(2, '0')}`;
    }

    // Format date
    formatDate(dateString) {
        if (!dateString) return 'Unknown';
        
        const date = new Date(dateString);
        return date.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        });
    }

    // Format relative time
    formatRelativeTime(dateString) {
        if (!dateString) return 'Unknown';
        
        const date = new Date(dateString);
        const now = new Date();
        const diffInSeconds = Math.floor((now - date) / 1000);
        
        if (diffInSeconds < 60) return 'Just now';
        if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)} minutes ago`;
        if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)} hours ago`;
        if (diffInSeconds < 2592000) return `${Math.floor(diffInSeconds / 86400)} days ago`;
        
        return this.formatDate(dateString);
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.youHoard = new YouHoard();
});

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = YouHoard;
} 