function __redirectAfterAuthSuccess(){ try{ window.location.href = '/home'; }catch(e){} }
import { ApiClient } from "./APIClient.js";
import { AuthService } from "./AuthService.js";
import settings from "./settings.js";

if (settings.debug) {
  console.log("BFF_ROOT:", settings.BFF_ROOT);
}

// DOM 元素
const signupform = document.getElementById("signupform");
const loginform = document.getElementById("loginform");


// 工具函數
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

// 註冊表單處理
signupform.addEventListener("submit", async (e) => {
  e.preventDefault();
  
  const submitButton = e.target.querySelector('button[type="submit"]');
  const originalText = submitButton.textContent;
  
  try {
    setButtonLoading(submitButton, true, originalText);

    // 收集表單數據，符合 SignupRequestDTO 格式
    const signupData = {
      account: document.getElementById("sign_account").value.trim(),
      name: document.getElementById("sign_name").value.trim(),
      gender: document.getElementById("sign_gender").value,
      birthday: document.getElementById("sign_birthday").value,
      phone: document.getElementById("sign_phone").value.trim(),
      email: document.getElementById("sign_email").value.trim(),
      password: document.getElementById("sign_password").value
    };
    // 驗證兩次密碼是否一致
    const pw = document.getElementById("sign_password").value;
    const pw2 = document.getElementById("sign_password_confirm").value;

        if (pw !== pw2) {
        e.preventDefault(); // 阻止送出
        window.showError("兩次輸入的密碼不一致，請重新確認！");
        return false;
        }
    // 驗證必填欄位
    if (!signupData.account || !signupData.name || !signupData.gender || 
        !signupData.birthday || !signupData.phone || !signupData.email || !signupData.password) {
      throw new Error("請填寫所有必填欄位");
    }

    // 驗證電子郵件格式
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(signupData.email)) {
      throw new Error("請輸入有效的電子郵件地址");
    }
    //驗證手機格式
    const phoneRegex = /^09\d{8}$/;
    if (!phoneRegex.test(signupData.phone)) {
      throw new Error("請輸入正確的手機號碼（09 開頭，共 10 碼）");
    }
    // 驗證密碼長度
    if (signupData.password.length < 6) {
      throw new Error("密碼至少需要6個字符");
    }

    const result = await ApiClient.signup(signupData);
    console.log("註冊結果:", result);
    
    // 檢查註冊是否返回了token（自動登入）
    if (result.access_token) {
      AuthService.saveToken(result.access_token); __redirectAfterAuthSuccess();
      
      // 移除註冊成功的 alert 警告視窗，自動登入後會跳轉
      // showSuccess("註冊成功！已自動登入。");
      
      // 清空表單
      signupform.reset();
      
      // 重新檢查登入狀態並更新UI（只檢查localStorage中是否有JWT）
      if (window.checkLoginStatus) {
        setTimeout(() => {
          window.checkLoginStatus();
        }, 1000);
      }
    } else {
      // 移除註冊成功的 alert 警告視窗
      // showSuccess("註冊成功！請使用您的帳號密碼登入。");
      
      // 清空表單
      signupform.reset();
      
      // 切換到登入頁面
      if (window.showSection) {
        setTimeout(() => window.showSection('login'), 1500);
      }
    }
    
  } catch (err) {
    console.error("註冊錯誤:", err);
    showError(err.message || "註冊失敗，請稍後再試");
  } finally {
    setButtonLoading(submitButton, false, originalText);
  }
});

// 登入表單處理
loginform.addEventListener("submit", async (e) => {
  e.preventDefault();
  
  const submitButton = e.target.querySelector('button[type="submit"]');
  const originalText = submitButton.textContent;

  try {
    setButtonLoading(submitButton, true, originalText);

    const username = document.getElementById("login_account").value.trim();
    const password = document.getElementById("login_password").value;

    // 驗證輸入
    if (!username || !password) {
      throw new Error("請輸入帳號和密碼");
    }

    // 符合 Body_login_auth_login_post 格式
    const result = await ApiClient.login({ username, password });
    
    // 根據 LoginResponseDTO，token 字段是 access_token
    if (result.access_token) {
      AuthService.saveToken(result.access_token); __redirectAfterAuthSuccess();
      console.log("登入結果:", result);
      
      // 移除登入成功的 alert 警告視窗，登入成功後會自動跳轉
      // showSuccess("登入成功！");
      
      // 清空表單
      loginform.reset();
      
      // 重新檢查登入狀態並更新UI（只檢查localStorage中是否有JWT）
      if (window.checkLoginStatus) {
        setTimeout(() => {
          window.checkLoginStatus();
        }, 1000);
      }
    } else {
      throw new Error("登入響應格式錯誤");
    }
    
  } catch (err) {
    console.error("登入錯誤:", err);
    showError(err.message || "登入失敗，請檢查您的帳號密碼");
  } finally {
    setButtonLoading(submitButton, false, originalText);
  }
});


document.addEventListener("DOMContentLoaded", function () {
    // 如果已經有 JWT，就直接跳到 home.html
    if (window.AuthService && window.AuthService.isLoggedIn && window.AuthService.isLoggedIn()) {
      window.location.href = "/home.html";
    }
  });
  // 控制區塊顯示
    function showSection(name) {
      document.getElementById("loginSection").classList.remove("active");
      document.getElementById("signupSection").classList.remove("active");
      document.getElementById("logoutSection").classList.remove("active");

      if (name === "login") document.getElementById("loginSection").classList.add("active");
      if (name === "signup") document.getElementById("signupSection").classList.add("active");
      if (name === "logout") document.getElementById("logoutSection").classList.add("active");
    }

    // 提供給 sign_login_logout.js 呼叫
    window.showSection = showSection;
    window.showError = (msg) => alert("❌ " + msg);
    window.showSuccess = (msg) => alert("✅ " + msg);
    window.setButtonLoading = (btn, isLoading, originalText) => {
      btn.disabled = isLoading;
      btn.textContent = isLoading ? "處理中…" : originalText;
    };
    window.checkLoginStatus = () => {
      // sign_login_logout.js 會呼叫這個來切換 UI
      // 這裡留白或簡單測試用
    };

function onLoginSuccess(){ __redirectAfterAuthSuccess(); }
