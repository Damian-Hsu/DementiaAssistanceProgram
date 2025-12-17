from ..main import app
from ..DTO import *
import cv2
import numpy as np
import gc
from typing import List, Dict, Any, Optional, Tuple, Literal
from PIL import Image
import torch
import math
import json
from datetime import datetime, timedelta
from pathlib import Path
import time
import threading
import requests
import dotenv
import os
import re
import boto3
from botocore.config import Config
from urllib.parse import quote
from urllib.parse import urlparse
from pydantic import BaseModel, Field
import torch
from transformers import AutoModelForCausalLM


dotenv.load_dotenv()

# 以此檔案為錨點，而非 CWD
HERE = Path(__file__).resolve().parent           # .../tasks
ROOT = HERE.parent                               # 專案根（含 prompts、tasks 的那層）
PROMPTS_DIR = ROOT / "prompts"
_JSON_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*([\s\S]*?)\s*```", re.MULTILINE)
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system_prompt.md"
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ROOT_USER = os.getenv("MINIO_ROOT_USER", "minioadmin")
MINIO_ROOT_PASSWORD = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin")
PRESIGN_EXPIRES = int(os.getenv("PRESIGN_EXPIRES", "3600"))  # 秒
DEBUG = os.getenv("DEBUG", "0") in ["1", "true", "True"]
_S3_CLIENT = None
_S3_LOCK = threading.Lock()
_S3_URL_RE = re.compile(r"^s3://(?P<bucket>[^/]+)/(?P<key>.+)$")

def _dbg(msg: str):
    if DEBUG:
        print(f"[DEBUG] {msg}")

def _frames_dicts_summary(frames_dicts: List[Dict[str, Any]]) -> str:
    total = len(frames_dicts)
    blurry = sum(1 for f in frames_dicts if not f.get("is_not_blurry", False))
    significant = sum(1 for f in frames_dicts if f.get("is_significant", False))
    return f"frames_dicts summary: total={total}, blurry={blurry}, significant={significant}"
def _get_s3_client():
    global _S3_CLIENT
    if _S3_CLIENT is None:
        with _S3_LOCK:
            if _S3_CLIENT is None:
                _S3_CLIENT = boto3.client(
                    "s3",
                    endpoint_url=MINIO_ENDPOINT,                # 例: http://minio:30300
                    aws_access_key_id=MINIO_ROOT_USER,
                    aws_secret_access_key=MINIO_ROOT_PASSWORD,
                    config=Config(signature_version="s3v4"),   # MinIO 建議 s3v4
                    region_name=os.getenv("AWS_REGION", "us-east-1"),
                )
    return _S3_CLIENT


def _s3_to_presigned_http(url: str, *, expires: int = PRESIGN_EXPIRES) -> str:
    """
    s3://bucket/key -> https://... 的限時 GET 署名網址
    """
    m = _S3_URL_RE.match(url)
    if not m:
        return url  # 不是 s3:// 就原樣回傳

    bucket = m.group("bucket")
    key = m.group("key")

    s3 = _get_s3_client()

    try:
        presigned = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires,
        )
        return presigned
    except Exception as e:
        # 讓上層看見清楚錯誤（例如帳密/endpoint 錯、bucket 不存在等）
        raise RuntimeError(f"Presign failed for {url}: {e}") from e


def ensure_http_video_url(url: str) -> str:
    """
    若是 s3:// 就轉 presigned http(s)；否則原樣回傳。
    """
    if isinstance(url, str) and url.startswith("s3://"):
        return _s3_to_presigned_http(url)
    return url


def _generate_video_thumbnail(video_url: str, thumbnail_path: str) -> bool:
    """
    從視頻第一幀生成縮圖
    
    Args:
        video_url: 視頻 URL (可以是 s3:// 或 http://)
        thumbnail_path: 縮圖輸出路徑
    
    Returns:
        是否成功生成
    """
    try:
        import cv2
        import tempfile
        
        # 如果是 s3:// URL，先轉換為 presigned URL
        video_http_url = ensure_http_video_url(video_url)
        
        # 使用 OpenCV 讀取視頻第一幀
        cap = cv2.VideoCapture(video_http_url)
        if not cap.isOpened():
            _dbg(f"無法打開視頻: {video_url}")
            return False
        
        ret, frame = cap.read()
        cap.release()
        
        if not ret or frame is None:
            _dbg(f"無法讀取視頻第一幀: {video_url}")
            return False
        
        # 縮放圖片（寬度 320，高度按比例）
        height, width = frame.shape[:2]
        new_width = 320
        new_height = int(height * (new_width / width))
        frame_resized = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
        
        # 保存為 JPEG
        cv2.imwrite(thumbnail_path, frame_resized, [cv2.IMWRITE_JPEG_QUALITY, 85])
        _dbg(f"縮圖生成成功: {thumbnail_path}")
        return True
        
    except Exception as e:
        _dbg(f"生成縮圖失敗: {e}")
        return False


def _upload_thumbnail_to_s3(thumbnail_path: str, s3_key: str) -> bool:
    """
    上傳縮圖到 S3/MinIO
    
    Args:
        thumbnail_path: 本地縮圖路徑
        s3_key: S3 對象鍵
    
    Returns:
        是否成功上傳
    """
    try:
        s3 = _get_s3_client()
        m = _S3_URL_RE.match(s3_key) if s3_key.startswith("s3://") else None
        
        if m:
            bucket = m.group("bucket")
            key = m.group("key")
        else:
            # 如果不是 s3:// 格式，假設是 key，使用默認 bucket
            bucket = os.getenv("MINIO_BUCKET", "media-bucket")
            key = s3_key
        
        s3.upload_file(
            thumbnail_path,
            bucket,
            key,
            ExtraArgs={'ContentType': 'image/jpeg'}
        )
        _dbg(f"縮圖已上傳到 S3: s3://{bucket}/{key}")
        return True
        
    except Exception as e:
        _dbg(f"上傳縮圖到 S3 失敗: {e}")
        return False

def _build_thumbnail_object_key(user_id: int, input_url: str, recording_id: str) -> str:
    """
    產生 recordings 縮圖的 object key（不含 bucket）。
    盡量沿用原影片檔名；若無法解析，則退回 recording_id.jpg
    """
    filename = None
    try:
        if isinstance(input_url, str) and input_url.startswith("s3://"):
            # s3://bucket/key
            m = _S3_URL_RE.match(input_url)
            if m:
                key = m.group("key")
                filename = os.path.basename(key)
        elif isinstance(input_url, str) and input_url:
            # http(s)://.../xxx.mp4?...
            p = urlparse(input_url)
            filename = os.path.basename(p.path) if p and p.path else None
    except Exception:
        filename = None

    if not filename:
        filename = f"{recording_id}.mp4"

    # .mp4/.MP4 -> .jpg（其他副檔名一律改成 .jpg）
    base, ext = os.path.splitext(filename)
    if not base:
        base = str(recording_id)
    thumb_name = f"{base}.jpg"
    return f"{int(user_id)}/video_thumbnails/{thumb_name}"

def _frame_to_thumbnail_jpeg_bytes(frame_bgr: np.ndarray, *, target_width: int = 320, quality: int = 85) -> Optional[bytes]:
    """把記憶體中的 OpenCV BGR frame 轉成縮圖 JPEG bytes（不落地檔案）。"""
    try:
        if frame_bgr is None:
            return None
        h, w = frame_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return None

        new_w = int(target_width)
        if new_w <= 0:
            new_w = 320
        new_h = max(1, int(h * (new_w / w)))
        resized = cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)

        ok, buf = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
        if not ok:
            return None
        return buf.tobytes()
    except Exception as e:
        _dbg(f"_frame_to_thumbnail_jpeg_bytes failed: {e}")
        return None

def _upload_thumbnail_bytes_to_s3(jpeg_bytes: bytes, object_key: str) -> bool:
    """上傳縮圖 bytes 到 S3/MinIO（使用預設 bucket）。"""
    try:
        if not jpeg_bytes:
            return False
        s3 = _get_s3_client()
        bucket = os.getenv("MINIO_BUCKET", "media-bucket")
        s3.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=jpeg_bytes,
            ContentType="image/jpeg",
        )
        _dbg(f"縮圖 bytes 已上傳到 S3: s3://{bucket}/{object_key}")
        return True
    except Exception as e:
        _dbg(f"上傳縮圖 bytes 到 S3 失敗: {e}")
        return False

def _update_recording_thumbnail_via_api(recording_id: str, thumbnail_s3_key: str) -> bool:
    """透過 API Server 回寫 recordings.thumbnail_s3_key。"""
    try:
        if not recording_id or not thumbnail_s3_key:
            return False
        resp = requests.patch(
            f"{API_SERVER_URL}/m2m/recordings/{recording_id}/thumbnail",
            params={"thumbnail_s3_key": thumbnail_s3_key},
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        _dbg(f"錄影縮圖路徑已更新: recording_id={recording_id} -> {thumbnail_s3_key}")
        return True
    except Exception as e:
        _dbg(f"更新錄影縮圖路徑失敗: {e}")
        return False

# SSIM 需用 skimage；只有在 module="SSIM" 時才會用到
try:
    from skimage.metrics import structural_similarity as ssim
    _HAS_SKIMAGE = True
except Exception:
    _HAS_SKIMAGE = False

# 計時裝飾器
def timer(func):
    
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        _dbg(f"Function {func.__name__} took {end_time - start_time:.2f} seconds")
        return result
    return wrapper

@timer
def get_video_frames(video_url: str, target_fps: int = 3):
    video_info = {
                "video_url": video_url,
                "fps": None,
                "duration": None,  # 影片總長度（秒）
                "total_frames": None,
                "target_frame": None,
                "possible_extracts": None,
                "extracted_frames": None
            }
    _dbg(f"get_video_frames() called with video_url={video_url}, target_fps={target_fps}")
    video_url = ensure_http_video_url(video_url)
    if target_fps <= 0:
        raise ValueError("target_fps 必須是正數，且大於0")
    
    cap = cv2.VideoCapture(video_url, cv2.CAP_FFMPEG)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps * 1000  # 毫秒

    # 檢查壞檔與target_fps = 0 的雖小情況
    if fps <= 0 or total_frames <= 0:
        cap.release()
        raise ValueError(f"影片檔案無法正確讀取或總幀為0,target_fps: {target_fps}, video_original_fps: {fps}, total_frames: {total_frames}")
    if target_fps <= 0:
        raise ValueError("target_fps 必須大於0")
    
    target_frame_interval = int(fps / target_fps) # 估算
    if target_frame_interval <= 1:
        cap.release()
        raise ValueError(f"target_fps:{target_fps}過高，超過影片原始fps:{fps}，無法抽取幀，請調整為更低的值")
    interval_ms = 1000 / target_fps 
    # 計算影片理論可抽取的張數 (忽略最後不足 interval 的幀)
    
    video_info.update({
        "fps": fps,
        "total_frames": total_frames,
        "target_frame": target_fps,
    }) #我覺得整理起來比較好閱讀，有誰維護看不爽可以改掉

    # 開始正式抽幀
    output_count = 0  # 記錄已輸出幾張
    current_ms = 0.0
    frames_dicts = []
    
    while current_ms <= duration:
        cap.set(cv2.CAP_PROP_POS_MSEC, current_ms)
        ret, frame = cap.read()
        if not ret:
            break

        frames_dicts.append({
            "stamp": current_ms / 1000.0,  # 秒數
            "frame": frame
        })

        output_count += 1
        current_ms += interval_ms

    cap.release()
    video_info.update({
        "extracted_frames": output_count,
        "duration": duration / 1000.0,  # 秒數
        })
    
    # 釋放 VideoCapture 相關資源
    del cap
    gc.collect()
    
    return {
        "video_info": video_info,
        "frames": frames_dicts
    }

@timer
def get_video_frames_fast(video_url: str, target_fps: int = 3):
    """
    GPT改我程式的加速版
    """
    _dbg(f"get_video_frames_fast() called with video_url={video_url}, target_fps={target_fps}")
    video_url = ensure_http_video_url(video_url)
    if target_fps <= 0:
        raise ValueError("target_fps 必須是正數，且大於0")

    cap = cv2.VideoCapture(video_url, cv2.CAP_FFMPEG)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0 or total_frames <= 0:
        cap.release()
        raise ValueError(f"影片檔案無法正確讀取或總幀為0, target_fps: {target_fps}, video_original_fps: {fps}, total_frames: {total_frames}")

    # 以「幀」為單位計算抽樣步長（避免時間制導致重解碼）
    step = max(1, int(round(fps / target_fps)))  # 每抓一張要跳過幾幀
    effective_fps = fps / step  # 實際抽到的 fps（可能略低於 target_fps）

    frames = []
    kept = 0
    idx = 0

    # 只順序讀取，不做 set/seek
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 只保留需要的幀（以 idx 做取樣）
        if idx % step == 0:
            # 用幀索引推算時間戳（以秒）
            ts = idx / fps
            frames.append({"stamp": ts, "frame": frame})
            kept += 1

        idx += 1

    duration_sec = total_frames / fps
    cap.release()
    
    # 釋放 VideoCapture 相關資源
    del cap
    gc.collect()

    video_info = {
        "video_url": video_url,
        "fps": fps,
        "duration": duration_sec,
        "total_frames": total_frames,
        "target_frame": target_fps,
        "possible_extracts": math.floor(total_frames / step),
        "extracted_frames": kept,
        "effective_fps": effective_fps
    }
    return {"video_info": video_info, "frames": frames}
@timer
def analyze_blur(
    frames_dicts: List[Dict[str, Any]],
    threshold: float = 20.0
) -> List[Dict[str, Any]]:
    """
    針對 frames_dict（[{ 'stamp': float, 'frame': np.ndarray(BGR) }, ...]）計算清晰度。
    使用 Laplacian 變異數作為指標，低於 threshold 視為模糊。

    回傳：list[dict]，每個元素結構為
        {
            "stamp": <float>,
            "frame": <np.ndarray (BGR)>,
            "variance": <float>,          # Laplacian 變異數
            "is_not_blurry": <bool>           # 變異數 < 門檻 -> False
        }
    """
    _dbg(f"analyze_blur() call: {_frames_dicts_summary(frames_dicts)}，threshold={threshold}")
    analyzed = []

    for item in frames_dicts:
        # 預設值＆基本檢查
        stamp = None
        frame = None
        variance = np.nan
        is_blurry = True  # 無效資料一律視為模糊，讓後續容易過濾掉

        if isinstance(item, dict):
            stamp = float(item.get("stamp")) if item.get("stamp") is not None else None
            frame = item.get("frame")

        if frame is not None and hasattr(frame, "shape"):
            # gray + Laplacian
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
            lap = cv2.Laplacian(gray, cv2.CV_64F)
            variance = float(lap.var())
            is_blurry = variance <= threshold # 小於門檻視為模糊

        analyzed.append({
            "stamp": stamp,
            "frame": frame,
            "variance": variance,
            "is_not_blurry": not is_blurry # 這裡的 is_not_blurry 反轉了邏輯，True 表示清晰
        })
        
        # 每處理 10 個幀後進行一次垃圾回收（避免記憶體累積）
        if len(analyzed) % 10 == 0:
            gc.collect()

    # 處理完成後進行垃圾回收
    gc.collect()
    return analyzed

@timer
def filter_by_frame_difference(
    frames_dicts: List[Dict[str, Any]],
    threshold: float = 0.8,
    compression_proportion: float = 0.5,
    module: str = "SSIM"):
    """
    module:
    "MSE_L2" : 灰階均方差，"({n}-({n-1}))^2 if n < 1"
    "SSIM" : 結構相似度，{\\displaystyle {\\text{SSIM}}(\\mathbf {x} ,\\mathbf {y} )=
    [l(\\mathbf {x} ,\\mathbf {y} )]^{\\alpha }
    [c(\\mathbf {x} ,\\mathbf {y} )]^{\\beta }
    [s(\\mathbf {x} ,\\mathbf {y} )]^{\\gamma }}(維基抄下來的，還有一堆沒有抄，好奇的自己去查)

    step 1 : 將影像壓縮，並形成對應的 key -> stamp ; value -> frame
    step 2 : 掠過第一張，從第二張開始，與前一張做差異比對，並根據key 修改原始dict的參數 
    """
    _dbg(f"filter_by_frame_difference() call: {_frames_dicts_summary(frames_dicts)}，threshold={threshold}, compression_proportion={compression_proportion}, module={module}")
    if module not in ["MSE_L2", "SSIM"]:
        raise ValueError("module 必須是 'MSE_L2' 或 'SSIM'")
    if module == "SSIM" and not _HAS_SKIMAGE:
        raise ImportError("使用 SSIM 需要安裝 scikit-image：pip install scikit-image")

    compression_frames = [
        {   "stamp": item["stamp"],
            "frame": cv2.resize(
                        cv2.cvtColor(item["frame"], cv2.COLOR_BGR2GRAY) if item["frame"].ndim == 3 else item["frame"],
                        (0, 0),
                        fx=compression_proportion,
                        fy=compression_proportion
                    )
        }
        for item in frames_dicts.copy()
     ] # 複製的 frames_dicts，避免修改原始資料，並壓縮影像作運算
    
    filtered_frames = [] #處理過的陣列
    for idx in range(len(compression_frames)):  # ← 索引修正
        if idx == 0:
            filtered_item = frames_dicts[idx].copy()
            filtered_item["ssim_value"] = 0 if module == "SSIM" else None
            filtered_item["mse_value"] = 0 if module == "MSE_L2" else None
            filtered_item["is_significant"] = True
            filtered_frames.append(filtered_item)
            continue

        current_frame = compression_frames[idx]["frame"]
        previous_frame = compression_frames[idx - 1]["frame"]
        diff_value = 0
        ssim_value = 0
        is_significant = False
        if module == "MSE_L2":
            
            diff_value = np.mean((current_frame - previous_frame) ** 2)
            is_significant = diff_value >= threshold
        elif module == "SSIM":
            # using skimage
            ssim_value = ssim(current_frame, previous_frame, data_range=255)
            # 越大越相似，我們要剃除相似，所以小於門檻的視為重要幀
            is_significant = ssim_value <= threshold

        filtered_item = frames_dicts[idx].copy()
        filtered_item["ssim_value"] = ssim_value if module == "SSIM" else None
        filtered_item["mse_value"] = diff_value if module == "MSE_L2" else None
        filtered_item["is_significant"] = bool(is_significant)
        filtered_frames.append(filtered_item)
    
    # 清理壓縮後的幀列表（不再需要）
    del compression_frames
    gc.collect()
    
    return filtered_frames  # 返回處理後的幀列表，包含是否顯著的標記


    # 處理方式規劃2,如過速度太慢再回來做
    # A = [0,1,2,3,4,....]
    # B = [ ,0,1,2,3,....]
    # A - B 


# 你原本就有的 _dbg / timer / _frames_dicts_summary ... 這裡沿用

class Moondream2ImageCaptioner:
    """
    Moondream2 captioner (Transformers).
    Uses model.caption(image, length=..., settings=...)  (no BLIP processor needed).
    Docs: https://docs.moondream.ai/transformers/  :contentReference[oaicite:2]{index=2}
    """

    def __init__(
        self,
        model_name: str = "vikhyatk/moondream2",
        cache_dir: str = "/srv/app/adapters/.cache/transformers",
        device: Optional[str] = None,
        dtype: Optional[torch.dtype] = None,
        device_map: Optional[str] = None,
        use_4bit: bool = False,
    ):
        self.device = device if device else ("cuda" if torch.cuda.is_available() else "cpu")
        self.cache_dir = cache_dir

        # dtype：6GB VRAM 常見用 float16；若你是 A100/L4 之類也可 bfloat16
        if dtype is None:
            dtype = torch.float16 if self.device.startswith("cuda") else torch.float32

        # device_map：Moondream docs 用 device_map="cuda"/"mps" 的寫法 :contentReference[oaicite:3]{index=3}
        if device_map is None:
            device_map = "cuda" if self.device.startswith("cuda") else "cpu"

        _dbg(f"Initializing Moondream2ImageCaptioner model={model_name} device={self.device} "
             f"dtype={dtype} device_map={device_map} use_4bit={use_4bit}")

        os.makedirs(self.cache_dir, exist_ok=True)

        # 4-bit（可選）：更容易塞進 6GB，但需要 bitsandbytes
        quant_kwargs = {}
        if use_4bit:
            try:
                from transformers import BitsAndBytesConfig
                quant_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=dtype,
                )
            except Exception as e:
                raise RuntimeError(
                    "use_4bit=True 需要安裝 bitsandbytes，且你的環境要支援。"
                ) from e

        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            cache_dir=self.cache_dir,
            trust_remote_code=True,   # Moondream2 必須開 :contentReference[oaicite:4]{index=4}
            dtype=dtype,
            device_map=device_map,
            **quant_kwargs,
        )
        self.model.eval()

        # 若你會反覆呼叫（很多幀），官方也提到可以 compile() 提升速度（可選） :contentReference[oaicite:5]{index=5}
        # try:
        #     self.model.compile()
        # except Exception:
        #     pass

    @torch.inference_mode()
    def describe(self, image_input, length: str = "normal", max_tokens: int = 128) -> str:
        """
        Args:
            image_input: 圖片路徑（str）或 PIL.Image
            length: "short" | "normal" | "long"  :contentReference[oaicite:6]{index=6}
            max_tokens: 上限（Moondream 的 settings.max_tokens） :contentReference[oaicite:7]{index=7}
        """
        _dbg(f"Moondream2ImageCaptioner.describe() called with image_input type {type(image_input)}")

        if isinstance(image_input, str):
            image = Image.open(image_input).convert("RGB")
        elif isinstance(image_input, Image.Image):
            image = image_input.convert("RGB")
        else:
            raise TypeError("請提供圖片路徑或 PIL Image 物件")

        settings = {"max_tokens": int(max_tokens)}
        result = self.model.caption(image, length=length, settings=settings)  # :contentReference[oaicite:8]{index=8}
        caption = result["caption"] if isinstance(result, dict) else str(result)

        # 你原本的清理習慣保留
        del image
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        return caption


_CAPTIONER = None
_CAPTIONER_LOCK = threading.Lock()

def get_captioner() -> Moondream2ImageCaptioner:
    global _CAPTIONER
    _dbg("get_captioner() called")
    if _CAPTIONER is None:
        with _CAPTIONER_LOCK:
            if _CAPTIONER is None:
                os.makedirs("/srv/app/adapters/.cache/transformers", exist_ok=True)
                _CAPTIONER = Moondream2ImageCaptioner(
                    model_name="vikhyatk/moondream2",
                    cache_dir="/srv/app/adapters/.cache/transformers",
                    device=None,
                    # < 6GB 先開：
                    use_4bit=True,
                    # dtype=torch.float16,  # 視你的 GPU 而定
                )
    return _CAPTIONER



@timer
def img_captioning(frames_dicts: List[Dict[str, Any]]):
    """
    Generate image captions for selected video frames using a singleton VLM captioner.

    Design considerations:
    - Frames are processed sequentially to avoid GPU memory spikes.
    - Only frames passing blur/significance filters are sent to the vision-language model.
    - Aggressive memory cleanup is intentionally applied to support low-VRAM GPUs (≈6GB).
    - The captioner instance is reused (singleton) to avoid repeated model initialization.
    """

    _dbg(f"img_captioning() called with {_frames_dicts_summary(frames_dicts)}")

    # Singleton captioner:
    # The underlying model is heavy (VLM + vision encoder),
    # so we ensure it is instantiated exactly once per process.
    captioner = get_captioner()

    processed_count = 0

    for idx, item in enumerate(frames_dicts):
        # Skip frames that are either blurry or semantically insignificant.
        # This acts as a cheap pre-filter to reduce expensive VLM invocations.
        if item["is_not_blurry"] and item["is_significant"]:
            frame = item["frame"]

            # Convert OpenCV BGR frame to PIL RGB image.
            # PIL.Image is required by most HuggingFace / VLM APIs.
            image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(image_rgb)

            # Run vision-language inference.
            # max_tokens is intentionally bounded to:
            #   1) prevent excessive KV-cache growth
            #   2) stabilize VRAM usage under repeated calls
            caption = captioner.describe(
                pil_image,
                length="normal",
                max_tokens=96
            )

            # Persist caption back into the frame metadata.
            item["caption"] = caption
            processed_count += 1

            # Explicitly release large Python-side objects after each iteration.
            # This reduces CPU RAM pressure and prevents delayed reference cleanup.
            del image_rgb
            del pil_image

            # Periodic deep cleanup:
            # - gc.collect(): reclaim Python objects that are no longer referenced
            # - torch.cuda.empty_cache(): release unused CUDA memory back to the allocator
            #
            # Running this every frame would cause performance jitter,
            # so we batch it every N frames as a compromise between stability and throughput.
            if processed_count % 5 == 0:
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
        else:
            # Mark skipped frames explicitly to keep downstream logic simple and explicit.
            item["caption"] = "<skipped due to blur or insignificance>"

    # Final cleanup to ensure no residual allocations remain
    # before returning control to the caller.
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return frames_dicts


# ====== LLM Schema 定義 ======

class LLMEvent(BaseModel):
    """LLM 返回的單一事件結構"""
    start_index: int = Field(description="事件起始索引值，對應 describe.frames[i].index")
    end_index: int = Field(description="事件結束索引值")
    summary: str = Field(description="事件內的場景描述以及使用者正在做的事")
    objects: List[str] = Field(default_factory=list, description="事件中出現的物件")
    scene: Optional[str] = Field(None, description="推測的場景（從場景集合中擇一）")
    action: Optional[str] = Field(None, description="推測目前發生行為")


class LLMRound(BaseModel):
    """LLM 推理輪次"""
    thought: Optional[str] = Field(None, description="推理與思考過程")
    reflection: Optional[str] = Field(None, description="反思標籤")
    events: List[LLMEvent] = Field(default_factory=list, description="事件的切分陣列")


class LLMFinalAnswer(BaseModel):
    """LLM 最終答案"""
    events: List[LLMEvent] = Field(default_factory=list, description="最終的事件陣列")


class LLMResponse(BaseModel):
    """LLM 完整回應結構"""
    rounds: List[LLMRound] = Field(default_factory=list, description="推理區域")
    final_answer: LLMFinalAnswer = Field(description="最終的答案")


def _extract_first_json_substring(s: str) -> Optional[str]:
    """
    在任意字串中找出第一個「平衡的」JSON 物件或陣列子字串。
    支援跳過字串中的大括號（會處理跳脫字元）。
    回傳子字串（含最外層 { } 或 [ ]），找不到回 None。
    """
    in_str = False
    esc = False
    quote = ""
    start = None
    depth = 0

    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            continue

        # 不在字串內
        if ch == '"' or ch == "'":
            in_str = True
            quote = ch
            continue

        if ch == "{" or ch == "[":
            if start is None:
                start = i
            depth += 1
            continue

        if ch == "}" or ch == "]":
            if start is not None:
                depth -= 1
                if depth == 0:
                    return s[start:i+1]

    return None

def clean_model_output(model_output: Any) -> Optional[Any]:
    """
    將 LLM 回傳文本清成可用的 JSON 物件。
    支援：
      - ```json fenced blocks```
      - 夾雜敘述文字的回應（自動擷取第一個平衡的 JSON）
      - 輸入已是 dict/list 時直接回傳
    """
    # 先處理已是 JSON 的情形
    if isinstance(model_output, (dict, list)):
        return model_output
    if model_output is None:
        return None

    s = str(model_output).strip()
    # 清掉常見不可見字元，避免 loads 受影響
    s = s.replace("\u00A0", " ").replace("\u200B", "")

    candidates: list[str] = []

    # 先嘗試 fenced blocks（可能有多段，逐一嘗試）
    fences = _JSON_FENCE_RE.findall(s)
    for block in fences:
        block = block.strip()
        if block:
            candidates.append(block)

    # 整段原文也加入候選
    candidates.append(s)

    # 逐一嘗試解析
    for cand in candidates:
        # 直接解析 JSON
        try:
            return json.loads(cand)
        except Exception:
            pass

        # 從候選中抽取第一個平衡 JSON 子字串
        sub = _extract_first_json_substring(cand)
        if sub:
            try:
                return json.loads(sub)
            except Exception:
                pass

    # 都失敗就回 None
    return None
@timer
def llm_processing(frames_dicts: List[Dict[str, Any]],
                   number_of_trys: int = 3,
                   api_key: Optional[str] = None):
    """使用 LLM 處理視頻幀，生成事件描述。
    
    使用 Google Gemini API 和 Pydantic Schema 規範輸出格式，
    確保返回結構化的事件列表。
    
    Args:
        frames_dicts: 視頻幀列表，每個包含 caption, stamp 等資訊
        number_of_trys: 重試次數，預設 3
        api_key: Google API Key（必填，必須由 job params 傳入）
        
    Returns:
        Tuple[dict, List[Dict[str, Any]], dict]: (LLM 結果字典, frames_summary, usage)
        
    Raises:
        ValueError: 當輸入參數無效時
        FileNotFoundError: 當 system_prompt.md 不存在時
        RuntimeError: 當所有重試都失敗時
    """
    _dbg(f"llm_processing() called with {_frames_dicts_summary(frames_dicts)}，number_of_trys={number_of_trys}")
    
    # 錯誤檢查
    if not frames_dicts or not isinstance(frames_dicts, list):
        raise ValueError("frames_dicts 必須是非空的列表")
    if number_of_trys < 1:
        raise ValueError("number_of_trys 必須大於等於1")  

    # 嚴格確認檔案存在，不存在就早點報錯好排查
    if not SYSTEM_PROMPT_PATH.is_file():
        raise FileNotFoundError(f"system_prompt.md not found at: {SYSTEM_PROMPT_PATH}")

    with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    # 先處理 frames_dicts，確保每個幀都有 caption
    del_list = ["frame", "is_not_blurry", "is_significant", "variance", "ssim_value", "mse_value"]
    # 跳過 is_not_blurry 與 is_significant 為 False 的幀
    new_frames_dicts = []
    for item in frames_dicts:
        if item["is_not_blurry"] and item["is_significant"]:
            new_frames_dicts.append(item)

    cleaned_frames = [
        {k: v for k, v in fr.items() if k not in del_list}
        for fr in new_frames_dicts
    ]
    
    # 清理不再需要的原始幀數據
    del new_frames_dicts
    gc.collect()
    
    frames_summary = [
        {
            "index": i,
            "stamp": fr.get("stamp"),
            "caption": fr.get("caption", "")
        }
        for i, fr in enumerate(cleaned_frames)
    ]
    _dbg(f"Frames prepared for LLM: {len(frames_summary)} frames.")
    
    # 準備 prompt
    prompt_text = json.dumps({
        "system_prompt": system_prompt,
        "describe": {
            "frames": frames_summary
        }
    }, ensure_ascii=False, indent=2)

    # 使用新的 Google Gemini API（google-genai）和 Schema
    # 注意：google-generativeai 舊 SDK 的 import 是 google.generativeai；本專案使用 google-genai。
    import google.genai as genai
    from google.genai import types
    
    # 獲取 API Key（必須從 job params 中提供，不允許從環境變數讀取）
    if not api_key:
        raise ValueError("GOOGLE_API_KEY 未設定（請在建立 job 時提供 google_api_key 參數）")
    
    client = genai.Client(api_key=api_key)
    
    # 定義 Safety Settings（關閉安全檢查）
    safety_settings = [
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF"),
    ]
    
    # 使用 Schema 規範輸出
    model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash-lite")
    max_output_tokens = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "65535"))
    
    # 構建 GenerateContentConfig，使用 Schema
    generate_content_config = types.GenerateContentConfig(
        temperature=0.0,
        system_instruction=system_prompt,
        max_output_tokens=max_output_tokens,
        response_modalities=["TEXT"],
        response_mime_type="application/json",
        response_schema=LLMResponse.model_json_schema(),
        safety_settings=safety_settings
    )
    
    # 如果輸出失敗，或者無法轉換成 JSON，則重試 number_of_trys 次
    output_num = number_of_trys
    result = None
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def _extract_usage(resp: Any) -> dict:
        """從 google.genai 回應萃取 token 使用量（盡量相容不同 SDK）。"""
        u = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if resp is None:
            return u
        meta = getattr(resp, "usage_metadata", None) or getattr(resp, "usage", None)
        if meta is None and isinstance(resp, dict):
            meta = resp.get("usage_metadata") or resp.get("usage")

        def _get(obj: Any, key: str) -> int:
            if obj is None:
                return 0
            try:
                if isinstance(obj, dict):
                    v = obj.get(key)
                else:
                    v = getattr(obj, key, None)
                return int(v) if v is not None else 0
            except Exception:
                return 0

        prompt = _get(meta, "prompt_token_count") or _get(meta, "prompt_tokens")
        completion = _get(meta, "candidates_token_count") or _get(meta, "completion_tokens")
        total = _get(meta, "total_token_count") or _get(meta, "total_tokens")
        if not total and (prompt or completion):
            total = prompt + completion

        u["prompt_tokens"] = max(0, int(prompt))
        u["completion_tokens"] = max(0, int(completion))
        u["total_tokens"] = max(0, int(total))
        return u
    
    while number_of_trys > 0:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[prompt_text],
                config=generate_content_config,
            )
            usage = _extract_usage(response)
            
            # 解析 JSON 回應
            response_text = response.text
            _dbg(f"{output_num-number_of_trys+1} of try. LLM raw output: {response_text[:200]}...")
            
            # 驗證並解析回應
            parsed_result = json.loads(response_text)
            
            # 使用 Pydantic 驗證結構
            validated_result = LLMResponse.model_validate(parsed_result)
            
            # 轉換回字典格式（保持向後兼容）
            result = validated_result.model_dump()
            _dbg(f"{output_num-number_of_trys+1} of try. LLM validated output: {len(result.get('final_answer', {}).get('events', []))} events")
            
            if result:
                break
                
        except json.JSONDecodeError as e:
            _dbg(f"{output_num-number_of_trys+1} of try. JSON 解析失敗: {e}")
            number_of_trys -= 1
        except Exception as e:
            _dbg(f"{output_num-number_of_trys+1} of try. LLM 調用失敗: {e}")
            number_of_trys -= 1
    
    if not result:
        raise RuntimeError(f"模型嘗試超過規定{output_num}次錯誤，請檢查模型輸出或重試。")

    # 返回結果和 frames_summary
    return result, frames_summary, usage
# ---- 工具：解析 ISO 時間（允許 None） ----
def _parse_iso_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # 支援 "Z"
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

# ---- 從 LLM 回傳抓出 events（優先 final_answer.events，其次 rounds[*].events 聚合）----
def _pick_llm_events(payload: dict) -> List[dict]:
    final = payload.get("final_answer", {})
    evs = final.get("events", [])
    if isinstance(evs, list) and evs:
        return evs
    rounds = payload.get("rounds", []) or []
    agg = []
    for r in rounds:
        revents = r.get("events", [])
        if isinstance(revents, list):
            agg.extend(revents)
    return agg

# ---- index → 秒數：使用 frames_summary 的 stamp；夾限並回傳是否有夾限 ----
def _idx_to_time_from_summary(frames_summary: List[Dict[str, Any]], idx: int) -> Tuple[float, bool]:
    """
    回傳 (stamp_in_seconds, clamped_flag)
    """
    if not frames_summary:
        return 0.0, False
    n = len(frames_summary)
    orig = idx
    i = max(0, min(int(idx), n - 1))
    clamped = (i != orig)
    ts = frames_summary[i].get("stamp", 0.0)
    try:
        return float(ts), clamped
    except Exception:
        return 0.0, clamped

# ---- 用 index 強制映射成 EventItem 結構需要的欄位 ----
def _build_events_from_llm_by_index(llm_result: dict,
                                    frames_summary: List[Dict[str, Any]],
                                    *,
                                    epsilon: float = 1e-3) -> Tuple[List[Dict[str, Any]], int]:
    """
    僅使用 start_index/end_index；完全忽略任何 start_time/end_time。
    產出符合 EventItem 的 dict 清單（不依賴 Pydantic 類別，方便序列化）。
    回傳 (events, clamp_count)，clamp_count 表示索引被夾限的次數（除錯用）。
    """
    raw_events = _pick_llm_events(llm_result)
    events: List[Dict[str, Any]] = []
    clamp_count = 0

    for ev in raw_events:
        if "start_index" not in ev or "end_index" not in ev:
            # 沒有索引就跳過
            continue
        try:
            s_idx = int(ev["start_index"])
            e_idx = int(ev["end_index"])
        except Exception:
            continue

        # 順序修正
        if s_idx > e_idx:
            s_idx, e_idx = e_idx, s_idx

        # 索引轉時間（夾限）
        st, c1 = _idx_to_time_from_summary(frames_summary, s_idx)
        et, c2 = _idx_to_time_from_summary(frames_summary, e_idx)
        clamp_count += int(c1) + int(c2)

        # 安全處理：避免 0 長度事件
        if et < st:
            st, et = et, st
        if abs(et - st) < epsilon:
            et = st + epsilon

        # 組裝成 EventItem 對應的 dict
        try:
            events.append({
                "start_time": float(st),
                "end_time": float(et),
                "summary": str(ev.get("summary", "")).strip() or "(no summary)",
                "objects": list(ev.get("objects", []) or []),
                "scene": ev.get("scene"),
                "action": ev.get("action"),
            })
        except Exception:
            # 單筆壞掉就略過
            continue

    return events, clamp_count

# ---- 收集 metrics（含幀處理與 LLM 事件統計）----
def _collect_metrics(video_info: dict,
                     frames_with_flags: List[Dict[str, Any]],
                     frames_summary: List[Dict[str, Any]],
                     *,
                     llm_events_count: int = 0,
                     index_clamp_count: int = 0) -> Dict[str, Any]:
    total = len(frames_with_flags)
    not_blurry = sum(1 for x in frames_with_flags if x.get("is_not_blurry"))
    significant = sum(1 for x in frames_with_flags if x.get("is_significant"))
    captioned = sum(
        1 for x in frames_with_flags
        if isinstance(x.get("caption"), str)
        and x["caption"]
        and x["caption"] != "<skipped due to blur or insignificance>"
    )
    kept_for_llm = len(frames_summary)

    return {
        # 影片層級
        "video_fps": video_info.get("fps"),
        "video_total_frames": video_info.get("total_frames"),
        "video_duration_sec": video_info.get("duration"),
        "target_fps": video_info.get("target_frame"),
        "effective_fps": video_info.get("effective_fps"),
        "extracted_frames": video_info.get("extracted_frames"),
        "possible_extracts": video_info.get("possible_extracts"),

        # 幀處理統計
        "frames_total": total,
        "frames_not_blurry": not_blurry,
        "frames_significant": significant,
        "frames_captioned": captioned,
        "frames_kept_for_llm": kept_for_llm,
        "not_blurry_rate": (not_blurry / total) if total else 0.0,
        "significant_rate": (significant / total) if total else 0.0,
        "captioned_rate": (captioned / total) if total else 0.0,

        # LLM 結果統計
        "llm_events_count": llm_events_count,
        "index_clamp_count": index_clamp_count,
    }

# ---- 建立成功／失敗的 JobResult dict（不綁定 Pydantic，方便 Celery 回傳）----
def _make_success_jobresult(job: dict,
                            video_info: dict,
                            events: List[Dict[str, Any]],
                            frames_with_flags: List[Dict[str, Any]],
                            frames_summary: List[Dict[str, Any]]) -> Dict[str, Any]:
    # video_start_time / video_end_time 推算
    video_start_dt = _parse_iso_dt(job.get("params", {}).get("video_start_time"))
    video_end_dt = None
    try:
        dur = float(video_info.get("duration")) if video_info.get("duration") is not None else None
    except Exception:
        dur = None
    if video_start_dt and isinstance(dur, float):
        video_end_dt = video_start_dt + timedelta(seconds=dur)

    metrics = _collect_metrics(
        video_info, frames_with_flags, frames_summary,
        llm_events_count=len(events), index_clamp_count=0  # 這裡的 clamp 計數從外層丟
    )

    return {
        "job_id": job.get("job_id", "?"),
        "trace_id": job.get("trace_id"),
        "status": "success",  # JobStatus.SUCCESS
        "video_start_time": video_start_dt.isoformat() if video_start_dt else None,
        "video_end_time": video_end_dt.isoformat() if video_end_dt else None,
        "error_code": None,
        "error_message": None,
        "duration": None, # 任務運行時間
        "metrics": metrics,
        "events": events,
    }

def _make_failed_jobresult(job: dict,
                           video_info: Optional[dict],
                           *,
                           code: str,
                           message: str,
                           frames_with_flags: Optional[List[Dict[str, Any]]] = None,
                           frames_summary: Optional[List[Dict[str, Any]]] = None,
                           raw_llm: Optional[dict] = None,
                           index_clamp_count: int = 0) -> Dict[str, Any]:
    video_start_dt = _parse_iso_dt(job.get("params", {}).get("video_start_time"))
    metrics = None
    if video_info is not None:
        metrics = _collect_metrics(
            video_info,
            frames_with_flags or [],
            frames_summary or [],
            llm_events_count=0,
            index_clamp_count=index_clamp_count,
        )
        if raw_llm is not None:
            metrics["raw_llm_result"] = raw_llm

    return {
        "job_id": job.get("job_id", "?"),
        "trace_id": job.get("trace_id"),
        "status": "failed",  # JobStatus.FAILED
        "video_start_time": video_start_dt.isoformat() if video_start_dt else None,
        "video_end_time": None,
        "error_code": code,
        "error_message": message,
        "duration": None,
        "metrics": metrics,
        "events": [],
    }

from ..libs.RAG import RAGModel

def video_description_extraction_main(job: dict):
    """
    step 1 : 從 job 取得 video_url
    step 2 : 將影片讀取至記憶體 (opencv)，並壓縮大小(先略過，等後續優化)
    step 3 : 將影片分割成幀(抽幀，3秒一幀)，並做成 {"stamp": "幀的相對時間", "frame": 幀圖片} 的dict格式
    step 4 : 去除資訊量過低的幀(模糊的、單色無明顯邊緣的)
    step 5 : 將幀與上一步的幀做差異比對，過濾掉與前一幀差異過小的幀 (先略過，等後續優化)
    step 6 : 透過 MDL.BLIPImageCaptioner載入Captioner Model
    step 7 : 將剩餘的幀送入Captioner Model，取得每一幀的描述
    step 8 : 將每一幀的描述與時間戳放入prompt中，組成完整的prompt
    step 9 : 將prompt送入 LLM（使用 Schema 規範輸出），取得最終的描述
    step 10: 將結果整理成對應格式，呼叫API Server，讓結果存入資料庫
    (感覺缺了一個模型存活時間控管的模塊，需要研究如何讓有任務的狀態下不重複載入模型，直到所有任務做完後1分鐘再釋放模型記憶體)

    """
    try:
        _dbg(f"job received: {json.dumps(job) if isinstance(job, dict) else str(job)}")
        # === Step 1~3: 取幀 ===
        reply = get_video_frames_fast(
            video_url=job.get("input_url", ""),
            target_fps=int(job.get("params", {}).get("target_fps", 3))
        )
        video_info = reply["video_info"]
        frames = reply["frames"]

        # === Step 4: 模糊度過濾 ===
        reply = analyze_blur(
            frames_dicts=frames,
            threshold=float(job.get("params", {}).get("blur_threshold", 20.0))
        )

        # === Step 5: 幀差過濾 ===
        reply = filter_by_frame_difference(
            frames_dicts=reply,
            threshold=float(job.get("params", {}).get("difference_threshold", 0.8)),
            compression_proportion=float(job.get("params", {}).get("compression_proportion", 0.5)),
            module=job.get("params", {}).get("difference_module", "SSIM")
        )

        # === Step 6~7: Caption ===
        reply = img_captioning(reply)

        # === Step 8~9: LLM ===
        # 從 job params 中獲取 Google API Key（如果有的話）
        google_api_key = job.get("params", {}).get("google_api_key")
        llm_result, frames_summary, llm_usage = llm_processing(reply, api_key=google_api_key)

        # 安全檢查：frames_summary 必須存在且非空，否則無法做 index→秒
        if not isinstance(frames_summary, list) or len(frames_summary) == 0:
            return _make_failed_jobresult(
                job, video_info,
                code="INDEX_MAPPING_EMPTY",
                message="frames_summary 為空，無法從 index 映射時間戳。",
                frames_with_flags=reply,
                frames_summary=frames_summary,
                raw_llm=llm_result
            )

        # === 強制用 index→秒數映射，完全忽略任何 start_time/end_time ===
        events, clamp_count = _build_events_from_llm_by_index(llm_result, frames_summary)

        # === Calculate Embeddings (Added) ===
        try:
            rag = RAGModel.get_instance()
            for event in events:
                summary_text = event.get("summary", "")
                if summary_text:
                    emb = rag.encode([f"passage: {summary_text}"])[0]
                    event["embedding"] = emb.tolist()
        except Exception as e:
            _dbg(f"Embedding calculation failed: {e}")

        if not events:
            return _make_failed_jobresult(
                job, video_info,
                code="INVALID_LLM_EVENTS",
                message="LLM 回傳缺少有效的 start_index/end_index。",
                frames_with_flags=reply,
                frames_summary=frames_summary,
                raw_llm=llm_result
            )

        # 成功：組裝 JobResult
        jr = _make_success_jobresult(job, video_info, events, reply, frames_summary)
        # 補回夾限統計
        if isinstance(jr.get("metrics"), dict):
            jr["metrics"]["index_clamp_count"] = clamp_count
            # 回傳給 API Server，讓後端能統計使用者 Token 使用量（compute service）
            if isinstance(llm_usage, dict):
                jr["metrics"]["llm_prompt_tokens"] = int(llm_usage.get("prompt_tokens") or 0)
                jr["metrics"]["llm_completion_tokens"] = int(llm_usage.get("completion_tokens") or 0)
                jr["metrics"]["llm_total_tokens"] = int(llm_usage.get("total_tokens") or 0)
                # 供 API Server 記錄使用的模型資訊
                jr["metrics"]["llm_provider"] = "google"
                jr["metrics"]["llm_model"] = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash-lite")

        # ====== 影片完成後立刻生成縮圖（併入 videosprocessing；不再依賴 thumbnail_tasks）======
        try:
            params = job.get("params", {}) if isinstance(job, dict) else {}
            recording_id = params.get("video_id") or params.get("recording_id") or job.get("video_id") or job.get("recording_id")
            user_id = params.get("user_id") or job.get("user_id")
            input_url = job.get("input_url", "")

            # 僅在必要資訊齊全、且已抽到幀的情況下生成縮圖
            if recording_id and user_id and isinstance(frames, list) and len(frames) > 0:
                # 直接用記憶體裡的第一張幀（已在本任務讀取/解碼）
                first_frame = frames[0].get("frame") if isinstance(frames[0], dict) else None
                jpeg_bytes = _frame_to_thumbnail_jpeg_bytes(first_frame)
                if jpeg_bytes:
                    thumb_key = _build_thumbnail_object_key(int(user_id), str(input_url), str(recording_id))
                    if _upload_thumbnail_bytes_to_s3(jpeg_bytes, thumb_key):
                        _update_recording_thumbnail_via_api(str(recording_id), thumb_key)
        except Exception as e:
            _dbg(f"[Thumbnail Inline] failed: {e}")

        return jr

    except Exception as e:
        # 報錯的程式返回格式
        # 發生錯誤時也要清理記憶體
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        return _make_failed_jobresult(
            job, video_info if "video_info" in locals() else None,
            code=getattr(e, "__class__", type(e)).__name__,
            message=str(e)
        )
    finally:
        # 任務完成後強制清理記憶體
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    

API_SERVER_URL = os.getenv("JOB_API_BASE", "http://api:30000")
headers = {
    "X-API-Key": os.getenv("JOB_API_KEY", ""),
    "Content-Type": "application/json"
}

@app.task(name="tasks.video_description_extraction", bind=True, acks_late=True)
def video_description_extraction(self, job: dict):
    start_time = time.time()
    try:
        reply = video_description_extraction_main(job)
        end_time = time.time()
        duration = end_time - start_time
        reply["duration"] = duration
        # 呼叫 API Server，將結果存入資料庫
        # print("URL："+job.get('input_url', ''))
        # print(reply)
        _dbg(f"Posting result to {API_SERVER_URL}/jobs/{job.get('job_id', '?')}/complete")
        _dbg(f"Result: {json.dumps(reply) if isinstance(reply, dict) else str(reply)}")
        try:
            response = requests.post(
                f"{API_SERVER_URL}/jobs/{job.get('job_id', '?')}/complete",
                headers=headers,
                json=reply,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        
        except requests.RequestException as e:
            # API 呼叫失敗，回傳錯誤訊息
            err_body = None
            try:
                if getattr(e, "response", None) is not None:
                    err_body = e.response.text
            except Exception:
                err_body = None
            if err_body:
                _dbg(f"[CompleteJob] API ERROR body: {err_body[:2000]}")
            return {
                "job_id": job.get("job_id", "?"),
                "trace_id": job.get("trace_id"),
                "error_code": "API_CALL_FAILED",
                "error_message": f"{str(e)}; body={err_body}" if err_body else str(e)
            }
    finally:
        # 任務完成後強制清理記憶體
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

