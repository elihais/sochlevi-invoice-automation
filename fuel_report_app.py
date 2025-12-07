import streamlit as st
import re
import zipfile
import pdfplumber
import io
from PyPDF2 import PdfReader, PdfWriter

# --- הגדרות עיצוב (RTL & תיקון נראות) ---
st.set_page_config(page_title="מערכת פיצול דוחות דלק", page_icon="⛽", layout="centered")

st.markdown("""
<style>
    /* ---------------------- 1. RTL & יישור גלובלי (הכרחי) ---------------------- */
    .stApp {
        direction: rtl;
        text-align: right;
    }
    
    /* ---------------------- 2. תיקון צבע טקסט אגרסיבי (במיוחד ל-File Uploader) ---------------------- */
    /* מכוון לכל טקסט באפליקציה כדי לוודא שהוא כהה על רקע Streamlit הבהיר */
    .stApp, 
    .stApp p, 
    .stApp span, 
    .stMarkdown,
    div[data-testid^="stBlock"] *, /* כל תוכן בתוך בלוקים */
    div[data-testid="stFileUploader"] label, /* תווית העלאת קובץ */
    div[data-testid="stFileUploader"] p, /* הטקסט בתוך תיבת ההעלאה */
    div[data-testid="stFileUploader"] svg, /* אייקון העלאה */
    .stAlert p,
    .stSpinner p,
    .stDownloadButton p {
        color: #333333 !important; /* צבע טקסט כהה */
        text-align: right;
    }

    /* יישור כל הטקסט (כולל כותרות וטקסט רגיל) לימין */
    h1, h2, h3, h4, h5, h6 {
        text-align: right;
        color: #1f78b4 !important; /* כותרת כחולה */
    }

    /* יישור תווית מעלה קובץ (File Uploader Label) לימין */
    div[data-testid="stFileUploader"] label, 
    div[data-testid^="stBlock"] label {
        justify-content: flex-end;
        width: 100%;
        display: flex;
        font-size: 1.1rem;
    }
    
    /* עיצוב כפתורים עדין */
    .stButton>button, .stDownloadButton>button {
        background-color: #1f78b4;
        color: white !important; 
        border-radius: 8px;
        border: none;
        padding: 0.5rem 1.5rem;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# --- לוגיקה עסקית: חילוץ נתונים (אסטרטגיית ה-OCR/טבלאות) ---

def robust_extract_metadata(pdf):
    """מחלץ מטא-דאטה באמצעות חיפוש גמיש בעמוד הראשון."""
    if not pdf.pages:
        return "99999", "0000", "00-0000"
    
    page = pdf.pages[0]
    full_text = page.extract_text(x_tolerance=1, y_tolerance=1) or ""
    
    # 1. מספר לקוח (חיפוש גמיש)
    customer_id_match = re.search(r'(?:לקוח|מס[\'"]? לקוח)\s*[:]?\s*(\d{4,})', full_text)
    customer_id = customer_id_match.group(1) if customer_id_match else "99999" 
    
    # 2. מספר דו"ח (חיפוש גמיש)
    invoice_num_match = re.search(r'(?:מס[\'"]? דו"?ח|חשבונית)\s*[:]?\s*(\d+)', full_text)
    invoice_num = invoice_num_match.group(1) if invoice_num_match else "0000" 
    
    # 3. תאריך (חודש-שנה) - מחפש תבנית תאריך בכל מקום
    date_match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', full_text)
    
    date_str = "00-0000"
    if date_match:
        # קבוצה 1: יום/חודש, קבוצה 2: יום/חודש, קבוצה 3: שנה
        try:
            day_or_month_1 = int(date_match.group(1))
            day_or_month_2 = int(date_match.group(2))
            year = date_match.group(3)
            
            # מניח פורמט ישראלי (DD/MM/YYYY) או אמריקאי (MM/DD/YYYY)
            if day_or_month_1 > 12: 
                # אם הראשון גדול מ-12, הוא כנראה היום, והשני הוא החודש
                month = str(day_or_month_2).zfill(2)
            else:
                # ברירת מחדל: לוקח את המופע השני כחודש (נפוץ בדו"חות)
                month = str(day_or_month_2).zfill(2)
            
            date_str = f"{month}-{year}"
        except:
            date_str = "00-0000"

    return customer_id, invoice_num, date_str

def robust_get_dept_id(page):
    """
    מחלץ מספר מחלקה באמצעות:
    1. חיפוש טקסט רגיל (גיבוי)
    2. חילוץ מבוסס טבלאות (האסטרטגיה החדשה והרובוסטית)
    """
    
    # 1. ניסיון בסיסי (מהיר) - עשוי לעבוד אם הכיווניות תקינה
    text = page.extract_text(y_tolerance=3) or ""
    match = re.search(r'מחלקה\s*[:]?\s*(\d{5})', text)
    if match:
        return match.group(1)

    # 2. אסטרטגיה חדשה: ניתוח טבלאות
    # שימוש ב-settings של pdfplumber לחילוץ כל הטבלאות בדף
    tables = page.extract_tables()
    
    for table in tables:
        for row in table:
            for cell_value in row:
                if cell_value:
                    cleaned_cell = str(cell_value).strip()
                    
                    # אם המילה "מחלקה" קיימת בתא
                    if re.search(r'מחלקה', cleaned_cell):
                        # חפש 5 ספרות רצופות בתא זה או בתאים סמוכים (בשורה)
                        five_digit_match = re.search(r'(\d{5})', cleaned_cell)
                        if five_digit_match:
                            return five_digit_match.group(1)
                        
                        # אם לא נמצא בתא עצמו, נסה לחפש בתאים הסמוכים באותה שורה
                        # (ניתוח מלא של שורה - מסובך מדי, נסתמך על ה-Regex שלמעלה)
    
    # 3. חילוץ מרחבי (גיבוי שני)
    words = page.extract_words()
    label_matches = [w for w in words if re.search(r'מחלקה', w['text'])]
    
    for label in label_matches:
        # הגדרת אזור חיפוש קטן סביב התווית
        bbox = (
            label['x0'] - 100, # שמאלה X
            label['top'] - 5,
            label['x1'] + 100, # ימינה X
            label['bottom'] + 5
        )
        try:
            cropped_text = page.within_bbox(bbox).extract_text()
            if cropped_text:
                matches = re.findall(r'(\d{5})', cropped_text)
                if matches:
                    return matches[0]
        except:
            pass # אם האזור מחוץ לגבולות הדף

    return None

def process_pdf_ultimate(pdf_bytes):
    input_stream = io.BytesIO(pdf_bytes)
    reader = PdfReader(input_stream)
    total_pages = len(reader.pages)
    
    dept_pages = {} 
    current_dept = "UNKNOWN"
    
    progress_bar = st.progress(0)
    status_text = st.empty()

    with pdfplumber.open(input_stream) as pdf:
        for i, page in enumerate(pdf.pages):
            progress_bar.progress((i + 1) / total_pages)
            status_text.text(f"סורק עמוד {i+1} מתוך {total_pages}... (מחלקה נוכחית: {current_dept})")

            dept_id = robust_get_dept_id(page)
            
            if dept_id:
                current_dept = dept_id
            
            if current_dept not in dept_pages:
                dept_pages[current_dept] = []
            
            pypdf_page = reader.pages[i]
            
            # חיתוך כותרת תחתונה
            current_lower_left = pypdf_page.cropbox.lower_left
            pypdf_page.cropbox.lower_left = (current_lower_left[0], current_lower_left[1] + 40)
            
            dept_pages[current_dept].append(pypdf_page)

    progress_bar.empty()
    status_text.empty()
    return dept_pages

# --- ממשק משתמש (UI) ---

st.title("⛽ דוחות דלק - מערכת פיצול (פיתרון אולטימטיבי)")
st.write("המערכת משתמשת בשלוש שיטות חילוץ נתונים (טקסט רגיל, מיקום מרחבי וניתוח טבלאות) כדי להבטיח זיהוי מחלקה יציב.")

uploaded_file = st.file_uploader("בחר קובץ PDF להעלאה", type=["pdf"])

if uploaded_file is not None:
    pdf_bytes = uploaded_file.getvalue()
    st.info(f"הקובץ **{uploaded_file.name}** נטען בהצלחה.")
    
    if st.button("הפעל מנוע פיצול", key="process"):
        try:
            # חילוץ מטא-דאטה
            temp_stream = io.BytesIO(pdf_bytes)
            with pdfplumber.open(temp_stream) as temp_pdf:
                cust_id, inv_num, date_str = robust_extract_metadata(temp_pdf)

            st.caption(f"זוהה בכותרת: **לקוח {cust_id}** | **חשבונית {inv_num}** | **תאריך {date_str}**")

            with st.spinner('⏳ מפעיל מנועי ניתוח מתקדמים (טקסט, מיקום, טבלאות)...'):
                dept_map = process_pdf_ultimate(pdf_bytes)
            
            if not dept_map:
                st.error("❌ לא נמצאו דפים לעיבוד. ייתכן שהקובץ אינו מכיל טקסט קריא.")
            else:
                st.success(f"✅ סיום עיבוד. פוצל ל-{len(dept_map)} קבצים ({sum(len(v) for v in dept_map.values())} דפים).")
                
                # יצירת ZIP
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                    total_pages = 0
                    
                    unknown = dept_map.pop("UNKNOWN", None)
                    if unknown:
                        st.warning(f"⚠️ {len(unknown)} דפים לא שויכו למחלקה (נשמרו בנפרד).")
                        writer = PdfWriter()
                        for p in unknown: writer.add_page(p)
                        tmp = io.BytesIO()
                        writer.write(tmp)
                        zip_file.writestr(f"Unknown_{cust_id}_{date_str}.pdf", tmp.getvalue())
                        total_pages += len(unknown)

                    for dept, pages in dept_map.items():
                        writer = PdfWriter()
                        for p in pages: writer.add_page(p)
                        tmp = io.BytesIO()
                        writer.write(tmp)
                        
                        fname = f"{cust_id}_{date_str}_{inv_num}_{dept}.pdf"
                        zip_file.writestr(fname, tmp.getvalue())
                        total_pages += len(pages)
                
                st.download_button(
                    label="⬇️ הורד קובץ ZIP סופי",
                    data=zip_buffer.getvalue(),
                    file_name=f"מפוצל_{cust_id}_{date_str}.zip",
                    mime="application/zip"
                )
                
                # טבלת סיכום
                st.divider()
                st.subheader("פירוט וסטטיסטיקה:")
                data = [{"מחלקה": k, "דפים": len(v)} for k,v in dept_map.items()]
                if 'unknown' in locals() and unknown: data.insert(0, {"מחלקה": "ללא זיהוי", "דפים": len(unknown)})
                st.table(data)

        except Exception as e:
            st.error("❌ שגיאה קריטית. לא ניתן היה לעבד את הקובץ.")
            st.exception(e)
