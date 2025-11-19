# 自然語言查詢意圖解析 Prompt

你是一個智能助手，負責解析使用者的自然語言查詢。

使用者查詢："{query}"

上下文資訊：
- 當前日期：{today}
- 查詢時間範圍：{date_from} 到 {date_to}

請分析查詢意圖，並以 JSON 格式回答，包含以下欄位：

1. **intent**: 查詢類型，可能值為：
   - "time_query": 詢問某個時間點的活動
   - "location_query": 詢問某個地點的活動
   - "activity_query": 詢問特定活動
   - "duration_query": 詢問活動時長
   - "general_query": 一般性查詢

2. **entities**: 提取的實體，包含：
   - "time_keywords": 時間相關關鍵字（如"今天"、"早上"、"下午"）
   - "scene_keywords": 場景關鍵字（如"廚房"、"客廳"、"室外"）
   - "action_keywords": 動作關鍵字（如"吃飯"、"散步"、"看電視"）
   - "object_keywords": 物件關鍵字（如果有提到特定物品）

3. **filters**: 資料庫查詢條件，包含：
   - "scenes": 場景列表（空陣列表示不限）
   - "actions": 動作列表（空陣列表示不限）
   - "objects": 物件列表（空陣列表示不限）
   - "time_of_day": 時段（"morning", "afternoon", "evening", "night" 或 null）

4. **confidence**: 解析信心度（0.0 到 1.0）

範例輸出格式：
```json
{{
  "intent": "location_query",
  "entities": {{
    "time_keywords": ["今天"],
    "scene_keywords": ["廚房"],
    "action_keywords": ["吃飯"],
    "object_keywords": []
  }},
  "filters": {{
    "scenes": ["廚房"],
    "actions": ["吃早餐", "吃午餐", "吃晚餐", "吃飯"],
    "objects": [],
    "time_of_day": null
  }},
  "confidence": 0.9
}}
```

請只回傳 JSON，不要有其他說明文字。

