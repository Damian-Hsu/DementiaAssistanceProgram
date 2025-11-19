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