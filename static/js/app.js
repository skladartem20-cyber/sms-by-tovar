// Уцененные товары — фронтенд

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  isAdmin: false,
  products: [],
  categories: [],
  settings: {},
  cart: loadCart(),
  filters: { search: '', category: '', sort: 'default', status: '', onlyHighlighted: false },
  bulkMode: false,
  bulkSelected: new Set(),
  detail: { productId: null, photoIndex: 0 },
  zoom: { scale: 1, x: 0, y: 0, dragging: false, startX: 0, startY: 0 },
};

const STORAGE_KEYS = {
  CART: 'uv_cart',
  THEME: 'uv_theme',
};

/* ========================== API helper ============================== */
async function api(url, options = {}) {
  const opts = {
    method: options.method || 'GET',
    headers: options.body && !(options.body instanceof FormData)
      ? { 'Content-Type': 'application/json' } : {},
    credentials: 'same-origin',
    ...options,
  };
  if (options.body && !(options.body instanceof FormData)) {
    opts.body = JSON.stringify(options.body);
  }
  const res = await fetch(url, opts);
  let data = null;
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) {
    data = await res.json();
  }
  if (!res.ok) {
    const msg = (data && data.error) || `Ошибка ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

/* ========================== Cart (localStorage) ===================== */
function loadCart() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEYS.CART)) || []; }
  catch { return []; }
}
function saveCart() {
  localStorage.setItem(STORAGE_KEYS.CART, JSON.stringify(state.cart));
  renderCartBadge();
}
function addToCart(product) {
  if (state.cart.some(item => item.id === product.id)) {
    toast('Этот товар уже в корзине', 'warning');
    return;
  }
  const mainPhoto = (product.photos.find(p => p.is_main) || product.photos[0] || {}).url || '';
  state.cart.push({
    id: product.id,
    number: product.number,
    name: product.name,
    price: product.price,
    photo: mainPhoto,
    defect: product.defect,
  });
  saveCart();
  toast(`✅ "${product.name}" добавлен в корзину`, 'success');
}
function removeFromCart(id) {
  state.cart = state.cart.filter(item => item.id !== id);
  saveCart();
  renderCart();
}
function clearCart() {
  if (!confirm('Очистить корзину?')) return;
  state.cart = [];
  saveCart();
  renderCart();
}

/**
 * Формирует текст заказа и копирует его в буфер обмена,
 * затем открывает ссылку из настроек (order_link) в новой вкладке.
 */
function buildOrderText() {
  const s = state.settings || {};
  const currency = s.currency || '₽';
  const greeting = s.order_greeting || 'Здравствуйте! Я хочу сделать заказ:';
  const footer = s.order_footer || '';

  if (!state.cart.length) return '';

  const lines = [greeting, ''];
  let total = 0;
  state.cart.forEach((it, i) => {
    const price = Number(it.price) || 0;
    const qty = it.qty || 1;
    const sum = price * qty;
    total += sum;
    const qtyStr = qty > 1 ? ` × ${qty}` : '';
    lines.push(`${i + 1}. [${it.number}] ${it.name}${qtyStr} — ${formatPrice(price)} ${currency}`);
  });
  lines.push('');
  lines.push(`Итого: ${formatPrice(total)} ${currency}`);
  if (footer) {
    lines.push('');
    lines.push(footer);
  }
  return lines.join('\n');
}

async function checkoutOrder() {
  if (!state.cart.length) { toast('Корзина пуста', 'error'); return; }
  const s = state.settings || {};
  const url = (s.order_link || s.messenger_link || '').trim();
  if (!url) {
    toast('Ссылка для заказа не настроена. Откройте «Настройки».', 'error');
    return;
  }
  const text = buildOrderText();

  // Открываем ссылку СИНХРОННО (до await), иначе popup-blocker может заблокировать
  const win = window.open(url, '_blank', 'noopener,noreferrer');

  // Копируем текст заказа в буфер обмена
  let copied = false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      copied = true;
    } else {
      // Fallback для старых браузеров
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      copied = document.execCommand('copy');
      ta.remove();
    }
  } catch (err) {
    copied = false;
  }

  if (copied) {
    toast('✓ Заказ скопирован — вставьте его в чат (Ctrl+V)', 'success');
  } else {
    // Если не получилось скопировать — показываем модалку с текстом, чтобы пользователь скопировал вручную
    showOrderTextModal(text);
  }

  if (!win) {
    toast('Не удалось открыть ссылку — разрешите всплывающие окна', 'error');
  }
}

/** Резервная модалка, если буфер обмена недоступен (Safari iOS без https и т.п.) */
function showOrderTextModal(text) {
  let m = document.getElementById('orderTextFallback');
  if (!m) {
    m = document.createElement('div');
    m.id = 'orderTextFallback';
    m.className = 'modal';
    m.innerHTML = `
      <div class="modal-overlay" data-close></div>
      <div class="modal-content modal-medium">
        <button class="modal-close" data-close>×</button>
        <h2>📋 Скопируйте текст заказа</h2>
        <p class="hint">Не удалось скопировать автоматически. Выделите весь текст ниже и скопируйте (Ctrl+C / ⌘+C), затем вставьте в чат.</p>
        <textarea id="orderTextArea" rows="10" style="width:100%;font-family:inherit;font-size:14px;padding:10px;border-radius:8px;border:1px solid var(--border);background:var(--bg-elev-2);color:var(--text);"></textarea>
        <div class="modal-actions">
          <button class="btn btn-secondary" data-close>Закрыть</button>
        </div>
      </div>`;
    document.body.appendChild(m);
    m.addEventListener('click', (e) => { if (e.target.hasAttribute('data-close')) closeModal('#orderTextFallback'); });
  }
  document.getElementById('orderTextArea').value = text;
  openModal('#orderTextFallback');
  setTimeout(() => {
    const ta = document.getElementById('orderTextArea');
    if (ta) { ta.focus(); ta.select(); }
  }, 50);
}


/* ========================== Theme ==================================== */
function initTheme() {
  const saved = localStorage.getItem(STORAGE_KEYS.THEME);
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const dark = saved ? saved === 'dark' : prefersDark;
  document.body.classList.toggle('dark', dark);
  $('#themeIcon').textContent = dark ? '☀️' : '🌙';
}
function toggleTheme() {
  const dark = document.body.classList.toggle('dark');
  localStorage.setItem(STORAGE_KEYS.THEME, dark ? 'dark' : 'light');
  $('#themeIcon').textContent = dark ? '☀️' : '🌙';
}

/* ========================== Toast ==================================== */
function toast(message, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  $('#toasts').appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .3s, transform .3s';
    el.style.opacity = '0';
    el.style.transform = 'translateX(20px)';
    setTimeout(() => el.remove(), 300);
  }, 3000);
}

/* ========================== Formatting =============================== */
function formatPrice(value) {
  const cur = state.settings.currency || '₽';
  const num = Number(value || 0);
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(num) + ' ' + cur;
}
function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso.replace(' ', 'T') + (iso.includes('T') ? '' : 'Z'));
  if (isNaN(d)) return iso;
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
}
function formatDimensions(p) {
  const dims = [p.length, p.width, p.height];
  if (dims.every(d => !d)) return '—';
  return dims.map(d => d || '?').join(' × ') + ' см';
}

/* ========================== Modals =================================== */
function openModal(id) {
  const el = $(id);
  if (!el) return;
  el.hidden = false;
  document.body.style.overflow = 'hidden';
}
function closeModal(id) {
  const el = $(id);
  if (!el) return;
  el.hidden = true;
  document.body.style.overflow = '';
}
function closeAllModals() {
  $$('.modal').forEach(m => m.hidden = true);
  document.body.style.overflow = '';
}

document.addEventListener('click', e => {
  if (e.target.matches('[data-close]') || e.target.matches('.modal-overlay')) {
    const modal = e.target.closest('.modal');
    if (modal) closeModal('#' + modal.id);
  }
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeAllModals();
});

/* ========================== Settings & data load =================== */
async function loadAll() {
  await loadSettings();
  await loadAuth();
  await Promise.all([loadCategories(), loadProducts(), loadVisitorCount()]);
}

async function loadSettings() {
  state.settings = await api('/api/settings');
  applySettings();
}
function applySettings() {
  const s = state.settings;
  if (s.shop_title) { $('#shopTitle').textContent = s.shop_title; document.title = s.shop_title; }
  if (s.shop_subtitle) $('#shopSubtitle').textContent = s.shop_subtitle;
  $('#howToText').textContent = s.how_to_order_text || '';
  $('#phoneNumber').textContent = s.phone || '';
  const link = s.messenger_link || '#';
  $('#btnMessenger').href = link;
  $('#messengerName').textContent = `Написать в ${s.messenger_name || 'мессенджер'}`;
}

async function loadAuth() {
  const r = await api('/api/me');
  state.isAdmin = !!r.is_admin;
  applyAdminUI();
}
function applyAdminUI() {
  $('#adminToolbar').hidden = !state.isAdmin;
  $('#btnAdmin').classList.toggle('active', state.isAdmin);
  $('#btnAdmin').title = state.isAdmin ? 'Админ-режим включён' : 'Войти как админ';
  document.body.classList.toggle('admin-mode', state.isAdmin);
}

async function loadCategories() {
  state.categories = await api('/api/categories');
  renderCategoryFilters();
}
function renderCategoryFilters() {
  const sel = $('#categoryFilter');
  sel.innerHTML = '<option value="">Все категории</option>'
    + state.categories.map(c => `<option value="${c.id}">${escapeHtml(c.name)} (${c.product_count})</option>`).join('');
  const editorSel = $('#editorCategory');
  editorSel.innerHTML = '<option value="">— Без категории —</option>'
    + state.categories.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
}

async function loadProducts() {
  state.products = await api('/api/products');
  renderProducts();
}

async function loadVisitorCount() {
  const r = await api('/api/visitor_count');
  $('#visitorCount').textContent = (r.count || 0).toLocaleString('ru-RU');
}

/* ========================== Render products ========================= */
function renderProducts() {
  const grid = $('#productsGrid');
  const filtered = applyFilters(state.products);
  if (filtered.length === 0) {
    grid.innerHTML = '';
    $('#emptyState').hidden = false;
    return;
  }
  $('#emptyState').hidden = true;
  grid.innerHTML = filtered.map(renderCard).join('');

  // Attach card click handlers
  $$('#productsGrid .card').forEach(card => {
    const id = Number(card.dataset.id);
    card.addEventListener('click', e => {
      // Bulk mode
      if (state.bulkMode && state.isAdmin) {
        if (e.target.closest('.card-admin-overlay')) return;
        toggleBulkSelect(id, card);
        return;
      }
      // Admin overlay buttons
      if (e.target.closest('[data-action]')) {
        const action = e.target.closest('[data-action]').dataset.action;
        e.stopPropagation();
        handleCardAction(action, id);
        return;
      }
      openProductDetail(id);
    });
  });
}

function applyFilters(products) {
  let arr = products.slice();
  const f = state.filters;
  if (f.search) {
    const q = f.search.toLowerCase();
    arr = arr.filter(p =>
      (p.name || '').toLowerCase().includes(q) ||
      String(p.number || '').toLowerCase().includes(q) ||
      (p.description || '').toLowerCase().includes(q) ||
      (p.defect || '').toLowerCase().includes(q)
    );
  }
  if (f.category) arr = arr.filter(p => String(p.category_id) === String(f.category));
  if (f.status) arr = arr.filter(p => p.status === f.status);
  if (f.onlyHighlighted) arr = arr.filter(p => p.highlighted);

  // Sort
  const pinFirst = (a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0);
  if (f.sort === 'price_asc') arr.sort((a, b) => pinFirst(a, b) || a.price - b.price);
  else if (f.sort === 'price_desc') arr.sort((a, b) => pinFirst(a, b) || b.price - a.price);
  else if (f.sort === 'newest') arr.sort((a, b) => pinFirst(a, b) || (b.created_at || '').localeCompare(a.created_at || ''));
  else if (f.sort === 'oldest') arr.sort((a, b) => pinFirst(a, b) || (a.created_at || '').localeCompare(b.created_at || ''));
  else arr.sort(pinFirst); // default: pinned first, then DB order (already by created_at desc)
  return arr;
}

function renderCard(p) {
  const main = p.photos.find(ph => ph.is_main) || p.photos[0];
  const photoHtml = main
    ? `<img src="${main.url}" alt="${escapeAttr(p.name)}" loading="lazy" />`
    : `<div class="card-no-photo">📦</div>`;

  const highlightClass = p.highlighted ? `highlighted color-${p.highlight_color || 'green'}` : '';
  const highlightRibbon = (p.highlighted && p.highlight_label)
    ? `<span class="highlight-ribbon color-${p.highlight_color || 'green'}">${escapeHtml(p.highlight_label)}</span>` : '';
  const pinBadge = p.pinned ? `<span class="pin-badge" title="Закреплено">📌</span>` : '';

  let statusPill = '';
  if (p.status === 'reserved') statusPill = `<span class="status-pill reserved">Бронь</span>`;
  else if (p.status === 'sold') statusPill = `<span class="status-pill sold">Продано</span>`;

  const photoCount = p.photos.length > 1
    ? `<span class="card-photo-count">📷 ${p.photos.length}</span>` : '';

  const selected = state.bulkMode && state.bulkSelected.has(p.id);
  const checkboxHtml = state.bulkMode && state.isAdmin
    ? `<div class="card-bulk-checkbox">${selected ? '✓' : ''}</div>` : '';

  const adminOverlay = state.isAdmin && !state.bulkMode ? `
    <div class="card-admin-overlay">
      <button data-action="edit" title="Редактировать">✏️ Изменить</button>
      <button data-action="pin">${p.pinned ? '📌 Открепить' : '📌 Закрепить'}</button>
      <button data-action="delete" class="danger">🗑️</button>
    </div>` : '';

  return `
    <div class="card ${highlightClass} ${selected ? 'bulk-selected' : ''}" data-id="${p.id}">
      ${checkboxHtml}
      <div class="card-photo">
        ${highlightRibbon}
        ${pinBadge}
        ${statusPill}
        ${photoCount}
        ${photoHtml}
      </div>
      <div class="card-body">
        <div class="card-number">№ ${escapeHtml(p.number)}</div>
        <h3 class="card-name">${escapeHtml(p.name)}</h3>
        <div class="card-defect">${escapeHtml(p.defect || '')}</div>
        <div class="card-bottom">
          <span class="card-price">${formatPrice(p.price)}</span>
          <span class="card-date">${formatDate(p.created_at)}</span>
        </div>
      </div>
      ${adminOverlay}
    </div>`;
}

async function handleCardAction(action, id) {
  const p = state.products.find(x => x.id === id);
  if (!p) return;
  if (action === 'edit') openEditor(p);
  else if (action === 'delete') {
    if (!confirm(`Удалить товар "${p.name}"?`)) return;
    await api(`/api/products/${id}`, { method: 'DELETE' });
    toast('Товар удалён', 'success');
    await loadProducts();
    await loadCategories();
  } else if (action === 'pin') {
    await api(`/api/products/${id}`, { method: 'PUT', body: { pinned: !p.pinned } });
    await loadProducts();
  }
}

/* ========================== Bulk mode =============================== */
function toggleBulkMode() {
  state.bulkMode = !state.bulkMode;
  state.bulkSelected.clear();
  document.body.classList.toggle('bulk-mode', state.bulkMode);
  $('#adminBulkToolbar').hidden = !state.bulkMode;
  $('#btnBulkMode').textContent = state.bulkMode ? '✓ Завершить' : '☑️ Выделить';
  updateBulkCount();
  renderProducts();
}
function toggleBulkSelect(id, card) {
  if (state.bulkSelected.has(id)) state.bulkSelected.delete(id);
  else state.bulkSelected.add(id);
  card.classList.toggle('bulk-selected', state.bulkSelected.has(id));
  const cb = card.querySelector('.card-bulk-checkbox');
  if (cb) cb.textContent = state.bulkSelected.has(id) ? '✓' : '';
  updateBulkCount();
}
function updateBulkCount() {
  $('#bulkCount').textContent = state.bulkSelected.size;
}
async function bulkDelete() {
  if (state.bulkSelected.size === 0) return;
  if (!confirm(`Удалить ${state.bulkSelected.size} товаров?`)) return;
  await api('/api/products/bulk_delete', {
    method: 'POST',
    body: { ids: Array.from(state.bulkSelected) },
  });
  toast(`Удалено: ${state.bulkSelected.size}`, 'success');
  toggleBulkMode();
  await loadProducts();
  await loadCategories();
}

/* ========================== Product detail ========================== */
function openProductDetail(id) {
  const p = state.products.find(x => x.id === id);
  if (!p) return;
  state.detail.productId = id;
  state.detail.photoIndex = 0;
  $('#detailNumber').textContent = '№ ' + p.number;
  $('#detailName').textContent = p.name;
  $('#detailPrice').textContent = formatPrice(p.price);
  $('#detailDescription').textContent = p.description || '';
  $('#detailCategory').textContent = p.category_name || '—';
  $('#detailWeight').textContent = p.weight ? p.weight + ' кг' : '—';
  $('#detailDimensions').textContent = formatDimensions(p);
  $('#detailDate').textContent = formatDate(p.created_at);

  const defectBlock = $('#detailDefectBlock');
  if (p.defect) {
    defectBlock.hidden = false;
    $('#detailDefect').textContent = p.defect;
  } else {
    defectBlock.hidden = true;
  }

  // Status pill
  const statusPill = $('#detailStatus');
  if (p.status === 'available') { statusPill.className = 'product-status-pill available'; statusPill.textContent = '✓ В наличии'; }
  else if (p.status === 'reserved') { statusPill.className = 'product-status-pill reserved'; statusPill.textContent = '⏱ Бронь'; }
  else if (p.status === 'sold') { statusPill.className = 'product-status-pill sold'; statusPill.textContent = '✗ Продано'; }

  // Highlight badges
  const badges = $('#detailBadges');
  badges.innerHTML = '';
  if (p.highlighted && p.highlight_label) {
    badges.innerHTML = `<span class="badge color-${p.highlight_color || 'green'}">${escapeHtml(p.highlight_label)}</span>`;
  }

  // Buy button — disable if sold
  const buyBtn = $('#btnBuyDetail');
  buyBtn.disabled = (p.status === 'sold');
  buyBtn.textContent = (p.status === 'sold') ? '✗ Продано' : '🛒 Купить';

  renderGallery(p);
  openModal('#modalProduct');
}

function renderGallery(p) {
  const main = $('#galleryMain');
  const thumbs = $('#galleryThumbs');
  if (p.photos.length === 0) {
    main.src = '';
    main.alt = 'Нет фото';
    main.style.background = 'var(--bg-elev-2)';
    thumbs.innerHTML = '';
    $('#galleryPrev').hidden = true;
    $('#galleryNext').hidden = true;
    $('#galleryZoom').hidden = true;
    return;
  }
  $('#galleryZoom').hidden = false;
  $('#galleryPrev').hidden = p.photos.length < 2;
  $('#galleryNext').hidden = p.photos.length < 2;
  updateGalleryMain(p);
  thumbs.innerHTML = p.photos.map((ph, i) =>
    `<img src="${ph.url}" alt="" data-idx="${i}" class="${i === state.detail.photoIndex ? 'active' : ''}" />`
  ).join('');
  $$('#galleryThumbs img').forEach(img => {
    img.addEventListener('click', () => {
      state.detail.photoIndex = Number(img.dataset.idx);
      updateGalleryMain(p);
      $$('#galleryThumbs img').forEach(t => t.classList.remove('active'));
      img.classList.add('active');
    });
  });
}
function updateGalleryMain(p) {
  const ph = p.photos[state.detail.photoIndex];
  $('#galleryMain').src = ph ? ph.url : '';
}
function galleryPrev() {
  const p = state.products.find(x => x.id === state.detail.productId);
  if (!p || p.photos.length < 2) return;
  state.detail.photoIndex = (state.detail.photoIndex - 1 + p.photos.length) % p.photos.length;
  updateGalleryMain(p);
  syncThumbActive();
}
function galleryNext() {
  const p = state.products.find(x => x.id === state.detail.productId);
  if (!p || p.photos.length < 2) return;
  state.detail.photoIndex = (state.detail.photoIndex + 1) % p.photos.length;
  updateGalleryMain(p);
  syncThumbActive();
}
function syncThumbActive() {
  $$('#galleryThumbs img').forEach((img, i) => {
    img.classList.toggle('active', i === state.detail.photoIndex);
  });
}

/* ========================== Zoom modal ============================== */
function openZoom() {
  const src = $('#galleryMain').src;
  if (!src) return;
  $('#zoomImg').src = src;
  state.zoom = { scale: 1, x: 0, y: 0, dragging: false, startX: 0, startY: 0 };
  applyZoom();
  openModal('#modalZoom');
}
function applyZoom() {
  const img = $('#zoomImg');
  img.style.transform = `translate(${state.zoom.x}px, ${state.zoom.y}px) scale(${state.zoom.scale})`;
  $('#zoomLevel').textContent = Math.round(state.zoom.scale * 100) + '%';
}
function zoomIn()  { state.zoom.scale = Math.min(state.zoom.scale * 1.25, 8); applyZoom(); }
function zoomOut() { state.zoom.scale = Math.max(state.zoom.scale / 1.25, 0.5); applyZoom(); }
function zoomReset() { state.zoom = { scale: 1, x: 0, y: 0, dragging: false, startX: 0, startY: 0 }; applyZoom(); }
function initZoomDrag() {
  const stage = $('#zoomStage');
  stage.addEventListener('mousedown', e => {
    state.zoom.dragging = true;
    state.zoom.startX = e.clientX - state.zoom.x;
    state.zoom.startY = e.clientY - state.zoom.y;
  });
  window.addEventListener('mousemove', e => {
    if (!state.zoom.dragging) return;
    state.zoom.x = e.clientX - state.zoom.startX;
    state.zoom.y = e.clientY - state.zoom.startY;
    applyZoom();
  });
  window.addEventListener('mouseup', () => state.zoom.dragging = false);

  // Wheel zoom
  stage.addEventListener('wheel', e => {
    e.preventDefault();
    if (e.deltaY < 0) zoomIn(); else zoomOut();
  }, { passive: false });

  // Touch (pinch + drag)
  let touchStartDist = 0;
  let touchStartScale = 1;
  let touchStartX = 0, touchStartY = 0;
  stage.addEventListener('touchstart', e => {
    if (e.touches.length === 2) {
      const [a, b] = e.touches;
      touchStartDist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      touchStartScale = state.zoom.scale;
    } else if (e.touches.length === 1) {
      state.zoom.dragging = true;
      touchStartX = e.touches[0].clientX - state.zoom.x;
      touchStartY = e.touches[0].clientY - state.zoom.y;
    }
  }, { passive: true });
  stage.addEventListener('touchmove', e => {
    if (e.touches.length === 2) {
      e.preventDefault();
      const [a, b] = e.touches;
      const dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      state.zoom.scale = Math.min(8, Math.max(0.5, touchStartScale * (dist / touchStartDist)));
      applyZoom();
    } else if (e.touches.length === 1 && state.zoom.dragging) {
      state.zoom.x = e.touches[0].clientX - touchStartX;
      state.zoom.y = e.touches[0].clientY - touchStartY;
      applyZoom();
    }
  }, { passive: false });
  stage.addEventListener('touchend', () => state.zoom.dragging = false);
}

/* ========================== Cart UI ================================ */
function renderCartBadge() {
  $('#cartBadge').textContent = state.cart.length;
  $('#cartBadge').style.display = state.cart.length ? 'grid' : 'none';
}
function renderCart() {
  const wrap = $('#cartItems');
  if (state.cart.length === 0) {
    wrap.innerHTML = '';
    $('#cartEmpty').hidden = false;
    $('#cartSummary').hidden = true;
    return;
  }
  $('#cartEmpty').hidden = true;
  $('#cartSummary').hidden = false;
  wrap.innerHTML = state.cart.map(item => `
    <div class="cart-item">
      ${item.photo
        ? `<img src="${item.photo}" alt="" />`
        : `<div style="width:64px;height:64px;display:grid;place-items:center;background:var(--bg-elev-2);border-radius:8px;font-size:28px;">📦</div>`}
      <div class="cart-item-info">
        <p class="cart-item-name">№${escapeHtml(item.number)} — ${escapeHtml(item.name)}</p>
        <div class="cart-item-meta">${escapeHtml(item.defect || '')}</div>
      </div>
      <div class="cart-item-price">${formatPrice(item.price)}</div>
      <button class="cart-item-remove" data-id="${item.id}" title="Удалить">×</button>
    </div>
  `).join('');
  const total = state.cart.reduce((s, i) => s + Number(i.price || 0), 0);
  $('#cartTotal').textContent = formatPrice(total);
  $$('#cartItems .cart-item-remove').forEach(btn => {
    btn.addEventListener('click', () => removeFromCart(Number(btn.dataset.id)));
  });
}

/* ========================== Editor (product form) ================== */
function openEditor(product = null) {
  $('#editorTitle').textContent = product ? 'Редактировать товар' : 'Новый товар';
  $('#editorId').value = product ? product.id : '';
  $('#editorNumber').value = product?.number || '';
  $('#editorName').value = product?.name || '';
  $('#editorPrice').value = product?.price ?? '';
  $('#editorCategory').value = product?.category_id || '';
  $('#editorStatus').value = product?.status || 'available';
  $('#editorDefect').value = product?.defect || '';
  $('#editorDescription').value = product?.description || '';
  $('#editorWeight').value = product?.weight ?? '';
  $('#editorLength').value = product?.length ?? '';
  $('#editorWidth').value = product?.width ?? '';
  $('#editorHeight').value = product?.height ?? '';
  $('#editorPinned').checked = !!product?.pinned;
  $('#editorHighlighted').checked = !!product?.highlighted;
  $('#editorHighlightLabel').value = product?.highlight_label || '';
  $('#editorHighlightColor').value = product?.highlight_color || 'green';
  renderEditorPhotos(product?.photos || []);
  openModal('#modalEditor');
}

function renderEditorPhotos(photos) {
  const wrap = $('#photosPreview');
  if (!photos.length) {
    wrap.innerHTML = '<p style="color:var(--text-muted);font-size:13px;">Фото ещё не добавлены. Сначала сохраните товар, затем добавьте фото.</p>';
    return;
  }
  wrap.innerHTML = photos.map(ph => `
    <div class="photo-thumb ${ph.is_main ? 'is-main' : ''}">
      ${ph.is_main ? '<span class="photo-thumb-main-badge">Главное</span>' : ''}
      <img src="${ph.url}" alt="" />
      <div class="photo-thumb-actions">
        ${!ph.is_main ? `<button data-action="main" data-id="${ph.id}">⭐ Главное</button>` : ''}
        <button class="danger" data-action="delete" data-id="${ph.id}">🗑️</button>
      </div>
    </div>
  `).join('');
  $$('#photosPreview [data-action]').forEach(btn => {
    btn.addEventListener('click', async e => {
      const action = btn.dataset.action;
      const id = Number(btn.dataset.id);
      try {
        if (action === 'main') {
          await api(`/api/photos/${id}/main`, { method: 'POST' });
          toast('Главное фото установлено', 'success');
        } else if (action === 'delete') {
          if (!confirm('Удалить это фото?')) return;
          await api(`/api/photos/${id}`, { method: 'DELETE' });
          toast('Фото удалено', 'success');
        }
        const pid = Number($('#editorId').value);
        if (pid) {
          const fresh = await api(`/api/products/${pid}`);
          renderEditorPhotos(fresh.photos);
          await loadProducts();
        }
      } catch (err) { toast(err.message, 'error'); }
    });
  });
}

async function saveProduct(e) {
  e.preventDefault();
  const id = $('#editorId').value;
  const body = {
    number: $('#editorNumber').value.trim(),
    name: $('#editorName').value.trim(),
    price: Number($('#editorPrice').value),
    category_id: $('#editorCategory').value || null,
    status: $('#editorStatus').value,
    defect: $('#editorDefect').value,
    description: $('#editorDescription').value,
    weight: $('#editorWeight').value || null,
    length: $('#editorLength').value || null,
    width: $('#editorWidth').value || null,
    height: $('#editorHeight').value || null,
    pinned: $('#editorPinned').checked,
    highlighted: $('#editorHighlighted').checked,
    highlight_label: $('#editorHighlightLabel').value.trim(),
    highlight_color: $('#editorHighlightColor').value,
  };
  try {
    let savedId = id;
    if (id) {
      await api(`/api/products/${id}`, { method: 'PUT', body });
      toast('Товар сохранён', 'success');
    } else {
      const r = await api('/api/products', { method: 'POST', body });
      savedId = r.id;
      $('#editorId').value = r.id;
      $('#editorTitle').textContent = 'Редактировать товар';
      toast('Товар создан. Теперь можно добавить фото.', 'success');
    }
    await loadProducts();
    await loadCategories();
    // Refresh photos for the editor
    const fresh = await api(`/api/products/${savedId}`);
    renderEditorPhotos(fresh.photos);
  } catch (err) { toast(err.message, 'error'); }
}

async function uploadPhotos(files) {
  const pid = Number($('#editorId').value);
  if (!pid) {
    toast('Сначала сохраните товар', 'warning');
    return;
  }
  if (!files || !files.length) return;
  const fd = new FormData();
  Array.from(files).forEach(f => fd.append('photos', f));
  try {
    const r = await api(`/api/products/${pid}/photos`, { method: 'POST', body: fd });
    toast(`Загружено фото: ${r.saved.length}`, 'success');
    renderEditorPhotos(r.photos);
    await loadProducts();
  } catch (err) { toast(err.message, 'error'); }
}

/* ========================== Categories UI ========================== */
async function openCategoriesModal() {
  await loadCategories();
  renderCategoryList();
  openModal('#modalCategories');
}
function renderCategoryList() {
  const list = $('#categoryList');
  if (state.categories.length === 0) {
    list.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:20px;">Категорий ещё нет</p>';
    return;
  }
  list.innerHTML = state.categories.map(c => `
    <li data-id="${c.id}">
      <input type="text" value="${escapeAttr(c.name)}" data-id="${c.id}" />
      <span class="category-count">${c.product_count} тов.</span>
      <button title="Удалить" data-id="${c.id}">×</button>
    </li>
  `).join('');

  // Rename on blur / Enter
  $$('#categoryList input').forEach(inp => {
    const save = async () => {
      const id = Number(inp.dataset.id);
      const cat = state.categories.find(c => c.id === id);
      const newName = inp.value.trim();
      if (newName && newName !== cat.name) {
        try {
          await api(`/api/categories/${id}`, { method: 'PUT', body: { name: newName } });
          toast('Категория переименована', 'success');
          await loadCategories();
          renderCategoryList();
          await loadProducts();
        } catch (err) { toast(err.message, 'error'); inp.value = cat.name; }
      }
    };
    inp.addEventListener('blur', save);
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); inp.blur(); }});
  });

  // Delete buttons
  $$('#categoryList button').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = Number(btn.dataset.id);
      const cat = state.categories.find(c => c.id === id);
      if (!confirm(`Удалить категорию "${cat.name}"? Товары останутся, но без категории.`)) return;
      try {
        await api(`/api/categories/${id}`, { method: 'DELETE' });
        toast('Категория удалена', 'success');
        await loadCategories();
        renderCategoryList();
        await loadProducts();
      } catch (err) { toast(err.message, 'error'); }
    });
  });
}
async function createCategory(e) {
  e.preventDefault();
  const name = $('#categoryName').value.trim();
  if (!name) return;
  try {
    await api('/api/categories', { method: 'POST', body: { name } });
    $('#categoryName').value = '';
    toast('Категория добавлена', 'success');
    await loadCategories();
    renderCategoryList();
  } catch (err) { toast(err.message, 'error'); }
}

/* ========================== Settings UI ============================= */
function openSettings() {
  const s = state.settings;
  $('#setTitle').value = s.shop_title || '';
  $('#setSubtitle').value = s.shop_subtitle || '';
  $('#setPhone').value = s.phone || '';
  $('#setCurrency').value = s.currency || '₽';
  $('#setMessengerName').value = s.messenger_name || '';
  $('#setMessengerLink').value = s.messenger_link || '';
  $('#setHowto').value = s.how_to_order_text || '';
  $('#setOrderLink').value = s.order_link || '';
  $('#setOrderGreeting').value = s.order_greeting || '';
  $('#setOrderFooter').value = s.order_footer || '';
  $('#setPassword').value = '';
  openModal('#modalSettings');
}
async function saveSettings(e) {
  e.preventDefault();
  const body = {
    shop_title: $('#setTitle').value,
    shop_subtitle: $('#setSubtitle').value,
    phone: $('#setPhone').value,
    currency: $('#setCurrency').value || '₽',
    messenger_name: $('#setMessengerName').value,
    messenger_link: $('#setMessengerLink').value,
    how_to_order_text: $('#setHowto').value,
    order_link: $('#setOrderLink').value,
    order_greeting: $('#setOrderGreeting').value,
    order_footer: $('#setOrderFooter').value,
  };
  const newPwd = $('#setPassword').value.trim();
  if (newPwd) body.admin_password = newPwd;
  try {
    await api('/api/settings', { method: 'POST', body });
    toast('Настройки сохранены', 'success');
    await loadSettings();
    closeModal('#modalSettings');
  } catch (err) { toast(err.message, 'error'); }
}

/* ========================== Stats =================================== */
async function openStats() {
  try {
    const s = await api('/api/stats');
    const last7 = s.visitors_last_7 || [];
    const maxCount = Math.max(1, ...last7.map(d => d.count));
    const bars = last7.map(d => {
      const h = Math.round((d.count / maxCount) * 70);
      const label = d.day.slice(5).replace('-', '.');
      return `<div class="stat-bar-day">
        <div class="stat-bar-fill" style="height:${h}px;" title="${d.count}"></div>
        <div class="stat-bar-label">${label}</div>
      </div>`;
    }).join('') || '<p style="color:var(--text-muted)">Нет данных</p>';

    const byCat = (s.by_category || []).map(c =>
      `<li><span>${escapeHtml(c.name)}</span> <b>${c.c}</b></li>`).join('');
    const statusMap = { available: 'В наличии', reserved: 'Бронь', sold: 'Продано' };
    const byStatus = Object.entries(s.by_status || {}).map(([k, v]) =>
      `<li><span>${statusMap[k] || k}</span> <b>${v}</b></li>`).join('');

    $('#statsContent').innerHTML = `
      <div class="stat-card"><h4>👀 Посетителей всего</h4><div class="stat-value">${s.visitors_total.toLocaleString('ru-RU')}</div></div>
      <div class="stat-card"><h4>📅 Сегодня</h4><div class="stat-value">${s.visitors_today}</div></div>
      <div class="stat-card"><h4>📦 Товаров</h4><div class="stat-value">${s.products_total}</div></div>
      <div class="stat-card"><h4>💰 Общая стоимость</h4><div class="stat-value">${formatPrice(s.products_value)}</div></div>
      <div class="stat-card full"><h4>📊 Посетителей за последние 7 дней</h4><div class="stat-bar">${bars}</div></div>
      <div class="stat-card"><h4>📁 По категориям</h4><ul class="stat-list">${byCat || '<li>—</li>'}</ul></div>
      <div class="stat-card"><h4>🎯 По статусам</h4><ul class="stat-list">${byStatus || '<li>—</li>'}</ul></div>
    `;
    openModal('#modalStats');
  } catch (err) { toast(err.message, 'error'); }
}

/* ========================== Backup ================================= */
async function downloadBackup() {
  toast('Готовим бэкап…', 'info');
  try {
    const res = await fetch('/api/backup', { credentials: 'same-origin' });
    if (!res.ok) throw new Error('Не удалось создать бэкап');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `backup_${new Date().toISOString().slice(0,10)}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast('✅ Бэкап скачан', 'success');
  } catch (err) { toast(err.message, 'error'); }
}

/* ========================== Login =================================== */
function openLogin() {
  if (state.isAdmin) {
    if (confirm('Выйти из режима администратора?')) doLogout();
    return;
  }
  $('#loginError').hidden = true;
  $('#loginPassword').value = '';
  openModal('#modalLogin');
  setTimeout(() => $('#loginPassword').focus(), 50);
}
async function doLogin(e) {
  e.preventDefault();
  const pwd = $('#loginPassword').value;
  try {
    await api('/api/login', { method: 'POST', body: { password: pwd } });
    state.isAdmin = true;
    applyAdminUI();
    closeModal('#modalLogin');
    toast('✅ Добро пожаловать!', 'success');
    await loadProducts();
  } catch (err) {
    $('#loginError').textContent = err.message;
    $('#loginError').hidden = false;
  }
}
async function doLogout() {
  await api('/api/logout', { method: 'POST' });
  state.isAdmin = false;
  state.bulkMode = false;
  state.bulkSelected.clear();
  applyAdminUI();
  $('#adminBulkToolbar').hidden = true;
  document.body.classList.remove('bulk-mode');
  toast('Вы вышли из админ-режима', 'info');
  await loadProducts();
}

/* ========================== Util ==================================== */
function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function escapeAttr(s) { return escapeHtml(s); }

function copyPhone() {
  const phone = state.settings.phone || '';
  navigator.clipboard.writeText(phone).then(
    () => toast('📋 Номер скопирован', 'success'),
    () => {
      // Fallback
      const ta = document.createElement('textarea');
      ta.value = phone;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); toast('📋 Номер скопирован', 'success'); }
      catch { toast('Не удалось скопировать', 'error'); }
      ta.remove();
    }
  );
}

/* ========================== Event wiring ============================ */
function wireEvents() {
  // Top bar
  $('#btnHowto').addEventListener('click', () => openModal('#modalHowto'));
  $('#btnTheme').addEventListener('click', toggleTheme);
  $('#btnCart').addEventListener('click', () => { renderCart(); openModal('#modalCart'); });
  $('#btnAdmin').addEventListener('click', openLogin);

  // How to order
  $('#btnCopyPhone').addEventListener('click', copyPhone);

  // Cart
  $('#btnClearCart').addEventListener('click', clearCart);
  $('#btnCheckout').addEventListener('click', checkoutOrder);

  // Filters
  let searchTimer;
  $('#searchInput').addEventListener('input', e => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.filters.search = e.target.value;
      renderProducts();
    }, 150);
  });
  $('#categoryFilter').addEventListener('change', e => { state.filters.category = e.target.value; renderProducts(); });
  $('#sortFilter').addEventListener('change', e => { state.filters.sort = e.target.value; renderProducts(); });
  $('#statusFilter').addEventListener('change', e => { state.filters.status = e.target.value; renderProducts(); });
  $('#onlyHighlighted').addEventListener('change', e => { state.filters.onlyHighlighted = e.target.checked; renderProducts(); });

  // Login
  $('#loginForm').addEventListener('submit', doLogin);
  $('#btnLogout').addEventListener('click', doLogout);

  // Admin toolbar
  $('#btnNewProduct').addEventListener('click', () => openEditor(null));
  $('#btnCategories').addEventListener('click', openCategoriesModal);
  $('#btnSettings').addEventListener('click', openSettings);
  $('#btnStats').addEventListener('click', openStats);
  $('#btnBackup').addEventListener('click', downloadBackup);
  $('#btnBulkMode').addEventListener('click', toggleBulkMode);
  $('#btnBulkDelete').addEventListener('click', bulkDelete);
  $('#btnBulkCancel').addEventListener('click', toggleBulkMode);

  // Editor
  $('#editorForm').addEventListener('submit', saveProduct);
  $('#btnUploadPhotos').addEventListener('click', () => $('#editorPhotos').click());
  $('#editorPhotos').addEventListener('change', e => { uploadPhotos(e.target.files); e.target.value = ''; });

  // Categories
  $('#categoryForm').addEventListener('submit', createCategory);

  // Settings
  $('#settingsForm').addEventListener('submit', saveSettings);

  // Detail modal
  $('#galleryPrev').addEventListener('click', galleryPrev);
  $('#galleryNext').addEventListener('click', galleryNext);
  $('#galleryMain').addEventListener('click', openZoom);
  $('#galleryZoom').addEventListener('click', openZoom);
  $('#btnBuyDetail').addEventListener('click', () => {
    const p = state.products.find(x => x.id === state.detail.productId);
    if (p && p.status !== 'sold') {
      addToCart(p);
      closeModal('#modalProduct');
    }
  });

  // Keyboard navigation in gallery
  document.addEventListener('keydown', e => {
    if (!$('#modalProduct').hidden) {
      if (e.key === 'ArrowLeft') galleryPrev();
      else if (e.key === 'ArrowRight') galleryNext();
    }
  });

  // Zoom
  $('#zoomIn').addEventListener('click', zoomIn);
  $('#zoomOut').addEventListener('click', zoomOut);
  $('#zoomReset').addEventListener('click', zoomReset);
  $('#zoomImg').addEventListener('dblclick', () => {
    if (state.zoom.scale > 1) zoomReset(); else { state.zoom.scale = 2; applyZoom(); }
  });
  initZoomDrag();
}

/* ========================== Boot ==================================== */
async function boot() {
  initTheme();
  wireEvents();
  renderCartBadge();
  try {
    await loadAll();
  } catch (err) {
    console.error(err);
    toast('Ошибка загрузки: ' + err.message, 'error');
  }
  // Re-fetch visitor count occasionally (in case of multi-window)
  setInterval(loadVisitorCount, 60000);
}

document.addEventListener('DOMContentLoaded', boot);
