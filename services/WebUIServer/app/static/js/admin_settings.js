import settings from "./settings.js";
import { ApiClient } from "./APIClient.js";
import {AuthService} from"./AuthService.js";

// ========== 共用狀態和工具函數 ==========
//jwt剩餘時間
let __jwtCountdownTimer = null;

const state = {
  apiKeys: [],
  currentUser: null,
  lastRotatedToken: null,
};

const showError = (msg) => {
  if (typeof window !== 'undefined' && typeof window.showError === 'function') {
    window.showError(msg);
  } else if (typeof alert === 'function') {
    alert(msg || '發生錯誤');
  }
};

const showSuccess = (msg) => {
  if (typeof window !== 'undefined' && typeof window.showSuccess === 'function') {
    window.showSuccess(msg);
  } else if (typeof alert === 'function') {
    alert(msg || '完成');
  }
};

(function () {
  function show(elId, msg) {
    var box = document.getElementById(elId);
    if (!box) { alert(msg); return; }

    // 清空另一個框
    var other = (elId === 'errorMessage')
      ? document.getElementById('successMessage')
      : document.getElementById('errorMessage');
    if (other) {
      other.textContent = '';
      other.removeAttribute('role');
      other.classList.remove('visible');
      other.classList.add('hidden');
    }

    // 顯示本框（用 class 控制，不用 display）
    box.textContent = (msg == null ? '' : String(msg));
    box.setAttribute('role', 'alert');
    box.classList.remove('hidden');
    box.classList.add('visible');

    var hideMs = (elId === 'successMessage') ? 2500 : 6000;
    clearTimeout(box.__hideTimer);
    box.__hideTimer = setTimeout(function(){
      box.classList.remove('visible');
      box.classList.add('hidden');
      box.textContent = '';
      box.removeAttribute('role');
    }, hideMs);
  }

  window.showSuccess = function (msg) { show('successMessage', msg); };
  window.showError   = function (msg) { show('errorMessage',   msg); };
})();

function parseJwt(token) {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(
      atob(base64).split('').map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join('')
    );
    return JSON.parse(jsonPayload);
  } catch (e) {
    return null;
  }
}

function formatRemaining(ms) {
  if (ms <= 0) return '已過期';
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const parts = [];
  if (d) parts.push(`${d}天`);
  if (h || d) parts.push(`${h}小時`);
  parts.push(`${m}分${sec}秒`);
  return parts.join(' ');
}

function renderJwtRemaining(token) {
  const el = document.getElementById('current_jwt_display');
  if (!el) return;
  const payload = parseJwt(token);
  if (!payload || !payload.exp) {
    el.textContent = '無法解析 token 的 exp（可能非標準 JWT）';
    return;
  }
  const end = payload.exp * 1000;

  const tick = () => {
    const left = end - Date.now();
    el.innerHTML = `剩餘：${formatRemaining(left)}<br>到期：${new Date(end).toLocaleString()}`;
  };
  tick();

  if (__jwtCountdownTimer) clearInterval(__jwtCountdownTimer);
  __jwtCountdownTimer = setInterval(tick, 1000);
}

function formatDate(isoString) {
  if (!isoString) return '-';
  try {
    const date = new Date(isoString);
    return date.toLocaleString();
  } catch {
    return isoString;
  }
}

function formatNumber(value) {
  if (value === null || value === undefined) return '-';
  return Number(value).toLocaleString();
}

function showHint(el, message, type = 'info') {
  if (!el) return;
  el.textContent = message || '';
  el.classList.remove('success', 'error', 'info');
  el.classList.add(type);
}

(function ensureBtnLoading(){
  if (typeof window !== 'undefined' && typeof window.setBtnLoading === 'function') return;
  function setBtnLoading(btn, loading, labelWhenLoading) {
    if (!btn) return;
    if (loading) {
      if (!btn.dataset._origText) btn.dataset._origText = btn.textContent;
      if (labelWhenLoading) btn.textContent = labelWhenLoading;
      btn.disabled = true;
      btn.setAttribute('aria-busy', 'true');
      btn.classList.add('is-loading');
    } else {
      if (btn.dataset._origText) btn.textContent = btn.dataset._origText;
      btn.disabled = false;
      btn.removeAttribute('aria-busy');
      btn.classList.remove('is-loading');
    }
  }
  if (typeof window !== 'undefined') window.setBtnLoading = setBtnLoading;
})();

// ========== 使用者設定相關函數 ==========
function fillUser(user) {
  const u = user || {};
  const uid = u?.id ?? u?.user_id ?? null;
  if (uid != null) {
    localStorage.setItem('user_id', String(uid));
    const idEl = document.getElementById('user_id');
    if (idEl) idEl.value = uid;
  }
  const map = {
    id:"user_id",
    account: 'user_account',
    name: 'user_name',
    gender: 'user_gender',
    birthday: 'user_birthday',
    phone: 'user_phone',
    email: 'user_email',
    headshot_url: 'user_headshot_url',
  };
  for (const k in map) {
    const el = document.getElementById(map[k]);
    if (!el) continue;
    const v = user?.[k] ?? '';
    el.value = v == null ? '' : v;
  }
  const brief = document.getElementById('userBrief');
  if (brief) brief.textContent = `${user?.name ?? '-'}（${user?.account ?? '-'}）`;
  const avatar = document.getElementById('avatarInitial');
  if (avatar) avatar.textContent = (user?.name?.[0] ?? user?.account?.[0] ?? 'U').toUpperCase();

  const jwtArea = document.getElementById('current_jwt');
  if (jwtArea) jwtArea.value = localStorage.getItem('jwt') || '';
}

async function loadMe() {
  const token = localStorage.getItem('jwt');
  if (!token) {
    showError && showError('尚未登入或 JWT 不存在，將返回登入頁');
    location.href = '/auth';
    return;
  }

  try {
    const me = await ApiClient.getCurrentUser();
    console.log('[admin_settings] /users/me =>', me);

    const data = me && me.user ? me.user : me;
    state.currentUser = data;
    
    fillUser(data);
    // 不顯示載入成功提示
    
    // 設置 API Key Owner ID
    const apiKeyOwner = document.getElementById('apiKeyOwner');
    if (apiKeyOwner && data.id) {
      apiKeyOwner.value = data.id;
    }
  } catch (e) {
    console.error('[admin_settings] 載入 /users/me 失敗：', e);
    showError && showError(e?.message || '載入使用者資料失敗，請稍後再試');
  }
}

async function saveProfile() {
  const btn = document.getElementById('btnSaveProfile');
  try {
    setBtnLoading(btn, true);

    const updateData = {
      name: document.getElementById('user_name')?.value || undefined,
      gender: document.getElementById('user_gender')?.value || undefined,
      birthday: document.getElementById('user_birthday')?.value || undefined,
      phone: document.getElementById('user_phone')?.value || undefined,
      email: document.getElementById('user_email')?.value || undefined,
      headshot_url: document.getElementById('user_headshot_url')?.value || undefined,
    };

    await ApiClient.updateUserProfile(updateData);
    const latest = await ApiClient.getCurrentUser();
    const data = latest?.user ? latest.user : latest;
    fillUser(data);
    showSuccess('已更新使用者資料');
  } catch (e) {
    showError(e?.message || '更新使用者資料失敗');
  } finally {
    setBtnLoading(btn, false);
  }
}

async function changePassword() {
  const btn = document.getElementById('btnSubmitChangePassword');
  const dlg = document.getElementById('changepassworddialog');
  try {
    setBtnLoading(btn, true);

    const old_password = document.getElementById('current_password')?.value.trim();
    const new_password = document.getElementById('new_password')?.value.trim();

    const res = await ApiClient.changePassword({ old_password, new_password });

    if (res?.message) showSuccess(res.message);
    else showSuccess('密碼已變更');

    document.getElementById('current_password').value = '';
    document.getElementById('new_password').value = '';
    dlg.close();
  } catch (e) {
    dlg.close();
    showError(e?.message || '變更密碼失敗');
  } finally {
    setBtnLoading(btn, false);
  }
}

async function refreshJwt() {
  const btn = document.getElementById('btnRefreshJwt');
  try {
    setBtnLoading(btn, true);
    let data;
    if (typeof ApiClient.refreshUserToken === 'function') {
      data = await ApiClient.refreshUserToken();
    } else {
      const res = await fetch(`${settings.BFF_ROOT}/users/token/refresh`, {
        method: 'GET',
        headers: { 'Authorization': `Bearer ${localStorage.getItem('jwt') || ''}` }
      });
      if (!res.ok) throw new Error('重新取得 JWT 失敗');
      data = await res.json().catch(()=>({}));
    }

    const newToken = data?.access_token || data?.token || data?.jwt;
    if (!newToken) throw new Error('回應未含新 JWT');

    if (window.AuthService && typeof window.AuthService.saveToken === 'function') {
      window.AuthService.saveToken(newToken);
    } else {
      localStorage.setItem('jwt', newToken);
    }

    renderJwtRemaining(newToken);
    showSuccess('已重新取得並覆寫 JWT');
  } catch (e) {
    showError(e?.message || '重新取得 JWT 失敗');
  } finally {
    setBtnLoading(btn, false);
  }
}

// ========== 應用程式設定相關函數 ==========
async function loadAppSettings() {
  try {
    if (!ApiClient || !ApiClient.settings) {
      console.error('[admin_settings] ApiClient.settings 未定義');
      showError && showError('API 客戶端未正確初始化');
      return;
    }

    const response = await ApiClient.settings.get();
    const settings = response.settings || response;
    
    await loadTimezones();
    
    if (settings && settings.timezone) {
      const timezoneSelect = document.getElementById('setting_timezone');
      if (timezoneSelect) {
        timezoneSelect.value = settings.timezone;
        console.log('[admin_settings] 設置時區為:', settings.timezone);
      }
    }
    
    if (settings && settings.diary_auto_refresh_interval_minutes !== undefined) {
      const diaryIntervalInput = document.getElementById('setting_diary_auto_refresh_interval');
      if (diaryIntervalInput) diaryIntervalInput.value = settings.diary_auto_refresh_interval_minutes;
    } else {
      const diaryIntervalInput = document.getElementById('setting_diary_auto_refresh_interval');
      if (diaryIntervalInput && !diaryIntervalInput.value) {
        diaryIntervalInput.value = 30;
      }
    }
  } catch (e) {
    console.error('[admin_settings] 載入應用程式設定失敗：', e);
    showError && showError('載入應用程式設定失敗：' + (e?.message || ''));
  }
}

async function loadTimezones() {
  try {
    if (!ApiClient || !ApiClient.settings) {
      console.error('[admin_settings] ApiClient.settings 未定義');
      return;
    }

    const response = await ApiClient.settings.getTimezones();
    const timezoneSelect = document.getElementById('setting_timezone');
    if (!timezoneSelect) return;
    
    timezoneSelect.innerHTML = '<option value="">請選擇時區</option>';
    
    const timezones = response.timezones || response;
    
    if (Array.isArray(timezones)) {
      timezones.forEach(tz => {
        const option = document.createElement('option');
        if (typeof tz === 'string') {
          option.value = tz;
          option.textContent = tz;
        } else if (typeof tz === 'object' && tz !== null) {
          const value = tz.value || tz.timezone || Object.keys(tz)[0];
          const label = tz.label || tz.name || tz[value] || value;
          option.value = value;
          option.textContent = label;
        }
        timezoneSelect.appendChild(option);
      });
    } else if (typeof timezones === 'object' && timezones !== null) {
      Object.keys(timezones).forEach(key => {
        const option = document.createElement('option');
        option.value = key;
        option.textContent = timezones[key] || key;
        timezoneSelect.appendChild(option);
      });
    }
    
    console.log('[admin_settings] 時區列表載入完成，共', timezoneSelect.options.length - 1, '個時區');
  } catch (e) {
    console.error('[admin_settings] 載入時區列表失敗：', e);
    const timezoneSelect = document.getElementById('setting_timezone');
    if (timezoneSelect) {
      timezoneSelect.innerHTML = '<option value="">載入失敗，請重新整理頁面</option>';
    }
  }
}

async function saveAppSettings() {
  const btn = document.getElementById('btnSaveAppSettings');
  try {
    if (!ApiClient || !ApiClient.settings) {
      showError('API 客戶端未正確初始化');
      return;
    }

    setBtnLoading(btn, true);

    const updateData = {
      timezone: document.getElementById('setting_timezone')?.value || undefined,
      diary_auto_refresh_interval_minutes: document.getElementById('setting_diary_auto_refresh_interval')?.value ? parseInt(document.getElementById('setting_diary_auto_refresh_interval').value) : undefined,
    };

    Object.keys(updateData).forEach(key => {
      if (updateData[key] === undefined) delete updateData[key];
    });

    await ApiClient.settings.update(updateData);
    showSuccess('應用程式設定已更新');
  } catch (e) {
    showError(e?.message || '更新應用程式設定失敗');
  } finally {
    setBtnLoading(btn, false);
  }
}

// ========== 模型設定相關函數 ==========
async function loadModelSettings() {
  try {
    if (!ApiClient || !ApiClient.settings) {
      console.error('[admin_settings] ApiClient.settings 未定義');
      showError && showError('API 客戶端未正確初始化');
      return;
    }

    const response = await ApiClient.settings.get();
    const settings = response.settings || response;
    
    if (!settings) {
      console.warn('[admin_settings] 未找到設定資料');
      return;
    }
    
    if (settings.default_llm_provider) {
      const providerSelect = document.getElementById('setting_llm_provider');
      if (providerSelect) providerSelect.value = settings.default_llm_provider;
    }
    
    if (settings.default_llm_model) {
      const modelInput = document.getElementById('setting_llm_model');
      if (modelInput) modelInput.value = settings.default_llm_model;
    }
    
    const llmProviders = settings.llm_model_api?.providers || settings.llm_providers;
    if (llmProviders && typeof llmProviders === 'object') {
      Object.keys(llmProviders).forEach(providerKey => {
        const provider = llmProviders[providerKey];
        if (provider && provider.api_key) {
          const keyInput = document.getElementById(`provider_${providerKey}_api_key`);
          if (keyInput) {
            keyInput.value = provider.api_key;
          }
        }
      });
      
      // 只支援 Google
      if (llmProviders.google?.api_key) {
        const googleKeyInput = document.getElementById('provider_google_api_key');
        if (googleKeyInput) googleKeyInput.value = llmProviders.google.api_key;
      }
    }
  } catch (e) {
    console.error('[admin_settings] 載入模型設定失敗：', e);
    showError && showError('載入模型設定失敗：' + (e?.message || ''));
  }
}

async function saveModelSettings() {
  const btn = document.getElementById('btnSaveModelSettings');
  try {
    if (!ApiClient || !ApiClient.settings) {
      showError('API 客戶端未正確初始化');
      return;
    }

    setBtnLoading(btn, true);

    const updateData = {
      default_llm_provider: document.getElementById('setting_llm_provider')?.value || undefined,
      default_llm_model: document.getElementById('setting_llm_model')?.value || undefined,
    };

    // 構建 LLM 供應商配置（只支援 Google）
    const llmProviders = {};
    const googleKey = (document.getElementById('provider_google_api_key')?.value || '').trim();

    // 只發送 Google 的設定
    llmProviders.google = { api_key: googleKey, model_names: [] };

    updateData.llm_providers = llmProviders;

    Object.keys(updateData).forEach(key => {
      if (updateData[key] === undefined) delete updateData[key];
    });

    await ApiClient.settings.update(updateData);
    showSuccess('模型設定已更新');
  } catch (e) {
    showError(e?.message || '更新模型設定失敗');
  } finally {
    setBtnLoading(btn, false);
  }
}

// ========== API Key 管理相關函數 ==========
async function loadApiKeys() {
  try {
    const data = await ApiClient.admin.apiKeys.list();
    state.apiKeys = data || [];
    renderApiKeyTable();
  } catch (error) {
    console.error('[admin_settings] 載入 API Key 失敗', error);
    const apiKeyTokenMessage = document.getElementById('apiKeyTokenMessage');
    if (apiKeyTokenMessage) {
      showHint(apiKeyTokenMessage, '載入 API Key 失敗，請稍後重試。', 'error');
    }
  }
}

function renderApiKeyTable() {
  const apiKeyTableBody = document.querySelector('#apiKeyTable tbody');
  if (!apiKeyTableBody) return;
  apiKeyTableBody.innerHTML = '';

  if (!state.apiKeys.length) {
    const emptyRow = document.createElement('tr');
    emptyRow.className = 'empty-row';
    emptyRow.innerHTML = `<td colspan="8">尚無 API Key，請建立新的 Key。</td>`;
    apiKeyTableBody.appendChild(emptyRow);
    return;
  }

  state.apiKeys.forEach((key) => {
    const tr = document.createElement('tr');
    const statusClass = key.active ? 'status-active' : 'status-inactive';
    const statusLabel = key.active ? '啟用' : '停用';
    const scopes = (key.scopes || []).join(', ') || '-';
    tr.innerHTML = `
      <td>${key.name}</td>
      <td>${key.owner_id}</td>
      <td><span class="status-badge ${statusClass}">${statusLabel}</span></td>
      <td>${scopes}</td>
      <td>${formatNumber(key.rate_limit_per_min)}</td>
      <td>${formatNumber(key.quota_per_day)}</td>
      <td>${formatDate(key.created_at)}</td>
      <td>
        <div class="table-actions">
          <button type="button" class="btn-tertiary" data-action="edit" data-key="${key.id}">編輯</button>
          <button type="button" class="btn-tertiary" data-action="rotate" data-key="${key.id}">旋轉</button>
          <button type="button" class="btn-secondary" data-action="toggle" data-key="${key.id}">
            ${key.active ? '停用' : '啟用'}
          </button>
        </div>
      </td>
    `;
    apiKeyTableBody.appendChild(tr);
  });

  apiKeyTableBody.querySelectorAll('button[data-action="edit"]').forEach((btn) => {
    btn.addEventListener('click', () => editApiKey(btn.dataset.key));
  });
  apiKeyTableBody.querySelectorAll('button[data-action="rotate"]').forEach((btn) => {
    btn.addEventListener('click', () => rotateApiKey(btn.dataset.key));
  });
  apiKeyTableBody.querySelectorAll('button[data-action="toggle"]').forEach((btn) => {
    btn.addEventListener('click', () => toggleApiKey(btn.dataset.key));
  });
}

function getSelectedScopes(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return [];
  const checkboxes = container.querySelectorAll('input[type="checkbox"]:checked');
  return Array.from(checkboxes).map(cb => cb.value);
}

function setSelectedScopes(containerId, scopes) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const checkboxes = container.querySelectorAll('input[type="checkbox"]');
  checkboxes.forEach(cb => {
    cb.checked = (scopes || []).includes(cb.value);
  });
}

async function handleApiKeyCreate(event) {
  event.preventDefault();
  const apiKeyName = document.getElementById('apiKeyName');
  const apiKeyOwner = document.getElementById('apiKeyOwner');
  const apiKeyRate = document.getElementById('apiKeyRate');
  const apiKeyQuota = document.getElementById('apiKeyQuota');
  const apiKeyTokenMessage = document.getElementById('apiKeyTokenMessage');
  
  if (!apiKeyName || !apiKeyOwner) return;

  const name = apiKeyName.value.trim();
  const ownerId = Number(apiKeyOwner.value);
  const rate = apiKeyRate?.value ? Number(apiKeyRate.value) : null;
  const quota = apiKeyQuota?.value ? Number(apiKeyQuota.value) : null;
  const scopes = getSelectedScopes('apiKeyScopes');

  if (!name || !ownerId) {
    showHint(apiKeyTokenMessage, '請填寫必要欄位。', 'error');
    return;
  }

  if (scopes.length === 0) {
    showHint(apiKeyTokenMessage, '請至少選擇一個 Scope。', 'error');
    return;
  }

  try {
    showHint(apiKeyTokenMessage, '建立中...', 'info');
    const result = await ApiClient.admin.apiKeys.create({
      name,
      ownerId,
      rateLimitPerMin: rate,
      quotaPerDay: quota,
      scopes,
    });
    state.apiKeys.unshift(result);
    renderApiKeyTable();
    document.getElementById('apiKeyForm').reset();
    setSelectedScopes('apiKeyScopes', []);
    if (state.currentUser?.id) {
      apiKeyOwner.value = state.currentUser.id;
    }
    if (result.token) {
      state.lastRotatedToken = result.token;
      showHint(apiKeyTokenMessage, `建立成功！請妥善保存新 Token：${result.token}`, 'success');
    } else {
      showHint(apiKeyTokenMessage, '建立成功。', 'success');
    }
  } catch (error) {
    console.error('[admin_settings] 建立 API Key 失敗', error);
    showHint(apiKeyTokenMessage, '建立失敗，請稍後再試。', 'error');
  }
}

async function rotateApiKey(keyId) {
  if (!keyId) return;
  if (!confirm('確認要旋轉此 API Key 嗎？舊金鑰將立即失效。')) return;
  try {
    const result = await ApiClient.admin.apiKeys.rotate(keyId);
    const index = state.apiKeys.findIndex((k) => k.id === keyId);
    if (index >= 0) {
      state.apiKeys[index] = result;
      renderApiKeyTable();
    }
    if (result.token) {
      state.lastRotatedToken = result.token;
      alert(`新的 API Token：\n${result.token}\n請立即保存，此對話框關閉後將無法再次取得。`);
    }
  } catch (error) {
    console.error('[admin_settings] 旋轉 API Key 失敗', error);
    alert('旋轉失敗，請稍後再試。');
  }
}

async function toggleApiKey(keyId) {
  const target = state.apiKeys.find((k) => k.id === keyId);
  if (!target) return;
  const nextActive = !target.active;
  try {
    await ApiClient.admin.apiKeys.update(keyId, { active: nextActive });
    target.active = nextActive;
    renderApiKeyTable();
  } catch (error) {
    console.error('[admin_settings] 切換 API Key 狀態失敗', error);
    alert('更新狀態失敗，請稍後再試。');
  }
}

function editApiKey(keyId) {
  const target = state.apiKeys.find((k) => k.id === keyId);
  if (!target) return;

  // 填充編輯表單
  document.getElementById('editApiKeyName').value = target.name || '';
  document.getElementById('editApiKeyRate').value = target.rate_limit_per_min || '';
  document.getElementById('editApiKeyQuota').value = target.quota_per_day || '';
  setSelectedScopes('editApiKeyScopes', target.scopes || []);

  // 儲存當前編輯的 key ID
  const editForm = document.getElementById('editApiKeyForm');
  editForm.dataset.keyId = keyId;

  // 顯示對話框
  document.getElementById('editApiKeyDialog').showModal();
}

async function handleApiKeyEdit(event) {
  event.preventDefault();
  const form = event.target;
  const keyId = form.dataset.keyId;
  if (!keyId) return;

  const btn = document.getElementById('btnSubmitEditApiKey');
  try {
    setBtnLoading(btn, true);

    const name = document.getElementById('editApiKeyName').value.trim();
    const rate = document.getElementById('editApiKeyRate').value ? Number(document.getElementById('editApiKeyRate').value) : null;
    const quota = document.getElementById('editApiKeyQuota').value ? Number(document.getElementById('editApiKeyQuota').value) : null;
    const scopes = getSelectedScopes('editApiKeyScopes');

    if (!name) {
      showError('請填寫名稱。');
      return;
    }

    if (scopes.length === 0) {
      showError('請至少選擇一個 Scope。');
      return;
    }

    const updateData = {
      name,
      rate_limit_per_min: rate,
      quota_per_day: quota,
      scopes,
    };

    const result = await ApiClient.admin.apiKeys.update(keyId, updateData);
    
    // 更新本地狀態
    const index = state.apiKeys.findIndex((k) => k.id === keyId);
    if (index >= 0) {
      state.apiKeys[index] = result;
    }
    
    renderApiKeyTable();
    document.getElementById('editApiKeyDialog').close();
    showSuccess('API Key 已更新');
  } catch (error) {
    console.error('[admin_settings] 更新 API Key 失敗', error);
    showError(error?.message || '更新失敗，請稍後再試。');
  } finally {
    setBtnLoading(btn, false);
  }
}

// ========== 事件綁定和初始化 ==========
function bindEvents() {
  // 使用者設定
  document.getElementById('btnSaveProfile')?.addEventListener('click', saveProfile);
  document.getElementById('btnChangePassword')?.addEventListener('click', () => {
    document.getElementById('changepassworddialog').showModal();
  });
  document.getElementById('btnSubmitChangePassword')?.addEventListener('click', changePassword);
  document.getElementById('btnRefreshJwt')?.addEventListener('click', refreshJwt);
  
  // 應用程式設定
  document.getElementById('btnSaveAppSettings')?.addEventListener('click', saveAppSettings);
  
  // 模型設定
  document.getElementById('btnSaveModelSettings')?.addEventListener('click', saveModelSettings);
  
  // API Key 管理
  const apiKeyForm = document.getElementById('apiKeyForm');
  if (apiKeyForm) {
    apiKeyForm.addEventListener('submit', handleApiKeyCreate);
  }
  
  const editApiKeyForm = document.getElementById('editApiKeyForm');
  if (editApiKeyForm) {
    editApiKeyForm.addEventListener('submit', handleApiKeyEdit);
  }
}

async function boot() {
  const token = localStorage.getItem('jwt');
  if (!token) {
    showError('尚未登入，3 秒後返回登入頁');
    setTimeout(()=>location.href='/auth', 3000);
    return;
  }
  
  // 檢查是否為管理員
  try {
    const response = window.__CURRENT_USER || await ApiClient.getCurrentUser();
    const currentUser = response?.user || response;
    if (!currentUser || currentUser.role !== 'admin') {
      alert('此頁面僅限管理員使用，將返回首頁。');
      window.location.href = '/home';
      return;
    }
    state.currentUser = currentUser;
  } catch (error) {
    console.error('[admin_settings] 檢查管理員權限失敗', error);
    showError('無法驗證管理員權限，請重新登入');
    setTimeout(()=>location.href='/auth', 2000);
    return;
  }
  
  bindEvents();
  await Promise.all([
    loadMe(),
    loadAppSettings(),
    loadModelSettings(),
    loadApiKeys()
  ]);
  
  const existing = localStorage.getItem('jwt');
  if (existing) renderJwtRemaining(existing);
}

window.__bootAdminSettings = boot;
export default { boot };
boot();

