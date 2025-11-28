SEARCH_EVENTS_BY_TIME_TOOL = {
    "name": "search_events_by_time",
    "description": "按時間範圍查詢生活事件。適用於「我今天做了什麼？」「我昨天幾點...」等問題。",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "date_from": {
                "type": "STRING",
                "description": "起始日期，ISO format (YYYY-MM-DD)"
            },
            "date_to": {
                "type": "STRING",
                "description": "結束日期，ISO format (YYYY-MM-DD)"
            },
            "limit": {
                "type": "INTEGER",
                "description": "最多返回幾筆結果"
            },
        },
        "required": ["date_from"]
    }
}

SEARCH_EVENTS_BY_LOCATION_TOOL = {
    "name": "search_events_by_location",
    "description": "按地點（場景）查詢事件。適用於「我在哪裡...」「我去過...」等問題。",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "location": {
                "type": "STRING",
                "description": "地點名稱（如：廚房、客廳、公園、餐廳）"
            },
            "date_from": {
                "type": "STRING",
                "description": "起始日期（可選），ISO format (YYYY-MM-DD)"
            },
            "date_to": {
                "type": "STRING",
                "description": "結束日期（可選），ISO format (YYYY-MM-DD)"
            },
            "limit": {
                "type": "INTEGER",
                "description": "最多返回幾筆結果"
            },
        },
        "required": ["location"]
    }
}

SEARCH_EVENTS_BY_ACTIVITY_TOOL = {
    "name": "search_events_by_activity",
    "description": "按活動類型查詢事件。適用於「我有沒有...」「我今天有運動嗎」等問題。",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "activity": {
                "type": "STRING",
                "description": "活動名稱（如：吃早餐、散步、看電視、運動）"
            },
            "date_from": {
                "type": "STRING",
                "description": "起始日期（可選），ISO format (YYYY-MM-DD)"
            },
            "date_to": {
                "type": "STRING",
                "description": "結束日期（可選），ISO format (YYYY-MM-DD)"
            },
            "limit": {
                "type": "INTEGER",
                "description": "最多返回幾筆結果"
            },
        },
        "required": ["activity"]
    }
}

GET_DAILY_SUMMARY_TOOL = {
    "name": "get_daily_summary",
    "description": "獲取某天的生活摘要（所有事件的時間軸）。適用於「我今天做了什麼？」「總結一下我的一天」等問題。",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "date": {
                "type": "STRING",
                "description": "日期，ISO format (YYYY-MM-DD)"
            },
        },
        "required": ["date"]
    }
}

SEARCH_RECORDINGS_BY_ACTIVITY_TOOL = {
    "name": "search_recordings_by_activity",
    "description": "【必須使用】按活動類型查詢影片。當用戶明確要求影片、視頻、錄影時，必須實際調用此工具函數！不能只回答「找到了影片」而不調用工具。這是強制性的，不能跳過。適用場景：1) 用戶說「請給我影片」「給我看視頻」「我要看錄影」；2) 查詢中包含「影片」「視頻」「錄影」等關鍵字；3) 用戶問「我有沒有...的影片？」；4) 用戶說「影片呢」表示之前沒有調用工具。範例：「請給我今天購物的影片」→ 必須調用此工具，參數：activity=\"購物\", date_from=\"今天\", date_to=\"今天\"。",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "activity": {
                "type": "STRING",
                "description": "活動名稱（如：購物、吃早餐、散步、看電視、運動）。直接使用用戶提到的活動名稱，不要改動。"
            },
            "date_from": {
                "type": "STRING",
                "description": "起始日期（可選），ISO format (YYYY-MM-DD)。必須將相對時間（今天、昨天、這週）轉換為具體日期。"
            },
            "date_to": {
                "type": "STRING",
                "description": "結束日期（可選），ISO format (YYYY-MM-DD)。必須將相對時間轉換為具體日期。"
            },
            "limit": {
                "type": "INTEGER",
                "description": "最多返回幾筆結果（預設 10）"
            },
        },
        "required": ["activity"]
    }
}

GET_DIARY_TOOL = {
    "name": "get_diary",
    "description": "查詢日記。適用於「我要看日記」「查詢日記」「今天的日記」等問題。預設查詢今天的日記，可以指定日期或相對時間（如「三天前」「上週一」）。",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "date": {
                "type": "STRING",
                "description": "日期（可選），ISO format (YYYY-MM-DD) 或相對時間（如「三天前」「昨天」）。如果不提供，預設為今天。"
            },
        },
        "required": []
    }
}

REFRESH_DIARY_TOOL = {
    "name": "refresh_diary",
    "description": "刷新日記。適用於「刷新日記」「重新生成日記」「更新日記」等問題。預設刷新今天的日記，可以指定日期或相對時間。",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "date": {
                "type": "STRING",
                "description": "日期（可選），ISO format (YYYY-MM-DD) 或相對時間（如「三天前」「昨天」）。如果不提供，預設為今天。"
            },
        },
        "required": []
    }
}

SEARCH_VLOGS_BY_DATE_TOOL = {
    "name": "search_vlogs_by_date",
    "description": "查詢 Vlog。適用於「我要看 Vlog」「查詢 Vlog」「今天的 Vlog」等問題。預設查詢今天的 Vlog，可以指定日期或相對時間（如「三天前」「上週一」）。也可以查詢日期範圍內的 Vlog。",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "date": {
                "type": "STRING",
                "description": "日期（可選），ISO format (YYYY-MM-DD) 或相對時間（如「三天前」「昨天」）。如果不提供，預設為今天。"
            },
            "date_from": {
                "type": "STRING",
                "description": "起始日期（可選），ISO format (YYYY-MM-DD) 或相對時間。用於查詢日期範圍。"
            },
            "date_to": {
                "type": "STRING",
                "description": "結束日期（可選），ISO format (YYYY-MM-DD) 或相對時間。用於查詢日期範圍。"
            },
            "limit": {
                "type": "INTEGER",
                "description": "最多返回幾筆結果（預設 10）"
            },
        },
        "required": []
    }
}