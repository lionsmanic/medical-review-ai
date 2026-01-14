import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader
from Bio import Entrez
from docx import Document
from PIL import Image
import io
import time

# --- 1. 頁面設定 ---
st.set_page_config(page_title="AI 醫學期刊審稿助手 (雙語+精確定位)", layout="wide")

# --- 2. 側邊欄設定 ---
with st.sidebar:
    st.header("⚙️ 設定面板")
    gemini_api_key = st.text_input("輸入 Google Gemini API Key (新)", type="password")
    email_address = st.text_input("輸入 Email (PubMed 規定)", value="doctor@example.com")
    st.markdown("---")
    st.info("✅ 模式：自動偵測可用模型")
    st.markdown("### 本次更新功能")
    st.markdown("""
    1. **雙語報告**：中文分析 + 簡潔口語英文 (方便直接回覆)。
    2. **精確定位**：標示章節 (Introduction...) 與行號或引用句。
    """)

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

# --- 4. 動態模型偵測 ---
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
            
        # 優先順序策略
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

# --- 7. 核心 AI 流程 (Prompt 更新) ---
def run_full_analysis(combined_text, api_key):
    
    # 步驟 0: 動態尋找模型
    model_name, error = find_best_model(api_key)
    if error:
        return f"Error (模型偵測失敗): {error}"
    
    st.toast(f"已連線模型: {model_name}")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    # 步驟 A: 提取關鍵字
    st.status(f"步驟 1/3: 使用 AI 提取關鍵字...", expanded=True)
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
    
    # 步驟 C: 雙語審稿 (Prompt 核心修改)
    st.status("步驟 3/3: 生成雙語且精確引用的審稿報告...", expanded=True)
    
    review_prompt = f"""
    You are a senior Medical Journal Reviewer.
    Your task is to review the provided manuscript based on the latest literature (provided below).

    【INPUT DATA】
    1. Manuscript Content: 
    {combined_text[:30000]}
    
    2. Latest PubMed Literature (2024-Present):
    {pubmed_data}

    【REQUIREMENTS】
    Please generate the output in **TWO PARTS**.

    ---
    ### PART 1: Traditional Chinese (繁體中文) - For the User
    - **Tone**: Professional yet conversational (Senior colleague to colleague). No AI-like stiffness.
    - **Structure**:
      1. **整體評價 (Overview)**: Brief summary of value.
      2. **文獻對照 (Reality Check)**: Compare with the PubMed data provided. Is it outdated?
      3. **待釐清問題 (Specific Queries)**: 3-5 sharp points.
         - **CRITICAL**: You MUST cite the location for every query.
         - Format: **[Section Name, Line Number OR Quote]** (e.g., [Methods, Line 125] or [Introduction, "The patient was..."]).
      4. **最終判決 (Recommendation)**: **Accept / Minor Revision / Major Revision / Reject** (Bold this).

    ---
    ### PART 2: English Report - For the Authors/Editor
    - **Tone**: Conversational, Concise, Direct, Polished (Native speaker tone).
    - **Style**: Avoid wordy academic jargon where simple language works. Get to the point.
    - **Structure**:
      1. **General Comments**: Very brief (2-3 sentences).
      2. **Specific Comments & Queries**:
         - Numbered list.
         - **CRITICAL**: Use the same location citation format: **[Section, Line X / Quote]**.
         - Example: "In the **[Methods]** section (Line 45), you mentioned X, but Table 1 shows Y. Please clarify."
    
    """
    
    try:
        final_resp = model.generate_content(review_prompt)
        return final_resp.text
    except Exception as e:
        return f"Error (生成報告階段 - {model_name}): {str(e)}"

# --- 8. 主介面 ---
st.title("🩺 AI 醫學期刊審稿助手 (雙語版)")
st.markdown("支援 PDF, Word, 圖檔。**含中英雙語報告與精確行號/引用定位。**")

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
                    combined_text += f"\n[圖表內容 - {file.name}]: {analyze_image_content(file, gemini_api_key)}\n"
                    time.sleep(1)
            except Exception as e:
                st.warning(f"讀取檔案 {file.name} 時發生小錯誤: {e}")
            
            progress.progress((i + 1) / len(uploaded_files))
            
        result = run_full_analysis(combined_text, gemini_api_key)
        
        if result and result.startswith("Error"):
            st.divider()
            st.error("❌ 分析失敗，錯誤如下：")
            st.code(result, language="text")
            
            if "leaked" in result:
                st.error("🚨 您的 API Key 已被 Google 停用 (Leaked)。請建立一把新的 Key 並重新輸入。")
                
        elif result:
            st.divider()
            st.markdown(result) # 直接顯示包含中英文的完整報告
            st.download_button("下載完整報告 (.txt)", result, "review_report.txt")

elif not gemini_api_key:
    st.warning("請先輸入 Google Gemini API Key")
