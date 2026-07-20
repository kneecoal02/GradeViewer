from flask import Flask, render_template, request, jsonify
import pandas as pd
import os

app = Flask(__name__)

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

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get_grades', methods=['POST'])
def get_grades():
    data = request.get_json()
    id_number = str(data.get('idNumber')).strip()
    section = data.get('section')
    period = data.get('period')
    subject = data.get('subject')
    teacher = data.get('teacher') # Fetch the teacher from request

    sheet_name = f"{subject}({section})"

    if not os.path.exists(EXCEL_FILE):
        return jsonify({'success': False, 'message': 'Database offline: Grades.xlsx not found.'}), 404

    try:
        df = pd.read_excel(EXCEL_FILE, sheet_name=sheet_name)
        
        # Column A (index 0) is the Student Number
        student_id_col = df.iloc[:, 0].astype(str).str.strip()
        student_row = df[student_id_col == id_number]

        if student_row.empty:
            return jsonify({'success': False, 'message': f'ID {id_number} not found in {section}. Please verify.'}), 404

        if period == 'P1':
            categories_config = [
                {
                    'name': 'SOC 1 & 2',
                    'class_type': 'soc',
                    'columns': ['C','D','E','F','G','H','I','J','K','L','M','N','O','P']
                },
                {
                    'name': "Let's Practice",
                    'class_type': 'practice',
                    'columns': ['Q','R','S','T','U','V','W','X','Y','Z','AA','AB','AC','AD']
                },
                {
                    'name': 'Reflection',
                    'class_type': 'reflection',
                    'columns': ['AE','AF','AG','AH','AI','AJ','AK','AL','AM','AN','AO','AP','AQ','AR']
                },
                {
                    'name': 'Wrap Up Quiz',
                    'class_type': 'wrapup',
                    'columns': ['AS','AT','AU','AV','AW','AX','AY','AZ','BA','BB','BC','BD','BE','BF']
                }
            ]

            # Extract Student Name (Col B)
            student_name = "N/A"
            b_idx = col_to_index('B')
            if b_idx < len(df.columns):
                val = student_row.iloc[0, b_idx]
                student_name = "N/A" if pd.isna(val) or str(val).strip() == "" else str(val)
            
            # Extract P1 Final Grade (Col BG)
            final_grade = "N/A"
            bg_idx = col_to_index('BG')
            if bg_idx < len(df.columns):
                val = student_row.iloc[0, bg_idx]
                if isinstance(val, float) and val.is_integer():
                    val = int(val)
                final_grade = "N/A" if pd.isna(val) or str(val).strip() == "" else str(val)

            # Process Modules
            modules_data = []
            for cat in categories_config:
                cat_items = []
                for i, col_letter in enumerate(cat['columns'], start=1):
                    col_idx = col_to_index(col_letter)
                    if col_idx < len(df.columns):
                        val = student_row.iloc[0, col_idx]
                        
                        if pd.isna(val) or str(val).strip() == "":
                            continue
                        
                        if isinstance(val, float) and val.is_integer():
                            val = int(val)
                        val = str(val)
                        
                        cat_items.append({
                            'column': col_letter,
                            'sub_header': f'Mod {i}',
                            'value': val
                        })
                
                if cat_items:
                    modules_data.append({
                        'category_name': cat['name'],
                        'class_type': cat['class_type'],
                        'items': cat_items
                    })

            # Get the full descriptive title
            subject_title = SUBJECT_TITLES.get(subject, "Course Module")

            return jsonify({
                'success': True,
                'period': period,
                'student_name': student_name,
                'id_number': id_number,
                'section': section,
                'subject_full': f"{subject} - {subject_title}",
                'teacher': teacher,
                'final_grade': final_grade,
                'modules_data': modules_data
            })
        
        elif period in ['P2', 'P3']:
            return jsonify({'success': False, 'message': f'Grade matrix for {period} is currently locked.'}), 400

    except ValueError:
        return jsonify({'success': False, 'message': f'Course section "{sheet_name}" does not exist in the registry.'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'Server Exception: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True)