import settings from "./settings.js";
import { ApiClient } from "./APIClient.js";
import {AuthService} from"./AuthService.js";
//jwt剩餘時間
let __jwtCountdownTimer = null;
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


function fillUser(user) {
  // user_id 儲存
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
    location.href = '/auth.html';
    return;
  }

  try {
    const me = await ApiClient.getCurrentUser();
    console.log('[user_profile] /users/me =>', me);

    // 這行是重點：API 回來的是 { user: {...} }，要取內層
    const data = me && me.user ? me.user : me;

    fillUser(data);
    showSuccess && showSuccess('已載入目前使用者資料');
  } catch (e) {
    console.error('[user_profile] 載入 /users/me 失敗：', e);
    // ⚠️ 有 JWT 但 API 失敗，不要馬上導回 auth，避免被 bounce 到 chat
    showError && showError(e?.message || '載入使用者資料失敗，請稍後再試');
  }
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
      btn.classList.add('is-loading'); // 可自行加 CSS
    } else {
      if (btn.dataset._origText) btn.textContent = btn.dataset._origText;
      btn.disabled = false;
      btn.removeAttribute('aria-busy');
      btn.classList.remove('is-loading');
    }
  }
  // 同時掛全域，讓其他頁也可用
  if (typeof window !== 'undefined') window.setBtnLoading = setBtnLoading;
})();

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

    await ApiClient.updateUserProfile(updateData);              // ✅ PATCH /users/me
    const latest = await ApiClient.getCurrentUser();            // 再 GET /users/me
    const data = latest?.user ? latest.user : latest;           // 有些 BFF 會包一層 {user: {...}}
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

    // 不再做格式驗證，交由後端檢查
    const res = await ApiClient.changePassword({ old_password, new_password });

    // 假設後端成功時會傳回 { message: "密碼已變更" }
    if (res?.message) showSuccess(res.message);
    else showSuccess('密碼已變更');

    // 清除輸入與關閉 dialog
    document.getElementById('current_password').value = '';
    document.getElementById('new_password').value = '';
    dlg.close();
  } catch (e) {
    // 後端錯誤時，handleApiError 會丟出 Error(message)
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
    // 走你已經實作的 API
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

    // 兼容不同欄位名
    const newToken = data?.access_token || data?.token || data?.jwt;
    if (!newToken) throw new Error('回應未含新 JWT');

    // 存起來（你已經有 AuthService 可用）
    if (window.AuthService && typeof window.AuthService.saveToken === 'function') {
      window.AuthService.saveToken(newToken);
    } else {
      localStorage.setItem('jwt', newToken);
    }

    // 改為顯示剩餘時間（而不是整串 token）
    renderJwtRemaining(newToken);
    showSuccess('已重新取得並覆寫 JWT');
  } catch (e) {
    showError(e?.message || '重新取得 JWT 失敗');
  } finally {
    setBtnLoading(btn, false);
  }
}

// 載入應用程式設定
async function loadAppSettings() {
  try {
    if (!ApiClient || !ApiClient.settings) {
      console.error('[settings] ApiClient.settings 未定義');
      showError && showError('API 客戶端未正確初始化');
      return;
    }

    const response = await ApiClient.settings.get();
    const settings = response.settings || response;
    
    // 先載入時區列表（確保在設置值之前列表已載入）
    await loadTimezones();
    
    // 填充應用程式設定
    if (settings && settings.timezone) {
      const timezoneSelect = document.getElementById('setting_timezone');
      if (timezoneSelect) {
        timezoneSelect.value = settings.timezone;
        console.log('[settings] 設置時區為:', settings.timezone);
      }
    }
    
    if (settings && settings.diary_auto_refresh_interval_minutes !== undefined) {
      const diaryIntervalInput = document.getElementById('setting_diary_auto_refresh_interval');
      if (diaryIntervalInput) diaryIntervalInput.value = settings.diary_auto_refresh_interval_minutes;
    } else {
      // 如果沒有設定，使用預設值 30 分鐘
      const diaryIntervalInput = document.getElementById('setting_diary_auto_refresh_interval');
      if (diaryIntervalInput && !diaryIntervalInput.value) {
        diaryIntervalInput.value = 30;
      }
    }
  } catch (e) {
    console.error('[settings] 載入應用程式設定失敗：', e);
    showError && showError('載入應用程式設定失敗：' + (e?.message || ''));
  }
}

// 載入時區列表
async function loadTimezones() {
  try {
    if (!ApiClient || !ApiClient.settings) {
      console.error('[settings] ApiClient.settings 未定義');
      return;
    }

    const response = await ApiClient.settings.getTimezones();
    const timezoneSelect = document.getElementById('setting_timezone');
    if (!timezoneSelect) return;
    
    timezoneSelect.innerHTML = '<option value="">請選擇時區</option>';
    
    // 處理後端返回的格式：可能是 { timezones: [...] } 或直接是數組/對象
    const timezones = response.timezones || response;
    
    if (Array.isArray(timezones)) {
      // 如果是數組，可能是字符串數組或對象數組
      timezones.forEach(tz => {
        const option = document.createElement('option');
        if (typeof tz === 'string') {
          // 字符串格式：直接使用
          option.value = tz;
          option.textContent = tz;
        } else if (typeof tz === 'object' && tz !== null) {
          // 對象格式：{ value: "...", label: "..." } 或 { timezone: "...", name: "..." }
          const value = tz.value || tz.timezone || Object.keys(tz)[0];
          const label = tz.label || tz.name || tz[value] || value;
          option.value = value;
          option.textContent = label;
        }
        timezoneSelect.appendChild(option);
      });
    } else if (typeof timezones === 'object' && timezones !== null) {
      // 如果是物件格式（字典），遍歷鍵值
      Object.keys(timezones).forEach(key => {
        const option = document.createElement('option');
        option.value = key;
        option.textContent = timezones[key] || key;
        timezoneSelect.appendChild(option);
      });
    }
    
    console.log('[settings] 時區列表載入完成，共', timezoneSelect.options.length - 1, '個時區');
  } catch (e) {
    console.error('[settings] 載入時區列表失敗：', e);
    const timezoneSelect = document.getElementById('setting_timezone');
    if (timezoneSelect) {
      timezoneSelect.innerHTML = '<option value="">載入失敗，請重新整理頁面</option>';
    }
  }
}

// 儲存應用程式設定
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

    // 移除 undefined 值
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

// 載入模型設定
async function loadModelSettings() {
  try {
    if (!ApiClient || !ApiClient.settings) {
      console.error('[settings] ApiClient.settings 未定義');
      showError && showError('API 客戶端未正確初始化');
      return;
    }

    const response = await ApiClient.settings.get();
    const settings = response.settings || response;
    
    if (!settings) {
      console.warn('[settings] 未找到設定資料');
      return;
    }
    
    // 填充模型設定
    if (settings.default_llm_provider) {
      const providerSelect = document.getElementById('setting_llm_provider');
      if (providerSelect) providerSelect.value = settings.default_llm_provider;
    }
    
    if (settings.default_llm_model) {
      const modelInput = document.getElementById('setting_llm_model');
      if (modelInput) modelInput.value = settings.default_llm_model;
    }
    
    // 填充 LLM 供應商 API 金鑰（根據 API 格式：llm_model_api.providers）
    const llmProviders = settings.llm_model_api?.providers || settings.llm_providers;
    if (llmProviders && typeof llmProviders === 'object') {
      // 處理 providers 對象
      Object.keys(llmProviders).forEach(providerKey => {
        const provider = llmProviders[providerKey];
        if (provider && provider.api_key) {
          const keyInput = document.getElementById(`provider_${providerKey}_api_key`);
          if (keyInput) {
            keyInput.value = provider.api_key;
          }
        }
      });
      
      // 也支援直接訪問 google, openai, anthropic
      if (llmProviders.google?.api_key) {
        const googleKeyInput = document.getElementById('provider_google_api_key');
        if (googleKeyInput) googleKeyInput.value = llmProviders.google.api_key;
      }
      
      if (llmProviders.openai?.api_key) {
        const openaiKeyInput = document.getElementById('provider_openai_api_key');
        if (openaiKeyInput) openaiKeyInput.value = llmProviders.openai.api_key;
      }
      
      if (llmProviders.anthropic?.api_key) {
        const anthropicKeyInput = document.getElementById('provider_anthropic_api_key');
        if (anthropicKeyInput) anthropicKeyInput.value = llmProviders.anthropic.api_key;
      }
    }
  } catch (e) {
    console.error('[settings] 載入模型設定失敗：', e);
    showError && showError('載入模型設定失敗：' + (e?.message || ''));
  }
}

// 儲存模型設定
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

    // 構建 LLM 供應商配置
    // 總是發送所有供應商的當前值，這樣可以正確更新和清除
    const llmProviders = {};
    const googleKey = (document.getElementById('provider_google_api_key')?.value || '').trim();
    const openaiKey = (document.getElementById('provider_openai_api_key')?.value || '').trim();
    const anthropicKey = (document.getElementById('provider_anthropic_api_key')?.value || '').trim();

    // 發送所有供應商的設定（包括空值，用於清除）
    llmProviders.google = { api_key: googleKey, model_names: [] };
    llmProviders.openai = { api_key: openaiKey, model_names: [] };
    llmProviders.anthropic = { api_key: anthropicKey, model_names: [] };

    updateData.llm_providers = llmProviders;

    // 移除 undefined 值
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

function bindEvents() {
  document.getElementById('btnSaveProfile')?.addEventListener('click', saveProfile);
  document.getElementById('btnChangePassword')?.addEventListener('click', () => {
    document.getElementById('changepassworddialog').showModal();
  });
  document.getElementById('btnSubmitChangePassword')?.addEventListener('click', changePassword);
  document.getElementById('btnRefreshJwt')?.addEventListener('click', refreshJwt);
  document.getElementById('btnSaveAppSettings')?.addEventListener('click', saveAppSettings);
  document.getElementById('btnSaveModelSettings')?.addEventListener('click', saveModelSettings);
}

async function boot() {
  // 未登入導回首頁（TEST.html）
  const token = localStorage.getItem('jwt');
  if (!token) {
    showError('尚未登入，3 秒後回首頁');
    setTimeout(()=>location.href='/', 3000);
    return;
  }
  bindEvents();
  await loadMe();
  await loadAppSettings();
  await loadModelSettings();
  const existing = localStorage.getItem('jwt');
  if (existing) renderJwtRemaining(existing);
}

// 讓 HTML 的 onload 呼叫
window.__bootUserProfile = boot;

export default { boot };
boot();

