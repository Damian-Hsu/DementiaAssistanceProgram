
## 安裝與運行

### 1. 安裝Python依賴


### 2. 啟動Flask服務器

```bash
python app.py
```

服務器將在 `http:192.168.191.254:api/v1` 運行

### 3. 訪問系統

打開瀏覽器訪問 `http://localhost:8001`


### 目錄結構
```
frontend/
├── app.py                      # Flask主應用+控制傳入頁面標題/頁面說明
├── requirements.lock.txt       # Python依賴
├── static/
│   ├── css/
│   │   ├── base.css            #底層樣式
│   │   ├── componet.css        #元件樣式
│   │   ├── layout.css          #排版樣式
│   │   ├── auth.css            #auth.html樣式(未使用公版樣式)
│   │   ├── user_profilecss     #user_profile.html樣式
│   │   └── events.css          #events.html樣式
│   │
│   ├── js/
│   │   ├── settings.js         # 伺服器(BFF_ROOT位址)
│   │   ├── sign_login.js       # 登入、註冊邏輯
│   │   ├── logout.js           # 手動登出(ok)、自動登出(不完善)
│   │   ├── AuthService.js      # 認證服務
│   │   ├── APIClient.js        # API客戶端
│   │   ├── camera.js           # 攝影機管理(需抽出部分程式碼到user_profile.js)
│   │   ├── recordings.js       # 影片管理
│   │   ├── events.js           # 事件管理
│   │   └── user_profile.js     # user_profile.html元件互動、
│   └──icons/                   #側邊欄圖示(Remix icon)
│
├── template/
     ├── particals
     ├──    ├── header.html     #右上角顯示頁面標題及簡易說明區排版
     ├──    └── sidebar.html    #左側導覽列排版 
     ├── base.html              # 基礎排版       
     ├── auth.html              # 登入/註冊頁面
     ├── home.html              # 首頁
     ├── camera.html            # 攝影機頁面(應為stream,僅保留串流相關功能之介面)
     ├── recordings.html        # 影片介面
     └── user_profile.html      # 使用者資訊介面(應為設定介面)
         ├── events.html        # 事件介面 
         └── chat.html          # 聊天介面

### camera.js有很大的問題，動到甚麼導致他有問題了

## 已知問題(通用問題)
1.見Notion提及事項
2.自動登出邏輯有問題
3.提示訊息方式(操作結果)不統一(dialog/alert混用)；應該可以從user_profile.js中抽出
4.FASTAPI未更新，有可能APIClient.js是舊的或缺少(EX：LLM)
5.沒有RWD

### html、css問題
1.camera.html、recordings.html仍使用card排版、未調整成新的
2.home.html、chat.html未建立html元件

### 各頁問題
0.sidebar.html之導覽列沒有浮出
1.base.html：
　　　自動登出的邏輯應該要用這邊控制，但沒有
2.auth.html：
　　　1.採用之CSS非公版(base/componments)
　　　2.註冊內容驗證格式
3.home.html：
　　　html、css、js(除了每日小結沒有API未實作外；串流畫面可以在camera.js中找到；事件列表可以在event.js找
                   到，但跨檔案引用的方法沒寫)
4.camera.html：
　　　1.沒有實際的html、css(但有js)
　　　2.部分功能應移出至user_profile.html/user_profile.js
　　　3.建立串流區塊邏輯怪異
　　　4.提示訊息/編輯 仍使用alert而不是dialog
　　　5.複製到剪貼簿的功能未實作(RTSP位址)>目前的寫法需要HTTPS，HTTP的沒找到一個好方法
　　　6.hls/webrtc沒有自動續時效
　　　7.Refresh/token/{audience}未實作
5.events.html：
　　　1.CSS排版
　　　2.訊息顯示方式
　　　3.事件摘要的限制
　　　4.允許用戶編輯的範圍?目前只有允許編輯事件摘要
6.recordings.html：
　　　1.CSS排版、html元件
　　　2.當初製作時影片部分API不完善，導致無法測試功能是否正確
7.chat.html：
　　　html、css、js未建立(不確定長相/api未公布)
8.user_profile.html：
     1.css排版
     2.編輯個人資料的方式
     3.html(新增的區塊們)未實作(無API)
