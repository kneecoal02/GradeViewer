from flask import Flask, render_template, request, jsonify
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# --- Google Sheets Config ---
CREDS_FILE = 'google_credentials.json'
GOOGLE_SHEET_NAME = 'Copy of Lampa_ITE 031_2-9'  

SUBJECT_TITLES = {
    "ITE 300": "Object Oriented Programming",
    "ITE 298": "IT Elective 1",        
    "ITE 031": "Data Structures & Algo"  
}

def col_to_index(col_str):
    """Converts an Excel/Sheets column letter (e.g., 'A', 'BG') to a 0-based index."""
    expn = 0
    col_num = 0
    for char in reversed(col_str.upper()):
        col_num += (ord(char) - ord('A') + 1) * (26 ** expn)
        expn += 1
    return col_num - 1

def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scope)
    return gspread.authorize(creds)

def pad_data(data, target_cols=150):
    """Forces spreadsheet data to a specific width so columns don't get truncated by Google API."""
    return [row + [""] * max(0, target_cols - len(row)) for row in data]

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get_grades', methods=['POST'])
def get_grades():
    data = request.get_json()
    
    id_number = str(data.get('accessCode', data.get('idNumber'))).strip()
    section = data.get('section', 'N/A')
    subject = data.get('subject', 'N/A')
    teacher = data.get('teacher', 'N/A')

    try:
        client = get_gsheet_client()
        
        try:
            sheet_doc = client.open(GOOGLE_SHEET_NAME)
            # We ONLY need the Summary Sheet now
            summary_ws = sheet_doc.worksheet("Grading Summary Sheet")
        except gspread.exceptions.WorksheetNotFound as e:
            return jsonify({'success': False, 'message': f'Required tab is missing: {str(e)}'}), 404
        except gspread.exceptions.SpreadsheetNotFound:
            return jsonify({'success': False, 'message': f'Database offline: "{GOOGLE_SHEET_NAME}" not found.'}), 404

        raw_summary = summary_ws.get_all_values()
        if not raw_summary:
             return jsonify({'success': False, 'message': 'Summary worksheet is empty.'}), 404

        df_summary = pd.DataFrame(pad_data(raw_summary, 150))

        # 1. MATCH STUDENT DIRECTLY IN SUMMARY SHEET (Column B / Index 1)
        summary_id_col = df_summary.iloc[:, 1].astype(str).str.strip()
        matching_indices = df_summary.index[summary_id_col == id_number].tolist()

        if not matching_indices:
            return jsonify({'success': False, 'message': f'Access Code {id_number} not found in Summary Sheet. Please verify.'}), 404

        row_idx = matching_indices[0] # Exact row for this student

        # 2. Extract Student Name from Summary Sheet Column C (Index 2)
        val_name = df_summary.iloc[row_idx, 2]
        student_name = "N/A" if pd.isna(val_name) or str(val_name).strip() == "" else str(val_name).strip()

        # 3. Extract All Final Grades (P1=K, P2=S, P3=AB)
        final_grades = []
        for period, col_letter in [('P1', 'K'), ('P2', 'S'), ('P3', 'AB')]:
            val_fg = df_summary.iloc[row_idx, col_to_index(col_letter)]
            if not pd.isna(val_fg) and str(val_fg).strip() != "":
                final_grades.append({'title': f'{period} Grade', 'value': str(val_fg).strip()})

        # 4. Extract Modules & All Check-Ins
        categories_config = [
            {'name': 'Attendance', 'class_type': 'soc', 'columns': ['AD','AE','AF','AG','AH','AI','AJ','AK','AL','AM','AN','AO','AP','AQ']},
            {'name': "Let's Practice", 'class_type': 'practice', 'columns': ['AU','AV','AW','AX','AY','AZ','BA','BB','BC','BD','BE','BF','BG','BH']},
            {'name': 'Reflection', 'class_type': 'reflection', 'columns': ['BL','BM','BN','BO','BP','BQ','BR','BS','BT','BU','BV','BW','BX','BY']},
            {'name': 'Wrap Up', 'class_type': 'wrapup', 'columns': ['CC','CD','CE','CF','CG','CH','CI','CJ','CK','CL','CM','CN','CO','CP']},
            {'name': 'Check-In', 'class_type': 'checkin', 'columns': ['CT', 'CU', 'CV', 'CW']}
        ]
        
        modules_data = []
        for cat in categories_config:
            cat_items = []
            for i, col_letter in enumerate(cat['columns'], start=1):
                col_idx = col_to_index(col_letter)
                val = df_summary.iloc[row_idx, col_idx]
                
                if pd.isna(val) or val is None or str(val).strip() == "":
                    continue
                    
                val_str = str(val).strip()
                if val_str.endswith('.0'):
                    val_str = val_str[:-2]
                    
                # Dynamic Sub-headers
                if cat['name'] == 'Check-In':
                    if col_letter == 'CT': sub_hdr = 'P1'
                    elif col_letter == 'CU': sub_hdr = 'P2'
                    elif col_letter == 'CV': sub_hdr = '3.1'
                    elif col_letter == 'CW': sub_hdr = '3.2'
                    else: sub_hdr = f'Mod {i}'
                else:
                    sub_hdr = f'Mod {i}'
                    
                cat_items.append({
                    'column': col_letter,
                    'sub_header': sub_hdr,
                    'value': val_str
                })
            
            if cat_items:
                modules_data.append({
                    'category_name': cat['name'],
                    'class_type': cat['class_type'],
                    'items': cat_items
                })

        subject_title = SUBJECT_TITLES.get(subject, "Course Module")

        return jsonify({
            'success': True,
            'student_name': student_name,
            'id_number': id_number,
            'section': section,
            'subject_full': f"{subject} - {subject_title}",
            'teacher': teacher,
            'final_grades': final_grades,
            'modules_data': modules_data
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'Server Exception: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True)