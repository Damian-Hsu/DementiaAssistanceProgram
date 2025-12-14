import { AuthService } from "./AuthService.js";

// 登出確認對話框
const logoutConfirmDialog = document.getElementById('logoutConfirmDialog');
const logoutCancelBtn = document.getElementById('logoutCancelBtn');
const logoutConfirmBtn = document.getElementById('logoutConfirmBtn');

// 顯示登出確認對話框
function showLogoutConfirm() {
  if (logoutConfirmDialog) {
    logoutConfirmDialog.showModal();
  }
}

// 關閉登出確認對話框
function closeLogoutConfirm() {
  if (logoutConfirmDialog) {
    logoutConfirmDialog.close();
  }
}

// 執行登出
function performLogout() {
  try {
    // 清除所有認證相關的資料
    AuthService.delToken();
    localStorage.removeItem('user_role');
    localStorage.removeItem('user_id');
    // 清除緩存的用戶資訊
    if (window.__CURRENT_USER) {
      delete window.__CURRENT_USER;
    }
    
    // 立刻換頁到登入頁面
    window.location.replace('/auth');
  } catch (err) {
    console.error("登出錯誤:", err);
    showError("登出時發生錯誤");
  }
}

// 綁定登出按鈕事件
const logoutbtn = document.getElementById("logoutbtn");
if (logoutbtn) {
  logoutbtn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    showLogoutConfirm();
  });
}

// 設定頁面底部登出按鈕
const settingsLogoutBtn = document.getElementById("logoutbtn_settings");
if (settingsLogoutBtn) {
  settingsLogoutBtn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    showLogoutConfirm();
  });
}

// 綁定取消按鈕事件
if (logoutCancelBtn) {
  logoutCancelBtn.addEventListener("click", () => {
    closeLogoutConfirm();
  });
}

// 綁定確認登出按鈕事件
if (logoutConfirmBtn) {
  logoutConfirmBtn.addEventListener("click", () => {
    closeLogoutConfirm();
    performLogout();
  });
}

// 點擊對話框外部關閉（可選）
if (logoutConfirmDialog) {
  logoutConfirmDialog.addEventListener("click", (e) => {
    if (e.target === logoutConfirmDialog) {
      closeLogoutConfirm();
    }
  });

  // ESC 鍵關閉對話框
  logoutConfirmDialog.addEventListener("cancel", (e) => {
    e.preventDefault();
    closeLogoutConfirm();
  });
}

// 舊版相容性處理
document.addEventListener('DOMContentLoaded', function(){
  try {
    var btn = document.getElementById('sidebarLogoutBtn');
    if (btn) {
      btn.addEventListener('click', function(e){
        e.preventDefault();
        e.stopPropagation();
        showLogoutConfirm();
      });
    }
    
    // 移動端登出按鈕
    var mobileLogoutBtn = document.getElementById('mobileLogoutBtn');
    if (mobileLogoutBtn) {
      mobileLogoutBtn.addEventListener('click', function(e){
        e.preventDefault();
        e.stopPropagation();
        showLogoutConfirm();
      });
    }
    
    // no token guard
    if (!(window.AuthService && window.AuthService.isLoggedIn && window.AuthService.isLoggedIn())) {
      window.location.href = '/auth';
    }
  } catch (e) {}
});

function showError(message) {
  if (window.showError) {
    window.showError(message);
  } else {
    alert("錯誤：" + message);
  }
}

function showSuccess(message) {
  if (window.showSuccess) {
    window.showSuccess(message);
  } else {
    alert("成功：" + message);
  }
}

function setButtonLoading(button, isLoading, originalText) {
  if (window.setButtonLoading) {
    window.setButtonLoading(button, isLoading);
    if (!isLoading && originalText) {
      button.textContent = originalText;
    }
  } else {
    button.disabled = isLoading;
    button.textContent = isLoading ? '處理中...' : originalText;
  }
}
