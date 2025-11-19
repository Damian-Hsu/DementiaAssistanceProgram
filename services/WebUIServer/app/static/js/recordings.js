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
  const searchInput = document.getElementById('searchInput');
  const deleteVideoBtn = document.getElementById('deleteVideoBtn');

  let currentRecordingId = null;
  let currentRecording = null;

  // 格式化時間
  function formatDateTime(dateTimeStr) {
    if (!dateTimeStr) return '未知時間';
    try {
      const date = new Date(dateTimeStr);
      return date.toLocaleString('zh-TW', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
      });
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

  // 載入影片列表
  async function loadRecordings(keyword = '') {
    recordingsList.innerHTML = '<p class="loading">載入中...</p>';
    try {
      const data = await ApiClient.recordings.list({ 
        keywords: keyword || null,
        sort: '-start_time', 
        page: 1, 
        size: 50 
      });
      recordingsList.innerHTML = '';

      if (!data.items || data.items.length === 0) {
        recordingsList.innerHTML = '<p class="loading">沒有找到錄影紀錄。</p>';
        return;
      }

      // 過濾掉沒有時間資訊的影片（不顯示未知時間的影片）
      const validRecordings = data.items.filter(rec => {
        // 檢查是否有 start_time 且為有效值
        if (!rec.start_time) return false;
        try {
          const date = new Date(rec.start_time);
          // 檢查日期是否有效（不是 Invalid Date）
          return !isNaN(date.getTime());
        } catch (e) {
          return false;
        }
      });

      if (validRecordings.length === 0) {
        recordingsList.innerHTML = '<p class="loading">沒有找到有時間資訊的錄影紀錄。</p>';
        return;
      }

      validRecordings.forEach(rec => {
        const item = document.createElement('div');
        item.className = 'recording-item';
        item.dataset.id = rec.id;
        
        // 使用時間作為名稱
        const timeName = formatDateTime(rec.start_time);
        const duration = formatDuration(rec.duration);
        
        item.innerHTML = `
          <div class="recording-title">${timeName}</div>
          <div class="recording-meta">長度：${duration}</div>
        `;
        
        // 點擊選擇影片
        item.addEventListener('click', () => selectRecording(rec));
        
        recordingsList.appendChild(item);
      });
    } catch (e) {
      recordingsList.innerHTML = `<p class="error">錯誤：${e.message}</p>`;
    }
  }

  // 選擇影片
  async function selectRecording(recording) {
    try {
      // 先清除之前的錯誤處理器和影片源，避免載入舊的 URL
      videoPlayer.onerror = null;
      videoPlayer.src = '';
      videoPlayer.pause();
      videoPlayer.load();
      
      // 更新當前選擇
      currentRecordingId = recording.id;
      currentRecording = recording;
      
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
      const timeName = formatDateTime(recording.start_time);
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

    // 保存當前關鍵字和要刪除的 ID
    const keyword = searchInput.value.trim();
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
      
      // 重新載入列表
      await loadRecordings(keyword);
      
      // 如果列表中有其他影片，自動選擇第一個（但不是剛刪除的那個）
      const firstItem = document.querySelector('.recording-item');
      if (firstItem && firstItem.dataset.id !== deletedId) {
        const firstId = firstItem.dataset.id;
        // 從列表中找到對應的 recording 對象
        try {
          const data = await ApiClient.recordings.list({ 
            keywords: keyword, 
            sort: '-start_time', 
            page: 1, 
            size: 50 
          });
          // 過濾掉沒有時間資訊的影片（與 loadRecordings 中的邏輯一致）
          const validRecordings = data.items.filter(rec => {
            if (!rec.start_time) return false;
            try {
              const date = new Date(rec.start_time);
              return !isNaN(date.getTime());
            } catch (e) {
              return false;
            }
          });
          const firstRecording = validRecordings.find(rec => rec.id === firstId);
          if (firstRecording) {
            await selectRecording(firstRecording);
          }
        } catch (e) {
          console.error('自動選擇第一個影片失敗：', e);
        }
      }
      
      alert('已刪除影片。');
    } catch (err) {
      console.error('刪除影片失敗：', err);
      alert('刪除影片失敗：' + err.message);
    }
  }

  // 搜尋功能
  let searchTimeout = null;
  searchInput.addEventListener('input', (e) => {
    const keyword = e.target.value.trim();
    
    // 防抖處理
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      loadRecordings(keyword);
    }, 300);
  });

  // 刪除按鈕事件
  deleteVideoBtn.addEventListener('click', deleteRecording);

  // 初始化
  loadRecordings();
});
