import cv2
from tqdm import tqdm
import pandas as pd
import shutil
import numpy as np
import os
class fet_key_frame:
    def __init__(self,
                 source_dir = "data\\source",
                 output_dir = "data\\Slicing_data",
                 output_blur_folder = "data\\analyze_blur",
                 action_if_filtered='move',
                 output_difference_folder='data\\ashcan'):
        """
        :param source_dir: 來源資料夾路徑，內含所有要處理的影片
        :param output_dir: 輸出資料夾，若不存在會自動建立
        :param frames_per_second: 每秒要抽取的幀數
        :param output_blur_folder: 模糊圖片的輸出資料夾
        :param action_if_filtered: 'delete' 或 'move'
        """
        self.source_dir = source_dir    # 來源資料夾（裡面包含所有影片）
        self.output_dir = output_dir    # 輸出資料夾（會自動建立對應子資料夾）
        self.output_blur_folder = output_blur_folder
        self.action_if_filtered = action_if_filtered
        self.output_difference_folder = output_difference_folder
        
    def extract_frames_from_directory(
        self,
        source_dir,              # 來源資料夾（裡面包含所有影片）
        frames_per_second,       # 每秒抽幾幀
        output_dir               # 輸出資料夾（會自動建立對應子資料夾）
    ):
        """
        從指定資料夾中的每一部影片進行抽幀，並將切片輸出至對應子資料夾。

        :param source_dir: 來源資料夾路徑，內含所有要處理的影片
        :param frames_per_second: 每秒要抽取的幀數
        :param output_dir: 輸出資料夾，若不存在會自動建立
        """

        if not os.path.exists(source_dir):
            print(f"來源資料夾 {source_dir} 不存在，請確認路徑。")
            return

        # 如果輸出資料夾不存在，就自動建立
        os.makedirs(output_dir, exist_ok=True)

        # 可自行調整的影片副檔名
        video_extensions = (".mp4", ".avi", ".mov", ".mkv")
        video_files = [f for f in os.listdir(source_dir) if f.lower().endswith(video_extensions)]

        if not video_files:
            print(f"在 {source_dir} 中沒有找到任何影片檔。")
            return

        # 前置計算：統計「理論上會抽到的總幀數」，以便設定 tqdm 的 total
        total_extract_frames = 0
        video_info_list = []  # 儲存每支影片的資訊，避免重複打開影片

        for video_name in video_files:
            video_path = os.path.join(source_dir, video_name)
            cap = cv2.VideoCapture(video_path)

            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            # 避免壞檔或 FPS = 0
            if fps <= 0 or total_frames <= 0:
                print(f"【警告】影片 {video_name} 無法正確讀取 (fps={fps}, total_frames={total_frames})，略過。")
                cap.release()
                continue

            frame_interval = int(fps / frames_per_second)
            if frame_interval < 1:
                print(f"【警告】每秒抽取幀數 {frames_per_second} 過高，超過影片 FPS({fps})，不進行切片。")
                cap.release()
                continue

            # 計算本部影片理論可抽取的張數 (忽略最後不足 interval 的幀)
            possible_extracts = total_frames // frame_interval

            # 儲存此影片資訊到列表
            video_info_list.append({
                "video_name": video_name,
                "video_path": video_path,
                "fps": fps,
                "total_frames": total_frames,
                "frame_interval": frame_interval,
                "possible_extracts": possible_extracts
            })

            total_extract_frames += possible_extracts
            cap.release()

        # 若全部影片都不符合條件，直接結束
        if not video_info_list or total_extract_frames == 0:
            print("沒有可抽幀的影片，請確認參數或影片品質。")
            return

        # 使用 tqdm 進度條：總量為所有可抽取的幀數
        with tqdm(total=total_extract_frames, desc="整體進度") as pbar:
            # 實際開始處理影片
            for info in video_info_list:
                video_name = info["video_name"]
                video_path = info["video_path"]
                total_frames = info["total_frames"]
                frame_interval = info["frame_interval"]

                # 建立對應子資料夾（以影片檔名去除副檔名為資料夾名稱）
                video_basename = os.path.splitext(video_name)[0]
                output_subfolder = os.path.join(output_dir, video_basename)
                os.makedirs(output_subfolder, exist_ok=True)

                cap = cv2.VideoCapture(video_path)
                frame_count = 0  # 記錄第幾幀
                output_count = 0  # 記錄已輸出幾張

                while cap.isOpened():
                    success, frame = cap.read()
                    if not success:
                        break

                    # 按照幀間隔抽幀
                    if frame_count % frame_interval == 0:
                        output_filename = f"{video_basename}_frame_{output_count:06d}.jpg"
                        output_file_path = os.path.join(output_subfolder, output_filename)
                        cv2.imwrite(output_file_path, frame)
                        output_count += 1

                        # 每存一張就更新一次進度條
                        pbar.update(1)

                    frame_count += 1

                cap.release()

                # 這邊可以簡單印一下每支影片處理結果
                #print(f"影片 {video_name} 完成，共輸出 {output_count} 張。")

        print("\n全部影片皆已處理完畢！")

    def analyze_blur_in_folders(
            self,
            input_folder,
            output_blur_folder,
            threshold=20,
            save_csv=False,
            csv_path='blur_analysis.csv'):
        # 確保輸出資料夾存在
        os.makedirs(output_blur_folder, exist_ok=True)
        
        # 存儲分析結果
        results = []
        
        # 遍歷輸入資料夾內的所有子資料夾
        for subfolder in os.listdir(input_folder):
            subfolder_path = os.path.join(input_folder, subfolder)
            
            if not os.path.isdir(subfolder_path):
                continue  # 跳過非資料夾項目
            
            file_list = [f for f in os.listdir(subfolder_path) if f.lower().endswith(('png', 'jpg', 'jpeg', 'bmp', 'tiff'))]
            total_files = len(file_list)
            
            with tqdm(total=total_files, desc=f"Processing {subfolder}", unit="image") as pbar:
                for filename in file_list:
                    img_path = os.path.join(subfolder_path, filename)
                    
                    # 讀取圖片
                    img = cv2.imread(img_path)
                    if img is None:
                        pbar.update(1)
                        continue  # 無法讀取的圖片跳過
                    
                    # 轉換為灰度圖並計算 Laplacian 變異數
                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
                    variance = np.var(laplacian)
                    
                    # 判斷是否為模糊圖片
                    is_blurry = variance < threshold
                    results.append({'filename': filename, 'folder': subfolder, 'variance': variance, 'blurry': is_blurry})
                    
                    # 移動模糊圖片到目標資料夾，不模糊則保持原地
                    if is_blurry:
                        shutil.move(img_path, os.path.join(output_blur_folder, filename))
                    
                    pbar.update(1)
        
        # 如果需要儲存 CSV
        if save_csv:
            df = pd.DataFrame(results)
            df.to_csv(csv_path, index=False, encoding='utf-8')
        
        print("\n分析完成，所有模糊圖片已移動至目標資料夾！")

    def filter_by_frame_difference(
    self,
    input_folder,
    threshold_method='median',
    action_if_filtered='delete',             # 'delete' 或 'move'
    output_difference_folder=None            # 若選擇 move，要指定這個資料夾
    ):
        """
        根據幀差異篩選圖片，只保留第一張與變化量大的圖片。

        :param input_folder: 輸入資料夾路徑（每部影片的子資料夾）
        :param threshold_method: 使用中位數或指定數值作為篩選門檻
        :param action_if_filtered: 不保留的圖片要 'delete' 或 'move'
        :param output_difference_folder: 若為 move，則搬移到此資料夾（會自動建立子資料夾）
        """
        if action_if_filtered not in ['delete', 'move']:
            raise ValueError("action_if_filtered 必須是 'delete' 或 'move'")

        if action_if_filtered == 'move' and output_difference_folder is None:
            raise ValueError("若 action_if_filtered 為 'move'，必須提供 output_difference_folder")

        if output_difference_folder:
            os.makedirs(output_difference_folder, exist_ok=True)

        for subfolder in os.listdir(input_folder):
            subfolder_path = os.path.join(input_folder, subfolder)

            if not os.path.isdir(subfolder_path):
                continue

            images = sorted([
                f for f in os.listdir(subfolder_path)
                if f.lower().endswith(('jpg', 'jpeg', 'png', 'bmp'))
            ])

            if len(images) < 2:
                print(f"子資料夾 {subfolder} 圖片太少，略過差異分析。")
                continue

            keep_images = [images[0]]  # 第一張保留
            diffs = []

            # 預先讀取第一張灰階圖
            prev_img_path = os.path.join(subfolder_path, images[0])
            prev_gray = cv2.cvtColor(cv2.imread(prev_img_path), cv2.COLOR_BGR2GRAY)

            for i in range(1, len(images)):
                curr_img_path = os.path.join(subfolder_path, images[i])
                curr_img = cv2.imread(curr_img_path)
                if curr_img is None:
                    continue
                curr_gray = cv2.cvtColor(curr_img, cv2.COLOR_BGR2GRAY)

                diff = cv2.absdiff(curr_gray, prev_gray)
                mean_diff = np.mean(diff)
                diffs.append((images[i], mean_diff))
                prev_gray = curr_gray

            # 計算中位數門檻
            all_diff_vals = [d[1] for d in diffs]
            if threshold_method == 'median':
                threshold = np.median(all_diff_vals)
            elif isinstance(threshold_method, (int, float)):
                threshold = float(threshold_method)
            else:
                raise ValueError("threshold_method 必須是 'median' 或 float 數值")

            # 根據門檻保留圖片
            for filename, diff_val in diffs:
                if diff_val >= threshold:
                    keep_images.append(filename)

            # 執行刪除或搬移
            for filename in images:
                if filename not in keep_images:
                    src_path = os.path.join(subfolder_path, filename)

                    if action_if_filtered == 'delete':
                        os.remove(src_path)
                    elif action_if_filtered == 'move':
                        subfolder_output = os.path.join(output_difference_folder, subfolder)
                        os.makedirs(subfolder_output, exist_ok=True)
                        dst_path = os.path.join(subfolder_output, filename)
                        shutil.move(src_path, dst_path)

            print(f"子資料夾 {subfolder} 處理完成：保留 {len(keep_images)} 張，原始共 {len(images)} 張。")

    def get_key_frame(self, frames_per_second = 3,blur_threshold = 20,diff_threshold_method='median'):
        try:

            self.extract_frames_from_directory(
            source_dir = self.source_dir,     
            frames_per_second = frames_per_second,  
            output_dir = self.output_dir
            )
            self.analyze_blur_in_folders(
            input_folder = self.output_dir,
            output_blur_folder = self.output_blur_folder,
            threshold = blur_threshold
            )
            self.filter_by_frame_difference(
            input_folder=self.output_dir,
            threshold_method=diff_threshold_method,
            action_if_filtered=self.action_if_filtered,
            output_difference_folder=self.output_difference_folder 
            )
            print("key frame 轉換成功")
            subfolders = [
                os.path.join(self.output_dir,name) for name in os.listdir(self.output_dir)
                if os.path.isdir(os.path.join(self.output_dir, name))
            ]
            return subfolders
        except Exception as e:
            print(f"錯誤: {e}")

def get_image_filenames(folder_path):
    # 支援的圖片格式
    valid_extensions = (".jpg", ".jpeg", ".png", ".bmp")

    # 建立一個空 list 存檔名
    image_filenames = []

    for filename in os.listdir(folder_path):
        if filename.lower().endswith(valid_extensions):
            image_filenames.append(filename)

    return image_filenames
