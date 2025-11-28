// Home 頁面邏輯（合併後的頁面）

// ====== 工具函數 ======
function el(id) { return document.getElementById(id); }

// ====== 日期選擇器邏輯 ======
document.addEventListener("DOMContentLoaded", () => {
  const dateInput = el("diaryDate");
  const dateDisplay = el("dateDisplay");
  
  if (!dateInput || !dateDisplay) return;

  // 當日期顯示文字被點擊時，激活日期選擇器
  dateDisplay.addEventListener("click", () => {
    dateInput.classList.add("active");
    dateInput.style.pointerEvents = "auto";
    // 觸發焦點以顯示日曆選擇器
    setTimeout(() => {
      dateInput.focus();
      dateInput.showPicker?.() || dateInput.click();
    }, 10);
  });

  // 當日期選擇器獲得焦點時，確保處於激活狀態
  dateInput.addEventListener("focus", () => {
    dateInput.classList.add("active");
    dateDisplay.style.display = "none";
  });

  // 當日期選擇器失去焦點時，恢復文字顯示
  dateInput.addEventListener("blur", () => {
    setTimeout(() => {
      dateInput.classList.remove("active");
      dateInput.style.pointerEvents = "none";
      dateDisplay.style.display = "inline-block";
      if (dateInput.value) {
        dateDisplay.textContent = formatDateForDisplay(dateInput.value);
      }
    }, 200); // 延遲一點，讓日曆選擇完成
  });

  // 日期變更時更新顯示
  dateInput.addEventListener("change", () => {
    if (dateInput.value) {
      dateDisplay.textContent = formatDateForDisplay(dateInput.value);
    }
  });
});

// 格式化日期顯示
function formatDateForDisplay(dateString) {
  if (!dateString) return "";
  const date = new Date(dateString + "T00:00:00");
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

