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

// 工具函數
function scrollChatToBottom() {
  if (!chatMessages) return;
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function addChatMessage(content, isUser = false, events = null) {
  if (!chatMessages) return;
  
  const messageDiv = document.createElement('div');
  messageDiv.className = `chat-message ${isUser ? 'user' : 'ai'}`;
  
  const now = new Date().toLocaleTimeString('zh-TW', { 
    hour: '2-digit', 
    minute: '2-digit' 
  });
  
  let eventsHtml = '';
  if (events && events.length > 0) {
    eventsHtml = '<div style="margin-top:12px">' + events.map(e => {
      const time = e.start_time 
        ? new Date(e.start_time).toLocaleString('zh-TW') 
        : '未知時間';
      const duration = e.duration 
        ? `(${Math.round(e.duration)}秒)` 
        : '';
      const objects = e.objects && e.objects.length > 0 
        ? `<br>物件: ${e.objects.join(', ')}` 
        : '';
      return `
        <div class="event-item">
          <div class="event-time">${time} ${duration}</div>
          <div class="event-summary">${e.summary || '無描述'}</div>
          <div class="event-meta">
            ${e.scene ? `地點: ${e.scene}` : ''}
            ${e.action ? ` | 動作: ${e.action}` : ''}${objects}
          </div>
        </div>
      `;
    }).join('') + '</div>';
  }
  
  messageDiv.innerHTML = `
    <div class="chat-avatar">${isUser ? '我' : 'AI'}</div>
    <div class="message-content">
      <div class="chat-bubble">${content.replace(/\n/g, '<br>')}${eventsHtml}</div>
      <div class="chat-time">${now}</div>
    </div>
  `;
  
  chatMessages.appendChild(messageDiv);
  scrollChatToBottom();
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
  
  // 顯示使用者訊息
  addChatMessage(query, true);
  
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
    
    // 添加 AI 回覆到對話歷史
    chatHistory.push({
      role: 'assistant',
      content: answer
    });
    
    addChatMessage(answer, false, events);
    
    // 如果有函數調用，可以在控制台輸出（用於調試）
    if (response.function_calls && response.function_calls.length > 0) {
      console.log('[Function Calls]', response.function_calls);
    }
    
  } catch (err) {
    document.getElementById(`loading-${loadingId}`)?.remove();
    
    // 如果是 401 錯誤，提示用戶重新登入
    if (err.message.includes('401') || err.message.includes('登入')) {
      addChatMessage('❌ 您的登入已過期，請重新登入後再試', false);
      setTimeout(() => {
        window.location.href = '/auth.html';
      }, 1500);
    } else {
      addChatMessage(`❌ ${err.message || '查詢失敗，請稍後再試'}`, false);
    }
    
    // 移除失敗的用戶訊息（保持歷史一致性）
    chatHistory.pop();
  } finally {
    // 恢復輸入和按鈕
    chatInput.disabled = false;
    chatSend.disabled = false;
    chatInput.focus();
  }
}

// 清除對話
function clearChatHistory() {
  if (!confirm('確定要清除所有對話記錄嗎？')) return;
  
  chatHistory = [];
  
  // 保留歡迎訊息
  if (chatMessages) {
    chatMessages.innerHTML = `
      <div class="chat-message ai">
        <div class="chat-avatar">AI</div>
        <div class="message-content">
          <div class="chat-bubble">
            👋 您好！我是您的 AI 助手。<br><br>
            您可以問我：<br>
            • "我今天幾點吃早餐？"<br>
            • "我今天去了哪裡？"<br>
            • "我在客廳做了什麼？"<br>
            • "我今天有散步嗎？"
          </div>
          <div class="chat-time">AI 助手</div>
        </div>
      </div>
    `;
  }
  
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

// 處理手機鍵盤彈出 - 只推動輸入區域，不推動整個頁面
function handleMobileKeyboard() {
  if (window.innerWidth <= 768 && chatInput) {
    const inputArea = document.querySelector('.chat-input-area');
    const mobileNav = document.querySelector('.mobile-nav');
    const mainContent = document.querySelector('.main-content');
    let initialViewportHeight = window.innerHeight;
    let keyboardHeight = 0;
    let isKeyboardOpen = false;

    // 防止整個頁面滾動
    function preventPageScroll(e) {
      // 如果正在輸入，阻止預設的滾動行為
      if (document.activeElement === chatInput || document.activeElement === chatInput) {
        e.preventDefault();
        e.stopPropagation();
        return false;
      }
    }

    // 計算鍵盤高度
    function calculateKeyboardHeight() {
      const currentViewportHeight = window.innerHeight;
      const heightDiff = initialViewportHeight - currentViewportHeight;
      // 如果視口高度減少超過 150px，認為鍵盤彈出
      if (heightDiff > 150) {
        keyboardHeight = heightDiff;
        return true;
      }
      return false;
    }

    // 獲取底部導覽列高度（動態計算）
    function getBottomNavHeight() {
      if (mobileNav && mobileNav.offsetParent !== null) {
        return mobileNav.offsetHeight;
      }
      return 80; // 預設高度
    }

    // 獲取安全區域高度
    function getSafeAreaBottom() {
      const safeArea = getComputedStyle(document.documentElement).getPropertyValue('--safe-area-inset-bottom');
      if (safeArea) {
        return parseInt(safeArea) || 0;
      }
      // 嘗試從 env() 獲取
      const envSafeArea = getComputedStyle(document.documentElement).getPropertyValue('env(safe-area-inset-bottom)');
      return parseInt(envSafeArea) || 0;
    }

    // 更新輸入區域位置
    function updateInputAreaPosition() {
      if (!inputArea) return;
      
      const navHeight = getBottomNavHeight();
      const safeAreaBottom = getSafeAreaBottom();
      
      if (isKeyboardOpen) {
        // 鍵盤彈出：只推動輸入區域向上
        inputArea.style.bottom = `${keyboardHeight + navHeight + safeAreaBottom}px`;
        inputArea.style.transform = 'translateY(0)';
        
        // 調整聊天訊息區域的 padding，確保輸入框不被遮擋
        if (chatMessages) {
          const inputHeight = inputArea.offsetHeight;
          chatMessages.style.paddingBottom = `${inputHeight + keyboardHeight + 20}px`;
        }
      } else {
        // 鍵盤收起：恢復輸入區域位置
        inputArea.style.bottom = `${navHeight + safeAreaBottom}px`;
        inputArea.style.transform = 'translateY(0)';
        
        // 恢復聊天訊息區域的 padding
        if (chatMessages) {
          chatMessages.style.paddingBottom = '';
        }
      }
    }

    // 監聽視窗大小變化（處理鍵盤彈出/收起）
    let resizeTimer;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        const wasKeyboardOpen = isKeyboardOpen;
        isKeyboardOpen = calculateKeyboardHeight();
        
        if (wasKeyboardOpen !== isKeyboardOpen) {
          updateInputAreaPosition();
          
          // 防止頁面滾動
          if (isKeyboardOpen) {
            // 鍵盤彈出時，阻止頁面滾動 - 使用 class
            if (mainContent) {
              mainContent.classList.add('keyboard-open');
              // 確保主內容區域不會被鍵盤推動
              mainContent.style.top = '0';
              mainContent.style.height = `${window.innerHeight}px`;
            }
            // 防止整個頁面滾動
            document.body.style.overflow = 'hidden';
            document.documentElement.style.overflow = 'hidden';
          } else {
            // 鍵盤收起時，恢復頁面滾動
            if (mainContent) {
              mainContent.classList.remove('keyboard-open');
              mainContent.style.top = '';
              mainContent.style.height = '';
            }
            document.body.style.overflow = '';
            document.documentElement.style.overflow = '';
            
            keyboardHeight = 0;
            initialViewportHeight = window.innerHeight;
          }
        }
        
        // 滾動到底部
        scrollChatToBottom();
      }, 100);
    });

    // 監聽輸入框聚焦事件
    chatInput.addEventListener('focus', (e) => {
      // 記錄初始視口高度
      initialViewportHeight = window.innerHeight;
      
      // 防止頁面自動滾動
      e.preventDefault();
      
      // 延遲一下，等待鍵盤彈出
      setTimeout(() => {
        isKeyboardOpen = calculateKeyboardHeight();
        
        if (isKeyboardOpen) {
          updateInputAreaPosition();
          
          // 防止頁面滾動 - 使用 class
          if (mainContent) {
            mainContent.classList.add('keyboard-open');
            mainContent.style.top = '0';
            mainContent.style.height = `${window.innerHeight}px`;
          }
          // 防止整個頁面滾動
          document.body.style.overflow = 'hidden';
          document.documentElement.style.overflow = 'hidden';
        }
        
        // 滾動到底部
        scrollChatToBottom();
      }, 300);
    }, { passive: false });

    // 監聽輸入框失焦事件
    chatInput.addEventListener('blur', () => {
      isKeyboardOpen = false;
      keyboardHeight = 0;
      
      // 恢復輸入區域位置
      updateInputAreaPosition();
      
      // 恢復頁面滾動
      if (mainContent) {
        mainContent.classList.remove('keyboard-open');
        mainContent.style.top = '';
        mainContent.style.height = '';
      }
      document.body.style.overflow = '';
      document.documentElement.style.overflow = '';
      
      // 等待視口恢復
      setTimeout(() => {
        initialViewportHeight = window.innerHeight;
      }, 300);
    });

    // 防止觸摸滾動導致整個頁面上移
    let touchStartY = 0;
    let touchEndY = 0;
    
    document.addEventListener('touchstart', (e) => {
      if (document.activeElement === chatInput) {
        touchStartY = e.touches[0].clientY;
      }
    }, { passive: true });

    document.addEventListener('touchmove', (e) => {
      if (document.activeElement === chatInput && isKeyboardOpen) {
        // 如果正在輸入且鍵盤打開，阻止頁面滾動
        e.preventDefault();
      }
    }, { passive: false });

    // 初始化視口高度
    initialViewportHeight = window.innerHeight;
    
    // 初始化輸入區域位置
    updateInputAreaPosition();
  }
}

// 修復 iPad Pro 底部白邊 - 動態計算視口高度並確保貼齊底部
function fixViewportHeight() {
  // 設置 CSS 變數用於安全區域
  // 嘗試從 CSS env() 獲取安全區域
  const computedStyle = getComputedStyle(document.documentElement);
  let safeAreaBottom = 0;
  
  // 方法1: 從 CSS 變數獲取
  const cssVar = computedStyle.getPropertyValue('--safe-area-inset-bottom');
  if (cssVar) {
    safeAreaBottom = parseInt(cssVar) || 0;
  } else {
    // 方法2: 計算視口差異（適用於有瀏覽器 UI 的情況）
    const viewportHeight = window.innerHeight;
    const screenHeight = window.screen.height;
    // 如果視口高度明顯小於螢幕高度，可能有安全區域
    if (screenHeight > viewportHeight && window.innerWidth <= 768) {
      safeAreaBottom = Math.max(0, screenHeight - viewportHeight - 100); // 減去可能的瀏覽器 UI
    }
  }
  
  document.documentElement.style.setProperty('--safe-area-inset-bottom', `${safeAreaBottom}px`);
  
  // 計算實際視口高度（考慮安全區域）
  const vh = window.innerHeight * 0.01;
  document.documentElement.style.setProperty('--vh', `${vh}px`);
  
  // 確保底部導覽列貼齊最底端
  const mobileNav = document.querySelector('.mobile-nav');
  if (mobileNav && window.innerWidth <= 768) {
    // 動態計算並設置底部導覽列高度
    const navHeight = 80; // 基礎高度
    const totalHeight = navHeight + safeAreaBottom;
    mobileNav.style.height = `${totalHeight}px`;
    mobileNav.style.minHeight = `${navHeight}px`;
    mobileNav.style.paddingBottom = `${Math.max(8, safeAreaBottom)}px`;
    mobileNav.style.bottom = '0'; // 確保貼齊最底端
    mobileNav.style.marginBottom = '0'; // 確保沒有間隙
  }
  
  // 確保輸入區域貼齊底部導覽列
  const inputArea = document.querySelector('.chat-input-area');
  if (inputArea && window.innerWidth <= 768) {
    const navHeight = mobileNav ? mobileNav.offsetHeight : 80;
    const safeArea = getComputedStyle(document.documentElement).getPropertyValue('--safe-area-inset-bottom');
    const safeAreaValue = parseInt(safeArea) || 0;
    inputArea.style.bottom = `${navHeight + safeAreaValue}px`;
  }
}

// 初始化
document.addEventListener('DOMContentLoaded', async () => {
  // 修復 iPad Pro 底部白邊
  fixViewportHeight();
  window.addEventListener('resize', fixViewportHeight);
  window.addEventListener('orientationchange', () => {
    setTimeout(fixViewportHeight, 100);
  });

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
  
  // 聚焦輸入框
  if (chatInput) {
    chatInput.focus();
  }
  
  // 滾動到底部
  scrollChatToBottom();
});

