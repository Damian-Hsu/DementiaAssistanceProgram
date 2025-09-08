from ..CeleryApp import app
from ..DTO import *
import cv2
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image
import torch
from transformers import BlipProcessor, BlipForConditionalGeneration
import math
import json
from datetime import datetime, timedelta
from pathlib import Path
import time

# 以此檔案為錨點，而非 CWD
HERE = Path(__file__).resolve().parent           # .../tasks
ROOT = HERE.parent                               # 專案根（含 prompts、tasks 的那層）
PROMPTS_DIR = ROOT / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system_prompt.md"


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
        print(f"Function {func.__name__} took {end_time - start_time:.2f} seconds")
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
    if target_fps <= 0:
        raise ValueError("target_fps 必須是正數，且大於0")
    
    cap = cv2.VideoCapture(video_url)
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
    return {
        "video_info": video_info,
        "frames": frames_dicts
    }

@timer
def get_video_frames_fast(video_url: str, target_fps: int = 3):
    """
    GPT改我程式的加速版
    """
    if target_fps <= 0:
        raise ValueError("target_fps 必須是正數，且大於0")

    cap = cv2.VideoCapture(video_url)
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
    "SSIM" : 結構相似度，{\displaystyle {\text{SSIM}}(\mathbf {x} ,\mathbf {y} )=
    [l(\mathbf {x} ,\mathbf {y} )]^{\alpha }
    [c(\mathbf {x} ,\mathbf {y} )]^{\beta }
    [s(\mathbf {x} ,\mathbf {y} )]^{\gamma }}(維基抄下來的，還有一堆沒有抄，好奇的自己去查)

    step 1 : 將影像壓縮，並形成對應的 key -> stamp ; value -> frame
    step 2 : 掠過第一張，從第二張開始，與前一張做差異比對，並根據key 修改原始dict的參數 
    """
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

    return filtered_frames  # 返回處理後的幀列表，包含是否顯著的標記


    # 處理方式規劃2,如過速度太慢再回來做
    # A = [0,1,2,3,4,....]
    # B = [ ,0,1,2,3,....]
    # A - B 

class BLIPImageCaptioner:
    
    def __init__(self, model_name="Salesforce/blip-image-captioning-base", device=None):
        # print(f"🔁 正在載入 BLIP 模型：{model_name}")
        self.device = device if device else ("cuda" if torch.cuda.is_available() else "cpu")

        self.processor = BlipProcessor.from_pretrained(model_name)
        self.model = BlipForConditionalGeneration.from_pretrained(model_name)
        self.model.to(self.device)

        # print(f"✅ BLIP 模型已載入至 {self.device}。")

    def describe(self, image_input):
        """
        將圖像轉為自然語言敘述。

        Args:
            image_input: 圖片路徑（str）或 PIL.Image 對象
            prompt: 給模型的指令提示詞（BLIP-base 不需要，可為 None）

        Returns:
            caption: 圖像描述文字（str）
        """
        if isinstance(image_input, str):
            image = Image.open(image_input).convert("RGB")
        elif isinstance(image_input, Image.Image):
            image = image_input
        else:
            raise TypeError("請提供圖片路徑或 PIL Image 物件")

        inputs = self.processor(image, return_tensors="pt").to(self.device)
        generated_ids = self.model.generate(**inputs, max_new_tokens=50)
        caption = self.processor.decode(generated_ids[0], skip_special_tokens=True)

        return caption
    
# 初始化 BLIP Captioner 
CAPTIONER = BLIPImageCaptioner()

@timer
def img_captioning(frames_dicts: List[Dict[str, Any]],
                   ):
    for item in frames_dicts:
        if item["is_not_blurry"] and item["is_significant"]:
            frame = item["frame"]

            # OpenCV (BGR) -> PIL (RGB)
            image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(image_rgb)

            # 丟進 BLIP 產生描述
            caption = CAPTIONER.describe(pil_image)

            # 存回 dict
            item["caption"] = caption
        else: 
            item["caption"] = "<skipped due to blur or insignificance>"
    return frames_dicts

from ..libs.ModelLoad import llm_core
import re
LLM_CORE = llm_core(supplier="google",
                    model_name="gemini-2.0-flash",
                    api_key="AIzaSyBvBotMRaGYMi4YYehNTT80d5-oknnp-68")

def clean_model_output(model_output: str):
    """
    將 Google 模型回傳的字串（含 ```json ... ``` 標記）轉成 Python dict
    """
    # 移除 ```json 與 ```
    cleaned = re.sub(r"^```json|```$", "", model_output.strip(), flags=re.MULTILINE).strip()
    
    # 嘗試轉換成 JSON
    try:
        data = json.loads(cleaned)
        return data
    except json.JSONDecodeError:
        return None
@timer
def llm_processing(frames_dicts: List[Dict[str, Any]],
                   number_of_trys: int = 3):
    #錯誤檢查
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
    # 跳過is_not_blurry與is_significant
    new_frames_dicts = []
    for item in frames_dicts:
        if item["is_not_blurry"] and item["is_significant"]:
            new_frames_dicts.append(item)

    cleaned_frames = [
        {k: v for k, v in fr.items() if k not in del_list}
        for fr in new_frames_dicts
    ]
   
    
    frames_summary = [
        {
            "index": i,
            "stamp": fr.get("stamp"),
            "caption": fr.get("caption", "")
        }
        for i, fr in enumerate(cleaned_frames)
        ]
    # 準備 prompt
    prompt = {
        "system_prompt": str(system_prompt),
        "describe": str(frames_summary)
    }

    # 如果輸出失敗，或者無法轉換成 JSON，則重試 number_of_trys 次
    output_num = number_of_trys
    while number_of_trys != 0:
        result = LLM_CORE.invoke(text = str(prompt))
        # 清理模型輸出
        result = clean_model_output(result)
        if result:
            break
        number_of_trys -= 1
    else:
        raise RuntimeError(f"模型嘗試超過規定{output_num}次錯誤，請檢查模型輸出或重試。")

    # 拼裝回原始格式
    return result, frames_summary
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
    step 9 : 將prompt送入MDL.llm_core，取得最終的描述
    step 10: 將結果整理成對應格式，呼叫API Server，讓結果存入資料庫
    (感覺缺了一個模型存活時間控管的模塊，需要研究如何讓有任務的狀態下不重複載入模型，直到所有任務做完後1分鐘再釋放模型記憶體)

    """
    try:
        # === Step 1~3: 取幀 ===
        reply = get_video_frames_fast(
            video_url=job.get("input_url", ""),
            target_fps=job.get("params", {}).get("target_fps", 3)
        )
        video_info = reply["video_info"]
        frames = reply["frames"]

        # === Step 4: 模糊度過濾 ===
        reply = analyze_blur(
            frames_dicts=frames,
            threshold=job.get("params", {}).get("blur_threshold", 20.0)
        )

        # === Step 5: 幀差過濾 ===
        reply = filter_by_frame_difference(
            frames_dicts=reply,
            threshold=job.get("params", {}).get("difference_threshold", 0.8),
            compression_proportion=job.get("params", {}).get("compression_proportion", 0.5),
            module=job.get("params", {}).get("difference_module", "SSIM")
        )

        # === Step 6~7: Caption ===
        reply = img_captioning(reply)

        # === Step 8~9: LLM ===
        llm_result, frames_summary = llm_processing(reply)

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

        return jr

    except Exception as e:
        # 報錯的程式返回格式
        return _make_failed_jobresult(
            job, video_info if "video_info" in locals() else None,
            code=getattr(e, "__class__", type(e)).__name__,
            message=str(e)
        )
    
import requests
API_SERVER_URL = "http://localhost:8000"
headers = {
    "X-API-Key": "aQV0OW43EmgRbQkOeDEJCT4QX8ZaZShQdHCQKYTyJsy8Z0n_9HIeiARXTAUkjw7Q",
    "Content-Type": "application/json"
}

@app.task(name="tasks.video_description_extraction", bind=True, acks_late=True)
def video_description_extraction(self, job: dict):
    start_time = time.time()
    reply = video_description_extraction_main(job)
    end_time = time.time()
    duration = end_time - start_time
    reply["duration"] = duration
    # 呼叫 API Server，將結果存入資料庫
    # print("URL："+job.get('input_url', ''))
    # print(reply)
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
        return {
            "job_id": job.get("job_id", "?"),
            "trace_id": job.get("trace_id"),
            "error_code": "API_CALL_FAILED",
            "error_message": str(e)
        }

