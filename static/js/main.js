/**
 * ComplyNex CMS - JavaScript Utilities
 */

document.addEventListener('DOMContentLoaded', function() {
    initAlertDismiss();
    initSidebarToggle();
    initActiveNavLink();
    initClickableRows();
    initConfirmActions();
    initAutoSelect();
    initZoomImages();
    initDecisionToggle();
    initPrintButtons();
});

/**
 * Auto-dismiss alerts after 5 seconds
 */
function initAlertDismiss() {
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    
    alerts.forEach(function(alert) {
        setTimeout(function() {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            bsAlert.close();
        }, 5000);
    });
}

/**
 * Sidebar toggle for mobile
 */
function initSidebarToggle() {
    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebar = document.querySelector('.sidebar');
    
    if (sidebarToggle && sidebar) {
        sidebarToggle.addEventListener('click', function() {
            sidebar.classList.toggle('show');
        });
        
        // Close sidebar when clicking outside
        document.addEventListener('click', function(event) {
            if (window.innerWidth < 992) {
                if (!sidebar.contains(event.target) && 
                    !sidebarToggle.contains(event.target) &&
                    sidebar.classList.contains('show')) {
                    sidebar.classList.remove('show');
                }
            }
        });
    }
}

/**
 * Highlight active navigation link based on current URL
 */
function initActiveNavLink() {
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.sidebar .nav-link');
    
    navLinks.forEach(function(link) {
        const href = link.getAttribute('href');
        if (href && currentPath.startsWith(href) && href !== '#') {
            link.classList.add('active');
        } else if (currentPath === '/' && href === '/dashboard') {
            link.classList.add('active');
        }
    });
}

/**
 * Format number with thousand separators
 * @param {number} num - Number to format
 * @returns {string} Formatted number
 */
function formatNumber(num) {
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/**
 * Format date to local string
 * @param {string} dateStr - Date string to format
 * @returns {string} Formatted date
 */
function formatDate(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
}

/**
 * Show loading spinner on button
 * @param {HTMLElement} button - Button element
 * @param {boolean} loading - Loading state
 */
function setButtonLoading(button, loading) {
    if (loading) {
        button.disabled = true;
        button.dataset.originalText = button.innerHTML;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Loading...';
    } else {
        button.disabled = false;
        button.innerHTML = button.dataset.originalText;
    }
}

/**
 * Show toast notification
 * @param {string} message - Message to display
 * @param {string} type - Type of notification (success, danger, warning, info)
 */
function showToast(message, type = 'info') {
    const toastContainer = document.getElementById('toastContainer') || createToastContainer();
    
    const toastHtml = `
        <div class="toast align-items-center text-white bg-${type} border-0" role="alert">
            <div class="d-flex">
                <div class="toast-body">${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        </div>
    `;
    
    toastContainer.insertAdjacentHTML('beforeend', toastHtml);
    const toast = toastContainer.lastElementChild;
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
    
    // Remove toast element after it's hidden
    toast.addEventListener('hidden.bs.toast', function() {
        toast.remove();
    });
}

/**
 * Create toast container if it doesn't exist
 * @returns {HTMLElement} Toast container element
 */
function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    container.style.zIndex = '1100';
    document.body.appendChild(container);
    return container;
}

/**
 * Confirm action with dialog
 * @param {string} message - Confirmation message
 * @returns {Promise<boolean>} Promise that resolves to true if confirmed
 */
function confirmAction(message) {
    return new Promise(function(resolve) {
        if (confirm(message)) {
            resolve(true);
        } else {
            resolve(false);
        }
    });
}

/**
 * Clickable rows — navigate to data-href when row is clicked (ignores clicks on interactive children).
 */
function initClickableRows() {
    document.querySelectorAll('[data-href]').forEach(function(el) {
        el.addEventListener('click', function(e) {
            if (e.target.closest('a, button, input, select, textarea, form')) return;
            window.location = el.dataset.href;
        });
    });
}

/**
 * Confirm-before-submit — reads data-confirm message from button or form.
 * Button variant: prevents the click (and thus form submission) on cancel.
 * Form variant: prevents submit on cancel.
 */
function initConfirmActions() {
    document.querySelectorAll('button[data-confirm]').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
            if (!confirm(btn.dataset.confirm)) {
                e.preventDefault();
                e.stopImmediatePropagation();
            }
        });
    });
    document.querySelectorAll('form[data-confirm]').forEach(function(form) {
        form.addEventListener('submit', function(e) {
            if (!confirm(form.dataset.confirm)) {
                e.preventDefault();
            }
        });
    });
}

/**
 * Auto-select input text on click — replaces onclick="this.select()".
 */
function initAutoSelect() {
    document.querySelectorAll('[data-autoselect]').forEach(function(input) {
        input.addEventListener('click', function() { input.select(); });
    });
}

/**
 * Zoom image into a modal — replaces onclick="document.getElementById(id).src=this.src".
 * Usage: <img data-zoom-target="modalImgElementId" src="...">
 */
function initZoomImages() {
    document.querySelectorAll('[data-zoom-target]').forEach(function(img) {
        img.addEventListener('click', function() {
            var target = document.getElementById(img.dataset.zoomTarget);
            if (target) target.src = img.src;
        });
    });
}

/**
 * Decision-column toggle for the eKYC session list.
 * Usage: <button data-decision-toggle="final|auto">
 */
function initDecisionToggle() {
    document.querySelectorAll('[data-decision-toggle]').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var mode = btn.dataset.decisionToggle;
            document.querySelectorAll('[data-decision-toggle]').forEach(function(b) {
                b.classList.toggle('active', b.dataset.decisionToggle === mode);
            });
            document.querySelectorAll('.decision-final').forEach(function(el) {
                el.classList.toggle('d-none', mode !== 'final');
            });
            document.querySelectorAll('.decision-auto').forEach(function(el) {
                el.classList.toggle('d-none', mode !== 'auto');
            });
        });
    });
}

/**
 * Print-button handler — replaces onclick="window.print()".
 */
function initPrintButtons() {
    document.querySelectorAll('[data-print]').forEach(function(btn) {
        btn.addEventListener('click', function() { window.print(); });
    });
}

/**
 * Copy text to clipboard
 * @param {string} text - Text to copy
 */
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast('Copied to clipboard!', 'success');
    } catch (err) {
        showToast('Failed to copy', 'danger');
    }
}
