import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader
from Bio import Entrez
from docx import Document
from PIL import Image
import io
import time
import os

# --- 1. 頁面設定 ---
st.set_page_config(page_title="AI 醫學期刊審稿助手 (Debug版)", layout="wide")

# --- 2. 側邊欄設定 ---
with st.sidebar:
    st.header("⚙️ 設定面板")
    gemini_api_key = st.text_input("輸入 Google Gemini API Key", type="password")
    
    email_address = st.text_input(
        "輸入 Email (PubMed 規定)", 
        value="doctor@example.com",
        help="NCBI 要求使用 PubMed API 時需附上聯絡 Email。"
    )
    
    st.markdown("---")
    st.info("✅ 模型：Gemini 1.5 Flash")
    st.warning("🛠 此版本包含詳細除錯模式，若發生錯誤會顯示具體原因。")

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
    """處理 Word 檔案 (.docx 和 .doc)"""
    try:
        doc = Document(file_obj)
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    except Exception as e:
        if "doc" in file_ext and "docx" not in file_ext:
            return "⚠️ [格式提示]: 偵測到舊版 Word (.doc)。建議另存為 .docx 格式以確保讀取成功。"
        else:
            return f"[Word 讀取錯誤: {e}]"

def analyze_image_content(image_file, model):
    try:
        image = Image.open(image_file)
        if image.format == 'TIFF': # TIFF 相容性處理
            buffered = io.BytesIO()
            image.save(buffered, format="PNG")
            image = Image.open(buffered)
            
        prompt = "這是醫學論文的附圖。請詳細描述數據、趨勢與關鍵資訊。"
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        return f"[圖片分析錯誤: {e}]"

# --- 4. PubMed 搜尋 ---
def search_pubmed(keywords, max_results=5):
    try:
        # 搜尋 2024 年至今
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

# --- 5. 核心 AI 分析流程 (含詳細除錯) ---
def run_full_analysis(combined_text, api_key):
    # 設定階段
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        return f"Error (API 設定失敗): {str(e)}"
    
    # 階段 A: 提取關鍵字
    st.status("步驟 1/3: 提取關鍵字...", expanded=True)
    keyword_prompt = f"請從以下內容提取 3-5 個醫學關鍵字 (MeSH terms)，用英文空格分隔：\n{combined_text[:5000]}"
    
    try:
        kw_resp = model.generate_content(keyword_prompt)
        keywords = kw_resp.text.strip()
        st.success(f"關鍵字: {keywords}")
    except Exception as e:
        # 這裡會捕捉如 403, 404 等具體錯誤
        return f"Error (Gemini 關鍵字提取階段失敗): {str(e)}"

    # 階段 B: PubMed
    st.status("步驟 2/3: 搜尋 PubMed...", expanded=True)
    pubmed_data = search_pubmed(keywords)
    
    # 階段 C: 審稿
    st.status("步驟 3/3: 生成審稿報告...", expanded=True)
    review_prompt = f"""
    角色：資深臨床醫師。
    任務：審閱同事的投稿論文，語氣口語化、專業且直接。
    
    內容包含：
    1. **整體評價**：簡述研究目的與價值。
    2. **文獻對照 (Reality Check)**：對比下方提供的 2024-2025 最新文獻，指出本研究是否過時或有衝突。
    3. **待釐清問題 (Queries)**：3-5 個尖銳問題 (如樣本、統計、排除標準)。
    4. **最終判決 (Recommendation)**：請從 [Accept, Minor Revision, Major Revision, Reject] 擇一並粗體標示，附上理由。

    ---
    【投稿內容】
    {combined_text[:20000]}

    【最新文獻】
    {pubmed_data}
    ---
    請用繁體中文回答。
    """
    
    try:
        final_resp = model.generate_content(review_prompt)
        return final_resp.text
    except Exception as e:
        return f"Error (Gemini 生成報告階段失敗): {str(e)}"

# --- 6. 主介面 ---
st.title("🩺 AI 醫學期刊審稿助手 (Debug Mode)")
st.markdown("支援 PDF, Word, 圖檔整合分析。**若發生錯誤將顯示詳細代碼。**")

uploaded_files = st.file_uploader(
    "請選擇檔案 (可多選)", 
    type=['pdf', 'docx', 'doc', 'jpg', 'jpeg', 'png', 'tiff', 'tif'],
    accept_multiple_files=True
)

if uploaded_files and gemini_api_key:
    if st.button("開始整合分析", type="primary"):
        # 重新初始化模型 (確保在按鈕按下時才建立連線)
        model = genai.GenerativeModel('gemini-1.5-flash')
        genai.configure(api_key=gemini_api_key)
        
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
                    combined_text += f"\n[圖表]: {analyze_image_content(file, model)}\n"
                    time.sleep(1) # 避免圖片連發太快
            except Exception as e:
                st.warning(f"讀取檔案 {file.name} 時發生小錯誤 (已略過): {e}")
            
            progress.progress((i + 1) / len(uploaded_files))
            
        # 執行核心分析
        result = run_full_analysis(combined_text, gemini_api_key)
        
        # 這裡會判斷回傳的是不是錯誤訊息
        if result and result.startswith("Error"):
            st.divider()
            st.error("❌ 分析失敗，請將以下錯誤訊息提供給工程師 (或貼給 AI 判斷)：")
            st.code(result, language="text") # 顯示紅色的錯誤區塊
        elif result:
            st.divider()
            st.markdown("### 📝 醫師審稿報告")
            st.markdown(result)
            st.download_button("下載報告", result, "review.txt")

elif not gemini_api_key:
    st.warning("請先輸入 Google Gemini API Key")
