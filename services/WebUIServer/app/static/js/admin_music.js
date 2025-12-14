import { ApiClient } from './APIClient.js';

const state = {
  music: [],
  currentUser: null,
  editingMusicId: null,
};

const elements = {
  addMusicBtn: document.getElementById('addMusicBtn'),
  musicList: document.getElementById('musicList'),
  
  // 新增音樂彈出視窗
  addMusicModal: document.getElementById('addMusicModal'),
  closeAddMusicModal: document.getElementById('closeAddMusicModal'),
  cancelAddMusic: document.getElementById('cancelAddMusic'),
  musicUploadForm: document.getElementById('musicUploadForm'),
  musicName: document.getElementById('musicName'),
  musicComposer: document.getElementById('musicComposer'),
  musicDescription: document.getElementById('musicDescription'),
  musicMetadata: document.getElementById('musicMetadata'),
  musicFile: document.getElementById('musicFile'),
  musicUploadMessage: document.getElementById('musicUploadMessage'),
  submitAddMusic: document.getElementById('submitAddMusic'),
  
  // 音樂詳情/編輯彈出視窗
  musicDetailModal: document.getElementById('musicDetailModal'),
  closeMusicDetailModal: document.getElementById('closeMusicDetailModal'),
  cancelEditMusic: document.getElementById('cancelEditMusic'),
  musicEditForm: document.getElementById('musicEditForm'),
  editMusicId: document.getElementById('editMusicId'),
  editMusicIdDisplay: document.getElementById('editMusicIdDisplay'),
  editMusicName: document.getElementById('editMusicName'),
  editMusicComposer: document.getElementById('editMusicComposer'),
  editMusicDescription: document.getElementById('editMusicDescription'),
  editMusicMetadata: document.getElementById('editMusicMetadata'),
  editMusicUploader: document.getElementById('editMusicUploader'),
  editMusicCreatedAt: document.getElementById('editMusicCreatedAt'),
  musicEditMessage: document.getElementById('musicEditMessage'),
  saveMusicBtn: document.getElementById('saveMusicBtn'),
  deleteMusicBtn: document.getElementById('deleteMusicBtn'),
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

function formatDuration(seconds) {
  if (!seconds) return '-';
  try {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  } catch {
    return seconds.toString();
  }
}

function showHint(el, message, type = 'info') {
  if (!el) return;
  el.textContent = message || '';
  el.classList.remove('success', 'error', 'info');
  if (message) {
    el.classList.add(type);
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
    await loadMusicLibrary();
  } catch (error) {
    console.error('[AdminMusic] 初始化失敗', error);
    alert('載入管理介面失敗，請重新整理頁面。');
  }
}

function bindEvents() {
  // 新增音樂按鈕
  if (elements.addMusicBtn) {
    elements.addMusicBtn.addEventListener('click', () => {
      openAddMusicModal();
    });
  }

  // 關閉新增音樂彈出視窗
  if (elements.closeAddMusicModal) {
    elements.closeAddMusicModal.addEventListener('click', () => {
      closeAddMusicModal();
    });
  }
  if (elements.cancelAddMusic) {
    elements.cancelAddMusic.addEventListener('click', () => {
      closeAddMusicModal();
    });
  }
  if (elements.addMusicModal) {
    elements.addMusicModal.addEventListener('click', (e) => {
      if (e.target === elements.addMusicModal) {
        closeAddMusicModal();
      }
    });
  }

  // 提交新增音樂
  if (elements.submitAddMusic) {
    elements.submitAddMusic.addEventListener('click', () => {
      handleMusicUpload();
    });
  }

  // 關閉音樂詳情彈出視窗
  if (elements.closeMusicDetailModal) {
    elements.closeMusicDetailModal.addEventListener('click', () => {
      closeMusicDetailModal();
    });
  }
  if (elements.cancelEditMusic) {
    elements.cancelEditMusic.addEventListener('click', () => {
      closeMusicDetailModal();
    });
  }
  if (elements.musicDetailModal) {
    elements.musicDetailModal.addEventListener('click', (e) => {
      if (e.target === elements.musicDetailModal) {
        closeMusicDetailModal();
      }
    });
  }

  // 儲存音樂編輯
  if (elements.saveMusicBtn) {
    elements.saveMusicBtn.addEventListener('click', () => {
      handleMusicUpdate();
    });
  }

  // 刪除音樂
  if (elements.deleteMusicBtn) {
    elements.deleteMusicBtn.addEventListener('click', () => {
      handleMusicDelete();
    });
  }
}

function openAddMusicModal() {
  if (!elements.addMusicModal) return;
  if (elements.musicUploadForm) {
    elements.musicUploadForm.reset();
  }
  showHint(elements.musicUploadMessage, '');
  elements.addMusicModal.classList.add('show');
}

function closeAddMusicModal() {
  if (!elements.addMusicModal) return;
  elements.addMusicModal.classList.remove('show');
  if (elements.musicUploadForm) {
    elements.musicUploadForm.reset();
  }
  showHint(elements.musicUploadMessage, '');
}

function openMusicDetailModal(music) {
  if (!elements.musicDetailModal || !music) return;
  
  state.editingMusicId = music.id;
  
  // 填充表單
  if (elements.editMusicId) elements.editMusicId.value = music.id;
  if (elements.editMusicIdDisplay) elements.editMusicIdDisplay.value = music.id;
  if (elements.editMusicName) elements.editMusicName.value = music.name || '';
  if (elements.editMusicComposer) elements.editMusicComposer.value = music.composer || '';
  if (elements.editMusicDescription) elements.editMusicDescription.value = music.description || '';
  if (elements.editMusicMetadata) {
    elements.editMusicMetadata.value = music.metadata 
      ? JSON.stringify(music.metadata, null, 2) 
      : '';
  }
  if (elements.editMusicUploader) elements.editMusicUploader.value = music.uploader_user_id || '-';
  if (elements.editMusicCreatedAt) elements.editMusicCreatedAt.value = formatDate(music.created_at);
  
  showHint(elements.musicEditMessage, '');
  elements.musicDetailModal.classList.add('show');
}

function closeMusicDetailModal() {
  if (!elements.musicDetailModal) return;
  elements.musicDetailModal.classList.remove('show');
  state.editingMusicId = null;
  if (elements.musicEditForm) {
    elements.musicEditForm.reset();
  }
  showHint(elements.musicEditMessage, '');
}

async function loadMusicLibrary() {
  if (!elements.musicList) return;
  elements.musicList.innerHTML = '<tr><td colspan="5" class="text-center">載入中...</td></tr>';
  
  try {
    const data = await ApiClient.admin.music.list();
    state.music = data?.items || [];
    renderMusicTable();
  } catch (error) {
    console.error('[AdminMusic] 取得音樂清單失敗', error);
    if (elements.musicList) {
      elements.musicList.innerHTML = '<tr><td colspan="5" class="text-center">載入音樂清單失敗，請稍後再試。</td></tr>';
    }
  }
}

function renderMusicTable() {
  if (!elements.musicList) return;

  if (!state.music.length) {
    elements.musicList.innerHTML = '<tr><td colspan="5" class="text-center">尚未上傳任何音樂。</td></tr>';
    return;
  }

  elements.musicList.innerHTML = state.music.map((track) => {
    const duration = track.duration ? formatDuration(track.duration) : '-';
    const composer = track.composer || '-';
    const uploader = track.uploader_user_id || '-';
    
    return `
      <tr class="music-row" data-music-id="${track.id}" style="cursor: pointer;">
        <td>${track.name || '-'}</td>
        <td>${composer}</td>
        <td>${duration}</td>
        <td>${uploader}</td>
        <td>${formatDate(track.created_at)}</td>
      </tr>
    `;
  }).join('');

  // 綁定行點擊事件
  elements.musicList.querySelectorAll('tr.music-row').forEach((row) => {
    row.addEventListener('click', (e) => {
      const musicId = row.dataset.musicId;
      const music = state.music.find(m => m.id === musicId);
      if (music) {
        openMusicDetailModal(music);
      }
    });
  });
}

async function handleMusicUpload() {
  if (!elements.musicFile?.files?.length) {
    showHint(elements.musicUploadMessage, '請選擇要上傳的音樂檔案。', 'error');
    return;
  }

  if (!elements.musicName?.value?.trim()) {
    showHint(elements.musicUploadMessage, '請輸入音樂名稱。', 'error');
    return;
  }

  const formData = new FormData();
  formData.append('file', elements.musicFile.files[0]);
  formData.append('name', elements.musicName.value.trim());
  if (elements.musicComposer?.value?.trim()) {
    formData.append('composer', elements.musicComposer.value.trim());
  }
  if (elements.musicDescription?.value?.trim()) {
    formData.append('description', elements.musicDescription.value.trim());
  }
  const metadataRaw = elements.musicMetadata?.value?.trim();
  if (metadataRaw) {
    try {
      JSON.parse(metadataRaw); // 驗證 JSON 格式
      formData.append('metadata', metadataRaw);
    } catch (e) {
      showHint(elements.musicUploadMessage, 'Metadata 必須是有效的 JSON 格式。', 'error');
      return;
    }
  }

  try {
    showHint(elements.musicUploadMessage, '上傳中...', 'info');
    elements.submitAddMusic.disabled = true;
    
    await ApiClient.admin.music.upload(formData);
    showHint(elements.musicUploadMessage, '上傳成功！', 'success');
    
    // 延遲關閉彈出視窗，讓用戶看到成功訊息
    setTimeout(() => {
      closeAddMusicModal();
      loadMusicLibrary();
    }, 1000);
  } catch (error) {
    console.error('[AdminMusic] 上傳音樂失敗', error);
    showHint(elements.musicUploadMessage, error.message || '上傳失敗，請檢查檔案或稍後再試。', 'error');
  } finally {
    if (elements.submitAddMusic) {
      elements.submitAddMusic.disabled = false;
    }
  }
}

async function handleMusicUpdate() {
  if (!state.editingMusicId) return;

  if (!elements.editMusicName?.value?.trim()) {
    showHint(elements.musicEditMessage, '請輸入音樂名稱。', 'error');
    return;
  }

  // 檢查 metadata JSON 格式
  const metadataRaw = elements.editMusicMetadata?.value?.trim();
  let metadata = null;
  if (metadataRaw) {
    try {
      metadata = JSON.parse(metadataRaw);
    } catch (e) {
      showHint(elements.musicEditMessage, 'Metadata 必須是有效的 JSON 格式。', 'error');
      return;
    }
  }

  const updateData = {
    name: elements.editMusicName.value.trim(),
    composer: elements.editMusicComposer?.value?.trim() || null,
    description: elements.editMusicDescription?.value?.trim() || null,
    metadata: metadata,
  };

  try {
    showHint(elements.musicEditMessage, '更新中...', 'info');
    elements.saveMusicBtn.disabled = true;
    
    await ApiClient.admin.music.update(state.editingMusicId, updateData);
    showHint(elements.musicEditMessage, '更新成功！', 'success');
    
    setTimeout(() => {
      closeMusicDetailModal();
      loadMusicLibrary();
    }, 1000);
  } catch (error) {
    console.error('[AdminMusic] 更新音樂失敗', error);
    showHint(elements.musicEditMessage, error.message || '更新失敗，請稍後再試。', 'error');
  } finally {
    if (elements.saveMusicBtn) {
      elements.saveMusicBtn.disabled = false;
    }
  }
}

async function handleMusicDelete() {
  if (!state.editingMusicId) return;
  
  if (!confirm('確定要刪除此音樂檔案嗎？刪除後無法復原。')) {
    return;
  }

  try {
    showHint(elements.musicEditMessage, '刪除中...', 'info');
    elements.deleteMusicBtn.disabled = true;
    
    await ApiClient.admin.music.delete(state.editingMusicId);
    showHint(elements.musicEditMessage, '刪除成功！', 'success');
    
    setTimeout(() => {
      closeMusicDetailModal();
      loadMusicLibrary();
    }, 1000);
  } catch (error) {
    console.error('[AdminMusic] 刪除音樂失敗', error);
    showHint(elements.musicEditMessage, error.message || '刪除失敗，請稍後再試。', 'error');
  } finally {
    if (elements.deleteMusicBtn) {
      elements.deleteMusicBtn.disabled = false;
    }
  }
}

document.addEventListener('DOMContentLoaded', init);
