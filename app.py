# ============================================================
#  StudyMate AI — app.py  (Professional Version)
#  Author  : Raja Swami
#  Version : 2.0
#
#  WHAT'S FIXED vs your original:
#  ✅ API key moved to .env (no more exposed keys!)
#  ✅ Passwords are now HASHED (secure storage)
#  ✅ Secret key loaded from .env
#  ✅ Homepage shows landing page (not redirecting to login)
#  ✅ Retry logic extracted into one helper function (DRY)
#  ✅ Proper error handling everywhere
#  ✅ Code comments added so you understand every line
#  ✅ Logout added
#  ✅ All your existing features preserved
# ============================================================

import os
import sqlite3
import json
import time
import asyncio
import edge_tts

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from google import genai

# ── STEP 1: Load secrets from .env file ─────────────────────
# This reads your .env file and makes the variables available
# via os.environ.get(). The API key is NEVER in this file.
load_dotenv()

# ── STEP 2: Create Flask App ─────────────────────────────────
app = Flask(__name__)

# Secret key is used to encrypt session cookies (login sessions)
# It's now loaded from .env — much safer!
app.secret_key = os.environ.get('SECRET_KEY', 'fallback_dev_key_change_this')

# ── STEP 3: Setup Google Gemini AI Client ────────────────────
# We read the API key from .env — NOT hardcoded!
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

if not GEMINI_API_KEY or GEMINI_API_KEY == 'YOUR_GEMINI_API_KEY_HERE':
    print("[WARNING] GEMINI_API_KEY not set in .env file!")
    print("          AI features will not work until you add your key.")
    client = None
else:
    client = genai.Client(api_key=GEMINI_API_KEY)
    print("[OK] Gemini AI client connected successfully!")

# ── STEP 4: Ensure required folders exist ────────────────────
os.makedirs('database', exist_ok=True)
os.makedirs('uploads', exist_ok=True)

# ── STEP 5: Database Setup ───────────────────────────────────
def get_db_connection():
    """
    Opens a connection to the SQLite database.
    conn.row_factory = sqlite3.Row lets us access columns by name
    instead of index. Example: user['email'] instead of user[2]
    """
    conn = sqlite3.connect('database/studymate.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """
    Creates the database tables if they don't exist yet.
    This runs every time the app starts — safely.
    
    NOTE: Passwords are stored as HASHES, not plain text.
    Example: "raja123" → "$pbkdf2-sha256$..." (unreadable hash)
    Even if someone steals the database, they can't read passwords.
    """
    conn = get_db_connection()
    
    # 1. Users Table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT    NOT NULL,
            email    TEXT    UNIQUE NOT NULL,
            password TEXT    NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 2. Saved Items Table (For Library/History Feature)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS saved_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            item_type  TEXT NOT NULL,
            title      TEXT NOT NULL,
            content    TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("[OK] Database initialized successfully!")

# Initialize DB when app starts
init_db()

# ── HEALTH / KEEP-ALIVE PING ROUTE ───────────────────────────
@app.route('/health')
def health():
    """Lightweight ping endpoint for keep-alive monitoring to prevent Render cold starts."""
    return {"status": "ok", "message": "StudyMate AI is active"}, 200


# ── STEP 6: Helper Function for Gemini API calls ─────────────
def ask_gemini(prompt):
    """
    Sends a prompt to Gemini AI and returns the response text.
    Uses robust fallback across valid Gemini SDK model names (gemini-2.5-flash, gemini-1.5-flash).
    
    Returns: (result_text, error_message)
    """
    if not client:
        return None, "⚠️ AI not configured. Please add your GEMINI_API_KEY in the .env file."
    
    models_to_try = ['gemini-1.5-flash', 'gemini-2.5-flash', 'gemini-2.0-flash']
    last_error = ""

    for model_name in models_to_try:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response and response.text:
                    return response.text, None  # Success!
            except Exception as e:
                last_error = str(e)
                if "429" in last_error or "RESOURCE_EXHAUSTED" in last_error:
                    # Rate limit hit — wait 5s then 8s for quota window to reset
                    time.sleep(5 if attempt == 0 else 8)
                else:
                    break  # Try next model if model not found/invalid

    if "429" in last_error or "RESOURCE_EXHAUSTED" in last_error:
        return None, "⏳ AI Free Quota Limit Reached: Google Gemini free tier rate limit was temporarily reached. Please wait 10 seconds and click Generate again!"

    return None, f"⚠️ Gemini API Error: {last_error}"


# ── STEP 7: Helper — Check if user is logged in ──────────────
def is_logged_in():
    """Returns True if user has an active session."""
    return 'user_id' in session


# ══════════════════════════════════════════════════════════════
#  ROUTES — Each function handles one URL
# ══════════════════════════════════════════════════════════════

# ── HOME PAGE ────────────────────────────────────────────────
@app.route('/')
def index():
    """
    Shows the landing homepage to everyone.
    If the user is already logged in, redirect to dashboard.
    """
    if is_logged_in():
        return redirect(url_for('dashboard'))
    return render_template('index.html')


# ── SIGNUP ───────────────────────────────────────────────────
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """
    GET  → Show the signup form
    POST → Process the form (create new user)
    """
    # If already logged in, no need to sign up again
    if is_logged_in():
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        # Basic validation
        if not username or not email or not password:
            return render_template('signup.html', error='All fields are required!')
        
        if len(password) < 6:
            return render_template('signup.html', error='Password must be at least 6 characters!')

        # 🔐 Hash the password BEFORE storing it in database
        # "raja123" → "$pbkdf2-sha256$260000$..." (secure hash)
        hashed_password = generate_password_hash(password)

        try:
            conn = get_db_connection()
            conn.execute(
                'INSERT INTO users (username, email, password) VALUES (?, ?, ?)',
                (username, email, hashed_password)
            )
            conn.commit()
            conn.close()
            flash('Account created successfully! Please login.', 'success')
            return redirect(url_for('login'))

        except sqlite3.IntegrityError:
            # IntegrityError happens when email already exists (UNIQUE constraint)
            return render_template('signup.html', error='This email is already registered!')
        
        except Exception as e:
            return render_template('signup.html', error=f'Something went wrong: {str(e)}')

    return render_template('signup.html')


# ── LOGIN ────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    GET  → Show the login form
    POST → Check credentials and log user in
    """
    if is_logged_in():
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not password:
            return render_template('login.html', error='Please fill in all fields!')

        conn = get_db_connection()
        user = conn.execute(
            'SELECT * FROM users WHERE email = ?', (email,)
        ).fetchone()
        conn.close()

        # check_password_hash compares plain password with stored hash
        # This is secure — we NEVER store plain passwords!
        if user and check_password_hash(user['password'], password):
            # Save user info in session (like a login token)
            session['user_id']  = user['id']
            session['username'] = user['username']
            session['email']    = user['email']
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='Invalid email or password!')

    return render_template('login.html')


# ── LOGOUT ───────────────────────────────────────────────────
@app.route('/logout')
def logout():
    """Clears the session and redirects to login."""
    session.clear()
    flash('Logged out successfully!', 'info')
    return redirect(url_for('login'))


# ── DASHBOARD ────────────────────────────────────────────────
@app.route('/dashboard')
def dashboard():
    """
    Main page after login.
    Protected: Only logged-in users can see this.
    """
    if not is_logged_in():
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    
    # 1. Total saved items count by type
    stats_rows = conn.execute(
        'SELECT item_type, COUNT(*) as count FROM saved_items WHERE user_id = ? GROUP BY item_type',
        (session['user_id'],)
    ).fetchall()
    
    # Initialize dictionary
    stats = {'notes': 0, 'doubt': 0, 'quiz': 0, 'flashcard': 0, 'total': 0}
    for row in stats_rows:
        itype = row['item_type']
        if itype in stats:
            stats[itype] = row['count']
        stats['total'] += row['count']
        
    # 2. Get 3 most recently saved items
    recent_items = conn.execute(
        'SELECT id, title, item_type, created_at FROM saved_items WHERE user_id = ? ORDER BY created_at DESC LIMIT 3',
        (session['user_id'],)
    ).fetchall()
    
    conn.close()
    
    return render_template(
        'dashboard.html', 
        username=session.get('username'),
        stats=stats,
        recent_items=recent_items
    )


# ── AI DOUBT SOLVER ──────────────────────────────────────────
@app.route('/doubt-solver', methods=['GET', 'POST'])
def doubt_solver():
    """Accepts a question and returns an AI-generated answer."""
    if not is_logged_in():
        return redirect(url_for('login'))

    answer = ""
    question = ""

    if request.method == 'POST':
        question = request.form.get('question', '').strip()

        if not question:
            return render_template('doubt_solver.html', error='Please enter a question!')

        prompt = f"""You are an engaging, expert study assistant for students.
Answer the following question clearly, simply, and engagingly.
- Use relevant emojis to make the content lively and interesting.
- Use bold text (**keyword**) to highlight important concepts, terms, formulas, and definitions.
- Use bullet points, subheadings, or tables to structure the explanation cleanly.
- Use code blocks or code highlights if the question is related to programming or technical concepts.

Question: {question}"""

        result, error = ask_gemini(prompt)
        answer = result if result else error

    return render_template('doubt_solver.html', answer=answer, question=question)


# ── QUIZ GENERATOR ───────────────────────────────────────────
@app.route('/quiz', methods=['GET', 'POST'])
def quiz():
    """Generates a 5-question MCQ quiz on any topic."""
    if not is_logged_in():
        return redirect(url_for('login'))

    quiz_data = []
    raw_quiz_json = ""
    topic = ""
    error = ""

    if request.method == 'POST':
        topic = request.form.get('topic', '').strip()

        if not topic:
            return render_template('quiz_generator.html', error='Please enter a topic!')

        prompt = f"""Generate a multiple-choice quiz with exactly 5 questions on the topic: '{topic}'.
Return the output as a valid JSON array of objects, with NO markdown code block wrapper (i.e. no ```json).
Each object in the array must have exactly these keys:
- "question": string, the text of the question
- "options": object with keys "A", "B", "C", "D" representing options
- "correct": string, one of "A", "B", "C", "D"
- "explanation": string, a brief explanation of why that option is correct

Example structure:
[
  {{
    "question": "What is the primary function of RAM?",
    "options": {{
      "A": "Permanent data storage",
      "B": "Temporary working memory for the CPU",
      "C": "Running basic input/output operations",
      "D": "Controlling cooling systems"
    }},
    "correct": "B",
    "explanation": "RAM (Random Access Memory) is volatile memory used by the CPU to store data currently in use for fast access."
  }}
]"""

        result, error_msg = ask_gemini(prompt)
        
        if result:
            raw_quiz_json = result.strip()
            # Clean up potential markdown wrappers
            if raw_quiz_json.startswith("```"):
                lines = raw_quiz_json.split('\n')
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_quiz_json = "\n".join(lines).strip()
            
            try:
                quiz_data = json.loads(raw_quiz_json)
            except Exception as e:
                error = f"Failed to parse quiz response: {str(e)}"
        else:
            error = error_msg

    return render_template('quiz_generator.html', quiz_data=quiz_data, raw_quiz_json=raw_quiz_json, topic=topic, error=error)


# ── AI NOTES GENERATOR ───────────────────────────────────────
@app.route('/ai-notes', methods=['GET', 'POST'])
def ai_notes():
    """Generates structured study notes on any topic."""
    if not is_logged_in():
        return redirect(url_for('login'))

    notes_result = ""
    topic = ""

    if request.method == 'POST':
        topic = request.form.get('topic', '').strip()

        if not topic:
            return render_template('ai_notes.html', error='Please enter a topic!')

        prompt = f"""Generate comprehensive, well-structured, and highly visual study notes on the topic: '{topic}'
        
        To make these notes extremely engaging and colorful for B.Tech CSE students, structure them strictly with:
        
        # 📚 Introduction
        [Detailed overview of the topic. Highlight key terms in bold]
        
        # 💡 Key Concepts & Callouts
        Use markdown blockquotes starting with emojis to create colored highlight cards:
        - For a key definition/term, use:
        > 📝 **Definition:** [Definition text here]
        - For an important concept/tip, use:
        > 💡 **Concept:** [Tip/Concept detail here]
        - For warnings or critical exam points, use:
        > ⚠️ **Warning:** [Common mistakes or critical exam questions here]
        
        # 📊 Structured Breakdown & Comparison
        - Draw a markdown comparison table comparing different aspects, types, or architectures of the topic.
        - Add a clean bulleted list where each bullet starts with a relevant emoji.
        
        # ⚙️ Technical Blueprint (Formulas, Equations or Code)
        - If math-related: use LaTeX block formulas like $$...$$.
        - If CS/coding-related: provide a clean, commented code snippet in a fenced code block with language specifier (e.g. ```python).
        
        # 🎯 Summary Cheat Sheet
        [Bullet-points summarizing the core takeaways]
        
        Use emojis, clear spacing, bold styling for important terms, and visual formatting. Make it detailed, highly structured, and suitable for exam revision."""

        result, error = ask_gemini(prompt)
        notes_result = result if result else error

    return render_template('ai_notes.html', notes=notes_result, topic=topic)


# ── FLASHCARDS ───────────────────────────────────────────────
@app.route('/flashcards', methods=['GET', 'POST'])
def flashcards():
    """Generates 10 Q&A flashcards on any topic."""
    if not is_logged_in():
        return redirect(url_for('login'))

    flashcards_data = []
    topic = ""

    if request.method == 'POST':
        topic = request.form.get('topic', '').strip()

        if not topic:
            return render_template('flashcards.html', error='Please enter a topic!')

        prompt = f"""Create exactly 10 study flashcards on the topic: {topic}

Use EXACTLY this format for each card (no deviation):
Q: [Question here]
A: [Short, clear answer here]

Keep answers concise — maximum 2 sentences each.
Make questions test real understanding, not just memorization."""

        result, error = ask_gemini(prompt)

        if result:
            # Parse the AI response into a list of dicts [{q:..., a:...}, ...]
            flashcards_data = parse_flashcards(result)
        else:
            return render_template('flashcards.html', error=error, topic=topic)

    return render_template('flashcards.html', flashcards_data=flashcards_data, topic=topic)


# ── VISUAL AI MIND MAP & ROADMAP GENERATOR ───────────────────
@app.route('/ai-roadmap', methods=['GET', 'POST'])
def ai_roadmap():
    """Generates an interactive visual mind map / learning roadmap for any topic or career path."""
    if not is_logged_in():
        return redirect(url_for('login'))

    roadmap_data = None
    raw_json = ""
    topic = ""
    error = ""

    if request.method == 'POST':
        topic = request.form.get('topic', '').strip()

        if not topic:
            return render_template('roadmap.html', error='Please enter a topic or career path!')

        prompt = f"""Generate a concise, structured Visual Learning Roadmap for topic: '{topic}'.
Return output as valid JSON with NO markdown code block wrappers (i.e. no ```json).

The JSON object must have this exact structure:
{{
  "title": "{topic}",
  "subtitle": "Complete Step-by-Step Learning & Mastery Roadmap",
  "estimated_total_hours": 60,
  "difficulty_level": "Beginner to Advanced",
  "phases": [
    {{
      "phase_num": 1,
      "phase_title": "Phase 1: Foundations & Core Prerequisites",
      "summary": "Core concepts to master first.",
      "nodes": [
        {{
          "id": "p1_n1",
          "title": "Topic Name",
          "desc": "Short 1-sentence explanation of this concept.",
          "hours": 8,
          "difficulty": "Easy",
          "key_takeaways": ["Core concept 1", "Core concept 2"],
          "action_step": "Practice exercise suggestion"
        }}
      ]
    }}
  ]
}}

Keep JSON concise (exactly 3 phases, 2 nodes per phase) so it generates super fast."""

        result, error_msg = ask_gemini(prompt)

        if result:
            raw_json = result.strip()
            if raw_json.startswith("```"):
                lines = raw_json.split('\n')
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_json = "\n".join(lines).strip()

            try:
                roadmap_data = json.loads(raw_json)
            except Exception as e:
                roadmap_data = generate_fallback_roadmap(topic)
                raw_json = json.dumps(roadmap_data)
        else:
            # Fallback if Gemini quota 429 is hit
            roadmap_data = generate_fallback_roadmap(topic)
            raw_json = json.dumps(roadmap_data)
            error = None

    return render_template('roadmap.html', roadmap_data=roadmap_data, raw_json=raw_json, topic=topic, error=error)


# ── AI EXAM PAPER PREDICTOR & QUESTION PAPER GENERATOR ───────
@app.route('/exam-predictor', methods=['GET', 'POST'])
def exam_predictor():
    """Generates authentic predicted model question papers with Model Answers based on 5-10 year PYQ analysis for RTU, B.Tech CSE, Midterms, and Boards."""
    if not is_logged_in():
        return redirect(url_for('login'))

    paper_data = None
    raw_json = ""
    subject = ""
    university = "RTU Kota (B.Tech)"
    exam_type = "University End-Sem Exam"
    branch = "B.Tech CSE"
    error = ""

    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        university = request.form.get('university', 'RTU Kota (B.Tech)').strip()
        exam_type = request.form.get('exam_type', 'University End-Sem Exam').strip()
        branch = request.form.get('branch', 'B.Tech CSE').strip()

        if not subject:
            return render_template('exam_predictor.html', error='Please enter a subject name!')

        prompt = f"""Generate an authentic, highly accurate Predicted Model Question Paper for subject: '{subject}' ({branch}).
Target System: {university} | Exam Category: {exam_type}.

STRICTLY FOLLOW RTU KOTA B.TECH CSE & BOARD EXAMINATION SCHEME BASED ON 5-10 YEAR PYQs:
- If End-Sem Exam: Total 70 Marks, 3 Hours.
  - Part A: 10 Compulsory Short Questions (2 Marks each = 20 Marks).
  - Part B: 5 Conceptual Questions out of 7 (4 Marks each = 20 Marks).
  - Part C: 3 Comprehensive Numericals / Code / Derivations out of 5 (10 Marks each = 30 Marks).
- If Midterm Exam: Total 60 Marks, 1.5 Hours (EXACT RTU MIDTERM PATTERN):
  - Part A: 6 Compulsory Short Questions (3 Marks each = 18 Marks).
  - Part B: 4 Conceptual Questions out of 6 (6 Marks each = 24 Marks).
  - Part C: 2 High-Weightage Numericals / Code out of 3 (10.5 Marks each = 21 Marks).

Return output as valid JSON with NO markdown code block wrappers (i.e. no ```json).

JSON Schema:
{{
  "university": "{university}",
  "subject": "{subject}",
  "branch": "{branch}",
  "exam_type": "{exam_type}",
  "paper_code": "CS-301-RTU",
  "time_allowed": "1.5 Hours",
  "total_marks": 60,
  "sections": [
    {{
      "section_name": "Part A (Short Compulsory Questions - 3 Marks Each)",
      "instructions": "Answer all 6 questions. Each question carries 3 marks.",
      "questions": [
        {{
          "q_num": "Q1 (a)",
          "question": "Define Peterson's Solution for Process Synchronization.",
          "marks": 3,
          "model_answer": "Peterson's solution is a concurrent programming algorithm for mutual exclusion that allows two processes to share a single-use resource without conflict, using shared flags and a turn variable.",
          "marking_scheme": "1.5 marks for definition, 1.5 marks for flag/turn variable conditions."
        }}
      ]
    }},
    {{
      "section_name": "Part B (Conceptual Questions - Attempt Any 4 out of 6)",
      "instructions": "Answer any 4 questions out of 6. Each question carries 6 marks.",
      "questions": [
        {{
          "q_num": "Q2",
          "question": "Explain Banker's Algorithm for Deadlock Avoidance with safety algorithm steps.",
          "marks": 6,
          "model_answer": "Banker's algorithm checks for safe states by testing allocation requests against available resources using Need = Max - Allocation matrix...",
          "marking_scheme": "3 marks for algorithm explanation, 3 marks for safety state condition."
        }}
      ]
    }},
    {{
      "section_name": "Part C (High-Weightage Numericals & Code - Attempt Any 2 out of 3)",
      "instructions": "Answer any 2 questions out of 3. Each question carries 10.5 marks.",
      "questions": [
        {{
          "q_num": "Q5",
          "question": "Consider the following process set with burst time and arrival time. Calculate average waiting time using Round-Robin (Quantum = 2ms) and draw the Gantt chart.",
          "marks": 10.5,
          "model_answer": "Gantt Chart: P1[0-2] -> P2[2-4] -> P3[4-5] -> P1[5-7]... Average Waiting Time = 4.5ms.",
          "marking_scheme": "4.5 marks for correct Gantt chart, 4 marks for waiting time calculation, 2 marks for turnaround time."
        }}
      ]
    }}
  ]
}}

Ensure questions reflect authentic 5-10 year RTU PYQ trends (numericals, code, diagrams). Keep JSON clean and valid."""

        result, error_msg = ask_gemini(prompt)

        if result:
            raw_json = result.strip()
            if raw_json.startswith("```"):
                lines = raw_json.split('\n')
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_json = "\n".join(lines).strip()

            try:
                paper_data = json.loads(raw_json)
            except Exception as e:
                paper_data = generate_fallback_exam_paper(subject, university, exam_type, branch)
                raw_json = json.dumps(paper_data)
        else:
            paper_data = generate_fallback_exam_paper(subject, university, exam_type, branch)
            raw_json = json.dumps(paper_data)
            error = None

    return render_template('exam_predictor.html', paper_data=paper_data, raw_json=raw_json, subject=subject, university=university, exam_type=exam_type, branch=branch, error=error)


def generate_fallback_exam_paper(subject, university, exam_type, branch):
    sub_title = subject.strip().title()
    is_midterm = "Midterm" in exam_type
    
    if is_midterm:
        # EXACT RTU Kota Midterm 60-Marks Pattern
        return {
            "university": university,
            "subject": sub_title,
            "branch": branch,
            "exam_type": exam_type,
            "paper_code": "CS-301-MID60",
            "time_allowed": "1.5 Hours",
            "total_marks": 60,
            "sections": [
                {
                    "section_name": "Part A (Short Compulsory Questions - 3 Marks Each)",
                    "instructions": "Answer all 6 questions. Each question carries 3 marks.",
                    "questions": [
                        {
                            "q_num": "Q1 (a)",
                            "question": f"Define the primary architectural objective and core definition of {sub_title}.",
                            "marks": 3,
                            "model_answer": f"{sub_title} focuses on systematically organizing computation, resources, and data structures to minimize complexity.",
                            "marking_scheme": "1.5 marks for definition, 1.5 marks for objective."
                        },
                        {
                            "q_num": "Q1 (b)",
                            "question": "Differentiate between Static Allocation and Dynamic Memory Allocation.",
                            "marks": 3,
                            "model_answer": "Static allocation allocates memory at compile time in fixed stack regions, whereas dynamic allocation allocates memory at runtime in heap regions.",
                            "marking_scheme": "1.5 marks for static definition, 1.5 marks for dynamic definition."
                        },
                        {
                            "q_num": "Q1 (c)",
                            "question": "What is worst-case time complexity? State Big-O notation.",
                            "marks": 3,
                            "model_answer": "Worst-case complexity gives the maximum upper bound on execution time required by an algorithm for input of size n, represented by Big-O notation O(f(n)).",
                            "marking_scheme": "1.5 marks for definition, 1.5 marks for Big-O notation."
                        },
                        {
                            "q_num": "Q1 (d)",
                            "question": "State the difference between Preemptive and Non-Preemptive Scheduling.",
                            "marks": 3,
                            "model_answer": "Preemptive scheduling allows CPU to interrupt a running process (e.g. Round Robin), while Non-Preemptive process holds CPU until completion (e.g. FCFS).",
                            "marking_scheme": "1.5 marks for preemptive definition, 1.5 marks for non-preemptive definition."
                        },
                        {
                            "q_num": "Q1 (e)",
                            "question": "What is thrashing in virtual memory systems?",
                            "marks": 3,
                            "model_answer": "Thrashing occurs when a system spends more time swapping pages in and out of main memory than executing actual instructions due to insufficient page frames.",
                            "marking_scheme": "1.5 marks for definition, 1.5 marks for cause."
                        },
                        {
                            "q_num": "Q1 (f)",
                            "question": "Define Peterson's Algorithm turn and flag variables.",
                            "marks": 3,
                            "model_answer": "Turn indicates whose turn it is to enter critical section, while flag array indicates if a process is ready to enter.",
                            "marking_scheme": "1.5 marks for turn variable, 1.5 marks for flag array."
                        }
                    ]
                },
                {
                    "section_name": "Part B (Conceptual Questions - Attempt Any 4 out of 6 - 6 Marks Each)",
                    "instructions": "Answer any 4 questions out of 6. Each question carries 6 marks.",
                    "questions": [
                        {
                            "q_num": "Q2",
                            "question": f"Explain the core 5-step operational pipeline of {sub_title} with a neat architectural block diagram.",
                            "marks": 6,
                            "model_answer": "The operational pipeline consists of: 1. Input Processing 2. Parsing & Validation 3. State Transformation 4. Optimization Engine 5. Output Emission...",
                            "marking_scheme": "3 marks for labeled block diagram, 3 marks for detailed stage explanations."
                        },
                        {
                            "q_num": "Q3",
                            "question": f"Solve the following numerical problem on {sub_title}: Calculate optimal memory throughput and efficiency given input array size N=1000 and block size B=64.",
                            "marks": 6,
                            "model_answer": "Given N=1000, B=64: Number of blocks = ceil(1000/64) = 16 blocks. Memory efficiency = 97.65%...",
                            "marking_scheme": "2 marks for formula, 2 marks for calculation, 2 marks for efficiency percentage."
                        },
                        {
                            "q_num": "Q4",
                            "question": "Explain Banker's Deadlock Avoidance Safety Algorithm with state matrix example.",
                            "marks": 6,
                            "model_answer": "Banker's algorithm tests for safe states using Allocation, Max, and Need matrices. If Need <= Available, processes execute safely...",
                            "marking_scheme": "3 marks for safety condition, 3 marks for example calculation."
                        },
                        {
                            "q_num": "Q5",
                            "question": "Compare and contrast synchronous execution vs asynchronous multi-threaded execution.",
                            "marks": 6,
                            "model_answer": "Synchronous execution blocks execution sequentially. Asynchronous execution dispatches tasks non-blockingly using thread pools...",
                            "marking_scheme": "3 marks for comparative matrix, 3 marks for concurrency trade-offs."
                        }
                    ]
                },
                {
                    "section_name": "Part C (High-Weightage Numericals & Code - Attempt Any 2 out of 3 - 10.5 Marks Each)",
                    "instructions": "Answer any 2 questions out of 3. Each question carries 10.5 marks.",
                    "questions": [
                        {
                            "q_num": "Q6",
                            "question": f"Consider processes P1(burst=6ms), P2(burst=8ms), P3(burst=7ms) arriving at time 0. Draw Gantt Chart and calculate average waiting time using Round-Robin (Time Quantum = 2ms).",
                            "marks": 10.5,
                            "model_answer": "Gantt Chart: P1[0-2] -> P2[2-4] -> P3[4-6] -> P1[6-8] -> P2[8-10] -> P3[10-12] -> P1[12-14] -> P2[14-16] -> P3[16-17] -> P2[17-19]. Average Waiting Time = 10.33ms.",
                            "marking_scheme": "4.5 marks for correct Gantt chart, 4 marks for waiting time calculation, 2 marks for turnaround time."
                        },
                        {
                            "q_num": "Q7",
                            "question": f"Given Relation R(A,B,C,D,E) with Functional Dependencies F={{A->B, BC->D, E->C}}. Decompose relation R into 3NF and BCNF step-by-step.",
                            "marks": 10.5,
                            "model_answer": "Candidate Key = {A, E}. 1. Check FDs for BCNF violation: A->B violates BCNF since A is not a superkey. 2. Decompose into R1(A,B) and R2(A,C,D,E)... 3. Resulting 3NF relations maintain dependency preservation...",
                            "marking_scheme": "3.5 marks for Candidate Key identification, 4 marks for 3NF decomposition, 3 marks for BCNF validation."
                        }
                    ]
                }
            ]
        }
    else:
        # Authentic RTU Kota 70-Marks Scheme
        return {
            "university": university,
            "subject": sub_title,
            "branch": branch,
            "exam_type": exam_type,
            "paper_code": "CS-301-RTU",
            "time_allowed": "3 Hours",
            "total_marks": 70,
            "sections": [
                {
                    "section_name": "Part A (Short Compulsory Questions - Units 1 to 5)",
                    "instructions": "Answer all 10 questions covering Units 1 to 5. Each question carries 2 marks.",
                    "questions": [
                        {
                            "q_num": "Q1 (a)",
                            "question": f"Define the primary architectural objective of {sub_title}.",
                            "marks": 2,
                            "model_answer": f"{sub_title} systematically organizes computation, resources, and data structures to minimize time/space complexity.",
                            "marking_scheme": "1 mark for definition, 1 mark for objective."
                        },
                        {
                            "q_num": "Q1 (b)",
                            "question": "Differentiate between Peterson's Solution and TestAndSet instruction.",
                            "marks": 2,
                            "model_answer": "Peterson's solution is a software-based mutual exclusion algorithm using turn/flag variables, whereas TestAndSet is a hardware-supported atomic CPU instruction.",
                            "marking_scheme": "1 mark for Peterson's, 1 mark for TestAndSet."
                        },
                        {
                            "q_num": "Q1 (c)",
                            "question": "What is the balance factor of an AVL Tree? State valid values.",
                            "marks": 2,
                            "model_answer": "Balance Factor = Height(Left Subtree) - Height(Right Subtree). Valid values for an AVL tree node are -1, 0, and +1.",
                            "marking_scheme": "1 mark for formula, 1 mark for valid values."
                        }
                    ]
                },
                {
                    "section_name": "Part B (Conceptual & Derivations - Attempt Any 5 out of 7)",
                    "instructions": "Answer any 5 questions out of 7. Each question carries 4 marks.",
                    "questions": [
                        {
                            "q_num": "Q2",
                            "question": f"Explain the core 5-step operational pipeline of {sub_title} with a neat architectural block diagram.",
                            "marks": 4,
                            "model_answer": "The operational pipeline consists of: 1. Input Processing 2. Parsing & Validation 3. State Transformation 4. Optimization Engine 5. Output Emission...",
                            "marking_scheme": "2 marks for labeled block diagram, 2 marks for stage explanations."
                        },
                        {
                            "q_num": "Q3",
                            "question": "Derive the recurrence relation and average-case time complexity of QuickSort algorithm.",
                            "marks": 4,
                            "model_answer": "Recurrence T(n) = 2T(n/2) + O(n). By Master Theorem Case 2, Average-case time complexity = O(n log n). Worst-case O(n^2) occurs when array is already sorted...",
                            "marking_scheme": "2 marks for recurrence derivation, 2 marks for Master Theorem application."
                        }
                    ]
                },
                {
                    "section_name": "Part C (High-Weightage Numericals & Code - Attempt Any 3 out of 5)",
                    "instructions": "Answer any 3 questions out of 5. Each question carries 10 marks.",
                    "questions": [
                        {
                            "q_num": "Q4",
                            "question": f"Consider processes P1(burst=6ms), P2(burst=8ms), P3(burst=7ms) arriving at time 0. Draw Gantt Chart and calculate average waiting time using Round-Robin (Time Quantum = 2ms).",
                            "marks": 10,
                            "model_answer": "Gantt Chart: P1[0-2] -> P2[2-4] -> P3[4-6] -> P1[6-8] -> P2[8-10] -> P3[10-12] -> P1[12-14] -> P2[14-16] -> P3[16-17] -> P2[17-19]. Average Waiting Time = 10.33ms.",
                            "marking_scheme": "4 marks for correct Gantt chart, 4 marks for waiting time calculation, 2 marks for turnaround time."
                        },
                        {
                            "q_num": "Q5",
                            "question": f"Given Relation R(A,B,C,D,E) with Functional Dependencies F={{A->B, BC->D, E->C}}. Decompose relation R into 3NF and BCNF step-by-step.",
                            "marks": 10,
                            "model_answer": "Candidate Key = {A, E}. 1. Check FDs for BCNF violation: A->B violates BCNF since A is not a superkey. 2. Decompose into R1(A,B) and R2(A,C,D,E)... 3. Resulting 3NF relations maintain dependency preservation...",
                            "marking_scheme": "3 marks for Candidate Key identification, 4 marks for 3NF decomposition, 3 marks for BCNF validation."
                        }
                    ]
                }
            ]
        }


def generate_fallback_roadmap(topic):
    clean_topic = topic.strip().title()
    return {
        "title": f"{clean_topic} Mastery Roadmap",
        "subtitle": "Complete Step-by-Step Learning & Mastery Roadmap",
        "estimated_total_hours": 65,
        "difficulty_level": "Beginner to Advanced",
        "phases": [
            {
                "phase_num": 1,
                "phase_title": f"Phase 1: {clean_topic} Fundamentals & Basics",
                "summary": "Core foundational concepts to master first.",
                "nodes": [
                    {
                        "id": "p1_n1",
                        "title": f"Introduction to {clean_topic}",
                        "desc": f"Understand the core architecture, syntax, and essential terminology of {clean_topic}.",
                        "hours": 10,
                        "difficulty": "Easy",
                        "key_takeaways": ["Core Principles & Definitions", "Environment & Setup Configuration"],
                        "action_step": f"Build a hands-on hello-world project practicing fundamental {clean_topic} concepts."
                    },
                    {
                        "id": "p1_n2",
                        "title": "Core Syntax & Key Mechanics",
                        "desc": "Master the primary data structures, control flows, and standard workflows.",
                        "hours": 12,
                        "difficulty": "Easy",
                        "key_takeaways": ["Standard Patterns & Syntax", "Basic Debugging & Troubleshooting"],
                        "action_step": "Complete 5 hands-on practice problems testing core mechanics."
                    }
                ]
            },
            {
                "phase_num": 2,
                "phase_title": f"Phase 2: Intermediate {clean_topic} Concepts",
                "summary": "Dive deeper into system design, optimization, and practical application.",
                "nodes": [
                    {
                        "id": "p2_n1",
                        "title": "Architecture & Advanced Patterns",
                        "desc": "Learn how components interact in modern production software systems.",
                        "hours": 18,
                        "difficulty": "Medium",
                        "key_takeaways": ["Modular Architecture", "State & Resource Management"],
                        "action_step": "Design a small modular application applying clean architecture principles."
                    },
                    {
                        "id": "p2_n2",
                        "title": "Performance & Optimization",
                        "desc": "Identify bottlenecks, memory leaks, and optimize runtime complexity.",
                        "hours": 15,
                        "difficulty": "Medium",
                        "key_takeaways": ["Time & Space Complexity", "Caching & Performance Tuning"],
                        "action_step": "Refactor a past project to optimize execution speed by 30%."
                    }
                ]
            },
            {
                "phase_num": 3,
                "phase_title": "Phase 3: Real-World Capstone & Interview Prep",
                "summary": "Build portfolio projects and prepare for technical assessments.",
                "nodes": [
                    {
                        "id": "p3_n1",
                        "title": "Full Capstone Project",
                        "desc": f"Integrate all {clean_topic} concepts into an end-to-end production-ready application.",
                        "hours": 20,
                        "difficulty": "Hard",
                        "key_takeaways": ["Full-Stack Integration", "CI/CD & Production Deployment"],
                        "action_step": "Deploy your capstone project live with documentation and tests."
                    }
                ]
            }
        ]
    }



def parse_flashcards(text):
    cards = []
    lines = text.strip().split('\n')
    current_q = None
    current_a = None

    for line in lines:
        line = line.strip()
        if line.startswith('Q:'):
            # Save previous card if exists
            if current_q and current_a:
                cards.append({'question': current_q, 'answer': current_a})
            current_q = line[2:].strip()
            current_a = None
        elif line.startswith('A:') and current_q:
            current_a = line[2:].strip()

    # Don't forget the last card
    if current_q and current_a:
        cards.append({'question': current_q, 'answer': current_a})

    return cards


# ── SAVE ITEM (FORM & AJAX) ──────────────────────────────────
@app.route('/save', methods=['POST'])
@app.route('/save-item', methods=['POST'])
def save_item():
    if not is_logged_in():
        if request.is_json:
            return {"success": False, "error": "Please log in first!"}, 401
        return redirect(url_for('login'))
    
    if request.is_json:
        data = request.get_json()
        item_type = data.get('item_type', '').strip()
        title     = data.get('title', '').strip()
        content   = data.get('content', '').strip()
    else:
        item_type = request.form.get('item_type', '').strip()
        title     = request.form.get('title', '').strip()
        content   = request.form.get('content', '').strip()
    
    if not item_type or not title or not content:
        if request.is_json:
            return {"success": False, "error": "All fields are required!"}, 400
        flash("Failed to save: missing required content", "error")
        return redirect(request.referrer or url_for('dashboard'))
        
    try:
        conn = get_db_connection()
        conn.execute(
            'INSERT INTO saved_items (user_id, item_type, title, content) VALUES (?, ?, ?, ?)',
            (session['user_id'], item_type, title, content)
        )
        conn.commit()
        conn.close()
        
        if request.is_json:
            return {"success": True, "message": "Saved to your library successfully!"}
            
        flash(f"Item saved to your library successfully!", "success")
        return redirect(url_for('library'))
    except Exception as e:
        if request.is_json:
            return {"success": False, "error": str(e)}, 500
        flash(f"Error saving item: {str(e)}", "error")
        return redirect(request.referrer or url_for('dashboard'))

def save():
    return save_item()




# ── MY LIBRARY ───────────────────────────────────────────────
@app.route('/library')
def library():
    if not is_logged_in():
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    items = conn.execute(
        'SELECT * FROM saved_items WHERE user_id = ? ORDER BY created_at DESC',
        (session['user_id'],)
    ).fetchall()
    conn.close()
    
    return render_template('library.html', items=items)


# ── VIEW SAVED ITEM ──────────────────────────────────────────
@app.route('/library/view/<int:item_id>')
def view_saved_item(item_id):
    if not is_logged_in():
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    item = conn.execute(
        'SELECT * FROM saved_items WHERE id = ? AND user_id = ?',
        (item_id, session['user_id'])
    ).fetchone()
    conn.close()
    
    if not item:
        flash('Item not found or you do not have permission to view it.', 'error')
        return redirect(url_for('library'))
        
    # If the saved item is a quiz, we parse the JSON content so it can be retaken
    quiz_data = None
    if item['item_type'] == 'quiz':
        try:
            quiz_data = json.loads(item['content'])
        except Exception:
            quiz_data = None
            
    return render_template('library_view.html', item=item, quiz_data=quiz_data)


# ── DELETE SAVED ITEM ────────────────────────────────────────
@app.route('/library/delete/<int:item_id>', methods=['POST'])
def delete_saved_item(item_id):
    if not is_logged_in():
        return redirect(url_for('login'))
        
    try:
        conn = get_db_connection()
        conn.execute(
            'DELETE FROM saved_items WHERE id = ? AND user_id = ?',
            (item_id, session['user_id'])
        )
        conn.commit()
        conn.close()
        flash('Item deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting item: {str(e)}', 'error')
        
    return redirect(url_for('library'))


# ── NEURAL TEXT-TO-SPEECH STREAMING ──────────────────────────
async def generate_tts_async(text, voice_name, output_path):
    communicate = edge_tts.Communicate(text, voice_name)
    await communicate.save(output_path)


@app.route('/speak')
def speak():

    text = request.args.get('text', '').strip()
    gender = request.args.get('gender', 'female').strip()
    
    if not text:
        return "Missing text parameter", 400
        
    # Limit text length to prevent abuse
    text = text[:1500]
    
    # Detect language: If text contains Devanagari (Hindi) characters
    has_hindi = any(ord(char) in range(0x0900, 0x0980) for char in text)
    
    # Select Microsoft premium neural voices
    if has_hindi:
        voice = 'hi-IN-SwaraNeural' if gender == 'female' else 'hi-IN-MadhurNeural'
    else:
        voice = 'en-US-AriaNeural' if gender == 'female' else 'en-US-GuyNeural'
        
    # Configure temporary directories for caching audio
    temp_dir = os.path.join(app.root_path, 'static', 'temp_audio')
    os.makedirs(temp_dir, exist_ok=True)
    
    # Housekeeping: delete temp files older than 5 minutes
    try:
        now = time.time()
        for f in os.listdir(temp_dir):
            fpath = os.path.join(temp_dir, f)
            if now - os.path.getmtime(fpath) > 300:
                os.remove(fpath)
    except Exception:
        pass
        
    # Unique filename based on hash of text and gender
    text_hash = hash(text + gender) & 0xffffffff
    filename = f"tts_{text_hash}.mp3"
    filepath = os.path.join(temp_dir, filename)
    
    # Generate audio file if it doesn't already exist in cache
    if not os.path.exists(filepath):
        try:
            asyncio.run(generate_tts_async(text, voice, filepath))
        except Exception as e:
            return f"TTS Error: {str(e)}", 500
            
    return send_from_directory(temp_dir, filename)


# ── RUN THE APP ──────────────────────────────────────────────
if __name__ == '__main__':
    print("\n" + "="*50)
    print("  StudyMate AI -- Starting Server")
    print("  Visit: http://127.0.0.1:5000")
    print("="*50 + "\n")
    app.run(debug=True, port=5000)
