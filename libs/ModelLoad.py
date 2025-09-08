import os
import json

class llm_core:
    def __init__(self, supplier, model_name, api_key=""):
        """
        supplier => google, openai
        """
        self.supplier = supplier.lower()
        self.model_name = model_name
        self.api_key = api_key

        if self.supplier == "google":
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(model_name=model_name)

        elif self.supplier == "openai":
            import openai
            openai.api_key = api_key
            self.openai = openai  # 保留物件供後續呼叫

        else:
            raise ValueError(f"Unsupported supplier: {supplier}")

    def invoke(self, text):
        if self.supplier == "google":
            response = self.model.generate_content(text)
            return response.text

        elif self.supplier == "openai":
            response = self.openai.ChatCompletion.create(
                model=self.model_name,
                messages=[{"role": "user", "content": text}],
                max_tokens=1000
            )
            return response.choices[0].message.content

        else:
            raise ValueError("Unsupported supplier")

    def run_chat(self, user_input, chat_filename, max_turns=10):
        """
        保留對話上下文並寫入 chatdata 資料夾，以 JSON 格式儲存，檔案由使用者指定名稱。
        不保留對話於記憶體中，僅依靠讀寫 JSON。
        max_turns => 最多保留多少輪對話（1輪 = user + assistant）
        """
        os.makedirs("chatdata", exist_ok=True)
        full_path = os.path.join("chatdata", f"{chat_filename}.json")
        config_path = os.path.join("chatdata", f"{chat_filename}_config.json")

        # 若不存在，建立對應的 config 檔案
        if not os.path.exists(full_path):
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"supplier": self.supplier}, f, ensure_ascii=False, indent=2)

        # 讀取現有對話紀錄
        if os.path.exists(full_path):
            with open(full_path, "r", encoding="utf-8") as f:
                chat_history = json.load(f)
        else:
            chat_history = []

        # 新增使用者輸入與回應，並限制對話長度（只保留最近 max_turns 輪）
        chat_history.append({"role": "user", "content": user_input})

        # 保留最近 max_turns 輪（每輪 2 則訊息）
        if len(chat_history) > max_turns * 2:
            chat_history = chat_history[-max_turns * 2:]

        # 呼叫 LLM 並取得回覆
        if self.supplier == "google":
            gemini_chat = [{"role": m["role"], "parts": [m["content"]]} for m in chat_history]
            response = self.model.generate_content(gemini_chat)
            reply = response.text

        elif self.supplier == "openai":
            response = self.openai.ChatCompletion.create(
                model=self.model_name,
                messages=chat_history,
                max_tokens=1000
            )
            reply = response.choices[0].message.content
        else:
            raise ValueError("Unsupported supplier")

        # 加入助理回覆
        chat_history.append({"role": "assistant", "content": reply})

        # 儲存新的 JSON 檔案
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(chat_history, f, ensure_ascii=False, indent=2)

        return reply

    def save_output(self, text, output_path="llm_output.txt", append=False):
        mode = "a" if append else "w"
        with open(output_path, mode, encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"✅ 已將輸出寫入 {output_path}")

        
from PIL import Image
import torch
from transformers import BlipProcessor, BlipForConditionalGeneration

class BLIPImageCaptioner:
    
    def __init__(self, model_name="Salesforce/blip-image-captioning-base", device=None):
        print(f"🔁 正在載入 BLIP 模型：{model_name}")
        self.device = device if device else ("cuda" if torch.cuda.is_available() else "cpu")

        self.processor = BlipProcessor.from_pretrained(model_name)
        self.model = BlipForConditionalGeneration.from_pretrained(model_name)
        self.model.to(self.device)

        print(f"✅ BLIP 模型已載入至 {self.device}。")

    def describe(self, image_input, prompt=None):
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
    
if __name__ == '__main__':
    google_api_key = "AIzaSyBvBotMRaGYMi4YYehNTT80d5-oknnp-68"
    google_model_dict={
            1:"gemini-2.0-flash",
            2:"gemini-2.0-flash-lite",
            3:"gemma-3-27b-it"
        }
    gemini2f = llm_core("google",google_model_dict[1],google_api_key)
    print("🟢 啟動聊天模式（輸入 /exit 結束對話）")

    while True:
        try:
            user_input = input("👤 You: ").strip()
            
            if user_input == "":
                continue  # 忽略空白輸入

            if user_input.lower() == "/exit":
                print("👋 結束對話，再見！")
                break

            reply = gemini2f.run_chat(user_input=user_input, chat_filename="first")
            print("🤖 AI:", reply)

        except KeyboardInterrupt:
            print("\n⛔ 中斷輸入，結束對話")
            break

        except Exception as e:
            print("⚠️ 發生錯誤：", str(e))
def add(a,b):
    return a+b