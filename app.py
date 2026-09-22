import pandas as pd
from flask import Flask, render_template, request, jsonify

# --- RATE LIMITER IMPORTS ---
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# --- GOOGLE SHEETS IMPORTS ---
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 

# ==========================================
# ROUTE-ONLY RATE LIMITER SETUP
# ==========================================
# setting default_limits=[] ensures NO global limits are applied
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://"
)

# Custom JSON response when a user hits a rate limit
@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        'success': False, 
        'message': f'Too many requests. Please wait a moment and try again. ({e.description})'
    }), 429

# ==========================================
# GOOGLE SHEETS SETUP
# ==========================================
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

try:
    CREDS = ServiceAccountCredentials.from_json_keyfile_name('google_credentials.json', SCOPE)
    GSPREAD_CLIENT = gspread.authorize(CREDS)
    print("Successfully connected to Google APIs!")
except Exception as e:
    print(f"Warning: Failed to load credentials.json. Google Sheets won't work. Error: {e}")
    GSPREAD_CLIENT = None


# ==========================================
# CONSTANTS & HELPERS
# ==========================================
SUBJECT_TITLES = {
    "ITE 300": "Object Oriented Programming",
    "ITE 298": "IT Elective 1",        
    "ITE 031": "Data Structures & Algo"  
}

def col_to_index(col_str):
    """Converts an Excel column letter (e.g., 'A', 'DC') to a 0-based index."""
    expn = 0
    col_num = 0
    for char in reversed(col_str.upper()):
        col_num += (ord(char) - ord('A') + 1) * (26 ** expn)
        expn += 1
    return col_num - 1

# ==========================================
# ROUTES
# ==========================================

@app.route('/')
def home():
    # Unlimited: Standard users loading the page will never be blocked
    return render_template('index.html')


@app.route('/get_grades', methods=['POST'])
@limiter.limit("10 per minute")  # Protects Google API quotas and prevents spam
def get_grades():
    data = request.get_json()
    access_code = str(data.get('accessCode')).strip()
    section = data.get('section')  # e.g., "BSIT2-4"
    subject = data.get('subject')  # e.g., "ITE 031" or "ITE 300"

    if GSPREAD_CLIENT is None:
        return jsonify({'success': False, 'message': 'Database offline: Google Credentials missing.'}), 500

    # 1. Construct the Google Sheet File Name dynamically
    if subject == "ITE 300":
        # Target format: Copy of Parel_OOP_F1-BSIT2-8
        target_filename = f"Copy of Parel_OOP_F1-{section}"
    else:
        # Original format for all other subjects (e.g. Copy of Lampa_ITE 031_2-4)
        section_suffix = section.replace("BSIT", "")
        target_filename = f"Copy of Lampa_{subject}_{section_suffix}"

    try:
        # 2. Open the specific Google Sheet by name
        spreadsheet = GSPREAD_CLIENT.open(target_filename)
        
        # Explicitly get the "Grading Summary Sheet" tab
        try:
            worksheet = spreadsheet.worksheet("Grading Summary Sheet")
        except gspread.exceptions.WorksheetNotFound:
            return jsonify({'success': False, 'message': f'Access code not found in {section} {subject}'}), 404
        
        # 3. Pull all data and convert to pandas DataFrame
        data_records = worksheet.get_all_values()
        df = pd.DataFrame(data_records)
        
        # Safely clean up empty strings
        df.replace("", float("NaN"), inplace=True)

        # Column B (index 1) is the Unique Access Code (case-insensitive check)
        user_code = access_code.lower()
        access_code_col = df.iloc[:, 1].astype(str).str.strip().str.lower()
        student_row = df[access_code_col == user_code]

        if student_row.empty:
            return jsonify({'success': False, 'message': f'Access code not found in {section} {subject}'}), 404

        # Full column mapping
        categories_config = [
            {
                'name': 'Attendance',
                'class_type': 'soc',
                'columns': ['AD','AE','AF','AG','AH','AI','AJ','AK','AL','AM','AN','AO','AP','AQ']
            },
            {
                'name': "Let's Practice",
                'class_type': 'practice',
                'columns': ['AU','AV','AW','AX','AY','AZ','BA','BB','BC','BD','BE','BF','BG','BH']
            },
            {
                'name': 'Reflection',
                'class_type': 'reflection',
                'columns': ['BL','BM','BN','BO','BP','BQ','BR','BS','BT','BU','BV','BW','BX','BY']
            },
            {
                'name': 'Wrap Up',
                'class_type': 'wrapup',
                'columns': ['CC','CD','CE','CF','CG','CH','CI','CJ','CK','CL','CM','CN','CO','CP']
            },
            {
                'name': 'Check-in Grades',
                'class_type': 'assessments',
                'columns': ['CT', 'CU', 'CV', 'CW'],
                'headers': ['P1 Check-in', 'P2 Check-in', 'P3.1 Check-in', 'P3.2 Check-in']
            }
        ]

        # Extract Student Name (Col C / Index 2)
        student_name = "N/A"
        c_idx = col_to_index('C')
        if c_idx < len(df.columns):
            val = student_row.iloc[0, c_idx]
            student_name = "N/A" if pd.isna(val) or str(val).strip() == "" else str(val)
        
        # Extract Available Modules
        modules_data = []
        for cat in categories_config:
            cat_items = []
            for i, col_letter in enumerate(cat['columns']):
                col_idx = col_to_index(col_letter)
                if col_idx < len(df.columns):
                    val = student_row.iloc[0, col_idx]
                    
                    if pd.isna(val) or str(val).strip() == "":
                        continue
                    
                    # Safely attempt to convert string to a number for rounding
                    try:
                        num_val = float(val)
                        is_number = True
                    except (ValueError, TypeError):
                        is_number = False

                    if cat['class_type'] == 'wrapup':
                        if is_number:
                            val = str(round((num_val * 7) / 100))
                        else:
                            val = str(val)
                    else:
                        if is_number:
                            if num_val.is_integer():
                                val = str(int(num_val))
                            else:
                                val = str(round(num_val, 2))
                        else:
                            val = str(val)
                    
                    if 'headers' in cat:
                        sub_header = cat['headers'][i]
                    else:
                        sub_header = f'Mod {i+1}'

                    cat_items.append({
                        'column': col_letter,
                        'sub_header': sub_header,
                        'value': val
                    })
            
            if cat_items:
                modules_data.append({
                    'category_name': cat['name'],
                    'class_type': cat['class_type'],
                    'items': cat_items
                })

        # Extract Final Grades (DC: P1 Grade, DD: P2 Grade, DE: P3 Grade)
        final_grades = []
        for col_letter, title in [('DC', 'P1 Grade'), ('DD', 'P2 Grade'), ('DE', 'P3 Grade')]:
            idx = col_to_index(col_letter)
            if idx < len(df.columns):
                val = student_row.iloc[0, idx]
                if not pd.isna(val) and str(val).strip() != "":
                    # Safely convert final grades
                    try:
                        num_val = float(val)
                        if num_val.is_integer():
                            val_str = str(int(num_val))
                        else:
                            val_str = str(round(num_val, 2))
                    except (ValueError, TypeError):
                        val_str = str(val)

                    final_grades.append({
                        'title': title,
                        'value': val_str
                    })

        subject_title = SUBJECT_TITLES.get(subject, "Course Module")

        return jsonify({
            'success': True,
            'student_name': student_name,
            'section': section,
            'subject_full': f"{subject} - {subject_title}",
            'final_grades': final_grades,
            'modules_data': modules_data
        })

    except gspread.exceptions.SpreadsheetNotFound:
        return jsonify({'success': False, 'message': f'Access code not found in {section} {subject}'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'Server Exception: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True)