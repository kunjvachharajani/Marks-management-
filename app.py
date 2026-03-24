from flask import Flask, request, jsonify, render_template, session
from supabase_client import supabase
import functools
import os

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), 'templates'))
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'marks_mgmt_secret_key_2024')


# ══════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════

def calc_grade(marks):
    if   marks >= 90: return 'A'
    elif marks >= 75: return 'B'
    elif marks >= 50: return 'C'
    elif marks >= 35: return 'D'
    else:             return 'F'


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({"ok": False, "error": "Not logged in"}), 401
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({"ok": False, "error": "Not logged in"}), 401
        if session.get('role') != 'admin':
            return jsonify({"ok": False, "error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════
#  PAGE ROUTES
# ══════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/register')
def register_page():
    return render_template('register.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return render_template('login.html')
    return render_template('admin_dashboard.html')

@app.route('/student/dashboard')
def student_dashboard():
    if not session.get('logged_in') or session.get('role') != 'student':
        return render_template('login.html')
    return render_template('student_dashboard.html')


# ══════════════════════════════════════════════════════
#  AUTH ROUTES
# ══════════════════════════════════════════════════════

@app.route('/api/register', methods=['POST'])
def register():
    data     = request.get_json()
    email    = data.get('email', '').strip()
    password = data.get('password', '')
    role     = data.get('role', 'student')
    name     = data.get('name', '').strip()

    if not email.endswith('@gmail.com'):
        return jsonify({"ok": False, "error": "Email must end with @gmail.com"})
    if len(password) < 6:
        return jsonify({"ok": False, "error": "Password must be at least 6 characters"})
    if role not in ('admin', 'student'):
        return jsonify({"ok": False, "error": "Invalid role"})
    if not name:
        return jsonify({"ok": False, "error": "Full name is required"})

    try:
        auth_response = supabase.auth.sign_up({
            "email": email,
            "password": password
        })
        user_id = auth_response.user.id

        supabase.table('profiles').insert({
            "id":    user_id,
            "email": email,
            "role":  role,
            "name":  name
        }).execute()

        return jsonify({"ok": True, "message": "Account created successfully"})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/login', methods=['POST'])
def login():
    data     = request.get_json()
    email    = data.get('email', '').strip()
    password = data.get('password', '')

    try:
        auth_response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        user_id = auth_response.user.id

        profile = supabase.table('profiles').select('role, name').eq('id', user_id).single().execute()
        role    = profile.data['role']
        name    = profile.data.get('name', email.split('@')[0])

        session['logged_in']      = True
        session['email']          = email
        session['role']           = role
        session['user_id']        = user_id
        session['name']           = name
        session['supabase_token'] = auth_response.session.access_token

        redirect_url = '/admin/dashboard' if role == 'admin' else '/student/dashboard'
        return jsonify({"ok": True, "redirect": redirect_url})

    except Exception as e:
        return jsonify({"ok": False, "error": "Invalid email or password"})


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route('/api/me')
@login_required
def me():
    return jsonify({
        "email": session.get('email'),
        "name":  session.get('name'),
        "role":  session.get('role')
    })


# ══════════════════════════════════════════════════════
#  ADMIN — STUDENT ACCOUNTS
# ══════════════════════════════════════════════════════

@app.route('/api/student_accounts')
@admin_required
def student_accounts():
    """Return all registered student user accounts so admin can pick who to add marks for."""
    try:
        result   = supabase.table('profiles').select('id, name, email').eq('role', 'student').execute()
        return jsonify({"ok": True, "students": result.data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ══════════════════════════════════════════════════════
#  ADMIN — MARKS OPERATIONS
# ══════════════════════════════════════════════════════

@app.route('/api/students')
@admin_required
def get_students():
    """Return all mark entries — full rows including subject, grade, and student name from profiles."""
    try:
        result = supabase.table('students') \
            .select('id, user_id, marks, grade, subject') \
            .order('marks', desc=True) \
            .execute()

        if not result.data:
            return jsonify({"ok": True, "students": []})

        # Get names from profiles
        user_ids = list({row['user_id'] for row in result.data})
        profiles = supabase.table('profiles').select('id, name, email').in_('id', user_ids).execute()
        profile_map = {p['id']: p for p in profiles.data}

        enriched = []
        for row in result.data:
            profile = profile_map.get(row['user_id'], {})
            enriched.append({
                "id":      row['id'],
                "user_id": row['user_id'],
                "name":    profile.get('name', profile.get('email', 'Unknown')),
                "email":   profile.get('email', ''),
                "subject": row['subject'],
                "marks":   row['marks'],
                "grade":   row['grade'],
            })

        return jsonify({"ok": True, "students": enriched})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/add_student', methods=['POST'])
@admin_required
def add_student():
    """Add a mark entry for a registered student account."""
    data     = request.get_json()
    user_id  = data.get('user_id', '').strip()
    subject  = data.get('subject', 'General').strip()
    marks    = data.get('marks')

    if not user_id:
        return jsonify({"ok": False, "error": "Student is required"})
    if not subject:
        return jsonify({"ok": False, "error": "Subject is required"})
    try:
        marks = int(marks)
        if not (0 <= marks <= 100):
            return jsonify({"ok": False, "error": "Marks must be between 0 and 100"})
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid marks value"})

    grade = calc_grade(marks)

    try:
        # Check we're not duplicating the same subject for the same student
        existing = supabase.table('students') \
            .select('id') \
            .eq('user_id', user_id) \
            .eq('subject', subject) \
            .execute()
        if existing.data:
            return jsonify({"ok": False, "error": f"Marks for '{subject}' already exist for this student. Use Edit to update."})

        supabase.table('students').insert({
            "user_id": user_id,
            "marks":   marks,
            "grade":   grade,
            "subject": subject,
        }).execute()
        return jsonify({"ok": True, "message": f"Marks added successfully"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/update_marks', methods=['POST'])
@admin_required
def update_marks():
    """Update marks for a specific row by its row id."""
    data  = request.get_json()
    row_id = data.get('id')
    marks  = data.get('marks')

    try:
        marks = int(marks)
        if not (0 <= marks <= 100):
            return jsonify({"ok": False, "error": "Marks must be between 0 and 100"})
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid marks value"})

    grade = calc_grade(marks)

    try:
        result = supabase.table('students').select('id').eq('id', row_id).execute()
        if not result.data:
            return jsonify({"ok": False, "error": "Record not found"})

        supabase.table('students').update({"marks": marks, "grade": grade}).eq('id', row_id).execute()
        return jsonify({"ok": True, "message": "Marks updated", "grade": grade})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/delete_student', methods=['POST'])
@admin_required
def delete_student():
    """Delete a mark entry by row id."""
    data   = request.get_json()
    row_id = data.get('id')

    try:
        result = supabase.table('students').select('id').eq('id', row_id).execute()
        if not result.data:
            return jsonify({"ok": False, "error": "Record not found"})

        supabase.table('students').delete().eq('id', row_id).execute()
        return jsonify({"ok": True, "message": "Record deleted"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/find_topper')
@admin_required
def find_topper():
    try:
        result = supabase.table('students').select('user_id, marks, subject').order('marks', desc=True).limit(1).execute()
        if not result.data:
            return jsonify({"ok": False, "error": "No records yet"})
        row = result.data[0]
        profile = supabase.table('profiles').select('name, email').eq('id', row['user_id']).single().execute()
        name = profile.data.get('name', profile.data.get('email', 'Unknown'))
        return jsonify({"ok": True, "name": name, "marks": row['marks'], "subject": row['subject']})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/average')
@admin_required
def calculate_average():
    try:
        result = supabase.table('students').select('marks').execute()
        if not result.data:
            return jsonify({"ok": False, "error": "No records yet"})
        total   = sum(row['marks'] for row in result.data)
        average = round(total / len(result.data), 1)
        return jsonify({"ok": True, "average": average})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ══════════════════════════════════════════════════════
#  STUDENT — VIEW OWN MARKS
# ══════════════════════════════════════════════════════

@app.route('/api/my_marks')
@login_required
def my_marks():
    """Student sees all their own mark entries, matched by user_id from session."""
    user_id = session.get('user_id')

    try:
        result = supabase.table('students') \
            .select('subject, marks, grade') \
            .eq('user_id', user_id) \
            .order('subject') \
            .execute()

        return jsonify({"ok": True, "marks": result.data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ══════════════════════════════════════════════════════
#  RUN
# ══════════════════════════════════════════════════════
if __name__ == '__main__':
    print("=" * 50)
    print("  Marks Management System — Flask + Supabase")
    print("  Open in browser: http://127.0.0.1:5000")
    print("=" * 50)
    app.run(debug=True)
