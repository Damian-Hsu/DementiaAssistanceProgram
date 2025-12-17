import { ApiClient } from './APIClient.js';
import { AuthService } from './AuthService.js';

// DOM 元素
const chatMessages = document.getElementById('chatMessages');
const chatInput = document.getElementById('chatInput');
const chatSend = document.getElementById('chatSend');
const clearChat = document.getElementById('clearChat');
const chatDateFrom = document.getElementById('chatDateFrom');
const chatDateTo = document.getElementById('chatDateTo');
const chatToolsBtn = document.getElementById('chatToolsBtn');
const chatToolsPanel = document.getElementById('chatToolsPanel');

// 對話歷史
let chatHistory = [];

// === 對話持久化（直到使用者按「清除對話」才清掉） ===
const CHAT_STORAGE_PREFIX = 'chat_history_user_v1:';
function getChatStorageKey() {
  const uid = (localStorage.getItem('user_id') || '').trim() || 'anonymous';
  return `${CHAT_STORAGE_PREFIX}${uid}`;
}
function loadPersistedChat() {
  try {
    const raw = localStorage.getItem(getChatStorageKey());
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed?.messages) ? parsed.messages : [];
  } catch {
    return [];
  }
}
function savePersistedChat(messages) {
  try {
    // 上限避免無限膨脹（保留最近 200 則即可）
    const trimmed = Array.isArray(messages) ? messages.slice(-200) : [];
    localStorage.setItem(getChatStorageKey(), JSON.stringify({ messages: trimmed }));
  } catch {}
}
function clearPersistedChat() {
  try { localStorage.removeItem(getChatStorageKey()); } catch {}
}

function renderWelcomeMessage() {
  if (!chatMessages) return;
  chatMessages.innerHTML = `
    <div class="chat-message ai">
      <div class="chat-avatar">AI</div>
      <div class="message-content">
        <div class="chat-bubble">
          👋 你好，我是你的 AI 助手。<br>
          你現在想回想什麼呢？我可以陪你聊～
        </div>
        <div class="chat-time">AI 助手</div>
      </div>
    </div>
  `;
}

// 工具函數
function scrollChatToBottom() {
  if (!chatMessages) return;
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function addChatMessage(content, isUser = false, events = null, recordings = null, diaries = null, vlogs = null, { persist = true } = {}) {
  if (!chatMessages) return;
  
  const messageDiv = document.createElement('div');
  messageDiv.className = `chat-message ${isUser ? 'user' : 'ai'}`;
  
  const now = new Date().toLocaleTimeString('zh-TW', { 
    hour: '2-digit', 
    minute: '2-digit' 
  });
  
  // 如果有事件，添加「顯示事件」按鈕，但不直接顯示事件列表
  let eventsButtonHtml = '';
  if (events && events.length > 0) {
    const eventsDataId = `events-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    messageDiv.dataset.eventsId = eventsDataId;
    messageDiv.dataset.eventsData = JSON.stringify(events);
    
    eventsButtonHtml = `
      <div style="margin-top: 12px;">
        <button class="btn-show-events" data-events-id="${eventsDataId}" style="
          padding: 8px 16px;
          background: var(--color-accent, #6B4F4F);
          color: #fff;
          border: none;
          border-radius: 8px;
          cursor: pointer;
          font-size: 14px;
          font-weight: 500;
          transition: all 0.2s ease;
        ">
          顯示事件 (${events.length})
        </button>
      </div>
    `;
  }
  
  // 如果有影片，根據數量決定顯示方式
  let recordingsButtonHtml = '';
  if (recordings && recordings.length > 0) {
    const recordingsDataId = `recordings-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    messageDiv.dataset.recordingsId = recordingsDataId;
    messageDiv.dataset.recordingsData = JSON.stringify(recordings);
    
    if (recordings.length > 3) {
      // 超過3個影片，顯示按鈕
      recordingsButtonHtml = `
        <div style="margin-top: 12px;">
          <button class="btn-show-recordings" data-recordings-id="${recordingsDataId}" style="
            padding: 8px 16px;
            background: var(--color-accent, #6B4F4F);
            color: #fff;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.2s ease;
          ">
            顯示影片 (${recordings.length})
          </button>
        </div>
      `;
    } else {
      // 3個或以下，直接顯示影片列表
      recordingsButtonHtml = `
        <div style="margin-top: 12px;" class="recordings-preview-list">
          ${recordings.map((rec, idx) => `
            <div class="recording-preview-item" data-recording-id="${rec.id}" style="
              padding: 8px 12px;
              margin-bottom: 8px;
              background: var(--bg-button, #F3F0EB);
              border: 1px solid var(--color-border, #D3C0A8);
              border-radius: 8px;
              cursor: pointer;
              transition: all 0.2s ease;
            ">
              <div style="font-size: 13px; color: var(--color-accent, #6B4F4F); font-weight: 500;">
                ${rec.time || '未知時間'} (${Math.round(rec.duration || 0)}秒)
              </div>
              <div style="font-size: 12px; color: var(--text-muted-light, #666); margin-top: 4px;">
                ${rec.summary || '無描述'}
              </div>
            </div>
          `).join('')}
        </div>
      `;
    }
  }
  
  // 處理日記顯示
  let diaryHtml = '';
  if (diaries && diaries.length > 0) {
    diaries.forEach(diary => {
      if (diary.exists && diary.content) {
        diaryHtml += `
          <div style="margin-top: 12px; padding: 12px; background: var(--bg-button, #F3F0EB); border-radius: 8px; border: 1px solid var(--color-border, #D3C0A8);">
            <div style="font-size: 13px; color: var(--color-accent, #6B4F4F); font-weight: 500; margin-bottom: 8px;">
              ${diary.date} 的日記
            </div>
            <div style="font-size: 14px; color: var(--color-text, #2E2E2E); line-height: 1.6; white-space: pre-wrap;">
              ${diary.content}
            </div>
          </div>
        `;
      } else if (diary.success !== undefined) {
        // 刷新日記的結果
        if (diary.success) {
          diaryHtml += `
            <div style="margin-top: 12px; padding: 12px; background: #e8f5e9; border-radius: 8px; border: 1px solid #4caf50;">
              <div style="font-size: 13px; color: #2e7d32; font-weight: 500; margin-bottom: 8px;">
                ${diary.date} 的日記已刷新
              </div>
              ${diary.content ? `<div style="font-size: 14px; color: var(--color-text, #2E2E2E); line-height: 1.6; white-space: pre-wrap;">${diary.content}</div>` : ''}
            </div>
          `;
        } else {
          diaryHtml += `
            <div style="margin-top: 12px; padding: 12px; background: #ffebee; border-radius: 8px; border: 1px solid #f44336;">
              <div style="font-size: 13px; color: #c62828; font-weight: 500;">
                刷新失敗：${diary.message || '未知錯誤'}
              </div>
            </div>
          `;
        }
      }
    });
  }
  
  // 處理Vlog顯示（類似影片）
  let vlogsButtonHtml = '';
  if (vlogs && vlogs.length > 0) {
    const vlogsDataId = `vlogs-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    messageDiv.dataset.vlogsId = vlogsDataId;
    messageDiv.dataset.vlogsData = JSON.stringify(vlogs);
    
    if (vlogs.length > 3) {
      vlogsButtonHtml = `
        <div style="margin-top: 12px;">
          <button class="btn-show-vlogs" data-vlogs-id="${vlogsDataId}" style="
            padding: 8px 16px;
            background: var(--color-accent, #6B4F4F);
            color: #fff;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.2s ease;
          ">
            顯示 Vlog (${vlogs.length})
          </button>
        </div>
      `;
    } else {
      vlogsButtonHtml = `
        <div style="margin-top: 12px;" class="vlogs-preview-list">
          ${vlogs.map((vlog, idx) => `
            <div class="vlog-preview-item" data-vlog-id="${vlog.id}" style="
              padding: 8px 12px;
              margin-bottom: 8px;
              background: var(--bg-button, #F3F0EB);
              border: 1px solid var(--color-border, #D3C0A8);
              border-radius: 8px;
              cursor: pointer;
              transition: all 0.2s ease;
            ">
              <div style="font-size: 13px; color: var(--color-accent, #6B4F4F); font-weight: 500;">
                ${vlog.date || '未知日期'} - ${vlog.title || '無標題'}
              </div>
              <div style="font-size: 12px; color: var(--text-muted-light, #666); margin-top: 4px;">
                狀態: ${vlog.status} ${vlog.duration ? `(${Math.round(vlog.duration)}秒)` : ''}
              </div>
            </div>
          `).join('')}
        </div>
      `;
    }
  }
  
  messageDiv.innerHTML = `
    <div class="chat-avatar">${isUser ? '我' : 'AI'}</div>
    <div class="message-content">
      <div class="chat-bubble">${content.replace(/\n/g, '<br>')}${eventsButtonHtml}${recordingsButtonHtml}${diaryHtml}${vlogsButtonHtml}</div>
      <div class="chat-time">${now}</div>
    </div>
  `;
  
  chatMessages.appendChild(messageDiv);

  // 保存到瀏覽器（不自動清除）
  if (persist) {
    const messages = loadPersistedChat();
    messages.push({
      role: isUser ? 'user' : 'assistant',
      content: String(content ?? ''),
      ts: Date.now(),
    });
    savePersistedChat(messages);
  }
  
  // 綁定「顯示事件」按鈕事件
  if (events && events.length > 0) {
    const showEventsBtn = messageDiv.querySelector('.btn-show-events');
    if (showEventsBtn) {
      showEventsBtn.addEventListener('click', () => {
        showEventsModal(events);
      });
    }
  }
  
  // 綁定「顯示影片」按鈕事件
  if (recordings && recordings.length > 3) {
    const showRecordingsBtn = messageDiv.querySelector('.btn-show-recordings');
    if (showRecordingsBtn) {
      showRecordingsBtn.addEventListener('click', () => {
        showRecordingsModal(recordings);
      });
    }
  }
  
  // 綁定影片預覽項目點擊事件（3個或以下直接顯示的）
  if (recordings && recordings.length <= 3) {
    const previewItems = messageDiv.querySelectorAll('.recording-preview-item');
    previewItems.forEach((item, idx) => {
      item.addEventListener('click', () => {
        playRecording(recordings[idx]);
      });
    });
  }
  
  // 綁定「顯示 Vlog」按鈕事件
  if (vlogs && vlogs.length > 3) {
    const showVlogsBtn = messageDiv.querySelector('.btn-show-vlogs');
    if (showVlogsBtn) {
      showVlogsBtn.addEventListener('click', () => {
        showVlogsModal(vlogs);
      });
    }
  }
  
  // 綁定Vlog預覽項目點擊事件（3個或以下直接顯示的）
  if (vlogs && vlogs.length <= 3) {
    const previewItems = messageDiv.querySelectorAll('.vlog-preview-item');
    previewItems.forEach((item, idx) => {
      item.addEventListener('click', () => {
        playVlog(vlogs[idx]);
      });
    });
  }
  
  scrollChatToBottom();
}

// 顯示事件列表的懸浮視窗
function showEventsModal(events) {
  // 創建或獲取 modal
  let modal = document.getElementById('chatEventsModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'chatEventsModal';
    modal.className = 'chat-events-modal-overlay';
    modal.innerHTML = `
      <div class="chat-events-modal-container">
        <div class="chat-events-modal-header">
          <h3>查詢到的事件</h3>
          <button class="chat-events-modal-close">&times;</button>
        </div>
        <div class="chat-events-modal-body">
          <div class="chat-events-list"></div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    
    // 綁定關閉按鈕
    const closeBtn = modal.querySelector('.chat-events-modal-close');
    closeBtn.addEventListener('click', () => {
      modal.classList.remove('show');
    });
    
    // 點擊背景關閉
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        modal.classList.remove('show');
      }
    });
  }
  
  // 渲染事件列表
  const eventsList = modal.querySelector('.chat-events-list');
  eventsList.innerHTML = events.map(e => {
    // 後端會把事件時間轉成使用者時區；前端只顯示，不做時區計算
    const time = e.start_time || '未知時間';
    const duration = e.duration 
      ? `(${Math.round(e.duration)}秒)` 
      : '';
    
    // 物件標籤
    let objectsHtml = '';
    if (e.objects && Array.isArray(e.objects) && e.objects.length > 0) {
      objectsHtml = `
        <div class="event-objects">
          <strong>物件：</strong>
          <div class="objects-tags">
            ${e.objects.map(obj => `<span class="object-tag">${obj}</span>`).join('')}
          </div>
        </div>
      `;
    }
    
    return `
      <div class="event-item">
        <div class="event-time">${time} ${duration}</div>
        <div class="event-summary">${e.summary || '無描述'}</div>
        <div class="event-meta">
          ${e.scene ? `<span><strong>地點：</strong>${e.scene}</span>` : ''}
          ${e.action ? `<span><strong>動作：</strong>${e.action}</span>` : ''}
        </div>
        ${objectsHtml}
      </div>
    `;
  }).join('');
  
  // 顯示 modal
  modal.classList.add('show');
}

// 顯示影片列表的懸浮視窗
function showRecordingsModal(recordings) {
  // 創建或獲取 modal
  let modal = document.getElementById('chatRecordingsModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'chatRecordingsModal';
    modal.className = 'chat-recordings-modal-overlay';
    modal.innerHTML = `
      <div class="chat-recordings-modal-container">
        <div class="chat-recordings-modal-header">
          <h3>查詢到的影片</h3>
          <button class="chat-recordings-modal-close">&times;</button>
        </div>
        <div class="chat-recordings-modal-body">
          <div class="chat-recordings-list"></div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    
    // 綁定關閉按鈕
    const closeBtn = modal.querySelector('.chat-recordings-modal-close');
    closeBtn.addEventListener('click', () => {
      modal.classList.remove('show');
    });
    
    // 點擊背景關閉
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        modal.classList.remove('show');
      }
    });
  }
  
  // 渲染影片列表
  const recordingsList = modal.querySelector('.chat-recordings-list');
  recordingsList.innerHTML = recordings.map(rec => {
    return `
      <div class="recording-item" data-recording-id="${rec.id}" style="
        padding: 12px;
        margin-bottom: 12px;
        background: var(--bg-button, #F3F0EB);
        border: 1px solid var(--color-border, #D3C0A8);
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.2s ease;
      ">
        <div style="font-size: 14px; color: var(--color-accent, #6B4F4F); font-weight: 500; margin-bottom: 4px;">
          ${rec.time || '未知時間'} (${Math.round(rec.duration || 0)}秒)
        </div>
        <div style="font-size: 13px; color: var(--color-text, #2E2E2E); margin-bottom: 4px;">
          ${rec.summary || '無描述'}
        </div>
        ${rec.action ? `<div style="font-size: 12px; color: var(--text-muted-light, #666);">動作: ${rec.action}</div>` : ''}
        ${rec.scene ? `<div style="font-size: 12px; color: var(--text-muted-light, #666);">地點: ${rec.scene}</div>` : ''}
      </div>
    `;
  }).join('');
  
  // 綁定影片項目點擊事件
  const recordingItems = recordingsList.querySelectorAll('.recording-item');
  recordingItems.forEach((item) => {
    const recordingId = item.dataset.recordingId;
    const recording = recordings.find(r => r.id === recordingId);
    if (recording) {
      item.addEventListener('click', () => {
        playRecording(recording);
      });
    }
  });
  
  // 顯示 modal
  modal.classList.add('show');
}

// 播放影片的懸浮視窗
async function playRecording(recording) {
  // 創建或獲取播放 modal
  let modal = document.getElementById('chatVideoPlayerModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'chatVideoPlayerModal';
    modal.className = 'chat-video-player-modal-overlay';
    modal.innerHTML = `
      <div class="chat-video-player-modal-container">
        <div class="chat-video-player-modal-header">
          <h3>影片播放</h3>
          <button class="chat-video-player-modal-close">&times;</button>
        </div>
        <div class="chat-video-player-modal-body">
          <video id="chatVideoPlayer" controls style="width: 100%; max-height: 70vh; background: #000;"></video>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    
    // 綁定關閉按鈕
    const closeBtn = modal.querySelector('.chat-video-player-modal-close');
    closeBtn.addEventListener('click', () => {
      const video = document.getElementById('chatVideoPlayer');
      if (video) {
        video.pause();
        video.src = '';
      }
      modal.classList.remove('show');
    });
    
    // 點擊背景關閉
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        const video = document.getElementById('chatVideoPlayer');
        if (video) {
          video.pause();
          video.src = '';
        }
        modal.classList.remove('show');
      }
    });
  }
  
  // 獲取影片 URL
  try {
    const video = document.getElementById('chatVideoPlayer');
    const bodyDiv = modal.querySelector('.chat-video-player-modal-body');
    if (!video || !bodyDiv) return;
    
    // 顯示載入中
    video.style.display = 'none';
    if (!bodyDiv.querySelector('.loading')) {
      const loadingDiv = document.createElement('div');
      loadingDiv.className = 'loading';
      loadingDiv.style.cssText = 'text-align: center; padding: 40px; color: #fff;';
      loadingDiv.textContent = '載入影片中...';
      bodyDiv.appendChild(loadingDiv);
    }
    
    // 獲取影片 URL
    const urlResponse = await ApiClient.recordings.getUrl(recording.id, 3600);
    const videoUrl = urlResponse.url;
    
    // 移除載入提示
    const loadingDiv = bodyDiv.querySelector('.loading');
    if (loadingDiv) {
      loadingDiv.remove();
    }
    
    // 設置影片源
    video.src = videoUrl;
    video.style.display = 'block';
    
    // 顯示 modal
    modal.classList.add('show');
  } catch (error) {
    console.error('獲取影片 URL 失敗:', error);
    const bodyDiv = modal.querySelector('.chat-video-player-modal-body');
    if (bodyDiv) {
      const loadingDiv = bodyDiv.querySelector('.loading');
      if (loadingDiv) {
        loadingDiv.textContent = '無法載入影片，請稍後再試';
        loadingDiv.style.color = '#ff6b6b';
      }
    }
  }
}

// 顯示 Vlog 列表的懸浮視窗
function showVlogsModal(vlogs) {
  // 創建或獲取 modal
  let modal = document.getElementById('chatVlogsModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'chatVlogsModal';
    modal.className = 'chat-vlogs-modal-overlay';
    modal.innerHTML = `
      <div class="chat-vlogs-modal-container">
        <div class="chat-vlogs-modal-header">
          <h3>查詢到的 Vlog</h3>
          <button class="chat-vlogs-modal-close">&times;</button>
        </div>
        <div class="chat-vlogs-modal-body">
          <div class="chat-vlogs-list"></div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    
    // 綁定關閉按鈕
    const closeBtn = modal.querySelector('.chat-vlogs-modal-close');
    closeBtn.addEventListener('click', () => {
      modal.classList.remove('show');
    });
    
    // 點擊背景關閉
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        modal.classList.remove('show');
      }
    });
  }
  
  // 渲染 Vlog 列表
  const vlogsList = modal.querySelector('.chat-vlogs-list');
  vlogsList.innerHTML = vlogs.map(vlog => {
    return `
      <div class="vlog-item" data-vlog-id="${vlog.id}" style="
        padding: 12px;
        margin-bottom: 12px;
        background: var(--bg-button, #F3F0EB);
        border: 1px solid var(--color-border, #D3C0A8);
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.2s ease;
      ">
        <div style="font-size: 14px; color: var(--color-accent, #6B4F4F); font-weight: 500; margin-bottom: 4px;">
          ${vlog.date || '未知日期'} - ${vlog.title || '無標題'}
        </div>
        <div style="font-size: 13px; color: var(--color-text, #2E2E2E); margin-bottom: 4px;">
          狀態: ${vlog.status}
        </div>
        ${vlog.duration ? `<div style="font-size: 12px; color: var(--text-muted-light, #666);">時長: ${Math.round(vlog.duration)}秒</div>` : ''}
      </div>
    `;
  }).join('');
  
  // 綁定 Vlog 項目點擊事件
  const vlogItems = vlogsList.querySelectorAll('.vlog-item');
  vlogItems.forEach((item) => {
    const vlogId = item.dataset.vlogId;
    const vlog = vlogs.find(v => v.id === vlogId);
    if (vlog) {
      item.addEventListener('click', () => {
        playVlog(vlog);
      });
    }
  });
  
  // 顯示 modal
  modal.classList.add('show');
}

// 播放 Vlog 的懸浮視窗
async function playVlog(vlog) {
  // 創建或獲取播放 modal
  let modal = document.getElementById('chatVlogPlayerModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'chatVlogPlayerModal';
    modal.className = 'chat-vlog-player-modal-overlay';
    modal.innerHTML = `
      <div class="chat-vlog-player-modal-container">
        <div class="chat-vlog-player-modal-header">
          <h3>Vlog 播放</h3>
          <button class="chat-vlog-player-modal-close">&times;</button>
        </div>
        <div class="chat-vlog-player-modal-body">
          <video id="chatVlogPlayer" controls style="width: 100%; max-height: 70vh; background: #000;"></video>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    
    // 綁定關閉按鈕
    const closeBtn = modal.querySelector('.chat-vlog-player-modal-close');
    closeBtn.addEventListener('click', () => {
      const video = document.getElementById('chatVlogPlayer');
      if (video) {
        video.pause();
        video.src = '';
      }
      modal.classList.remove('show');
    });
    
    // 點擊背景關閉
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        const video = document.getElementById('chatVlogPlayer');
        if (video) {
          video.pause();
          video.src = '';
        }
        modal.classList.remove('show');
      }
    });
  }
  
  // 獲取 Vlog URL
  try {
    const video = document.getElementById('chatVlogPlayer');
    const bodyDiv = modal.querySelector('.chat-vlog-player-modal-body');
    if (!video || !bodyDiv) return;
    
    // 顯示載入中
    video.style.display = 'none';
    if (!bodyDiv.querySelector('.loading')) {
      const loadingDiv = document.createElement('div');
      loadingDiv.className = 'loading';
      loadingDiv.style.cssText = 'text-align: center; padding: 40px; color: #fff;';
      loadingDiv.textContent = '載入 Vlog 中...';
      bodyDiv.appendChild(loadingDiv);
    }
    
    // 獲取 Vlog URL
    const urlResponse = await ApiClient.vlogs.getUrl(vlog.id, 3600);
    const videoUrl = urlResponse.url;
    
    // 移除載入提示
    const loadingDiv = bodyDiv.querySelector('.loading');
    if (loadingDiv) {
      loadingDiv.remove();
    }
    
    // 設置影片源
    video.src = videoUrl;
    video.style.display = 'block';
    
    // 顯示 modal
    modal.classList.add('show');
  } catch (error) {
    console.error('獲取 Vlog URL 失敗:', error);
    const bodyDiv = modal.querySelector('.chat-vlog-player-modal-body');
    if (bodyDiv) {
      const loadingDiv = bodyDiv.querySelector('.loading');
      if (loadingDiv) {
        loadingDiv.textContent = '無法載入 Vlog，請稍後再試';
        loadingDiv.style.color = '#ff6b6b';
      }
    }
  }
}

// 發送訊息
async function sendChatMessage() {
  const query = chatInput.value.trim();
  
  if (!query) {
    return;
  }
  
  // 檢查登入狀態
  if (!AuthService.isLoggedIn()) {
    alert('請先登入');
    window.location.href = '/auth.html';
    return;
  }
  
  const hadFocusBeforeSend = document.activeElement === chatInput;

  // 顯示使用者訊息（並持久化）
  addChatMessage(query, true, null, null, null, null, { persist: true });
  
  // 添加到對話歷史
  chatHistory.push({
    role: 'user',
    content: query
  });
  
  // 限制歷史長度（最多保留 10 條，API 會自動處理）
  if (chatHistory.length > 20) {
    chatHistory = chatHistory.slice(-20);
  }
  
  chatInput.value = '';
  chatInput.style.height = 'auto';
  
  // 顯示載入中
  const loadingId = Date.now();
  const loadingDiv = document.createElement('div');
  loadingDiv.id = `loading-${loadingId}`;
  loadingDiv.className = 'chat-message ai';
  loadingDiv.innerHTML = `
    <div class="chat-avatar">AI</div>
    <div class="message-content">
      <div class="chat-bubble">
        <span class="loading">思考中...</span>
      </div>
    </div>
  `;
  chatMessages.appendChild(loadingDiv);
  scrollChatToBottom();
  
  // 禁用輸入和按鈕
  chatInput.disabled = true;
  chatSend.disabled = true;
  
  try {
    const dateFrom = chatDateFrom.value || null;
    const dateTo = chatDateTo.value || null;
    
    // 構建請求（history 格式：{ role: 'user'|'assistant', content: string }）
    const response = await ApiClient.chat.send({
      message: query,
      date_from: dateFrom,
      date_to: dateTo,
      history: chatHistory.slice(0, -1) // 不包含剛剛添加的用戶訊息
    });
    
    // 移除載入訊息
    document.getElementById(`loading-${loadingId}`)?.remove();
    
    // 顯示 AI 回答
    const answer = response.message || '查詢完成';
    const events = response.events || [];
    const recordings = response.recordings || [];
    const diaries = response.diaries || [];
    const vlogs = response.vlogs || [];
    
    // 添加 AI 回覆到對話歷史
    chatHistory.push({
      role: 'assistant',
      content: answer
    });
    
    addChatMessage(answer, false, events, recordings, diaries, vlogs, { persist: true });
    
    // 如果有函數調用，可以在控制台輸出（用於調試）
    if (response.function_calls && response.function_calls.length > 0) {
      console.log('[Function Calls]', response.function_calls);
    }
    
  } catch (err) {
    document.getElementById(`loading-${loadingId}`)?.remove();
    
    // 如果是 401 錯誤，提示用戶重新登入
    if (err.message.includes('401') || err.message.includes('登入')) {
      addChatMessage('❌ 您的登入已過期，請重新登入後再試', false, null, null, null, null, { persist: true });
      setTimeout(() => {
        window.location.href = '/auth.html';
      }, 1500);
    } else {
      addChatMessage(`❌ ${err.message || '查詢失敗，請稍後再試'}`, false, null, null, null, null, { persist: true });
    }
    
    // 移除失敗的用戶訊息（保持歷史一致性）
    chatHistory.pop();
  } finally {
    // 恢復輸入和按鈕
    chatInput.disabled = false;
    chatSend.disabled = false;
    // 不要強制 focus（避免進頁/操作後自動彈鍵盤）；只有原本就在輸入時才回復 focus
    if (hadFocusBeforeSend) {
      try { chatInput.focus({ preventScroll: true }); } catch { chatInput.focus(); }
    }
  }
}

// 清除對話
function clearChatHistory() {
  if (!confirm('確定要清除所有對話記錄嗎？')) return;
  
  chatHistory = [];
  clearPersistedChat();
  
  // 保留歡迎訊息
  renderWelcomeMessage();
  
  scrollChatToBottom();
}

// 自動調整 textarea 高度
function autoResizeTextarea() {
  if (!chatInput) return;
  
  chatInput.style.height = 'auto';
  const newHeight = Math.min(chatInput.scrollHeight, 120);
  chatInput.style.height = `${newHeight}px`;
}

// 監聽輸入框變化
if (chatInput) {
  chatInput.addEventListener('input', autoResizeTextarea);
  
  // Enter 發送，Shift+Enter 換行
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage();
    }
  });
}

// 綁定事件
if (chatSend) {
  chatSend.addEventListener('click', sendChatMessage);
}

if (clearChat) {
  clearChat.addEventListener('click', clearChatHistory);
}

// 工具按鈕展開/收起
if (chatToolsBtn && chatToolsPanel) {
  chatToolsBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const isExpanded = chatToolsBtn.getAttribute('aria-expanded') === 'true';
    
    if (isExpanded) {
      // 收起
      chatToolsBtn.setAttribute('aria-expanded', 'false');
      chatToolsPanel.classList.remove('active');
    } else {
      // 展開
      chatToolsBtn.setAttribute('aria-expanded', 'true');
      chatToolsPanel.classList.add('active');
    }
  });

  // 點擊外部關閉面板
  document.addEventListener('click', (e) => {
    if (chatToolsPanel && chatToolsPanel.classList.contains('active')) {
      if (!chatToolsPanel.contains(e.target) && !chatToolsBtn.contains(e.target)) {
        chatToolsBtn.setAttribute('aria-expanded', 'false');
        chatToolsPanel.classList.remove('active');
      }
    }
  });
}

// 監聽聊天容器變化，自動滾動
if (chatMessages) {
  const observer = new MutationObserver(() => {
    scrollChatToBottom();
  });
  observer.observe(chatMessages, { 
    childList: true, 
    subtree: false 
  });
}

// 視窗尺寸變化時滾動到底部
window.addEventListener('resize', () => {
  setTimeout(scrollChatToBottom, 50);
});

// 處理手機鍵盤彈出：
// - chat-header 不應被往上擠
// - chat-messages 不整塊上移，而是「可視高度縮小」並保持顯示最新訊息
// - 只讓 chat-input-area 浮在鍵盤上方
function handleMobileKeyboard() {
  if (!(window.innerWidth <= 768 && chatInput)) return;
  const root = document.documentElement;
  const inputArea = document.querySelector('.chat-input-area');
  const mobileNav = document.querySelector('.mobile-nav');
  const chatContainer = document.querySelector('.chat-container');
  const chatHeader = document.querySelector('.chat-header');
  const scrollEl = document.scrollingElement || document.documentElement;
  let keyboardOpen = false;
  const initialInnerHeight = window.innerHeight;
  let focusLockRequested = false;

  // 在聊天頁面手機模式下，避免整頁滾動（只允許 chatMessages 滾動）
  document.body.style.overflow = 'hidden';
  document.documentElement.style.overflow = 'hidden';

  function updateVisualViewportHeightVar() {
    // 讓聊天頁容器高度跟著「可視 viewport」縮放（鍵盤出現/收起會變）
    if (window.visualViewport && window.visualViewport.height) {
      root.style.setProperty('--chat-vv-height', `${Math.round(window.visualViewport.height)}px`);
    } else {
      root.style.setProperty('--chat-vv-height', `${window.innerHeight}px`);
    }
  }

  function computeKeyboardInset() {
    // iOS/Android 新版瀏覽器：VisualViewport 更準
    if (window.visualViewport) {
      const vv = window.visualViewport;
      // 注意：vv.offsetTop 會隨「可視視窗捲動/橡皮筋」變動，會造成輸入列跟著飄。
      // 這裡只用高度差估算鍵盤佔用，避免 scroll 時抖動。
      const raw = Math.max(0, window.innerHeight - vv.height);
      const inset = Math.round(raw);
      // 小於門檻視為 0，避免位址列顯示/隱藏造成誤判「鍵盤開啟」
      return inset >= 50 ? inset : 0;
    }
    return 0;
  }

  function getNavHeight() {
    if (mobileNav && mobileNav.offsetParent !== null) return mobileNav.offsetHeight;
    return 80;
  }

  function updateLayoutVars() {
    if (!inputArea) return;
    updateVisualViewportHeightVar();
    const inputH = inputArea.offsetHeight || 80;
    const kb = computeKeyboardInset();
    root.style.setProperty('--chat-keyboard-inset', `${kb}px`);
    root.style.setProperty('--chat-input-area-height', `${inputH}px`);
    if (chatHeader) {
      root.style.setProperty('--chat-header-height', `${chatHeader.offsetHeight || 64}px`);
    }

    // 鍵盤彈出時：隱藏底部導覽列，讓輸入列直接貼齊鍵盤（並同步讓聊天區縮短）
    // ✅ 修正：keyboard-open 只以「kb>0 或 input focus」判定，避免收鍵盤後仍被誤判為開啟
    const isFocused = document.activeElement === chatInput;
    const isKeyboardOpen = (kb > 0) || isFocused;
    document.body.classList.toggle('keyboard-open', isKeyboardOpen);

    // ✅ 終極修正：不要用 html/body position:fixed（不同瀏覽器副作用大）
    // 改成：鍵盤開啟期間「強制 window scroll 在 0」，阻止 scroll-into-view 把 header/整頁推上去
    keyboardOpen = isKeyboardOpen;
    if (keyboardOpen) requestAnimationFrame(() => window.scrollTo(0, 0));

    // 讓訊息區域在鍵盤/輸入框變動後保持最新訊息可見
    requestAnimationFrame(scrollChatToBottom);
  }

  updateLayoutVars();
  window.addEventListener('resize', () => setTimeout(updateLayoutVars, 50));
  window.addEventListener('orientationchange', () => setTimeout(updateLayoutVars, 100));
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', () => setTimeout(updateLayoutVars, 0));
    // 不監聽 visualViewport.scroll：它會在使用者滑動/橡皮筋時頻繁觸發，造成輸入列「跟著飄」
  }

  // 使用者點輸入框才會彈鍵盤：在 focus 當下立刻鎖定（比 resize 更早），避免 header/整頁先被頂起
  chatInput.addEventListener('focus', () => {
    focusLockRequested = true;
    window.scrollTo(0, 0);
    updateLayoutVars();
  });
  // blur 時給瀏覽器一點時間收鍵盤/恢復 viewport，再判定一次，確保 nav 會回來
  chatInput.addEventListener('blur', () => {
    focusLockRequested = false;
    setTimeout(updateLayoutVars, 80);
  });

  // 只要鍵盤開啟，就禁止 window scroll（瀏覽器強制 scroll-into-view 也會被拉回）
  const enforceTop = () => {
    if (!keyboardOpen) return;
    if ((window.scrollY || scrollEl.scrollTop || 0) !== 0) window.scrollTo(0, 0);
  };
  window.addEventListener('scroll', enforceTop, { passive: true });
  if (window.visualViewport) {
    window.visualViewport.addEventListener('scroll', enforceTop, { passive: true });
  }

  // iOS/Safari 常見：即使外層 overflow hidden，仍可能發生「滾動鏈/橡皮筋」把整頁拖動，
  // 導致 fixed 的 nav/input/header 被一起帶走再回彈。這裡強制只允許 chatMessages 區域的 touchmove。
  const allowTouchMove = (el) => {
    if (!el) return false;
    if (chatMessages && chatMessages.contains(el)) return true;
    if (inputArea && inputArea.contains(el)) return true;
    if (chatContainer && chatContainer.contains(el) && el.tagName === 'TEXTAREA') return true;
    return false;
  };
  const preventBodyScroll = (e) => {
    if (allowTouchMove(e.target)) return;
    e.preventDefault();
  };
  // 只在聊天頁手機模式啟用（passive:false 才能 preventDefault）
  document.addEventListener('touchmove', preventBodyScroll, { passive: false });
}

// 初始化
document.addEventListener('DOMContentLoaded', async () => {
  // 標記聊天頁（給 CSS 用）
  document.body.classList.add('page-chat');

  // 檢查登入狀態
  if (!AuthService.isLoggedIn()) {
    window.location.href = '/auth.html';
    return;
  }
  
  // 嘗試獲取當前用戶資訊
  try {
    await ApiClient.getCurrentUser();
  } catch (err) {
    console.warn('無法獲取用戶資訊:', err);
    window.location.href = '/auth.html';
    return;
  }
  
  // 處理手機鍵盤
  handleMobileKeyboard();

  // 載入瀏覽器保存的對話（不要自動 focus，避免進頁就彈鍵盤）
  const persisted = loadPersistedChat();
  if (persisted.length > 0) {
    // 先清空預設歡迎訊息
    chatMessages.innerHTML = '';
    persisted.forEach((m) => {
      const role = m?.role === 'user' ? 'user' : 'assistant';
      addChatMessage(m?.content || '', role === 'user', null, null, null, null, { persist: false });
    });
  } else {
    renderWelcomeMessage();
  }

  // 讓 API 的 history 也有同樣的上下文（只保留最近 20 則）
  chatHistory = persisted
    .filter(m => m && (m.role === 'user' || m.role === 'assistant'))
    .slice(-20)
    .map(m => ({ role: m.role, content: String(m.content ?? '') }));

  scrollChatToBottom();
});

