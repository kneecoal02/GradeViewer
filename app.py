import os
import pandas as pd
from flask import Flask, render_template, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

# 1. Load variables from .env file
load_dotenv()

app = Flask(__name__)

# 2. Initialize Rate Limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"], # Global default limit
    storage_uri="memory://" # Uses in-memory storage (simple & fast)
)

# 3. Custom 429 Error Handler so your frontend JS toast handles it gracefully
@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify(
        success=False, 
        message=f"Rate limit exceeded: {e.description}. Please slow down!"
    ), 429


# ==========================================
# CONSTANTS & HELPERS
# ==========================================
EXCEL_FILE = 'Grades.xlsx'

# Dictionary mapping subject codes to their descriptive titles
SUBJECT_TITLES = {
    "ITE 300": "Object Oriented Programming",
    "ITE 298": "IT Elective 1",        
    "ITE 031": "Data Structures & Algo"  
}

def col_to_index(col_str):
    """Converts an Excel column letter (e.g., 'A', 'BG') to a 0-based index."""
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
    return render_template('index.html')


# --- SECURE ADMIN LOGIN ---
@app.route('/admin_login', methods=['POST'])
@limiter.limit("5 per minute") # Prevents brute-force password guessing
def admin_login():
    data = request.get_json()
    username_attempt = data.get('username')
    password_attempt = data.get('password')

    # Read the correct credentials from the .env file
    correct_username = os.getenv('ADMIN_USERNAME')
    correct_password = os.getenv('ADMIN_PASSWORD')

    if username_attempt == correct_username and password_attempt == correct_password:
        return jsonify(success=True, message="Login successful")
    else:
        return jsonify(success=False, message="Invalid username or password"), 401


# --- GET GRADES ROUTE ---
@app.route('/get_grades', methods=['POST'])
@limiter.limit("5 per minute") # Max 5 attempts per minute per IP
def get_grades():
    data = request.get_json()
    access_code = str(data.get('accessCode')).strip()
    section = data.get('section')
    subject = data.get('subject')

    sheet_name = f"{subject}({section})"

    if not os.path.exists(EXCEL_FILE):
        return jsonify({'success': False, 'message': 'Database offline: Grades.xlsx not found.'}), 404

    try:
        df = pd.read_excel(EXCEL_FILE, sheet_name=sheet_name)
        
        # Column B (index 1) is the Unique Access Code
        access_code_col = df.iloc[:, 1].astype(str).str.strip()
        student_row = df[access_code_col == access_code]

        if student_row.empty:
            return jsonify({'success': False, 'message': f'Access code not found in {section}. Please verify.'}), 404

        # Full column mapping including the newly added check-ins
        categories_config = [
            {
                'name': 'SOC 1 & 2',
                'class_type': 'soc',
                'columns': ['D','E','F','G','H','I','J','K','L','M','N','O','P','Q']
            },
            {
                'name': "Let's Practice",
                'class_type': 'practice',
                'columns': ['R','S','T','U','V','W','X','Y','Z','AA','AB','AC','AD','AE']
            },
            {
                'name': 'Reflection',
                'class_type': 'reflection',
                'columns': ['AF','AG','AH','AI','AJ','AK','AL','AM','AN','AO','AP','AQ','AR','AS']
            },
            {
                'name': 'Wrap Up Quiz',
                'class_type': 'wrapup',
                'columns': ['AT','AU','AV','AW','AX','AY','AZ','BA','BB','BC','BD','BE','BF','BG']
            },
            {
                'name': 'Assessments & Outputs',
                'class_type': 'assessments',
                'columns': ['BH', 'BI', 'BJ', 'BK', 'BL', 'BM', 'BN'],
                'headers': ['P1 Check-in', 'P2 Check-in', 'P3.1 Check-in', 'P3.2 Check-in', 'Check-in Avg', 'Final Output', 'Overall Grade']
            }
        ]

        # Extract Student Name (Col C / Index 2)
        student_name = "N/A"
        c_idx = col_to_index('C')
        if c_idx < len(df.columns):
            val = student_row.iloc[0, c_idx]
            student_name = "N/A" if pd.isna(val) or str(val).strip() == "" else str(val)
        
        # Extract Available Modules & Check-ins dynamically
        modules_data = []
        for cat in categories_config:
            cat_items = []
            for i, col_letter in enumerate(cat['columns']):
                col_idx = col_to_index(col_letter)
                if col_idx < len(df.columns):
                    val = student_row.iloc[0, col_idx]
                    
                    # If empty or NaN, skip it entirely
                    if pd.isna(val) or str(val).strip() == "":
                        continue
                    
                    # Special logic for Wrap Up Quiz to convert percentage to raw score out of 7
                    if cat['class_type'] == 'wrapup':
                        try:
                            numeric_val = float(val)
                            val = str(round((numeric_val * 7) / 100))
                        except ValueError:
                            val = str(val)
                    else:
                        # Clean up floats (round decimals to 2 places to handle calculated averages neatly)
                        if isinstance(val, float):
                            if val.is_integer():
                                val = int(val)
                            else:
                                val = round(val, 2)
                        val = str(val)
                    
                    # Use custom headers if provided (for check-ins), otherwise use "Mod X"
                    if 'headers' in cat:
                        sub_header = cat['headers'][i]
                    else:
                        sub_header = f'Mod {i+1}'

                    cat_items.append({
                        'column': col_letter,
                        'sub_header': sub_header,
                        'value': val
                    })
            
            # Only add category if there are modules with values
            if cat_items:
                modules_data.append({
                    'category_name': cat['name'],
                    'class_type': cat['class_type'],
                    'items': cat_items
                })

        # Extract Final Grades (Shifted to BO, BP, BQ)
        final_grades = []
        for col_letter, title in [('BO', 'P1 Grade'), ('BP', 'P2 Grade'), ('BQ', 'Final Grade')]:
            idx = col_to_index(col_letter)
            if idx < len(df.columns):
                val = student_row.iloc[0, idx]
                if not pd.isna(val) and str(val).strip() != "":
                    if isinstance(val, float):
                        if val.is_integer():
                            val = int(val)
                        else:
                            val = round(val, 2)
                    final_grades.append({
                        'title': title,
                        'value': str(val)
                    })

        # Get full descriptive title
        subject_title = SUBJECT_TITLES.get(subject, "Course Module")

        return jsonify({
            'success': True,
            'student_name': student_name,
            'section': section,
            'subject_full': f"{subject} - {subject_title}",
            'final_grades': final_grades,
            'modules_data': modules_data
        })

    except ValueError:
        return jsonify({'success': False, 'message': f'Course section "{sheet_name}" does not exist in the registry.'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'Server Exception: {str(e)}'}), 500


# --- EXCEL UPLOAD ROUTE ---
@app.route('/upload_excel', methods=['POST'])
@limiter.limit("3 per minute") # Max 3 uploads per minute per IP
def upload_excel():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file part in the request.'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected for uploading.'}), 400
        
    if file and file.filename.endswith('.xlsx'):
        try:
            file.save(EXCEL_FILE)
            return jsonify({'success': True, 'message': 'Database updated: Grades.xlsx saved successfully.'})
        except Exception as e:
            return jsonify({'success': False, 'message': f'Failed to save file: {str(e)}'}), 500
    else:
        return jsonify({'success': False, 'message': 'Invalid file format. Please upload an .xlsx file.'}), 400

if __name__ == '__main__':
    app.run(debug=True)