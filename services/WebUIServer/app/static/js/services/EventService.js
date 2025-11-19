export const EventService = {
  list: async (q) => {
    try { return await window.ApiClient.listEvents(q); }
    catch (e) { throw new Error(e.message || '取得事件列表失敗'); }
  },
  read: async (eventId) => {
    try { return await window.ApiClient.getEvent(eventId); }
    catch (e) { throw new Error(e.message || '取得事件詳情失敗'); }
  },
  update: async (eventId, patch) => {
    try { return await window.ApiClient.updateEvent(eventId, patch); }
    catch (e) { throw new Error(e.message || '更新事件失敗'); }
  },
  delete: async (eventId) => {
    try { return await window.ApiClient.deleteEvent(eventId); }
    catch (e) { throw new Error(e.message || '刪除事件失敗'); }
  }
};
window.EventService = EventService;