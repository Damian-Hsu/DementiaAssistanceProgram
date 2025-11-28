import { ApiClient } from './APIClient.js';

const state = {
  music: [],
  currentUser: null,
};

const elements = {
  musicUploadForm: document.getElementById('musicUploadForm'),
  musicName: document.getElementById('musicName'),
  musicComposer: document.getElementById('musicComposer'),
  musicDescription: document.getElementById('musicDescription'),
  musicMetadata: document.getElementById('musicMetadata'),
  musicFile: document.getElementById('musicFile'),
  musicUploadMessage: document.getElementById('musicUploadMessage'),
  musicList: document.getElementById('musicList'),
};

function formatDate(isoString) {
  if (!isoString) return '-';
  try {
    const date = new Date(isoString);
    return date.toLocaleString();
  } catch {
    return isoString;
  }
}

function formatNumber(value) {
  if (value === null || value === undefined) return '-';
  return Number(value).toLocaleString();
}

function showHint(el, message, type = 'info') {
  if (!el) return;
  el.textContent = message || '';
  el.classList.remove('success', 'error', 'info');
  el.classList.add(type);
}

async function init() {
  try {
    const response = window.__CURRENT_USER || await ApiClient.getCurrentUser();
    // API 返回格式為 {user: {...}}，需要提取 user 物件
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
    console.error('[AdminDashboard] 初始化失敗', error);
    alert('載入管理介面失敗，請重新整理頁面。');
  }
}

function bindEvents() {
  if (elements.musicUploadForm) {
    elements.musicUploadForm.addEventListener('submit', handleMusicUpload);
  }
}

async function loadMusicLibrary() {
  if (!elements.musicList) return;
  elements.musicList.classList.add('loading');
  try {
    const data = await ApiClient.admin.music.list();
    state.music = data?.items || [];
    renderMusicList();
  } catch (error) {
    console.error('[AdminDashboard] 取得音樂清單失敗', error);
    elements.musicList.innerHTML = `
      <div class="empty-state">
        <p>載入音樂清單失敗，請稍後再試。</p>
      </div>
    `;
  } finally {
    elements.musicList.classList.remove('loading');
  }
}

function renderMusicList() {
  if (!elements.musicList) return;
  elements.musicList.innerHTML = '';

  if (!state.music.length) {
    elements.musicList.innerHTML = `
      <div class="empty-state">
        <p>尚未上傳任何音樂。</p>
      </div>
    `;
    return;
  }

  state.music.forEach((track) => {
    const card = document.createElement('div');
    card.className = 'music-item';

    const composer = track.composer ? `・${track.composer}` : '';
    const description = track.description ? `<p>${track.description}</p>` : '';
    card.innerHTML = `
      <header>
        <div>
          <h3>${track.name}</h3>
          <div class="music-meta">
            <span>ID：${track.id}</span>
            <span>上傳者：${track.uploader_user_id}${composer}</span>
            <span>建立：${formatDate(track.created_at)}</span>
          </div>
        </div>
        <button type="button" class="btn-tertiary" data-music="${track.id}" data-action="delete">刪除</button>
      </header>
      <div class="music-meta">
        ${track.duration ? `<span>時長：約 ${Math.round(track.duration)} 秒</span>` : ''}
      </div>
      ${description}
    `;
    elements.musicList.appendChild(card);
  });

  elements.musicList.querySelectorAll('button[data-action="delete"]').forEach((btn) => {
    btn.addEventListener('click', () => deleteMusic(btn.dataset.music));
  });
}

async function handleMusicUpload(event) {
  event.preventDefault();
  if (!elements.musicFile?.files?.length) {
    showHint(elements.musicUploadMessage, '請選擇要上傳的音樂檔案。', 'error');
    return;
  }

  const formData = new FormData();
  formData.append('file', elements.musicFile.files[0]);
  formData.append('name', elements.musicName?.value?.trim() || '');
  formData.append('composer', elements.musicComposer?.value?.trim() || '');
  formData.append('description', elements.musicDescription?.value?.trim() || '');
  const metadataRaw = elements.musicMetadata?.value?.trim();
  if (metadataRaw) {
    formData.append('metadata', metadataRaw);
  }

  try {
    showHint(elements.musicUploadMessage, '上傳中...', 'info');
    await ApiClient.admin.music.upload(formData);
    showHint(elements.musicUploadMessage, '上傳成功！', 'success');
    elements.musicUploadForm.reset();
    await loadMusicLibrary();
  } catch (error) {
    console.error('[AdminDashboard] 上傳音樂失敗', error);
    showHint(elements.musicUploadMessage, '上傳失敗，請檢查檔案或稍後再試。', 'error');
  }
}

async function deleteMusic(musicId) {
  if (!musicId) return;
  if (!confirm('確定要刪除此音樂檔案嗎？刪除後無法復原。')) return;
  try {
    await ApiClient.admin.music.delete(musicId);
    state.music = state.music.filter((track) => track.id !== musicId);
    renderMusicList();
  } catch (error) {
    console.error('[AdminDashboard] 刪除音樂失敗', error);
    alert('刪除失敗，請稍後再試。');
  }
}

document.addEventListener('DOMContentLoaded', init);

