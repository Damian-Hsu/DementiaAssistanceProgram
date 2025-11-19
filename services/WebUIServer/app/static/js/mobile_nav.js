// 手機模式導覽列互動功能

document.addEventListener('DOMContentLoaded', () => {
  const videoBtn = document.getElementById('mobileNavVideoBtn');
  const videoSubmenu = document.getElementById('mobileNavVideoSubmenu');
  const videoNavItem = videoBtn?.closest('.mobile-nav-expandable');
  
  if (!videoBtn || !videoSubmenu || !videoNavItem) return;

  // 切換展開/收起
  videoBtn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    
    const isExpanded = videoNavItem.classList.contains('expanded');
    
    // 關閉其他展開的選單
    document.querySelectorAll('.mobile-nav-expandable.expanded').forEach(item => {
      if (item !== videoNavItem) {
        item.classList.remove('expanded');
      }
    });
    
    // 切換當前選單
    if (isExpanded) {
      videoNavItem.classList.remove('expanded');
    } else {
      videoNavItem.classList.add('expanded');
    }
  });

  // 點擊外部關閉展開選單
  document.addEventListener('click', (e) => {
    if (!videoNavItem.contains(e.target)) {
      videoNavItem.classList.remove('expanded');
    }
  });

  // 點擊子選單項目後關閉展開選單
  const submenuItems = videoSubmenu.querySelectorAll('.mobile-nav-submenu-item');
  submenuItems.forEach(item => {
    item.addEventListener('click', () => {
      // 延遲關閉，讓頁面跳轉先執行
      setTimeout(() => {
        videoNavItem.classList.remove('expanded');
      }, 100);
    });
  });

  // 防止子選單點擊事件冒泡
  videoSubmenu.addEventListener('click', (e) => {
    e.stopPropagation();
  });

  // 如果當前頁面是影片相關頁面，自動展開
  if (videoNavItem.classList.contains('expanded')) {
    // 頁面載入時如果是影片相關頁面，保持展開狀態
    // 這個邏輯已經在 HTML 模板中通過 active_page 判斷處理
  }
});

