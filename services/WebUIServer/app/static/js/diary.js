import { ApiClient } from "/static/js/APIClient.js";
import { AuthService } from "/static/js/AuthService.js";

window.ApiClient = ApiClient;
window.AuthService = AuthService;

// ====== 工具函數 ======
function el(id) { return document.getElementById(id); }

// ====== 狀態管理 ======
let currentDate = new Date(); // 當前選擇的日期（單頁顯示）
let diaryAutoRefreshInterval = null; // 自動刷新定時器
let lastEventsHash = {}; // 記錄每個日期的上次事件哈希 { dateStr: hash }
let userSettings = null; // 用戶設定

// ====== URL Query 參數處理 ======
function getDateFromURL() {
  const urlParams = new URLSearchParams(window.location.search);
  const dateParam = urlParams.get('date');
  if (dateParam) {
    // 驗證日期格式 (YYYY-MM-DD)
    const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
    if (dateRegex.test(dateParam)) {
      const date = new Date(dateParam + "T00:00:00");
      // 檢查日期是否有效
      if (!isNaN(date.getTime())) {
        return date;
      }
    }
  }
  return null;
}

function updateURLDate(date) {
  const dateStr = formatDate(date);
  const url = new URL(window.location);
  url.searchParams.set('date', dateStr);
  // 使用 replaceState 而不是 pushState，避免產生過多歷史記錄
  window.history.replaceState({ date: dateStr }, '', url);
}

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

  // 從 URL query 參數讀取日期，如果沒有則使用今天
  const urlDate = getDateFromURL();
  const initialDate = urlDate || new Date();
  const dateInput = el("diaryDate");
  if (dateInput) {
    dateInput.value = formatDateForInput(initialDate);
    currentDate = initialDate;
  }

  // 如果從 URL 讀取到日期，更新 URL（確保格式一致）
  if (urlDate) {
    updateURLDate(initialDate);
  }

  // 初始化頁面
  await initializePages();

  // 綁定事件
  bindEvents();
  
  // 載入用戶設定並啟動自動刷新
  await loadUserSettings();
  startDiaryAutoRefresh();
  
  // 確保 VlogManager 初始化完成後載入 Vlog
  // 使用 setTimeout 確保在 DOM 完全載入後執行
  setTimeout(async () => {
    if (window.vlogManager) {
      // 等待 VlogManager 初始化完成
      if (window.vlogManager.initPromise) {
        try {
          await window.vlogManager.initPromise;
        } catch (error) {
          console.error('[diary] VlogManager 初始化失敗:', error);
          // 即使初始化失敗，也嘗試載入 Vlog
          await window.vlogManager.syncSelectedDate();
          window.vlogManager.loadDailyVlog();
        }
      } else {
        // 如果 initPromise 不存在，確保日期同步並載入 Vlog
        await window.vlogManager.syncSelectedDate();
        window.vlogManager.loadDailyVlog();
      }
    } else {
      // 如果 vlogManager 還不存在，等待它被創建（最多等待 1 秒）
      let attempts = 0;
      const maxAttempts = 20; // 20 * 50ms = 1秒
      const checkVlogManager = setInterval(async () => {
        attempts++;
        if (window.vlogManager) {
          clearInterval(checkVlogManager);
          if (window.vlogManager.initPromise) {
            try {
              await window.vlogManager.initPromise;
            } catch (error) {
              console.error('[diary] VlogManager 初始化失敗:', error);
              await window.vlogManager.syncSelectedDate();
              window.vlogManager.loadDailyVlog();
            }
          } else {
            await window.vlogManager.syncSelectedDate();
            window.vlogManager.loadDailyVlog();
          }
        } else if (attempts >= maxAttempts) {
          clearInterval(checkVlogManager);
          console.warn('[diary] VlogManager 未在預期時間內創建');
        }
      }, 50);
    }
  }, 100);
});

// ====== 事件綁定 ======
function bindEvents() {
  // 日期選擇器變更
  el("diaryDate")?.addEventListener("change", async (e) => {
    const selectedDate = new Date(e.target.value + "T00:00:00");
    currentDate = selectedDate;
    updateDateDisplay();
    // 更新 URL query 參數
    updateURLDate(selectedDate);
    await loadDiaryPages();
    // 同時更新 vlog
    if (window.vlogManager) {
      await window.vlogManager.syncSelectedDate();
      window.vlogManager.loadDailyVlog();
    }
  });

  // 翻頁處理函數
  const handlePrevPage = async (e) => {
    e.stopPropagation();
    currentDate = new Date(currentDate);
    currentDate.setDate(currentDate.getDate() - 1);
    updateDateInput();
    // 更新 URL query 參數
    updateURLDate(currentDate);
    await loadDiaryPages();
    // 同時更新 vlog
    if (window.vlogManager) {
      await window.vlogManager.syncSelectedDate();
      window.vlogManager.loadDailyVlog();
    }
  };

  const handleNextPage = async (e) => {
    e.stopPropagation();
    currentDate = new Date(currentDate);
    currentDate.setDate(currentDate.getDate() + 1);
    updateDateInput();
    // 更新 URL query 參數
    updateURLDate(currentDate);
    await loadDiaryPages();
    // 同時更新 vlog
    if (window.vlogManager) {
      await window.vlogManager.syncSelectedDate();
      window.vlogManager.loadDailyVlog();
    }
  };

  // 左側翻頁區域（上一頁）- 電腦模式（main 區域）
  el("prevPageArea")?.addEventListener("click", handlePrevPage);
  
  // 左側翻頁區域（上一頁）- 手機模式（header 區域）
  el("prevPageAreaHeader")?.addEventListener("click", handlePrevPage);

  // 右側翻頁區域（下一頁）- 電腦模式（main 區域）
  el("nextPageArea")?.addEventListener("click", handleNextPage);
  
  // 右側翻頁區域（下一頁）- 手機模式（header 區域）
  el("nextPageAreaHeader")?.addEventListener("click", handleNextPage);

  // 當前頁刷新按鈕
  el("currentPageRefreshBtn")?.addEventListener("click", async (e) => {
    e.stopPropagation();
    await refreshDiaryPage(currentDate, "currentPageContent");
  });
}

// ====== 初始化頁面 ======
async function initializePages() {
  await loadDiaryPages();
}

// ====== 載入日記頁面 ======
async function loadDiaryPages() {
  // 單頁顯示：只顯示當前選擇的日期
  // 更新日期顯示
  updateDateDisplay();

  // 載入日記內容
  await loadDiaryContent(currentDate, "currentPageContent");
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
      // 將換行符轉換為段落，空行不加入<br>
      const formattedContent = diaryData.content
        .split('\n')
        .filter(line => line.trim() !== '') // 過濾空行
        .map(line => `<p>${line}</p>`)
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
  // 更新當前頁日期顯示
  const currentDateEl = el("currentPageDate");
  if (currentDateEl) {
    currentDateEl.textContent = formatDate(currentDate);
  }
  
  // 更新日期選擇器顯示
  const dateDisplay = el("dateDisplay");
  if (dateDisplay) {
    dateDisplay.textContent = formatDate(currentDate);
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
    
    // 檢查是否正在查看今天
    if (!currentDate) {
      return; // 還沒有初始化頁面
    }
    
    const currentDateStr = formatDate(currentDate);
    
    // 只刷新當天的日記（如果用戶正在查看今天）
    if (currentDateStr === todayStr) {
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
        
        // 刷新當前頁（今天）的日記
        // 使用 generateDiarySummary，它會自動檢查哈希並只在需要時刷新
        await refreshDiaryPage(currentDate, "currentPageContent");
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
      // 將換行符轉換為段落，空行不加入<br>
      const formattedContent = diaryData.content
        .split('\n')
        .filter(line => line.trim() !== '') // 過濾空行
        .map(line => `<p>${line}</p>`)
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

