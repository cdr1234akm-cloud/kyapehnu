/**
 * StyleAI — Complete Frontend JavaScript
 * No frameworks, no build tools, pure vanilla JS
 */

// ─── CONFIG ──────────────────────────────────────
const API_BASE = 'http://localhost:8000/api';

// ─── STATE ───────────────────────────────────────
const state = {
    token: localStorage.getItem('styleai_token') || null,
    user: JSON.parse(localStorage.getItem('styleai_user') || 'null'),
    wardrobe: [],
    currentOccasion: null,
    outfits: [],
};

// ─── API HELPER ──────────────────────────────────
async function api(path, options = {}) {
    const headers = { ...(options.headers || {}) };

    if (state.token) {
        headers['Authorization'] = `Bearer ${state.token}`;
    }

    // Don't set Content-Type for FormData (browser sets it with boundary)
    if (!(options.body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
    }

    try {
        const res = await fetch(`${API_BASE}${path}`, {
            ...options,
            headers,
        });

        const data = await res.json();

        if (!res.ok) {
            throw new Error(data.detail || data.message || 'Something went wrong');
        }

        return data;
    } catch (err) {
        if (err.message === 'Failed to fetch') {
            throw new Error('Cannot connect to server. Make sure the backend is running.');
        }
        throw err;
    }
}

// ─── AUTH ─────────────────────────────────────────
function saveAuth(data) {
    state.token = data.token;
    state.user = data;
    localStorage.setItem('styleai_token', data.token);
    localStorage.setItem('styleai_user', JSON.stringify(data));
}

function logout() {
    state.token = null;
    state.user = null;
    localStorage.removeItem('styleai_token');
    localStorage.removeItem('styleai_user');
    window.location.href = 'login.html';
}

function isLoggedIn() {
    return !!state.token;
}

function requireAuth() {
    if (!isLoggedIn()) {
        window.location.href = 'login.html';
        return false;
    }
    return true;
}

// ─── AUTH PAGE LOGIC ─────────────────────────────
function initAuthPage() {
    if (isLoggedIn()) {
        window.location.href = 'wardrobe.html';
        return;
    }

    const tabs = document.querySelectorAll('.auth-tab');
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            if (tab.dataset.tab === 'login') {
                loginForm.style.display = 'block';
                registerForm.style.display = 'none';
            } else {
                loginForm.style.display = 'none';
                registerForm.style.display = 'block';
            }
        });
    });

    // Login
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = loginForm.querySelector('button[type="submit"]');
        btn.disabled = true;
        btn.classList.add('btn-loading');
        btn.textContent = 'Signing in';

        try {
            const data = await api('/auth/login', {
                method: 'POST',
                body: JSON.stringify({
                    email: document.getElementById('loginEmail').value,
                    password: document.getElementById('loginPassword').value,
                }),
            });

            saveAuth(data);
            showToast('Welcome back! 👋', 'success');

            setTimeout(() => {
                window.location.href = data.onboarded ? 'wardrobe.html' : 'onboarding.html';
            }, 500);
        } catch (err) {
            showToast(err.message, 'error');
            btn.disabled = false;
            btn.classList.remove('btn-loading');
            btn.textContent = 'Sign In';
        }
    });

    // Register
    registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = registerForm.querySelector('button[type="submit"]');
        btn.disabled = true;
        btn.classList.add('btn-loading');
        btn.textContent = 'Creating account';

        try {
            const data = await api('/auth/register', {
                method: 'POST',
                body: JSON.stringify({
                    full_name: document.getElementById('regName').value,
                    email: document.getElementById('regEmail').value,
                    password: document.getElementById('regPassword').value,
                }),
            });

            saveAuth(data);
            showToast('Account created! Let\'s set up your profile ✨', 'success');

            setTimeout(() => {
                window.location.href = 'onboarding.html';
            }, 800);
        } catch (err) {
            showToast(err.message, 'error');
            btn.disabled = false;
            btn.classList.remove('btn-loading');
            btn.textContent = 'Create Account';
        }
    });
}

// ─── ONBOARDING LOGIC ────────────────────────────
function initOnboarding() {
    if (!requireAuth()) return;

    let currentStep = 0;
    const totalSteps = 4;
    const onboardData = { gender: '', body_type: '', skin_tone: '', style_prefs: [] };

    const steps = document.querySelectorAll('.ob-step');
    const dots = document.querySelectorAll('.progress-dot');
    const nextBtn = document.getElementById('obNext');
    const prevBtn = document.getElementById('obPrev');

    function updateStep() {
        steps.forEach((s, i) => {
            s.style.display = i === currentStep ? 'block' : 'none';
            s.style.animation = i === currentStep ? 'fadeUp 0.4s var(--ease-out)' : 'none';
        });
        dots.forEach((d, i) => {
            d.className = 'progress-dot';
            if (i < currentStep) d.classList.add('completed');
            if (i === currentStep) d.classList.add('active');
        });
        prevBtn.style.visibility = currentStep > 0 ? 'visible' : 'hidden';
        nextBtn.textContent = currentStep === totalSteps - 1 ? '✨ Finish' : 'Next →';
    }

    // Option cards
    document.querySelectorAll('.option-card').forEach(card => {
        card.addEventListener('click', () => {
            const field = card.dataset.field;
            const value = card.dataset.value;

            // Deselect siblings
            card.parentElement.querySelectorAll('.option-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');

            onboardData[field] = value;

            // Update body type options based on gender
            if (field === 'gender') {
                updateBodyTypeOptions(value);
            }
        });
    });

    function updateBodyTypeOptions(gender) {
        const btContainer = document.getElementById('bodyTypeOptions');
        if (!btContainer) return;

        const options = gender === 'female'
            ? [
                { value: 'slim', icon: '🏃‍♀️', label: 'Slim' },
                { value: 'regular', icon: '👩', label: 'Regular' },
                { value: 'curvy', icon: '💃', label: 'Curvy' },
                { value: 'plus', icon: '🌸', label: 'Plus' }
              ]
            : [
                { value: 'slim', icon: '🏃‍♂️', label: 'Slim' },
                { value: 'regular', icon: '👨', label: 'Regular' },
                { value: 'athletic', icon: '💪', label: 'Athletic' },
                { value: 'plus', icon: '🌟', label: 'Plus' }
              ];

        btContainer.innerHTML = options.map(o => `
            <div class="option-card" data-field="body_type" data-value="${o.value}" onclick="selectOption(this)">
                <div class="option-icon">${o.icon}</div>
                ${o.label}
            </div>
        `).join('');
    }

    // Skin swatches
    document.querySelectorAll('.skin-swatch').forEach(swatch => {
        swatch.addEventListener('click', () => {
            document.querySelectorAll('.skin-swatch').forEach(s => s.classList.remove('selected'));
            swatch.classList.add('selected');
            onboardData.skin_tone = swatch.dataset.value;
        });
    });

    // Style chips
    document.querySelectorAll('.style-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            chip.classList.toggle('selected');
            const style = chip.dataset.value;
            if (onboardData.style_prefs.includes(style)) {
                onboardData.style_prefs = onboardData.style_prefs.filter(s => s !== style);
            } else {
                onboardData.style_prefs.push(style);
            }
        });
    });

    nextBtn.addEventListener('click', async () => {
        if (currentStep < totalSteps - 1) {
            currentStep++;
            updateStep();
        } else {
            // Save onboarding
            nextBtn.disabled = true;
            nextBtn.classList.add('btn-loading');
            try {
                await api('/onboarding', {
                    method: 'POST',
                    body: JSON.stringify(onboardData),
                });
                showToast('Profile set up! Time to build your wardrobe 🎉', 'success');
                setTimeout(() => { window.location.href = 'wardrobe.html'; }, 800);
            } catch (err) {
                showToast(err.message, 'error');
                nextBtn.disabled = false;
                nextBtn.classList.remove('btn-loading');
            }
        }
    });

    prevBtn.addEventListener('click', () => {
        if (currentStep > 0) {
            currentStep--;
            updateStep();
        }
    });

    updateStep();
}

// Helper for dynamically created option cards
window.selectOption = function(card) {
    const field = card.dataset.field;
    const value = card.dataset.value;
    card.parentElement.querySelectorAll('.option-card').forEach(c => c.classList.remove('selected'));
    card.classList.add('selected');
};

// ─── WARDROBE LOGIC ──────────────────────────────
function initWardrobe() {
    if (!requireAuth()) return;

    loadWardrobe();
    setupUpload();
    updateNavbar();
}

async function loadWardrobe() {
    const grid = document.getElementById('garmentGrid');
    grid.innerHTML = '<div class="skeleton" style="height:200px"></div>'.repeat(4);

    try {
        const data = await api('/wardrobe');
        state.wardrobe = data.garments;
        renderWardrobe();
        updateWardrobeCount(data.total);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderWardrobe() {
    const grid = document.getElementById('garmentGrid');

    if (state.wardrobe.length === 0) {
        grid.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">👗</div>
                <h3>Your wardrobe is empty</h3>
                <p class="text-muted">Upload photos of your clothes to get started</p>
            </div>`;
        return;
    }

    // Categorize garments by type
    const categories = {
        'tops': [],
        'outerwear': [],
        'bottoms': [],
        'shoes': [],
        'dresses': [],
        'accessories': [],
        'other': []
    };

    state.wardrobe.forEach(g => {
        const type = g.metadata.type?.toLowerCase() || 'other';
        let category = 'other';
        
        if (type.includes('top') || type.includes('shirt') || type.includes('blouse') || type.includes('sweater') || type.includes('tee')) {
            category = 'tops';
        } else if (type.includes('coat') || type.includes('jacket') || type.includes('blazer') || type.includes('cardigan')) {
            category = 'outerwear';
        } else if (type.includes('pant') || type.includes('jeans') || type.includes('skirt') || type.includes('short')) {
            category = 'bottoms';
        } else if (type.includes('shoe') || type.includes('boot') || type.includes('sneaker') || type.includes('sandal')) {
            category = 'shoes';
        } else if (type.includes('dress')) {
            category = 'dresses';
        } else if (type.includes('accessory') || type.includes('hat') || type.includes('belt') || type.includes('scarf')) {
            category = 'accessories';
        }
        
        categories[category].push(g);
    });

    // Define category info with distinct colors
    const categoryInfo = {
        'tops': { icon: '👕', label: 'Tops & T-shirts', color: '#FF6B9D' },
        'outerwear': { icon: '🧥', label: 'Outerwear', color: '#4EA8DE' },
        'bottoms': { icon: '👖', label: 'Bottoms', color: '#5A189A' },
        'shoes': { icon: '👟', label: 'Shoes', color: '#FF9F43' },
        'dresses': { icon: '👗', label: 'Dresses', color: '#EE5A6F' },
        'accessories': { icon: '💍', label: 'Accessories', color: '#FFD93D' },
        'other': { icon: '👕', label: 'Other', color: '#A8DADC' }
    };

    // Render categories with garments
    let html = '';
    let garmentIndex = 0;

    Object.keys(categoryInfo).forEach(catKey => {
        const garments = categories[catKey];
        if (garments.length === 0) return;

        const catInfo = categoryInfo[catKey];
        html += `
            <div class="garment-category" data-category="${catKey}">
                <div class="category-header" style="border-left: 5px solid ${catInfo.color}; background: rgba(${hexToRgb(catInfo.color)}, 0.05)">
                    <h2 class="category-title">
                        <span class="category-icon">${catInfo.icon}</span>
                        <span class="category-label">${catInfo.label}</span>
                        <span class="category-count">${garments.length}</span>
                    </h2>
                </div>
                <div class="category-garments" style="border-bottom: 1px solid ${catInfo.color}40">
                    ${garments.map((g, i) => {
                        const meta = g.metadata;
                        const colors = meta.color || [];
                        const colorDots = colors.map(c =>
                            `<span class="color-dot" style="background:${getColorHex(c)}" title="${c}"></span>`
                        ).join('');

                        return `
                            <div class="garment-card" style="animation-delay: ${(garmentIndex + i) * 0.05}s">
                                <img src="${g.image_url}" alt="${meta.subtype || meta.type}" loading="lazy">
                                <button class="garment-delete" onclick="deleteGarment('${g.id}')" title="Remove">✕</button>
                                <div class="garment-info">
                                    <h4>${meta.subtype || meta.type}</h4>
                                    <div class="garment-tags">
                                        <span>${meta.type}</span>
                                        <span>${meta.pattern || ''}</span>
                                    </div>
                                    <div class="garment-color-dots">${colorDots}</div>
                                </div>
                            </div>`;
                    }).join('')}
                </div>
            </div>`;
        
        garmentIndex += garments.length;
    });

    grid.innerHTML = html;
}

// Helper function to convert hex to RGB
function hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return result ? `${parseInt(result[1], 16)}, ${parseInt(result[2], 16)}, ${parseInt(result[3], 16)}` : '0, 0, 0';
}

function getColorHex(name) {
    const map = {
        black: '#1a1a1a', white: '#f5f5f5', navy: '#1a237e', blue: '#2196F3',
        red: '#e53935', green: '#4CAF50', yellow: '#FFC107', pink: '#E91E63',
        purple: '#9C27B0', orange: '#FF9800', brown: '#795548', grey: '#9E9E9E',
        gray: '#9E9E9E', beige: '#D4C5A9', cream: '#FFFDD0', maroon: '#800000',
        olive: '#808000', teal: '#008080', burgundy: '#800020', tan: '#D2B48C',
        'sky blue': '#87CEEB', charcoal: '#36454F', coral: '#FF7F50',
        lavender: '#E6E6FA', gold: '#FFD700', silver: '#C0C0C0',
    };
    return map[name?.toLowerCase()] || '#888';
}

function setupUpload() {
    const zone = document.getElementById('uploadZone');
    const input = document.getElementById('fileInput');

    zone.addEventListener('click', () => input.click());

    zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.classList.add('dragover');
    });

    zone.addEventListener('dragleave', () => {
        zone.classList.remove('dragover');
    });

    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('dragover');
        handleFiles(e.dataTransfer.files);
    });

    input.addEventListener('change', (e) => {
        handleFiles(e.target.files);
        input.value = ''; // Reset for re-upload
    });
}

async function handleFiles(files) {
    const progress = document.getElementById('uploadProgress');
    const fill = document.getElementById('progressFill');
    const status = document.getElementById('uploadStatus');

    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        if (!file.type.startsWith('image/')) continue;

        progress.classList.add('active');
        const pct = ((i + 0.5) / files.length * 100);
        fill.style.width = pct + '%';
        status.textContent = `Uploading & analysing ${file.name}...`;

        const formData = new FormData();
        formData.append('file', file);

        try {
            const result = await api('/wardrobe/upload', {
                method: 'POST',
                body: formData,
            });

            if (result.status === 'duplicate') {
                showToast(`${file.name} — already in your wardrobe`, 'info');
            } else {
                showToast(`${file.name} — analysed! ✨`, 'success');
            }
        } catch (err) {
            showToast(`${file.name} — ${err.message}`, 'error');
        }
    }

    fill.style.width = '100%';
    status.textContent = 'All done!';
    setTimeout(() => { progress.classList.remove('active'); }, 1500);

    // Reload wardrobe
    loadWardrobe();
}

window.deleteGarment = async function(id) {
    if (!confirm('Remove this garment from your wardrobe?')) return;

    try {
        await api(`/wardrobe/${id}`, { method: 'DELETE' });
        showToast('Garment removed', 'success');
        loadWardrobe();
    } catch (err) {
        showToast(err.message, 'error');
    }
};

function updateWardrobeCount(count) {
    const el = document.getElementById('wardrobeCount');
    if (el) el.textContent = `${count} items`;
}

// ─── OCCASION LOGIC ──────────────────────────────
function initOccasion() {
    if (!requireAuth()) return;
    updateNavbar();

    document.querySelectorAll('.occasion-card').forEach(card => {
        card.addEventListener('click', () => {
            const occasion = card.dataset.occasion;
            localStorage.setItem('styleai_occasion', occasion);
            window.location.href = 'outfits.html';
        });
    });
}

// ─── OUTFITS LOGIC ───────────────────────────────
function initOutfits() {
    if (!requireAuth()) return;
    updateNavbar();

    const occasion = localStorage.getItem('styleai_occasion') || 'casual';
    document.getElementById('currentOccasion').textContent =
        occasion.charAt(0).toUpperCase() + occasion.slice(1);

    loadOutfits(occasion);
}

async function loadOutfits(occasion) {
    const list = document.getElementById('outfitList');
    list.innerHTML = `
        <div style="text-align:center; padding:60px 0">
            <div class="spinner" style="margin:0 auto 16px"></div>
            <p class="text-muted">Finding the best ${occasion} outfits from your wardrobe...</p>
        </div>`;

    try {
        const data = await api('/outfits/suggest', {
            method: 'POST',
            body: JSON.stringify({ occasion }),
        });

        if (data.outfits.length === 0) {
            list.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">🤷</div>
                    <h3>No outfits found</h3>
                    <p class="text-muted">Add more clothes to your wardrobe for better suggestions</p>
                    <a href="wardrobe.html" class="btn btn-primary" style="margin-top:16px">Add Clothes</a>
                </div>`;
            return;
        }

        renderOutfits(data.outfits);
    } catch (err) {
        showToast(err.message, 'error');
        list.innerHTML = `<div class="empty-state"><p>${err.message}</p></div>`;
    }
}

async function loadMoreOutfits() {
    const occasion = localStorage.getItem('styleai_occasion') || 'casual';
    const btn = document.getElementById('showMoreBtn');
    
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-loading"></span> Finding more...';

    try {
        const data = await api('/outfits/more', {
            method: 'POST',
            body: JSON.stringify({ occasion }),
        });

        if (data.outfits.length === 0) {
            showToast('No more unique combinations found!', 'info');
            btn.textContent = 'All combinations explored ✓';
            btn.disabled = true;
            return;
        }

        // Append new outfits to existing list
        const list = document.getElementById('outfitList');
        const existingCount = list.querySelectorAll('.outfit-card').length;
        
        data.outfits.forEach((outfit, i) => {
            outfit.rank = existingCount + i + 1;
        });
        
        // Render and append
        const newHTML = data.outfits.map((outfit, i) => {
            // ... same rendering code as renderOutfits
            // (reuse the template)
        }).join('');
        
        list.insertAdjacentHTML('beforeend', newHTML);
        showToast(`Found ${data.outfits.length} more outfits!`, 'success');

    } catch (err) {
        showToast(err.message, 'error');
    }

    btn.disabled = false;
    btn.innerHTML = '🔄 Show More Outfits';
}

function renderOutfits(outfits) {
    const list = document.getElementById('outfitList');

    list.innerHTML = outfits.map((outfit, i) => {
        const pieces = outfit.pieces || [];
        const piecesHTML = pieces.map(p => `
            <div class="piece-thumb" title="${p.subtype || p.type}">
                <img src="${p.image_url}" alt="${p.type}">
            </div>
        `).join('');

        const score = Math.round((outfit.score || 0) * 100);
        
        // Prepare data for Try-On page
        const outfitData = {
            garmentIds: outfit.garment_ids,
            meta: {
                name: outfit.name || `Outfit ${i + 1}`,
                reasoning: outfit.reasoning || '',
                styling_tip: outfit.styling_tip || '',
                score: outfit.score || 0
            }
        };
        const encodedData = encodeURIComponent(JSON.stringify(outfitData));

        return `
            <div class="outfit-card" style="animation-delay: ${i * 0.1}s">
                <div class="outfit-header">
                    <div style="display:flex; align-items:center; gap:12px">
                        <div class="outfit-rank">${outfit.rank || i + 1}</div>
                        <div>
                            <h3 style="font-family:var(--font-body); font-size:1rem; font-weight:600">
                                ${outfit.name || 'Outfit ' + (i + 1)}
                            </h3>
                        </div>
                    </div>
                    <div class="outfit-score">
                        <div class="score-bar">
                            <div class="score-fill" style="width:${score}%"></div>
                        </div>
                        <span style="font-weight:600; font-size:0.9rem">${score}%</span>
                    </div>
                </div>
                <div class="outfit-pieces">${piecesHTML || '<p class="text-muted">No preview available</p>'}</div>
                <div class="outfit-details">
                    <p class="outfit-reasoning">${outfit.reasoning || ''}</p>
                    ${outfit.styling_tip ? `
                        <div class="outfit-tip">
                            <span>💡</span>
                            <span>${outfit.styling_tip}</span>
                        </div>
                    ` : ''}
                </div>
                <div class="outfit-actions">
                    <button class="btn btn-sm btn-primary"
                        onclick="openTryOn('${encodedData}')">
                        👁️ Try On
                    </button>
                    <button class="btn btn-sm btn-secondary"
                        onclick="saveOutfit('${encodeURIComponent(JSON.stringify(outfit.garment_ids))}')">
                        ❤️ Save
                    </button>
                    <button class="btn btn-sm btn-secondary"
                        onclick="shareOutfit(${i})">
                        📤 Share
                    </button>
                </div>
            </div>`;
    }).join('');
}

// Open Try-On page with selected outfit
window.openTryOn = function(encodedData) {
    const occasion = localStorage.getItem('styleai_occasion') || 'casual';
    const data = JSON.parse(decodeURIComponent(encodedData));
    
    localStorage.setItem('styleai_tryon_garments', JSON.stringify(data.garmentIds));
    localStorage.setItem('styleai_tryon_occasion', occasion);
    localStorage.setItem('styleai_tryon_meta', JSON.stringify(data.meta));
    
    window.location.href = 'tryon.html';
};

window.saveOutfit = async function(garmentIdsStr) {
    const occasion = localStorage.getItem('styleai_occasion') || 'casual';
    const formData = new FormData();
    formData.append('occasion', occasion);
    formData.append('garment_ids', decodeURIComponent(garmentIdsStr));

    try {
        await api('/history/save', { method: 'POST', body: formData });
        showToast('Outfit saved to history! ✨', 'success');
    } catch (err) {
        showToast(err.message, 'error');
    }
};

window.shareOutfit = function(index) {
    showToast('Share feature coming soon!', 'info');
};

// ─── PROFILE LOGIC ───────────────────────────────
async function initProfile() {
    if (!requireAuth()) return;
    updateNavbar();

    try {
        const user = await api('/auth/me');
        const stats = await api('/wardrobe/stats');

        // Fill profile info
        document.getElementById('profileName').textContent = user.full_name || 'User';
        document.getElementById('profileEmail').textContent = user.email;
        document.getElementById('profileAvatar').textContent =
            (user.full_name || user.email)[0].toUpperCase();

        // Fill stats
        document.getElementById('statTotal').textContent = stats.total || 0;
        document.getElementById('statTypes').textContent =
            Object.keys(stats.by_type || {}).length;
        document.getElementById('statColors').textContent =
            Object.keys(stats.by_color || {}).length;
        document.getElementById('statFormality').textContent =
            stats.avg_formality || '-';

        // Fill settings form
        document.getElementById('settingName').value = user.full_name || '';
        document.getElementById('settingGender').value = user.gender || '';
        document.getElementById('settingBody').value = user.body_type || '';
        document.getElementById('settingSkin').value = user.skin_tone || '';

    } catch (err) {
        showToast(err.message, 'error');
    }

    // Save settings
    document.getElementById('settingsForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData();
        formData.append('full_name', document.getElementById('settingName').value);
        formData.append('gender', document.getElementById('settingGender').value);
        formData.append('body_type', document.getElementById('settingBody').value);
        formData.append('skin_tone', document.getElementById('settingSkin').value);

        try {
            await api('/profile', { method: 'PUT', body: formData });
            showToast('Profile updated! ✅', 'success');
        } catch (err) {
            showToast(err.message, 'error');
        }
    });

    // Add after existing stats loading
    try {
        const cacheStats = await api('/cache/stats');
        document.getElementById('statCached').textContent = cacheStats.outfit_combos_cached || 0;
    } catch (err) {
        console.log('Cache stats not available');
    }
}

// ─── NAVBAR ──────────────────────────────────────
function updateNavbar() {
    const avatar = document.getElementById('navAvatar');
    if (avatar && state.user) {
        const name = state.user.full_name || state.user.email || 'U';
        avatar.textContent = name[0].toUpperCase();
    }
}

// ─── TOAST NOTIFICATIONS ─────────────────────────
function showToast(message, type = 'info') {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    const icons = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${icons[type] || ''}</span><span>${message}</span>`;

    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('removing');
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

// ─── GLOBAL ──────────────────────────────────────
window.logout = logout;
window.showToast = showToast;

// ─── THEME TOGGLE ────────────────────────────────
function initTheme() {
    const saved = localStorage.getItem('styleai_theme') || 'dark';
    document.documentElement.setAttribute('data-theme', saved);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const newTheme = current === 'dark' ? 'light' : 'dark';

    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('styleai_theme', newTheme);

    // Save to server
    try {
        const formData = new FormData();
        formData.append('theme', newTheme);
        api('/preferences/theme', { method: 'PUT', body: formData });
    } catch (err) {
        console.log('Could not save theme preference');
    }

    showToast(`Switched to ${newTheme} mode ${newTheme === 'dark' ? '🌙' : '☀️'}`, 'info');
}

// Initialize theme on every page
initTheme();