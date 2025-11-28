# Chat Prompts 目錄

此目錄包含所有用於 AI 聊天助手的 prompt 模板文件。

## 文件說明

### 1. `system_instruction.md`
- **用途**: 系統指令，定義 AI 助手的基本行為和可用工具
- **使用位置**: `llm_tools.py` - 在創建 LLM 模型時載入
- **內容**: 
  - AI 助手的角色定義
  - 可用工具列表（事件查詢、影片查詢等）
  - 回覆風格指南
  - 時間理解規則
  - 範例對話

### 2. `diary_summary.md`
- **用途**: 日記摘要生成的 prompt 模板
- **使用位置**: `service.py` - `_generate_diary_summary` 函數
- **模板變數**: 
  - `{events_text}`: 事件列表文本（自動替換）
- **內容**:
  - 日記生成任務說明
  - 格式要求
  - 範例格式
  - 注意事項

### 3. `answer_generation.md` (未使用)
- **用途**: 自然語言回答生成 prompt（目前未在代碼中使用）
- **模板變數**:
  - `{query}`: 使用者查詢
  - `{total_events}`: 事件總數
  - `{events_summary}`: 事件摘要

### 4. `video_query_guidance.md`
- **用途**: 影片查詢工具使用指南和範例
- **使用位置**: 作為開發參考文檔，內容已整合到 `system_instruction.md`
- **內容**:
  - 何時使用影片查詢工具
  - 使用格式和範例
  - 活動名稱提取指南
  - 範例對話

### 5. `query_intent_parsing.md` (未使用)
- **用途**: 查詢意圖解析 prompt（目前未在代碼中使用）
- **模板變數**:
  - `{query}`: 使用者查詢
  - `{today}`: 當前日期
  - `{date_from}`: 查詢起始日期
  - `{date_to}`: 查詢結束日期

## 使用方式

### 載入 Prompt

```python
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROMPTS_DIR = HERE / "prompts"
PROMPT_PATH = PROMPTS_DIR / "diary_summary.md"

with open(PROMPT_PATH, "r", encoding="utf-8") as f:
    prompt = f.read()
```

### 使用模板變數

```python
# 替換模板變數
user_message = prompt.replace("{events_text}", events_text)
```

## 添加新的 Prompt

1. 在 `prompts` 目錄中創建新的 `.md` 文件
2. 使用 `{variable_name}` 格式定義模板變數
3. 在代碼中載入並使用該 prompt
4. 更新此 README 文件

## 注意事項

- 所有 prompt 文件使用 UTF-8 編碼
- 模板變數使用 `{variable_name}` 格式
- 保持 prompt 內容清晰、結構化
- 定期檢查未使用的 prompt 文件，考慮移除或實作

