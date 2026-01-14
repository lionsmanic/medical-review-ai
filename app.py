import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader
from Bio import Entrez
from docx import Document
from PIL import Image
import io
import time

# --- 1. 頁面設定 ---
st.set_page_config(page_title="AI 醫學期刊審稿助手 (精確引用版)", layout="wide")

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
    st.info("✅ 模型策略：優先使用 Flash，若失敗自動切換為 Pro。")
    st.warning("💡 提示：若出現 404 錯誤，請務必執行 `pip install -U google-generativeai` 更新套件。")

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
        if image.format == 'TIFF': 
            buffered = io.BytesIO()
            image.save(buffered, format="PNG")
            image = Image.open(buffered)
            
        prompt = "這是醫學論文的附圖。請詳細描述數據、趨勢、圖表標題(如 Figure 1)與關鍵資訊。"
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        return f"[圖片分析錯誤: {e}]"

# --- 4. 初始化 Gemini 模型 (含自動降級容錯機制) ---
def get_gemini_model(api_key):
    genai.configure(api_key=api_key)
    
    # 策略：優先嘗試 1.5-flash (最快)，失敗則試 1.5-pro，再失敗試 gemini-pro (舊版但穩)
    models_to_try = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']
    
    for model_name in models_to_try:
        try:
            # 測試建立模型物件
            model = genai.GenerativeModel(model_name)
            return model, model_name
        except Exception:
            continue
            
    # 如果都失敗，回傳預設 flash 讓主程式報錯顯示詳細訊息
    return genai.GenerativeModel('gemini-1.5-flash'), 'gemini-1.5-flash'

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

# --- 6. 核心 AI 分析流程 ---
def run_full_analysis(combined_text, api_key):
    # 初始化模型
    try:
        model, model_name = get_gemini_model(api_key)
        st.toast(f"正在使用模型: {model_name}") # 跳出小提示告知使用者目前用的模型
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
        return f"Error (關鍵字提取失敗 - {model_name}): {str(e)} \n建議執行 pip install -U google-generativeai 更新套件。"

    # 階段 B: PubMed
    st.status("步驟 2/3: 搜尋 PubMed...", expanded=True)
    pubmed_data = search_pubmed(keywords)
    
    # 階段 C: 審稿 (針對引用位置做 Prompt 優化)
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
        return f"Error (生成報告失敗 - {model_name}): {str(e)}"

# --- 7. 主介面 ---
st.title("🩺 AI 醫學期刊審稿助手 (Debug Mode)")
st.markdown("支援 PDF, Word, 圖檔整合分析。**自動嘗試多種模型以確保連線。**")

uploaded_files = st.file_uploader(
    "請選擇檔案 (可多選)", 
    type=['pdf', 'docx', 'doc', 'jpg', 'jpeg', 'png', 'tiff', 'tif'],
    accept_multiple_files=True
)

if uploaded_files and gemini_api_key:
    if st.button("開始整合分析", type="primary"):
        # 這裡不需重新初始化，直接傳遞 Key 給函式處理
        combined_text = ""
        progress = st.progress(0)
        
        # 預先載入模型以供圖片分析使用
        img_model, _ = get_gemini_model(gemini_api_key)

        for i, file in enumerate(uploaded_files):
            ext = file.name.split('.')[-1].lower()
            combined_text += f"\n\n--- File: {file.name} ---\n"
            
            try:
                if ext == 'pdf':
                    combined_text += get_text_from_pdf(file)
                elif ext in ['docx', 'doc']:
                    combined_text += get_text_from_word(file, ext)
                elif ext in ['jpg', 'jpeg', 'png', 'tiff', 'tif']:
                    combined_text += f"\n[圖表內容 - {file.name}]: {analyze_image_content(file, img_model)}\n"
                    time.sleep(1)
            except Exception as e:
                st.warning(f"讀取檔案 {file.name} 時發生小錯誤 (已略過): {e}")
            
            progress.progress((i + 1) / len(uploaded_files))
            
        result = run_full_analysis(combined_text, gemini_api_key)
        
        if result and result.startswith("Error"):
            st.divider()
            st.error("❌ 分析失敗，錯誤訊息如下：")
            st.code(result, language="text")
            st.info("💡 如果看到 '404' 或 'not found'，請務必執行 `pip install -U google-generativeai`")
        elif result:
            st.divider()
            st.markdown("### 📝 醫師審稿報告")
            st.markdown(result)
            st.download_button("下載報告", result, "review.txt")

elif not gemini_api_key:
    st.warning("請先輸入 Google Gemini API Key")
