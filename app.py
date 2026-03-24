from flask import Flask, request, jsonify, render_template, session
from supabase_client import supabase
import functools
import os

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), 'templates'))
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'marks_mgmt_secret_key_2024')

# ══════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════

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
    role     = data.get('role', 'student')   # 'admin' or 'student'

    # basic validation
    if not email.endswith('@gmail.com'):
        return jsonify({"ok": False, "error": "Email must end with @gmail.com"})
    if len(password) < 6:
        return jsonify({"ok": False, "error": "Password must be at least 6 characters"})
    if role not in ('admin', 'student'):
        return jsonify({"ok": False, "error": "Invalid role"})

    try:
        # 1. create user in Supabase Auth
        auth_response = supabase.auth.sign_up({
            "email": email,
            "password": password
        })

        user_id = auth_response.user.id

        # 2. save role in profiles table
        supabase.table('profiles').insert({
            "id":    user_id,
            "email": email,
            "role":  role
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
        # 1. sign in with Supabase Auth
        auth_response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })

        user_id = auth_response.user.id

        # 2. get role from profiles table
        profile = supabase.table('profiles').select('role').eq('id', user_id).single().execute()
        role    = profile.data['role']

        # 3. save to Flask session
        session['logged_in']    = True
        session['email']        = email
        session['role']         = role
        session['user_id']      = user_id
        session['supabase_token'] = auth_response.session.access_token

        # 4. redirect based on role
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
        "role":  session.get('role')
    })


# ══════════════════════════════════════════════════════
#  STUDENT OPERATIONS  (admin only except check_grade)
# ══════════════════════════════════════════════════════

@app.route('/api/students')
@login_required
def get_students():
    try:
        result   = supabase.table('students').select('*').execute()
        students = {}
        for row in result.data:
            students[row['name']] = row['marks']
        return jsonify({"students": students})
    except Exception as e:
        return jsonify({"students": {}, "error": str(e)})


@app.route('/api/add_student', methods=['POST'])
@admin_required
def add_student():
    data  = request.get_json()
    name  = data.get('name', '').strip()
    marks = data.get('marks')

    if not name:
        return jsonify({"ok": False, "error": "Name is required"})
    try:
        marks = int(marks)
        if not (0 <= marks <= 100):
            return jsonify({"ok": False, "error": "Marks must be between 0 and 100"})
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid marks value"})

    # calculate grade
    if   marks >= 90: grade = 'A'
    elif marks >= 75: grade = 'B'
    elif marks >= 50: grade = 'C'
    elif marks >= 35: grade = 'D'
    else:             grade = 'F'

    try:
        supabase.table('students').insert({
            "name":    name,
            "marks":   marks,
            "grade":   grade,
            "user_id": session.get('user_id')
        }).execute()
        return jsonify({"ok": True, "message": f"Student '{name}' added successfully"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/delete_student', methods=['POST'])
@admin_required
def delete_student():
    data = request.get_json()
    name = data.get('name', '').strip()

    try:
        result = supabase.table('students').select('id').eq('name', name).execute()
        if not result.data:
            return jsonify({"ok": False, "error": f"Student '{name}' not found"})

        supabase.table('students').delete().eq('name', name).execute()
        return jsonify({"ok": True, "message": f"Student '{name}' deleted successfully"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/find_topper')
@admin_required
def find_topper():
    try:
        result = supabase.table('students').select('name, marks').order('marks', desc=True).limit(1).execute()
        if not result.data:
            return jsonify({"ok": False, "error": "No students available"})
        topper = result.data[0]
        return jsonify({"ok": True, "name": topper['name'], "marks": topper['marks']})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ══════════════════════════════════════════════════════
#  MARKS OPERATIONS
# ══════════════════════════════════════════════════════

@app.route('/api/update_marks', methods=['POST'])
@admin_required
def update_marks():
    data  = request.get_json()
    name  = data.get('name', '').strip()
    marks = data.get('marks')

    try:
        marks = int(marks)
        if not (0 <= marks <= 100):
            return jsonify({"ok": False, "error": "Marks must be between 0 and 100"})
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid marks value"})

    if   marks >= 90: grade = 'A'
    elif marks >= 75: grade = 'B'
    elif marks >= 50: grade = 'C'
    elif marks >= 35: grade = 'D'
    else:             grade = 'F'

    try:
        result = supabase.table('students').select('id').eq('name', name).execute()
        if not result.data:
            return jsonify({"ok": False, "error": f"Student '{name}' not found"})

        supabase.table('students').update({"marks": marks, "grade": grade}).eq('name', name).execute()
        return jsonify({"ok": True, "message": f"Marks updated for '{name}'"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/check_grade', methods=['POST'])
@login_required
def check_grade():
    data = request.get_json()
    name = data.get('name', '').strip()

    try:
        result = supabase.table('students').select('name, marks, grade').eq('name', name).execute()
        if not result.data:
            return jsonify({"ok": False, "error": f"Student '{name}' not found"})

        student = result.data[0]
        return jsonify({"ok": True, "name": student['name'], "marks": student['marks'], "grade": student['grade']})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/average')
@admin_required
def calculate_average():
    try:
        result = supabase.table('students').select('marks').execute()
        if not result.data:
            return jsonify({"ok": False, "error": "No students available"})

        total   = sum(row['marks'] for row in result.data)
        average = round(total / len(result.data), 2)
        return jsonify({"ok": True, "average": average})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/my_marks')
@login_required
def my_marks():
    """Student sees only their own marks — matched by email name"""
    email = session.get('email', '')
    name  = email.split('@')[0]   # e.g. rahul@gmail.com → rahul

    try:
        result = supabase.table('students').select('name, marks, grade').ilike('name', name).execute()
        if not result.data:
            return jsonify({"ok": False, "error": "Your marks not found yet"})

        student = result.data[0]
        return jsonify({"ok": True, "name": student['name'], "marks": student['marks'], "grade": student['grade']})
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
