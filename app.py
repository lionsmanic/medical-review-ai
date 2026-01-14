import streamlit as st
import openai
from pypdf import PdfReader
from Bio import Entrez
from docx import Document
from PIL import Image
import io
import base64

# --- 頁面設定 ---
st.set_page_config(page_title="全能醫學期刊審稿助手", layout="wide")

with st.sidebar:
    st.header("設定")
    openai_api_key = st.text_input("輸入 OpenAI API Key", type="password")
    # 這裡解釋了為什麼需要 Email
    email_address = st.text_input(
        "輸入 Email (NCBI 要求)", 
        value="doctor@example.com",
        help="NCBI 要求使用 API 時需附上聯絡 Email，若發生連線頻率過高時他們可能會通知您。"
    )
    st.markdown("---")
    st.info("💡 提示：您可以一次選取多個檔案 (PDF, Word, 圖檔) 上傳，AI 會自動合併閱讀。")

Entrez.email = email_address

# --- 工具函式 (讀取各類檔案) ---

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

def get_text_from_image(file_obj, api_key):
    """利用 GPT-4o Vision 讀取圖表內容"""
    try:
        # 轉為 Image 物件
        image = Image.open(file_obj)
        
        # 統一轉為 PNG 用於 API 傳輸
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')

        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "這是醫學論文的圖表或附圖。請詳細描述圖片中的數據、標題與文字內容。"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                    ]
                }
            ],
            max_tokens=1000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"[圖片辨識錯誤: {e}]"

# --- 核心 AI 分析函式 ---

def search_pubmed(keywords, max_results=5):
    try:
        # 搜尋 2024 年至今的文章
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

def analyze_and_generate_review(full_text, api_key):
    client = openai.OpenAI(api_key=api_key)
    
    # 1. 抓關鍵字
    st.status("步驟 1/3: 綜合分析所有檔案內容，提取主題...", expanded=True)
    prompt_extract = f"""
    以下是投稿論文的完整內容（包含 Cover letter, 正文, 圖表說明）。
    請提取 3-5 個核心醫學關鍵字 (MeSH terms) 用於搜尋最新文獻。
    
    內容片段: 
    {full_text[:3000]}
    """
    kw_resp = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": prompt_extract}]
    )
    keywords = kw_resp.choices[0].message.content
    st.success(f"搜尋關鍵字: {keywords}")
    
    # 2. 查 PubMed
    st.status(f"步驟 2/3: 正在搜尋 PubMed 關於 {keywords} 的最新文章...", expanded=True)
    pubmed_data = search_pubmed(keywords)
    
    # 3. 生成評論
    st.status("步驟 3/3: 正在撰寫口語化審閱報告...", expanded=True)
    
    system_prompt = """
    你是一位資深、臨床經驗豐富的醫師。這是一份來自你同事的論文投稿（可能包含多個檔案內容）。
    
    語氣要求：
    1. **口語化**：像是在晨會或休息室跟學弟妹討論案子，不要像機器人。
    2. **專業且直接**：針對研究設計、數據與最新文獻的差異進行評論。
    
    你的任務：
    1. **整體評價**：綜合 Cover letter 與正文，簡單說這篇想幹嘛，有沒有搞頭。
    2. **文獻對照**：參考我給你的 PubMed 最新摘要，指出這篇論文的論點是否跟現在最新的風向一致，還是有衝突？
    3. **待釐清問題 (Queries)**：列出 3-5 個你需要作者解釋清楚的問題（例如數據怪怪的、選樣有偏誤等）。
    """

    user_prompt = f"""
    【投稿論文完整資料】:
    {full_text[:8000]} 
    (若內容過長已截斷，請根據現有資訊分析)

    【PubMed 最新文獻 (2024-Now)】:
    {pubmed_data}
    
    請用繁體中文輸出。
    """

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7
    )
    return response.choices[0].message.content

# --- 主程式 ---
st.title("🩺 全能醫學期刊審稿助手 (多檔整合版)")
st.markdown("支援 **一次上傳多個檔案** (Main text, Cover letter, Figures...)，AI 會自動整合分析。")

# 這裡開啟 accept_multiple_files=True
uploaded_files = st.file_uploader(
    "請選擇所有相關檔案 (可多選)", 
    type=['pdf', 'docx', 'jpg', 'jpeg', 'png', 'tiff', 'tif'],
    accept_multiple_files=True
)

if uploaded_files and openai_api_key:
    if st.button("開始整合分析"):
        combined_text = ""
        
        # 建立進度條
        progress_bar = st.progress(0)
        total_files = len(uploaded_files)
        
        for idx, file in enumerate(uploaded_files):
            file_name = file.name
            file_type = file_name.split('.')[-1].lower()
            
            # 在文字中標註這是哪個檔案的內容，幫助 AI 區分
            combined_text += f"\n\n--- 檔案來源：{file_name} ---\n"
            
            extracted_text = ""
            try:
                if file_type == 'pdf':
                    extracted_text = get_text_from_pdf(file)
                elif file_type in ['docx', 'doc']:
                    extracted_text = get_text_from_docx(file)
                elif file_type in ['jpg', 'jpeg', 'png', 'tiff', 'tif']:
                    # 為了節省 API 呼叫與時間，這裡可以選擇是否對每張圖都跑 Vision
                    # 或是只對有 'Table', 'Figure' 字眼的檔案跑
                    extracted_text = f"[圖片內容]: {get_text_from_image(file, openai_api_key)}"
                
                combined_text += extracted_text
                
            except Exception as e:
                st.error(f"處理檔案 {file_name} 時發生錯誤: {e}")
            
            # 更新進度條
            progress_bar.progress((idx + 1) / total_files)

        st.success(f"已成功讀取 {total_files} 個檔案，開始 AI 分析...")
        
        # 呼叫分析函式
        try:
            final_review = analyze_and_generate_review(combined_text, openai_api_key)
            st.divider()
            st.markdown("### 📝 綜合審稿建議")
            st.markdown(final_review)
        except Exception as e:
            st.error(f"AI 分析過程發生錯誤: {e}")

elif not openai_api_key:
    st.warning("請先輸入 OpenAI API Key。")
