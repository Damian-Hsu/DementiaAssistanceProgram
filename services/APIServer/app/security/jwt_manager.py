import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError
from passlib.context import CryptContext
from fastapi import HTTPException, status
import time


class JWTManager:
    def __init__(
        self,
        secret_key: Optional[str] = None,
        algorithm: Optional[str] = None,
        expire_minutes: Optional[int] = None,
        issuer: Optional[str] = None,
        audience: Optional[str] = None,
        leeway_seconds: int = 60,  # 容忍時鐘誤差
    ):
        self.secret_key = secret_key or os.getenv("JWT_SECRET_KEY")
        if not self.secret_key:
            raise RuntimeError("JWT_SECRET_KEY not set")

        self.algorithm = (algorithm or os.getenv("JWT_ALG") or "HS256").upper()
        self.expire_minutes = int(expire_minutes or os.getenv("JWT_EXPIRE_MINUTES") or 60)
        self.issuer = issuer or os.getenv("JWT_ISS")
        self.audience = audience or os.getenv("JWT_AUD")
        self.leeway_seconds = leeway_seconds

        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    # 密碼雜湊/驗證
    def hash_password(self, password: str) -> str:
        return self.pwd_context.hash(password)

    def verify_password(self, plain: str, hashed: str) -> bool:
        return self.pwd_context.verify(plain, hashed)

    # JWT 簽發
    def create_token(self, subject: str | int, extra: Optional[Dict[str, Any]] = None) -> str:
        now = datetime.now(timezone.utc)
        payload: Dict[str, Any] = {
            "sub": str(subject),  # 統一為字串，避免型別落差
            "iat": int(now.timestamp()),
            "ttl": self.expire_minutes * 60,  # 以秒為單位
            "exp": int((now + timedelta(minutes=self.expire_minutes)).timestamp()),
        }
        if self.issuer:
            payload["iss"] = self.issuer
        if self.audience:
            payload["aud"] = self.audience
        if extra:
            payload.update(extra)
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    # JWT 驗證/解碼
    def decode_token(self, token: str) -> Dict[str, Any]:
        try:
            decoded = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                options={"require": ["exp", "iat", "sub"]},
                leeway=self.leeway_seconds,
                issuer=self.issuer if self.issuer else None,
                audience=self.audience if self.audience else None,
            )
            return decoded

        except ExpiredSignatureError as e:
            # 過期：仍回 401，但訊息更明確
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="存取權杖已過期",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

        except InvalidTokenError as e:
            # 其他驗證失敗
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="無效或過期的存取權杖",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e




class CameraJWTManager:
    """
    專門用於 RTSP / HLS / WebRTC 串流的短效 Token。
    """
    def __init__(
        self,
        secret_key: Optional[str] = None,
        algorithm: Optional[str] = None,
        leeway_seconds: int = 60,
        default_publish_ttl: int = 180,  # 秒
        default_play_ttl: int = 300,     # 秒
    ):
        self.secret_key = secret_key or os.getenv("STREAM_JWT_SECRET", os.getenv("JWT_SECRET_KEY"))
        if not self.secret_key:
            raise RuntimeError("STREAM_JWT_SECRET (or JWT_SECRET_KEY) not set")

        self.algorithm = (algorithm or os.getenv("STREAM_JWT_ALG") or "HS256").upper()
        self.leeway = int(os.getenv("STREAM_TOKEN_CLOCK_SKEW", leeway_seconds))
        self.default_publish_ttl = int(os.getenv("STREAM_PUBLISH_TTL", default_publish_ttl))
        self.default_play_ttl = int(os.getenv("STREAM_PLAY_TTL", default_play_ttl))

    def issue(
        self,
        *,
        camera_id: str,
        action: str,  # "publish" | "read"
        token_version: int,
        ttl: Optional[int] = None,   # 秒
        aud: Optional[str] = None,   # "rtsp" | "hls" | "webrtc"
    ) -> str:
        ttl = int(ttl or (self.default_publish_ttl if action == "publish" else self.default_play_ttl))
        now = datetime.now(timezone.utc)
        payload: Dict[str, Any] = {
            "cid": camera_id,       # camera id（UUID）
            "action": action,       # publish / read
            "ver": int(token_version),
            "ttl": ttl, # token 存活秒數
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        }
        if aud:
            payload["aud"] = aud
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def decode(self, token: str, aud: Optional[str] = None) -> Dict[str, Any]:
        return jwt.decode(
            token,
            self.secret_key,
            algorithms=[self.algorithm],
            options={"require": ["exp", "iat", "cid", "action", "ver", "ttl"]},
            leeway=self.leeway,
            audience=aud,
        )
