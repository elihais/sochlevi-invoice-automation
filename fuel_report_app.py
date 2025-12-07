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

# --- לוגיקה עסקית: חילוץ נתונים כלליים ---

def extract_metadata(pdf_bytes):
    """
    מחלץ מספר לקוח, מספר דו"ח ותאריך (חודש ושנה) כללי מהעמוד הראשון.
    """
    input_stream = io.BytesIO(pdf_bytes)
    
    with pdfplumber.open(input_stream) as pdf:
        if not pdf.pages:
            return "99999", "0000", "00-0000"
        
        first_page_text = pdf.pages[0].extract_text()
        
        # 1. מספר לקוח (Customer ID) - מחפש: לקוח : [5 ספרות ומעלה]
        customer_id_match = re.search(r'לקוח\s*:\s*(\d+)', first_page_text)
        customer_id = customer_id_match.group(1) if customer_id_match else "99999" 
        
        # 2. מספר דו"ח (Invoice Number) - מחפש: מס' דו"ח : [4 ספרות ומעלה]
        invoice_num_match = re.search(r'מס\' דו"ח\s*:\s*(\d+)', first_page_text)
        invoice_num = invoice_num_match.group(1) if invoice_num_match else "0000" 
        
        # 3. חודש ושנה (Month and Year from the report date) - מחפש תאריך בפורמט DD/MM/YYYY
        date_match = re.search(r'תאריך הפקת דו"ח\s*:\s*(\d{1,2})/(\d{1,2})/(\d{4})', first_page_text)
        
        if date_match:
            month = date_match.group(2)
            year = date_match.group(3)
            date_str = f"{month}-{year}"
        else:
            date_str = "00-0000"
            
        return customer_id, invoice_num, date_str, first_page_text

def extract_department_id(text):
    """מחלץ מספר מחלקה (5 ספרות) מתוך טקסט"""
    if not text:
        return None
    
    # חיפוש תבנית: 5 ספרות ליד המילה מחלקה או הפוך
    # דוגמא: "30063 : מחלקה" או "מחלקה : 30063"
    match = re.search(r'(\d{5})\s*[:]?\s*מחלקה', text)
    if not match:
        match = re.search(r'מחלקה\s*[:]?\s*(\d{5})', text)
    
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

            text = page.extract_text()
            dept_id = extract_department_id(text)
            
            # לוגיקת שיוך מחלקה (Carry-Forward)
            if dept_id:
                # אם נמצאה מחלקה חדשה, היא הופכת להיות הנוכחית
                current_dept = dept_id
            # אם לא נמצאה מחלקה, נשארים עם הקודמת (או UNKNOWN)
            
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
    # קוראים את הקובץ לזיכרון פעם אחת
    pdf_bytes = uploaded_file.getvalue()
    st.info(f"הקובץ הועלה בהצלחה: **{uploaded_file.name}**")
    
    if st.button("התחל עיבוד 🚀", key="process_button"):
        try:
            # 1. חילוץ מטא-דאטה ראשונית
            customer_id, invoice_num, date_str, first_page_text = extract_metadata(pdf_bytes)

            if customer_id == "99999" or invoice_num == "0000":
                st.warning("שים לב: לא ניתן היה לחלץ באופן מלא את מספר הלקוח או מספר הדו״ח מהעמוד הראשון. שם הקובץ יכלול ערכי ברירת מחדל.")
            
            with st.spinner('מבצע פיצול וניתוח... נא להמתין'):
                dept_map = process_pdf(pdf_bytes)
            
            # 2. בדיקה אם זוהו מחלקות
            if not dept_map:
                st.warning("לא נמצאו דפים לעיבוד. ודא שהקובץ אינו ריק או מוגן בסיסמה.")
            else:
                # 3. אם נמצאו מחלקות, ממשיכים בלוגיקת יצירת ה-ZIP וההורדה
                st.success(f"העיבוד הסתיים! זוהו {len(dept_map)} קבצים מפוצלים.")
                
                # יצירת קובץ ZIP בזיכרון
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                    total_pages_processed = 0
                    
                    # הוספת קובץ דוח מרכז אם זוהה UNKNOWN
                    if "UNKNOWN" in dept_map:
                        st.info("נמצאו דפים ללא מספר מחלקה שקובצו תחת השם 'דפים_ללא_מחלקה'.")
                        # נשמור אותם תחת שם מיוחד
                        unknown_pages = dept_map.pop("UNKNOWN")
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
                    label="📥 הורד את כל הקבצים (ZIP)",
                    data=zip_buffer.getvalue(),
                    file_name=f"מפוצל_{customer_id}_{date_str}_{invoice_num}.zip",
                    mime="application/zip"
                )
                
                # הצגת סטטיסטיקה
                st.divider()
                st.subheader("📊 סיכום דפים לפי מחלקה:")
                st.markdown(f"**סה״כ עמודים שעובדו:** {total_pages_processed}")
                
                stats_list = [{"מחלקה": k, "עמודים": len(v)} for k, v in dept_map.items()]
                
                # אם היו דפים ללא מחלקה (Unknown), נוסיף אותם לטבלה
                if 'unknown_pages' in locals():
                    stats_list.insert(0, {"מחלקה": "דפים ללא מחלקה", "עמודים": len(unknown_pages)})
                    
                st.table(stats_list)

        except Exception as e:
            # הצגת שגיאה ברורה למשתמש
            st.error("אירעה שגיאה קריטית במהלך העיבוד. אנא ודא שהקובץ תקין ונסה שוב.")
            # הדפסת השגיאה המלאה לקונסול
            st.exception(e)
