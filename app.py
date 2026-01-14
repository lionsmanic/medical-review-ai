import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader
from Bio import Entrez
from docx import Document
from PIL import Image
import io
import time

# --- 1. 頁面設定 ---
st.set_page_config(page_title="AI 醫學期刊審稿助手 (Gemini Flash版)", layout="wide")

# --- 2. 側邊欄設定 ---
with st.sidebar:
    st.header("⚙️ 設定面板")
    gemini_api_key = st.text_input("輸入 Google Gemini API Key", type="password")
    
    email_address = st.text_input(
        "輸入 Email (PubMed 規定)", 
        value="doctor@example.com",
        help="NCBI 要求使用 PubMed API 時需附上聯絡 Email，以防濫用。"
    )
    
    st.markdown("---")
    st.info("✅ 目前使用模型：Gemini 1.5 Flash (速度快、支援長文本)")
    st.markdown("---")
    st.markdown("**支援功能：**\n- 自動摘要\n- PubMed 最新文獻比對\n- 審稿問題生成\n- **最終判決建議 (Accept/Revision/Reject)**")

# 設定 Entrez email
Entrez.email = email_address

# --- 3. 初始化 Gemini 模型 ---
def get_gemini_model(api_key):
    genai.configure(api_key=api_key)
    # 使用 gemini-1.5-flash，它是目前最穩定且免費額度較寬鬆的模型
    # 適合處理長篇論文與大量圖片
    return genai.GenerativeModel('gemini-1.5-flash')

# --- 4. 檔案讀取工具函式 ---

def get_text_from_pdf(file_obj):
    """讀取 PDF 文字"""
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
    """讀取 Word 文字"""
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
        prompt = "這是醫學論文的附圖。請詳細描述這張圖片中的數據、趨勢、圖例與關鍵資訊，忽略無關的頁碼或浮水印。"
        # Gemini 支援直接輸入圖片物件
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        return f"[圖片分析錯誤: {e}]"

# --- 5. PubMed 搜尋功能 ---
def search_pubmed(keywords, max_results=5):
    """根據關鍵字搜尋 2024 年至今的文獻"""
    try:
        # 設定搜尋範圍：2024/01/01 到現在
        search_term = f"{keywords} AND (2024/01/01[Date - Publication] : 3000[Date - Publication])"
        
        # 1. 搜尋 ID
        handle = Entrez.esearch(db="pubmed", term=search_term, retmax=max_results, sort="date")
        record = Entrez.read(handle)
        handle.close()
        
        id_list = record["IdList"]
        if not id_list:
            return "未找到 2024 年後的最新相關文獻。"

        # 2. 抓取摘要
        handle = Entrez.efetch(db="pubmed", id=id_list, rettype="abstract", retmode="text")
        abstracts = handle.read()
        handle.close()
        return abstracts
    except Exception as e:
        return f"PubMed API 連線錯誤: {e}"

# --- 6. 核心 AI 分析流程 ---
def run_full_analysis(combined_text, api_key):
    model = get_gemini_model(api_key)
    
    # --- 階段 A: 提取關鍵字 ---
    st.status("步驟 1/3: AI 正在閱讀全文並提取關鍵字...", expanded=True)
    
    keyword_prompt = f"""
    任務：你是一位專業的醫學審稿人。請閱讀以下論文內容，提取 3-5 個核心醫學關鍵字 (MeSH terms)，用於在 PubMed 檢索最新文獻。
    輸出要求：只要關鍵字，用英文，以空格分隔，不要有其他廢話。
    
    論文內容片段：
    {combined_text[:5000]}
    """
    
    try:
        kw_response = model.generate_content(keyword_prompt)
        keywords = kw_response.text.strip()
        st.success(f"搜尋關鍵字: {keywords}")
    except Exception as e:
        st.error(f"Gemini 連線錯誤 (階段A): {e}")
        return None

    # --- 階段 B: 搜尋 PubMed ---
    st.status(f"步驟 2/3: 正在搜尋 PubMed 最新文獻...", expanded=True)
    pubmed_data = search_pubmed(keywords)
    
    # --- 階段 C: 綜合審稿與判決 ---
    st.status("步驟 3/3: Gemini 正在撰寫口語化審閱報告與最終建議...", expanded=True)
    
    review_prompt = f"""
    角色設定：
    你是一位資深、臨床經驗豐富的醫師前輩。這是一份來自你同事的論文投稿。
    
    語氣要求：
    1. **口語化**：像是在醫生休息室喝咖啡時的對話，輕鬆但專業。
    2. **禁止 AI 腔**：不要用「首先、其次、綜上所述」這種八股文。
    3. **直球對決**：有問題直接點出來，好的地方也不要吝嗇稱讚。

    任務內容：
    
    1. **整體評價 (General Comments)**：
       簡單講一下這篇在做什麼，臨床意義大不大。
       
    2. **文獻對照 (Reality Check)**：
       參考下方我提供的【PubMed 最新文獻】，這篇論文的發現是符合最新趨勢 (e.g. 2024-2025年的研究)，還是已經過時？或是與最新數據矛盾？
       
    3. **待釐清問題 (Queries for Authors)**：
       列出 3-5 個具體且尖銳的問題，要求作者解釋（例如：樣本數太少、排除標準不清楚、統計方法有誤、圖表數據不一致等）。
       
    4. **最終判決建議 (Recommendation)**：
       請根據學術慣例，從以下四個選項中選一個，並用粗體標示，且說明理由：
       - **Accept** (直接接受)
       - **Minor Revision** (小修)
       - **Major Revision** (大修)
       - **Reject** (拒絕)

    ---
    【投稿論文內容 (包含圖表描述)】
    {combined_text[:20000]} 

    【PubMed 最新文獻摘要 (2024-Now)】
    {pubmed_data}
    ---
    
    請用**繁體中文**輸出結果。
    """
    
    try:
        final_response = model.generate_content(review_prompt)
        return final_response.text
    except Exception as e:
        st.error(f"Gemini 連線錯誤 (階段C): {e}")
        return None

# --- 7. 主介面邏輯 ---
st.title("🩺 AI 醫學期刊審稿助手")
st.markdown("""
此工具協助醫師快速分析投稿論文。
1. 上傳 PDF/Word/圖檔 (支援多檔一次上傳)
2. 自動抓取 PubMed 最新文獻比對
3. 生成口語化評論與 **Accept/Reject 建議**
""")

uploaded_files = st.file_uploader(
    "請選擇所有相關檔案 (Main text, Cover letter, Figures...)", 
    type=['pdf', 'docx', 'jpg', 'jpeg', 'png', 'tiff', 'tif'],
    accept_multiple_files=True
)

if uploaded_files and gemini_api_key:
    if st.button("開始整合分析", type="primary"):
        model = get_gemini_model(gemini_api_key)
        combined_text = ""
        
        # 進度條
        progress_bar = st.progress(0)
        status_text = st.empty()
        total_files = len(uploaded_files)
        
        # --- 迴圈處理所有檔案 ---
        for idx, file in enumerate(uploaded_files):
            file_name = file.name
            file_type = file_name.split('.')[-1].lower()
            
            status_text.text(f"正在讀取檔案：{file_name} ...")
            combined_text += f"\n\n--- 檔案來源：{file_name} ---\n"
            
            try:
                if file_type == 'pdf':
                    combined_text += get_text_from_pdf(file)
                elif file_type in ['docx', 'doc']:
                    combined_text += get_text_from_docx(file)
                elif file_type in ['jpg', 'jpeg', 'png', 'tiff', 'tif']:
                    # 圖片處理
                    img_desc = analyze_image_content(file, model)
                    combined_text += f"\n[圖片描述]: {img_desc}\n"
                    time.sleep(1) # 避免太快
                
            except Exception as e:
                st.error(f"處理檔案 {file_name} 時發生錯誤: {e}")
            
            progress_bar.progress((idx + 1) / total_files)

        status_text.text("檔案讀取完畢，開始 AI 分析...")
        
        # --- 執行分析 ---
        result = run_full_analysis(combined_text, gemini_api_key)
        
        if result:
            st.divider()
            st.markdown("### 📝 醫師審稿報告")
            st.markdown(result)
            
            # 提供下載按鈕
            st.download_button(
                label="下載審稿報告 (.txt)",
                data=result,
                file_name="review_report.txt",
                mime="text/plain"
            )

elif not gemini_api_key:
    st.warning("👈 請先在左側輸入 Google Gemini API Key。")
