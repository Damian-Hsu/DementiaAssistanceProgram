# -*- coding: utf-8 -*-
"""
公開網域配置工具
用於生成外部訪問的 URL，支援從環境變數或 Request Host header 自動偵測
"""
from __future__ import annotations
import os
from typing import Optional
from fastapi import Request


def get_public_domain(
    service: str,
    request: Optional[Request] = None,
    *,
    default_scheme: str = "http",
    default_port: Optional[int] = None,
) -> str:
    """
    獲取服務的公開網域（包含 scheme 和可選的 port）
    
    Args:
        service: 服務名稱（'api', 'webui', 'rtsp', 'hls', 'webrtc', 'minio'）
        request: FastAPI Request 對象，用於自動偵測 Host header
        default_scheme: 預設的 scheme（http/https）
        default_port: 預設的端口（如果為 None，則根據 scheme 自動判斷）
    
    Returns:
        完整的 URL（例如：http://192.168.191.20 或 https://app.lifelog.ai）
    
    優先順序：
    1. 環境變數 {SERVICE}_PUBLIC_DOMAIN（如果包含 scheme，直接返回）
    2. 環境變數 {SERVICE}_PUBLIC_DOMAIN + {SERVICE}_PUBLIC_SCHEME + {SERVICE}_PUBLIC_PORT
    3. Request Host header（如果提供）
    4. 預設值（localhost）
    """
    # 環境變數名稱
    domain_var = f"{service.upper()}_PUBLIC_DOMAIN"
    scheme_var = f"{service.upper()}_PUBLIC_SCHEME"
    port_var = f"{service.upper()}_PUBLIC_PORT"
    
    # 嘗試從環境變數獲取完整域名（可能包含 scheme）
    public_domain = os.getenv(domain_var, "").strip()
    
    if public_domain:
        # 如果已經包含 scheme，直接返回
        if public_domain.startswith(("http://", "https://", "rtsp://")):
            return public_domain.rstrip("/")
        
        # 獲取 scheme 和 port
        scheme = os.getenv(scheme_var, default_scheme).strip()
        port_str = os.getenv(port_var, "").strip()
        
        # 判斷是否需要添加端口
        if port_str:
            try:
                port = int(port_str)
                # 標準端口不需要顯示
                if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
                    return f"{scheme}://{public_domain}"
                return f"{scheme}://{public_domain}:{port}"
            except ValueError:
                pass
        
        # 如果沒有指定端口，使用預設端口邏輯
        if default_port:
            if (scheme == "http" and default_port == 80) or (scheme == "https" and default_port == 443):
                return f"{scheme}://{public_domain}"
            return f"{scheme}://{public_domain}:{default_port}"
        
        return f"{scheme}://{public_domain}"
    
    # 如果沒有環境變數，嘗試從 Request Host header 獲取
    if request:
        host = request.headers.get("host", "").strip()
        if host:
            # 從 Host header 構建 URL
            # 注意：Host header 不包含 scheme，需要判斷
            scheme = "https" if request.url.scheme == "https" else default_scheme
            
            # 檢查 Host 是否包含端口
            if ":" in host:
                # Host 已經包含端口
                return f"{scheme}://{host}"
            else:
                # 需要添加端口（如果不是標準端口）
                if default_port and not ((scheme == "http" and default_port == 80) or (scheme == "https" and default_port == 443)):
                    return f"{scheme}://{host}:{default_port}"
                return f"{scheme}://{host}"
    
    # 預設值（如果環境變數和 Request 都沒有，使用預設值）
    # 注意：這應該只在開發環境發生，生產環境應該設定環境變數
    if default_port and default_port not in (80, 443):
        return f"{default_scheme}://localhost:{default_port}"
    return f"{default_scheme}://localhost"


def get_rtsp_url(domain: str, path: str, token: str) -> str:
    """構建 RTSP URL。
    
    Args:
        domain: 網域
        path: 路徑
        token: 認證 token
        
    Returns:
        str: 完整的 RTSP URL
    """
    domain = domain.rstrip("/")
    path = path.lstrip("/")
    return f"{domain}/{path}?token={token}"


def get_hls_url(domain: str, path: str, token: str) -> str:
    """構建 HLS URL（通過 /hls/ 路徑）。
    
    Args:
        domain: 網域
        path: 路徑
        token: 認證 token
        
    Returns:
        str: 完整的 HLS URL
    """
    domain = domain.rstrip("/")
    path = path.lstrip("/")
    return f"{domain}/hls/{path}/index.m3u8?token={token}"


def get_webrtc_url(domain: str, path: str, token: str) -> str:
    """構建 WebRTC URL。
    
    Args:
        domain: 網域
        path: 路徑
        token: 認證 token
        
    Returns:
        str: 完整的 WebRTC URL
    """
    domain = domain.rstrip("/")
    path = path.lstrip("/")
    return f"{domain}/webrtc/{path}/whep?token={token}"


def get_api_url(domain: str, path: str = "") -> str:
    """構建 API URL。
    
    Args:
        domain: 網域
        path: 可選的 API 路徑
        
    Returns:
        str: 完整的 API URL
    """
    domain = domain.rstrip("/")
    path = path.lstrip("/")
    if path:
        return f"{domain}/api/v1/{path}"
    return f"{domain}/api/v1"

