import { ApiClient } from "../APIClient.js";
class AppError extends Error {
  constructor(userMessage, technicalMessage, code, cause) {
    super(technicalMessage || userMessage);
    this.name = 'AppError';
    this.userMessage = userMessage;
    this.code = code;
    this.cause = cause;
  }
}
function toTTL(input, dflt = 300, min = 300, max = 21600) {
  const raw = (typeof input === 'object' && input !== null) ? input.ttl : input;
  const v = Number(raw);
  if (!Number.isFinite(v)) return dflt;
  const iv = Math.floor(v);
  if (iv < min) return min;
  if (iv > max) return max;
  return iv;
}
export class CameraService {
  constructor(api = ApiClient) {
    this.api = api;
    this._currentUserId = null;
  }

  async getCurrentUserId() {
    if (this._currentUserId) return this._currentUserId;
    // 先嘗試從 AuthService 取，取不到再打 /users/me
    if (window.AuthService && typeof window.AuthService.getUserId === 'function') {
      const uid = window.AuthService.getUserId();
      if (uid) {
        this._currentUserId = uid;
        return uid;
      }
    }
    const response = await this.api.getCurrentUser(); 
    // API 返回格式為 {user: {id: ..., ...}}，需要從 user 物件中取得 id
    const user = response?.user || response;
    if (!user?.id) throw new Error('無法取得使用者 ID');
    this._currentUserId = user.id;
    // 若有 AuthService，可回填
    if (window.AuthService && typeof window.AuthService.setUserId === 'function') {
      try { window.AuthService.setUserId(user.id); } catch (_) {}
    }
    return user.id;
  }

  async connect(id, arg) {
    // 僅轉呼叫 API；TTL 做安全轉換，避免 NaN/越界
    const ttl = toTTL(arg, 300, 300, 21600);
    return this.api.connectStream(id, { ttl });
  }

  // 取清單（參數物件可省略）
  async list(arg = {}) {
    const { status, q, page = 1, size = 10 } = arg;
    // 後端會用 JWT 的 current_user.id 決定可見範圍，因此前端不再強制帶 user_id，
    // 避免因為快取/錯誤 user_id 導致 403。
    return this.api.getCameras(null, status, q, page, size);
  }

  // 建立鏡頭
  async create(fields = {}) {
    const cameraData = {
      name: fields.name || "",
      max_publishers: fields.max_publishers || 1,
    };

    return this.api.createCamera(cameraData);
  }

  async get(id) {
    return this.api.getCamera(id); // ApiClient.getCamera
  }

  async update(id, fields = {}) {
    const patch = {};
    if (fields.name != null) patch.name = String(fields.name).trim();
      return this.api.updateCamera(id, patch);
  }

  async remove(id) {
    return this.api.deleteCamera(id); // ApiClient.deleteCamera
  }

  async deactivate(id) {
    return this.api.setCameraStatus(id, 'inactive'); // ApiClient.setCameraStatus
  }

  async activate(id) {
    return this.api.setCameraStatus(id, 'active'); // ApiClient.setCameraStatus
  }

  async setStatus(id, status) {
    return this.api.setCameraStatus(id, status); // ApiClient.setCameraStatus
  }

  async rotateToken(id) {
    return this.api.rotateTokenVersion(id); // ApiClient.rotateTokenVersion
  }

  // 串流操作（camera.js 會呼叫 svc.connect / svc.stop）


async connect(id, arg) {
  const ttl = toTTL(arg, 300, 300, 21600);
  return this.api.connectStream(id, { ttl });
}

  async stop(id) {
    return this.api.stopStream(id); // ApiClient.stopStream
  }

  // 取得推流/播放 URL（若你在 UI 要用）
  async getPublishRtspUrl(id, ttl = 10800) {
  return this.api.getPublishRtspUrl(id, ttl);
}


async getPlayWebrtcUrl(id, ttl = 180) {
  return this.api.getPlayWebrtcUrl(id, ttl);
}

async getStreamStatus(id) {
  return this.api.getStreamStatus(id);
}
}

window.CameraService = CameraService;
