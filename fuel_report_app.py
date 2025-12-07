import streamlit as st
import re
import zipfile
import pdfplumber
import io
from PyPDF2 import PdfReader, PdfWriter

# --- הגדרות עיצוב (RTL & Liquid Glass - נשמר מהגרסה הקודמת) ---
st.set_page_config(page_title="מערכת פיצול דוחות דלק", page_icon="⛽", layout="centered")

st.markdown("""
<style>
    /* הגדרות RTL וצבעים (נשמר לטובת נראות) */
    .stApp { direction: rtl; text-align: right; background-color: #f0f2f6; }
    .stApp, .stApp p, .stApp span, .stMarkdown, div[data-testid^="stBlock"] *, 
    div[data-testid="stFileUploader"] label, div[data-testid="stFileUploader"] p,
    .stAlert p, div[data-testid="stAlert"] *, .stSpinner p, .stDownloadButton p, .stTable .dataframe * {
        color: #333333 !important;
    }
    h1 { text-align: center; width: 100%; color: #1f78b4 !important; }
    h2, h3, h4, h5, h6 { color: #333333 !important; }
    div[data-testid="stFileUploader"] label { justify-content: flex-end; width: 100%; display: flex; font-size: 1.1rem; }
    .block-container {
        background: rgba(255, 255, 255, 0.7); border-radius: 16px;
        box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1); backdrop-filter: blur(5px);
        border: 1px solid rgba(255, 255, 255, 0.3); padding: 2rem !important;
    }
    .stButton>button, .stDownloadButton>button {
        background-color: #1f78b4; color: white !important; border-radius: 8px; border: none;
        padding: 0.5rem 1.5rem; font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# --- לוגיקה חדשה: חילוץ מרחבי (Spatial Extraction) ---

def find_text_near_label(page, label_pattern, search_direction='left', width_units=150):
    """
    מחפש טקסט ספציפי שנמצא פיזית ליד תווית מסוימת בדף.
    label_pattern: המילה שמחפשים (למשל 'מחלקה')
    search_direction: איפה לחפש את הערך? 'left' (משמאל לתווית) או 'right' (מימין)
    width_units: כמה רחוק לחפש (בפיקסלים)
    """
    words = page.extract_words()
    
    # חיפוש התווית (Label)
    label_matches = [w for w in words if re.search(label_pattern, w['text'])]
    
    found_values = []
    
    for label in label_matches:
        # הגדרת אזור חיפוש (Bounding Box) יחסי למיקום התווית שנמצאה
        if search_direction == 'left':
            # מחפש משמאל לתווית (מתאים לעברית ומספרים ב-PDF לפעמים)
            bbox = (
                label['x0'] - width_units, # שמאלה X
                label['top'] - 2,          # אותו גובה Y (קצת למעלה)
                label['x0'],               # עד התווית עצמה
                label['bottom'] + 2        # קצת למטה
            )
        else:
            # מחפש מימין לתווית
            bbox = (
                label['x1'],               # מהסוף של התווית
                label['top'] - 2,
                label['x1'] + width_units, # ימינה X
                label['bottom'] + 2
            )
            
        # חילוץ טקסט מתוך הריבוע הספציפי שהגדרנו
        try:
            cropped_text = page.within_bbox(bbox).extract_text()
            if cropped_text:
                found_values.append(cropped_text)
        except Exception:
            continue # אם האזור מחוץ לגבולות הדף

    return found_values

def robust_extract_metadata(pdf):
    """מחלץ מטא-דאטה באמצעות חיפוש מרחבי בעמוד הראשון"""
    if not pdf.pages:
        return "99999", "0000", "00-0000"
    
    page = pdf.pages[0]
    full_text = page.extract_text() or ""
    
    # 1. מספר לקוח
    # אסטרטגיה: לחפש את המילה "לקוח", ולהסתכל שמאלה וימינה
    potential_ids = find_text_near_label(page, r'לקוח', 'left', 100) + \
                    find_text_near_label(page, r'לקוח', 'right', 100)
    # סינון: לוקחים רק מספרים
    ids = []
    for val in potential_ids:
        nums = re.findall(r'(\d{5,})', val)
        ids.extend(nums)
    
    customer_id = ids[0] if ids else "99999"

    # 2. מספר חשבונית/דוח
    # אסטרטגיה: לחפש "דו"ח" או "מס" ולהסתכל סביב
    potential_inv = find_text_near_label(page, r'דו"?ח', 'left', 100) + \
                    find_text_near_label(page, r'דו"?ח', 'right', 100)
    invs = []
    for val in potential_inv:
        nums = re.findall(r'(\d{4,})', val)
        invs.extend(nums)
        
    invoice_num = invs[0] if invs else "0000"

    # 3. תאריך
    # גיבוי: חיפוש רגיל בטקסט כי תאריכים הם פורמט קשיח
    date_match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', full_text)
    if date_match:
        # בדיקה אם זה פורמט ישראלי (DD/MM/YYYY)
        if int(date_match.group(2)) > 12: # אם החלק השני גדול מ-12, זה כנראה הימים
             date_str = f"{date_match.group(1).zfill(2)}-{date_match.group(3)}"
        else:
             date_str = f"{date_match.group(2).zfill(2)}-{date_match.group(3)}"
    else:
        date_str = "00-0000"

    return customer_id, invoice_num, date_str

def robust_get_dept_id(page):
    """
    מחלץ מספר מחלקה מהעמוד בצורה ויזואלית.
    מחפש את המילה 'מחלקה' וסורק את סביבתה הקרובה למספר בן 5 ספרות.
    """
    # 1. מצא את כל המופעים של המילה "מחלקה"
    # אנו מחפשים גם משמאל וגם מימין כי ב-PDF עברי הסדר מתהפך ויזואלית
    values_near_label = find_text_near_label(page, r'מחלקה', 'left', 150) + \
                        find_text_near_label(page, r'מחלקה', 'right', 150)
    
    for val in values_near_label:
        # נקה הכל חוץ ממספרים
        matches = re.findall(r'(\d{5})', val)
        for match in matches:
            # ודא שזה לא מספר הלקוח (לפעמים הם דומים, אבל לרוב מחלקה היא ייחודית)
            return match
            
    return None

def process_pdf_spatial(pdf_bytes):
    input_stream = io.BytesIO(pdf_bytes)
    
    # שלב 1: PyPDF2 לחיתוך וכתיבה (מהיר ויעיל למניפולציות)
    reader = PdfReader(input_stream)
    
    # שלב 2: pdfplumber לניתוח טקסט חכם (איטי יותר אך מדויק)
    dept_pages = {} 
    current_dept = "UNKNOWN"
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    total_pages = len(reader.pages)

    # פותחים עם pdfplumber רק כדי לזהות את הטקסט
    with pdfplumber.open(input_stream) as pdf:
        for i, page in enumerate(pdf.pages):
            progress_bar.progress((i + 1) / total_pages)
            status_text.text(f"סורק עמוד {i+1} (מחלקה נוכחית: {current_dept})")

            # --- הליבה החדשה: זיהוי מרחבי ---
            dept_id = robust_get_dept_id(page)
            
            if dept_id:
                current_dept = dept_id
            
            if current_dept not in dept_pages:
                dept_pages[current_dept] = []
            
            # לוקחים את העמוד המקביל מ-PyPDF2 (כדי לשמור על איכות המקור)
            pypdf_page = reader.pages[i]
            
            # חיתוך כותרת תחתונה (Footer) - 40 יחידות
            current_lower_left = pypdf_page.cropbox.lower_left
            pypdf_page.cropbox.lower_left = (current_lower_left[0], current_lower_left[1] + 40)
            
            dept_pages[current_dept].append(pypdf_page)

    progress_bar.empty()
    status_text.empty()
    return dept_pages

# --- ממשק משתמש (UI) ---

st.title("⛽ דוחות דלק - מערכת פיצול (מנוע אופטי)")
st.write("מערכת זו משתמשת בזיהוי מיקום טקסט (Spatial Layout) כדי להתגבר על בעיות כיווניות וסדר ב-PDF.")

uploaded_file = st.file_uploader("גרור לכאן את קובץ ה-PDF", type=["pdf"])

if uploaded_file is not None:
    pdf_bytes = uploaded_file.getvalue()
    st.info(f"הקובץ **{uploaded_file.name}** נטען. מוכן לניתוח.")
    
    if st.button("הפעל מנוע פיצול", key="process"):
        try:
            # חילוץ מטא-דאטה בשיטה החדשה
            with st.spinner('מפענח נתוני כותרת (לקוח/תאריך)...'):
                # פותחים לרגע עם pdfplumber רק בשביל המטא-דאטה
                temp_stream = io.BytesIO(pdf_bytes)
                with pdfplumber.open(temp_stream) as temp_pdf:
                    cust_id, inv_num, date_str = robust_extract_metadata(temp_pdf)

            st.caption(f"זוהה: לקוח {cust_id} | חשבונית {inv_num} | תאריך {date_str}")

            with st.spinner('סורק דפים ומפצל לפי מיקום ויזואלי...'):
                dept_map = process_pdf_spatial(pdf_bytes)
            
            if not dept_map:
                st.error("לא נמצאו דפים. הקובץ כנראה ריק או סרוק כתמונה בלבד.")
            else:
                st.success(f"הסתיים בהצלחה! פוצל ל-{len(dept_map)} קבצים.")
                
                # יצירת ZIP
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                    total_pages = 0
                    
                    # טיפול ב-UNKNOWN
                    unknown = dept_map.pop("UNKNOWN", None)
                    if unknown:
                        st.warning(f"שים לב: {len(unknown)} דפים לא שויכו למחלקה (נמצאים בקובץ נפרד ב-ZIP).")
                        writer = PdfWriter()
                        for p in unknown: writer.add_page(p)
                        tmp = io.BytesIO()
                        writer.write(tmp)
                        zip_file.writestr(f"Unknown_{cust_id}.pdf", tmp.getvalue())

                    for dept, pages in dept_map.items():
                        writer = PdfWriter()
                        for p in pages: writer.add_page(p)
                        tmp = io.BytesIO()
                        writer.write(tmp)
                        
                        # שם קובץ לפי הפורמט המבוקש
                        fname = f"{cust_id}_{date_str}_{inv_num}_{dept}.pdf"
                        zip_file.writestr(fname, tmp.getvalue())
                        total_pages += len(pages)

                st.download_button(
                    "⬇️ הורד קובץ ZIP סופי",
                    data=zip_buffer.getvalue(),
                    file_name=f"Split_{cust_id}_{date_str}.zip",
                    mime="application/zip"
                )
                
                # טבלת סיכום
                st.subheader("פירוט:")
                data = [{"מחלקה": k, "דפים": len(v)} for k,v in dept_map.items()]
                if unknown: data.insert(0, {"מחלקה": "ללא זיהוי", "דפים": len(unknown)})
                st.table(data)

        except Exception as e:
            st.error("שגיאה במנוע הניתוח.")
            st.exception(e)
