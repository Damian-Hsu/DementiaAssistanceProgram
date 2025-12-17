import { ApiClient } from "/static/js/APIClient.js";
import { AuthService } from "/static/js/AuthService.js";
import { EventService } from "/static/js/services/EventService.js";

window.ApiClient = ApiClient;
window.AuthService = AuthService;

// ====== 小工具 ======
function el(id) { return document.getElementById(id); }
function fmt(x) { return (x === null || x === undefined || x === "") ? "—" : String(x); }
function setDisabled(n, b) { if (n) n.disabled = !!b; }

function formatEventTime(isoString) {
  // 後端會處理時區；前端只做「字串切分」，不做任何時區換算。
  if (!isoString) return { date: "-", time: "-", datetime: "-" };
  const s = String(isoString).replace('T', ' ').replace('Z', '').replace(/\.\d+/, '').trim();
  // 預期格式：YYYY-MM-DD HH:MM[:SS]
  const parts = s.split(' ');
  const date = parts[0] || "-";
  const time = (parts[1] || "-").slice(0, 5); // 只顯示到分鐘
  return {
    date,
    dateFull: date,
    time,
    datetime: `${date} ${time}`,
  };
}
// ====== 狀態 ======
let pageNow = 1;
let pageSize = 20;

// 目前頁面的事件快取（點一下就能開 modal，不用再打一次 API）
const eventCache = new Map(); // id -> event
let currentEditingEventId = null;
let currentObjects = [];

// ====== 權限檢查 & 啟動 ======
document.addEventListener("DOMContentLoaded", async () => {
  // 未登入就導回登入頁
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

  bindEvents();
  bindEventModal();
  await loadEvents();
});

// ====== 綁定事件 ======
function bindEvents() {

  // 查詢
  el("searchBtn")?.addEventListener("click", async () => {
    pageNow = 1;
    await loadEvents();
  });

  // 重設
  el("resetBtn")?.addEventListener("click", async () => {
    if (el("keywords")) el("keywords").value = "";
    if (el("start")) el("start").value = "";
    if (el("end")) el("end").value = "";
    if (el("sort")) el("sort").value = "+start_time";
    if (el("pageSize")) el("pageSize").value = "20";
    Array.from(document.querySelectorAll('input[name="sr"]')).forEach(cb => cb.checked = true);
    pageNow = 1;
    pageSize = 20;
    await loadEvents();
  });

  // 分頁
  el("prevBtn")?.addEventListener("click", async () => {
    if (pageNow > 1) {
      pageNow--;
      await loadEvents();
    }
  });
  el("nextBtn")?.addEventListener("click", async () => {
    pageNow++;
    await loadEvents();
  });

  // 頁數輸入框
  el("pageInput")?.addEventListener("change", async () => {
    const inputValue = parseInt(el("pageInput").value, 10);
    const maxPage = parseInt(el("pageInput")?.max || "1", 10);
    if (inputValue && inputValue >= 1 && inputValue <= maxPage) {
      pageNow = inputValue;
      await loadEvents();
    } else {
      // 如果輸入無效，恢復當前頁數
      el("pageInput").value = pageNow;
    }
  });

  el("pageInput")?.addEventListener("keypress", async (e) => {
    if (e.key === "Enter") {
      const inputValue = parseInt(el("pageInput").value, 10);
      const maxPage = parseInt(el("pageInput")?.max || "1", 10);
      if (inputValue && inputValue >= 1 && inputValue <= maxPage) {
        pageNow = inputValue;
        await loadEvents();
      } else {
        // 如果輸入無效，恢復當前頁數
        el("pageInput").value = pageNow;
      }
    }
  });

  // 每頁筆數
  el("pageSize")?.addEventListener("change", async () => {
    pageSize = parseInt(el("pageSize").value, 10) || 20;
    pageNow = 1;
    await loadEvents();
  });

  // 每頁筆數輸入框 enter 鍵觸發
  el("pageSize")?.addEventListener("keypress", async (e) => {
    if (e.key === "Enter") {
      pageSize = parseInt(el("pageSize").value, 10) || 20;
      pageNow = 1;
      await loadEvents();
    }
  });

}
// ====== 讀取 & 渲染 ======
async function loadEvents() {
  const keywords   = el("keywords")?.value.trim() || null;
  const start_time = el("start")?.value || null;
  const end_time   = el("end")?.value || null;
  // 本頁面沒有 sr 勾選（先保留向後相容：不傳就用後端預設）
  const sr = null;
  
  // ✅ 新增這一行
  const sort = `${sortOrder === "asc" ? "+" : "-"}${sortField}`;

  const q = { keywords, start_time, end_time, sr, sort, page: pageNow, size: pageSize };
  console.log("🔍 loadEvents query:", q);

  try {
    const resp = await ApiClient.listEvents(q);
    renderList(resp);
  } catch (err) {
    console.error(err);
    alert(err.message || "取得事件列表失敗");
  }
}

function renderList(resp) {
  const listBody = el("eventsList");
  listBody.innerHTML = "";

  // 檢查是否存在卡片列表容器，如果不存在則創建
  let cardListContainer = document.querySelector(".events-card-list");
  if (!cardListContainer) {
    cardListContainer = document.createElement("div");
    cardListContainer.className = "events-card-list";
    const eventsSection = document.querySelector(".events-section");
    if (eventsSection) {
      eventsSection.insertBefore(cardListContainer, listBody.parentElement);
    }
  }
  cardListContainer.innerHTML = "";

  const items = resp.items || [];
  eventCache.clear();
  items.forEach(it => { if (it?.id) eventCache.set(String(it.id), it); });

  const total = resp.item_total ?? items.length;
  const page = resp.page_now ?? pageNow;
  const size = resp.page_size ?? pageSize;
  const pageTotal = resp.page_total || (items.length < size ? page : page + 1);

  // 更新分頁資訊
  if (el("pageInput")) {
    el("pageInput").value = page;
    el("pageInput").max = pageTotal;
  }
  if (el("pageTotal")) {
    el("pageTotal").textContent = `/ ${pageTotal}`;
  }
  if (el("totalCount")) {
    el("totalCount").textContent = total;
  }

  // 更新每頁筆數輸入框的值
  if (el("pageSize")) {
    el("pageSize").value = size;
  }

  setDisabled(el("prevBtn"), page <= 1);
  setDisabled(el("nextBtn"), page >= pageTotal);

  // 沒資料時
  if (!items.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="5" style="text-align:center;color:#777;">沒有資料</td>`;
    listBody.appendChild(tr);
    
    // 手機版也顯示空狀態
    const emptyCard = document.createElement("div");
    emptyCard.className = "event-card";
    emptyCard.innerHTML = `<div style="text-align:center;color:#777;padding:var(--spacing-xl,32px);">沒有資料</div>`;
    cardListContainer.appendChild(emptyCard);
    return;
  }

  // ✅ 動態生成表格（桌面版）
  items.forEach((it) => {
    const { date, time } = formatEventTime(it.start_time);

    const tr = document.createElement("tr");
    tr.className = "events-clickable-row";
    tr.dataset.eventId = String(it.id);
    tr.innerHTML = `
      <td>${date}</td>
      <td>${time}</td>
      <td>${fmt(it.action)}</td>
      <td>${fmt(it.scene)}</td>
      <td>${fmt(it.summary)}</td>
    `;
    listBody.appendChild(tr);
  });

  // ✅ 動態生成卡片（手機版）
  items.forEach((it) => {
    const { datetime } = formatEventTime(it.start_time);

    const card = document.createElement("div");
    card.className = "event-card";
    card.dataset.eventId = String(it.id);
    card.innerHTML = `
      <div class="event-card-header">
        <div class="event-card-datetime">${datetime}</div>
      </div>
      <div class="event-card-body">
        <div class="event-card-field">
          <div class="event-card-label">進行行為</div>
          <div class="event-card-value">${fmt(it.action)}</div>
        </div>
        <div class="event-card-field">
          <div class="event-card-label">發生地點</div>
          <div class="event-card-value">${fmt(it.scene)}</div>
        </div>
        <div class="event-card-field event-card-summary">
          <div class="event-card-label">事件摘要</div>
          <div class="event-card-value">${fmt(it.summary)}</div>
        </div>
      </div>
    `;
    cardListContainer.appendChild(card);
  });

  // 點一下事件列/卡片就開啟 modal（不需要按鈕）
  listBody.onclick = (e) => {
    const tr = e.target.closest("tr[data-event-id]");
    if (!tr) return;
    const id = tr.dataset.eventId;
    openEventModalById(id);
  };
  cardListContainer.onclick = (e) => {
    const card = e.target.closest(".event-card[data-event-id]");
    if (!card) return;
    openEventModalById(card.dataset.eventId);
  };
}

// ====== Modal（直覺化：點一下事件就開啟，預設可編輯） ======
function bindEventModal() {
  const modal = el("eventDetailModal");
  const closeBtn = el("closeEventDetailModal");
  const cancelBtn = el("cancelEventDetail");
  const saveBtn = el("saveEventDetail");
  const deleteBtn = el("deleteEventBtn");
  const objectsInput = el("detailObjectsInput");

  if (closeBtn) closeBtn.addEventListener("click", closeEventModal);
  if (cancelBtn) cancelBtn.addEventListener("click", closeEventModal);
  if (modal) {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeEventModal();
    });
  }
  if (saveBtn) saveBtn.addEventListener("click", saveEventModal);
  if (deleteBtn) deleteBtn.addEventListener("click", deleteCurrentEvent);

  // 新增物件
  if (objectsInput) {
    objectsInput.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const v = objectsInput.value.trim();
      if (!v) return;
      if (!currentObjects.includes(v)) currentObjects.push(v);
      objectsInput.value = "";
      renderObjectTags();
    });
  }

  // 刪除物件 tag（事件委派）
  el("detailObjectsTags")?.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-index]");
    if (!btn) return;
    const idx = parseInt(btn.dataset.index, 10);
    if (Number.isFinite(idx)) {
      currentObjects.splice(idx, 1);
      renderObjectTags();
    }
  });
}

function renderObjectTags() {
  const wrap = el("detailObjectsTags");
  if (!wrap) return;
  wrap.innerHTML = (currentObjects || []).map((obj, idx) => `
    <span class="object-tag">
      ${obj}
      <button type="button" class="object-tag-remove" data-index="${idx}">×</button>
    </span>
  `).join("");
}

function closeEventModal() {
  const modal = el("eventDetailModal");
  modal?.classList.remove("show");
  currentEditingEventId = null;
  currentObjects = [];
  renderObjectTags();
  const msg = el("eventDetailMessage");
  if (msg) msg.textContent = "";
}

async function openEventModalById(id) {
  const item = eventCache.get(String(id));
  if (!item) return;
  currentEditingEventId = String(id);

  // 填入欄位
  if (el("detailEventId")) el("detailEventId").value = String(id);
  if (el("detailEventTime")) el("detailEventTime").value = formatEventTime(item.start_time).datetime;
  if (el("detailEventDuration")) el("detailEventDuration").value = item.duration != null ? String(Math.round(item.duration)) : "-";
  if (el("detailAction")) el("detailAction").value = item.action || "";
  if (el("detailScene")) el("detailScene").value = item.scene || "";
  if (el("detailSummary")) el("detailSummary").value = item.summary || "";

  currentObjects = Array.isArray(item.objects) ? [...item.objects] : [];
  renderObjectTags();

  // 影片預覽
  await loadRecordingPreview(item.recording_id);

  el("eventDetailModal")?.classList.add("show");
}

async function loadRecordingPreview(recordingId) {
  const section = el("recordingJumpSection");
  const container = el("recordingPreviewContainer");
  if (!container || !section) return;

  if (!recordingId) {
    section.style.display = "none";
    container.innerHTML = "";
    return;
  }
  section.style.display = "block";
  container.innerHTML = `<div style="color:#7a8aa6;">載入影片資訊中...</div>`;

  try {
    const resp = await ApiClient.recordings.list({ recording_id: recordingId, page: 1, size: 1 });
    const rec = resp?.items?.[0];
    if (!rec) {
      container.innerHTML = `<div style="color:#7a8aa6;">找不到對應影片</div>`;
      return;
    }

    let thumbUrl = "";
    if (rec.thumbnail_s3_key) {
      try {
        const u = await ApiClient.recordings.getUrl(recordingId, { ttl: 3600, disposition: "inline", asset_type: "thumbnail" });
        thumbUrl = u?.url || "";
      } catch {}
    }

    const title = String(rec.start_time || "").replace("T", " ").replace("Z", "").split(".")[0] || "影片";
    const dur = rec.duration != null ? `${Math.round(rec.duration)} 秒` : "未知";

    container.innerHTML = `
      <div class="recording-preview-card" id="recordingPreviewCard" role="button" tabindex="0">
        <div class="recording-preview-thumb">
          ${thumbUrl ? `<img src="${thumbUrl}" alt="影片縮圖">` : ``}
        </div>
        <div class="recording-preview-info">
          <div class="recording-preview-title">${title}</div>
          <div class="recording-preview-meta">長度：${dur}</div>
          <div class="recording-preview-meta">ID：${rec.id}</div>
        </div>
      </div>
    `;

    const card = el("recordingPreviewCard");
    if (card) {
      card.onclick = () => {
        window.location.href = `/recordings?recording_id=${encodeURIComponent(recordingId)}`;
      };
      card.onkeypress = (e) => {
        if (e.key === "Enter") window.location.href = `/recordings?recording_id=${encodeURIComponent(recordingId)}`;
      };
    }
  } catch (e) {
    container.innerHTML = `<div style="color:#7a8aa6;">載入影片資訊失敗：${fmt(e?.message)}</div>`;
  }
}

async function saveEventModal() {
  if (!currentEditingEventId) return;
  const id = currentEditingEventId;
  const action = el("detailAction")?.value.trim() || "";
  const scene = el("detailScene")?.value.trim() || "";
  const summary = el("detailSummary")?.value.trim() || "";
  const objects = currentObjects.length ? currentObjects : null;

  const msg = el("eventDetailMessage");
  if (msg) msg.textContent = "儲存中...";

  try {
    await ApiClient.updateEvent(id, {
      action: action || null,
      scene: scene || null,
      summary: summary || null,
      objects
    });
    if (msg) msg.textContent = "已儲存";
    // 重新載入列表（保持當前頁）
    await loadEvents();
    closeEventModal();
  } catch (e) {
    if (msg) msg.textContent = `儲存失敗：${fmt(e?.message)}`;
  }
}

async function deleteCurrentEvent() {
  if (!currentEditingEventId) return;
  const id = currentEditingEventId;
  if (!confirm("確定要刪除此事件嗎？此動作無法復原。")) return;

  const msg = el("eventDetailMessage");
  if (msg) msg.textContent = "刪除中...";
  try {
    await ApiClient.deleteEvent(id);
    // 若刪除後當頁可能變空，退一頁
    if (pageNow > 1) {
      const resp = await ApiClient.listEvents({
        keywords: el("keywords")?.value.trim() || null,
        start_time: el("start")?.value || null,
        end_time: el("end")?.value || null,
        sort: `${sortOrder === "asc" ? "+" : "-"}${sortField}`,
        page: pageNow,
        size: pageSize
      });
      if (!resp?.items?.length) pageNow -= 1;
    }
    await loadEvents();
    closeEventModal();
  } catch (e) {
    if (msg) msg.textContent = `刪除失敗：${fmt(e?.message)}`;
  }
}
// ====== 排序設定 ======
let sortField = "start_time";
let sortOrder = "desc"; // 預設由最近排到最遠

// ====== 綁定排序事件 ======
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("th[data-sort]").forEach((th) => {
    th.addEventListener("click", async () => {
      const field = th.dataset.sort;

      // 切換排序方向
      if (sortField === field) {
        sortOrder = sortOrder === "asc" ? "desc" : "asc";
      } else {
        sortField = field;
        sortOrder = "asc";
      }

      updateSortIcons();
      await loadEvents();
    });
  });
});

// ====== 排序圖示更新 ======
function updateSortIcons() {
  document.querySelectorAll("th[data-sort]").forEach((th) => {
    const field = th.dataset.sort;
    let icon = "";
    if (field === sortField) {
      icon = sortOrder === "asc" ? " ▲" : " ▼";
    }
    th.textContent = th.textContent.replace(/[▲▼]/g, "") + icon;
  });
}