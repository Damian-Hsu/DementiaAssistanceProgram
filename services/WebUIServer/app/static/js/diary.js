import { ApiClient } from "/static/js/APIClient.js";
import { AuthService } from "/static/js/AuthService.js";

window.ApiClient = ApiClient;
window.AuthService = AuthService;

// ====== 工具函數 ======
function el(id) { return document.getElementById(id); }

// ====== 狀態管理 ======
let currentDate = new Date(); // 當前選擇的日期（右頁）
let leftPageDate = null; // 左頁日期
let rightPageDate = null; // 右頁日期
let diaryAutoRefreshInterval = null; // 自動刷新定時器
let lastEventsHash = {}; // 記錄每個日期的上次事件哈希 { dateStr: hash }
let userSettings = null; // 用戶設定

// ====== 初始化 ======
document.addEventListener("DOMContentLoaded", async () => {
  // 權限檢查
  if (!(window.AuthService && AuthService.isLoggedIn && AuthService.isLoggedIn())) {
    window.location.href = "/auth.html";
    return;
  }

  try {
    await ApiClient.getCurrentUser();
  } catch (e) {
    console.warn(e);
    window.location.href = "/auth.html";
    return;
  }

  // 初始化日期選擇器為今天
  const today = new Date();
  const dateInput = el("diaryDate");
  if (dateInput) {
    dateInput.value = formatDateForInput(today);
    currentDate = today;
  }

  // 初始化頁面
  await initializePages();

  // 綁定事件
  bindEvents();
  
  // 載入用戶設定並啟動自動刷新
  await loadUserSettings();
  startDiaryAutoRefresh();
});

// ====== 事件綁定 ======
function bindEvents() {
  // 日期選擇器變更
  el("diaryDate")?.addEventListener("change", async (e) => {
    const selectedDate = new Date(e.target.value);
    currentDate = selectedDate;
    await loadDiaryPages();
  });

  // 左側翻頁區域（上一頁）
  el("prevPageArea")?.addEventListener("click", async (e) => {
    e.stopPropagation();
    currentDate = new Date(currentDate);
    // 根據螢幕寬度決定翻頁步長：雙頁模式翻兩頁，單頁模式翻一頁
    const isSinglePage = window.innerWidth <= 1150;
    const step = isSinglePage ? 1 : 2;
    currentDate.setDate(currentDate.getDate() - step);
    updateDateInput();
    await loadDiaryPages();
  });

  // 右側翻頁區域（下一頁）
  el("nextPageArea")?.addEventListener("click", async (e) => {
    e.stopPropagation();
    currentDate = new Date(currentDate);
    // 根據螢幕寬度決定翻頁步長：雙頁模式翻兩頁，單頁模式翻一頁
    const isSinglePage = window.innerWidth <= 1150;
    const step = isSinglePage ? 1 : 2;
    currentDate.setDate(currentDate.getDate() + step);
    updateDateInput();
    await loadDiaryPages();
  });

  // 移除點擊頁面翻頁功能
  // 左頁和右頁不再響應點擊事件來切換日期

  // 左頁刷新按鈕
  el("leftPageRefreshBtn")?.addEventListener("click", async (e) => {
    e.stopPropagation();
    // TODO: 未來實現刷新功能
    await refreshDiaryPage(leftPageDate, "leftPageContent");
  });

  // 右頁刷新按鈕
  el("rightPageRefreshBtn")?.addEventListener("click", async (e) => {
    e.stopPropagation();
    // TODO: 未來實現刷新功能
    await refreshDiaryPage(rightPageDate, "rightPageContent");
  });
}

// ====== 初始化頁面 ======
async function initializePages() {
  await loadDiaryPages();
}

// ====== 載入日記頁面 ======
async function loadDiaryPages() {
  // 計算左右頁日期
  // 右頁顯示當前選擇的日期
  rightPageDate = new Date(currentDate);
  
  // 左頁顯示前一天
  leftPageDate = new Date(currentDate);
  leftPageDate.setDate(leftPageDate.getDate() - 1);

  // 更新日期顯示
  updateDateDisplay();

  // 載入日記內容
  await loadDiaryContent(leftPageDate, "leftPageContent");
  await loadDiaryContent(rightPageDate, "rightPageContent");
}

// ====== 刷新日記頁面 ======
async function refreshDiaryPage(date, containerId) {
  if (!date) return;
  
  const container = el(containerId);
  if (!container) return;
  
  // 顯示載入中
  container.innerHTML = '<p class="diary-placeholder">刷新中...</p>';
  
  try {
    const dateStr = formatDate(date);
    // 強制刷新日記
    const diaryData = await ApiClient.chat.generateDiarySummary(dateStr, true);
    
    // 檢查是否有事件
    if (diaryData.events_count === 0) {
      container.innerHTML = `
        <div class="diary-content">
          <p class="diary-placeholder">本日無事件，無法提供日記喔~</p>
        </div>
      `;
      return;
    }
    
    // 如果有內容，顯示日記內容
    if (diaryData.content) {
      // 將換行符轉換為段落
      const formattedContent = diaryData.content
        .split('\n')
        .map(line => `<p>${line || '<br>'}</p>`)
        .join('');
      
      container.innerHTML = `
        <div class="diary-content">
          ${formattedContent}
        </div>
      `;
    } else {
      container.innerHTML = `
        <div class="diary-content">
          <p class="diary-placeholder">這一天還沒有日記內容</p>
        </div>
      `;
    }
  } catch (err) {
    console.error("刷新日記失敗:", err);
    let errorMessage = "刷新失敗，請稍後再試";
    
    // 檢查是否為配額限制錯誤
    if (err.message && (err.message.includes("429") || err.message.includes("配額") || err.message.includes("quota"))) {
      errorMessage = err.message || "AI 服務配額已用盡，請稍後再試";
    }
    
    container.innerHTML = `<p class="diary-placeholder">${errorMessage}</p>`;
  }
}


// ====== 更新日期顯示 ======
function updateDateDisplay() {
  if (leftPageDate) {
    const leftDateEl = el("leftPageDate");
    if (leftDateEl) {
      leftDateEl.textContent = formatDate(leftPageDate);
    }
  }

  if (rightPageDate) {
    const rightDateEl = el("rightPageDate");
    if (rightDateEl) {
      rightDateEl.textContent = formatDate(rightPageDate);
    }
  }
}

// ====== 更新日期輸入框 ======
function updateDateInput() {
  const dateInput = el("diaryDate");
  if (dateInput) {
    dateInput.value = formatDateForInput(currentDate);
  }
}

// ====== 日期格式化 ======
function formatDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDateForInput(date) {
  return formatDate(date);
}

// ====== 計算事件列表哈希（與後端算法一致） ======
async function calculateEventsHash(events) {
  // 將事件轉換為可序列化的格式（只包含關鍵字段，與後端一致）
  const eventData = events.map(e => ({
    id: String(e.id || ""),
    time: e.start_time ? (new Date(e.start_time).toISOString()) : "",
    location: e.scene || "",
    activity: e.action || "",
    summary: e.summary || "",
  }));
  
  // 按 ID 排序以確保一致性（與後端一致）
  eventData.sort((a, b) => a.id.localeCompare(b.id));
  
  // 計算 SHA256 哈希（使用 Web Crypto API，與後端算法一致）
  const eventsJson = JSON.stringify(eventData, null, 0);
  
  // 使用 Web Crypto API 計算 SHA256
  const encoder = new TextEncoder();
  const data = encoder.encode(eventsJson);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  
  return hashHex;
}

// ====== 載入用戶設定 ======
async function loadUserSettings() {
  try {
    if (!ApiClient || !ApiClient.settings) {
      console.warn('[diary] ApiClient.settings 未定義，使用預設設定');
      // 使用預設設定（預設啟用自動刷新）
      userSettings = {
        diary_auto_refresh_enabled: true, // 預設啟用
        diary_auto_refresh_interval_minutes: 30
      };
      return;
    }
    
    const response = await ApiClient.settings.get();
    const settings = response.settings || response;
    
    // 系統預設啟用日記自動刷新
    userSettings = {
      diary_auto_refresh_enabled: true, // 預設啟用，不再從設定中讀取
      diary_auto_refresh_interval_minutes: settings?.diary_auto_refresh_interval_minutes || 30
    };
    
    console.log('[diary] 用戶設定已載入:', userSettings);
  } catch (e) {
    console.error('[diary] 載入用戶設定失敗:', e);
    // 使用預設設定（預設啟用自動刷新）
    userSettings = {
      diary_auto_refresh_enabled: true, // 預設啟用
      diary_auto_refresh_interval_minutes: 30
    };
  }
}

// ====== 啟動日記自動刷新 ======
function startDiaryAutoRefresh() {
  // 清除現有的定時器
  stopDiaryAutoRefresh();
  
  // 檢查是否啟用自動刷新
  if (!userSettings || !userSettings.diary_auto_refresh_enabled) {
    console.log('[diary] 日記自動刷新未啟用');
    return;
  }
  
  const intervalMinutes = userSettings.diary_auto_refresh_interval_minutes || 30;
  const intervalMs = intervalMinutes * 60 * 1000; // 轉換為毫秒
  
  console.log(`[diary] 啟動日記自動刷新，間隔: ${intervalMinutes} 分鐘`);
  
  // 立即執行一次檢查（登入時）
  checkAndRefreshTodayDiary();
  
  // 設置定期檢查
  diaryAutoRefreshInterval = setInterval(() => {
    checkAndRefreshTodayDiary();
  }, intervalMs);
}

// ====== 停止日記自動刷新 ======
function stopDiaryAutoRefresh() {
  if (diaryAutoRefreshInterval) {
    clearInterval(diaryAutoRefreshInterval);
    diaryAutoRefreshInterval = null;
    console.log('[diary] 日記自動刷新已停止');
  }
}

// ====== 檢查並刷新當天日記 ======
async function checkAndRefreshTodayDiary() {
  try {
    // 獲取今天的日期
    const today = new Date();
    const todayStr = formatDate(today);
    
    // 檢查是否正在查看今天（右頁是今天）
    if (!rightPageDate) {
      return; // 還沒有初始化頁面
    }
    
    const rightPageDateStr = formatDate(rightPageDate);
    
    // 只刷新當天的日記（如果用戶正在查看今天）
    if (rightPageDateStr === todayStr) {
      console.log('[diary] 檢查今天的事件是否有變化...');
      
      // 獲取今天的事件列表來計算哈希
      const events = await ApiClient.listEvents({
        start_time: todayStr,
        end_time: todayStr,
        sort: 'start_time:asc',
        page: 1,
        size: 100 // 獲取所有事件
      });
      
      if (!events || !events.items) {
        console.warn('[diary] 無法獲取事件列表');
        return;
      }
      
      // 計算當前事件列表的哈希（異步函數）
      const currentHash = await calculateEventsHash(events.items);
      const lastHash = lastEventsHash[todayStr];
      
      // 如果哈希不同，說明有新事件，需要刷新日記
      if (currentHash !== lastHash) {
        console.log('[diary] 檢測到事件變化，自動刷新今天日記');
        console.log('[diary] 上次哈希:', lastHash?.substring(0, 16) + '...');
        console.log('[diary] 當前哈希:', currentHash.substring(0, 16) + '...');
        
        // 更新哈希記錄
        lastEventsHash[todayStr] = currentHash;
        
        // 刷新右頁（今天）的日記
        // 使用 generateDiarySummary，它會自動檢查哈希並只在需要時刷新
        await refreshDiaryPage(rightPageDate, "rightPageContent");
      } else {
        console.log('[diary] 事件沒有變化，無需刷新');
      }
    }
  } catch (err) {
    console.error('[diary] 檢查日記變化失敗:', err);
    // 不中斷自動刷新，繼續運行
  }
}

// ====== 更新日記內容時記錄哈希 ======
async function loadDiaryContent(date, containerId) {
  const container = el(containerId);
  if (!container) return;

  // 顯示載入中
  container.innerHTML = '<p class="diary-placeholder">載入中...</p>';

  try {
    const dateStr = formatDate(date);
    const diaryData = await ApiClient.chat.getDiary(dateStr);
    
    // 獲取該日期的事件列表來計算哈希
    try {
      const events = await ApiClient.listEvents({
        start_time: dateStr,
        end_time: dateStr,
        sort: 'start_time:asc',
        page: 1,
        size: 100
      });
      
      if (events && events.items) {
        // 記錄該日期的事件哈希（異步函數）
        lastEventsHash[dateStr] = await calculateEventsHash(events.items);
      }
    } catch (e) {
      console.warn('[diary] 獲取事件列表失敗（用於哈希計算）:', e);
    }
    
    // 檢查是否有事件
    if (diaryData.events_count === 0) {
      container.innerHTML = `
        <div class="diary-content">
          <p class="diary-placeholder">本日無事件，無法提供日記喔~</p>
        </div>
      `;
      return;
    }
    
    // 如果有內容，顯示日記內容
    if (diaryData.content) {
      // 將換行符轉換為 <br> 或使用 <pre> 標籤
      const formattedContent = diaryData.content
        .split('\n')
        .map(line => `<p>${line || '<br>'}</p>`)
        .join('');
      
      container.innerHTML = `
        <div class="diary-content">
          ${formattedContent}
        </div>
      `;
    } else {
      container.innerHTML = `
        <div class="diary-content">
          <p class="diary-placeholder">這一天還沒有日記內容</p>
        </div>
      `;
    }
  } catch (err) {
    console.error("載入日記失敗:", err);
    let errorMessage = "載入失敗，請稍後再試";
    
    // 檢查是否為配額限制錯誤
    if (err.message && (err.message.includes("429") || err.message.includes("配額") || err.message.includes("quota"))) {
      errorMessage = err.message || "AI 服務配額已用盡，請稍後再試";
    }
    
    container.innerHTML = `<p class="diary-placeholder">${errorMessage}</p>`;
  }
}

// ====== 頁面卸載時清理 ======
window.addEventListener('beforeunload', () => {
  stopDiaryAutoRefresh();
});

