import { ApiClient } from './APIClient.js';

const state = {
  usersStats: [],
  currentUser: null,
  selectedUserDetail: null,
  originalBlacklist: null,
  originalActive: null,
  pageNow: 1,
  pageSize: 20,
  scrollPosition: 0
};

const elements = {
  usersStatsList: document.getElementById('usersStatsList'),
  prevBtn: document.getElementById('prevBtn'),
  nextBtn: document.getElementById('nextBtn'),
  pageInput: document.getElementById('pageInput'),
  pageTotal: document.getElementById('pageTotal'),
  pageSize: document.getElementById('pageSize'),
  totalCount: document.getElementById('totalCount'),

  // 使用者詳情 Modal
  userDetailModal: document.getElementById('userDetailModal'),
  closeUserDetailModal: document.getElementById('closeUserDetailModal'),
  cancelUserDetail: document.getElementById('cancelUserDetail'),
  saveUserDetail: document.getElementById('saveUserDetail'),
  userDetailMessage: document.getElementById('userDetailMessage'),

  detailUserId: document.getElementById('detailUserId'),
  detailAccount: document.getElementById('detailAccount'),
  detailName: document.getElementById('detailName'),
  detailRole: document.getElementById('detailRole'),
  detailActive: document.getElementById('detailActive'),
  detailGender: document.getElementById('detailGender'),
  detailBirthday: document.getElementById('detailBirthday'),
  detailPhone: document.getElementById('detailPhone'),
  detailEmail: document.getElementById('detailEmail'),
  detailPasswordHash: document.getElementById('detailPasswordHash'),
  detailBlacklist: document.getElementById('detailBlacklist'),
  detailBlacklistState: document.getElementById('detailBlacklistState'),
  detailBlacklistReason: document.getElementById('detailBlacklistReason'),
};

function formatNumber(value) {
  if (value === null || value === undefined) return '-';
  return Number(value).toLocaleString();
}

function formatTokensWan(value) {
  if (value === null || value === undefined) return '-';
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  return `${(n / 10000).toFixed(2)}萬`;
}

function showHint(el, message, type = 'info') {
  if (!el) return;
  el.textContent = message || '';
  el.classList.remove('success', 'error', 'info');
  if (message) el.classList.add(type);
}

function setDisabled(element, disabled) {
  if (element) {
    element.disabled = disabled;
  }
}

async function init() {
  try {
    const response = window.__CURRENT_USER || await ApiClient.getCurrentUser();
    const user = response?.user || response;
    if (!user || user.role !== 'admin') {
      alert('此頁面僅限管理員使用，將返回首頁。');
      window.location.href = '/home';
      return;
    }
    state.currentUser = user;
    bindEvents();
    await loadUsersStats();
  } catch (error) {
    console.error('[AdminUsers] 初始化失敗', error);
    alert('載入管理介面失敗，請重新整理頁面。');
  }
}

function bindEvents() {
  // 分頁事件
  if (elements.prevBtn) {
    elements.prevBtn.addEventListener('click', () => {
      if (state.pageNow > 1) {
        state.pageNow--;
        loadUsersStats();
      }
    });
  }
  if (elements.nextBtn) {
    elements.nextBtn.addEventListener('click', () => {
      state.pageNow++;
      loadUsersStats();
    });
  }
  if (elements.pageInput) {
    elements.pageInput.addEventListener('change', () => {
      const inputValue = parseInt(elements.pageInput.value, 10);
      const maxPage = parseInt(elements.pageInput?.max || "1", 10);
      if (inputValue && inputValue >= 1 && inputValue <= maxPage) {
        state.pageNow = inputValue;
        loadUsersStats();
      } else {
        elements.pageInput.value = state.pageNow;
      }
    });
    elements.pageInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        const inputValue = parseInt(elements.pageInput.value, 10);
        const maxPage = parseInt(elements.pageInput?.max || "1", 10);
        if (inputValue && inputValue >= 1 && inputValue <= maxPage) {
          state.pageNow = inputValue;
          loadUsersStats();
        } else {
          elements.pageInput.value = state.pageNow;
        }
      }
    });
  }
  if (elements.pageSize) {
    elements.pageSize.addEventListener('change', () => {
      state.pageSize = parseInt(elements.pageSize.value, 10) || 20;
      state.pageNow = 1;
      loadUsersStats();
    });
    elements.pageSize.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        state.pageSize = parseInt(elements.pageSize.value, 10) || 20;
        state.pageNow = 1;
        loadUsersStats();
      }
    });
  }

  // 使用者詳情 modal
  if (elements.closeUserDetailModal) {
    elements.closeUserDetailModal.addEventListener('click', closeUserDetailModal);
  }
  if (elements.cancelUserDetail) {
    elements.cancelUserDetail.addEventListener('click', closeUserDetailModal);
  }
  if (elements.userDetailModal) {
    elements.userDetailModal.addEventListener('click', (e) => {
      if (e.target === elements.userDetailModal) closeUserDetailModal();
    });
  }
  if (elements.saveUserDetail) {
    elements.saveUserDetail.addEventListener('click', saveUserDetail);
  }
  if (elements.detailBlacklist) {
    elements.detailBlacklist.addEventListener('change', () => {
      updateBlacklistStateText();
    });
  }
}

function openUserDetailModal(detail) {
  if (!elements.userDetailModal || !detail) return;
  state.selectedUserDetail = detail;
  state.originalBlacklist = {
    is_blacklisted: !!detail.is_blacklisted,
    reason: detail.blacklist_reason || ''
  };
  state.originalActive = !!detail.active;

  if (elements.detailUserId) elements.detailUserId.value = detail.user_id ?? '';
  if (elements.detailAccount) elements.detailAccount.value = detail.account ?? '';
  if (elements.detailName) elements.detailName.value = detail.name ?? '';
  if (elements.detailRole) elements.detailRole.value = detail.role ?? '';
  if (elements.detailActive) elements.detailActive.value = detail.active ? 'true' : 'false';
  if (elements.detailGender) elements.detailGender.value = detail.gender ?? '';
  if (elements.detailBirthday) elements.detailBirthday.value = detail.birthday ?? '-';
  if (elements.detailPhone) elements.detailPhone.value = detail.phone ?? '';
  if (elements.detailEmail) elements.detailEmail.value = detail.email ?? '';
  if (elements.detailPasswordHash) elements.detailPasswordHash.value = detail.password_hash ?? '';

  if (elements.detailBlacklist) elements.detailBlacklist.checked = !!detail.is_blacklisted;
  if (elements.detailBlacklistReason) elements.detailBlacklistReason.value = detail.blacklist_reason ?? '';

  updateBlacklistStateText();
  showHint(elements.userDetailMessage, '');
  elements.userDetailModal.classList.add('show');
}

function closeUserDetailModal() {
  if (!elements.userDetailModal) return;
  elements.userDetailModal.classList.remove('show');
  state.selectedUserDetail = null;
  state.originalBlacklist = null;
  state.originalActive = null;
  showHint(elements.userDetailMessage, '');
}

function updateBlacklistStateText() {
  if (!elements.detailBlacklistState || !elements.detailBlacklist) return;
  elements.detailBlacklistState.textContent = elements.detailBlacklist.checked ? '已加入黑名單' : '未加入黑名單';
  elements.detailBlacklistState.style.color = elements.detailBlacklist.checked ? '#C45B5B' : '#2E2E2E';
}

async function fetchAndOpenUserDetail(userId) {
  try {
    showHint(elements.userDetailMessage, '載入中...', 'info');
    const detail = await ApiClient.admin.users.getDetail(userId);
    openUserDetailModal(detail);
  } catch (e) {
    console.error('[AdminUsers] 載入使用者詳情失敗', e);
    alert(e?.message || '載入使用者詳情失敗');
  }
}

async function saveUserDetail() {
  if (!state.selectedUserDetail || !elements.detailUserId) return;
  const userId = parseInt(elements.detailUserId.value, 10);
  if (!Number.isFinite(userId)) return;

  const wantActive = String(elements.detailActive?.value || 'true') === 'true';
  const wantBlacklisted = !!elements.detailBlacklist?.checked;
  const reason = (elements.detailBlacklistReason?.value || '').trim() || null;

  const original = state.originalBlacklist || { is_blacklisted: false, reason: '' };
  const originalBlacklisted = !!original.is_blacklisted;
  const originalReason = (original.reason || '').trim();
  const originalActive = state.originalActive;

  try {
    setDisabled(elements.saveUserDetail, true);
    showHint(elements.userDetailMessage, '儲存中...', 'info');

    const activeChanged = (originalActive !== null && wantActive !== originalActive);
    const blacklistChanged = !(wantBlacklisted === originalBlacklisted && ((reason || '') === originalReason));

    // 沒有變更：不打 API
    if (!activeChanged && !blacklistChanged) {
      showHint(elements.userDetailMessage, '沒有變更', 'success');
      setTimeout(() => closeUserDetailModal(), 400);
      return;
    }

    // 1) 帳號啟用狀態
    if (activeChanged) {
      await ApiClient.admin.users.setActive(userId, wantActive);
      state.originalActive = wantActive;
    }

    if (!originalBlacklisted && wantBlacklisted) {
      // 加入黑名單
      await ApiClient.admin.blacklist.add(userId, reason);
    } else if (originalBlacklisted && !wantBlacklisted) {
      // 移除黑名單
      await ApiClient.admin.blacklist.remove(userId);
    } else if (originalBlacklisted && wantBlacklisted) {
      // 仍在黑名單：用 add 來更新 reason（後端已改成 idempotent / 更新式）
      await ApiClient.admin.blacklist.add(userId, reason);
    }

    showHint(elements.userDetailMessage, '已儲存', 'success');

    // 更新表格狀態（不用重抓整頁，直接就地更新）
    const idx = state.usersStats.findIndex(u => Number(u.user_id) === Number(userId));
    if (idx >= 0) {
      state.usersStats[idx].is_blacklisted = wantBlacklisted;
      state.usersStats[idx].use_default_api_key = !wantBlacklisted;
      renderUsersStatsTable({ items: state.usersStats, item_total: state.usersStats.length, page_now: state.pageNow, page_size: state.pageSize });
    }

    setTimeout(() => closeUserDetailModal(), 400);
  } catch (e) {
    console.error('[AdminUsers] 儲存使用者詳情失敗', e);
    showHint(elements.userDetailMessage, e?.message || '儲存失敗', 'error');
  } finally {
    setDisabled(elements.saveUserDetail, false);
  }
}

async function loadUsersStats() {
  if (!elements.usersStatsList) return;
  
  elements.usersStatsList.innerHTML = '<tr><td colspan="7" class="text-center">載入中...</td></tr>';
  
  try {
    // 注意：這裡假設API支持分頁，如果沒有，需要後端添加
    const data = await ApiClient.admin.users.getStats({
      page: state.pageNow,
      size: state.pageSize,
    });
    
    const items = Array.isArray(data) ? data : (data?.items || []);
    const total = data?.item_total ?? items.length;
    const page = data?.page_now ?? state.pageNow;
    const size = data?.page_size ?? state.pageSize;
    const pageTotal = data?.page_total || (items.length < size ? page : page + 1);
    
    state.usersStats = items;
    renderUsersStatsTable({ items, item_total: total, page_now: page, page_size: size, page_total: pageTotal });
    
    // 恢復滾動位置
    if (state.scrollPosition > 0) {
      window.scrollTo(0, state.scrollPosition);
      state.scrollPosition = 0;
    }
  } catch (error) {
    console.error('[AdminUsers] 載入使用者統計失敗', error);
    if (elements.usersStatsList) {
      elements.usersStatsList.innerHTML = '<tr><td colspan="7" class="text-center">載入失敗，請稍後重試</td></tr>';
    }
  }
}

function renderUsersStatsTable(resp) {
  if (!elements.usersStatsList) return;
  
  const items = resp?.items || state.usersStats || [];
  const total = resp?.item_total ?? items.length;
  const page = resp?.page_now ?? state.pageNow;
  const size = resp?.page_size ?? state.pageSize;
  const pageTotal = resp?.page_total || (items.length < size ? page : page + 1);

  // 更新分頁資訊
  if (elements.pageInput) {
    elements.pageInput.value = page;
    elements.pageInput.max = pageTotal;
  }
  if (elements.pageTotal) {
    elements.pageTotal.textContent = `/ ${pageTotal}`;
  }
  if (elements.totalCount) {
    elements.totalCount.textContent = total;
  }
  if (elements.pageSize) {
    elements.pageSize.value = size;
  }

  setDisabled(elements.prevBtn, page <= 1);
  setDisabled(elements.nextBtn, page >= pageTotal);

  state.pageNow = page;

  if (!items.length) {
    elements.usersStatsList.innerHTML = '<tr><td colspan="7" class="text-center">尚無使用者資料</td></tr>';
    return;
  }
  
  elements.usersStatsList.innerHTML = items.map(user => `
    <tr class="user-row" data-user-id="${user.user_id}" style="cursor: pointer;">
      <td>${user.user_id}</td>
      <td>${user.account}</td>
      <td>${user.name}</td>
      <td>${formatTokensWan(user.total_token_usage)}</td>
      <td>${formatNumber(user.total_chat_messages)}</td>
      <td>${user.use_default_api_key ? '是' : '否'}</td>
      <td>${user.is_blacklisted ? '<span style="color: red;">是</span>' : '否'}</td>
    </tr>
  `).join('');

  // 綁定點擊事件：打開詳情 modal
  elements.usersStatsList.querySelectorAll('tr.user-row').forEach((row) => {
    row.addEventListener('click', () => {
      const userId = row.dataset.userId;
      if (userId) fetchAndOpenUserDetail(userId);
    });
  });
}

document.addEventListener('DOMContentLoaded', init);
