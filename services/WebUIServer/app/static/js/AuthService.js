export class AuthService {
  static saveToken(token) {
    localStorage.setItem("jwt", token);
  }

  static getToken() {
    return localStorage.getItem("jwt");
  }

  static delToken() {
    localStorage.removeItem("jwt");
  }

  static isLoggedIn() {
    // 只檢查token是否存在，不進行任何驗證
    // 所有驗證都由後端處理
    return !!this.getToken();
  }

  static getUserId() {
    // 前端不解析JWT，通過API獲取用戶資訊
    const v = localStorage.getItem('user_id');
    return v != null ? Number(v) : null;
  }

  static getUsername() {
    // 前端不解析JWT，通過API獲取用戶資訊
    return null;
  }
}

// 將 AuthService 暴露到全域範圍
window.AuthService = AuthService;

