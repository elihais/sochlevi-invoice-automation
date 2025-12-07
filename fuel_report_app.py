import streamlit as st
import re
import zipfile
import pdfplumber
import io
import os
from PyPDF2 import PdfReader, PdfWriter

# --- הגדרות עיצוב (RTL & Liquid Glass/Minimalism) ---
st.set_page_config(page_title="מערכת פיצול דוחות דלק", page_icon="⛽", layout="centered")

st.markdown("""
<style>
    /* ---------------------- 1. RTL & יישור גלובלי ---------------------- */
    .stApp {
        direction: rtl;
        text-align: right;
        background-color: #f0f2f6; /* רקע בהיר ונקי */
        padding: 1rem;
    }
    
    /* ---------------------- 2. תיקון צבע טקסט (פתרון חובה עם !important) ---------------------- */
    /* מכריח טקסט להיות כהה (#333333) על רקע בהיר, עוקף את הגדרות Streamlit בכל מקום אפשרי */
    .stApp, 
    .stApp p, 
    .stApp span, 
    .stMarkdown,
    div[data-testid^="stBlock"] * , /* מכוון לכל תוכן בתוך בלוקים */
    div[data-testid^="stFileUploader"] label, /* תווית העלאת קובץ */
    div[data-testid="stFileUploader"] p,
    .stAlert p,
    div[data-testid="stAlert"] * ,
    .stSpinner p,
    .stDownloadButton p,
    .stTable .dataframe * {
        color: #333333 !important;
    }

    /* יישור מרכזי לכותרת העליונה וצבע כחול */
    h1 {
        text-align: center;
        width: 100%;
        color: #1f78b4 !important; /* כחול נקי */
    }

    /* כותרות משנה ואחרות - כהות */
    h2, h3, h4, h5, h6 {
        color: #333333 !important;
    }

    /* יישור תווית מעלה קובץ לימין */
    div[data-testid="stFileUploader"] label {
        justify-content: flex-end;
        width: 100%;
        display: flex;
        font-size: 1.1rem;
        /* צבע הטקסט כאן מכוון שוב למעלה */
    }
    
    /* ---------------------- 3. Liquid Glass Card ---------------------- */
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        max-width: 700px; /* רוחב מוגבל במרכז */
        
        /* אפקט זכוכית עדין */
        background: rgba(255, 255, 255, 0.7);
        border-radius: 16px;
        box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
        backdrop-filter: blur(5px);
        -webkit-backdrop-filter: blur(5px);
        border: 1px solid rgba(255, 255, 255, 0.3);
    }
    
    /* כפתורים מודרניים */
    .stButton>button, .stDownloadButton>button {
        background-color: #1f78b4;
        color: white !important; /* לוודא שהטקסט בתוך הכפתור לבן */
        border-radius: 8px;
        border: none;
        padding: 0.5rem 1.5rem;
        transition: all 0.2s ease-in-out;
        font-weight: bold;
    }
    .stButton>button:hover, .stDownloadButton>button:hover {
        background-color: #0b5585;
        box-shadow: 0 2px 8px rgba(31, 120, 180, 0.5);
    }
</style>
""", unsafe_allow_html=True)

# --- לוגיקה עסקית: חילוץ נתונים כלליים (תבניות רגולריות משופרות) ---

def extract_metadata(pdf_bytes):
    """
    מחלץ מספר לקוח, מספר דו"ח ותאריך (חודש ושנה) כללי מהעמוד הראשון.
    """
    input_stream = io.BytesIO(pdf_bytes)
    
    with pdfplumber.open(input_stream) as pdf:
        if not pdf.pages:
            return "99999", "0000", "00-0000", ""
        
        first_page_text = pdf.pages[0].extract_text()
        
        # 1. מספר לקוח (Customer ID) - מחפש: לקוח [רווחים/נקודתיים אופציונליים] [מספר]
        customer_id_match = re.search(r'לקוח\s*[:]?\s*(\d+)', first_page_text)
        customer_id = customer_id_match.group(1) if customer_id_match else "99999" 
        
        # 2. מספר דו"ח (Invoice Number) - מחפש: מס' דו"ח [רווחים/נקודתיים אופציונליים] [מספר]
        invoice_num_match = re.search(r'מס\' דו"ח\s*[:]?\s*(\d+)', first_page_text)
        invoice_num = invoice_num_match.group(1) if invoice_num_match else "0000" 
        
        # 3. חודש ושנה (Month and Year) - תיקון האינדקס: group(2) הוא החודש, group(3) הוא השנה
        # תבנית: X/Y/Z (יום/חודש/שנה)
        date_match = re.search(r'תאריך הפקת דו"ח\s*[:]?\s*(\d{1,2})/(\d{1,2})/(\d{4})', first_page_text)
        
        if date_match:
            month = date_match.group(2).zfill(2) # אינדקס 2 הוא החודש
            year = date_match.group(3)          # אינדקס 3 הוא השנה
            date_str = f"{month}-{year}"
        else:
            date_str = "00-0000"
            
        return customer_id, invoice_num, date_str, first_page_text

def extract_department_id(text):
    """מחלץ מספר מחלקה (5 ספרות) מתוך טקסט - לוגיקה משופרת."""
    if not text:
        return None
    
    # חיפוש גמיש: [5 ספרות] סמוך למילה 'מחלקה'
    # הדגש הוא על תפיסת המופע הראשון של 5 ספרות אחרי "מחלקה"
    match = re.search(r'מחלקה\s*[:]?\s*(\d{5})', text)
    if match:
        return match.group(1)
        
    # חיפוש חלופי (פחות סביר): [5 ספרות] לפני המילה 'מחלקה'
    match = re.search(r'(\d{5})\s*[:]?\s*מחלקה', text)
    if match:
        return match.group(1)
        
    return None

def process_pdf(pdf_bytes):
    """מפצל את ה-PDF לפי מחלקות ומבצע חיתוך תחתי."""
    input_stream = io.BytesIO(pdf_bytes)
    
    reader = PdfReader(input_stream)
    total_pages = len(reader.pages)
    
    dept_pages = {} # {dept_id: [page_obj, ...]}
    current_dept = "UNKNOWN"
    
    # פס התקדמות
    progress_bar = st.progress(0)
    status_text = st.empty()

    with pdfplumber.open(input_stream) as pdf:
        for i, page in enumerate(pdf.pages):
            # עדכון סטטוס
            progress_bar.progress((i + 1) / total_pages)
            status_text.text(f"מעבד עמוד {i+1} מתוך {total_pages}... (מחלקה נוכחית: {current_dept})")

            # חילוץ טקסט
            text = page.extract_text(y_tolerance=3) 
            dept_id = extract_department_id(text)
            
            # לוגיקת שיוך מחלקה (Carry-Forward)
            if dept_id:
                current_dept = dept_id
            
            if current_dept not in dept_pages:
                dept_pages[current_dept] = []
            
            # חיתוך (Cropping) - עבודה עם PyPDF2
            pypdf_page = reader.pages[i]
            
            # חיתוך 40 נקודות מלמטה (Footer removal - מספרי עמודים)
            current_lower_left = pypdf_page.cropbox.lower_left
            pypdf_page.cropbox.lower_left = (current_lower_left[0], current_lower_left[1] + 40)
            
            dept_pages[current_dept].append(pypdf_page)
            
    # מנקה את פס ההתקדמות לאחר סיום
    progress_bar.empty()
    status_text.empty()
    
    return dept_pages

# --- ממשק משתמש (UI) ---

st.title("⛽ דוחות דלק - מערכת פיצול")
st.write("אנא העלה את קובץ ה-PDF המרוכז. המערכת תפצל אותו לפי מספרי מחלקות (5 ספרות), תסיר את כותרת התחתונה ותכין קובץ ZIP להורדה.")

uploaded_file = st.file_uploader("בחר קובץ PDF", type=["pdf"])

if uploaded_file is not None:
    # קוראים את הקובץ לזיכרון פעם אחת
    pdf_bytes = uploaded_file.getvalue()
    st.info(f"הקובץ הועלה בהצלחה: **{uploaded_file.name}**")
    
    if st.button("התחל עיבוד", key="process_button"):
        try:
            # 1. חילוץ מטא-דאטה ראשונית
            customer_id, invoice_num, date_str, first_page_text = extract_metadata(pdf_bytes)

            # בדיקה משופרת והצגת אזהרה אם נותרו ערכי ברירת מחדל
            if customer_id == "99999" or invoice_num == "0000" or date_str == "00-0000":
                st.warning("שים לב: לא ניתן היה לחלץ באופן מלא את מספר הלקוח, מספר הדו״ח או התאריך מהעמוד הראשון. שם הקובץ יכלול ערכי ברירת מחדל (99999/0000/00-0000).")
            
            with st.spinner('מבצע פיצול וניתוח... נא להמתין'):
                dept_map = process_pdf(pdf_bytes)
            
            # 2. בדיקה אם זוהו מחלקות
            if not dept_map:
                st.warning("לא נמצאו דפים לעיבוד. ודא שהקובץ אינו ריק או מוגן בסיסמה.")
            else:
                # 3. אם נמצאו מחלקות, ממשיכים בלוגיקת יצירת ה-ZIP וההורדה
                st.success(f"העיבוד הסתיים בהצלחה. זוהו {len(dept_map)} קבצים מפוצלים.")
                
                # יצירת קובץ ZIP בזיכרון
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                    total_pages_processed = 0
                    
                    # טיפול בדפי UNKNOWN
                    unknown_pages = dept_map.pop("UNKNOWN", None)
                    if unknown_pages:
                        st.info("נמצאו דפים ללא מספר מחלקה שקובצו תחת השם 'דפים_ללא_מחלקה'.")
                        
                        writer = PdfWriter()
                        for page in unknown_pages:
                            writer.add_page(page)
                        pdf_out = io.BytesIO()
                        writer.write(pdf_out)
                        
                        # שם קובץ מותאם: דפים_ללא_מחלקה_ [לקוח]_ [תאריך]_ [דוח].pdf
                        unknown_filename = f"דפים_ללא_מחלקה_{customer_id}_{date_str}_{invoice_num}.pdf"
                        zip_file.writestr(unknown_filename, pdf_out.getvalue())
                        total_pages_processed += len(unknown_pages)

                    # לולאה על המחלקות המזוהות
                    for dept, pages in dept_map.items():
                        writer = PdfWriter()
                        for page in pages:
                            writer.add_page(page)
                        
                        # שמירת PDF בודד לזיכרון
                        pdf_out = io.BytesIO()
                        writer.write(pdf_out)
                        
                        # **בניית שם קובץ ייחודי:** [Customer ID]_[Month-Year]_[Invoice No]_[Dept ID].pdf
                        new_filename = f"{customer_id}_{date_str}_{invoice_num}_{dept}.pdf"
                        
                        # הוספה ל-ZIP
                        zip_file.writestr(new_filename, pdf_out.getvalue())
                        total_pages_processed += len(pages)
                
                # כפתור הורדה
                st.download_button(
                    label="הורד את כל הקבצים (ZIP)",
                    data=zip_buffer.getvalue(),
                    file_name=f"מפוצל_{customer_id}_{date_str}_{invoice_num}.zip",
                    mime="application/zip"
                )
                
                # הצגת סטטיסטיקה
                st.divider()
                st.subheader("סיכום דפים:")
                st.markdown(f"**סה״כ עמודים שעובדו:** {total_pages_processed}")
                
                stats_list = [{"מחלקה": k, "עמודים": len(v)} for k, v in dept_map.items() if k != "UNKNOWN"]
                
                # אם היו דפים ללא מחלקה (Unknown), נוסיף אותם לטבלה
                if 'unknown_pages' in locals() and unknown_pages:
                    stats_list.insert(0, {"מחלקה": "דפים ללא מחלקה (UNKNOWN)", "עמודים": len(unknown_pages)})
                    
                # מציג את הטבלה רק אם יש נתונים קריאים
                if stats_list:
                    st.table(stats_list)
                else:
                    st.info("לא זוהו מחלקות ספציפיות בדוח.")


        except Exception as e:
            # הצגת שגיאה ברורה למשתמש
            st.error("אירעה שגיאה קריטית במהלך העיבוד. אנא ודא שהקובץ תקין ונסה שוב.")
            # הדפסת השגיאה המלאה לקונסול
            st.exception(e)
