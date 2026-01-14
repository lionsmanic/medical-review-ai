import google.generativeai as genai
import os

# --- 設定您的 API Key ---
api_key = "AIzaSyA6ZTusMROFzgVS2g7O7FzdqpcnNACd0c4" 

print(f"正在測試 API Key: {api_key[:5]}... (隱藏後碼)")

try:
    genai.configure(api_key=api_key)
    
    # 1. 測試列出模型 (確認權限)
    print("\n[測試 1] 正在列出可用模型...")
    models = [m.name for m in genai.list_models()]
    if not models:
        print("❌ 錯誤：無法取得模型清單。請檢查 API Key 是否正確。")
    else:
        print(f"✅ 成功連線！您的帳號可用模型包含：")
        for m in models:
            if 'flash' in m or 'pro' in m:
                print(f"   - {m}")

    # 2. 測試生成文字 (確認功能)
    print("\n[測試 2] 正在測試 gemini-1.5-flash 模型生成文字...")
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content("Hello, simply reply 'OK'.")
    print(f"✅ 模型回應：{response.text.strip()}")
    print("\n🎉 測試完全成功！您的 API Key 和網路都沒有問題。")

except Exception as e:
    print("\n❌❌❌ 發生錯誤 ❌❌❌")
    print(f"錯誤類型: {type(e).__name__}")
    print(f"詳細訊息: {e}")
    print("------------------------------------------------")
    if "404" in str(e):
        print("💡 推測原因：找不到模型。請確認您已執行 `pip install -U google-generativeai` 更新套件。")
    elif "400" in str(e) or "API key not valid" in str(e):
        print("💡 推測原因：API Key 無效。請重新複製，確保沒有複製到多餘的空白鍵。")
    elif "403" in str(e):
        print("💡 推測原因：權限不足或區域限制。")
