import { ApiClient } from './APIClient.js';

const state = {
  tasks: [],
  currentUser: null,
  filters: {
    taskType: '',
    status: ''
  },
  pageNow: 1,
  pageSize: 20,
  scrollPosition: 0
};

const elements = {
  tasksList: document.getElementById('tasksList'),
  taskTypeFilter: document.getElementById('taskTypeFilter'),
  taskStatusFilter: document.getElementById('taskStatusFilter'),
  refreshTasks: document.getElementById('refreshTasks'),
  taskDetailModal: document.getElementById('taskDetailModal'),
  closeTaskDetail: document.getElementById('closeTaskDetail'),
  taskDetailContent: document.getElementById('taskDetailContent'),
  prevBtn: document.getElementById('prevBtn'),
  nextBtn: document.getElementById('nextBtn'),
  pageInput: document.getElementById('pageInput'),
  pageTotal: document.getElementById('pageTotal'),
  pageSize: document.getElementById('pageSize'),
  totalCount: document.getElementById('totalCount'),
};

function formatDate(isoString) {
  if (!isoString) return '-';
  try {
    const date = new Date(isoString);
    return date.toLocaleString('zh-TW');
  } catch {
    return isoString;
  }
}

function getStatusBadge(status) {
  const statusMap = {
    'pending': { text: '等待中', class: 'status-pending' },
    'processing': { text: '處理中', class: 'status-processing' },
    'running': { text: '運行中', class: 'status-running' },
    'starting': { text: '啟動中', class: 'status-starting' },
    'success': { text: '成功', class: 'status-success' },
    'failed': { text: '失敗', class: 'status-failed' },
    'error': { text: '錯誤', class: 'status-error' },
    'stopped': { text: '已停止', class: 'status-stopped' },
    'reconnecting': { text: '重連中', class: 'status-reconnecting' },
  };
  const statusInfo = statusMap[status] || { text: status, class: 'status-unknown' };
  return `<span class="status-badge ${statusInfo.class}">${statusInfo.text}</span>`;
}

function getTaskTypeLabel(type) {
  const typeMap = {
    'video_description': '影像轉換事件',
    'vlog_generation': 'Vlog 生成',
    'diary_generation': '日記生成',
    'embedding_generation': 'Embedding 生成',
    'diary_embeddings': '日記 Embedding',
    'rag_highlights': 'RAG 推薦',
    'streaming': '影像串流',
  };
  return typeMap[type] || type;
}

function setDisabled(element, disabled) {
  if (element) {
    element.disabled = disabled;
  }
}

async function init() {
  try {
    const response = window.__CURRENT_USER || await ApiClient.getCurrentUser();
    const user = response?.user || response;
    if (!user || user.role !== 'admin') {
      alert('此頁面僅限管理員使用，將返回首頁。');
      window.location.href = '/home';
      return;
    }
    state.currentUser = user;
    bindEvents();
    await loadTasks();
  } catch (error) {
    console.error('[AdminTasks] 初始化失敗', error);
    alert('載入管理介面失敗，請重新整理頁面。');
  }
}

function bindEvents() {
  if (elements.taskTypeFilter) {
    elements.taskTypeFilter.addEventListener('change', (e) => {
      state.filters.taskType = e.target.value;
      state.pageNow = 1;
      loadTasks();
    });
  }
  if (elements.taskStatusFilter) {
    elements.taskStatusFilter.addEventListener('change', (e) => {
      state.filters.status = e.target.value;
      state.pageNow = 1;
      loadTasks();
    });
  }
  if (elements.refreshTasks) {
    elements.refreshTasks.addEventListener('click', () => {
      // 保存當前滾動位置
      state.scrollPosition = window.pageYOffset || document.documentElement.scrollTop;
      loadTasks();
    });
  }
  if (elements.closeTaskDetail) {
    elements.closeTaskDetail.addEventListener('click', () => {
      elements.taskDetailModal?.classList.remove('show');
    });
  }
  if (elements.taskDetailModal) {
    elements.taskDetailModal.addEventListener('click', (e) => {
      if (e.target === elements.taskDetailModal) {
        elements.taskDetailModal.classList.remove('show');
      }
    });
  }

  // 分頁事件
  if (elements.prevBtn) {
    elements.prevBtn.addEventListener('click', () => {
      if (state.pageNow > 1) {
        state.pageNow--;
        loadTasks();
      }
    });
  }
  if (elements.nextBtn) {
    elements.nextBtn.addEventListener('click', () => {
      state.pageNow++;
      loadTasks();
    });
  }
  if (elements.pageInput) {
    elements.pageInput.addEventListener('change', () => {
      const inputValue = parseInt(elements.pageInput.value, 10);
      const maxPage = parseInt(elements.pageInput?.max || "1", 10);
      if (inputValue && inputValue >= 1 && inputValue <= maxPage) {
        state.pageNow = inputValue;
        loadTasks();
      } else {
        elements.pageInput.value = state.pageNow;
      }
    });
    elements.pageInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        const inputValue = parseInt(elements.pageInput.value, 10);
        const maxPage = parseInt(elements.pageInput?.max || "1", 10);
        if (inputValue && inputValue >= 1 && inputValue <= maxPage) {
          state.pageNow = inputValue;
          loadTasks();
        } else {
          elements.pageInput.value = state.pageNow;
        }
      }
    });
  }
  if (elements.pageSize) {
    elements.pageSize.addEventListener('change', () => {
      state.pageSize = parseInt(elements.pageSize.value, 10) || 20;
      state.pageNow = 1;
      loadTasks();
    });
    elements.pageSize.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        state.pageSize = parseInt(elements.pageSize.value, 10) || 20;
        state.pageNow = 1;
        loadTasks();
      }
    });
  }
}

async function loadTasks() {
  if (!elements.tasksList) return;
  
  elements.tasksList.innerHTML = '<tr><td colspan="7" class="text-center">載入中...</td></tr>';
  
  try {
    const data = await ApiClient.admin.tasks.list({
      task_type: state.filters.taskType || undefined,
      status_filter: state.filters.status || undefined,
      page: state.pageNow,
      size: state.pageSize,
    });
    
    state.tasks = data?.items || [];
    renderTasksTable(data);
    
    // 恢復滾動位置
    if (state.scrollPosition > 0) {
      window.scrollTo(0, state.scrollPosition);
      state.scrollPosition = 0; // 重置
    }
  } catch (error) {
    console.error('[AdminTasks] 取得任務列表失敗', error);
    if (elements.tasksList) {
      elements.tasksList.innerHTML = '<tr><td colspan="7" class="text-center">載入任務列表失敗，請稍後再試。</td></tr>';
    }
  }
}

function renderTasksTable(resp) {
  if (!elements.tasksList) return;

  const items = resp?.items || [];
  const total = resp?.item_total ?? items.length;
  const page = resp?.page_now ?? state.pageNow;
  const size = resp?.page_size ?? state.pageSize;
  const pageTotal = resp?.page_total || (total > 0 ? Math.ceil(total / size) : 1);

  // 更新分頁資訊
  if (elements.pageInput) {
    elements.pageInput.value = page;
    elements.pageInput.max = pageTotal;
  }
  if (elements.pageTotal) {
    elements.pageTotal.textContent = `/ ${pageTotal}`;
  }
  if (elements.totalCount) {
    elements.totalCount.textContent = total;
  }
  if (elements.pageSize) {
    elements.pageSize.value = size;
  }

  setDisabled(elements.prevBtn, page <= 1);
  setDisabled(elements.nextBtn, page >= pageTotal);

  state.pageNow = page;
  state.pageSize = size;

  if (!items.length) {
    elements.tasksList.innerHTML = '<tr><td colspan="7" class="text-center">目前沒有任務。</td></tr>';
    return;
  }

  elements.tasksList.innerHTML = items.map((task) => {
    const taskIdShort = task.task_id.length > 12 
      ? `${task.task_id.substring(0, 12)}...` 
      : task.task_id;
    
    const progress = task.progress !== null && task.progress !== undefined
      ? `${task.progress.toFixed(1)}%`
      : '-';
    
    return `
      <tr class="task-row" data-task-id="${task.task_id}" style="cursor: pointer;">
        <td title="${task.task_id}">${taskIdShort}</td>
        <td>${getTaskTypeLabel(task.task_type)}</td>
        <td>${getStatusBadge(task.status)}</td>
        <td>${task.user_id || '-'}</td>
        <td>${task.camera_id || '-'}</td>
        <td>${progress}</td>
        <td>${formatDate(task.created_at)}</td>
      </tr>
    `;
  }).join('');

  // 綁定行點擊事件
  elements.tasksList.querySelectorAll('tr.task-row').forEach((row) => {
    row.addEventListener('click', (e) => {
      if (e.target.tagName === 'BUTTON' || e.target.closest('button')) {
        return;
      }
      const taskId = row.dataset.taskId;
      const task = state.tasks.find(t => t.task_id === taskId);
      if (task) {
        showTaskDetail(task);
      }
    });
  });
}

function showTaskDetail(task) {
  if (!elements.taskDetailContent || !elements.taskDetailModal) return;
  
  const details = task.details || {};
  const detailHtml = `
    <div class="task-detail">
      <div class="detail-section">
        <h4>基本資訊</h4>
        <div class="table-responsive">
          <table class="table table-bordered">
            <tbody>
              <tr><th scope="row">任務 ID</th><td>${task.task_id}</td></tr>
              <tr><th scope="row">任務類型</th><td>${getTaskTypeLabel(task.task_type)}</td></tr>
              <tr><th scope="row">狀態</th><td>${getStatusBadge(task.status)}</td></tr>
              ${task.user_id ? `<tr><th scope="row">使用者 ID</th><td>${task.user_id}</td></tr>` : ''}
              ${task.camera_id ? `<tr><th scope="row">相機 ID</th><td>${task.camera_id}</td></tr>` : ''}
              ${task.created_at ? `<tr><th scope="row">建立時間</th><td>${formatDate(task.created_at)}</td></tr>` : ''}
              ${task.updated_at ? `<tr><th scope="row">更新時間</th><td>${formatDate(task.updated_at)}</td></tr>` : ''}
              ${task.progress !== null && task.progress !== undefined ? `<tr><th scope="row">進度</th><td>${task.progress.toFixed(1)}%</td></tr>` : ''}
            </tbody>
          </table>
        </div>
      </div>
      
      ${task.error_message ? `
        <div class="detail-section">
          <h4>錯誤資訊</h4>
          <div class="error-message">${task.error_message}</div>
        </div>
      ` : ''}
      
      ${Object.keys(details).length > 0 ? `
        <div class="detail-section">
          <h4>詳細資訊</h4>
          <pre class="detail-json">${JSON.stringify(details, null, 2)}</pre>
        </div>
      ` : ''}
    </div>
  `;
  
  elements.taskDetailContent.innerHTML = detailHtml;
  elements.taskDetailModal.classList.add('show');
}

// 自動刷新任務列表（每 10 秒）
setInterval(() => {
  if (document.visibilityState === 'visible') {
    // 保存滾動位置
    state.scrollPosition = window.pageYOffset || document.documentElement.scrollTop;
    loadTasks();
  }
}, 10000);

document.addEventListener('DOMContentLoaded', init);

