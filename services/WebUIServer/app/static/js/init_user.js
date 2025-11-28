import { ApiClient } from './APIClient.js';

async function loadUserAndSwitchUI() {
  try {
    const response = window.__CURRENT_USER || await ApiClient.getCurrentUser();
    // API 返回格式為 {user: {...}}，需要提取 user 物件
    const currentUser = response?.user || response;
    window.__CURRENT_USER = currentUser;
    localStorage.setItem('user_role', currentUser?.role ?? '');

    const isAdmin = currentUser?.role === 'admin';
    console.log('[init_user] 完整使用者資料:', currentUser);
    console.log('[init_user] 使用者角色:', currentUser?.role, '是否為管理員:', isAdmin);
    
    // 檢查是否為 admin 頁面（根據 URL 或 active_page）
    const isAdminPage = window.location.pathname.startsWith('/admin') || 
                        document.body.dataset.activePage?.startsWith('admin_');
    
    // 只有在非 admin 頁面時才需要切換 sidebar（admin 頁面已經直接載入正確的 sidebar）
    if (!isAdminPage) {
      // 切換 sidebar 和 mobile_nav 的顯示
      const sidebarUser = document.getElementById('sidebar-user');
      const sidebarAdmin = document.getElementById('sidebar-admin');
      const mobileNavUser = document.getElementById('mobile-nav-user');
      const mobileNavAdmin = document.getElementById('mobile-nav-admin');
      
      if (isAdmin) {
        // 顯示 admin 版本，隱藏 user 版本
        if (sidebarUser) sidebarUser.classList.add('hidden');
        if (sidebarAdmin) sidebarAdmin.classList.remove('hidden');
        if (mobileNavUser) mobileNavUser.classList.add('hidden');
        if (mobileNavAdmin) mobileNavAdmin.classList.remove('hidden');
      } else {
        // 顯示 user 版本，隱藏 admin 版本
        if (sidebarUser) sidebarUser.classList.remove('hidden');
        if (sidebarAdmin) sidebarAdmin.classList.add('hidden');
        if (mobileNavUser) mobileNavUser.classList.remove('hidden');
        if (mobileNavAdmin) mobileNavAdmin.classList.add('hidden');
      }
    }
    
    // 處理 data-requires-admin 元素（向後兼容）
    const adminElements = document.querySelectorAll('[data-requires-admin]');
    if (adminElements.length) {
      adminElements.forEach((el) => {
        if (isAdmin) {
          el.classList.remove('hidden');
        } else {
          el.classList.add('hidden');
        }
      });
    }
  } catch (error) {
    console.error('[init_user] 載入使用者資訊失敗', error);
  }
}

// 滾動條互動效果：點擊頁面時顯示滾動條（透明度 70%），平常透明度 10%
// 所有動畫效果由 CSS 處理，JavaScript 只負責添加/移除類
function initScrollbarInteraction() {
  let scrollbarTimeout = null;
  const SCROLLBAR_ACTIVE_DURATION = 200; // 0.2 秒後恢復到平常狀態

  // 當用戶點擊或滾動時，顯示滾動條
  function activateScrollbar() {
    // 添加 active 類，CSS 會自動處理動畫
    document.body.classList.add('scrollbar-active');
    
    // 清除之前的計時器
    if (scrollbarTimeout) {
      clearTimeout(scrollbarTimeout);
    }
    
    // 2 秒後移除類，CSS transition 會自動處理變淡動畫
    scrollbarTimeout = setTimeout(() => {
      document.body.classList.remove('scrollbar-active');
    }, SCROLLBAR_ACTIVE_DURATION);
  }

  // 監聽點擊事件
  document.addEventListener('click', activateScrollbar, true);
  
  // 監聽滾動事件（當用戶滾動時也顯示滾動條）
  document.addEventListener('scroll', activateScrollbar, true);
  
  // 監聽滾動條拖拽
  document.addEventListener('mousedown', activateScrollbar, true);
  document.addEventListener('mouseup', activateScrollbar, true);
}

// 活動監聽和自動刷新 Token 邏輯
// 全域變數：用戶活動狀態（每10分鐘會自動更新為 false）
window.userActivityStatus = true; // 預設為 true，表示用戶有活動

function initAutoTokenRefresh() {
  const ACTIVITY_CHECK_INTERVAL = 10 * 60 * 1000; // 10分鐘（毫秒）
  let activityCheckInterval = null;

  // 標記用戶為活動狀態（當使用者移動滑鼠或滾動畫面時）
  function markUserActive() {
    window.userActivityStatus = true;
  }

  // 每10分鐘將變數更新為 false，並檢查是否需要刷新 Token
  function updateActivityStatusAndRefreshToken() {
    // 保存當前狀態（在設為 false 之前）
    const hadActivity = window.userActivityStatus;
    
    // 將全域變數更新為 false
    window.userActivityStatus = false;
    console.log('[AutoTokenRefresh] 10分鐘計時器觸發，將 userActivityStatus 設為 false');

    // 檢查變數狀態並刷新 Token
    // 如果變數在更新前是 false（表示10分鐘內沒有活動），刷新 Token
    if (!hadActivity) {
      async function refreshToken() {
        try {
          const token = localStorage.getItem('jwt');
          if (!token) {
            console.warn('[AutoTokenRefresh] 沒有 token，跳過刷新');
            return;
          }

          console.log('[AutoTokenRefresh] 10分鐘內無活動，刷新 Token');
          const data = await ApiClient.refreshUserToken();
          const newToken = data?.access_token || data?.token || data?.jwt;
          
          if (newToken) {
            if (window.AuthService && typeof window.AuthService.saveToken === 'function') {
              window.AuthService.saveToken(newToken);
            } else {
              localStorage.setItem('jwt', newToken);
            }
            console.log('[AutoTokenRefresh] Token 已刷新');
            
            // 如果設定頁面有顯示剩餘時間，更新它
            if (typeof window.renderJwtRemaining === 'function') {
              window.renderJwtRemaining(newToken);
            }
          }
        } catch (error) {
          console.error('[AutoTokenRefresh] 刷新 Token 失敗:', error);
          // 如果刷新失敗（可能是 token 已過期），導向登入頁面
          if (error.status === 401 || error.status === 403) {
            if (window.AuthService && typeof window.AuthService.delToken === 'function') {
              window.AuthService.delToken();
            } else {
              localStorage.removeItem('jwt');
            }
            window.location.href = '/auth';
          }
        }
      }

      // 執行刷新
      refreshToken();
    } else {
      console.log('[AutoTokenRefresh] 10分鐘內有活動，不刷新 Token');
    }
  }

  // 監聽用戶活動事件（移動滑鼠或滾動畫面）
  const activityEvents = ['mousemove', 'mousedown', 'keypress', 'scroll', 'touchstart', 'click'];
  activityEvents.forEach(eventType => {
    document.addEventListener(eventType, markUserActive, { passive: true });
  });

  // 每10分鐘執行一次：將變數設為 false，並檢查是否需要刷新 Token
  activityCheckInterval = setInterval(updateActivityStatusAndRefreshToken, ACTIVITY_CHECK_INTERVAL);
  
  console.log('[AutoTokenRefresh] 活動監聽已啟動，每10分鐘檢查一次');
}

document.addEventListener('DOMContentLoaded', async () => {
  const token = localStorage.getItem('jwt');
  if (!token) {
    // 沒有 token，導向登入頁面
    if (window.location.pathname !== '/auth' && !window.location.pathname.includes('/auth')) {
      window.location.href = '/auth';
    }
    return;
  }
  
  try {
    await loadUserAndSwitchUI();
    
    // 檢查當前頁面是否需要 admin 權限
    const isAdminPage = window.location.pathname.startsWith('/admin');
    const userRole = localStorage.getItem('user_role');
    const isAdmin = userRole === 'admin';
    
    // 如果在 admin 頁面但不是 admin，導向 home
    if (isAdminPage && !isAdmin) {
      console.warn('[init_user] 非管理員嘗試訪問管理頁面，導向首頁');
      window.location.href = '/home';
      return;
    }
    
    // 如果是 admin 但在非 admin 頁面（除了設定頁面），可以選擇導向 admin_home
    // 這裡我們不強制導向，讓 admin 可以訪問所有頁面（如果需要限制，可以在後端處理）
  } catch (error) {
    console.error('[init_user] 初始化失敗:', error);
    // 如果載入用戶資訊失敗，可能是 token 過期，導向登入頁面
    if (error.status === 401 || error.status === 403) {
      window.location.href = '/auth';
    }
  }
  
  // 初始化滾動條互動效果
  initScrollbarInteraction();
  
  // 初始化自動 Token 刷新
  initAutoTokenRefresh();
});

