import streamlit as st
import re
import zipfile
import pdfplumber
import io
import os
from PyPDF2 import PdfReader, PdfWriter

# --- הגדרות עיצוב (RTL לעברית) ---
st.set_page_config(page_title="מערכת פיצול דוחות דלק", page_icon="⛽", layout="centered")

st.markdown("""
<style>
    /* הגדרת כיוון כללי מימין לשמאל */
    .stApp {
        direction: rtl;
        text-align: right;
    }
    /* יישור כל רכיבי הטקסט, העלאה וכפתורים לימין */
    .stMarkdown, .stFileUploader, .stButton, .stDownloadButton, div[data-testid^="stBlock"] {
        text-align: right;
    }
    /* יישור תווית מעלה קובץ לימין */
    div[data-testid="stFileUploader"] label {
        justify-content: flex-end;
        width: 100%;
        display: flex;
    }
</style>
""", unsafe_allow_html=True)

# --- לוגיקה עסקית ---

def extract_department_id(text):
    """מחלץ מספר מחלקה (5 ספרות) מתוך טקסט"""
    if not text:
        return None
    
    # חיפוש תבנית: 5 ספרות ליד המילה מחלקה או הפוך
    match = re.search(r'(\d{5})\s*[:]?\s*מחלקה', text)
    if not match:
        match = re.search(r'מחלקה\s*[:]?\s*(\d{5})', text)
    
    if match:
        return match.group(1)
    return None

def process_pdf(uploaded_file):
    # קריאת הקובץ לזיכרון
    pdf_bytes = uploaded_file.getvalue()
    input_stream = io.BytesIO(pdf_bytes)
    
    reader = PdfReader(input_stream)
    total_pages = len(reader.pages)
    
    dept_pages = {} # {dept_id: [page_obj, ...]}
    current_dept = "UNKNOWN"
    
    # פס התקדמות
    progress_bar = st.progress(0)
    status_text = st.empty()

    # שימוש ב-pdfplumber לקריאת טקסט
    with pdfplumber.open(input_stream) as pdf:
        for i, page in enumerate(pdf.pages):
            # עדכון סטטוס
            progress_bar.progress((i + 1) / total_pages)
            status_text.text(f"מעבד עמוד {i+1} מתוך {total_pages}... (מחלקה נוכחית: {current_dept})")

            text = page.extract_text()
            dept_id = extract_department_id(text)
            
            # לוגיקת שיוך מחלקה (Carry-Forward)
            if dept_id:
                current_dept = dept_id
            
            if current_dept not in dept_pages:
                dept_pages[current_dept] = []
            
            # חיתוך (Cropping) - עבודה עם PyPDF2
            pypdf_page = reader.pages[i]
            
            # חיתוך 40 נקודות מלמטה (Footer removal)
            current_lower_left = pypdf_page.cropbox.lower_left
            pypdf_page.cropbox.lower_left = (current_lower_left[0], current_lower_left[1] + 40)
            
            dept_pages[current_dept].append(pypdf_page)
            
    # מנקה את פס ההתקדמות לאחר סיום
    progress_bar.empty()
    status_text.empty()
    
    return dept_pages

# --- ממשק משתמש (UI) ---

st.title("⛽ מערכת פיצול דוחות צריכה")
st.write("אנא העלה את קובץ ה-PDF המרוכז. המערכת תפצל אותו לפי מספרי מחלקות (5 ספרות), תסיר את מספרי העמודים ותכין קובץ ZIP להורדה.")

uploaded_file = st.file_uploader("בחר קובץ PDF", type=["pdf"])

if uploaded_file is not None:
    # מציג את השם של הקובץ שהועלה
    st.info(f"הקובץ הועלה בהצלחה: **{uploaded_file.name}**")
    
    if st.button("התחל עיבוד 🚀", key="process_button"):
        try:
            with st.spinner('מבצע פיצול וניתוח... נא להמתין'):
                dept_map = process_pdf(uploaded_file)
            
            # 1. בדיקה אם זוהו מחלקות. משתמשים ב-if/else במקום return.
            if not dept_map:
                st.warning("לא נמצאו נתונים לעיבוד. ודא שהקובץ אינו ריק או מוגן.")
            else:
                # 2. אם נמצאו מחלקות, ממשיכים בלוגיקת יצירת ה-ZIP וההורדה
                st.success(f"העיבוד הסתיים! זוהו {len(dept_map)} קבצים מפוצלים.")
                
                # יצירת קובץ ZIP בזיכרון
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                    total_pages_processed = 0
                    for dept, pages in dept_map.items():
                        writer = PdfWriter()
                        for page in pages:
                            writer.add_page(page)
                        
                        # שמירת PDF בודד לזיכרון
                        pdf_out = io.BytesIO()
                        writer.write(pdf_out)
                        
                        # הוספה ל-ZIP
                        zip_file.writestr(f"{dept}.pdf", pdf_out.getvalue())
                        total_pages_processed += len(pages)
                
                # כפתור הורדה
                st.download_button(
                    label="📥 הורד את כל הקבצים (ZIP)",
                    data=zip_buffer.getvalue(),
                    file_name="split_reports.zip",
                    mime="application/zip"
                )
                
                # הצגת סטטיסטיקה
                st.divider()
                st.subheader("📊 סיכום דפים לפי מחלקה:")
                st.markdown(f"**סה״כ עמודים שעובדו:** {total_pages_processed}")
                
                stats_list = [{"מחלקה": k, "עמודים": len(v)} for k, v in dept_map.items()]
                st.table(stats_list)

        except Exception as e:
            # הצגת שגיאה ברורה למשתמש
            st.error("אירעה שגיאה קריטית במהלך העיבוד. אנא ודא שהקובץ תקין ונסה שוב.")
            # הדפסת השגיאה המלאה לקונסול
            st.exception(e)
