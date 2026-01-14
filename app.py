import streamlit as st
import openai
from pypdf import PdfReader
from Bio import Entrez
from docx import Document
from PIL import Image
import io
import base64

# --- 設定頁面 ---
st.set_page_config(page_title="全能醫學期刊審稿助手", layout="wide")

with st.sidebar:
    st.header("設定")
    openai_api_key = st.text_input("輸入 OpenAI API Key", type="password")
    email_address = st.text_input("輸入您的 Email (PubMed 用)", value="doctor@example.com")
    st.markdown("---")
    st.info("支援格式：PDF, Word, JPG, PNG, TIFF")

Entrez.email = email_address

# --- 工具函式區 ---

def get_text_from_pdf(pdf_file):
    """讀取 PDF 文字"""
    try:
        reader = PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            extract = page.extract_text()
            if extract: text += extract
        return text
    except Exception as e:
        return f"PDF 讀取錯誤: {e}"

def get_text_from_docx(docx_file):
    """讀取 Word 文字"""
    try:
        doc = Document(docx_file)
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    except Exception as e:
        return f"Word 讀取錯誤: {e}"

def get_text_from_image(image_file, api_key, file_type):
    """
    利用 GPT-4o Vision 讀取圖片中的文字。
    包含自動將 TIFF 轉為 PNG 的邏輯。
    """
    client = openai.OpenAI(api_key=api_key)
    
    # 處理圖片格式
    image = Image.open(image_file)
    
    # 如果是 TIFF 或其他格式，統一轉為 PNG 以確保 API 相容性
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')

    st.caption("正在使用 AI 視覺辨識圖片內容...")
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "請將這張圖片中的醫學論文內容轉錄為純文字，忽略頁碼或浮水印，只保留內文。"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        max_tokens=2000
    )
    return response.choices[0].message.content

def search_pubmed(keywords, max_results=5):
    """搜尋 PubMed (維持不變)"""
    try:
        # 搜尋最近 2 年
        search_term = f"{keywords} AND (2024[Date - Publication] : 3000[Date - Publication])"
        handle = Entrez.esearch(db="pubmed", term=search_term, retmax=max_results, sort="date")
        record = Entrez.read(handle)
        handle.close()
        
        id_list = record["IdList"]
        if not id_list:
            return "未找到相關最新文獻。"

        handle = Entrez.efetch(db="pubmed", id=id_list, rettype="abstract", retmode="text")
        abstracts = handle.read()
        handle.close()
        return abstracts
    except Exception as e:
        return f"PubMed 搜尋錯誤: {e}"

def analyze_and_generate_review(paper_text, api_key):
    """
    整合流程：
    1. 抓關鍵字 -> 2. 查 PubMed -> 3. 生成口語化評論
    """
    client = openai.OpenAI(api_key=api_key)
    
    # 1. 抓關鍵字
    st.status("步驟 1/3: 分析論文主題與關鍵字...", expanded=True)
    prompt_extract = f"""
    請閱讀以下論文摘要或片段，提取 3-5 個用於 PubMed 搜尋的核心英文醫學關鍵字 (MeSH terms 佳)。
    只回傳關鍵字，用空格隔開。
    
    內容: {paper_text[:2000]}
    """
    kw_resp = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": prompt_extract}]
    )
    keywords = kw_resp.choices[0].message.content
    st.success(f"關鍵字: {keywords}")
    
    # 2. 查 PubMed
    st.status("步驟 2/3: 搜尋 PubMed 最新文獻...", expanded=True)
    pubmed_data = search_pubmed(keywords)
    with st.expander("點擊查看抓取到的文獻摘要"):
        st.text(pubmed_data[:2000] + "...") # 預覽部分

    # 3. 生成評論
    st.status("步驟 3/3: 生成口語化審閱報告...", expanded=True)
    
    system_prompt = """
    你是一位資深、臨床經驗豐富的醫師前輩。你正在協助同事審閱論文。
    
    語氣指引：
    - **高度口語化**：像是在醫生休息室喝咖啡時的對話。
    - **避免 AI 腔**：禁止使用「首先、其次、綜上所述」這類八股文。
    - **專業但輕鬆**：例如「這篇講 HIFU 的切入點蠻特別的，但我看了一下最新的 paper，像 Chen et al. 那篇，結論好像有點出入...」。
    
    任務：
    1. 總結這篇文章想解決什麼臨床問題。
    2. 對比我提供的 PubMed 最新文獻，指出這篇文章的創新或過時之處。
    3. 列出 3-5 個具體且尖銳的問題 (Questions for authors)，這是要用來幫作者釐清盲點的。
    """

    user_prompt = f"""
    【投稿文章片段】:
    {paper_text[:6000]}

    【PubMed 最新相關文獻】:
    {pubmed_data}
    
    請用繁體中文輸出建議。
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

# --- 主程式邏輯 ---
st.title("🩺 全能醫學期刊審稿助手")
st.markdown("支援 **PDF, Word, JPG, PNG, TIFF**。上傳後自動聯網分析。")

# 允許上傳多種格式
uploaded_file = st.file_uploader(
    "請上傳檔案", 
    type=['pdf', 'docx', 'jpg', 'jpeg', 'png', 'tiff', 'tif']
)

if uploaded_file and openai_api_key:
    if st.button("開始分析"):
        raw_text = ""
        file_type = uploaded_file.name.split('.')[-1].lower()
        
        try:
            with st.spinner('正在讀取檔案內容...'):
                # 根據副檔名分流處理
                if file_type == 'pdf':
                    raw_text = get_text_from_pdf(uploaded_file)
                
                elif file_type in ['docx', 'doc']:
                    raw_text = get_text_from_docx(uploaded_file)
                
                elif file_type in ['jpg', 'jpeg', 'png', 'tiff', 'tif']:
                    # 圖片需要呼叫 API 進行視覺辨識
                    raw_text = get_text_from_image(uploaded_file, openai_api_key, file_type)
                
                if len(raw_text) < 50:
                    st.error("讀取到的文字太少，請確認檔案內容是否清晰。")
                else:
                    # 進入分析流程
                    final_review = analyze_and_generate_review(raw_text, openai_api_key)
                    st.divider()
                    st.markdown("### 📝 醫師審稿建議")
                    st.markdown(final_review)

        except Exception as e:
            st.error(f"發生未預期的錯誤: {e}")

elif not openai_api_key:
    st.warning("請先輸入 OpenAI API Key 才能運作。")
