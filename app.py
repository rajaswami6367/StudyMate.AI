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
import time

from flask import Flask, render_template, request, redirect, url_for, session, flash
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
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT    NOT NULL,
            email    TEXT    UNIQUE NOT NULL,
            password TEXT    NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    print("[OK] Database initialized successfully!")

# Initialize DB when app starts
init_db()

# ── STEP 6: Helper Function for Gemini API calls ─────────────
def ask_gemini(prompt):
    """
    Sends a prompt to Gemini AI and returns the response text.
    
    WHY a separate function?
    Before, you had the same retry code copy-pasted in 4 places.
    Now it's in ONE place. If we want to change the model or
    add logging, we only change it here. This is called DRY:
    Don't Repeat Yourself — a key professional principle.
    
    Returns: (result_text, error_message)
    """
    if not client:
        return None, "⚠️ AI not configured. Please add your GEMINI_API_KEY in the .env file."
    
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-flash-latest',
                contents=prompt
            )
            return response.text, None  # Success!

        except Exception as e:
            error_str = str(e)
            # 429 = Too Many Requests (quota limit hit)
            if "429" in error_str and attempt < 2:
                print(f"⏳ Rate limit hit, waiting 5 seconds... (attempt {attempt + 1}/3)")
                time.sleep(5)
                continue
            else:
                # Final failure
                return None, f"AI Error: {error_str}"

    return None, "Quota limit reached. Please wait a moment and try again."


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
    return render_template('dashboard.html', username=session.get('username'))


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

        prompt = f"""You are a helpful study assistant for students.
Answer the following question clearly and simply.
Use examples where helpful. Format your answer nicely.

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

    quiz_result = ""
    topic = ""

    if request.method == 'POST':
        topic = request.form.get('topic', '').strip()

        if not topic:
            return render_template('quiz_generator.html', error='Please enter a topic!')

        prompt = f"""Create a multiple-choice quiz with 5 questions on the topic: {topic}

Format each question exactly like this:
Q1. [Question here]
A) [Option A]
B) [Option B]
C) [Option C]
D) [Option D]
✅ Correct Answer: [Letter] - [Brief explanation]

Make questions clear, educational, and appropriate for college students."""

        result, error = ask_gemini(prompt)
        quiz_result = result if result else error

    return render_template('quiz_generator.html', quiz_result=quiz_result, topic=topic)


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

        prompt = f"""Generate comprehensive, well-structured study notes on: {topic}

Please format them clearly with:
# Introduction
[Brief intro]

# Key Concepts
[Main concepts with explanations]

# Important Points
[Bullet points of must-remember facts]

# Formulas / Definitions (if applicable)
[Any relevant formulas or definitions]

# Summary
[3-4 line summary]

Make it clear, educational, and easy to understand for a B.Tech student."""

        result, error = ask_gemini(prompt)
        notes_result = result if result else error

    return render_template('ai_notes.html', notes_result=notes_result, topic=topic)


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


def parse_flashcards(text):
    """
    Converts raw AI text into a structured list of flashcard dicts.
    
    Input:  "Q: What is RAM?\nA: Random Access Memory..."
    Output: [{'question': 'What is RAM?', 'answer': 'Random Access Memory...'}, ...]
    """
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


# ── RUN THE APP ──────────────────────────────────────────────
if __name__ == '__main__':
    print("\n" + "="*50)
    print("  StudyMate AI -- Starting Server")
    print("  Visit: http://127.0.0.1:5000")
    print("="*50 + "\n")
    app.run(debug=True, port=5000)
