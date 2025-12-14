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
  } else {
    console.error(msg || '發生錯誤');
  }
};

const showSuccess = (msg) => {
  if (typeof window !== 'undefined' && typeof window.showSuccess === 'function') {
    window.showSuccess(msg);
  } else {
    console.log(msg || '完成');
  }
};

(function () {
  function show(elId, msg) {
    var box = document.getElementById(elId);
    if (!box) {
      console.warn('[admin_settings] 找不到訊息框：', elId, msg);
      return;
    }

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

/**
 * 可靠複製到剪貼簿（避免原生 alert/prompt）
 */
async function copyToClipboard(text) {
  const value = (text ?? '').toString();
  if (!value) return false;

  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch (e) {
    console.warn('[admin_settings] navigator.clipboard 失敗，嘗試 fallback：', e);
  }

  try {
    const ta = document.createElement('textarea');
    ta.value = value;
    ta.setAttribute('readonly', 'true');
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    ta.style.top = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return !!ok;
  } catch (e) {
    console.warn('[admin_settings] execCommand(copy) 失敗：', e);
    return false;
  }
}

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
    if (!ApiClient || !ApiClient.admin || !ApiClient.admin.settings) {
      console.error('[admin_settings] ApiClient.admin.settings 未定義');
      showError && showError('API 客戶端未正確初始化');
      return;
    }

    const sys = await ApiClient.admin.settings.getDefaultLLM();
    const providerSelect = document.getElementById('setting_llm_provider');
    const modelInput = document.getElementById('setting_llm_model');
    if (providerSelect && sys?.default_llm_provider) providerSelect.value = sys.default_llm_provider;
    if (modelInput && sys?.default_llm_model) modelInput.value = sys.default_llm_model;
  } catch (e) {
    console.error('[admin_settings] 載入模型設定失敗：', e);
    showError && showError('載入模型設定失敗：' + (e?.message || ''));
  }
}

async function saveModelSettings() {
  const btn = document.getElementById('btnSaveModelSettings');
  try {
    if (!ApiClient || !ApiClient.admin || !ApiClient.admin.settings) {
      showError('API 客戶端未正確初始化');
      return;
    }

    setBtnLoading(btn, true);

    const default_llm_provider = document.getElementById('setting_llm_provider')?.value;
    const default_llm_model = document.getElementById('setting_llm_model')?.value;
    if (!default_llm_provider || !default_llm_model) {
      throw new Error('請填寫預設 LLM 供應商與模型');
    }

    await ApiClient.admin.settings.setDefaultLLM({ default_llm_provider, default_llm_model });
    showSuccess('系統預設模型設定已更新');
  } catch (e) {
    showError(e?.message || '更新模型設定失敗');
  } finally {
    setBtnLoading(btn, false);
  }
}

// ========== 影片參數設定（切片長度等） ==========
async function loadVideoParams() {
  const messageEl = document.getElementById('videoParamsMessage');
  try {
    if (!ApiClient || !ApiClient.admin || !ApiClient.admin.settings) {
      showError('API 客戶端未正確初始化');
      return;
    }
    const data = await ApiClient.admin.settings.getVideoParams();
    const segInput = document.getElementById('setting_segment_seconds');
    if (segInput) {
      if (data?.segment_seconds != null) segInput.value = String(data.segment_seconds);
      else if (!segInput.value) segInput.value = '30';
    }
    if (messageEl) showHint(messageEl, '已載入影片參數設定', 'success');
  } catch (e) {
    console.error('[admin_settings] 載入影片參數設定失敗：', e);
    if (messageEl) showHint(messageEl, `載入失敗：${e?.message || ''}`, 'error');
  }
}

async function saveVideoParams() {
  const btn = document.getElementById('btnSaveVideoParams');
  const messageEl = document.getElementById('videoParamsMessage');
  try {
    if (!ApiClient || !ApiClient.admin || !ApiClient.admin.settings) {
      showError('API 客戶端未正確初始化');
      return;
    }
    setBtnLoading(btn, true);
    const segRaw = document.getElementById('setting_segment_seconds')?.value;
    const segment_seconds = parseInt(segRaw, 10);
    if (!Number.isFinite(segment_seconds)) throw new Error('請輸入切片長度（秒）');
    if (segment_seconds < 1 || segment_seconds > 600) throw new Error('切片長度範圍需為 1-600 秒');
    await ApiClient.admin.settings.setVideoParams({ segment_seconds });
    if (messageEl) showHint(messageEl, '影片參數設定已更新', 'success');
  } catch (e) {
    if (messageEl) showHint(messageEl, e?.message || '更新影片參數設定失敗', 'error');
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
    emptyRow.innerHTML = `<td colspan="7" class="text-center">尚無 API Key，請建立新的 Key。</td>`;
    apiKeyTableBody.appendChild(emptyRow);
    return;
  }

  state.apiKeys.forEach((key) => {
    const tr = document.createElement('tr');
    tr.className = 'api-key-row';
    tr.style.cursor = 'pointer';
    tr.dataset.keyId = key.id;
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
    `;
    apiKeyTableBody.appendChild(tr);
  });

  // 綁定行點擊事件
  apiKeyTableBody.querySelectorAll('tr.api-key-row').forEach((row) => {
    row.addEventListener('click', (e) => {
      // 如果點擊的是按鈕或其他互動元素，不觸發編輯
      if (e.target.tagName === 'BUTTON' || e.target.closest('button')) {
        return;
      }
      const keyId = row.dataset.keyId;
      if (keyId) {
        editApiKey(keyId);
      }
    });
  });
}

function getSelectedScopes(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return [];
  // 使用 Bootstrap form-check-input 選擇器（向後兼容舊的選擇器）
  const checkboxes = container.querySelectorAll('.form-check-input[type="checkbox"]:checked, input[type="checkbox"]:checked');
  return Array.from(checkboxes).map(cb => cb.value);
}

function setSelectedScopes(containerId, scopes) {
  const container = document.getElementById(containerId);
  if (!container) return;
  // 使用 Bootstrap form-check-input 選擇器（向後兼容舊的選擇器）
  const checkboxes = container.querySelectorAll('.form-check-input[type="checkbox"], input[type="checkbox"]');
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
    // 預設擁有者 ID 為當前使用者
    if (state.currentUser?.id && !apiKeyOwner.value) {
      apiKeyOwner.value = state.currentUser.id;
    }
    if (result.token) {
      state.lastRotatedToken = result.token;
      const copied = await copyToClipboard(result.token);
      showHint(
        apiKeyTokenMessage,
        `Token：${result.token}${copied ? '（已複製到剪貼簿）' : '（無法自動複製，請手動複製）'}`,
        'success'
      );
      showSuccess(copied ? '已建立並複製 Token' : '已建立 Token（請手動複製）');
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
  
  const btn = document.getElementById('btnRotateApiKey');
  try {
    if (btn) setBtnLoading(btn, true);
    
    const result = await ApiClient.admin.apiKeys.rotate(keyId);
    const index = state.apiKeys.findIndex((k) => String(k.id) === String(keyId));
    if (index >= 0) {
      state.apiKeys[index] = result;
      renderApiKeyTable();
    }
    if (result.token) {
      state.lastRotatedToken = result.token;
      const apiKeyTokenMessage = document.getElementById('apiKeyTokenMessage');
      const copied = await copyToClipboard(result.token);
      showHint(
        apiKeyTokenMessage,
        `Token：${result.token}${copied ? '（已複製到剪貼簿）' : '（無法自動複製，請手動複製）'}`,
        'success'
      );
      showSuccess(copied ? '已旋轉並複製 Token' : '已旋轉 Token（請手動複製）');
    } else {
      showSuccess('API Key 已成功旋轉');
    }
    
    // 關閉對話框
    const dialog = document.getElementById('editApiKeyDialog');
    if (dialog) dialog.classList.remove('show');
  } catch (error) {
    console.error('[admin_settings] 旋轉 API Key 失敗', error);
    showError(error?.message || '旋轉失敗，請稍後再試。');
  } finally {
    if (btn) setBtnLoading(btn, false);
  }
}

async function deleteApiKey(keyId) {
  if (!keyId) return;
  const target = state.apiKeys.find((k) => String(k.id) === String(keyId));
  if (!target) {
    showError('找不到指定的 API Key');
    return;
  }
  
  const confirmMsg = `確認要刪除此 API Key "${target.name}" 嗎？\n\n此操作將停用該 API Key，使其無法再使用。\n此操作無法復原。`;
  if (!confirm(confirmMsg)) return;
  
  const btn = document.getElementById('btnDeleteApiKey');
  try {
    if (btn) setBtnLoading(btn, true);
    
    // 使用停用功能作為刪除（因為後端可能沒有真正的刪除端點）
    await ApiClient.admin.apiKeys.update(keyId, { active: false });
    
    // 更新本地狀態
    const index = state.apiKeys.findIndex((k) => String(k.id) === String(keyId));
    if (index >= 0) {
      state.apiKeys[index].active = false;
      renderApiKeyTable();
    }
    
    showSuccess('API Key 已停用');
    
    // 關閉對話框
    const dialog = document.getElementById('editApiKeyDialog');
    if (dialog) dialog.classList.remove('show');
  } catch (error) {
    console.error('[admin_settings] 停用 API Key 失敗', error);
    showError(error?.message || '停用失敗，請稍後再試。');
  } finally {
    if (btn) setBtnLoading(btn, false);
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
    showError('更新狀態失敗，請稍後再試。');
  }
}

function editApiKey(keyId) {
  // 確保 keyId 是字符串
  const keyIdStr = String(keyId);
  const target = state.apiKeys.find((k) => String(k.id) === keyIdStr);
  if (!target) {
    console.error('[admin_settings] 找不到 API Key:', keyIdStr);
    showError('找不到指定的 API Key');
    return;
  }

  // 填充編輯表單
  const nameInput = document.getElementById('editApiKeyName');
  const rateInput = document.getElementById('editApiKeyRate');
  const quotaInput = document.getElementById('editApiKeyQuota');
  
  if (nameInput) nameInput.value = target.name || '';
  if (rateInput) rateInput.value = target.rate_limit_per_min || '';
  if (quotaInput) quotaInput.value = target.quota_per_day || '';
  setSelectedScopes('editApiKeyScopes', target.scopes || []);

  // 儲存當前編輯的 key ID
  const editForm = document.getElementById('editApiKeyForm');
  if (editForm) {
    editForm.dataset.keyId = keyIdStr;
  }

  // 儲存 keyId 到對話框元素，供旋轉和刪除按鈕使用
  const dialog = document.getElementById('editApiKeyDialog');
  if (dialog) {
    dialog.dataset.keyId = keyIdStr;
    dialog.classList.add('show');
  } else {
    console.error('[admin_settings] 找不到編輯對話框元素');
    showError('無法開啟編輯對話框');
  }
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
    const dialog = document.getElementById('editApiKeyDialog');
    if (dialog) dialog.classList.remove('show');
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

  // 影片參數設定
  document.getElementById('btnLoadVideoParams')?.addEventListener('click', loadVideoParams);
  document.getElementById('btnSaveVideoParams')?.addEventListener('click', saveVideoParams);
  
  // API Key 管理
  const apiKeyForm = document.getElementById('apiKeyForm');
  if (apiKeyForm) {
    apiKeyForm.addEventListener('submit', handleApiKeyCreate);
  }
  
  const editApiKeyForm = document.getElementById('editApiKeyForm');
  if (editApiKeyForm) {
    editApiKeyForm.addEventListener('submit', handleApiKeyEdit);
  }
  
  // 綁定旋轉和刪除按鈕
  const btnRotate = document.getElementById('btnRotateApiKey');
  if (btnRotate) {
    btnRotate.addEventListener('click', () => {
      const dialog = document.getElementById('editApiKeyDialog');
      const keyId = dialog?.dataset.keyId;
      if (keyId) {
        rotateApiKey(keyId);
      }
    });
  }
  
  const btnDelete = document.getElementById('btnDeleteApiKey');
  if (btnDelete) {
    btnDelete.addEventListener('click', () => {
      const dialog = document.getElementById('editApiKeyDialog');
      const keyId = dialog?.dataset.keyId;
      if (keyId) {
        deleteApiKey(keyId);
      }
    });
  }
  
  // 綁定關閉按鈕
  const closeBtn = document.getElementById('closeEditApiKeyDialog');
  if (closeBtn) {
    closeBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const dialog = document.getElementById('editApiKeyDialog');
      if (dialog) {
        dialog.classList.remove('show');
      }
    });
  }
  
  // 點擊背景關閉對話框
  const dialog = document.getElementById('editApiKeyDialog');
  if (dialog) {
    dialog.addEventListener('click', (e) => {
      if (e.target === dialog) {
        dialog.classList.remove('show');
      }
    });
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
      showError('此頁面僅限管理員使用，將返回首頁。');
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
    loadModelSettings(),
    loadDefaultApiKey(),
    loadDefaultAiKeyLimits(),
    loadVideoParams(),
    loadApiKeys(),
    loadBlacklist()
  ]);
  
  // 綁定新功能的事件
  bindNewFeatureEvents();
  
  const existing = localStorage.getItem('jwt');
  if (existing) renderJwtRemaining(existing);
}

// ========== 預設 Google API Key 管理 ==========
async function loadDefaultApiKey() {
  const apiKeyInput = document.getElementById('default_google_api_key');
  if (!apiKeyInput) return;
  
  try {
    const data = await ApiClient.admin.settings.getDefaultGoogleApiKey();
    if (data && data.api_key) {
      // 顯示遮罩後的 API Key
      apiKeyInput.value = '';
      apiKeyInput.placeholder = data.api_key || '未設定';
    } else {
      apiKeyInput.placeholder = '未設定預設 API Key';
    }
  } catch (error) {
    console.error('[admin_settings] 載入預設 API Key 失敗', error);
  }
}

async function saveDefaultApiKey() {
  const apiKeyInput = document.getElementById('default_google_api_key');
  const messageEl = document.getElementById('modelSettingsMessage');
  if (!apiKeyInput) return;
  
  const apiKey = apiKeyInput.value.trim();
  // 如果輸入框為空，不更新（保留現有設定）
  if (!apiKey) {
    return;
  }
  
  try {
    if (messageEl) {
      showHint(messageEl, '儲存中...', 'info');
    }
    await ApiClient.admin.settings.setDefaultGoogleApiKey(apiKey);
    // 清空輸入框（安全考量）
    apiKeyInput.value = '';
    apiKeyInput.placeholder = '已儲存（輸入後會遮罩顯示）';
  } catch (error) {
    console.error('[admin_settings] 儲存預設 API Key 失敗', error);
    if (messageEl) {
      showHint(messageEl, `儲存失敗：${error.message}`, 'error');
    }
    throw error;
  }
}

// ========== 系統預設 AI API Key 用量限制（RPM/RPD） ==========
async function loadDefaultAiKeyLimits() {
  const rpmEl = document.getElementById('default_ai_key_rpm');
  const rpdEl = document.getElementById('default_ai_key_rpd');
  if (!rpmEl || !rpdEl) return;

  try {
    const data = await ApiClient.admin.settings.getDefaultAiKeyLimits();
    if (data && data.rpm != null) rpmEl.value = String(data.rpm);
    if (data && data.rpd != null) rpdEl.value = String(data.rpd);
  } catch (e) {
    console.error('[admin_settings] 載入預設 AI key 限制失敗：', e);
  }
}

async function saveDefaultAiKeyLimits() {
  const rpmEl = document.getElementById('default_ai_key_rpm');
  const rpdEl = document.getElementById('default_ai_key_rpd');
  if (!rpmEl || !rpdEl) return;

  const rpm = parseInt((rpmEl.value || '').trim(), 10);
  const rpd = parseInt((rpdEl.value || '').trim(), 10);

  // 空值就不更新（保留既有設定）
  if (!Number.isFinite(rpm) || !Number.isFinite(rpd)) return;

  if (rpm < 1 || rpm > 300) throw new Error('RPM 範圍需為 1-300');
  if (rpd < 1 || rpd > 10000) throw new Error('RPD 範圍需為 1-10000');

  await ApiClient.admin.settings.setDefaultAiKeyLimits({ rpm, rpd });
}

// ========== 黑名單管理 ==========
async function loadBlacklist() {
  const tableBody = document.querySelector('#blacklistTable tbody');
  if (!tableBody) return;
  
  try {
    const data = await ApiClient.admin.blacklist.list();
    renderBlacklistTable(data || []);
  } catch (error) {
    console.error('[admin_settings] 載入黑名單失敗', error);
    if (tableBody) {
      tableBody.innerHTML = '<tr><td colspan="6">載入失敗，請稍後重試</td></tr>';
    }
  }
}

function renderBlacklistTable(entries) {
  const tableBody = document.querySelector('#blacklistTable tbody');
  if (!tableBody) return;
  
  if (!entries.length) {
    tableBody.innerHTML = '<tr><td colspan="6" class="text-center">黑名單為空</td></tr>';
    return;
  }
  
  tableBody.innerHTML = entries.map(entry => `
    <tr>
      <td>${entry.user_id}</td>
      <td>${entry.user_account}</td>
      <td>${entry.user_name}</td>
      <td>${entry.reason || '-'}</td>
      <td>${formatDate ? formatDate(entry.created_at) : entry.created_at}</td>
      <td>
        <button type="button" class="btn-tertiary" data-user-id="${entry.user_id}" data-action="remove">移除</button>
      </td>
    </tr>
  `).join('');
  
  // 綁定移除按鈕事件
  tableBody.querySelectorAll('button[data-action="remove"]').forEach(btn => {
    btn.addEventListener('click', () => removeFromBlacklist(btn.dataset.userId));
  });
}

async function addToBlacklist() {
  const userIdInput = document.getElementById('blacklistUserId');
  const reasonInput = document.getElementById('blacklistReason');
  const messageEl = document.getElementById('blacklistMessage');
  
  if (!userIdInput) return;
  
  const userId = parseInt(userIdInput.value.trim());
  if (!userId || userId < 1) {
    if (messageEl) {
      showHint(messageEl, '請輸入有效的使用者 ID', 'error');
    }
    return;
  }
  
  try {
    if (messageEl) {
      showHint(messageEl, '處理中...', 'info');
    }
    await ApiClient.admin.blacklist.add(userId, reasonInput?.value.trim() || null);
    if (messageEl) {
      showHint(messageEl, '已添加到黑名單', 'success');
    }
    // 清空輸入框
    userIdInput.value = '';
    if (reasonInput) reasonInput.value = '';
    // 重新載入黑名單
    await loadBlacklist();
  } catch (error) {
    console.error('[admin_settings] 添加到黑名單失敗', error);
    if (messageEl) {
      showHint(messageEl, `操作失敗：${error.message}`, 'error');
    }
  }
}

async function removeFromBlacklist(userId) {
  if (!confirm('確定要將此使用者從黑名單中移除嗎？')) return;
  
  const messageEl = document.getElementById('blacklistMessage');
  try {
    if (messageEl) {
      showHint(messageEl, '處理中...', 'info');
    }
    await ApiClient.admin.blacklist.remove(userId);
    if (messageEl) {
      showHint(messageEl, '已從黑名單移除', 'success');
    }
    // 重新載入黑名單
    await loadBlacklist();
  } catch (error) {
    console.error('[admin_settings] 從黑名單移除失敗', error);
    if (messageEl) {
      showHint(messageEl, `操作失敗：${error.message}`, 'error');
    }
  }
}

function bindNewFeatureEvents() {
  // 預設 API Key 相關按鈕
  const btnLoadDefaultApiKey = document.getElementById('btnLoadDefaultApiKey');
  if (btnLoadDefaultApiKey) {
    btnLoadDefaultApiKey.addEventListener('click', loadDefaultApiKey);
  }
  
  // 儲存模型設定時同時儲存預設 API Key
  const btnSaveModelSettings = document.getElementById('btnSaveModelSettings');
  if (btnSaveModelSettings) {
    btnSaveModelSettings.addEventListener('click', async () => {
      try {
        await saveModelSettings();
        await saveDefaultApiKey();
        await saveDefaultAiKeyLimits();
        const messageEl = document.getElementById('modelSettingsMessage');
        if (messageEl) {
          showHint(messageEl, '設定已儲存', 'success');
        }
      } catch (error) {
        const messageEl = document.getElementById('modelSettingsMessage');
        if (messageEl) {
          showHint(messageEl, `儲存失敗：${error.message}`, 'error');
        }
      }
    });
  }
  
  // 黑名單相關按鈕
  const btnAddToBlacklist = document.getElementById('btnAddToBlacklist');
  if (btnAddToBlacklist) {
    btnAddToBlacklist.addEventListener('click', addToBlacklist);
  }
}

window.__bootAdminSettings = boot;
export default { boot };
boot();

