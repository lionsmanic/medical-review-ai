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
st.set_page_config(page_title="AI 醫學期刊審稿助手 (Word/PDF/圖檔)", layout="wide")

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
    st.info("✅ 模型：Gemini 1.5 Flash (快速、長文本)")
    st.markdown("### 支援格式說明")
    st.markdown("""
    - **PDF**: 標準格式
    - **Word (.docx)**: 完美支援
    - **Word (.doc)**: 舊版格式 (建議另存為 .docx 以確保讀取成功)
    - **圖片**: JPG, PNG, TIFF (自動視覺辨識)
    """)

Entrez.email = email_address

# --- 3. 初始化 Gemini ---
def get_gemini_model(api_key):
    genai.configure(api_key=api_key)
    return genai.GenerativeModel('gemini-1.5-flash')

# --- 4. 檔案讀取工具 ---

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
    """
    處理 Word 檔案 (.docx 和 .doc)
    """
    try:
        # 嘗試使用 python-docx 讀取
        # python-docx 原生只支援 .docx
        doc = Document(file_obj)
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    except Exception as e:
        # 如果讀取失敗，通常是因為使用者上傳了舊版 .doc
        if "doc" in file_ext and "docx" not in file_ext:
            return "⚠️ [格式提示]: 偵測到舊版 Word (.doc) 格式。為了確保分析精確度，建議您將檔案打開並「另存新檔」為 .docx 格式後再上傳。"
        else:
            return f"[Word 讀取錯誤: {e}]"

def analyze_image_content(image_file, model):
    try:
        image = Image.open(image_file)
        # 針對 TIFF 做相容性轉換 (Gemini 有時對原始 TIFF 支援度不一)
        if image.format == 'TIFF':
            buffered = io.BytesIO()
            image.save(buffered, format="PNG")
            image = Image.open(buffered)
            
        prompt = "這是醫學論文的附圖。請詳細描述數據、趨勢與關鍵資訊。"
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        return f"[圖片分析錯誤: {e}]"

# --- 5. PubMed 搜尋 ---
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

# --- 6. AI 分析流程 ---
def run_full_analysis(combined_text, api_key):
    model = get_gemini_model(api_key)
    
    # A. 關鍵字
    st.status("步驟 1/3: 提取關鍵字...", expanded=True)
    keyword_prompt = f"請從以下內容提取 3-5 個醫學關鍵字 (MeSH terms)，用英文空格分隔：\n{combined_text[:5000]}"
    try:
        kw_resp = model.generate_content(keyword_prompt)
        keywords = kw_resp.text.strip()
        st.success(f"關鍵字: {keywords}")
    except:
        return "Error: API 連線失敗"

    # B. PubMed
    st.status("步驟 2/3: 搜尋 PubMed...", expanded=True)
    pubmed_data = search_pubmed(keywords)
    
    # C. 審稿
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
    return model.generate_content(review_prompt).text

# --- 7. 主介面 ---
st.title("🩺 AI 醫學期刊審稿助手")
st.markdown("支援 **PDF, Word (.docx/.doc), 圖檔** 多檔整合分析。")

# 這裡加入 'doc' 到支援列表
uploaded_files = st.file_uploader(
    "請選擇檔案 (可多選)", 
    type=['pdf', 'docx', 'doc', 'jpg', 'png', 'tiff', 'tif'],
    accept_multiple_files=True
)

if uploaded_files and gemini_api_key:
    if st.button("開始整合分析", type="primary"):
        model = get_gemini_model(gemini_api_key)
        combined_text = ""
        progress = st.progress(0)
        
        for i, file in enumerate(uploaded_files):
            ext = file.name.split('.')[-1].lower()
            combined_text += f"\n\n--- File: {file.name} ---\n"
            
            try:
                if ext == 'pdf':
                    combined_text += get_text_from_pdf(file)
                elif ext in ['docx', 'doc']:
                    # 呼叫新的 Word 處理函式
                    combined_text += get_text_from_word(file, ext)
                elif ext in ['jpg', 'jpeg', 'png', 'tiff', 'tif']:
                    combined_text += f"\n[圖表]: {analyze_image_content(file, model)}\n"
                    time.sleep(1)
            except Exception as e:
                combined_text += f"[讀取錯誤: {e}]"
            
            progress.progress((i + 1) / len(uploaded_files))
            
        result = run_full_analysis(combined_text, gemini_api_key)
        if result and "Error" not in result:
            st.divider()
            st.markdown("### 📝 醫師審稿報告")
            st.markdown(result)
            st.download_button("下載報告", result, "review.txt")
        elif "Error" in result:
             st.error("分析過程發生錯誤，請檢查 API Key 或網路。")

elif not gemini_api_key:
    st.warning("請先輸入 Google Gemini API Key")
