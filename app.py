import os
from flask import Flask, render_template, request, redirect, session, jsonify
import mysql.connector
import google.generativeai as genai
import json

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'RA23_SRM_CAMPUS_AI_KEY')
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax'
)

# --- AI CONFIGURATION ---
GEMINI_KEY = os.environ.get('GEMINI_KEY', '')
model = None
if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        print(f"AI configuration error: {e}")

# --- DATABASE CONNECTION ---
db = mysql.connector.connect(
    host=os.environ.get('DB_HOST', 'localhost'),
    user=os.environ.get('DB_USER', 'root'),
    password=os.environ.get('DB_PASSWORD', 'Geetha@2912'),
    database=os.environ.get('DB_NAME', 'campus_ai'),
    autocommit=True
)
cursor = db.cursor(buffered=True)

# --- 1. AUTHENTICATION & REGISTRATION ---

@app.route('/')
def index():
    return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        cursor.execute("SELECT id, email, role, roll_number FROM users WHERE email=%s AND password=%s", (email, password))
        user = cursor.fetchone()
        if user:
            session['user_id'] = user[0]
            session['email'] = user[1]
            session['role'] = user[2]
            session['roll_number'] = user[3]
            return redirect('/teacher_dashboard' if user[2] == 'teacher' else '/dashboard')
        return "Invalid Credentials"
    return render_template('login.html')

def safe_generate(prompt, fallback_text):
    if not model:
        return fallback_text
    try:
        response = model.generate_content(prompt)
        text = getattr(response, 'text', None) or str(response)
        return text
    except Exception as e:
        print(f"AI generation failed: {e}")
        return fallback_text

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        roll_number = request.form.get('roll_number')
        email = request.form.get('email')
        password = request.form.get('password')
        try:
            cursor.execute("INSERT INTO users (roll_number, email, password, role) VALUES (%s, %s, %s, 'student')", 
                           (roll_number, email, password))
            return redirect('/login')
        except mysql.connector.Error as e:
            print(f"Registration DB error: {e}")
            return "Registration Failed: This email or roll number may already exist."
        except Exception as e:
            print(f"Registration error: {e}")
            return "Registration Failed: Please try again later."
    return render_template('register.html')

# --- 2. ASSIGNMENT TRACKER ---

@app.route('/assignment', methods=['GET', 'POST'])
def assignment():
    if 'user_id' not in session: return redirect('/')
    user_id = session['user_id']
    if request.method == 'POST':
        title = request.form.get('title')
        cursor.execute("INSERT INTO assignments (user_id, title, status) VALUES (%s, %s, 'Pending')", (user_id, title))
    cursor.execute("SELECT id, user_id, title, status FROM assignments WHERE user_id=%s ORDER BY id DESC", (user_id,))
    data = cursor.fetchall()
    return render_template('assignment.html', data=data)

@app.route('/complete_assignment/<int:id>')
def complete_assignment(id):
    if 'user_id' in session:
        cursor.execute("UPDATE assignments SET status='Completed' WHERE id=%s AND user_id=%s", (id, session['user_id']))
    return redirect('/assignment')

@app.route('/delete_assignment/<int:id>')
def delete_assignment(id):
    if 'user_id' in session:
        cursor.execute("DELETE FROM assignments WHERE id=%s AND user_id=%s", (id, session['user_id']))
    return redirect('/assignment')

# --- 3. UNIFIED STUDENT DASHBOARD ---

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect('/')
    user_id = session['user_id']
    cursor.execute("SELECT title FROM exams WHERE is_active = 1 LIMIT 1")
    active_exam = cursor.fetchone()
    cursor.execute("""
        SELECT subject, ROUND((SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) / COUNT(*)) * 100, 2) 
        FROM attendance WHERE user_id=%s GROUP BY subject
    """, (user_id,))
    attendance = cursor.fetchall()
    cursor.execute("SELECT title, file_path FROM materials ORDER BY uploaded_at DESC")
    materials = cursor.fetchall()
    return render_template('dashboard.html', email=session['email'], roll_number=session.get('roll_number', 'N/A'), exam_active=active_exam, 
                           attendance=attendance, materials=materials)

# --- 4. AI EXAMINATION & PROCTORING HUB ---

@app.route('/create_exam', methods=['POST'])
def create_exam():
    if session.get('role') != 'teacher': return redirect('/')
    topic = request.form.get('exam_title')
    prompt = f"Generate 5 MCQ questions for {topic} in Python. Return ONLY valid JSON list. " \
             "Format: [{\"q\":\"Q?\",\"a\":\"O1\",\"b\":\"O2\",\"c\":\"O3\",\"d\":\"O4\",\"correct\":\"a\"}]"
    fallback_questions = json.dumps([
        {"q": "What is the output of print(2 + 3)?", "a": "23", "b": "5", "c": "2", "d": "Error", "correct": "b"},
        {"q": "Which keyword defines a function in Python?", "a": "func", "b": "define", "c": "def", "d": "function", "correct": "c"}
    ])
    questions_json = safe_generate(prompt, fallback_questions)
    try:
        json.loads(questions_json)
    except Exception:
        questions_json = fallback_questions

    cursor.execute("UPDATE exams SET is_active = 0")
    cursor.execute("INSERT INTO exams (title, questions_json, is_active) VALUES (%s, %s, 1)", (topic, questions_json))
    return redirect('/teacher_dashboard')

@app.route('/test')
def take_test():
    if 'user_id' not in session: return redirect('/')
    cursor.execute("SELECT title, questions_json FROM exams WHERE is_active = 1 LIMIT 1")
    exam = cursor.fetchone()
    if not exam: return redirect('/dashboard')
    questions = json.loads(exam[1])
    return render_template('test.html', topic=exam[0], questions=questions)

@app.route('/submit_exam', methods=['POST'])
def submit_exam():
    return "<h1>Exam Submitted Successfully!</h1><p>Identity verified. Logs saved. <a href='/dashboard'>Back to Dashboard</a></p>"

# --- 5. REAL-TIME PROCTORING LOGS ---

@app.route('/log_warning', methods=['POST'])
def log_warning():
    data = request.get_json()
    reason = data.get('reason', 'General').upper()
    user_id = session.get('user_id')
    
    # Map high-level proctoring reasons to database columns
    col = "face_alerts" if ("FACE" in reason or "GAZE" in reason) else ("noise_alerts" if "NOISE" in reason else "tab_alerts")

    cursor.execute("SELECT id FROM exams WHERE is_active = 1 LIMIT 1")
    exam = cursor.fetchone()
    if exam and user_id:
        cursor.execute("SELECT id FROM results WHERE user_id=%s AND exam_id=%s", (user_id, exam[0]))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO results (user_id, exam_id, warnings, face_alerts, noise_alerts, tab_alerts) VALUES (%s, %s, 0, 0, 0, 0)", (user_id, exam[0]))
        
        # Update the warning count and the specific alert column
        cursor.execute(f"UPDATE results SET warnings = warnings + 1, {col} = {col} + 1 WHERE user_id=%s AND exam_id=%s", (user_id, exam[0]))
    
    return jsonify({"status": "success", "logged": reason})

# --- 6. AI CHATBOT & TEACHER COMMAND CENTER ---

@app.route('/chatbot', methods=['GET', 'POST'])
def chatbot():
    if 'user_id' not in session: return redirect('/login')
    
    # Security: Disable AI Chat during active exams
    cursor.execute("SELECT id FROM exams WHERE is_active = 1 LIMIT 1")
    if cursor.fetchone():
        return render_template('chatbot.html', response="Security Protocol: AI Chat is offline during active exams.", user_query="N/A")

    response, query = "", ""
    if request.method == 'POST':
        query = request.form.get('msg')
        cursor.execute("SELECT subject, time_slot FROM timetable WHERE user_id=%s", (session['user_id'],))
        timetable = cursor.fetchall()
        prompt = f"User: {session['email']}. Schedule: {timetable}. Query: {query}. Be a helpful SRM Campus AI advisor."
        response = safe_generate(prompt, "SRM Cloud synchronization error.")
    return render_template('chatbot.html', response=response, user_query=query)

@app.route('/teacher_dashboard')
def teacher_dashboard():
    if session.get('role') != 'teacher': return redirect('/')
    cursor.execute("""
        SELECT u.roll_number, u.email, IFNULL(r.warnings, 0), IFNULL(r.noise_alerts, 0), IFNULL(r.face_alerts, 0), IFNULL(r.tab_alerts, 0)
        FROM users u LEFT JOIN results r ON u.id = r.user_id WHERE u.role = 'student'
    """)
    students = cursor.fetchall()
    cursor.execute("SELECT l.id, u.roll_number, l.reason, l.status FROM leave_requests l JOIN users u ON l.user_id = u.id ORDER BY l.id DESC")
    leaves = cursor.fetchall()
    return render_template('teacher_dashboard.html', students=students, leaves=leaves, email=session['email'])

@app.route('/recommend')
def recommend():
    if 'user_id' not in session: return redirect('/')
    cursor.execute("SELECT subject, time_slot FROM timetable WHERE user_id=%s", (session['user_id'],))
    schedule = cursor.fetchall()
    cursor.execute("SELECT title FROM assignments WHERE user_id=%s AND status='Pending'", (session['user_id'],))
    tasks = cursor.fetchall()
    prompt = f"Analyze schedule {schedule} and tasks {tasks}. Provide a 3-step study plan."
    ai_advice = safe_generate(prompt, "AI is busy calculating your strategy.")
    return render_template('recommend.html', message=ai_advice)

# --- 7. ADDITIONAL HUB FEATURES ---

@app.route('/upload_material', methods=['POST'])
def upload_material():
    if session.get('role') != 'teacher': return redirect('/')
    title = request.form.get('title')
    link = request.form.get('link')
    cursor.execute("INSERT INTO materials (title, file_path) VALUES (%s, %s)", (title, link))
    return redirect('/teacher_dashboard')

@app.route('/leave', methods=['GET', 'POST'])
def leave():
    if 'user_id' not in session: return redirect('/')
    if request.method == 'POST':
        reason = request.form.get('reason')
        cursor.execute("INSERT INTO leave_requests (user_id, reason, status) VALUES (%s, %s, 'Pending')", (session['user_id'], reason))
    cursor.execute("SELECT id, reason, status FROM leave_requests WHERE user_id=%s ORDER BY applied_at DESC", (session['user_id'],))
    return render_template('leave.html', data=cursor.fetchall())

@app.route('/timetable')
def timetable():
    if 'user_id' not in session: return redirect('/')
    cursor.execute("SELECT day, subject, time_slot FROM timetable WHERE user_id=%s", (session['user_id'],))
    return render_template('timetable.html', data=cursor.fetchall())

@app.route('/approve_leave/<int:id>/<status>')
def approve_leave(id, status):
    if session.get('role') == 'teacher':
        cursor.execute("UPDATE leave_requests SET status=%s WHERE id=%s", (status, id))
    return redirect('/teacher_dashboard')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == "__main__":
    app.run(debug=True)