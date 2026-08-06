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

        prompt = f"""Generate a comprehensive, structured Visual Learning Roadmap & Mind Map for the topic/career path: '{topic}'.
Return the output as a valid JSON object with NO markdown code block wrappers (i.e. no ```json).

The JSON object must have this exact structure:
{{
  "title": "{topic}",
  "subtitle": "Complete Step-by-Step Learning & Mastery Roadmap",
  "estimated_total_hours": 80,
  "difficulty_level": "Beginner to Advanced",
  "phases": [
    {{
      "phase_num": 1,
      "phase_title": "Phase 1: Foundations & Prerequisites",
      "icon": "book-open",
      "summary": "Core concepts to learn first before diving deeper.",
      "nodes": [
        {{
          "id": "p1_n1",
          "title": "Topic Title",
          "desc": "Short explanation of what this topic covers and why it's important.",
          "hours": 10,
          "difficulty": "Easy",
          "key_takeaways": ["Takeaway 1", "Takeaway 2"],
          "action_step": "Practice exercise or mini project suggestion"
        }}
      ]
    }}
  ]
}}

Provide 3 to 4 distinct phases (e.g. Phase 1: Foundations, Phase 2: Core Concepts, Phase 3: Advanced Topics, Phase 4: Real-World Projects).
Each phase should contain 2 to 4 nodes.
Ensure the JSON is valid, properly escaped, and strictly follows the schema."""

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
                error = f"Failed to parse AI Roadmap data: {str(e)}"
        else:
            error = error_msg

    return render_template('roadmap.html', roadmap_data=roadmap_data, raw_json=raw_json, topic=topic, error=error)



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


# ── SAVE ITEM (AJAX) ─────────────────────────────────────────
@app.route('/save-item', methods=['POST'])
def save_item():
    """Saves an AI response to the user's library."""
    if not is_logged_in():
        return {"success": False, "error": "Please log in first!"}, 401
    
    data = request.get_json()
    if not data:
        return {"success": False, "error": "Invalid request data!"}, 400
        
    item_type = data.get('item_type', '').strip()
    title     = data.get('title', '').strip()
    content   = data.get('content', '').strip()
    
    if not item_type or not title or not content:
        return {"success": False, "error": "All fields are required!"}, 400
        
    try:
        conn = get_db_connection()
        conn.execute(
            'INSERT INTO saved_items (user_id, item_type, title, content) VALUES (?, ?, ?, ?)',
            (session['user_id'], item_type, title, content)
        )
        conn.commit()
        conn.close()
        return {"success": True, "message": "Saved to your library successfully!"}
    except Exception as e:
        return {"success": False, "error": str(e)}, 500


# ── MY LIBRARY ───────────────────────────────────────────────
@app.route('/library')
def library():
    """Displays all items saved by the logged-in user."""
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
    """Shows a single saved item in full detail."""
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
    """Deletes a saved item from the user's library."""
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
    """Asynchronously communicates with Edge TTS servers to generate audio."""
    communicate = edge_tts.Communicate(text, voice_name)
    await communicate.save(output_path)


@app.route('/speak')
def speak():
    """Generates and streams high-fidelity neural MP3 voice audio."""
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
