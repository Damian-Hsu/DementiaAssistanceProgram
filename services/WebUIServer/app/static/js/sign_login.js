async function __redirectAfterAuthSuccess(){ 
  try{ 
    // 根據用戶角色導向不同頁面
    const response = await ApiClient.getCurrentUser();
    const currentUser = response?.user || response;
    const isAdmin = currentUser?.role === 'admin';
    
    if (isAdmin) {
      window.location.href = '/admin/tasks';
    } else {
      window.location.href = '/home';
    }
  } catch(e) {
    console.error('獲取用戶資訊失敗，預設導向 /home:', e);
    window.location.href = '/home';
  }
}
import { ApiClient } from "./APIClient.js";
import { AuthService } from "./AuthService.js";
import settings from "./settings.js";

if (settings.debug) {
  console.log("BFF_ROOT:", settings.BFF_ROOT);
}

// DOM 元素
const signupform = document.getElementById("signupform");
const loginform = document.getElementById("loginform");
const loginError = document.getElementById("loginError");
const signupError = document.getElementById("signupError");

// 驗證函數
function validateAccount(account) {
  if (!account || typeof account !== 'string') {
    return { valid: false, message: '帳號不能為空' };
  }
  
  const trimmed = account.trim();
  if (trimmed !== account) {
    return { valid: false, message: '帳號前後不可有空格' };
  }
  
  if (trimmed.length < 6) {
    return { valid: false, message: '帳號至少需要6個字元' };
  }
  
  if (trimmed.length > 30) {
    return { valid: false, message: '帳號最多30個字元' };
  }
  
  // 只允許英文字母、數字、.、_
  const accountRegex = /^[a-zA-Z0-9._]+$/;
  if (!accountRegex.test(trimmed)) {
    return { valid: false, message: '帳號只能包含英文字母、數字、.、_，不可有空格' };
  }
  
  return { valid: true };
}

function validatePassword(password) {
  if (!password || typeof password !== 'string') {
    return { valid: false, message: '密碼不能為空' };
  }
  
  if (password.length < 8) {
    return { valid: false, message: '密碼至少需要8個字元' };
  }
  
  if (password.length > 30) {
    return { valid: false, message: '密碼最多30個字元' };
  }
  
  // 只允許英文字母、數字、.、_
  const passwordRegex = /^[a-zA-Z0-9._]+$/;
  if (!passwordRegex.test(password)) {
    return { valid: false, message: '密碼只能包含英文字母、數字、.、_' };
  }
  
  return { valid: true };
}

function showError(element, message) {
  if (element) {
    element.textContent = message || '';
    element.style.display = message ? 'block' : 'none';
  }
}

function hideError(element) {
  if (element) {
    element.textContent = '';
    element.style.display = 'none';
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

// 輸入驗證：即時檢查帳號和密碼格式
function setupInputValidation() {
  // 登入頁面的帳號驗證
  const loginAccount = document.getElementById("login_account");
  if (loginAccount) {
    loginAccount.addEventListener('input', (e) => {
      const value = e.target.value;
      if (value && value.includes(' ')) {
        e.target.value = value.replace(/\s/g, '');
      }
    });
    
    loginAccount.addEventListener('blur', (e) => {
      const value = e.target.value.trim();
      if (value) {
        const validation = validateAccount(value);
        if (!validation.valid) {
          e.target.classList.add('error');
        } else {
          e.target.classList.remove('error');
        }
      }
    });
  }

  // 登入頁面的密碼驗證
  const loginPassword = document.getElementById("login_password");
  if (loginPassword) {
    loginPassword.addEventListener('input', (e) => {
      const value = e.target.value;
      if (value && value.includes(' ')) {
        e.target.value = value.replace(/\s/g, '');
      }
    });
  }

  // 註冊頁面的帳號驗證
  const signAccount = document.getElementById("sign_account");
  if (signAccount) {
    signAccount.addEventListener('input', (e) => {
      const value = e.target.value;
      if (value && value.includes(' ')) {
        e.target.value = value.replace(/\s/g, '');
      }
    });
    
    signAccount.addEventListener('blur', (e) => {
      const value = e.target.value.trim();
      if (value) {
        const validation = validateAccount(value);
        if (!validation.valid) {
          e.target.classList.add('error');
        } else {
          e.target.classList.remove('error');
        }
      }
    });
  }

  // 註冊頁面的密碼驗證
  const signPassword = document.getElementById("sign_password");
  if (signPassword) {
    signPassword.addEventListener('input', (e) => {
      const value = e.target.value;
      if (value && value.includes(' ')) {
        e.target.value = value.replace(/\s/g, '');
      }
    });
  }

  const signPasswordConfirm = document.getElementById("sign_password_confirm");
  if (signPasswordConfirm) {
    signPasswordConfirm.addEventListener('input', (e) => {
      const value = e.target.value;
      if (value && value.includes(' ')) {
        e.target.value = value.replace(/\s/g, '');
      }
    });
  }
}

// 註冊表單處理
signupform.addEventListener("submit", async (e) => {
  e.preventDefault();
  
  hideError(signupError);
  
  const submitButton = e.target.querySelector('button[type="submit"]');
  const originalText = submitButton.textContent;
  
  try {
    setButtonLoading(submitButton, true, originalText);

    // 收集表單數據
    const account = document.getElementById("sign_account").value.trim();
    const password = document.getElementById("sign_password").value;
    const passwordConfirm = document.getElementById("sign_password_confirm").value;
    const name = document.getElementById("sign_name").value.trim();
    const gender = document.getElementById("sign_gender").value;
    const birthday = document.getElementById("sign_birthday").value;
    const phone = document.getElementById("sign_phone").value.trim();
    const email = document.getElementById("sign_email").value.trim();

    // 驗證帳號
    const accountValidation = validateAccount(account);
    if (!accountValidation.valid) {
      showError(signupError, accountValidation.message);
      document.getElementById("sign_account").classList.add('error');
      return;
    }
    document.getElementById("sign_account").classList.remove('error');

    // 驗證密碼
    const passwordValidation = validatePassword(password);
    if (!passwordValidation.valid) {
      showError(signupError, passwordValidation.message);
      document.getElementById("sign_password").classList.add('error');
      return;
    }
    document.getElementById("sign_password").classList.remove('error');

    // 驗證兩次密碼是否一致
    if (password !== passwordConfirm) {
      showError(signupError, "兩次輸入的密碼不一致，請重新確認！");
      document.getElementById("sign_password_confirm").classList.add('error');
      return;
    }
    document.getElementById("sign_password_confirm").classList.remove('error');

    // 驗證必填欄位
    if (!name || !gender || !birthday || !phone || !email) {
      showError(signupError, "請填寫所有必填欄位");
      return;
    }

    // 驗證電子郵件格式
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      showError(signupError, "請輸入有效的電子郵件地址");
      return;
    }

    // 驗證手機格式
    const phoneRegex = /^09\d{8}$/;
    if (!phoneRegex.test(phone)) {
      showError(signupError, "請輸入正確的手機號碼（09 開頭，共 10 碼）");
      return;
    }

    const signupData = {
      account,
      name,
      gender,
      birthday,
      phone,
      email,
      password
    };

    const result = await ApiClient.signup(signupData);
    console.log("註冊結果:", result);
    
    // 檢查註冊是否返回了token（自動登入）
    if (result.access_token) {
      AuthService.saveToken(result.access_token);
      __redirectAfterAuthSuccess();
      
      signupform.reset();
      
      if (window.checkLoginStatus) {
        setTimeout(() => {
          window.checkLoginStatus();
        }, 1000);
      }
    } else {
      signupform.reset();
      
      if (window.showSection) {
        setTimeout(() => window.showSection('login'), 1500);
      }
    }
    
  } catch (err) {
    console.error("註冊錯誤:", err);
    showError(signupError, err.message || "註冊失敗，請稍後再試");
  } finally {
    setButtonLoading(submitButton, false, originalText);
  }
});

// 登入表單處理
loginform.addEventListener("submit", async (e) => {
  e.preventDefault();
  
  hideError(loginError);
  
  const submitButton = e.target.querySelector('button[type="submit"]');
  const originalText = submitButton.textContent;

  try {
    setButtonLoading(submitButton, true, originalText);

    const username = document.getElementById("login_account").value.trim();
    const password = document.getElementById("login_password").value;

    // 驗證帳號
    const accountValidation = validateAccount(username);
    if (!accountValidation.valid) {
      showError(loginError, accountValidation.message);
      document.getElementById("login_account").classList.add('error');
      return;
    }
    document.getElementById("login_account").classList.remove('error');

    // 驗證密碼
    const passwordValidation = validatePassword(password);
    if (!passwordValidation.valid) {
      showError(loginError, passwordValidation.message);
      document.getElementById("login_password").classList.add('error');
      return;
    }
    document.getElementById("login_password").classList.remove('error');

    // 符合 Body_login_auth_login_post 格式
    const result = await ApiClient.login({ username, password });
    
    // 根據 LoginResponseDTO，token 字段是 access_token
    if (result.access_token) {
      AuthService.saveToken(result.access_token);
      __redirectAfterAuthSuccess();
      console.log("登入結果:", result);
      
      loginform.reset();
      
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
    showError(loginError, err.message || "登入失敗，請檢查您的帳號密碼");
  } finally {
    setButtonLoading(submitButton, false, originalText);
  }
});


document.addEventListener("DOMContentLoaded", async function () {
    // 設置輸入驗證
    setupInputValidation();
    
    // 如果已經有 JWT，根據角色導向不同頁面
    if (window.AuthService && window.AuthService.isLoggedIn && window.AuthService.isLoggedIn()) {
      try {
        const response = await ApiClient.getCurrentUser();
        const currentUser = response?.user || response;
        const isAdmin = currentUser?.role === 'admin';
        
        if (isAdmin) {
          window.location.href = "/admin/tasks";
        } else {
          window.location.href = "/home";
        }
      } catch (e) {
        console.error('獲取用戶資訊失敗，預設導向 /home:', e);
        window.location.href = "/home";
      }
    }
  });
  // 控制區塊顯示
    function showSection(name) {
      document.getElementById("loginSection").classList.remove("active");
      document.getElementById("signupSection").classList.remove("active");
      document.getElementById("logoutSection").classList.remove("active");

      if (name === "login") {
        document.getElementById("loginSection").classList.add("active");
        hideError(loginError);
      }
      if (name === "signup") {
        document.getElementById("signupSection").classList.add("active");
        hideError(signupError);
      }
      if (name === "logout") document.getElementById("logoutSection").classList.add("active");
    }

    // 提供給 sign_login_logout.js 呼叫
    window.showSection = showSection;
    window.showError = (msg) => {
      // 不再使用 alert，改為顯示在對應的錯誤區域
      if (document.getElementById("loginSection").classList.contains("active")) {
        showError(loginError, msg);
      } else if (document.getElementById("signupSection").classList.contains("active")) {
        showError(signupError, msg);
      }
    };
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
