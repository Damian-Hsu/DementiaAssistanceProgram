import { ApiClient } from './APIClient.js';

document.addEventListener('DOMContentLoaded', async () => {
  const videoPlayer = document.getElementById('videoPlayer');
  const playerPlaceholder = document.getElementById('playerPlaceholder');
  const videoDetails = document.getElementById('videoDetails');
  const videoTitle = document.getElementById('videoTitle');
  const videoDuration = document.getElementById('videoDuration');
  const videoTime = document.getElementById('videoTime');
  const eventsList = document.getElementById('eventsList');
  const recordingsList = document.getElementById('recordingsList');
  const deleteVideoBtn = document.getElementById('deleteVideoBtn');

  // 分頁元件（位於 list-section 底下）
  const paginationEl = document.getElementById('recordingsPagination');
  const prevBtn = document.getElementById('prevBtn');
  const nextBtn = document.getElementById('nextBtn');
  const pageInput = document.getElementById('pageInput');
  const pageTotalEl = document.getElementById('pageTotal');
  const pageSizeInput = document.getElementById('pageSize');
  const totalCountEl = document.getElementById('totalCount');

  let currentRecordingId = null;
  let currentRecording = null;
  let validRecordings = []; // 保存當前載入的影片列表

  // 分頁狀態
  let pageNow = 1;
  let pageSize = 20;
  let pageTotal = 1;
  
  // 檢查 URL 參數中是否有 recording_id
  const urlParams = new URLSearchParams(window.location.search);
  const targetRecordingId = urlParams.get('recording_id');
  // 若有指定 recording_id：先以「單筆定位」模式載入，避免分頁找不到該影片
  let forcedRecordingId = targetRecordingId;

  // 格式化時間
  function formatDateTime(dateTimeStr) {
    if (!dateTimeStr) return '未知時間';
    try {
      // 後端會回傳已換算使用者時區的時間字串（ISO），
      // 這裡只做顯示用的「字串格式化」，不做時區計算。
      if (typeof dateTimeStr === 'string') {
        return dateTimeStr
          .replace('T', ' ')
          .replace('Z', '')
          .replace(/\.\d+/, '')
          .replace(/([+-]\d\d:\d\d)$/, '') // 移除時區 offset（顯示用）
          .trim();
      }
      const date = new Date(dateTimeStr);
      return date.toLocaleString('zh-TW');
    } catch (e) {
      return dateTimeStr;
    }
  }

  // 格式化持續時間
  function formatDuration(seconds) {
    if (!seconds) return '未知';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
  }

  // 載入縮圖
  async function loadThumbnail(recordingId, imgElement, thumbnailS3Key) {
    if (!imgElement || !thumbnailS3Key) {
      // 如果沒有縮圖元素或縮圖 key，確保縮圖區域仍然顯示黑色背景
      return;
    }
    try {
      // 嘗試獲取縮圖 URL（使用 type=thumbnail 參數）
      const urlData = await ApiClient.recordings.getUrl(recordingId, {
        ttl: 3600,
        disposition: 'inline',
        asset_type: 'thumbnail'
      });
      
      // 使用返回的 URL
      if (urlData && urlData.url) {
        imgElement.src = urlData.url;
        imgElement.style.display = 'block';
      } else {
        // 如果沒有 URL，隱藏圖片，顯示黑色背景
        imgElement.style.display = 'none';
      }
      
      imgElement.onerror = () => {
        // 載入失敗時隱藏圖片，顯示黑色背景
        imgElement.style.display = 'none';
      };
    } catch (e) {
      console.warn('無法載入縮圖:', e);
      if (imgElement) {
        // 錯誤時隱藏圖片，顯示黑色背景
        imgElement.style.display = 'none';
      }
    }
  }

  function updatePagination(resp, items) {
    const total = resp?.item_total ?? resp?.total ?? (items ? items.length : 0);
    const size = resp?.page_size ?? pageSize;
    const page = resp?.page_now ?? pageNow;
    const pt = resp?.page_total ?? (total > 0 ? Math.ceil(total / size) : 1);

    pageNow = page;
    pageSize = size;
    pageTotal = pt;

    if (pageInput) {
      pageInput.value = pageNow;
      pageInput.max = pageTotal;
    }
    if (pageTotalEl) {
      pageTotalEl.textContent = `/ ${pageTotal}`;
    }
    if (pageSizeInput) {
      pageSizeInput.value = pageSize;
    }
    if (totalCountEl) {
      totalCountEl.textContent = total;
    }
    if (prevBtn) prevBtn.disabled = pageNow <= 1;
    if (nextBtn) nextBtn.disabled = pageNow >= pageTotal;

    // 有資料才顯示分頁（定位單筆也顯示總筆數，方便回到全部）
    if (paginationEl) {
      paginationEl.style.display = total > 0 ? 'flex' : 'none';
    }
  }

  // 載入影片列表（支援分頁與單筆定位）
  async function loadRecordings(keyword = '', startDate = null, endDate = null, sortOrder = '-start_time', page = 1, size = 20, recordingId = null) {
    recordingsList.innerHTML = '<p class="loading">載入中...</p>';
    try {
      const params = {
        recording_id: recordingId || null,
        keywords: keyword || null,
        sort: sortOrder, 
        page: page, 
        size: size
      };
      
      // 添加日期範圍篩選
      if (startDate) {
        params.start_time = startDate;
      }
      if (endDate) {
        params.end_time = endDate;
      }
      
      const data = await ApiClient.recordings.list(params);
      recordingsList.innerHTML = '';

      if (!data.items || data.items.length === 0) {
        recordingsList.innerHTML = '<p class="loading">沒有找到錄影紀錄。</p>';
        updatePagination(data, []);
        return;
      }

      // 後端已盡量補齊 start_time（若缺失會用第一個事件時間/created_at）
      // 前端不再把「未知時間」整批濾掉，避免影片多時看起來像查不到
      validRecordings = Array.isArray(data.items) ? data.items : [];
      updatePagination(data, validRecordings);

      validRecordings.forEach(rec => {
        const item = document.createElement('div');
        item.className = 'recording-item';
        item.dataset.id = rec.id;
        
        // 使用時間作為名稱
        const timeName = formatDateTime(rec.start_time || rec.created_at);
        const duration = formatDuration(rec.duration);
        
        // 所有項目都顯示縮圖區域，即使沒有縮圖也顯示黑色佔位符（3:4 比例）
        item.innerHTML = `
          <div class="recording-thumbnail">
            ${rec.thumbnail_s3_key ? `<img src="" alt="影片縮圖" data-recording-id="${rec.id}" class="thumbnail-img" />` : ''}
          </div>
          <div class="recording-info">
            <div class="recording-title">${timeName}</div>
            <div class="recording-meta">長度：${duration}</div>
          </div>
        `;
        
        // 如果有縮圖，載入縮圖 URL
        if (rec.thumbnail_s3_key) {
          const thumbnailImg = item.querySelector('.thumbnail-img');
          if (thumbnailImg) {
            loadThumbnail(rec.id, thumbnailImg, rec.thumbnail_s3_key);
          }
        }
        
        // 點擊選擇影片
        item.addEventListener('click', () => selectRecording(rec));
        
        recordingsList.appendChild(item);
      });
      
      // 返回 validRecordings 供外部使用
      return validRecordings;
    } catch (e) {
      recordingsList.innerHTML = `<p class="error">錯誤：${e.message}</p>`;
      updatePagination(null, []);
    }
  }

  // 選擇影片
  async function selectRecording(recording, updateUrl = true) {
    try {
      // 先清除之前的錯誤處理器和影片源，避免載入舊的 URL
      videoPlayer.onerror = null;
      videoPlayer.src = '';
      videoPlayer.pause();
      videoPlayer.load();
      
      // 更新當前選擇
      currentRecordingId = recording.id;
      currentRecording = recording;
      
      // 更新 URL query（如果允許）
      if (updateUrl) {
        const url = new URL(window.location.href);
        url.searchParams.set('recording_id', recording.id);
        window.history.pushState({ recording_id: recording.id }, '', url);
      }
      
      // 更新列表中的 active 狀態
      document.querySelectorAll('.recording-item').forEach(item => {
        item.classList.remove('active');
        if (item.dataset.id === recording.id) {
          item.classList.add('active');
        }
      });

      // 獲取影片 URL
      const urlData = await ApiClient.recordings.getUrl(recording.id, { 
        ttl: 3600, 
        disposition: 'inline' 
      });

      // 檢查是否還是同一個 recording（避免異步競態條件）
      if (currentRecordingId !== recording.id) {
        console.log('Recording changed during URL fetch, aborting');
        return;
      }

      // 設置影片源
      videoPlayer.src = urlData.url;
      videoPlayer.style.display = 'block';
      playerPlaceholder.style.display = 'none';
      
      // 處理影片載入錯誤（只處理一次，避免重複提示）
      const handleVideoError = () => {
        // 檢查是否還是當前選擇的影片
        if (currentRecordingId !== recording.id) {
          return; // 已經切換到其他影片，忽略此錯誤
        }
        
        console.error('影片載入錯誤');
        console.error('影片 URL：', urlData.url);
        console.error('Recording ID：', recording.id);
        
        // 清除當前選擇，避免重複嘗試載入
        currentRecordingId = null;
        currentRecording = null;
        videoPlayer.src = '';
        videoPlayer.pause();
        videoPlayer.load();
        videoPlayer.style.display = 'none';
        playerPlaceholder.style.display = 'flex';
        videoDetails.style.display = 'none';
        
        // 移除 active 狀態
        document.querySelectorAll('.recording-item').forEach(item => {
          item.classList.remove('active');
        });
        
        // 檢查是否是網絡錯誤
        if (videoPlayer.error) {
          const errorCode = videoPlayer.error.code;
          if (errorCode === MediaError.MEDIA_ERR_NETWORK) {
            alert('無法載入影片：網絡連接錯誤。請檢查網絡連接或聯繫管理員。');
          } else if (errorCode === MediaError.MEDIA_ERR_DECODE) {
            alert('無法載入影片：影片格式錯誤或已損壞。');
          } else if (errorCode === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED) {
            alert('無法載入影片：不支援的影片格式。可能是影片已被刪除或檔案損壞。');
          } else {
            alert('無法載入影片，請檢查網絡連接或聯繫管理員。');
          }
        }
      };
      videoPlayer.addEventListener('error', handleVideoError, { once: true });

      // 更新詳細資訊
      const timeName = formatDateTime(recording.start_time || recording.created_at);
      const duration = formatDuration(recording.duration);
      const timeRange = recording.end_time
        ? `${formatDateTime(recording.start_time)} - ${formatDateTime(recording.end_time)}`
        : formatDateTime(recording.start_time);

      videoTitle.textContent = timeName;
      videoDuration.textContent = `長度：${duration}`;
      videoTime.textContent = `時間：${timeRange}`;

      // 顯示詳細資訊區塊
      videoDetails.style.display = 'block';

      // 載入影片內的事件
      await loadRecordingEvents(recording.id);

    } catch (err) {
      console.error('載入影片失敗：', err);
      alert('載入影片失敗：' + err.message);
    }
  }

  // 載入影片內的事件
  async function loadRecordingEvents(recordingId) {
    eventsList.innerHTML = '<p class="loading">載入事件中...</p>';
    try {
      const events = await ApiClient.recordings.getEvents(recordingId, '-start_time');
      eventsList.innerHTML = '';

      if (!events || events.length === 0) {
        eventsList.innerHTML = '<p class="loading">此影片無事件。</p>';
        return;
      }

      events.forEach(event => {
        const eventItem = document.createElement('div');
        eventItem.className = 'event-item';
        
        const eventTime = formatDateTime(event.start_time);
        const eventDuration = event.duration ? `持續 ${Math.floor(event.duration)} 秒` : '';
        const eventLocation = event.scene || '未知地點';
        const eventAction = event.action || '未知活動';
        
        eventItem.innerHTML = `
          <div class="event-time">${eventTime}</div>
          <div class="event-summary">${event.summary || '（無摘要）'}</div>
          <div class="event-meta">${eventLocation} · ${eventAction}${eventDuration ? ' · ' + eventDuration : ''}</div>
        `;
        
        eventsList.appendChild(eventItem);
      });
    } catch (err) {
      console.error('載入事件失敗：', err);
      eventsList.innerHTML = `<p class="error">載入事件失敗：${err.message}</p>`;
    }
  }

  // 刪除影片
  async function deleteRecording() {
    if (!currentRecordingId) {
      alert('請先選擇一個影片');
      return;
    }

    if (!confirm('確定要刪除此影片？此動作無法復原。')) {
      return;
    }

    // 保存要刪除的 ID
    const deletedId = currentRecordingId;

    try {
      await ApiClient.recordings.delete(currentRecordingId);
      
      // 立即清除當前選擇和播放器，避免嘗試載入已刪除的影片
      currentRecordingId = null;
      currentRecording = null;
      
      // 清除播放器和詳細資訊
      videoPlayer.src = '';
      videoPlayer.pause();
      videoPlayer.load(); // 重置 video 元素
      videoPlayer.style.display = 'none';
      playerPlaceholder.style.display = 'flex';
      videoDetails.style.display = 'none';
      
      // 移除所有 active 狀態
      document.querySelectorAll('.recording-item').forEach(item => {
        item.classList.remove('active');
      });
      
      // 重新載入列表（使用當前的篩選條件）
      await loadRecordingsWithFilters();

      // 若刪到當頁最後一筆，可能會變成空頁：退一頁再載一次（僅一般列表模式）
      if (!forcedRecordingId && (!validRecordings || validRecordings.length === 0) && pageNow > 1) {
        pageNow--;
        await loadRecordingsWithFilters();
      }
      
      // 如果列表中有其他影片，自動選擇第一個（但不是剛刪除的那個）
      const firstItem = document.querySelector('.recording-item');
      if (firstItem && firstItem.dataset.id !== deletedId) {
        const firstId = firstItem.dataset.id;
        // 從已載入的列表中找到對應的 recording 對象
        const firstRecording = validRecordings.find(rec => rec.id === firstId);
        if (firstRecording) {
          await selectRecording(firstRecording, false); // 不更新 URL
        }
      } else if (validRecordings && validRecordings.length > 0) {
        // 如果沒有找到第一個項目，但有列表，選擇列表中的第一個
        await selectRecording(validRecordings[0], false); // 不更新 URL
      }
      
      alert('已刪除影片。');
    } catch (err) {
      console.error('刪除影片失敗：', err);
      alert('刪除影片失敗：' + err.message);
    }
  }

  // 搜尋功能
  const keywordsInput = document.getElementById('keywords');
  const startDateInput = document.getElementById('start');
  const endDateInput = document.getElementById('end');
  const sortOrderSelect = document.getElementById('sortOrder');
  const resetBtn = document.getElementById('resetBtn');
  
  let searchTimeout = null;
  
  // 關鍵字搜尋（防抖）
  if (keywordsInput) {
    keywordsInput.addEventListener('input', (e) => {
      const keyword = e.target.value.trim();
      
      // 一旦開始搜尋，就解除單筆定位模式
      if (forcedRecordingId) {
        forcedRecordingId = null;
        const url = new URL(window.location.href);
        url.searchParams.delete('recording_id');
        window.history.replaceState({}, '', url);
      }

      // 防抖處理
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        pageNow = 1;
        loadRecordingsWithFilters();
      }, 300);
    });
  }
  
  // 日期範圍搜尋
  if (startDateInput) {
    startDateInput.addEventListener('change', () => {
      if (forcedRecordingId) {
        forcedRecordingId = null;
        const url = new URL(window.location.href);
        url.searchParams.delete('recording_id');
        window.history.replaceState({}, '', url);
      }
      pageNow = 1;
      loadRecordingsWithFilters();
    });
  }
  
  if (endDateInput) {
    endDateInput.addEventListener('change', () => {
      if (forcedRecordingId) {
        forcedRecordingId = null;
        const url = new URL(window.location.href);
        url.searchParams.delete('recording_id');
        window.history.replaceState({}, '', url);
      }
      pageNow = 1;
      loadRecordingsWithFilters();
    });
  }
  
  // 排序變更
  if (sortOrderSelect) {
    sortOrderSelect.addEventListener('change', () => {
      if (forcedRecordingId) {
        forcedRecordingId = null;
        const url = new URL(window.location.href);
        url.searchParams.delete('recording_id');
        window.history.replaceState({}, '', url);
      }
      pageNow = 1;
      loadRecordingsWithFilters();
    });
  }
  
  // 重設按鈕
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      if (keywordsInput) keywordsInput.value = '';
      if (startDateInput) startDateInput.value = '';
      if (endDateInput) endDateInput.value = '';
      if (sortOrderSelect) sortOrderSelect.value = '-start_time';
      // 重設同時解除單筆定位，並把 URL 的 recording_id 拿掉
      forcedRecordingId = null;
      const url = new URL(window.location.href);
      url.searchParams.delete('recording_id');
      window.history.replaceState({}, '', url);
      pageNow = 1;
      loadRecordingsWithFilters();
    });
  }

  // 分頁：上一頁/下一頁
  if (prevBtn) {
    prevBtn.addEventListener('click', () => {
      if (pageNow > 1) {
        pageNow--;
        loadRecordingsWithFilters();
      }
    });
  }
  if (nextBtn) {
    nextBtn.addEventListener('click', () => {
      if (pageNow < pageTotal) {
        pageNow++;
        loadRecordingsWithFilters();
      }
    });
  }
  if (pageInput) {
    pageInput.addEventListener('change', () => {
      const inputValue = parseInt(pageInput.value, 10);
      const maxPage = parseInt(pageInput.max || '1', 10);
      if (inputValue && inputValue >= 1 && inputValue <= maxPage) {
        pageNow = inputValue;
        loadRecordingsWithFilters();
      } else {
        pageInput.value = pageNow;
      }
    });
    pageInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        const inputValue = parseInt(pageInput.value, 10);
        const maxPage = parseInt(pageInput.max || '1', 10);
        if (inputValue && inputValue >= 1 && inputValue <= maxPage) {
          pageNow = inputValue;
          loadRecordingsWithFilters();
        } else {
          pageInput.value = pageNow;
        }
      }
    });
  }
  if (pageSizeInput) {
    pageSizeInput.addEventListener('change', () => {
      pageSize = parseInt(pageSizeInput.value, 10) || 20;
      pageNow = 1;
      loadRecordingsWithFilters();
    });
    pageSizeInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        pageSize = parseInt(pageSizeInput.value, 10) || 20;
        pageNow = 1;
        loadRecordingsWithFilters();
      }
    });
  }
  
  // 統一的載入函數（包含所有篩選條件）
  async function loadRecordingsWithFilters() {
    const keyword = keywordsInput?.value.trim() || '';
    const startDate = startDateInput?.value || null;
    const endDate = endDateInput?.value || null;
    const sortOrder = sortOrderSelect?.value || '-start_time';
    
    await loadRecordings(keyword, startDate, endDate, sortOrder, pageNow, pageSize, forcedRecordingId);
  }

  // 刪除按鈕事件
  deleteVideoBtn.addEventListener('click', deleteRecording);

  // 初始化
  await loadRecordingsWithFilters();
  
  // 第一次進入頁面：只自動選取一次，避免重複呼叫 selectRecording 造成競態
  if (forcedRecordingId && validRecordings && validRecordings.length > 0) {
    // 定位模式：列表預期只回傳該筆，直接選取
    await selectRecording(validRecordings[0], false);
  } else if (validRecordings && validRecordings.length > 0) {
    // 沒有指定 recording_id：預載入最新的影片（不更新 URL）
    await selectRecording(validRecordings[0], false);
  }
});
