// Home 頁面切換邏輯

// ====== 工具函數 ======
function el(id) { return document.getElementById(id); }

// ====== 標籤切換 ======
document.addEventListener("DOMContentLoaded", () => {
  const diaryTab = el("diaryTab");
  const vlogTab = el("vlogTab");
  const diarySection = el("diarySection");
  const vlogSection = el("vlogSection");

  if (!diaryTab || !vlogTab || !diarySection || !vlogSection) return;

  // 日記標籤點擊
  diaryTab.addEventListener("click", () => {
    switchTab("diary");
  });

  // Vlog 標籤點擊
  vlogTab.addEventListener("click", () => {
    switchTab("vlog");
  });
});

// ====== 切換標籤 ======
function switchTab(tabName) {
  const diaryTab = el("diaryTab");
  const vlogTab = el("vlogTab");
  const diarySection = el("diarySection");
  const vlogSection = el("vlogSection");

  if (tabName === "diary") {
    diaryTab?.classList.add("active");
    vlogTab?.classList.remove("active");
    diarySection?.classList.add("active");
    vlogSection?.classList.remove("active");
  } else if (tabName === "vlog") {
    diaryTab?.classList.remove("active");
    vlogTab?.classList.add("active");
    diarySection?.classList.remove("active");
    vlogSection?.classList.add("active");
  }
}

