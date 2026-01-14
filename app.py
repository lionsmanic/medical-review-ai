import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader
from Bio import Entrez
from docx import Document
from PIL import Image
import io
import time

# --- 頁面設定 ---
st.set_page_config(page_title="AI 醫學期刊審稿助手 (Gemini版)", layout="wide")

with st.sidebar:
    st.header("設定")
    gemini_api_key = st.text_input("輸入 Google Gemini API Key", type="password")
    email_address = st.text_input(
        "輸入 Email (NCBI 要求)", 
        value="doctor@example.com",
        help="PubMed 搜尋功能需要 Email 作為識別。"
    )
    st.markdown("---")
    st.success("✅ 目前使用模型：Gemini 1.5 Pro (擅長長文本與圖表分析)")

Entrez.email = email_address

# --- 初始化 Gemini ---
def get_gemini_model(api_key):
    genai.configure(api_key=api_key)
    # 使用 gemini-1.5-pro，因為它的邏輯推理和醫學理解能力最強
    return genai.GenerativeModel('gemini-1.5-pro')

# --- 工具函式 ---

def get_text_from_pdf(file_obj):
    try:
        reader = PdfReader(file_obj)
        text = ""
        for page in reader.pages:
            extract = page.extract_text()
            if extract: text += extract
        return text
    except Exception as e:
        return f"[PDF讀取錯誤: {e}]"

def get_text_from_docx(file_obj):
    try:
        doc = Document(file_obj)
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    except Exception as e:
        return f"[Word讀取錯誤: {e}]"

def analyze_image_content(image_file, model):
    """直接將圖片物件傳給 Gemini 進行分析"""
    try:
        image = Image.open(image_file)
        prompt = "這是醫學論文的附圖。請詳細描述這張圖片中的數據、趨勢、圖例與關鍵資訊，忽略無關的頁碼。"
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        return f"[圖片分析錯誤: {e}]"

# --- PubMed 搜尋 (維持不變) ---
def search_pubmed(keywords, max_results=5):
    try:
        # 搜尋 2024 年以後的文章
        search_term = f"{keywords} AND (2024/01/01[Date - Publication] : 3000[Date - Publication])"
        handle = Entrez.esearch(db="pubmed", term=search_term, retmax=max_results, sort="date")
        record = Entrez.read(handle)
        handle.close()
        
        id_list = record["IdList"]
        if not id_list:
            return "未找到相關最新文獻 (2024-Now)。"

        handle = Entrez.efetch(db="pubmed", id=id_list, rettype="abstract", retmode="text")
        abstracts = handle.read()
        handle.close()
        return abstracts
    except Exception as e:
        return f"PubMed API 錯誤: {e}"

# --- 核心流程 ---
def run_full_analysis(combined_text, api_key):
    model = get_gemini_model(api_key)
    
    # 1. 提取關鍵字
    st.status("步驟 1/3: Gemini 正在閱讀並提取關鍵字...", expanded=True)
    
    keyword_prompt = f"""
    任務：你是一位專業的醫學審稿人。請閱讀以下論文內容，提取 3-5 個核心醫學關鍵字 (MeSH terms)，用於在 PubMed 檢索最新文獻。
    輸出要求：只要關鍵字，用英文，以空格分隔。
    
    論文內容片段：
    {combined_text[:5000]}
    """
    
    # 呼叫 Gemini
    try:
        kw_response = model.generate_content(keyword_prompt)
        keywords = kw_response.text.strip()
        st.success(f"搜尋關鍵字: {keywords}")
    except Exception as e:
        st.error(f"Gemini 連線錯誤: {e}")
        return "Error"

    # 2. 搜尋 PubMed
    st.status(f"步驟 2/3: 正在搜尋 PubMed 最新文獻...", expanded=True)
    pubmed_data = search_pubmed(keywords)
    
    # 3. 綜合審稿
    st.status("步驟 3/3: Gemini 正在撰寫口語化審閱報告...", expanded=True)
    
    review_prompt = f"""
    角色設定：
    你是一位資深、臨床經驗豐富的醫師前輩。這是一份來自你同事的論文投稿。
    
    語氣要求 (非常重要)：
    1. **口語化、像真人**：就像在醫院休息室喝咖啡時的對話。
    2. **禁止 AI 腔**：不要用「首先、其次、綜上所述」這種八股文。
    3. **專業但直接**：直接講這篇有沒有臨床價值，數據可不可信。

    任務：
    1. **整體評價**：這篇論文想解決什麼問題？設計有沒有亮點？
    2. **文獻對照 (Reality Check)**：
       參考下方我提供的【PubMed 最新文獻】，這篇論文的發現是符合最新趨勢，還是已經過時？或是與最新數據矛盾？
    3. **待釐清問題 (Queries)**：
       列出 3-5 個具體且尖銳的問題，要求作者解釋（例如：樣本數太少、排除標準不清楚、統計方法有誤等）。

    ---
    【投稿論文內容】
    {combined_text[:15000]} 
    (Gemini 支援長文本，若更長可自行調整)

    【PubMed 最新文獻摘要 (2024-Now)】
    {pubmed_data}
    ---
    
    請用繁體中文輸出結果。
    """
    
    final_response = model.generate_content(review_prompt)
    return final_response.text

# --- 主程式 ---
st.title("🩺 AI 醫學期刊審稿助手 (Gemini Pro 版)")
st.markdown("使用 **Google Gemini 1.5 Pro** 模型。支援 PDF, Word, 多種圖檔整合分析。")

uploaded_files = st.file_uploader(
    "請選擇所有相關檔案 (Main text, Cover letter, Figures...)", 
    type=['pdf', 'docx', 'jpg', 'jpeg', 'png', 'tiff', 'tif'],
    accept_multiple_files=True
)

if uploaded_files and gemini_api_key:
    if st.button("開始整合分析"):
        model = get_gemini_model(gemini_api_key)
        combined_text = ""
        
        progress_bar = st.progress(0)
        total_files = len(uploaded_files)
        
        for idx, file in enumerate(uploaded_files):
            file_name = file.name
            file_type = file_name.split('.')[-1].lower()
            
            combined_text += f"\n\n--- 檔案來源：{file_name} ---\n"
            
            try:
                if file_type == 'pdf':
                    combined_text += get_text_from_pdf(file)
                elif file_type in ['docx', 'doc']:
                    combined_text += get_text_from_docx(file)
                elif file_type in ['jpg', 'jpeg', 'png', 'tiff', 'tif']:
                    # 針對圖片，我們直接呼叫 Gemini 看圖並轉成文字描述
                    # 這樣可以讓最後的總結 Prompt 知道圖片裡有什麼
                    img_desc = analyze_image_content(file, model)
                    combined_text += f"\n[圖片描述]: {img_desc}\n"
                    # 稍微暫停一下避免觸發 API 頻率限制 (雖然 Gemini 限制很寬)
                    time.sleep(1)
                
            except Exception as e:
                st.error(f"處理檔案 {file_name} 時發生錯誤: {e}")
            
            progress_bar.progress((idx + 1) / total_files)

        st.success(f"檔案讀取完畢，Gemini 開始分析...")
        
        result = run_full_analysis(combined_text, gemini_api_key)
        if result != "Error":
            st.divider()
            st.markdown("### 📝 Gemini 審稿建議")
            st.markdown(result)

elif not gemini_api_key:
    st.warning("請先輸入 Google Gemini API Key。")
