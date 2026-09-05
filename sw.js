// JellyStock Service Worker
// 目的：讓網站可被「加到主畫面」／包成 App 殼時符合安裝條件，
// 並在離線時顯示友善提示頁。
// 刻意不快取任何法人買賣超、股價等資料頁面或 API 回應——
// 這些資料一律以 Firebase 即時同步為準，快取舊資料會誤導使用者。

const OFFLINE_URL = '/offline.html';
const CACHE_NAME = 'jellystock-shell-v1';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.add(OFFLINE_URL))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  // 只處理「整頁導覽」請求（例如直接開網址、App 啟動），不攔截 API/資料 fetch
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(OFFLINE_URL))
    );
  }
});
