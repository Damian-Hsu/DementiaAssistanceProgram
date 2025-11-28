import settings from "./settings.js";

const BFF_ROOT = settings.BFF_ROOT;
console.log("BFF_ROOT:", BFF_ROOT);
console.log("ApiClient loaded");

// 統一的API錯誤處理函數
async function handleApiError(res) {
  // 若權杖失效或未授權，統一清除並導回登入頁
  if (res.status === 401 || res.status === 403) {
    try { localStorage.removeItem('jwt'); } catch (e) {}
    // 立即導回登入頁；也可帶上 returnUrl
    window.location.href = '/auth.html';
    // 仍丟出錯誤讓呼叫端停止後續流程
    throw new Error('未授權或登入逾期，請重新登入');
  }
  let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
  try {
    const errorData = await res.json();
    if (errorData.detail) {
      if (Array.isArray(errorData.detail)) {
        errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
      } else {
        errorMessage = errorData.detail;
      }
    }
  } catch (e) {
    // 如果無法解析為 JSON，使用預設錯誤訊息
  }
  
  // 前端不處理JWT驗證，只拋出錯誤讓調用方處理
  throw new Error(errorMessage);
}
// 本地（Flask）控制伺服器端推流
async function startServerPush({ camera_id, source_rtsp, publish_rtsp_url, video_codec = "copy", audio = true }) {
  const r = await fetch(`/local/stream/push`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ camera_id, source_rtsp, publish_rtsp_url, video_codec, audio })
  });
  if (!r.ok) throw new Error(`startServerPush 失敗：HTTP ${r.status}`);
  return r.json();
}

async function stopServerPush(camera_id) {
  const r = await fetch(`/local/stream/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ camera_id })
  });
  if (!r.ok) throw new Error(`stopServerPush 失敗：HTTP ${r.status}`);
  return r.json();
}
export const ApiClient = {
  // 註冊 - 使用 JSON 格式，符合 SignupRequestDTO
  signup: async (userData) => {
    try {
      // 確保所有必需字段都存在
      const signupData = {
        account: userData.account,
        name: userData.name,
        gender: userData.gender,
        birthday: userData.birthday,
        phone: userData.phone,
        email: userData.email,
        password: userData.password,
        ...(userData.headshot_url && { headshot_url: userData.headshot_url })
      };

      const res = await fetch(`${BFF_ROOT}/auth/signup`, {
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          // 添加一些常見的CORS標頭
          "Accept": "application/json",
        },
        body: JSON.stringify(signupData),
      });
      
      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errorData = await res.json();
          if (errorData.detail) {
            if (Array.isArray(errorData.detail)) {
              errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
            } else {
              errorMessage = errorData.detail;
            }
          }
        } catch (e) {
          // 如果無法解析為 JSON，使用預設錯誤訊息
        }
        throw new Error(errorMessage);
      }
      
      return await res.json();
    } catch (error) {
      console.error("Signup error:", error);
      
      // 處理不同類型的錯誤
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        if (error.message.includes('Failed to fetch')) {
          throw new Error('網路連接失敗：請檢查後端服務是否運行，或是否存在CORS跨域問題。請聯繫系統管理員。');
        }
      }
      
      throw error;
    }
  },

  // 登入 - 使用 form-urlencoded 格式，符合 Body_login_auth_login_post
  login: async (userData) => {
    try {
      const formData = new URLSearchParams();
      formData.append('username', userData.username);
      formData.append('password', userData.password);
      formData.append('grant_type', 'password'); // API 要求的格式
      formData.append('scope', ''); // 預設空字串
      
      const res = await fetch(`${BFF_ROOT}/auth/login`, {
        method: "POST",
        headers: { 
          "Content-Type": "application/x-www-form-urlencoded",
          "Accept": "application/json",
        },
        body: formData,
      });
      
      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errorData = await res.json();
          if (errorData.detail) {
            if (Array.isArray(errorData.detail)) {
              errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
            } else if (typeof errorData.detail === 'string') {
              errorMessage = errorData.detail;
            }
          }
        } catch (e) {
          // 如果無法解析為 JSON，使用預設錯誤訊息
        }
        throw new Error(errorMessage);
      }
      
      return await res.json();
    } catch (error) {
      console.error("Login error:", error);
      
      // 處理不同類型的錯誤
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        if (error.message.includes('Failed to fetch')) {
          throw new Error('網路連接失敗：請檢查後端服務是否運行，或是否存在CORS跨域問題。請聯繫系統管理員。');
        }
      }
      
      throw error;
    }
  },

  // 新增相機
  createCamera: async (cameraData) => {
    try {
      const token = localStorage.getItem('jwt');
      if (!token) {
        throw new Error('請先登入');
      }

      const res = await fetch(`${BFF_ROOT}/camera/`, {
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          "Accept": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify(cameraData),
      });
      
      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errorData = await res.json();
          if (errorData.detail) {
            if (Array.isArray(errorData.detail)) {
              errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
            } else {
              errorMessage = errorData.detail;
            }
          }
        } catch (e) {
          // 如果無法解析為 JSON，使用預設錯誤訊息
        }
        throw new Error(errorMessage);
      }
      
      return await res.json();
    } catch (error) {
      console.error("Create camera error:", error);
      
      // 處理不同類型的錯誤
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        if (error.message.includes('Failed to fetch')) {
          throw new Error('網路連接失敗：請檢查後端服務是否運行，或是否存在CORS跨域問題。請聯繫系統管理員。');
        }
      }
      
      throw error;
    }
  },

  // 取得相機列表
  getCameras: async (userId, status = null, q = null, page = 1, size = 20) => {
    try {
      const token = localStorage.getItem('jwt');
      if (!token) {
        throw new Error('請先登入');
      }

      const params = new URLSearchParams({
        user_id: userId,
        page: page,
        size: size
      });
      
      if (status) params.append('status', status);
      if (q) params.append('q', q);

      const res = await fetch(`${BFF_ROOT}/camera/?${params}`, {
        method: "GET",
        headers: { 
          "Accept": "application/json",
          "Authorization": `Bearer ${token}`
        }
      });
      
      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errorData = await res.json();
          if (errorData.detail) {
            if (Array.isArray(errorData.detail)) {
              errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
            } else {
              errorMessage = errorData.detail;
            }
          }
        } catch (e) {
          // 如果無法解析為 JSON，使用預設錯誤訊息
        }
        throw new Error(errorMessage);
      }
      
      return await res.json();
    } catch (error) {
      console.error("Get cameras error:", error);
      
      // 處理不同類型的錯誤
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        if (error.message.includes('Failed to fetch')) {
          throw new Error('網路連接失敗：請檢查後端服務是否運行，或是否存在CORS跨域問題。請聯繫系統管理員。');
        }
      }
      
      throw error;
    }
  },

  // 取得單一相機資訊
  getCamera: async (cameraId) => {
    try {
      const token = localStorage.getItem('jwt');
      if (!token) {
        throw new Error('請先登入');
      }

      const res = await fetch(`${BFF_ROOT}/camera/${cameraId}`, {
        method: "GET",
        headers: { 
          "Accept": "application/json",
          "Authorization": `Bearer ${token}`
        }
      });
      
      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errorData = await res.json();
          if (errorData.detail) {
            if (Array.isArray(errorData.detail)) {
              errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
            } else {
              errorMessage = errorData.detail;
            }
          }
        } catch (e) {
          // 如果無法解析為 JSON，使用預設錯誤訊息
        }
        throw new Error(errorMessage);
      }
      
      return await res.json();
    } catch (error) {
      console.error("Get camera error:", error);
      
      // 處理不同類型的錯誤
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        if (error.message.includes('Failed to fetch')) {
          throw new Error('網路連接失敗：請檢查後端服務是否運行，或是否存在CORS跨域問題。請聯繫系統管理員。');
        }
      }
      
      throw error;
    }
  },

  // 更新相機
  updateCamera: async (cameraId, updateData) => {
    try {
      const token = localStorage.getItem('jwt');
      if (!token) {
        throw new Error('請先登入');
      }

      const res = await fetch(`${BFF_ROOT}/camera/${cameraId}`, {
        method: "PATCH",
        headers: { 
          "Content-Type": "application/json",
          "Accept": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify(updateData),
      });
      
      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errorData = await res.json();
          if (errorData.detail) {
            if (Array.isArray(errorData.detail)) {
              errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
            } else {
              errorMessage = errorData.detail;
            }
          }
        } catch (e) {
          // 如果無法解析為 JSON，使用預設錯誤訊息
        }
        throw new Error(errorMessage);
      }
      
      return await res.json();
    } catch (error) {
      console.error("Update camera error:", error);
      
      // 處理不同類型的錯誤
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        if (error.message.includes('Failed to fetch')) {
          throw new Error('網路連接失敗：請檢查後端服務是否運行，或是否存在CORS跨域問題。請聯繫系統管理員。');
        }
      }
      
      throw error;
    }
  },

  // 刪除相機
  deleteCamera: async (cameraId) => {
    try {
      const token = localStorage.getItem('jwt');
      if (!token) {
        throw new Error('請先登入');
      }

      const res = await fetch(`${BFF_ROOT}/camera/${cameraId}`, {
        method: "DELETE",
        headers: { 
          "Accept": "application/json",
          "Authorization": `Bearer ${token}`
        }
      });
      
      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errorData = await res.json();
          if (errorData.detail) {
            if (Array.isArray(errorData.detail)) {
              errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
            } else {
              errorMessage = errorData.detail;
            }
          }
        } catch (e) {
          // 如果無法解析為 JSON，使用預設錯誤訊息
        }
        throw new Error(errorMessage);
      }
      
      return await res.json();
    } catch (error) {
      console.error("Delete camera error:", error);
      
      // 處理不同類型的錯誤
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        if (error.message.includes('Failed to fetch')) {
          throw new Error('網路連接失敗：請檢查後端服務是否運行，或是否存在CORS跨域問題。請聯繫系統管理員。');
        }
      }
      
      throw error;
    }
  },

  // === 開始串流 ===
connectStream: async (cameraId, req = { ttl: 300 }) => {
  const token = localStorage.getItem('jwt');
  if (!token) throw new Error('請先登入');

  const res = await fetch(`${BFF_ROOT}/camera/${cameraId}/stream/connect`, {
    method: "POST",
    headers: {
      "Accept": "application/json",
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`
    },
    body: JSON.stringify(req) // 先支援最小 { ttl }，之後有需要再加欄位
  });

  if (!res.ok) {
    let msg = `HTTP ${res.status}: ${res.statusText}`;
    try { const j = await res.json(); if (j?.detail) msg = Array.isArray(j.detail) ? j.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join(', ') : j.detail; } catch {}
    const err = new Error(msg);
    err.status = res.status;
    if (res.status === 409) err.code = 'AlreadyConnected';
    throw err;
  }
  return await res.json(); // StreamConnectResp
},

// === 停止串流 ===
stopStream: async (cameraId) => {
  const token = localStorage.getItem('jwt');
  if (!token) throw new Error('請先登入');

  const res = await fetch(`${BFF_ROOT}/camera/${cameraId}/stream/stop`, {
    method: "POST",
    headers: {
      "Accept": "application/json",
      "Authorization": `Bearer ${token}`
    }
  });

  if (!res.ok) {
    let msg = `HTTP ${res.status}: ${res.statusText}`;
    try { const j = await res.json(); if (j?.detail) msg = Array.isArray(j.detail) ? j.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join(', ') : j.detail; } catch {}
    throw new Error(msg);
  }
  return await res.json();
},

  // 取得 RTSP 推流 URL
  getPublishRtspUrl: async (cameraId, ttl = 300) => {
    try {
      const token = localStorage.getItem('jwt');
      if (!token) {
        throw new Error('請先登入');
      }

      const res = await fetch(`${BFF_ROOT}/camera/${cameraId}/publish_rtsp_url?ttl=${ttl}`, {
        method: "GET",
        headers: { 
          "Accept": "application/json",
          "Authorization": `Bearer ${token}`
        }
      });
      
      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errorData = await res.json();
          if (errorData.detail) {
            if (Array.isArray(errorData.detail)) {
              errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
            } else {
              errorMessage = errorData.detail;
            }
          }
        } catch (e) {
          // 如果無法解析為 JSON，使用預設錯誤訊息
        }
        throw new Error(errorMessage);
      }
      
      return await res.json();
    } catch (error) {
      console.error("Get publish RTSP URL error:", error);
      
      // 處理不同類型的錯誤
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        if (error.message.includes('Failed to fetch')) {
          throw new Error('網路連接失敗：請檢查後端服務是否運行，或是否存在CORS跨域問題。請聯繫系統管理員。');
        }
      }
      
      throw error;
    }
  },

  // 取得 HLS 播放 URL
  getPlayHlsUrl: async (cameraId, ttl = 300) => {
    try {
      const token = localStorage.getItem('jwt');
      if (!token) {
        throw new Error('請先登入');
      }

      const res = await fetch(`${BFF_ROOT}/camera/${cameraId}/play-hls-url?ttl=${ttl}`, {
        method: "GET",
        headers: { 
          "Accept": "application/json",
          "Authorization": `Bearer ${token}`
        }
      });
      
      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errorData = await res.json();
          if (errorData.detail) {
            if (Array.isArray(errorData.detail)) {
              errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
            } else {
              errorMessage = errorData.detail;
            }
          }
        } catch (e) {
          // 如果無法解析為 JSON，使用預設錯誤訊息
        }
        throw new Error(errorMessage);
      }
      
      return await res.json();
    } catch (error) {
      console.error("Get play HLS URL error:", error);
      
      // 處理不同類型的錯誤
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        if (error.message.includes('Failed to fetch')) {
          throw new Error('網路連接失敗：請檢查後端服務是否運行，或是否存在CORS跨域問題。請聯繫系統管理員。');
        }
      }
      
      throw error;
    }
  },

  // 取得串流狀態
  getStreamStatus: async (cameraId) => {
    try {
      const token = localStorage.getItem('jwt');
      if (!token) {
        throw new Error('請先登入');
      }

      const res = await fetch(`${BFF_ROOT}/camera/${cameraId}/stream/status`, {
        method: "GET",
        headers: { 
          "Accept": "application/json",
          "Authorization": `Bearer ${token}`
        }
      });
      
      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errorData = await res.json();
          if (errorData.detail) {
            if (Array.isArray(errorData.detail)) {
              errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
            } else {
              errorMessage = errorData.detail;
            }
          }
        } catch (e) {
          // 如果無法解析為 JSON，使用預設錯誤訊息
        }
        throw new Error(errorMessage);
      }
      
      return await res.json();
    } catch (error) {
      console.error("Get stream status error:", error);
      throw error;
    }
  },

  // 取得 WebRTC 播放 URL
  getPlayWebrtcUrl: async (cameraId, ttl = 300) => {
    try {
      const token = localStorage.getItem('jwt');
      if (!token) {
        throw new Error('請先登入');
      }

      const res = await fetch(`${BFF_ROOT}/camera/${cameraId}/play-webrtc-url?ttl=${ttl}`, {
        method: "GET",
        headers: { 
          "Accept": "application/json",
          "Authorization": `Bearer ${token}`
        }
      });
      
      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errorData = await res.json();
          if (errorData.detail) {
            if (Array.isArray(errorData.detail)) {
              errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
            } else {
              errorMessage = errorData.detail;
            }
          }
        } catch (e) {
          // 如果無法解析為 JSON，使用預設錯誤訊息
        }
        throw new Error(errorMessage);
      }
      
      return await res.json();
    } catch (error) {
      console.error("Get play WebRTC URL error:", error);
      
      // 處理不同類型的錯誤
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        if (error.message.includes('Failed to fetch')) {
          throw new Error('網路連接失敗：請檢查後端服務是否運行，或是否存在CORS跨域問題。請聯繫系統管理員。');
        }
      }
      
      throw error;
    }
  },

  // 輪換Token版本
  rotateTokenVersion: async (cameraId) => {
    try {
      const token = localStorage.getItem('jwt');
      if (!token) {
        throw new Error('請先登入');
      }

      const res = await fetch(`${BFF_ROOT}/camera/${cameraId}/token/version-rotate`, {
        method: "POST",
        headers: { 
          "Accept": "application/json",
          "Authorization": `Bearer ${token}`
        }
      });
      
      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errorData = await res.json();
          if (errorData.detail) {
            if (Array.isArray(errorData.detail)) {
              errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
            } else {
              errorMessage = errorData.detail;
            }
          }
        } catch (e) {
          // 如果無法解析為 JSON，使用預設錯誤訊息
        }
        throw new Error(errorMessage);
      }
      
      return await res.json();
    } catch (error) {
      console.error("Rotate token version error:", error);
      
      // 處理不同類型的錯誤
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        if (error.message.includes('Failed to fetch')) {
          throw new Error('網路連接失敗：請檢查後端服務是否運行，或是否存在CORS跨域問題。請聯繫系統管理員。');
        }
      }
      
      throw error;
    }
  },

  // 重新整理 Token
  refreshToken: async (cameraId, audience, token) => {
    try {
      const authToken = localStorage.getItem('jwt');
      if (!authToken) {
        throw new Error('請先登入');
      }

      const res = await fetch(`${BFF_ROOT}/camera/${cameraId}/token/refresh/${audience}?token=${encodeURIComponent(token)}`, {
        method: "GET",
        headers: { 
          "Accept": "application/json",
          "Authorization": `Bearer ${authToken}`
        }
      });
      
      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errorData = await res.json();
          if (errorData.detail) {
            if (Array.isArray(errorData.detail)) {
              errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
            } else {
              errorMessage = errorData.detail;
            }
          }
        } catch (e) {
          // 如果無法解析為 JSON，使用預設錯誤訊息
        }
        throw new Error(errorMessage);
      }
      
      return await res.json();
    } catch (error) {
      console.error("Refresh token error:", error);
      
      // 處理不同類型的錯誤
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        if (error.message.includes('Failed to fetch')) {
          throw new Error('網路連接失敗：請檢查後端服務是否運行，或是否存在CORS跨域問題。請聯繫系統管理員。');
        }
      }
      
      throw error;
    }
  },

  // 取得當前用戶資訊
  getCurrentUser: async () => {
    try {
      const token = localStorage.getItem('jwt');
      if (!token) {
        throw new Error('請先登入');
      }

      const res = await fetch(`${BFF_ROOT}/users/me`, {
        method: "GET",
        headers: { 
          "Accept": "application/json",
          "Authorization": `Bearer ${token}`
        }
      });
      
      if (!res.ok) {
        await handleApiError(res);
      }
      
      return await res.json();
    } catch (error) {
      console.error("Get current user error:", error);
      
      // 處理不同類型的錯誤
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        if (error.message.includes('Failed to fetch')) {
          throw new Error('網路連接失敗：請檢查後端服務是否運行，或是否存在CORS跨域問題。請聯繫系統管理員。');
        }
      }
      
      throw error;
    }
  },

  // 更新用戶資料
  updateUserProfile: async (updateData) => {
  const token = localStorage.getItem('jwt');
  if (!token) throw new Error('請先登入');
  const res = await fetch(`${BFF_ROOT}/users/me`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json",
      "Authorization": `Bearer ${token}`
    },
    body: JSON.stringify(updateData)
  });
  if (!res.ok) await handleApiError(res);
  // 你的 Flask 實作回傳 { ok: true }，因此這裡不回使用者物件
  return await res.json();
},

  // 修改密碼
  changePassword: async ({ old_password, new_password }) => {
  const token = localStorage.getItem('jwt');
  if (!token) throw new Error('請先登入');
  const res = await fetch(`${BFF_ROOT}/users/me/password`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json",
      "Authorization": `Bearer ${token}`
    },
    body: JSON.stringify({ old_password, new_password })
  });
  if (!res.ok) await handleApiError(res);
  return await res.json();
},

  // 重新申請JWT Token
  refreshUserToken: async () => {
    try {
      const token = localStorage.getItem('jwt');
      if (!token) {
        throw new Error('請先登入');
      }

      const res = await fetch(`${BFF_ROOT}/users/token/refresh`, {
        method: "GET",
        headers: { 
          "Accept": "application/json",
          "Authorization": `Bearer ${token}`
        }
      });
      
      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errorData = await res.json();
          if (errorData.detail) {
            if (Array.isArray(errorData.detail)) {
              errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
            } else {
              errorMessage = errorData.detail;
            }
          }
        } catch (e) {
          // 如果無法解析為 JSON，使用預設錯誤訊息
        }
        throw new Error(errorMessage);
      }
      
      return await res.json();
    } catch (error) {
      console.error("Refresh user token error:", error);
      
      // 處理不同類型的錯誤
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        if (error.message.includes('Failed to fetch')) {
          throw new Error('網路連接失敗：請檢查後端服務是否運行，或是否存在CORS跨域問題。請聯繫系統管理員。');
        }
      }
      
      throw error;
    }
  }

  ,
  // 依ID取得使用者資料 GET /users/{id}
  getUserById: async (userId) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');
    const res = await fetch(`${BFF_ROOT}/users/${userId}`, {
      method: "GET",
      headers: { "Accept": "application/json", "Authorization": `Bearer ${token}` }
    });
    if (!res.ok) { await handleApiError(res); }
    return await res.json();
  },

  // 依ID更新使用者資料 PATCH /users/{id}
  updateUserById: async (userId, updateData) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');
    const res = await fetch(`${BFF_ROOT}/users/${userId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "Accept": "application/json", "Authorization": `Bearer ${token}` },
      body: JSON.stringify(updateData)
    });
    if (!res.ok) { await handleApiError(res); }
    return await res.json();
  },

// 設定相機狀態：PATCH /camera/{id}/status  Body: { status: "active" | "inactive" | "deleted" }
  setCameraStatus: async (cameraId, status) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');

    const res = await fetch(`${BFF_ROOT}/camera/${cameraId}/status`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": `Bearer ${token}`
      },
      body: JSON.stringify({ status })
    });
    if (!res.ok) { await handleApiError(res); }
    return await res.json();
  },
  listEvents: async (params = {}) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');

    const usp = new URLSearchParams();
    const {
      recording_id = null,
      start_time = null,       // ISO local date, ex: "2025-09-28"
      end_time = null,         // ISO local date
      keywords = null,         // 查 action/scene/summary/objects
      sr = null,               // 多值：["action","scene","objects"]
      sort = null,             // 欄位：start_time|created_at|duration；可 + / - 或 :asc/:desc
      page = 1,
      size = 20
    } = params;

    if (recording_id) usp.set('recording_id', recording_id);
    if (start_time)   usp.set('start_time', start_time);
    if (end_time)     usp.set('end_time', end_time);
    if (keywords)     usp.set('keywords', keywords);
    if (Array.isArray(sr)) sr.forEach(v => usp.append('sr', v));
    else if (typeof sr === 'string') usp.append('sr', sr);
    if (sort)         usp.set('sort', sort);
    usp.set('page', page);
    usp.set('size', size);

    const res = await fetch(`${BFF_ROOT}/events/?${usp.toString()}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });
    if (!res.ok) {
      let msg = `HTTP ${res.status}: ${res.statusText}`;
      try { const j = await res.json(); if (j.detail) msg = Array.isArray(j.detail) ? j.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join(', ') : j.detail; } catch {}
      throw new Error(msg);
    }
    return await res.json(); // EventListResp
  },

  getEvent: async (eventId) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');

    const res = await fetch(`${BFF_ROOT}/events/${encodeURIComponent(eventId)}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });
    if (!res.ok) {
      let msg = `HTTP ${res.status}: ${res.statusText}`;
      try { const j = await res.json(); if (j.detail) msg = Array.isArray(j.detail) ? j.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join(', ') : j.detail; } catch {}
      throw new Error(msg);
    }
    return await res.json(); // EventRead
  },

  updateEvent: async (eventId, patch) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');

    // EventUpdate（部分欄位）：recording_id, action, scene, summary, objects, start_time, duration
    const res = await fetch(`${BFF_ROOT}/events/${encodeURIComponent(eventId)}`, {
      method: 'PATCH',
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify(patch)
    });
    if (!res.ok) {
      let msg = `HTTP ${res.status}: ${res.statusText}`;
      try { const j = await res.json(); if (j.detail) msg = Array.isArray(j.detail) ? j.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join(', ') : j.detail; } catch {}
      throw new Error(msg);
    }
    return await res.json(); // OkResp
  },
  // 刪除事件
  deleteEvent: async (eventId) => {
    try {
      const token = localStorage.getItem('jwt');
      if (!token) {
        throw new Error('請先登入');
      }

      const res = await fetch(`${BFF_ROOT}/events/${eventId}`, {
        method: "DELETE",
        headers: { 
          "Accept": "application/json",
          "Authorization": `Bearer ${token}`
        }
      });

      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errorData = await res.json();
          if (errorData.detail) {
            if (Array.isArray(errorData.detail)) {
              errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
            } else {
              errorMessage = errorData.detail;
            }
          }
        } catch (e) {
          // 無法解析為 JSON 時，沿用預設錯誤訊息
        }
        throw new Error(errorMessage);
      }

      return await res.json(); // OkResp
    } catch (error) {
      console.error("Delete event error:", error);
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        if (error.message.includes('Failed to fetch')) {
          throw new Error('網路連接失敗：請檢查後端服務是否運行，或是否存在CORS跨域問題。請聯繫系統管理員。');
        }
      }
      throw error;
    }
  },
// === Recordings API ===
recordings: {
  // 取得錄影列表
  list: async ({ keywords = null, sr = null, start_time = null, end_time = null, sort = null, page = 1, size = 20 } = {}) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');

    const usp = new URLSearchParams();
    if (keywords) usp.set('keywords', keywords);
    if (Array.isArray(sr)) sr.forEach(v => usp.append('sr', v));
    else if (typeof sr === 'string') usp.append('sr', sr);
    if (start_time) usp.set('start_time', start_time);
    if (end_time) usp.set('end_time', end_time);
    if (sort) usp.set('sort', sort);
    usp.set('page', page);
    usp.set('size', size);

    const res = await fetch(`${BFF_ROOT}/recordings/?${usp.toString()}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });

    if (!res.ok) {
      let msg = `HTTP ${res.status}: ${res.statusText}`;
      try { const j = await res.json(); if (j.detail) msg = Array.isArray(j.detail) ? j.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join(', ') : j.detail; } catch {}
      throw new Error(msg);
    }
    return await res.json(); // RecordingListResp
  },

  // 取得單一錄影的播放/下載連結
  getUrl: async (recordingId, { ttl = 900, disposition = 'inline', filename = null, type = null } = {}) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');

    const usp = new URLSearchParams({ ttl, disposition });
    if (filename) usp.set('filename', filename);
    if (type) usp.set('type', type);

    const res = await fetch(`${BFF_ROOT}/recordings/${encodeURIComponent(recordingId)}?${usp.toString()}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });

    if (!res.ok) {
      let msg = `HTTP ${res.status}: ${res.statusText}`;
      try { const j = await res.json(); if (j.detail) msg = Array.isArray(j.detail) ? j.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join(', ') : j.detail; } catch {}
      throw new Error(msg);
    }
    return await res.json(); // RecordingUrlResp
  },

  // 刪除錄影
  delete: async (recordingId) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');

    const res = await fetch(`${BFF_ROOT}/recordings/${encodeURIComponent(recordingId)}`, {
      method: 'DELETE',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });

    if (!res.ok) {
      let msg = `HTTP ${res.status}: ${res.statusText}`;
      try { const j = await res.json(); if (j.detail) msg = Array.isArray(j.detail) ? j.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join(', ') : j.detail; } catch {}
      throw new Error(msg);
    }
    return await res.json(); // OkResp
  },

  // 取得指定錄影的事件
  getEvents: async (recordingId, sort = '-start_time') => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');

    const usp = new URLSearchParams({ sort });
    const res = await fetch(`${BFF_ROOT}/recordings/${encodeURIComponent(recordingId)}/events?${usp.toString()}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });

    if (!res.ok) {
      let msg = `HTTP ${res.status}: ${res.statusText}`;
      try { const j = await res.json(); if (j.detail) msg = Array.isArray(j.detail) ? j.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join(', ') : j.detail; } catch {}
      throw new Error(msg);
    }
    return await res.json(); // EventRead[]
  }
},

// === 音樂 API ===
music: {
  list: async (skip = 0, limit = 100) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');

    const params = new URLSearchParams({ skip, limit });
    const res = await fetch(`${BFF_ROOT}/music?${params.toString()}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });

    if (!res.ok) await handleApiError(res);
    return await res.json();
  },

  get: async (musicId) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');

    const res = await fetch(`${BFF_ROOT}/music/${musicId}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });

    if (!res.ok) await handleApiError(res);
    return await res.json();
  },

  getUrl: async (musicId, ttl = 3600) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');

    const params = new URLSearchParams({ ttl });
    const res = await fetch(`${BFF_ROOT}/music/${musicId}/url?${params.toString()}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });

    if (!res.ok) await handleApiError(res);
    return await res.json();
  }
},

// === Admin API ===
admin: {
  apiKeys: {
    list: async (ownerId = null) => {
      const token = localStorage.getItem('jwt');
      if (!token) throw new Error('請先登入');

      const params = new URLSearchParams();
      if (ownerId != null) params.set('owner_id', ownerId);

      const res = await fetch(`${BFF_ROOT}/admin/api-keys?${params.toString()}`, {
        method: 'GET',
        headers: {
          'Accept': 'application/json',
          'Authorization': `Bearer ${token}`
        }
      });

      if (!res.ok) await handleApiError(res);
      return await res.json();
    },

    create: async ({ name, ownerId, rateLimitPerMin = null, quotaPerDay = null, scopes = null }) => {
      const token = localStorage.getItem('jwt');
      if (!token) throw new Error('請先登入');

      const body = {
        name,
        owner_id: ownerId,
        rate_limit_per_min: rateLimitPerMin,
        quota_per_day: quotaPerDay,
        scopes
      };

      const res = await fetch(`${BFF_ROOT}/admin/api-keys`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(body)
      });

      if (!res.ok) await handleApiError(res);
      return await res.json();
    },

    update: async (keyId, patch) => {
      const token = localStorage.getItem('jwt');
      if (!token) throw new Error('請先登入');

      const res = await fetch(`${BFF_ROOT}/admin/api-keys/${keyId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(patch)
      });

      if (!res.ok) await handleApiError(res);
      return await res.json();
    },

    rotate: async (keyId) => {
      const token = localStorage.getItem('jwt');
      if (!token) throw new Error('請先登入');

      const res = await fetch(`${BFF_ROOT}/admin/api-keys/${keyId}/rotate`, {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
          'Authorization': `Bearer ${token}`
        }
      });

      if (!res.ok) await handleApiError(res);
      return await res.json();
    }
  },

  music: {
    list: async (skip = 0, limit = 100) => {
      const token = localStorage.getItem('jwt');
      if (!token) throw new Error('請先登入');

      const params = new URLSearchParams({ skip, limit });
      const res = await fetch(`${BFF_ROOT}/admin/music?${params.toString()}`, {
        method: 'GET',
        headers: {
          'Accept': 'application/json',
          'Authorization': `Bearer ${token}`
        }
      });

      if (!res.ok) await handleApiError(res);
      return await res.json();
    },

    upload: async (formData) => {
      const token = localStorage.getItem('jwt');
      if (!token) throw new Error('請先登入');

      const res = await fetch(`${BFF_ROOT}/admin/music`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`
        },
        body: formData
      });

      if (!res.ok) await handleApiError(res);
      return await res.json();
    },

    delete: async (musicId) => {
      const token = localStorage.getItem('jwt');
      if (!token) throw new Error('請先登入');

      const res = await fetch(`${BFF_ROOT}/admin/music/${musicId}`, {
        method: 'DELETE',
        headers: {
          'Accept': 'application/json',
          'Authorization': `Bearer ${token}`
        }
      });

      if (!res.ok) await handleApiError(res);
      return await res.json();
    }
  }
},

// === Chat API ===
chat: {
  // 發送聊天訊息
  send: async ({ message, date_from = null, date_to = null, history = [] }) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');

    const body = {
      message,
      ...(history.length > 0 && { history }),
      ...(date_from && { date_from }),
      ...(date_to && { date_to })
    };

    const res = await fetch(`${BFF_ROOT}/chat/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify(body)
    });

    if (!res.ok) {
      let msg = `HTTP ${res.status}: ${res.statusText}`;
      try {
        const j = await res.json();
        if (j.detail) {
          msg = Array.isArray(j.detail) 
            ? j.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join(', ')
            : j.detail;
        }
      } catch {}
      throw new Error(msg);
    }

    return await res.json(); // ChatResponse
  },

  // 獲取日記摘要
  getDiary: async (diaryDate) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');

    const res = await fetch(`${BFF_ROOT}/chat/diary/${diaryDate}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });

    if (!res.ok) {
      let msg = `HTTP ${res.status}: ${res.statusText}`;
      try {
        const j = await res.json();
        if (j.detail) {
          msg = Array.isArray(j.detail) 
            ? j.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join(', ')
            : j.detail;
        }
      } catch {}
      throw new Error(msg);
    }

    return await res.json(); // DiarySummaryResponse
  },

  // 生成或刷新日記摘要
  generateDiarySummary: async (diaryDate, forceRefresh = false) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');

    const res = await fetch(`${BFF_ROOT}/chat/diary/summary`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        diary_date: diaryDate,
        force_refresh: forceRefresh
      })
    });

    if (!res.ok) {
      let msg = `HTTP ${res.status}: ${res.statusText}`;
      try {
        const j = await res.json();
        if (j.detail) {
          msg = Array.isArray(j.detail) 
            ? j.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join(', ')
            : j.detail;
        }
      } catch {}
      throw new Error(msg);
    }

    return await res.json(); // DiarySummaryResponse
  }
},

  // 使用者設定 API
settings: {
  // 獲取使用者設定
  get: async () => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');
    
    const res = await fetch(`${BFF_ROOT}/users/settings`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });
    
    if (!res.ok) await handleApiError(res);
    return await res.json();
  },

  // 更新使用者設定
  update: async (updateData) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');
    
    const res = await fetch(`${BFF_ROOT}/users/settings`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify(updateData)
    });
    
    if (!res.ok) await handleApiError(res);
    return await res.json();
  },

  // 獲取可用時區列表
  getTimezones: async () => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');
    
    const res = await fetch(`${BFF_ROOT}/users/settings/timezones`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });
    
    if (!res.ok) await handleApiError(res);
    return await res.json();
  }
},

// === Vlog API ===
vlogs: {
  // 取得指定日期的 Vlog（若不存在返回 null）
  getDaily: async (date) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');

    // 確保日期格式正確 (YYYY-MM-DD)
    const dateStr = typeof date === 'string' ? date : date.toISOString().split('T')[0];
    console.log(`[APIClient] getDaily: date=${dateStr} (original: ${date}, type: ${typeof date})`);

    const res = await fetch(`${BFF_ROOT}/vlogs/date/${dateStr}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });

    if (res.status === 404) {
      console.log(`[APIClient] getDaily: 404 - 該日期(${dateStr})尚未生成 Vlog`);
      return null;
    }
    if (!res.ok) {
      console.error(`[APIClient] getDaily: 錯誤 ${res.status} - ${res.statusText}`);
      await handleApiError(res);
    }
    const data = await res.json();
    console.log(`[APIClient] getDaily: 成功獲取 Vlog - id=${data.id}, target_date=${data.target_date}, status=${data.status}`);
    return data;
  },

  // 獲取指定日期的事件列表
  getDateEvents: async (date) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');
    
    const res = await fetch(`${BFF_ROOT}/vlogs/events/${date}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });
    
    if (!res.ok) await handleApiError(res);
    return await res.json();
  },

  // AI 自動選擇事件片段
  aiSelectEvents: async (date, summaryText = null, limit = 20) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');
    
    const body = { date, limit };
    if (summaryText) body.summary_text = summaryText;
    
    const res = await fetch(`${BFF_ROOT}/vlogs/ai-select`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify(body)
    });
    
    if (!res.ok) await handleApiError(res);
    return await res.json();
  },

  // 創建 Vlog
  create: async ({
    targetDate,
    eventIds,
    title = null,
    maxDuration = 180,
    resolution = '720p',
    musicId = null,
    musicStart = null,
    musicEnd = null,
    musicFade = true,
    musicVolume = null
  }) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');
    
    const payload = {
      target_date: targetDate,
      event_ids: eventIds,
      title,
      max_duration: maxDuration,
      resolution
    };

    if (musicId) payload.music_id = musicId;
    if (musicStart !== null && musicStart !== undefined) payload.music_start = musicStart;
    if (musicEnd !== null && musicEnd !== undefined) payload.music_end = musicEnd;
    if (musicFade !== null && musicFade !== undefined) payload.music_fade = musicFade;
    if (musicVolume !== null && musicVolume !== undefined) payload.music_volume = musicVolume;
    
    const res = await fetch(`${BFF_ROOT}/vlogs`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify(payload)
    });
    
    if (!res.ok) await handleApiError(res);
    return await res.json();
  },

  // 獲取 Vlog 列表
  list: async ({ skip = 0, limit = 20, status = null } = {}) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');
    
    const params = new URLSearchParams({ skip, limit });
    if (status) params.append('status', status);
    
    const res = await fetch(`${BFF_ROOT}/vlogs?${params.toString()}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });
    
    if (!res.ok) await handleApiError(res);
    return await res.json();
  },

  // 獲取 Vlog 詳情
  get: async (vlogId) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');
    
    const res = await fetch(`${BFF_ROOT}/vlogs/${vlogId}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });
    
    if (!res.ok) await handleApiError(res);
    return await res.json();
  },

  // 獲取 Vlog 播放 URL
  getUrl: async (vlogId, ttl = 3600) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');
    
    const params = new URLSearchParams({ ttl });
    
    const res = await fetch(`${BFF_ROOT}/vlogs/${vlogId}/url?${params.toString()}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });
    
    if (!res.ok) await handleApiError(res);
    return await res.json();
  },

  // 獲取 Vlog 縮圖 URL
  getThumbnailUrl: async (vlogId, ttl = 3600) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');
    
    const params = new URLSearchParams({ ttl });
    
    const res = await fetch(`${BFF_ROOT}/vlogs/${vlogId}/thumbnail-url?${params.toString()}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });
    
    if (!res.ok) await handleApiError(res);
    return await res.json();
  },

  // 刪除 Vlog
  delete: async (vlogId) => {
    const token = localStorage.getItem('jwt');
    if (!token) throw new Error('請先登入');
    
    const res = await fetch(`${BFF_ROOT}/vlogs/${vlogId}`, {
      method: 'DELETE',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });
    
    if (!res.ok) await handleApiError(res);
    return await res.json();
  }
},
};
