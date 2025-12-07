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
    .stApp {
        direction: rtl;
        text-align: right;
    }
    .stMarkdown, .stFileUploader, .stButton, .stDownloadButton {
        text-align: right;
    }
    div[data-testid="stFileUploader"] label {
        justify-content: flex-end;
        width: 100%;
        display: flex;
    }
</style>
""", unsafe_allow_html=True)

# --- לוגיקה עסקית (אותו קוד Python, מותאם לזיכרון במקום לדיסק) ---

def extract_department_id(text):
    """מחלץ מספר מחלקה (5 ספרות) מתוך טקסט"""
    if not text:
        return None
    # חיפוש תבנית: 5 ספרות ליד המילה מחלקה
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

    # שימוש ב-pdfplumber לקריאת טקסט (מדויק יותר בעברית)
    with pdfplumber.open(input_stream) as pdf:
        for i, page in enumerate(pdf.pages):
            # עדכון סטטוס
            progress_bar.progress((i + 1) / total_pages)
            status_text.text(f"מעבד עמוד {i+1} מתוך {total_pages}...")

            text = page.extract_text()
            dept_id = extract_department_id(text)
            
            # לוגיקת שיוך מחלקה
            if dept_id:
                current_dept = dept_id
            
            if current_dept not in dept_pages:
                dept_pages[current_dept] = []
            
            # חיתוך (Cropping) - עבודה עם PyPDF2
            pypdf_page = reader.pages[i]
            
            # חיתוך 40 נקודות מלמטה (Footer)
            # הערה: זה עובד על הקובץ בזיכרון, לא משנה את המקור
            current_lower_left = pypdf_page.cropbox.lower_left
            pypdf_page.cropbox.lower_left = (current_lower_left[0], current_lower_left[1] + 40)
            
            dept_pages[current_dept].append(pypdf_page)

    return dept_pages

# --- ממשק משתמש (UI) ---

st.title("⛽ מערכת פיצול דוחות צריכה")
st.write("אנא העלה את קובץ ה-PDF המרוכז. המערכת תפצל אותו למחלקות, תסיר את מספרי העמודים ותכין קובץ ZIP להורדה.")

uploaded_file = st.file_uploader("בחר קובץ PDF", type=["pdf"])

if uploaded_file is not None:
    if st.button("התחל עיבוד 🚀"):
        try:
            with st.spinner('מבצע פיצול וניתוח... נא להמתין'):
                dept_map = process_pdf(uploaded_file)
            
            st.success(f"העיבוד הסתיים! זוהו {len(dept_map)} מחלקות.")
            
            # יצירת קובץ ZIP בזיכרון
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                for dept, pages in dept_map.items():
                    writer = PdfWriter()
                    for page in pages:
                        writer.add_page(page)
                    
                    # שמירת PDF בודד לזיכרון
                    pdf_out = io.BytesIO()
                    writer.write(pdf_out)
                    
                    # הוספה ל-ZIP
                    zip_file.writestr(f"{dept}.pdf", pdf_out.getvalue())
            
            # כפתור הורדה
            st.download_button(
                label="📥 הורד את כל הקבצים (ZIP)",
                data=zip_buffer.getvalue(),
                file_name="split_reports.zip",
                mime="application/zip"
            )
            
            # הצגת סטטיסטיקה
            st.divider()
            st.subheader("📊 סיכום דפים:")
            stats = {k: len(v) for k, v in dept_map.items()}
            st.json(stats)

        except Exception as e:
            st.error(f"אירעה שגיאה: {e}")

איך מפעילים את זה? (חינם לגמרי)
אין צורך בהתקנות על המחשב.
 * הירשם לאתר Streamlit Community Cloud (חיבור דרך GitHub).
 * צור מאגר (Repository) חדש ב-GitHub ושים בו את הקובץ fuel_report_app.py וקובץ נוסף בשם requirements.txt שמכיל את השורות הבאות:
   streamlit
pdfplumber
pypdf2

 * באתר של Streamlit, לחץ על "New App", בחר את המאגר שיצרת.
 * זהו! יש לך לינק (URL) לאפליקציה שאתה יכול לשלוח למזכירה/מנהל חשבונות. הם נכנסים מהדפדפן ועובדים.
אפשרות ב': Google Colab בתצורת "טופס" (Form Mode)
אם אתה מעדיף להישאר אך ורק בתוך גוגל ולא לפתוח חשבונות חיצוניים, אפשר להשתמש ב-Colab אבל להסתיר את הקוד כך שזה ייראה כמו טופס.
 * פותחים מחברת Colab חדשה.
 * מדביקים את הקוד הבא.
 * בתפריט העליון בוחרים: View -> Show/hide code (כדי להסתיר את הקוד המפחיד).
 * המשתמש רק לוחץ על כפתור ה-Play הקטן בצד.
# @title ⛽ כלי פיצול דוחות דלק
# @markdown לחץ על כפתור ה-Play משמאל כדי להפעיל את הכלי.
# @markdown <br>לאחר הלחיצה, יופיע כפתור להעלאת הקובץ.

import os
import re
import zipfile
import io
from google.colab import files
from PyPDF2 import PdfReader, PdfWriter

# התקנת ספריות חסרות (רץ אוטומטית)
try:
    import pdfplumber
except ImportError:
    print("מתקין רכיבים נדרשים...")
    !pip install -q pdfplumber
    import pdfplumber

def split_and_download():
    print("אנא העלה את קובץ ה-PDF...")
    uploaded = files.upload()
    
    if not uploaded:
        print("לא נבחר קובץ.")
        return

    filename = next(iter(uploaded))
    print(f"מעבד את הקובץ: {filename}...")

    # פתיחת הקובץ
    reader = PdfReader(io.BytesIO(uploaded[filename]))
    
    dept_pages = {}
    current_dept = "UNKNOWN"
    
    # שימוש ב-pdfplumber לקריאת טקסט
    with pdfplumber.open(io.BytesIO(uploaded[filename])) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            
            # זיהוי מחלקה
            match = re.search(r'(\d{5})\s*[:]?\s*מחלקה', text) or re.search(r'מחלקה\s*[:]?\s*(\d{5})', text)
            if match:
                current_dept = match.group(1)
            
            if current_dept not in dept_pages:
                dept_pages[current_dept] = []
            
            # חיתוך
            pypdf_page = reader.pages[i]
            curr_bottom = pypdf_page.cropbox.lower_left
            pypdf_page.cropbox.lower_left = (curr_bottom[0], curr_bottom[1] + 40)
            
            dept_pages[current_dept].append(pypdf_page)
            print(f"\rמעבד עמוד {i+1}/{total}", end="")

    print("\nיוצר קובץ ZIP...")
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        for dept, pages in dept_pages.items():
            pdf_out = io.BytesIO()
            writer = PdfWriter()
            for p in pages:
                writer.add_page(p)
            writer.write(pdf_out)
            zf.writestr(f"{dept}.pdf", pdf_out.getvalue())

    # שמירה לדיסק של קולאב והורדה אוטומטית
    with open("split_reports.zip", "wb") as f:
        f.write(zip_buffer.getvalue())
    
    files.download("split_reports.zip")
    print("\n✅ הסתיים! ההורדה תתחיל מיד.")

# הרצת הפונקציה
split_and_download()
