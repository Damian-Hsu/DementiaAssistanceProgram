from flask import Flask, jsonify, render_template, send_from_directory, request,Response,abort
from flask_cors import CORS
import os,requests
import uuid
import time
from datetime import datetime, timedelta
import hashlib

# 創建Flask應用實例
app = Flask(__name__, 
           static_folder='static', 
           template_folder='template',
           instance_relative_config=True)

# CORS設置 - 允許跨域請求
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://127.0.0.1:30202", "http://192.168.191.20:30202","http://192.168.191.254:30202"],
        "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Accept"],
        "supports_credentials": True
    }
})

# 開發模式配置
app.config['DEBUG'] = True
app.config['JSON_AS_ASCII'] = False  # 支援中文JSON

# 主頁路由 - 提供登入頁面
@app.route('/')
def index():
    return render_template('auth.html')

@app.route("/auth")
def auth():
    return render_template("auth.html")

@app.route("/home")
def home():
    return render_template(
        'home.html',
        title_zh='主頁',
        active_page='home'
    )
@app.route('/settings')
def settings():
    return render_template(
        'user_profile.html',
        title_zh='設定',
        desc_zh='',
        active_page='settings'
    )

@app.route('/events')
def events():
    return render_template(
        'events.html',
        title_zh='事件檢視',
        desc_zh='',
        active_page='events'
    )

@app.route('/camera')
def camera():
    return render_template(
        'camera.html',
        title_zh='鏡頭串流',
        desc_zh='',
        active_page='camera'
    )

@app.route('/recordings')
def recordings():
    return render_template(
        'recordings.html',
        title_zh='影片管理',
        desc_zh='',
        active_page='recordings'
    )

@app.route('/chat')
def chat():
    return render_template(
        'chat.html',
        title_zh='AI助手',
        desc_zh='',
        active_page='chat'
    )


@app.route('/admin/home')
@app.route('/admin')
def admin_home():
    return render_template(
        'admin_home.html',
        title_zh='管理員首頁',
        desc_zh='',
        active_page='admin_home'
    )

@app.route('/admin/dashboard')
def admin_dashboard():
    return render_template(
        'admin_dashboard.html',
        title_zh='管理儀表板',
        desc_zh='',
        active_page='admin_dashboard'
    )

@app.route('/admin/settings')
def admin_settings():
    return render_template(
        'admin_settings.html',
        title_zh='管理員設定',
        desc_zh='',
        active_page='admin_settings'
    )


# 靜態文件路由 - 確保JS文件能正確載入
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory(app.static_folder, filename)

HOP_BY_HOP_REQ_HEADERS = {
    # 這些**請求**端的標頭不要轉發，交給 requests 自己處理
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "accept-encoding",   # 避免雙重壓縮/長度不一致（可選，建議也移除）
}

HOP_BY_HOP_RESP_HEADERS = {
    # 這些**回應**端的標頭不要原樣轉回（讓 Flask 計算）
    "content-encoding",
    "content-length",
    "transfer-encoding",
    "connection",
}

@app.route("/bff/v1/<path:path>", methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"])
def proxy_to_backend(path):
    # 在 Docker 環境中使用服務名稱，本地開發時使用環境變數或預設值
    api_host = os.getenv("API_HOST", "api")  # Docker 服務名稱或 IP
    api_port = os.getenv("API_PORT", "30000")
    backend_url = f"http://{api_host}:{api_port}/api/v1/{path}"

    # 過濾 hop-by-hop；保留 Authorization
    fwd_headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in {"host","content-length","transfer-encoding","connection","accept-encoding"}}

    is_json = request.headers.get("Content-Type", "").startswith("application/json")
    # AI 推薦需要載入模型，可能需要較長時間，設定為 150 秒
    timeout_seconds = 150 if path == "vlogs/ai-select" else 30
    kwargs = dict(
        method=request.method, url=backend_url, params=request.args,
        headers=fwd_headers, cookies=request.cookies, allow_redirects=False, timeout=timeout_seconds,
    )
    if is_json:
        kwargs["json"] = request.get_json(silent=True)
    else:
        kwargs["data"] = request.get_data()

    # 🔎 這裡新增兩個偵錯點（只印存在與否）
    has_auth_in  = "Authorization" in request.headers
    has_auth_out = "Authorization" in fwd_headers
    try:
        print("→", request.method, backend_url)
        print("  auth in?", has_auth_in, "| auth out?", has_auth_out)  # ✅ 不印 token 值
        print("  qs =", dict(request.args))
        print("  is_json =", is_json)
        if "json" in kwargs:
            print("  json =", kwargs["json"])
        elif "data" in kwargs:
            print("  data(bytes) =", len(kwargs["data"]))
    except Exception as e:
        print("  [debug print error]", e)

    resp = requests.request(**kwargs)

    try:
        preview = resp.text[:500].replace("\n", "\\n")
        print("←", resp.status_code, request.method, backend_url)
        print("  resp preview:", preview)
    except Exception as e:
        print("  [debug print resp error]", e)

    out_headers = [(k, v) for k, v in resp.headers.items()
                   if k.lower() not in {"content-encoding","content-length","transfer-encoding","connection"}]
    return Response(resp.content, resp.status_code, out_headers)
    
# --- Shim: allow extension-style URLs like /auth.html, /camera.html, etc. ---
@app.route('/<page>.html')
def serve_html_pages(page):
    allowed = {'auth', 'home','camera', 'recordings', 'user_profile', 'settings',"events","chat","diary","vlog"}
    if page in allowed:
        return render_template(f'{page}.html')
    return jsonify({'error': 'Page not found'}), 404

if __name__ == "__main__":
    # 開發模式運行設置  
    app.run(
        host='0.0.0.0',  # 允許外部訪問
        port=30202,       # 設置端口
        debug=True,      # 開啟調試模式
        threaded=True    # 支援多線程
    )
    