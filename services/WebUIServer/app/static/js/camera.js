import { ApiClient } from "/static/js/APIClient.js";
import { AuthService } from "/static/js/AuthService.js";
import { CameraService } from "/static/js/services/CameraService.js";

window.ApiClient = ApiClient;
window.AuthService = AuthService;
window.CameraService = CameraService;

const svc = new CameraService(ApiClient);

// ----------------------------------------------------
// 使用者設定（TTL）
let userStreamTTL = 300; // 預設值

// 載入使用者設定
async function loadUserSettings() {
  try {
    if (ApiClient && ApiClient.settings) {
      const response = await ApiClient.settings.get();
      const settings = response.settings || response;
      if (settings && settings.default_stream_ttl !== undefined) {
        userStreamTTL = settings.default_stream_ttl;
        console.log('[Camera] 已載入使用者串流 TTL 設定:', userStreamTTL);
      }
    }
  } catch (e) {
    console.warn('[Camera] 載入使用者設定失敗，使用預設 TTL:', e);
  }
}

// ----------------------------------------------------
// DOM 快捷
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// ----------------------------------------------------
// 訊息顯示
function handleError(err) {
  console.error(err);
  alert(err?.message || "發生未知錯誤");
}
function handleSuccess(msg) {
  alert(msg || "操作成功");
}

// 顯示成功複製提示
function showCopySuccessToast(message = "成功複製") {
  // 移除已存在的提示框
  const existingToast = document.getElementById("copySuccessToast");
  if (existingToast) {
    existingToast.remove();
  }
  
  // 創建提示框
  const toast = document.createElement("div");
  toast.id = "copySuccessToast";
  toast.className = "copy-success-toast";
  toast.textContent = message;
  
  // 添加到頁面
  document.body.appendChild(toast);
  
  // 觸發動畫
  setTimeout(() => {
    toast.classList.add("show");
  }, 10);
  
  // 3 秒後自動移除
  setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => {
      if (toast.parentNode) {
        toast.remove();
      }
    }, 300); // 等待動畫完成
  }, 3000);
}

// ----------------------------------------------------
// 輔助狀態
let currentCamera = null;
let webrtcReconnectTimer = null;
let isPreviewActive = false;
let lastStreamStatus = null; // 追蹤上次的串流狀態，用於檢測狀態變化
let streamStatusInterval = null;

// ----------------------------------------------------
// 權限檢查與初始化
document.addEventListener("DOMContentLoaded", async () => {
  try {
    if (!(window.AuthService && AuthService.isLoggedIn && AuthService.isLoggedIn())) {
      window.location.href = "/auth.html";
      return;
    }
    await ApiClient.getCurrentUser();
    
    // 載入使用者設定（包含 TTL）
    await loadUserSettings();
  } catch (e) {
    console.warn(e);
    window.location.href = "/auth.html";
    return;
  }

  bindForm();
  bindControls();
  await loadCamera();
  
  // 開始輪詢串流狀態
  startStreamStatusPolling();

  // 頁面卸載時清理
  window.addEventListener("beforeunload", () => {
    stopPreview();
    stopStreamStatusPolling();
  });
});

// ----------------------------------------------------
// TTL：從使用者設定讀取
function getTTL() {
  // 確保 TTL 在有效範圍內
  if (userStreamTTL >= 30 && userStreamTTL <= 3600) {
    return userStreamTTL;
  }
  return 300; // 預設值
}

// ----------------------------------------------------
// WebRTC (WHEP)：以 WHEP Endpoint 建立下行播放
async function fetchWhepUrl(id, ttl) {
  const t = ttl ?? getTTL();
  const resp = await svc.getPlayWebrtcUrl?.(id, t);
  const url = resp?.play_webrtc_url || resp?.url;
  if (!url) throw new Error("未取得 WebRTC 播放網址");
  return url;
}

async function playWebRTCWithWHEP(video, id, ttl) {
  // 清掉 HLS 播放器，避免互相干擾
  if (window.__hls) { 
    try { window.__hls.destroy(); } catch {} 
    window.__hls = null; 
  }

  // 清除舊的連接
  if (window.__pc) {
    try { window.__pc.close(); } catch {}
    window.__pc = null;
  }

  try {
    const whepUrl = await fetchWhepUrl(id, ttl);

    // 配置 RTCPeerConnection
    // 即使是本地環境，也添加 STUN 服務器以幫助 ICE 連接
    const pc = new RTCPeerConnection({
      iceServers: [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' }
      ],
      iceCandidatePoolSize: 10
    });
    window.__pc = pc;
    
    // 監聽 ICE candidate 收集（用於調試）
    let iceCandidates = [];
    pc.onicecandidate = (event) => {
      if (event.candidate) {
        iceCandidates.push(event.candidate);
        console.log("[WebRTC] ICE candidate collected:", event.candidate.type, event.candidate.protocol, event.candidate.address, "port:", event.candidate.port);
      } else {
        console.log("[WebRTC] ICE candidate collection complete, total candidates:", iceCandidates.length);
        // 記錄所有 candidates 的詳細信息
        iceCandidates.forEach((c, i) => {
          console.log(`[WebRTC] Candidate ${i + 1}:`, c.type, c.protocol, c.address, "port:", c.port, "priority:", c.priority);
        });
        iceCandidates = []; // 重置
      }
    };
    
    // 監聽 ICE gathering 狀態
    pc.onicegatheringstatechange = () => {
      console.log("[WebRTC] ICE gathering state:", pc.iceGatheringState);
    };

    // 參考 view.html：創建一個 MediaStream 並直接設置到 video
    const remoteStream = new MediaStream();
    video.srcObject = remoteStream;
    
    // 確保 video 元素屬性正確設置（參考 view.html）
    video.autoplay = true;
    video.playsInline = true;
    video.muted = true; // 自動播放需要 muted

    // 參考 view.html：使用 ontrack 事件處理
    pc.ontrack = (ev) => {
      console.log("[WebRTC] Track received:", ev.track.kind, "streams:", ev.streams?.length || 0, "readyState:", ev.track.readyState);
      // 將 track 添加到 remoteStream（參考 view.html 的實現）
      if (ev.streams && ev.streams[0]) {
        ev.streams[0].getTracks().forEach(t => {
          // 避免重複添加相同的 track
          if (!remoteStream.getTracks().some(existing => existing.id === t.id)) {
            remoteStream.addTrack(t);
            console.log("[WebRTC] Added track to remoteStream:", t.kind, t.id, "enabled:", t.enabled, "muted:", t.muted);
            // 確保 track 啟用
            if (!t.enabled) {
              t.enabled = true;
              console.log("[WebRTC] Enabled track:", t.kind);
            }
          }
        });
      } else if (ev.track) {
        // 如果沒有 stream，直接添加 track
        if (!remoteStream.getTracks().some(existing => existing.id === ev.track.id)) {
          remoteStream.addTrack(ev.track);
          console.log("[WebRTC] Added track to remoteStream:", ev.track.kind, ev.track.id, "enabled:", ev.track.enabled, "muted:", ev.track.muted);
          // 確保 track 啟用
          if (!ev.track.enabled) {
            ev.track.enabled = true;
            console.log("[WebRTC] Enabled track:", ev.track.kind);
          }
        }
      }
      
      // 監聽 track 狀態變化
      ev.track.addEventListener("ended", () => {
        console.warn("[WebRTC] Track ended:", ev.track.kind);
      });
      
      ev.track.addEventListener("mute", () => {
        console.warn("[WebRTC] Track muted:", ev.track.kind);
        // 嘗試啟用 track
        if (!ev.track.enabled) {
          ev.track.enabled = true;
        }
      });
      
      ev.track.addEventListener("unmute", () => {
        console.log("[WebRTC] Track unmuted:", ev.track.kind);
        // Track 取消靜音時，確保視頻播放
        if (video.srcObject && video.paused) {
          video.play().catch((err) => {
            console.warn("[WebRTC] Video play failed after unmute:", err);
          });
        }
      });
      
      // 確保視頻播放（參考 view.html）
      // 立即嘗試播放，不等待
      if (video.srcObject) {
        console.log("[WebRTC] Attempting to play video immediately after track received");
        video.play().catch((err) => {
          console.warn("[WebRTC] Video play failed in ontrack:", err);
          // 如果立即播放失敗，等待一下再試
          setTimeout(() => {
            if (video.srcObject && video.paused) {
              console.log("[WebRTC] Retrying video play after delay");
              video.play().catch((err2) => {
                console.warn("[WebRTC] Video play retry failed:", err2);
              });
            }
          }, 500);
        });
      }
    };

    // 監聽 ICE 連接狀態變化
    // 參考 view.html：不主動處理失敗，但記錄狀態以便調試
    let iceConnectionTimeout = null;
    let iceConnectionStateLog = [];
    pc.addEventListener("iceconnectionstatechange", () => {
      const state = pc.iceConnectionState;
      console.log("[WebRTC] ICE connection state:", state);
      iceConnectionStateLog.push({ state, time: Date.now() });
      
      // 如果狀態變化太快，記錄警告
      if (iceConnectionStateLog.length > 1) {
        const lastState = iceConnectionStateLog[iceConnectionStateLog.length - 2];
        const timeDiff = Date.now() - lastState.time;
        if (timeDiff < 1000 && (state === "disconnected" || state === "failed")) {
          console.warn("[WebRTC] ICE connection state changed too quickly:", lastState.state, "->", state, "in", timeDiff, "ms");
        }
      }
      
      // 清除之前的超時
      if (iceConnectionTimeout) {
        clearTimeout(iceConnectionTimeout);
        iceConnectionTimeout = null;
      }
      
      if (pc.iceConnectionState === "connected" || pc.iceConnectionState === "completed") {
        console.log("[WebRTC] ICE connection established");
        if (video.srcObject && video.paused) {
          video.play().catch((err) => {
            console.warn("[WebRTC] Video play failed after ICE connected:", err);
          });
        }
      } else if (pc.iceConnectionState === "checking") {
        // 開始檢查連接，設置超時（30秒）
        console.log("[WebRTC] ICE connection checking, waiting for connection...");
        iceConnectionTimeout = setTimeout(() => {
          if (pc.iceConnectionState === "checking" || pc.iceConnectionState === "disconnected") {
            console.warn("[WebRTC] ICE connection timeout after 30s, current state:", pc.iceConnectionState);
            // 不主動重連，讓瀏覽器處理
          }
        }, 30000);
      } else if (pc.iceConnectionState === "disconnected") {
        // 連接中斷，等待恢復（給更多時間）
        console.log("[WebRTC] ICE connection disconnected, waiting for recovery...");
        iceConnectionTimeout = setTimeout(() => {
          if (pc.iceConnectionState === "disconnected" && isPreviewActive && currentCamera?.id === id) {
            console.warn("[WebRTC] ICE still disconnected after 15s, attempting ICE restart");
            // 嘗試重啟 ICE 連接
            try {
              pc.restartIce();
              console.log("[WebRTC] ICE restart initiated");
              
              // 監聽 ICE restart 後的狀態變化
              const restartTimeout = setTimeout(() => {
                if (pc.iceConnectionState === "disconnected" || pc.iceConnectionState === "failed") {
                  if (isPreviewActive && currentCamera?.id === id) {
                    console.warn("[WebRTC] ICE restart did not recover from disconnected state, will reconnect");
                    scheduleWebRTCReconnect(video, id, ttl);
                  }
                }
              }, 10000); // 10 秒後檢查是否恢復
              
              // 如果恢復成功，清除超時
              const checkRecovery = () => {
                if (pc.iceConnectionState === "connected" || pc.iceConnectionState === "completed") {
                  clearTimeout(restartTimeout);
                  pc.removeEventListener("iceconnectionstatechange", checkRecovery);
                  console.log("[WebRTC] ICE connection recovered after restart");
                }
              };
              pc.addEventListener("iceconnectionstatechange", checkRecovery);
            } catch (err) {
              console.warn("[WebRTC] ICE restart failed:", err);
              // 如果重啟失敗，嘗試重新連接
              if (isPreviewActive && currentCamera?.id === id) {
                scheduleWebRTCReconnect(video, id, ttl);
              }
            }
          }
        }, 15000); // 15 秒後嘗試重啟
      } else if (pc.iceConnectionState === "failed") {
        // ICE 連接失敗，嘗試重啟
        console.warn("[WebRTC] ICE connection failed, attempting ICE restart");
        try {
          pc.restartIce();
          console.log("[WebRTC] ICE restart initiated after failure");
          
          // 監聽 ICE restart 後的狀態變化
          const restartTimeout = setTimeout(() => {
            if (pc.iceConnectionState === "failed" && isPreviewActive && currentCamera?.id === id) {
              console.warn("[WebRTC] ICE restart did not recover connection, will reconnect");
              scheduleWebRTCReconnect(video, id, ttl);
            }
          }, 10000); // 10 秒後檢查是否恢復
          
          // 如果恢復成功，清除超時
          const checkRecovery = () => {
            if (pc.iceConnectionState === "connected" || pc.iceConnectionState === "completed") {
              clearTimeout(restartTimeout);
              pc.removeEventListener("iceconnectionstatechange", checkRecovery);
            }
          };
          pc.addEventListener("iceconnectionstatechange", checkRecovery);
        } catch (err) {
          console.warn("[WebRTC] ICE restart failed:", err);
          // 如果重啟失敗，嘗試重新連接
          if (isPreviewActive && currentCamera?.id === id) {
            setTimeout(() => {
              if (isPreviewActive && currentCamera?.id === id) {
                scheduleWebRTCReconnect(video, id, ttl);
              }
            }, 2000);
          }
        }
      }
    });

    // 監聽連接狀態變化（簡化處理，參考 view.html）
    pc.addEventListener("connectionstatechange", () => {
      console.log("[WebRTC] Connection state:", pc.connectionState);
      if (pc.connectionState === "connected") {
        // 連接成功，清除重連計數器
        console.log("[WebRTC] Connection established");
        if (webrtcReconnectTimer) {
          clearTimeout(webrtcReconnectTimer);
          webrtcReconnectTimer = null;
        }
        reconnectAttempts = 0;
        // 確保視頻播放
        if (video.srcObject && video.paused) {
          video.play().catch((err) => {
            console.warn("[WebRTC] Video play failed after connection:", err);
          });
        }
      }
      // 不主動處理 failed 狀態，讓瀏覽器自動重試或依賴重連機制
    });

    // 參考 view.html：添加 video 和 audio transceiver
    pc.addTransceiver('video', { direction: 'recvonly' });
    pc.addTransceiver('audio', { direction: 'recvonly' });

    // 創建 offer，使用 offerToReceive 選項以改善連接
    const offer = await pc.createOffer({
      offerToReceiveAudio: true,
      offerToReceiveVideo: true
    });
    await pc.setLocalDescription(offer);

    // 等待 ICE gathering 完成後再發送 offer
    // 參考 view.html：不設置超時，等待 ICE gathering 完成
    // 這確保所有 ICE candidates 都包含在 SDP 中
    await new Promise((res) => {
      if (pc.iceGatheringState === 'complete') {
        console.log("[WebRTC] ICE gathering already complete");
        return res();
      }
      
      // 優化：減少超時時間，通常幾秒內就能完成
      const timeout = setTimeout(() => {
        pc.removeEventListener('icegatheringstatechange', fn);
        console.warn("[WebRTC] ICE gathering timeout (10s), proceeding anyway. Current state:", pc.iceGatheringState);
        res(); // 超時後繼續，不阻塞
      }, 10000); // 減少到 10 秒超時（通常幾秒內就能完成）
      
      const fn = () => {
        console.log("[WebRTC] ICE gathering state changed:", pc.iceGatheringState);
        if (pc.iceGatheringState === 'complete') {
          clearTimeout(timeout);
          pc.removeEventListener('icegatheringstatechange', fn);
          console.log("[WebRTC] ICE gathering complete, sending offer");
          res();
        }
      };
      pc.addEventListener('icegatheringstatechange', fn);
    });

    // 記錄發送的 SDP offer（用於調試）
    console.log("[WebRTC] Sending offer, SDP length:", pc.localDescription.sdp.length);
    const offerCandidates = (pc.localDescription.sdp.match(/a=candidate:/g) || []).length;
    console.log("[WebRTC] Offer contains", offerCandidates, "ICE candidates");
    
    const res = await fetch(whepUrl, {
      method: "POST",
      headers: { "Content-Type": "application/sdp" },
      body: pc.localDescription.sdp
    });
    if (!res.ok) {
      const errorText = await res.text().catch(() => "");
      console.warn(`[WebRTC] WHEP request failed: ${res.status} ${res.statusText}`, errorText);
      // 如果是 404，表示串流還沒有開始，等待一下再重試
      if (res.status === 404) {
        console.log("[WebRTC] Stream not available yet, will retry after delay");
        if (isPreviewActive && currentCamera?.id === id) {
          // 優化：減少重試延遲，更快響應
          setTimeout(() => {
            if (isPreviewActive && currentCamera?.id === id) {
              scheduleWebRTCReconnect(video, id, ttl);
            }
          }, 1000); // 減少到 1 秒後重試（更快響應）
        }
      } else {
        if (isPreviewActive && currentCamera?.id === id) {
          scheduleWebRTCReconnect(video, id, ttl);
        }
      }
      return;
    }
    const answerSdp = await res.text();
    if (!answerSdp || answerSdp.trim().length === 0) {
      console.warn("[WebRTC] Empty SDP answer received");
      if (isPreviewActive && currentCamera?.id === id) {
        scheduleWebRTCReconnect(video, id, ttl);
      }
      return;
    }
    
    // 記錄接收到的 SDP answer（用於調試）
    console.log("[WebRTC] Received answer, SDP length:", answerSdp.length);
    const answerCandidates = (answerSdp.match(/a=candidate:/g) || []).length;
    console.log("[WebRTC] Answer contains", answerCandidates, "ICE candidates");
    
    // 關鍵修復：如果 answer 中的 candidates 使用內部端口 8189，需要替換為外部端口 30205
    // 因為瀏覽器無法直接連接到容器內部端口
    let modifiedAnswerSdp = answerSdp;
    
    // 檢查 answer 中是否包含 ICE candidates
    if (answerCandidates === 0) {
      console.warn("[WebRTC] WARNING: Answer SDP contains no ICE candidates!");
    } else {
      // 解析並顯示前幾個 candidates 的詳細信息
      const candidateLines = answerSdp.match(/a=candidate:.*/g) || [];
      console.log("[WebRTC] Answer ICE candidates (first 5):");
      candidateLines.slice(0, 5).forEach((line, i) => {
        const parts = line.split(' ');
        if (parts.length >= 5) {
          const port = parts[5];
          const address = parts[4];
          console.log(`[WebRTC]   Candidate ${i + 1}:`, address, parts[2], parts[3], "port:", port);
          // 如果端口是 8189（內部端口），記錄警告
          if (port === "8189" && (address === "127.0.0.1" || address === "localhost")) {
            console.warn(`[WebRTC]   WARNING: Candidate uses internal port ${port}, but Docker maps it to external port 30205`);
          }
        }
      });
      
      // 如果 answer 中包含內部端口 8189，替換為外部端口 30205
      // 檢查多種可能的格式：:8189、 8189、port 8189 等
      if (answerSdp.includes('8189')) {
        console.warn("[WebRTC] Answer contains internal port 8189, replacing with external port 30205");
        console.log("[WebRTC] Original SDP snippet (first 500 chars):", answerSdp.substring(0, 500));
        
        // 替換所有 candidate 行中的端口 8189 為 30205
        // SDP candidate 格式：a=candidate:foundation component type priority address port typ ...
        // 例如：a=candidate:1 1 udp 2130706431 127.0.0.1 8189 typ host
        // 需要匹配：空格 + 8189 + 空格 或 空格 + 8189 + 回車/換行
        modifiedAnswerSdp = answerSdp.replace(/(\s)8189(\s|$)/g, '$130205$2');
        
        // 同時替換可能的其他格式（如果有的話）
        modifiedAnswerSdp = modifiedAnswerSdp.replace(/:8189/g, ':30205');
        
        console.log("[WebRTC] Modified answer SDP to use external port 30205");
        console.log("[WebRTC] Modified SDP snippet (first 500 chars):", modifiedAnswerSdp.substring(0, 500));
        
        // 驗證替換是否成功
        const originalCount = (answerSdp.match(/8189/g) || []).length;
        const modifiedCount = (modifiedAnswerSdp.match(/8189/g) || []).length;
        const newPortCount = (modifiedAnswerSdp.match(/30205/g) || []).length;
        console.log("[WebRTC] Port replacement: original 8189 count:", originalCount, "remaining:", modifiedCount, "new 30205 count:", newPortCount);
        
        if (modifiedCount > 0) {
          console.error("[WebRTC] WARNING: Some port 8189 instances were not replaced!");
        }
      }
    }
    
    console.log("[WebRTC] Setting remote description");
    // 使用修改後的 SDP（如果端口被替換）
    await pc.setRemoteDescription({ type: "answer", sdp: modifiedAnswerSdp });
    
    // 參考 view.html：在設置 remote description 後，確保視頻播放
    // 添加一個短延遲，確保 track 事件已經觸發
    setTimeout(() => {
      if (video.srcObject && video.paused) {
        console.log("[WebRTC] Attempting to play video after setRemoteDescription");
        video.play().catch((err) => {
          console.warn("[WebRTC] Video play failed after setRemoteDescription:", err);
        });
      }
    }, 500);
  } catch (e) {
    console.warn("[WebRTC] Connection error, will retry:", e);
    if (isPreviewActive && currentCamera?.id === id) {
      scheduleWebRTCReconnect(video, id, ttl);
    }
  }
}

// 安排 WebRTC 重連（每5秒，避免過於頻繁）
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 20; // 最多重試 20 次（約 100 秒）

function scheduleWebRTCReconnect(video, id, ttl) {
  if (webrtcReconnectTimer) {
    clearTimeout(webrtcReconnectTimer);
  }
  
  if (!isPreviewActive || currentCamera?.id !== id) {
    reconnectAttempts = 0; // 重置計數
    return;
  }

  reconnectAttempts++;
  if (reconnectAttempts > MAX_RECONNECT_ATTEMPTS) {
    console.warn("[WebRTC] Max reconnect attempts reached, stopping retry");
    reconnectAttempts = 0;
    return;
  }

  webrtcReconnectTimer = setTimeout(async () => {
    if (isPreviewActive && currentCamera?.id === id) {
      console.log(`[WebRTC] Attempting to reconnect... (attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`);
      try {
        // 先清理舊的連接
        if (window.__pc) {
          try {
            window.__pc.close();
          } catch (e) {
            console.warn("[WebRTC] Error closing old connection:", e);
          }
          window.__pc = null;
        }
        await playWebRTCWithWHEP(video, id, ttl);
        reconnectAttempts = 0; // 重置計數
      } catch (e) {
        console.warn("[WebRTC] Reconnect failed, will retry:", e);
        // 如果重連失敗，繼續安排下一次重試
        scheduleWebRTCReconnect(video, id, ttl);
      }
    }
  }, 5000); // 改為 5 秒，避免過於頻繁
}

// ----------------------------------------------------
// 綁定：新增鏡頭表單
function bindForm() {
  const form = $("#cameraForm");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector('button[type="submit"]');
    const name = $("#camera_name")?.value?.trim();

    if (!name) return handleError(new Error("請輸入鏡頭名稱"));

    btn.disabled = true;
    try {
      await svc.create({ name });
      handleSuccess("已新增鏡頭");
      form.reset();
      await loadCamera();
    } catch (err) {
      handleError(err);
    } finally {
      btn.disabled = false;
    }
  });
}

// ----------------------------------------------------
// 綁定：操作按鈕
function bindControls() {
  $("#startStreamBtn")?.addEventListener("click", async () => {
    if (!currentCamera) return;
    await handleStartStream();
  });

  $("#stopStreamBtn")?.addEventListener("click", async () => {
    if (!currentCamera) return;
    await handleStopStream();
  });

  $("#publishUrlBtn")?.addEventListener("click", async () => {
    if (!currentCamera) return;
    await handlePublishUrl();
  });

  // 鏡頭資訊表單提交
  const infoForm = $("#cameraInfoForm");
  if (infoForm) {
    infoForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!currentCamera) return;
      await handleSaveCameraInfo();
    });
  }
}

// ----------------------------------------------------
// 載入鏡頭（只載入第一個非刪除狀態的鏡頭）
async function loadCamera() {
  try {
    const resp = await svc.list({
      page: 1,
      size: 100,
    });
    
    const items = resp?.items || resp || [];
    // 找到第一個非刪除狀態的鏡頭
    const activeCamera = items.find(cam => cam.status !== "deleted");
    
    if (activeCamera) {
      currentCamera = activeCamera;
      showCameraInfo(activeCamera);
      showControls(true);
      showAddForm(false);
    } else {
      currentCamera = null;
      showCameraInfo(null);
      showControls(false);
      showAddForm(true);
    }
  } catch (err) {
    handleError(err);
  }
}

// 顯示鏡頭資訊
function showCameraInfo(camera) {
  const infoCard = $("#cameraInfoCard");
  if (!infoCard) return;

  if (camera) {
    const nameInput = $("#cameraNameInput");
    const statusSelect = $("#cameraStatusSelect");
    
    if (nameInput) {
      nameInput.value = camera.name || "";
    }
    if (statusSelect) {
      statusSelect.value = camera.status || "inactive";
    }
    infoCard.style.display = "block";
    
    // 更新串流狀態
    updateStreamStatus();
  } else {
    infoCard.style.display = "none";
    // 清除串流狀態顯示
    updateStreamStatusDisplay(false, "stopped");
  }
}

// 更新串流狀態顯示（完全根據後端返回的狀態）
function updateStreamStatusDisplay(isStreaming, status) {
  const statusDot = $("#streamStatusDot");
  const statusText = $("#streamStatusText");
  
  if (!statusDot || !statusText) return;
  
  // 根據後端返回的狀態顯示
  if (status === "reconnecting") {
    // 重連中狀態（後端明確返回）
    statusDot.className = "status-dot reconnecting";
    statusText.textContent = "重連中...";
  } else if (status === "running") {
    // 運行中
    statusDot.className = "status-dot streaming";
    statusText.textContent = "串流中";
  } else if (status === "starting") {
    // 啟動中
    statusDot.className = "status-dot streaming";
    statusText.textContent = "串流啟動中...";
  } else {
    // stopped, error 或其他狀態
    statusDot.className = "status-dot stopped";
    statusText.textContent = "未串流";
  }
}

// 查詢並更新串流狀態
async function updateStreamStatus() {
  if (!currentCamera) {
    updateStreamStatusDisplay(false, "stopped");
    // 如果沒有當前相機，停止預覽
    if (isPreviewActive) {
      stopPreview();
    }
    lastStreamStatus = null;
    return;
  }
  
  try {
    const statusResp = await svc.getStreamStatus?.(currentCamera.id);
    const isStreaming = statusResp?.is_streaming || false;
    const status = statusResp?.status || "stopped";
    
    // 完全依賴後端返回的狀態，不自己判斷
    // 後端會返回: "starting", "running", "stopped", "error", "reconnecting"
    
    // 更新顯示（根據後端返回的狀態）
    // 完全依賴後端返回的狀態
    if (status === "running") {
      updateStreamStatusDisplay(true, "running");
      
      // 檢測狀態變化並自動觸發 WebRTC 播放
      if (lastStreamStatus !== "running") {
        console.log(`[Stream Status] Status changed: ${lastStreamStatus} -> running`);
        lastStreamStatus = "running";
        
        // 串流狀態變為 running，自動啟動預覽
        if (!isPreviewActive) {
          console.log("[Stream Status] Stream is running, auto-starting preview");
          startPreview();
        }
      }
    } else if (status === "reconnecting") {
      // 後端明確返回重連中狀態
      updateStreamStatusDisplay(true, "reconnecting");
      
      if (lastStreamStatus !== "reconnecting") {
        console.log(`[Stream Status] Status changed: ${lastStreamStatus} -> reconnecting (backend reported)`);
        lastStreamStatus = "reconnecting";
      }
    } else {
      // stopped, error, starting 等狀態
      updateStreamStatusDisplay(isStreaming, status);
      
      // 如果狀態變為 stopped 或 error，停止預覽
      if ((status === "stopped" || status === "error") && isPreviewActive) {
        if (lastStreamStatus !== status) {
          console.log(`[Stream Status] Status changed: ${lastStreamStatus} -> ${status}, stopping preview`);
          lastStreamStatus = status;
          stopPreview();
        }
      } else if (lastStreamStatus !== status) {
        console.log(`[Stream Status] Status changed: ${lastStreamStatus} -> ${status}`);
        lastStreamStatus = status;
      }
    }
  } catch (err) {
    console.warn("[Stream Status] Failed to get stream status:", err);
    
    // API 錯誤時，如果之前有串流，給一次機會（不清除狀態）
    // 但不要自己判斷重連，等後端恢復後再判斷
    updateStreamStatusDisplay(false, "stopped");
    if (isPreviewActive && lastStreamStatus === "running") {
      // 如果之前是運行狀態，可能是暫時的 API 錯誤，不立即停止預覽
      // 但清除狀態追蹤，讓下次成功獲取狀態時再判斷
      console.log("[Stream Status] API error, but keeping preview active temporarily");
    } else {
      // 如果之前就不是運行狀態，直接停止
      if (isPreviewActive) {
        stopPreview();
      }
      lastStreamStatus = null;
    }
  }
}

// 開始輪詢串流狀態（每 3 秒）
function startStreamStatusPolling() {
  stopStreamStatusPolling(); // 先清除舊的輪詢
  streamStatusInterval = setInterval(() => {
    if (currentCamera) {
      updateStreamStatus();
    }
  }, 3000);
  
  // 立即執行一次
  if (currentCamera) {
    updateStreamStatus();
  }
}

// 停止輪詢串流狀態
function stopStreamStatusPolling() {
  if (streamStatusInterval) {
    clearInterval(streamStatusInterval);
    streamStatusInterval = null;
  }
}

// 顯示/隱藏控制區
function showControls(show) {
  const controlCard = $("#cameraControlCard");
  if (controlCard) {
    controlCard.style.display = show ? "block" : "none";
  }
}

// 顯示/隱藏新增表單
function showAddForm(show) {
  const addCard = $("#addCameraCard");
  if (addCard) {
    addCard.style.display = show ? "block" : "none";
  }
}

// ----------------------------------------------------
// 操作處理函數
async function handleStartStream() {
  if (!currentCamera) return;
  
  const btn = $("#startStreamBtn");
  btn.disabled = true;
  
  try {
    const ttl = getTTL();
    let resp;
    try {
      resp = await svc.connect(currentCamera.id, { ttl });
    } catch (e) {
      if (!(e && (e.status === 409 || e.code === "AlreadyConnected"))) throw e;
      resp = { ttl };
    }
    // 獲取推流 URL 並複製到剪貼板（不顯示 alert）
    try {
      const pub = await svc.getPublishRtspUrl?.(currentCamera.id, ttl);
      const rtsp = pub?.publish_rtsp_url || pub?.rtsp_url || pub?.url || null;
      if (rtsp) {
        await navigator.clipboard?.writeText?.(rtsp).catch(() => {});
        // 使用 toast 提示而不是 alert
        showCopySuccessToast(`已複製 RTSP URL\n請到攝影機/OBS 開始推流`);
        console.log("[Start Stream] RTSP URL copied to clipboard:", rtsp);
      }
    } catch (e) {
      console.warn("getPublishRtspUrl 失敗：", e);
    }
    
    // 更新串流狀態（會自動觸發預覽啟動，如果狀態為 running）
    await updateStreamStatus();
  } catch (err) {
    handleError(err);
  } finally {
    btn.disabled = false;
  }
}

// 停止串流確認對話框
const stopStreamConfirmDialog = document.getElementById('stopStreamConfirmDialog');
const stopStreamCancelBtn = document.getElementById('stopStreamCancelBtn');
const stopStreamConfirmBtn = document.getElementById('stopStreamConfirmBtn');

// 顯示停止串流確認對話框
function showStopStreamConfirm() {
  if (stopStreamConfirmDialog) {
    stopStreamConfirmDialog.showModal();
  }
}

// 關閉停止串流確認對話框
function closeStopStreamConfirm() {
  if (stopStreamConfirmDialog) {
    stopStreamConfirmDialog.close();
  }
}

// 執行停止串流
async function performStopStream() {
  if (!currentCamera) return;
  
  const btn = $("#stopStreamBtn");
  btn.disabled = true;
  
  try {
    await svc.stop(currentCamera.id);
    // 不顯示 alert，只使用 toast 提示
    showCopySuccessToast("串流已停止");
    console.log("[Stop Stream] Stream stopped successfully");
    
    // 更新串流狀態（會自動停止預覽，如果狀態變為 stopped）
    await updateStreamStatus();
  } catch (err) {
    handleError(err);
  } finally {
    btn.disabled = false;
  }
}

async function handleStopStream() {
  if (!currentCamera) return;
  // 顯示確認對話框（與登出一樣的風格）
  showStopStreamConfirm();
}

// 綁定停止串流確認對話框事件
if (stopStreamCancelBtn) {
  stopStreamCancelBtn.addEventListener("click", () => {
    closeStopStreamConfirm();
  });
}

// 綁定確認停止串流按鈕事件
if (stopStreamConfirmBtn) {
  stopStreamConfirmBtn.addEventListener("click", () => {
    closeStopStreamConfirm();
    performStopStream();
  });
}

// 點擊對話框外部關閉
if (stopStreamConfirmDialog) {
  stopStreamConfirmDialog.addEventListener("click", (e) => {
    if (e.target === stopStreamConfirmDialog) {
      closeStopStreamConfirm();
    }
  });

  // ESC 鍵關閉對話框
  stopStreamConfirmDialog.addEventListener("cancel", (e) => {
    e.preventDefault();
    closeStopStreamConfirm();
  });
}

// 自動開始預覽（當開始串流後）
async function startPreview() {
  if (!currentCamera) return;
  
  try {
    const ttl = getTTL();
    const video = $("#previewVideo");
    const placeholder = $("#previewPlaceholder");
    
    if (!video || !placeholder) {
      console.warn("[Preview] Video or placeholder element not found");
      return;
    }
    
    // 顯示視頻，隱藏佔位符
    video.style.display = "block";
    placeholder.style.display = "none";
    
    // 確保視頻元素可見
    video.style.visibility = "visible";
    video.style.opacity = "1";
    
    // 設置必要的屬性
    video.muted = true; // 必須靜音才能自動播放
    video.playsInline = true;
    video.autoplay = true; // 啟用自動播放
    
    // 監聽視頻元素狀態變化
    video.addEventListener("loadedmetadata", () => {
      console.log("[Preview] Video metadata loaded:", {
        videoWidth: video.videoWidth,
        videoHeight: video.videoHeight,
        duration: video.duration
      });
    });
    
    video.addEventListener("loadeddata", () => {
      console.log("[Preview] Video data loaded");
      if (video.paused) {
        video.play().catch((err) => {
          console.warn("[Preview] Video play failed on loadeddata:", err);
        });
      }
    });
    
    video.addEventListener("playing", () => {
      console.log("[Preview] Video is playing");
    });
    
    video.addEventListener("pause", () => {
      console.warn("[Preview] Video paused");
    });
    
    video.addEventListener("error", (e) => {
      console.error("[Preview] Video error:", e, video.error);
    });
    
    isPreviewActive = true;
    
    console.log("[Preview] Starting WebRTC playback");
    // 直接嘗試播放，如果失敗會自動重連
    // WebRTC 連接失敗時會自動重試，不需要等待串流狀態
    await playWebRTCWithWHEP(video, currentCamera.id, ttl);
  } catch (err) {
    console.warn("[Preview] Failed to start preview:", err);
    // 優化：減少重試延遲
    if (isPreviewActive && currentCamera?.id) {
      setTimeout(() => startPreview(), 1000); // 減少到 1 秒後重試（更快響應）
    }
  }
}

function stopPreview() {
  if (!isPreviewActive) return; // 如果已經停止，不需要重複執行
  
  console.log("[Preview] Stopping preview");
  isPreviewActive = false;
  reconnectAttempts = 0; // 重置重連計數
  
  // 清除重連計時器
  if (webrtcReconnectTimer) {
    clearTimeout(webrtcReconnectTimer);
    webrtcReconnectTimer = null;
  }
  
  // 關閉連接
  if (window.__hls) { 
    try { window.__hls.destroy(); } catch {} 
    window.__hls = null; 
  }
  if (window.__pc) { 
    try { window.__pc.close(); } catch {} 
    window.__pc = null; 
  }
  
  // 重置視頻
  const video = $("#previewVideo");
  const placeholder = $("#previewPlaceholder");
  if (video) {
    video.pause();
    video.removeAttribute("src");
    video.srcObject = null;
    video.load();
    video.style.display = "none";
  }
  if (placeholder) {
    placeholder.style.display = "flex";
  }
}

async function handlePublishUrl() {
  if (!currentCamera) return;
  
  const btn = $("#publishUrlBtn");
  btn.disabled = true;
  
  try {
    const ttl = getTTL();
    const resp = await svc.getPublishRtspUrl?.(currentCamera.id, ttl);
    const url = resp?.publish_rtsp_url || resp?.rtsp_url || resp?.url || null;
    
    if (url) {
      // 複製到剪貼簿
      try {
        await navigator.clipboard?.writeText?.(url);
        // 顯示成功複製提示
        showCopySuccessToast("成功複製");
      } catch (clipboardErr) {
        console.error("複製失敗：", clipboardErr);
        handleError(new Error("複製到剪貼簿失敗，請手動複製"));
      }
    } else {
      handleError(new Error("無法取得串流連結"));
    }
  } catch (err) {
    handleError(err);
  } finally {
    btn.disabled = false;
  }
}

async function handleSaveCameraInfo() {
  if (!currentCamera) return;
  
  const btn = $("#saveCameraBtn");
  const nameInput = $("#cameraNameInput");
  const statusSelect = $("#cameraStatusSelect");
  
  if (!nameInput || !statusSelect) return;
  
  const newName = nameInput.value.trim();
  const newStatus = statusSelect.value;
  
  if (!newName) {
    handleError(new Error("名稱必填"));
    return;
  }

  btn.disabled = true;
  
  try {
    // 更新名稱
    await svc.update(currentCamera.id, { name: newName });
    
    // 如果狀態改變，更新狀態
    if (newStatus !== currentCamera.status) {
      await svc.setStatus(currentCamera.id, newStatus);
    }
    
    handleSuccess("已更新鏡頭設定");
    await loadCamera();
  } catch (err) {
    handleError(err);
  } finally {
    btn.disabled = false;
  }
}
