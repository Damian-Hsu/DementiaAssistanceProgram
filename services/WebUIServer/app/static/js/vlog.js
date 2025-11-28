/**
 * Vlog 功能模組
 * 處理 Vlog 列表、事件選擇、Vlog 生成等功能
 */

import { ApiClient } from './APIClient.js';

class VlogManager {
    constructor() {
        this.selectedEvents = [];
        this.selectedDate = null;
        this.pollTimer = null;
        this.dailyVlog = null;
        this.currentVideoUrl = null;
        this.currentVideoId = null;
        this.musicTracks = [];
        this.musicLoaded = false;
        this.musicSelection = {
            trackId: null,
            duration: 0, // 影片長度（選擇的片段長度）
            totalDuration: 0, // 音樂原始總長度
            start: 0,
            end: 0,
            fade: true,
            volume: 0.6,
        };
        // 最大時長現在由音樂選擇的 in/out 控制，不再需要單獨的變數
        this.musicElements = {};
        this.musicAudio = null;
        this.audioContext = null;
        this.audioBuffer = null;
        this.audioObjectUrl = null;
        this.isDragging = false;
        this.dragType = null; // 'start' | 'end' | 'selection'
        this.dragStartX = 0;
        this.isPlaying = false;
        this.initPromise = this.init();
    }

    initializeMusicAudio() {
        if (this.musicAudio) {
            this.musicAudio.pause();
        }
        this.musicAudio = new Audio();
        this.musicAudio.preload = 'auto';
        this.musicAudio.addEventListener('timeupdate', () => this.handleMusicTimeUpdate());
        this.musicAudio.addEventListener('ended', () => {
            this.stopMusicPlayback(false);
            this.isPlaying = false;
        });
        this.musicAudio.addEventListener('pause', () => {
            this.isPlaying = false;
            if (this.musicElements.playBtn) {
                this.musicElements.playBtn.src = '/static/icons/play.svg';
            }
        });
        this.musicAudio.addEventListener('loadedmetadata', () => {
            if (!this.musicSelection.duration && Number.isFinite(this.musicAudio.duration)) {
                this.musicSelection.duration = this.musicAudio.duration;
                this.musicSelection.end = Math.min(
                    this.musicAudio.duration,
                    this.musicSelection.end || this.musicAudio.duration
                );
                this.updateMusicRangeInputs();
                this.updateSelectionOverlay();
            }
        });
    }

    async loadMusicTracks(force = false) {
        if (!this.musicElements.select) return;
        if (this.musicLoaded && !force) return;

        try {
            this.musicElements.select.disabled = true;
            const response = await ApiClient.music.list(0, 100);
            this.musicTracks = response?.items || [];
            this.musicLoaded = true;
            this.populateMusicSelect();
        } catch (error) {
            console.error('載入音樂清單失敗:', error);
            this.showToast('載入音樂清單失敗，請稍後再試', 'error');
        } finally {
            this.musicElements.select.disabled = false;
        }
    }

    populateMusicSelect() {
        const select = this.musicElements.select;
        if (!select) return;

        const currentValue = select.value;
        select.innerHTML = '<option value="">請選擇音樂</option>';
        this.musicTracks.forEach((track) => {
            const option = document.createElement('option');
            option.value = track.id;
            // 構建顯示文字：名稱 — 作曲家（如果有介紹，顯示前30字元）
            let displayText = track.name;
            if (track.composer) {
                displayText += ` — ${track.composer}`;
            }
            if (track.description) {
                const desc = track.description.length > 30 
                    ? track.description.substring(0, 30) + '...' 
                    : track.description;
                displayText += ` (${desc})`;
            }
            option.textContent = displayText;
            // 將完整 track 資料存到 option 的 dataset 中，方便後續使用
            option.dataset.trackData = JSON.stringify(track);
            select.appendChild(option);
        });

        if (currentValue && this.musicTracks.some((track) => track.id === currentValue)) {
            select.value = currentValue;
        } else {
            select.value = '';
            this.resetMusicSelection();
        }

        this.toggleMusicPreview();
        // 更新生成按鈕狀態（音樂列表載入後）
        this.updateGenerateButtonState();
    }

    resetMusicSelection() {
        this.stopMusicPlayback(false);
        this.musicSelection.trackId = null;
        this.musicSelection.duration = 0;
        this.musicSelection.start = 0;
        this.musicSelection.end = 0;
        this.musicSelection.fade = true;
        if (this.musicElements.fadeToggle) {
            this.musicElements.fadeToggle.checked = true;
        }
        this.updateMusicRangeInputs();
        this.updateSelectionOverlay();
        if (this.musicElements.currentTime) {
            this.musicElements.currentTime.textContent = `00:00/00:00`;
        }
        if (this.musicElements.videoDuration) {
            this.musicElements.videoDuration.textContent = `00:00`;
        }
        if (this.musicElements.avgSegmentTime) {
            this.musicElements.avgSegmentTime.textContent = '--';
        }
        this.musicSelection.totalDuration = 0;
        // 隱藏音樂資訊
        if (this.musicElements.info) {
            this.musicElements.info.classList.add('hidden');
        }
        if (this.musicElements.emptyState) {
            this.musicElements.emptyState.classList.remove('hidden');
        }
        if (this.musicElements.preview) {
            this.musicElements.preview.classList.add('hidden');
        }
    }

    async handleMusicSelectChange() {
        const select = this.musicElements.select;
        if (!select) return;
        const musicId = select.value;
        if (!musicId) {
            this.resetMusicSelection();
            this.toggleMusicPreview();
            // 更新生成按鈕狀態（未選擇音樂時禁用）
            this.updateGenerateButtonState();
            return;
        }
        await this.prepareMusicPreview(musicId);
        // 更新生成按鈕狀態（選擇音樂後啟用）
        this.updateGenerateButtonState();
    }

    async prepareMusicPreview(musicId) {
        const track = this.musicTracks.find((item) => item.id === musicId);
        if (!track) {
            this.showToast('找不到音樂資料', 'error');
            return;
        }

        try {
            if (this.musicElements.emptyState) this.musicElements.emptyState.classList.add('hidden');
            if (this.musicElements.preview) this.musicElements.preview.classList.remove('hidden');

            const { url } = await ApiClient.music.getUrl(musicId, 3600);
            const response = await fetch(url);
            const arrayBuffer = await response.arrayBuffer();
            const blob = new Blob([arrayBuffer], { type: track.content_type || 'audio/mpeg' });

            if (this.audioObjectUrl) {
                URL.revokeObjectURL(this.audioObjectUrl);
                this.audioObjectUrl = null;
            }

            this.audioObjectUrl = URL.createObjectURL(blob);
            if (this.musicAudio) {
                this.musicAudio.pause();
                this.musicAudio.src = this.audioObjectUrl;
                this.musicAudio.currentTime = 0;
            }

            if (!this.audioContext) {
                const AudioContextClass = window.AudioContext || window.webkitAudioContext;
                if (AudioContextClass) {
                    this.audioContext = new AudioContextClass();
                }
            }

            // 獲取音樂原始總長度
            let totalDuration = 0;
            if (this.audioContext) {
                try {
                    const clonedBuffer = arrayBuffer.slice(0);
                    this.audioBuffer = await this.audioContext.decodeAudioData(clonedBuffer);
                    totalDuration = this.audioBuffer.duration || track.duration || 0;
                } catch (decodeError) {
                    console.warn('音訊解碼失敗，使用預設時長', decodeError);
                    this.audioBuffer = null;
                    totalDuration = track.duration || this.musicAudio.duration || 0;
                }
            } else {
                this.audioBuffer = null;
                totalDuration = track.duration || this.musicAudio.duration || 0;
            }
            
            // 等待音樂載入完成以獲取準確的總長度
            await new Promise((resolve) => {
                if (this.musicAudio.readyState >= 2) {
                    // 已經載入足夠的資料
                    if (Number.isFinite(this.musicAudio.duration) && this.musicAudio.duration > 0) {
                        totalDuration = this.musicAudio.duration;
                    }
                    resolve();
                } else {
                    this.musicAudio.addEventListener('loadedmetadata', () => {
                        if (Number.isFinite(this.musicAudio.duration) && this.musicAudio.duration > 0) {
                            totalDuration = this.musicAudio.duration;
                        }
                        resolve();
                    }, { once: true });
                }
            });

            this.musicSelection.totalDuration = totalDuration;
            this.musicSelection.trackId = musicId;
            this.musicSelection.start = 0;
            // 預設選擇前 180 秒（如果音樂足夠長）
            this.musicSelection.end = Math.min(totalDuration || 180, 180);
            // 影片長度 = 選擇的片段長度
            this.musicSelection.duration = this.musicSelection.end - this.musicSelection.start;
            this.constrainMusicSelection();
            this.musicSelection.fade = this.musicElements.fadeToggle
                ? this.musicElements.fadeToggle.checked
                : true;

            // 顯示音樂詳細資訊
            this.displayMusicInfo(track);

            this.updateMusicRangeInputs();
            this.drawWaveform();
            this.updateSelectionOverlay();
            const selectedDuration = this.musicSelection.duration || 0;
            if (this.musicElements.currentTime) {
                this.musicElements.currentTime.textContent = `00:00/${this.formatTime(selectedDuration)}`;
            }
            // 顯示音樂原始總長度（不會因為選擇範圍變化而改變）
            if (this.musicElements.videoDuration) {
                this.musicElements.videoDuration.textContent = this.formatTime(this.musicSelection.totalDuration || 0);
            }
            // 更新平均分鏡時間
            this.updateAvgSegmentTime();
        } catch (error) {
            console.error('載入音樂預覽失敗:', error);
            this.showToast('載入音樂預覽失敗，請稍後再試', 'error');
        }
    }

    updateMusicRangeInputs() {
        // 不再需要 range 輸入，最大時長由音樂選擇的 in/out 控制
        // 更新時間標記顯示
        this.updateTimeMarkers();
    }
    
    updateTimeMarkers() {
        if (!this.musicSelection.totalDuration) return;
        
        const canvas = this.musicElements.waveform;
        if (!canvas) return;
        
        const totalDuration = this.musicSelection.totalDuration;
        const start = this.musicSelection.start || 0;
        const end = this.musicSelection.end || totalDuration;
        const selectedDuration = end - start;
        
        // 使用 canvas 的實際顯示寬度（clientWidth）來計算位置
        const canvasWidth = canvas.clientWidth || canvas.width;
        const startRatio = start / totalDuration;
        const endRatio = end / totalDuration;
        
        // 更新開始時間標記
        if (this.musicElements.timeMarkerStart) {
            const startX = startRatio * canvasWidth;
            this.musicElements.timeMarkerStart.style.left = `${startX}px`;
            const startLabel = this.musicElements.timeMarkerStart.querySelector('.time-label');
            if (startLabel) {
                startLabel.textContent = this.formatTime(start);
            }
        }
        
        // 更新結束時間標記
        if (this.musicElements.timeMarkerEnd) {
            const endX = endRatio * canvasWidth;
            this.musicElements.timeMarkerEnd.style.left = `${endX}px`;
            const endLabel = this.musicElements.timeMarkerEnd.querySelector('.time-label');
            if (endLabel) {
                endLabel.textContent = this.formatTime(end);
            }
        }
        
        // music-total-duration 顯示音樂原始總長度，不會因為選擇範圍變化而改變
        // 所以這裡不需要更新 videoDuration
    }

    constrainMusicSelection() {
        const totalDuration = this.musicSelection.totalDuration || 0;
        // 不再限制最大時長，由用戶通過拖動 in/out 自由控制
        // 只確保選擇範圍在音樂總時長內
        if (this.musicSelection.start < 0) {
            this.musicSelection.start = 0;
        }
        if (this.musicSelection.end > totalDuration) {
            this.musicSelection.end = totalDuration;
        }
        if (this.musicSelection.end <= this.musicSelection.start) {
            this.musicSelection.end = Math.min(totalDuration, this.musicSelection.start + 0.5);
        }
        // 更新選擇的片段長度
        this.musicSelection.duration = this.musicSelection.end - this.musicSelection.start;

        // 更新平均分鏡時間
        this.updateAvgSegmentTime();

        this.updateMusicRangeInputs();
        this.updateSelectionOverlay();
    }

    // 移除 handleMusicStartChange，因為不再需要 startRange 拉桿

    // 移除 handleMusicEndChange，因為不再需要 endRange 拉桿

    handleWaveformMouseDown(e) {
        if (!this.musicSelection.totalDuration) return;
        
        const canvas = this.musicElements.waveform;
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const width = canvas.width;
        const totalDuration = this.musicSelection.totalDuration;
        const clickRatio = Math.max(0, Math.min(1, x / width));
        const clickTime = clickRatio * totalDuration;

        const startRatio = this.musicSelection.start / totalDuration;
        const endRatio = this.musicSelection.end / totalDuration;
        const startX = startRatio * width;
        const endX = endRatio * width;

        // 判斷點擊位置
        const threshold = 10; // 像素閾值
        if (Math.abs(x - startX) < threshold) {
            this.isDragging = true;
            this.dragType = 'start';
        } else if (Math.abs(x - endX) < threshold) {
            this.isDragging = true;
            this.dragType = 'end';
        } else if (x >= startX && x <= endX) {
            this.isDragging = true;
            this.dragType = 'selection';
            this.dragStartX = x;
            this.dragStartTime = this.musicSelection.start;
        } else {
            // 點擊選擇範圍外，直接設置新的選擇（預設 180 秒）
            const defaultDuration = 180;
            this.musicSelection.start = Math.max(0, clickTime - defaultDuration / 2);
            this.musicSelection.end = Math.min(totalDuration, this.musicSelection.start + defaultDuration);
            this.musicSelection.duration = this.musicSelection.end - this.musicSelection.start;
            this.constrainMusicSelection();
        }

        e.preventDefault();
    }

    handleWaveformMouseMove(e) {
        if (!this.isDragging || !this.musicSelection.totalDuration) return;

        const canvas = this.musicElements.waveform;
        if (!canvas) return;
        const rect = canvas.getBoundingClientRect();
        const x = Math.max(0, Math.min(canvas.width, e.clientX - rect.left));
        const width = canvas.width;
        const totalDuration = this.musicSelection.totalDuration;
        const time = (x / width) * totalDuration;

        if (this.dragType === 'start') {
            let newStart = Math.max(0, Math.min(time, this.musicSelection.end - 0.5));
            this.musicSelection.start = newStart;
            this.musicSelection.duration = this.musicSelection.end - this.musicSelection.start;
        } else if (this.dragType === 'end') {
            let newEnd = Math.max(this.musicSelection.start + 0.5, Math.min(time, totalDuration));
            this.musicSelection.end = newEnd;
            this.musicSelection.duration = this.musicSelection.end - this.musicSelection.start;
        } else if (this.dragType === 'selection') {
            const deltaX = x - this.dragStartX;
            const deltaTime = (deltaX / width) * totalDuration;
            let newStart = this.dragStartTime + deltaTime;
            const currentDuration = this.musicSelection.end - this.musicSelection.start;
            newStart = Math.max(0, Math.min(newStart, totalDuration - currentDuration));
            this.musicSelection.start = newStart;
            this.musicSelection.end = newStart + currentDuration;
            this.musicSelection.duration = currentDuration;
        }

        // 更新相對時間顯示
        const selectedDuration = this.musicSelection.duration || 0;
        if (this.musicElements.currentTime) {
            this.musicElements.currentTime.textContent = `00:00/${this.formatTime(selectedDuration)}`;
        }
        // 更新平均分鏡時間
        this.updateAvgSegmentTime();

        this.updateMusicRangeInputs();
        this.updateSelectionOverlay();
        e.preventDefault();
    }

    handleWaveformMouseUp() {
        if (this.isDragging) {
            this.isDragging = false;
            this.dragType = null;
        }
    }

    drawWaveform() {
        const canvas = this.musicElements.waveform;
        if (!canvas) return;
        const width = canvas.clientWidth || 600;
        const height = canvas.clientHeight || 140;
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, width, height);

        if (!this.audioBuffer) {
            ctx.fillStyle = '#dbe6ff';
            ctx.fillRect(0, height / 2 - 2, width, 4);
            return;
        }

        const rawData = this.audioBuffer.getChannelData(0);
        const samples = width;
        const blockSize = Math.max(1, Math.floor(rawData.length / samples));
        const amp = height / 2;

        ctx.fillStyle = '#eef3ff';
        ctx.fillRect(0, 0, width, height);
        ctx.fillStyle = '#4d73ff';

        for (let i = 0; i < samples; i++) {
            let min = 1.0;
            let max = -1.0;
            for (let j = 0; j < blockSize; j++) {
                const data = rawData[i * blockSize + j] || 0;
                if (data < min) min = data;
                if (data > max) max = data;
            }
            const y1 = (1 + min) * amp;
            const y2 = (1 + max) * amp;
            ctx.fillRect(i, y1, 1, Math.max(1, y2 - y1));
        }
    }

    updateSelectionOverlay() {
        const overlay = this.musicElements.overlay;
        const playhead = this.musicElements.playhead;
        const totalDuration = this.musicSelection.totalDuration || 0;

        if (!overlay || totalDuration <= 0) {
            if (overlay) {
                overlay.style.width = '0%';
            }
            if (playhead) {
                playhead.classList.add('hidden');
            }
            return;
        }

        const startRatio = this.musicSelection.start / totalDuration;
        const endRatio = this.musicSelection.end / totalDuration;
        overlay.style.left = `${startRatio * 100}%`;
        overlay.style.width = `${Math.max(0, endRatio - startRatio) * 100}%`;

        if (playhead) {
            playhead.classList.remove('hidden');
            // playhead 位置應該基於當前播放時間相對於總時長的比例
            if (this.musicAudio && this.isPlaying) {
                const currentRatio = this.musicAudio.currentTime / totalDuration;
                playhead.style.left = `${Math.min(100, Math.max(0, currentRatio * 100))}%`;
            } else {
                playhead.style.left = `${startRatio * 100}%`;
            }
        }
        
        // 同時更新時間標記
        this.updateTimeMarkers();
    }

    playMusicPreview() {
        if (!this.musicSelection.trackId || !this.musicAudio) {
            this.showToast('請先選擇音樂', 'info');
            return;
        }
        
        if (this.isPlaying) {
            // 如果正在播放，則停止
            this.stopMusicPlayback();
            return;
        }

        try {
            this.isPlaying = true;
            this.musicAudio.currentTime = this.musicSelection.start || 0;
            const playPromise = this.musicAudio.play();
            if (playPromise?.catch) {
                playPromise.catch((error) => {
                    console.warn('音樂預覽播放被阻擋:', error);
                    this.isPlaying = false;
                });
            }
            // 更新按鈕圖標
            if (this.musicElements.playBtn) {
                this.musicElements.playBtn.src = '/static/icons/pause.svg';
            }
        } catch (error) {
            console.error('播放音樂預覽失敗:', error);
            this.isPlaying = false;
        }
    }

    stopMusicPlayback(resetPosition = true) {
        if (!this.musicAudio) return;
        this.isPlaying = false;
        this.musicAudio.pause();
        if (resetPosition) {
            this.musicAudio.currentTime = this.musicSelection.start || 0;
            const selectedDuration = this.musicSelection.duration || 0;
            if (this.musicElements.currentTime) {
                this.musicElements.currentTime.textContent = `00:00/${this.formatTime(selectedDuration)}`;
            }
            if (this.musicElements.playhead && this.musicSelection.totalDuration) {
                const ratio = (this.musicSelection.start || 0) / (this.musicSelection.totalDuration || 1);
                this.musicElements.playhead.style.left = `${ratio * 100}%`;
            }
        }
        // 更新按鈕圖標
        if (this.musicElements.playBtn) {
            this.musicElements.playBtn.src = '/static/icons/play.svg';
        }
    }

    handleMusicTimeUpdate() {
        if (!this.musicAudio) return;
        const current = this.musicAudio.currentTime || 0;
        const start = this.musicSelection.start || 0;
        const selectedDuration = this.musicSelection.duration || 0;
        
        // 計算相對時間（當前時間 - 開始時間）
        const relativeTime = Math.max(0, current - start);
        
        // 更新相對時間顯示：{相對秒數}/選擇的片段長度
        if (this.musicElements.currentTime) {
            this.musicElements.currentTime.textContent = `${this.formatTime(relativeTime)}/${this.formatTime(selectedDuration)}`;
        }

        const totalDuration = this.musicSelection.totalDuration || this.musicAudio.duration || 0;
        if (totalDuration > 0 && this.musicElements.playhead) {
            const ratio = Math.min(1, current / totalDuration);
            this.musicElements.playhead.style.left = `${ratio * 100}%`;
        }

        if (current >= (this.musicSelection.end || duration) - 0.05) {
            this.stopMusicPlayback();
            // 重置為開始位置
            if (this.musicElements.currentTime) {
                this.musicElements.currentTime.textContent = `${this.formatTime(0)}/${this.formatTime(selectedDuration)}`;
            }
        }
    }

    displayMusicInfo(track) {
        if (!track || !this.musicElements.info) return;
        
        const titleEl = this.musicElements.infoTitle;
        const descEl = this.musicElements.infoDescription;
        
        if (titleEl) {
            let title = track.name;
            if (track.composer) {
                title += ` — ${track.composer}`;
            }
            titleEl.textContent = title;
        }
        
        if (descEl) {
            if (track.description) {
                descEl.textContent = track.description;
                descEl.classList.remove('hidden');
            } else {
                descEl.textContent = '';
                descEl.classList.add('hidden');
            }
        }
        
        this.musicElements.info.classList.remove('hidden');
    }

    toggleMusicPreview() {
        if (!this.musicElements.preview) return;
        if (this.musicSelection.trackId) {
            this.musicElements.preview.classList.remove('hidden');
            this.musicElements.emptyState?.classList.add('hidden');
        } else {
            this.musicElements.preview.classList.add('hidden');
            this.musicElements.emptyState?.classList.remove('hidden');
            // 隱藏音樂資訊
            if (this.musicElements.info) {
                this.musicElements.info.classList.add('hidden');
            }
        }
    }

    formatTime(value) {
        if (!Number.isFinite(value)) return '0:00';
        const totalSeconds = Math.max(0, Math.floor(value));
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        return `${minutes}:${seconds.toString().padStart(2, '0')}`;
    }

    updateAvgSegmentTime() {
        if (!this.musicElements.avgSegmentTime) return;
        
        const selectedDuration = this.musicSelection.duration || 0;
        const eventCount = this.selectedEvents.length;
        
        if (eventCount > 0 && selectedDuration > 0) {
            const avgTime = selectedDuration / eventCount;
            // 顯示到小數點後1位
            this.musicElements.avgSegmentTime.textContent = `${avgTime.toFixed(1)}秒`;
        } else {
            this.musicElements.avgSegmentTime.textContent = '--';
        }
    }

    async init() {
        this.bindEvents();
        this.initializeMusicAudio();
        await this.syncSelectedDate();
        // 合併後的頁面，直接載入 Vlog
        await this.loadDailyVlog();
        // 初始化時更新生成按鈕狀態
        this.updateGenerateButtonState();
    }

    bindEvents() {
        const generateVlogBtn = document.getElementById('generateVlogBtn');
        if (generateVlogBtn) {
            generateVlogBtn.addEventListener('click', () => {
                this.selectedEvents = [];
                this.openEventSelectModal();
            });
        }

        const aiSelectBtn = document.getElementById('aiSelectBtn');
        if (aiSelectBtn) {
            aiSelectBtn.addEventListener('click', () => this.aiSelectEvents());
        }

        const confirmEventSelect = document.getElementById('confirmEventSelect');
        if (confirmEventSelect) {
            confirmEventSelect.addEventListener('click', () => this.confirmEventSelection());
        }

        const cancelEventSelect = document.getElementById('cancelEventSelect');
        if (cancelEventSelect) {
            cancelEventSelect.addEventListener('click', () => this.closeEventSelectModal());
        }

        const closeEventModal = document.getElementById('closeEventModal');
        if (closeEventModal) {
            closeEventModal.addEventListener('click', () => this.closeEventSelectModal());
        }

        const diaryDate = document.getElementById('diaryDate');
        if (diaryDate) {
            diaryDate.addEventListener('change', async () => {
                await this.syncSelectedDate();
                this.loadDailyVlog();
            });
        }

        // 最大時長現在由音樂選擇的 in/out 控制，不再需要單獨的 vlogDuration 輸入

        const backToEventSelect = document.getElementById('backToEventSelect');
        if (backToEventSelect) {
            backToEventSelect.addEventListener('click', () => this.backToEventSelect());
        }

        const confirmVlogGenerate = document.getElementById('confirmVlogGenerate');
        if (confirmVlogGenerate) {
            confirmVlogGenerate.addEventListener('click', () => this.generateVlog());
        }

        const closeSettingsModal = document.getElementById('closeSettingsModal');
        if (closeSettingsModal) {
            closeSettingsModal.addEventListener('click', () => this.closeVlogSettingsModal());
        }

        const playBtn = document.getElementById('playDailyVlogBtn');
        if (playBtn) {
            playBtn.addEventListener('click', () => this.playDailyVlog());
        }

        const deleteBtn = document.getElementById('deleteDailyVlogBtn');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', () => this.deleteDailyVlog());
        }

        const generateBtn = document.getElementById('generateVlogBtn');
        if (generateBtn) {
            generateBtn.addEventListener('click', () => {
                this.selectedEvents = [];
                this.openEventSelectModal();
            });
        }

        this.musicElements = {
            select: document.getElementById('musicSelect'),
            preview: document.getElementById('musicPreview'),
            emptyState: document.getElementById('musicEmptyState'),
            info: document.getElementById('musicInfo'),
            infoTitle: document.getElementById('musicInfoTitle'),
            infoDescription: document.getElementById('musicInfoDescription'),
            waveform: document.getElementById('musicWaveform'),
            overlay: document.getElementById('musicSelectionOverlay'),
            playhead: document.getElementById('musicPlayhead'),
            currentTime: document.getElementById('musicCurrentTime'),
            videoDuration: document.getElementById('musicTotalDuration'),
            avgSegmentTime: document.getElementById('musicAvgSegmentTime'),
            playBtn: document.getElementById('musicPlayBtn'),
            fadeToggle: document.getElementById('musicFadeToggle'),
            timeMarkerStart: document.getElementById('timeMarkerStart'),
            timeMarkerEnd: document.getElementById('timeMarkerEnd'),
        };

        if (this.musicElements.select) {
            this.musicElements.select.addEventListener('change', () => this.handleMusicSelectChange());
        }
        if (this.musicElements.playBtn) {
            this.musicElements.playBtn.addEventListener('click', () => this.playMusicPreview());
        }
        // 移除停止按鈕，因為播放按鈕現在可以切換播放/暫停
        if (this.musicElements.fadeToggle) {
            this.musicElements.fadeToggle.addEventListener('change', () => {
                this.musicSelection.fade = !!this.musicElements.fadeToggle.checked;
            });
        }

        // 波形圖拖動功能
        const waveformWrapper = document.querySelector('.music-waveform-wrapper');
        if (this.musicElements.waveform && waveformWrapper) {
            this.musicElements.waveform.addEventListener('mousedown', (e) => this.handleWaveformMouseDown(e));
            document.addEventListener('mousemove', (e) => this.handleWaveformMouseMove(e));
            document.addEventListener('mouseup', () => this.handleWaveformMouseUp());
            this.musicElements.waveform.style.cursor = 'pointer';
            
            // 更新游標樣式
            this.musicElements.waveform.addEventListener('mousemove', (e) => {
                if (!this.musicSelection.duration) return;
                const canvas = this.musicElements.waveform;
                const rect = canvas.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const width = canvas.width;
                const duration = this.musicSelection.duration;
                const startRatio = this.musicSelection.start / duration;
                const endRatio = this.musicSelection.end / duration;
                const startX = startRatio * width;
                const endX = endRatio * width;
                const threshold = 10;
                
                if (Math.abs(x - startX) < threshold || Math.abs(x - endX) < threshold) {
                    canvas.style.cursor = 'ew-resize';
                } else if (x >= startX && x <= endX) {
                    canvas.style.cursor = 'move';
                } else {
                    canvas.style.cursor = 'pointer';
                }
            });
        }
    }

    async syncSelectedDate() {
        // 優先從 URL query 參數讀取日期
        const urlParams = new URLSearchParams(window.location.search);
        const dateParam = urlParams.get('date');
        if (dateParam) {
            const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
            if (dateRegex.test(dateParam)) {
                const date = new Date(dateParam + "T00:00:00");
                if (!isNaN(date.getTime())) {
                    this.selectedDate = dateParam;
                    console.log(`[VlogManager] syncSelectedDate: 從 URL 參數獲取日期 = ${this.selectedDate}`);
                    return;
                }
            }
        }
        
        // 其次從 diaryDate 元素讀取
        const diaryDate = document.getElementById('diaryDate');
        if (diaryDate && diaryDate.value) {
            this.selectedDate = diaryDate.value;
            console.log(`[VlogManager] syncSelectedDate: 從 diaryDate 獲取日期 = ${this.selectedDate}`);
        } else {
            // 最後使用使用者時區獲取今天的日期，而不是 UTC
            try {
                const settingsResponse = await ApiClient.settings.get();
                const settings = settingsResponse.settings || settingsResponse;
                const userTimezone = settings?.timezone || 'Asia/Taipei';
                
                // 使用使用者時區獲取今天的日期
                const now = new Date();
                // 將 UTC 時間轉換為使用者時區的日期字符串
                const userDateStr = this.getDateInTimezone(now, userTimezone);
                this.selectedDate = userDateStr;
                console.log(`[VlogManager] syncSelectedDate: diaryDate 為空，使用使用者時區(${userTimezone})的今天日期 = ${this.selectedDate}`);
            } catch (error) {
                console.warn(`[VlogManager] 無法獲取使用者時區設定，使用本地時區: ${error}`);
                // 如果無法獲取時區設定，使用本地時區（瀏覽器時區）
                const now = new Date();
                const year = now.getFullYear();
                const month = String(now.getMonth() + 1).padStart(2, '0');
                const day = String(now.getDate()).padStart(2, '0');
                this.selectedDate = `${year}-${month}-${day}`;
                console.log(`[VlogManager] syncSelectedDate: 使用本地時區的今天日期 = ${this.selectedDate}`);
            }
        }
    }
    
    /**
     * 將日期轉換為指定時區的日期字符串 (YYYY-MM-DD)
     * @param {Date} date - 要轉換的日期對象
     * @param {string} timezone - 時區名稱，例如 'Asia/Taipei'
     * @returns {string} 日期字符串 (YYYY-MM-DD)
     */
    getDateInTimezone(date, timezone) {
        try {
            // 使用 Intl.DateTimeFormat 來處理時區轉換
            const formatter = new Intl.DateTimeFormat('en-CA', {
                timeZone: timezone,
                year: 'numeric',
                month: '2-digit',
                day: '2-digit'
            });
            return formatter.format(date);
        } catch (error) {
            console.warn(`[VlogManager] 時區轉換失敗，使用本地日期: ${error}`);
            // 如果時區轉換失敗，使用本地時區
            const year = date.getFullYear();
            const month = String(date.getMonth() + 1).padStart(2, '0');
            const day = String(date.getDate()).padStart(2, '0');
            return `${year}-${month}-${day}`;
        }
    }

    async loadDailyVlog() {
        this.stopPolling();

        // 確保 selectedDate 已設置
        if (!this.selectedDate) {
            await this.syncSelectedDate();
        }
        
        console.log(`[VlogManager] loadDailyVlog: selectedDate = ${this.selectedDate}`);

        const loader = document.getElementById('dailyVlogLoader');
        if (loader) loader.classList.remove('hidden');

        try {
            const data = await ApiClient.vlogs.getDaily(this.selectedDate);
            this.dailyVlog = data;
            await this.renderDailyVlog();

            // 如果狀態是 processing 或 pending，開始輪詢以追蹤進度
            if (data && (data.status === 'processing' || data.status === 'pending')) {
                // 如果是第一次載入且狀態是 pending，立即開始輪詢（1秒後）
                // 否則正常輪詢（5秒後）
                // 注意：刷新頁面時，如果狀態是 processing，應該立即開始輪詢（使用較短的延遲）
                const isNewVlog = data.status === 'pending';
                const shouldImmediate = isNewVlog || data.status === 'processing';
                this.startPolling(shouldImmediate);
                console.log(`[VlogManager] 開始輪詢 vlog 狀態: status=${data.status}, immediate=${shouldImmediate}`);
            } else {
                this.stopPolling();
                console.log(`[VlogManager] vlog 狀態為 ${data?.status || 'null'}，停止輪詢`);
            }
        } catch (error) {
            // 404 表示當日沒有 Vlog，這是正常情況，不需要顯示錯誤
            if (error && typeof error.message === 'string' && error.message.includes('404')) {
                this.dailyVlog = null;
                await this.renderDailyVlog();
                this.stopPolling();
            } else {
                // 其他錯誤不顯示警告，只記錄到 console
                console.error('載入每日 Vlog 失敗:', error);
                this.dailyVlog = null;
                await this.renderDailyVlog();
                this.stopPolling();
            }
        } finally {
            if (loader) loader.classList.add('hidden');
        }
    }

    startPolling(immediate = false) {
        this.stopPolling();
        // 如果 immediate 為 true，立即開始第一次輪詢；否則等待 5 秒
        const delay = immediate ? 1000 : 5000; // 立即模式：1秒後開始，正常模式：5秒
        this.pollTimer = setTimeout(() => this.loadDailyVlog(), delay);
    }

    stopPolling() {
        if (this.pollTimer) {
            clearTimeout(this.pollTimer);
            this.pollTimer = null;
        }
    }

    async renderDailyVlog() {
        // 更新生成按鈕狀態：如果 vlog 狀態是 processing 或 pending，禁用按鈕
        this.updateGenerateButtonState();

        const titleEl = document.getElementById('dailyVlogTitle');
        const statusEl = document.getElementById('dailyVlogStatus');
        const dateEl = document.getElementById('dailyVlogDate');
        const durationEl = document.getElementById('dailyVlogDuration');
        const messageEl = document.getElementById('dailyVlogMessage');
        const progressBar = document.getElementById('dailyVlogProgressBar');
        const progressFill = document.getElementById('dailyVlogProgressFill');
        const progressValue = document.getElementById('dailyVlogProgressValue');
        const videoEl = document.getElementById('dailyVlogVideo');
        const placeholder = document.getElementById('dailyVlogPlaceholder');
        const loader = document.getElementById('dailyVlogLoader');
        const deleteBtn = document.getElementById('deleteDailyVlogBtn');

        if (!titleEl || !statusEl || !messageEl) return;

        if (!this.dailyVlog) {
            titleEl.textContent = `${this.selectedDate} 的 Vlog`;
            statusEl.textContent = '尚未生成';
            if (dateEl) dateEl.textContent = this.selectedDate || '--';
            if (durationEl) durationEl.textContent = '-';
            messageEl.textContent = '請點擊「生成 Vlog」來建立今日影片。';
            this.updateProgressUI(null, progressBar, progressFill, progressValue);
            this.hideVideoPlayer(videoEl, placeholder, loader, '目前沒有可預覽的影片');
            if (deleteBtn) deleteBtn.classList.add('hidden');
            this.currentVideoUrl = null;
            this.currentVideoId = null;
            return;
        }

        const { id, title, status, progress, status_message: statusMessage, duration, target_date, thumbnail_s3_key } = this.dailyVlog;
        titleEl.textContent = title || `${this.selectedDate} 的 Vlog`;
        statusEl.textContent = this.translateStatus(status);
        if (dateEl) dateEl.textContent = target_date || this.selectedDate || '--';
        if (durationEl) durationEl.textContent = duration ? `${Math.round(duration)} 秒` : '-';
        messageEl.textContent = statusMessage || this.getDefaultMessage(status);

        // 保留進度條顯示（處理中時顯示）
        this.updateProgressUI(status === 'processing' ? progress : null, progressBar, progressFill, progressValue);

        if (deleteBtn) {
            deleteBtn.classList.toggle('hidden', status !== 'completed' && status !== 'failed');
        }

        if (status === 'completed') {
            // 先顯示縮圖（如果有）
            const thumbnailEl = document.getElementById('dailyVlogThumbnail');
            if (thumbnail_s3_key && thumbnailEl) {
                try {
                    const { url } = await ApiClient.vlogs.getThumbnailUrl(id, 3600);
                    thumbnailEl.src = url;
                    thumbnailEl.classList.remove('hidden');
                    // 點擊縮圖時播放影片
                    thumbnailEl.onclick = () => {
                        thumbnailEl.classList.add('hidden');
                        this.prepareVideoSource(id, videoEl, placeholder, loader);
                    };
                } catch (error) {
                    console.warn('無法載入縮圖:', error);
                    thumbnailEl.classList.add('hidden');
                }
            }
            // 準備影片源（但不自動播放）
            await this.prepareVideoSource(id, videoEl, placeholder, loader, false);
        } else {
            const placeholderMessage = status === 'processing'
                ? '影片生成中，請稍候…'
                : status === 'failed'
                ? '影片生成失敗'
                : '任務已排程，等待開始生成。';
            const showSpinner = status === 'processing';
            this.hideVideoPlayer(videoEl, placeholder, loader, placeholderMessage, showSpinner);
            // 隱藏縮圖
            const thumbnailEl = document.getElementById('dailyVlogThumbnail');
            if (thumbnailEl) thumbnailEl.classList.add('hidden');
        }
    }

    translateStatus(status) {
        switch (status) {
            case 'pending':
                return '等待中';
            case 'processing':
                return '生成中';
            case 'completed':
                return '已完成';
            case 'failed':
                return '失敗';
            default:
                return status || '';
        }
    }

    getDefaultMessage(status) {
        switch (status) {
            case 'pending':
                return '任務已排程，等待開始。';
            case 'processing':
                return '影片處理中，請稍候。';
            case 'completed':
                return '影片已完成生成。';
            case 'failed':
                return '生成失敗，請重新嘗試。';
            default:
                return '';
        }
    }

    updateProgressUI(progress, progressBar, progressFill, progressValue) {
        if (!progressBar || !progressFill || !progressValue) return;

        if (progress === null || progress === undefined) {
            progressBar.classList.add('hidden');
            progressFill.style.width = '0%';
            progressValue.textContent = '';
            return;
        }

        const clamped = Math.max(0, Math.min(100, progress));
        progressBar.classList.remove('hidden');
        progressFill.style.width = `${clamped}%`;
        progressValue.textContent = `${Math.round(clamped)}%`;
    }

    hideVideoPlayer(videoEl, placeholder, loader, message = '目前沒有可預覽的影片', showSpinner = false) {
        if (videoEl) {
            videoEl.style.display = 'none';
            videoEl.pause();
            videoEl.removeAttribute('src');
            videoEl.load();
        }
        // 隱藏縮圖
        const thumbnailEl = document.getElementById('dailyVlogThumbnail');
        if (thumbnailEl) thumbnailEl.classList.add('hidden');
        if (placeholder) {
            placeholder.classList.remove('hidden');
            const textEl = placeholder.querySelector('#dailyVlogPlaceholderText');
            if (textEl) textEl.textContent = message;
        }
        if (loader) {
            loader.classList.toggle('hidden', !showSpinner);
        }
    }

    async prepareVideoSource(vlogId, videoEl, placeholder, loader, autoPlay = false) {
        if (!videoEl || !placeholder) return;

        if (this.currentVideoId === vlogId && this.currentVideoUrl) {
            videoEl.style.display = 'block';
            placeholder.classList.add('hidden');
            if (loader) loader.classList.add('hidden');
            if (autoPlay) {
                videoEl.play().catch(() => {});
            }
            return;
        }

        try {
            const { url } = await ApiClient.vlogs.getUrl(vlogId, 3600);
            this.currentVideoUrl = url;
            this.currentVideoId = vlogId;
            videoEl.src = url;
            videoEl.style.display = 'block';
            placeholder.classList.add('hidden');
            if (loader) loader.classList.add('hidden');
            videoEl.load();
            // 隱藏縮圖
            const thumbnailEl = document.getElementById('dailyVlogThumbnail');
            if (thumbnailEl) thumbnailEl.classList.add('hidden');
            if (autoPlay) {
                videoEl.play().catch(() => {});
            }
        } catch (error) {
            console.error('取得 Vlog 播放 URL 失敗:', error);
            // 不顯示錯誤提示，只記錄到 console
            this.currentVideoUrl = null;
            this.currentVideoId = null;
            this.hideVideoPlayer(videoEl, placeholder, loader, '無法取得影片來源');
        }
    }

    // 移除播放按鈕功能，影片直接顯示 controls

    async deleteDailyVlog() {
        if (!this.dailyVlog) {
            this.showToast('今日尚未生成 Vlog', 'info');
            return;
        }
        if (!confirm('確定要刪除今日的 Vlog 嗎？')) return;

        try {
            await ApiClient.vlogs.delete(this.dailyVlog.id);
            this.showToast('Vlog 已刪除', 'success');
            this.dailyVlog = null;
            this.loadDailyVlog();
        } catch (error) {
            console.error('刪除 Vlog 失敗:', error);
            this.showToast('刪除失敗，請稍後再試', 'error');
        }
    }

    openEventSelectModal() {
        const modal = document.getElementById('eventSelectModal');
        if (modal) {
            modal.classList.add('show');
            const diaryDate = document.getElementById('diaryDate');
            if (diaryDate && diaryDate.value) {
                this.selectedDate = diaryDate.value;
            }
            this.loadDateEvents(this.selectedDate);
        }
    }

    closeEventSelectModal() {
        const modal = document.getElementById('eventSelectModal');
        if (modal) {
            modal.classList.remove('show');
        }
    }

    async loadDateEvents(date) {
        const eventList = document.getElementById('eventList');
        if (!eventList) return;

        eventList.innerHTML = '<div class="event-loading">載入中...</div>';

        try {
            const response = await ApiClient.vlogs.getDateEvents(date);
            if (response.events && response.events.length > 0) {
                this.renderEventList(response.events);
            } else {
                eventList.innerHTML = '<div class="empty-state"><p>該日期沒有事件記錄</p></div>';
            }
        } catch (error) {
            console.error('載入事件失敗:', error);
            eventList.innerHTML = '<div class="error-state"><p>載入失敗,請重試</p></div>';
        }
    }

    renderEventList(events) {
        const eventList = document.getElementById('eventList');
        if (!eventList) return;

        eventList.innerHTML = events.map(event => {
            const time = event.start_time ? new Date(event.start_time).toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' }) : '未知時間';
            const duration = event.duration ? `${Math.floor(event.duration)}秒` : '';
            const isChecked = this.selectedEvents.includes(String(event.id)) ? 'checked' : '';

            return `
                <div class="event-item" data-event-id="${event.id}">
                    <input type="checkbox" class="event-checkbox" id="event-${event.id}" ${isChecked} />
                    <label for="event-${event.id}" class="event-label">
                        <div class="event-header">
                            <span class="event-time">${time}</span>
                            <span class="event-duration">${duration}</span>
                        </div>
                        <div class="event-info">
                            <span class="event-action">${event.action || '未知活動'}</span>
                            <span class="event-scene">${event.scene || ''}</span>
                        </div>
                        <div class="event-summary">${event.summary || '無描述'}</div>
                    </label>
                </div>
            `;
        }).join('');

        const checkboxes = eventList.querySelectorAll('.event-checkbox');
        checkboxes.forEach(checkbox => {
            checkbox.addEventListener('change', () => this.updateSelectedEvents());
        });
    }

    updateSelectedEvents() {
        const checkboxes = document.querySelectorAll('.event-checkbox:checked');
        this.selectedEvents = Array.from(checkboxes).map(cb => cb.closest('.event-item').dataset.eventId);

        const confirmBtn = document.getElementById('confirmEventSelect');
        if (confirmBtn) {
            confirmBtn.disabled = this.selectedEvents.length === 0;
        }
        
        // 更新平均分鏡時間（如果已經在設定頁面）
        this.updateAvgSegmentTime();
    }

    async aiSelectEvents() {
        const aiSelectBtn = document.getElementById('aiSelectBtn');
        const aiSelectLimit = document.getElementById('aiSelectLimit');
        const limit = aiSelectLimit ? parseInt(aiSelectLimit.value, 10) : 20;

        if (!aiSelectBtn || !this.selectedDate) return;

        const originalText = aiSelectBtn.innerHTML;
        aiSelectBtn.disabled = true;
        aiSelectBtn.innerHTML = '<span class="loading-spinner"></span> AI 分析中...';

        try {
            const response = await ApiClient.vlogs.aiSelectEvents(this.selectedDate, null, limit);

            if (response.selected_event_ids && response.selected_event_ids.length > 0) {
                const checkboxes = document.querySelectorAll('.event-checkbox');
                checkboxes.forEach(cb => cb.checked = false);

                response.selected_event_ids.forEach(eventId => {
                    const checkbox = document.getElementById(`event-${eventId}`);
                    if (checkbox) checkbox.checked = true;
                });

                this.updateSelectedEvents();
                // 移除成功提示，直接顯示選擇結果更直覺
            } else {
                this.showToast('AI 未找到合適的片段,請手動選擇', 'info');
            }
        } catch (error) {
            console.error('AI 選擇失敗:', error);
            // 移除錯誤提示，靜默處理
        } finally {
            aiSelectBtn.disabled = false;
            aiSelectBtn.innerHTML = originalText;
        }
    }

    confirmEventSelection() {
        if (this.selectedEvents.length === 0) return;
        this.closeEventSelectModal();
        this.openVlogSettingsModal();
        // 更新平均分鏡時間（進入設定頁面後）
        this.updateAvgSegmentTime();
    }

    openVlogSettingsModal() {
        const modal = document.getElementById('vlogSettingsModal');
        if (modal) {
            modal.classList.add('show');
            const titleInput = document.getElementById('vlogTitle');
            if (titleInput) {
                titleInput.value = `${this.selectedDate} 的 Vlog`;
            }
            this.loadMusicTracks();
            this.toggleMusicPreview();
        }
    }

    closeVlogSettingsModal() {
        const modal = document.getElementById('vlogSettingsModal');
        if (modal) {
            modal.classList.remove('show');
        }
        this.stopMusicPlayback();
    }

    backToEventSelect() {
        this.closeVlogSettingsModal();
        this.openEventSelectModal();
    }

    async generateVlog() {
        // 驗證：必須選擇音樂才能生成
        if (!this.musicSelection.trackId) {
            this.showToast('請先選擇音樂才能生成 Vlog', 'error');
            return;
        }

        const title = document.getElementById('vlogTitle')?.value || null;
        // 最大時長由音樂選擇的 in/out 控制
        let duration = 180; // 預設值
        if (this.musicSelection.trackId) {
            // 如果有選擇音樂，使用音樂選擇的時長作為最大時長
            const selectedDuration = (this.musicSelection.end || 0) - (this.musicSelection.start || 0);
            if (selectedDuration > 0) {
                duration = Math.ceil(selectedDuration);
            }
        }
        const resolution = document.getElementById('vlogResolution')?.value || '1080p';

        const confirmBtn = document.getElementById('confirmVlogGenerate');
        if (!confirmBtn) return;

        const originalText = confirmBtn.innerHTML;
        confirmBtn.disabled = true;
        confirmBtn.innerHTML = '<span class="loading-spinner"></span> 生成中...';

        try {
            const payload = {
                targetDate: this.selectedDate,
                eventIds: this.selectedEvents,
                title: title,
                maxDuration: duration,
                resolution: resolution
            };

            // 準備音樂參數
            let musicParams = {};
            if (this.musicSelection.trackId) {
                musicParams.musicId = this.musicSelection.trackId;
                musicParams.musicStart = Number((this.musicSelection.start || 0).toFixed(3));
                musicParams.musicEnd = Number((this.musicSelection.end || 0).toFixed(3));
                musicParams.musicFade = !!this.musicSelection.fade;
                musicParams.musicVolume = this.musicSelection.volume;
                console.log('[Vlog] 音樂參數:', musicParams);
            }

            await ApiClient.vlogs.create({
                ...payload,
                ...musicParams
            });

            // 移除成功提示，直接關閉視窗並刷新更直覺
            this.closeVlogSettingsModal();
            
            // 立即載入 Vlog 狀態，loadDailyVlog 會自動開始輪詢（如果狀態是 pending 或 processing）
            await this.loadDailyVlog();
            // 更新生成按鈕狀態（生成後可能變為 processing 狀態）
            this.updateGenerateButtonState();
        } catch (error) {
            console.error('生成 Vlog 失敗:', error);
            this.showToast('生成 Vlog 失敗,請重試', 'error');
        } finally {
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = originalText;
        }
    }

    updateGenerateButtonState() {
        const generateVlogBtn = document.getElementById('generateVlogBtn');
        if (!generateVlogBtn) return;

        // 檢查 vlog 狀態
        const status = this.dailyVlog?.status;
        const isProcessing = status === 'processing' || status === 'pending';

        // 只有在 processing 或 pending 時禁用按鈕
        // completed、failed 或 null（沒有 vlog）時，按鈕可以點擊
        // 注意：音樂選擇的檢查在 generateVlog() 函數中進行，不在這裡禁用按鈕
        // 這樣用戶可以先點擊按鈕打開設置模態框，然後再選擇音樂
        if (isProcessing) {
            generateVlogBtn.disabled = true;
            generateVlogBtn.classList.add('disabled');
            generateVlogBtn.title = 'Vlog 正在生成中，請稍候';
        } else {
            // completed、failed 或沒有 vlog 時，按鈕可以點擊
            generateVlogBtn.disabled = false;
            generateVlogBtn.classList.remove('disabled');
            generateVlogBtn.title = '';
        }
    }

    showToast(message, type = 'info') {
        alert(message);
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.vlogManager = new VlogManager();
    });
} else {
    window.vlogManager = new VlogManager();
}

export default VlogManager;

