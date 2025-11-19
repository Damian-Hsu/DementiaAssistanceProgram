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
  if (!isoString) return { date: "-", time: "-", datetime: "-" };
  const d = new Date(isoString);
  const t = new Date(d.getTime() + 8 * 60 * 60 * 1000); // +8小時
  const yyyy = String(t.getFullYear());
  const mm = String(t.getMonth() + 1).padStart(2, "0");
  const dd = String(t.getDate()).padStart(2, "0");
  const HH = String(t.getHours()).padStart(2, "0");
  const MM = String(t.getMinutes()).padStart(2, "0");
  return { 
    date: `${mm}-${dd}`, 
    dateFull: `${yyyy}-${mm}-${dd}`, 
    time: `${HH}:${MM}`,
    datetime: `${yyyy}-${mm}-${dd} ${HH}:${MM}`
  };
}
// ====== 狀態 ======
let pageNow = 1;
let pageSize = 20;

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
  setupEventDelegation();
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
  const sr         = Array.from(document.querySelectorAll('input[name="sr"]:checked')).map(cb => cb.value);
  
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

  const total = resp.item_total ?? items.length;
  const page = resp.page_now ?? pageNow;
  const size = resp.page_size ?? pageSize;
  const pageTotal = resp.page_total || (items.length < size ? page : page + 1);

  // 更新分頁資訊
  el("resultSummary").textContent = `共 ${total} 筆 / 第 ${page} 頁（每頁 ${size} 筆）`;
  el("pageInfo").textContent = `第 ${page} / ${pageTotal} 頁`;

  // 更新每頁筆數輸入框的值
  if (el("pageSize")) {
    el("pageSize").value = size;
  }

  setDisabled(el("prevBtn"), page <= 1);
  setDisabled(el("nextBtn"), page >= pageTotal);

  // 沒資料時
  if (!items.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="6" style="text-align:center;color:#777;">沒有資料</td>`;
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
    tr.innerHTML = `
      <td>${date}</td>
      <td>${time}</td>
      <td>${fmt(it.action)}</td>
      <td>${fmt(it.scene)}</td>
      <td>${fmt(it.summary)}</td>
      <td>
        <button class="btn-detail" data-action="detail" data-id="${it.id}">詳情</button>
        <button class="btn-edit" data-action="edit" data-id="${it.id}">編輯</button>
        <button class="btn-delete" data-action="delete" data-id="${it.id}">刪除</button>
      </td>
    `;
    listBody.appendChild(tr);
  });

  // ✅ 動態生成卡片（手機版）
  items.forEach((it) => {
    const { datetime } = formatEventTime(it.start_time);

    const card = document.createElement("div");
    card.className = "event-card";
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
      <div class="event-card-actions">
        <button class="btn-detail" data-action="detail" data-id="${it.id}">詳情</button>
        <button class="btn-edit" data-action="edit" data-id="${it.id}">編輯</button>
        <button class="btn-delete" data-action="delete" data-id="${it.id}">刪除</button>
      </div>
    `;
    cardListContainer.appendChild(card);
  });
}

const dialog = el("eventDialog");
const dialogTitle = el("dialogTitle");
const dialogContent = el("dialogContent");
const closeDialogBtn = el("closeDialogBtn");

// 事件代理 - 同時處理表格和卡片列表的點擊事件
function setupEventDelegation() {
  // 表格列表事件代理
  el("eventsList")?.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    await handleEventAction(btn);
  });

  // 卡片列表事件代理
  document.addEventListener("click", async (e) => {
    const cardList = document.querySelector(".events-card-list");
    if (cardList && cardList.contains(e.target)) {
      const btn = e.target.closest("button[data-action]");
      if (btn) {
        await handleEventAction(btn);
      }
    }
  });

  // 關閉對話框
  closeDialogBtn.addEventListener("click", () => dialog.close());
}

async function handleEventAction(btn) {
  const id = btn.getAttribute("data-id");
  const action = btn.getAttribute("data-action");

  if (action === "detail") {
    const item = await ApiClient.getEvent(id);
    const { date, time } = formatEventTime(item.start_time);

    dialogTitle.textContent = "事件詳情";
    dialogContent.innerHTML = `
      <p><strong>日期：</strong>${date}</p>
      <p><strong>時間：</strong>${time}</p>
      <p><strong>行為：</strong>${item.action}</p>
      <p><strong>地點：</strong>${item.scene}</p>
      <p><strong>摘要：</strong>${item.summary}</p>
    `;
    dialog.showModal();
  }

  if (action === "edit") {
    const item = await ApiClient.getEvent(id);
    dialogTitle.textContent = "編輯事件";
    dialogContent.innerHTML = `
      <div class="dlg__field">
        <label>摘要：</label>
        <input id="editSummary" type="text" value="${item.summary || ""}">
      </div>
      <button id="saveEditBtn" class="btn-primary">儲存</button>
    `;
    dialog.showModal();

    el("saveEditBtn").addEventListener("click", async () => {
      const newSummary = el("editSummary").value;
      await ApiClient.updateEvent(id, { summary: newSummary });
      dialog.close();
      await loadEvents();
    });
  }
  
  if (action === "delete") {
    if (confirm("確定要刪除此事件嗎？")) {
      try {
        await ApiClient.deleteEvent(id);
        const listBody = el("eventsList");
        const cardList = document.querySelector(".events-card-list");
        if ((listBody?.rows?.length === 1 || (cardList && cardList.children.length === 1)) && pageNow > 1) {
          pageNow -= 1;
        }
        await loadEvents();
        alert("事件已刪除");
      } catch (err) {
        console.error(err);
        alert("刪除失敗：" + (err.message || ""));
      }
    }
  }
}

// closeDialogBtn 事件綁定在 setupEventDelegation 中
// ====== 詳情 Dialog ======
function showEventDetail(data) {
  const dlg = document.getElementById("eventModal");
  const pre = document.getElementById("eventDetail");
  if (!dlg || !pre) {
    alert(JSON.stringify(data, null, 2));
    return;
  }
  pre.textContent = JSON.stringify(data, null, 2);
  try { dlg.showModal(); } catch { dlg.show(); }
}
// ====== 排序設定 ======
let sortField = "start_time";
let sortOrder = "asc";

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