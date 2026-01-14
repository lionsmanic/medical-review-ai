import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader
from Bio import Entrez
from docx import Document
from PIL import Image
import io
import time

# --- 1. 頁面設定 ---
st.set_page_config(page_title="AI 醫學期刊審稿助手 (自動偵測版)", layout="wide")

# --- 2. 側邊欄設定 ---
with st.sidebar:
    st.header("⚙️ 設定面板")
    gemini_api_key = st.text_input("輸入 Google Gemini API Key", type="password")
    email_address = st.text_input("輸入 Email (PubMed 規定)", value="doctor@example.com")
    st.markdown("---")
    st.info("✅ 模式：自動偵測可用模型")

Entrez.email = email_address

# --- 3. 檔案讀取工具 ---
def get_text_from_pdf(file_obj):
    try:
        reader = PdfReader(file_obj)
        text = ""
        for page in reader.pages:
            extract = page.extract_text()
            if extract: text += extract
        return text
    except Exception as e:
        return f"[PDF 讀取錯誤: {e}]"

def get_text_from_word(file_obj, file_ext):
    try:
        doc = Document(file_obj)
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    except Exception as e:
        if "doc" in file_ext and "docx" not in file_ext:
            return "⚠️ [格式提示]: 偵測到舊版 Word (.doc)。建議另存為 .docx。"
        else:
            return f"[Word 讀取錯誤: {e}]"

# --- 4. 動態模型偵測 (關鍵修復) ---
def find_best_model(api_key):
    """
    直接詢問 API 有哪些模型可用，不再瞎猜名稱。
    """
    genai.configure(api_key=api_key)
    try:
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        if not available_models:
            return None, "沒有找到任何支援生成內容的模型 (權限或區域問題)。"
            
        # 優先順序策略：找 flash -> 找 pro -> 隨便選一個
        # 模型名稱通常長這樣: models/gemini-1.5-flash
        best_model = None
        
        # 1. 優先找 Flash (最快)
        for m in available_models:
            if 'flash' in m:
                best_model = m
                break
        
        # 2. 其次找 1.5 Pro
        if not best_model:
            for m in available_models:
                if '1.5-pro' in m:
                    best_model = m
                    break
        
        # 3. 再不行找 gemini-pro
        if not best_model:
            for m in available_models:
                if 'gemini-pro' in m:
                    best_model = m
                    break
                    
        # 4. 真的都沒有，就拿第一個
        if not best_model:
            best_model = available_models[0]
            
        return best_model, None

    except Exception as e:
        return None, str(e)

# --- 5. 圖片分析 ---
def analyze_image_content(image_file, api_key):
    # 先取得可用模型
    model_name, error = find_best_model(api_key)
    if error: return f"[圖片分析失敗: {error}]"
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    try:
        image = Image.open(image_file)
        if image.format == 'TIFF':
            buffered = io.BytesIO()
            image.save(buffered, format="PNG")
            image = Image.open(buffered)
        
        prompt = "這是醫學論文的附圖。請詳細描述數據、趨勢、圖表標題(如 Figure 1)與關鍵資訊。"
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        return f"[圖片分析錯誤: {e}]"

# --- 6. PubMed 搜尋 ---
def search_pubmed(keywords, max_results=5):
    try:
        search_term = f"{keywords} AND (2024/01/01[Date - Publication] : 3000[Date - Publication])"
        handle = Entrez.esearch(db="pubmed", term=search_term, retmax=max_results, sort="date")
        record = Entrez.read(handle)
        handle.close()
        
        id_list = record["IdList"]
        if not id_list:
            return "未找到 2024 年後的最新相關文獻。"

        handle = Entrez.efetch(db="pubmed", id=id_list, rettype="abstract", retmode="text")
        abstracts = handle.read()
        handle.close()
        return abstracts
    except Exception as e:
        return f"PubMed API 連線錯誤: {e}"

# --- 7. 核心 AI 流程 ---
def run_full_analysis(combined_text, api_key):
    
    # 步驟 0: 動態尋找模型
    model_name, error = find_best_model(api_key)
    if error:
        return f"Error (模型偵測失敗): {error} \n請檢查 API Key 是否正確，或嘗試 `pip install -U google-generativeai`"
    
    st.toast(f"已自動連線至模型: {model_name}")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    # 步驟 A: 提取關鍵字
    st.status(f"步驟 1/3: 使用 {model_name} 提取關鍵字...", expanded=True)
    keyword_prompt = f"請從以下內容提取 3-5 個醫學關鍵字 (MeSH terms)，用英文空格分隔：\n{combined_text[:5000]}"
    
    try:
        kw_resp = model.generate_content(keyword_prompt)
        keywords = kw_resp.text.strip()
        st.success(f"關鍵字: {keywords}")
    except Exception as e:
        return f"Error (關鍵字階段 - {model_name}): {str(e)}"

    # 步驟 B: PubMed
    st.status("步驟 2/3: 搜尋 PubMed...", expanded=True)
    pubmed_data = search_pubmed(keywords)
    
    # 步驟 C: 審稿 (含引用要求)
    st.status("步驟 3/3: 生成精確引用的審稿報告...", expanded=True)
    
    review_prompt = f"""
    角色：資深且嚴謹的醫學期刊審稿人。
    任務：審閱投稿論文，提供具體、可操作的建議。

    【重要規則：引用位置】
    在提出批評或建議時，**必須明確指出位置**，增加說服力：
    1. **圖表**：請明確寫出 "In Table 1...", "In Figure 2B..."。
    2. **內文**：由於無法取得準確行號，**請直接引用該段落的起始句或關鍵字句** (例如: "In the Methods section, regarding 'patients were excluded if...', the criteria is ambiguous.")。
    
    審稿報告結構：
    1. **整體評價 (Overview)**：簡述臨床價值。
    2. **文獻對照 (Reality Check)**：對比下方提供的 2024-2025 最新文獻，指出本研究是否過時或矛盾。
    3. **具體待釐清問題 (Specific Queries)**：
       - 請列出 3-5 點。
       - 每點都必須包含 **[Location]** (指出是哪個 Table/Figure 或引用原文)。
       - 語氣要尖銳但專業。
    4. **最終判決 (Recommendation)**：從 [Accept, Minor Revision, Major Revision, Reject] 擇一並粗體標示，附上理由。

    ---
    【投稿內容】
    {combined_text[:25000]}

    【最新文獻】
    {pubmed_data}
    ---
    請用繁體中文回答。
    """
    
    try:
        final_resp = model.generate_content(review_prompt)
        return final_resp.text
    except Exception as e:
        return f"Error (生成報告階段 - {model_name}): {str(e)}"

# --- 8. 主介面 ---
st.title("🩺 AI 醫學期刊審稿助手 (自動偵測版)")
st.markdown("支援 PDF, Word, 圖檔。**自動尋找您帳號可用的最佳模型。**")

uploaded_files = st.file_uploader(
    "請選擇檔案 (可多選)", 
    type=['pdf', 'docx', 'doc', 'jpg', 'jpeg', 'png', 'tiff', 'tif'],
    accept_multiple_files=True
)

if uploaded_files and gemini_api_key:
    if st.button("開始整合分析", type="primary"):
        combined_text = ""
        progress = st.progress(0)
        
        for i, file in enumerate(uploaded_files):
            ext = file.name.split('.')[-1].lower()
            combined_text += f"\n\n--- File: {file.name} ---\n"
            
            try:
                if ext == 'pdf':
                    combined_text += get_text_from_pdf(file)
                elif ext in ['docx', 'doc']:
                    combined_text += get_text_from_word(file, ext)
                elif ext in ['jpg', 'jpeg', 'png', 'tiff', 'tif']:
                    # 圖片分析
                    combined_text += f"\n[圖表內容 - {file.name}]: {analyze_image_content(file, gemini_api_key)}\n"
                    time.sleep(1)
            except Exception as e:
                st.warning(f"讀取檔案 {file.name} 時發生小錯誤: {e}")
            
            progress.progress((i + 1) / len(uploaded_files))
            
        result = run_full_analysis(combined_text, gemini_api_key)
        
        if result and result.startswith("Error"):
            st.divider()
            st.error("❌ 分析失敗，詳細錯誤如下：")
            st.code(result, language="text")
            
            # 這裡顯示一個診斷資訊，幫助使用者除錯
            if "模型偵測失敗" in result:
                st.info("💡 診斷建議：\n1. 請確認您的 API Key 沒有多複製空格。\n2. 請確認您已執行 `pip install -U google-generativeai`。")
                
        elif result:
            st.divider()
            st.markdown("### 📝 醫師審稿報告")
            st.markdown(result)
            st.download_button("下載報告", result, "review.txt")

elif not gemini_api_key:
    st.warning("請先輸入 Google Gemini API Key")
