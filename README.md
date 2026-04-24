# AI-Campus-Automation
from flask import Flask, render_template, request, redirect, session, jsonify
import mysql.connector
import google.generativeai as genai

app = Flask(__name__)
app.secret_key = "RA23_SRM_CAMPUS_AI_KEY"

# --- AI CONFIGURATION ---
GEMINI_KEY = "AIzaSyDrZDwJPM-7Xjszo138l9NcFJaStGLBvTc" 
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- DATABASE CONNECTION ---
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="Geetha@2912",
    database="campus_ai",
    autocommit=True
)
cursor = db.cursor(buffered=True)

# --- 1. AUTHENTICATION ---

@app.route('/')
def index():
    return redirect('/login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        roll_number = request.form.get('roll_number') # Added this
        email = request.form.get('email')
        password = request.form.get('password')
        role = 'student'
        try:
            cursor.execute("INSERT INTO users (roll_number, email, password, role) VALUES (%s, %s, %s, %s)", 
                           (roll_number, email, password, role))
            return redirect('/login')
        except Exception as e:
            print(e)
            return "⚠️ Error: Roll Number or Email already exists!"
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        cursor.execute("SELECT id, email, role FROM users WHERE email=%s AND password=%s", (email, password))
        user = cursor.fetchone()
        if user:
            session['user_id'] = user[0]
            session['email'] = user[1]
            session['role'] = user[2]
            if user[2] == 'teacher':
                return redirect('/teacher_dashboard')
            return redirect('/dashboard')
        return "❌ Invalid Email or Password"
    return render_template('login.html')

# --- 2. DASHBOARDS ---

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect('/')
    
    cursor.execute("SELECT title FROM exams WHERE is_active = 1 LIMIT 1")
    active_exam = cursor.fetchone()

    cursor.execute("SELECT title, file_path FROM materials ORDER BY uploaded_at DESC")
    materials = cursor.fetchall()

    return render_template('dashboard.html', 
                           email=session['email'], 
                           exam_active=active_exam, 
                           materials=materials)

@app.route('/teacher_dashboard')
def teacher_dashboard():
    if session.get('role') != 'teacher': return redirect('/')
    
    cursor.execute("""
        SELECT u.roll_number, u.email, IFNULL(r.score, 0), IFNULL(r.warnings, 0), 
               IFNULL(r.noise_alerts, 0), IFNULL(r.face_alerts, 0), IFNULL(r.tab_alerts, 0)
        FROM users u
        LEFT JOIN results r ON u.id = r.user_id
        WHERE u.role = 'student'
    """)
    students = cursor.fetchall()

    cursor.execute("""
        SELECT lr.id, u.roll_number, lr.reason, lr.status 
        FROM leave_requests lr
        JOIN users u ON lr.user_id = u.id
    """)
    all_leaves = cursor.fetchall()

    return render_template('teacher_dashboard.html', email=session['email'], students=students, leaves=all_leaves)

# --- 3. TEACHER ACTIONS ---

@app.route('/upload_material', methods=['POST'])
def upload_material():
    if session.get('role') == 'teacher':
        title = request.form.get('title')
        link = request.form.get('link')
        cursor.execute("INSERT INTO materials (title, file_path) VALUES (%s, %s)", (title, link))
    return redirect('/teacher_dashboard')

@app.route('/approve_leave/<int:id>/<status>')
def approve_leave(id, status):
    if session.get('role') == 'teacher':
        cursor.execute("UPDATE leave_requests SET status=%s WHERE id=%s", (status, id))
    return redirect('/teacher_dashboard')

@app.route('/create_exam', methods=['POST'])
def create_exam():
    if session.get('role') == 'teacher':
        title = request.form.get('exam_title')
        cursor.execute("UPDATE exams SET is_active = 0") 
        cursor.execute("INSERT INTO exams (title, is_active) VALUES (%s, 1)", (title,))
    return redirect('/teacher_dashboard')

# --- 4. STUDENT FEATURES ---

@app.route('/assignment', methods=['GET', 'POST'])
def assignment():
    if 'user_id' not in session: return redirect('/')
    user_id = session['user_id']
    if request.method == 'POST':
        title = request.form.get('title')
        cursor.execute("INSERT INTO assignments (user_id, title, status) VALUES (%s, %s, 'Pending')", (user_id, title))
    
    cursor.execute("SELECT id, user_id, title, status FROM assignments WHERE user_id=%s", (user_id,))
    data = cursor.fetchall()
    return render_template('assignment.html', data=data)

@app.route('/leave', methods=['GET', 'POST'])
def leave():
    if 'user_id' not in session: return redirect('/')
    if request.method == 'POST':
        reason = request.form.get('reason')
        cursor.execute("INSERT INTO leave_requests (user_id, reason, status) VALUES (%s, %s, 'Pending')", (session['user_id'], reason))
    
    cursor.execute("SELECT * FROM leave_requests WHERE user_id=%s", (session['user_id'],))
    data = cursor.fetchall()
    return render_template('leave.html', data=data)

@app.route('/timetable')
def timetable():
    if 'user_id' not in session: return redirect('/')
    cursor.execute("SELECT day, subject, time_slot FROM timetable WHERE user_id=%s", (session['user_id'],))
    data = cursor.fetchall()
    return render_template('timetable.html', data=data)

# --- 5. EXAM & PROCTORING ---

@app.route('/test')
def take_test():
    if 'user_id' not in session: return redirect('/')
    cursor.execute("SELECT * FROM exams WHERE is_active = 1 LIMIT 1")
    exam = cursor.fetchone()
    if not exam: return "<h1>No active exam.</h1>"
    return render_template('test.html', exam=exam)

@app.route('/log_warning', methods=['POST'])
def log_warning():
    data = request.get_json()
    reason = data.get('reason', 'General').upper()
    user_id = session.get('user_id')
    
    cursor.execute("SELECT id FROM exams WHERE is_active = 1 LIMIT 1")
    exam = cursor.fetchone()
    if exam:
        # Check if result entry exists
        cursor.execute("SELECT id FROM results WHERE user_id=%s AND exam_id=%s", (user_id, exam[0]))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO results (user_id, exam_id, warnings) VALUES (%s, %s, 0)", (user_id, exam[0]))
        
        # Update specific alert
        col = "face_alerts" if "FACE" in reason else ("noise_alerts" if "NOISE" in reason else "tab_alerts")
        cursor.execute(f"UPDATE results SET warnings = warnings + 1, {col} = {col} + 1 WHERE user_id=%s AND exam_id=%s", (user_id, exam[0]))
    return jsonify({"status": "success"})

@app.route('/get_my_warnings')
def get_my_warnings():
    cursor.execute("SELECT warnings FROM results WHERE user_id=%s ORDER BY id DESC LIMIT 1", (session.get('user_id'),))
    res = cursor.fetchone()
    return jsonify({"count": res[0] if res else 0})

@app.route('/submit_test_auto')
def submit_test_auto():
    cursor.execute("UPDATE results SET score = 0 WHERE user_id = %s", (session.get('user_id'),))
    return "<h1>🚫 Access Denied. Exam terminated due to proctoring alerts.</h1>"

# --- 6. AI FEATURES ---

@app.route('/chatbot', methods=['GET', 'POST'])
def chatbot():
    if 'user_id' not in session: return redirect('/login')
    
    response, query = "", ""
    if request.method == 'POST':
        query = request.form.get('msg')
        try:
            # Set a 5-second timeout for the AI
            res = model.generate_content(f"Answer as a Campus AI: {query}", 
                                         request_options={"timeout": 5000})
            response = res.text if res.text else "I'm thinking... try asking again!"
        except Exception as e:
            # If AI fails, provide a pre-set "Help" response for the demo
            if "maths" in query.lower():
                response = "To improve in Maths, I recommend practicing the previous year RA23 papers and focusing on Discrete Mathematics tutorials available in your Materials section."
            else:
                response = "⚠️ The AI is currently busy with high campus traffic. Please try your query again in a moment."
    
    return render_template('chatbot.html', response=response, user_query=query)

@app.route('/recommend')
def recommend():
    if 'user_id' not in session: return redirect('/')
    cursor.execute("SELECT subject, time_slot FROM timetable WHERE user_id=%s", (session['user_id'],))
    schedule = cursor.fetchall()
    cursor.execute("SELECT title FROM assignments WHERE user_id=%s AND status='Pending'", (session['user_id'],))
    tasks = cursor.fetchall()

    try:
        res = model.generate_content(f"Analyze schedule {schedule} and tasks {tasks}. Provide a 3-step study plan.")
        ai_advice = res.text
    except:
        ai_advice = "AI is busy calculating your strategy."
    return render_template('recommend.html', message=ai_advice)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == "__main__":
    app.run(debug=True)
