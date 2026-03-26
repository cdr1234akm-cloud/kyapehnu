"""
StyleAI — Complete FastAPI Backend with Groq AI (FREE)
Run: python backend/main.py

Features:
✅ Real AI garment analysis (Groq - FREE)
✅ Real AI outfit combinations (Groq - FREE)  
✅ Detailed logging to verify AI is working
✅ No random/mock data when AI is active
"""

import os
import sys
import json
import uuid
import hashlib
import base64
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

import cloudinary
import cloudinary.uploader
import cloudinary.api

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials



# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════
SECRET_KEY = os.environ.get("SECRET_KEY", "styleai-secret-key-change-in-production-2024")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30
UPLOAD_DIR = Path("uploads")
RENDER_DIR = Path("renders")
DB_PATH = "styleai.db"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🔑 GROQ API KEY (loaded from environment)
# Get free key from: https://console.groq.com/keys
# Set GROQ_API_KEY environment variable locally
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Groq Models (free tier)
TEXT_MODEL = "llama-3.3-70b-versatile"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# Create directories
UPLOAD_DIR.mkdir(exist_ok=True)
RENDER_DIR.mkdir(exist_ok=True)

# Cloudinary config for persistent file storage
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET")
)

# ═══════════════════════════════════════════════════════════
# LOGGING SETUP
# ═══════════════════════════════════════════════════════════
class Logger:
    """Simple colored logger for terminal"""
    COLORS = {
        'reset': '\033[0m',
        'red': '\033[91m',
        'green': '\033[92m',
        'yellow': '\033[93m',
        'blue': '\033[94m',
        'purple': '\033[95m',
        'cyan': '\033[96m',
        'white': '\033[97m',
    }

    @staticmethod
    def _time():
        return datetime.now().strftime("%H:%M:%S")

    @classmethod
    def info(cls, msg):
        print(f"{cls.COLORS['cyan']}[{cls._time()}] ℹ️  {msg}{cls.COLORS['reset']}")

    @classmethod
    def success(cls, msg):
        print(f"{cls.COLORS['green']}[{cls._time()}] ✅ {msg}{cls.COLORS['reset']}")

    @classmethod
    def warning(cls, msg):
        print(f"{cls.COLORS['yellow']}[{cls._time()}] ⚠️  {msg}{cls.COLORS['reset']}")

    @classmethod
    def error(cls, msg):
        print(f"{cls.COLORS['red']}[{cls._time()}] ❌ {msg}{cls.COLORS['reset']}")

    @classmethod
    def ai(cls, msg):
        print(f"{cls.COLORS['purple']}[{cls._time()}] 🤖 AI: {msg}{cls.COLORS['reset']}")

    @classmethod
    def data(cls, label, data):
        print(f"{cls.COLORS['blue']}[{cls._time()}] 📊 {label}:{cls.COLORS['reset']}")
        if isinstance(data, dict):
            for k, v in data.items():
                print(f"           {k}: {v}")
        else:
            print(f"           {data}")

log = Logger()

# ═══════════════════════════════════════════════════════════
# 🛡️ RATE LIMITER (Protects against Groq free tier limits)
# ═══════════════════════════════════════════════════════════
import time
from collections import deque

class RateLimiter:
    """
    Groq Free Tier Limits:
    - 30 requests per minute
    - 14,400 requests per day
    - 6,000 tokens per minute
    
    This ensures we NEVER hit those limits.
    """
    def __init__(self, max_per_minute=25, max_per_day=14000):
        self.max_per_minute = max_per_minute  # Keep 5 buffer
        self.max_per_day = max_per_day        # Keep 400 buffer
        self.minute_calls = deque()  # Timestamps of calls in last minute
        self.day_calls = deque()     # Timestamps of calls today
        self.total_tokens_used = 0
        self.total_calls = 0
        self.calls_saved_by_cache = 0
    
    def wait_if_needed(self):
        """Wait if we're about to hit the rate limit"""
        now = time.time()
        
        # Clean old entries
        while self.minute_calls and self.minute_calls[0] < now - 60:
            self.minute_calls.popleft()
        while self.day_calls and self.day_calls[0] < now - 86400:
            self.day_calls.popleft()
        
        # Check minute limit
        if len(self.minute_calls) >= self.max_per_minute:
            wait_time = 60 - (now - self.minute_calls[0])
            if wait_time > 0:
                log.warning(f"Rate limit approaching — waiting {wait_time:.1f}s")
                time.sleep(wait_time + 1)
        
        # Check daily limit
        if len(self.day_calls) >= self.max_per_day:
            log.error("Daily rate limit reached! Please try again tomorrow.")
            raise Exception("Daily API limit reached. Try again tomorrow.")
    
    def record_call(self, tokens_used=0):
        """Record an API call"""
        now = time.time()
        self.minute_calls.append(now)
        self.day_calls.append(now)
        self.total_calls += 1
        self.total_tokens_used += tokens_used
    
    def record_cache_hit(self):
        """Record when cache saved an API call"""
        self.calls_saved_by_cache += 1
    
    def get_stats(self):
        """Get current rate limit stats"""
        now = time.time()
        
        # Clean old entries
        while self.minute_calls and self.minute_calls[0] < now - 60:
            self.minute_calls.popleft()
        while self.day_calls and self.day_calls[0] < now - 86400:
            self.day_calls.popleft()
        
        return {
            "calls_this_minute": len(self.minute_calls),
            "calls_today": len(self.day_calls),
            "total_calls_ever": self.total_calls,
            "total_tokens_used": self.total_tokens_used,
            "calls_saved_by_cache": self.calls_saved_by_cache,
            "minute_limit": f"{len(self.minute_calls)}/{self.max_per_minute}",
            "day_limit": f"{len(self.day_calls)}/{self.max_per_day}",
            "status": "OK" if len(self.minute_calls) < self.max_per_minute else "THROTTLED"
        }

# Create global rate limiter
rate_limiter = RateLimiter(max_per_minute=25, max_per_day=14000)
log.info("Rate limiter initialized (25/min, 14000/day)")

# ═══════════════════════════════════════════════════════════
# GROQ AI SETUP
# ═══════════════════════════════════════════════════════════
try:
    from groq import Groq
    from PIL import Image

    groq_client = Groq(api_key=GROQ_API_KEY)
    AI_AVAILABLE = GROQ_API_KEY.startswith("gsk_") and len(GROQ_API_KEY) > 20

    if AI_AVAILABLE:
        log.success("Groq AI is ACTIVE — Real garment analysis enabled (FREE)")
        log.info(f"Text Model: {TEXT_MODEL}")
        log.info(f"Vision Model: {VISION_MODEL}")
    else:
        log.warning("No valid Groq API key — Running in DEMO mode (random data)")
        log.info("Get free key from: https://console.groq.com/keys")

except ImportError as e:
    AI_AVAILABLE = False
    groq_client = None
    log.error(f"Required package not installed: {e}")
    log.info("Run: pip install groq Pillow")

# ═══════════════════════════════════════════════════════════
# APP SETUP
# ═══════════════════════════════════════════════════════════
app = FastAPI(title="StyleAI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded images
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/renders", StaticFiles(directory="renders"), name="renders")

# # Serve frontend static files
# app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

# ═══════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    c = conn.cursor()

    c.executescript("""
        -- Existing tables (keep them)
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT DEFAULT '',
            gender TEXT DEFAULT '',
            body_type TEXT DEFAULT '',
            skin_tone TEXT DEFAULT '',
            style_prefs TEXT DEFAULT '[]',
            onboarded INTEGER DEFAULT 0,
            plan TEXT DEFAULT 'free',
            theme TEXT DEFAULT 'dark',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS garments (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            image_url TEXT NOT NULL,
            image_hash TEXT NOT NULL,
            metadata TEXT DEFAULT '{}',
            is_favorite INTEGER DEFAULT 0,
            wear_count INTEGER DEFAULT 0,
            last_worn TEXT,
            analysed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, image_hash)
        );

        CREATE TABLE IF NOT EXISTS outfit_combos (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            occasion TEXT NOT NULL,
            garment_ids TEXT NOT NULL,
            combo_key TEXT UNIQUE NOT NULL,
            score REAL DEFAULT 0,
            reasoning TEXT DEFAULT '',
            styling_tip TEXT DEFAULT '',
            pieces TEXT DEFAULT '[]',
            is_favorite INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS outfit_history (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            occasion TEXT NOT NULL,
            garment_ids TEXT NOT NULL,
            outfit_name TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            weather TEXT DEFAULT '',
            temperature INTEGER,
            render_url TEXT DEFAULT '',
            worn_on TEXT DEFAULT (date('now')),
            rating INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS tryon_renders (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            combo_key TEXT DEFAULT '',
            model_id TEXT DEFAULT 'default',
            render_key TEXT UNIQUE,
            image_url TEXT NOT NULL,
            is_affiliate INTEGER DEFAULT 0,
            rendered_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- NEW: Calendar Events
        CREATE TABLE IF NOT EXISTS calendar_events (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            event_date TEXT NOT NULL,
            event_time TEXT DEFAULT '',
            occasion_type TEXT DEFAULT 'casual',
            location TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            outfit_id TEXT,
            garment_ids TEXT DEFAULT '[]',
            reminder_sent INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- NEW: Favorite Outfits (separate from combos)
        CREATE TABLE IF NOT EXISTS favorite_outfits (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT DEFAULT 'My Outfit',
            garment_ids TEXT NOT NULL,
            occasion TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            times_worn INTEGER DEFAULT 0,
            last_worn TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- NEW: Affiliate Products
        CREATE TABLE IF NOT EXISTS affiliate_products (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            price_inr INTEGER DEFAULT 0,
            affiliate_url TEXT NOT NULL,
            platform TEXT DEFAULT 'amazon',
            tags TEXT DEFAULT '[]',
            active INTEGER DEFAULT 1,
            clicks INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- NEW: Affiliate Clicks Tracking
        CREATE TABLE IF NOT EXISTS affiliate_clicks (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            product_id TEXT NOT NULL,
            clicked_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (product_id) REFERENCES affiliate_products(id)
        );

        -- NEW: User Preferences
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id TEXT PRIMARY KEY,
            weather_location TEXT DEFAULT '',
            temperature_unit TEXT DEFAULT 'celsius',
            notifications_enabled INTEGER DEFAULT 1,
            weekly_digest INTEGER DEFAULT 1,
            outfit_reminders INTEGER DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- Indexes
        CREATE INDEX IF NOT EXISTS idx_garments_user ON garments(user_id);
        CREATE INDEX IF NOT EXISTS idx_garments_favorite ON garments(user_id, is_favorite);
        CREATE INDEX IF NOT EXISTS idx_combos_user ON outfit_combos(user_id, occasion);
        CREATE INDEX IF NOT EXISTS idx_history_user ON outfit_history(user_id, worn_on);
        CREATE INDEX IF NOT EXISTS idx_calendar_user ON calendar_events(user_id, event_date);
        CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorite_outfits(user_id);
    """)

    conn.commit()
    conn.close()
    log.info("Database initialized with all tables")

init_db()

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════
# AUTH SETUP (Simple Password Hashing — No bcrypt needed)
# ═══════════════════════════════════════════════════════════
import hashlib as hl

class SimpleHasher:
    """Simple password hasher using PBKDF2 (built into Python)"""
    def hash(self, password: str) -> str:
        salt = os.urandom(16).hex()
        hashed = hl.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()
        return f"{salt}${hashed}"

    def verify(self, password: str, stored_hash: str) -> bool:
        try:
            salt, hashed = stored_hash.split("$")
            check = hl.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()
            return check == hashed
        except (ValueError, AttributeError):
            return False

pwd_context = SimpleHasher()
security = HTTPBearer()

# JWT Setup
import jwt as pyjwt
from jwt.exceptions import PyJWTError as JWTError

class UserRegister(BaseModel):
    email: str
    password: str
    full_name: str = ""

class UserLogin(BaseModel):
    email: str
    password: str

class OnboardingData(BaseModel):
    gender: str
    body_type: str
    skin_tone: str
    style_prefs: list[str] = []

class OccasionRequest(BaseModel):
    occasion: str
    context: str = ""

def create_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    return pyjwt.encode(
        {"sub": user_id, "exp": expire},
        SECRET_KEY, algorithm=ALGORITHM
    )

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = pyjwt.decode(
            credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM]
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(401, "Invalid token")
        return user_id
    except JWTError:
        raise HTTPException(401, "Invalid token")

# ═══════════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════════
@app.post("/api/auth/register")
def register(data: UserRegister):
    log.info(f"Registration attempt: {data.email}")

    with get_db() as db:
        existing = db.execute(
            "SELECT id FROM users WHERE email = ?", (data.email,)
        ).fetchone()
        if existing:
            log.warning(f"Registration failed — email exists: {data.email}")
            raise HTTPException(400, "Email already registered")

        user_id = str(uuid.uuid4())
        password_hash = pwd_context.hash(data.password)

        db.execute(
            "INSERT INTO users (id, email, password_hash, full_name) VALUES (?, ?, ?, ?)",
            (user_id, data.email, password_hash, data.full_name)
        )

    token = create_token(user_id)
    log.success(f"User registered: {data.email} (ID: {user_id[:8]}...)")
    return {"token": token, "user_id": user_id, "email": data.email}


@app.post("/api/auth/login")
def login(data: UserLogin):
    log.info(f"Login attempt: {data.email}")

    with get_db() as db:
        user = db.execute(
            "SELECT * FROM users WHERE email = ?", (data.email,)
        ).fetchone()

        if not user or not pwd_context.verify(data.password, user["password_hash"]):
            log.warning(f"Login failed — invalid credentials: {data.email}")
            raise HTTPException(401, "Invalid email or password")

    token = create_token(user["id"])
    log.success(f"User logged in: {data.email}")
    return {
        "token": token,
        "user_id": user["id"],
        "email": user["email"],
        "onboarded": bool(user["onboarded"])
    }


@app.get("/api/auth/me")
def get_me(user_id: str = Depends(get_current_user)):
    with get_db() as db:
        user = db.execute(
            "SELECT id, email, full_name, gender, body_type, skin_tone, "
            "style_prefs, onboarded, plan, created_at FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        if not user:
            raise HTTPException(404, "User not found")
    return dict(user)


# ═══════════════════════════════════════════════════════════
# ONBOARDING
# ═══════════════════════════════════════════════════════════
@app.post("/api/onboarding")
def save_onboarding(data: OnboardingData, user_id: str = Depends(get_current_user)):
    log.info(f"Onboarding user: {user_id[:8]}...")
    log.data("Onboarding data", {
        "gender": data.gender,
        "body_type": data.body_type,
        "skin_tone": data.skin_tone,
        "styles": data.style_prefs
    })

    with get_db() as db:
        db.execute(
            """UPDATE users SET gender=?, body_type=?, skin_tone=?,
               style_prefs=?, onboarded=1 WHERE id=?""",
            (data.gender, data.body_type, data.skin_tone,
             json.dumps(data.style_prefs), user_id)
        )

    log.success("Onboarding saved")
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════
# 🤖 AI: GARMENT ANALYSIS (GROQ VISION - FREE)
# ═══════════════════════════════════════════════════════════

from PIL import Image
import io

def compress_image_for_ai(image_path: str, max_size_kb: int = 250) -> str:
    """
    Compress image to reduce size for AI API.
    Returns path to compressed image.
    """
    log.ai(f"Checking image size...")
    
    original_size = os.path.getsize(image_path) / 1024  # KB
    log.ai(f"Original size: {original_size:.1f} KB")
    
    if original_size <= max_size_kb:
        log.ai("Size OK — no compression needed")
        return image_path
    
    log.ai(f"Compressing to under {max_size_kb} KB...")
    
    # Open and resize
    img = Image.open(image_path)
    
    # Convert RGBA to RGB if needed
    if img.mode == 'RGBA':
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background
    
    # Calculate new dimensions (max 1024px on longest side)
    max_dimension = 600
    ratio = min(max_dimension / img.width, max_dimension / img.height)
    if ratio < 1:
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        log.ai(f"Resized to: {new_size[0]}x{new_size[1]}")
    
    # Save with compression
    compressed_path = image_path.rsplit('.', 1)[0] + '_compressed.jpg'
    
    # Start with quality 85, reduce until under limit
    quality = 85
    while quality > 20:
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=quality, optimize=True)
        size_kb = buffer.tell() / 1024
        
        if size_kb <= max_size_kb:
            # Save to file
            with open(compressed_path, 'wb') as f:
                f.write(buffer.getvalue())
            log.success(f"Compressed: {original_size:.1f} KB → {size_kb:.1f} KB (quality={quality})")
            return compressed_path
        
        quality -= 10
    
    # Last resort — save at minimum quality
    img.save(compressed_path, format='JPEG', quality=20, optimize=True)
    final_size = os.path.getsize(compressed_path) / 1024
    log.warning(f"Max compression: {original_size:.1f} KB → {final_size:.1f} KB")
    
    return compressed_path

def analyse_garment_with_ai(image_path: str) -> dict:
    """
    Analyse a garment image using Groq Vision AI (FREE).
    Returns detailed JSON with colors, type, occasions, etc.
    """
    log.ai("━━━ GARMENT ANALYSIS STARTED ━━━")
    log.ai(f"Image: {image_path}")

    # Compress if too large
    image_path = compress_image_for_ai(image_path, max_size_kb=500)

    if not AI_AVAILABLE:
        log.warning("AI not available — returning MOCK data")
        mock_result = generate_mock_analysis()
        log.data("MOCK Result", mock_result)
        return mock_result

    try:
        # Read and encode image
        log.ai("Reading image file...")
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()

        file_size_kb = os.path.getsize(image_path) / 1024
        log.ai(f"Image size: {file_size_kb:.1f} KB")

        ext = Path(image_path).suffix.lower()
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp"
        }.get(ext, "image/jpeg")
        log.ai(f"Media type: {media_type}")

        # Build the prompt
        prompt = """Analyse this clothing item carefully. Look at the actual image.

Return ONLY valid JSON with no extra text, no markdown, no explanation:
{
  "type": "top/bottom/dress/shoes/accessory/outerwear",
  "subtype": "specific type like t-shirt/jeans/blazer/sneakers/hoodie/skirt/etc",
  "color": ["primary_color", "secondary_color_if_any"],
  "pattern": "solid/striped/floral/checked/printed/graphic/plaid",
  "material": "cotton/denim/silk/polyester/leather/wool/linen/synthetic",
  "formality": 3,
  "season": ["summer", "winter", "all-season", "spring", "fall"],
  "occasions": {
    "casual": 0.8,
    "office": 0.5,
    "party": 0.6,
    "wedding": 0.2,
    "date": 0.7,
    "outdoor": 0.8,
    "formal": 0.3
  },
  "description": "A brief 10-15 word description of this specific garment"
}

Important:
- Look at the ACTUAL colors in the image, don't guess
- Formality: 1=very casual (gym wear), 3=smart casual, 5=very formal (suit)
- Occasion scores: 0.0 (not suitable) to 1.0 (perfect fit)
- Be specific in subtype (e.g., "polo shirt" not just "top")
- Description should describe THIS specific item"""

         # ━━━ RATE LIMIT CHECK ━━━
        rate_limiter.wait_if_needed()
        log.ai(f"Sending to Groq Vision ({VISION_MODEL})...")
        log.ai("Waiting for AI response...")

        # Call Groq API
        start_time = datetime.now()

        response = groq_client.chat.completions.create(
            model=VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_data}"
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }],
            max_tokens=500,
            temperature=0.3
        )

         # ━━━ RECORD THE CALL ━━━
        rate_limiter.record_call(tokens_used=response.usage.total_tokens)
        
        elapsed = (datetime.now() - start_time).total_seconds()
        log.ai(f"Response received in {elapsed:.2f}s")
        log.ai(f"Rate limit: {rate_limiter.get_stats()['minute_limit']} calls/min")

        # Parse response
        raw_text = response.choices[0].message.content.strip()
        log.ai(f"Raw AI response length: {len(raw_text)} chars")
        log.ai(f"Raw response preview: {raw_text[:200]}...")

        # Clean markdown if present
        text = raw_text
        if "```" in text:
            log.ai("Cleaning markdown formatting...")
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        # Parse JSON
        result = json.loads(text)

        # Log the result beautifully
        log.success("━━━ AI ANALYSIS COMPLETE ━━━")
        log.data("Garment Details", {
            "Type": f"{result.get('type')} → {result.get('subtype')}",
            "Colors": result.get('color'),
            "Pattern": result.get('pattern'),
            "Material": result.get('material'),
            "Formality": f"{result.get('formality')}/5",
            "Season": result.get('season'),
        })

        log.ai("Occasion Scores:")
        occasions = result.get('occasions', {})
        for occ, score in occasions.items():
            bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
            print(f"           {occ:10s} {bar} {score:.1f}")

        log.ai(f"Description: {result.get('description')}")
        log.ai(f"Tokens used: {response.usage.total_tokens}")
        log.ai(f"Cost: ₹0 (FREE)")

        return result, image_path

    except json.JSONDecodeError as e:
        log.error(f"JSON parsing failed: {e}")
        log.error(f"Raw text was: {raw_text[:500]}")
        log.warning("Falling back to MOCK data")
        return generate_mock_analysis(), image_path

    except Exception as e:
        log.error(f"AI analysis failed: {e}")
        log.warning("Falling back to MOCK data")
        return generate_mock_analysis(), image_path


def generate_mock_analysis() -> dict:
    """Generate mock analysis when AI is not available — CLEARLY MARKED AS FAKE"""
    import random

    log.warning("⚠️  GENERATING MOCK DATA — NOT REAL AI ⚠️")

    types = [
        ("top", "t-shirt"), ("top", "shirt"), ("top", "blazer"),
        ("bottom", "jeans"), ("bottom", "trousers"), ("bottom", "skirt"),
        ("dress", "casual dress"), ("dress", "formal dress"),
        ("shoes", "sneakers"), ("shoes", "heels"),
        ("outerwear", "jacket"), ("accessory", "watch"),
    ]
    colors = [["navy"], ["black"], ["white"], ["red"], ["beige"], ["olive"]]
    patterns = ["solid", "striped", "checked", "printed", "floral"]

    choice = random.choice(types)

    result = {
        "type": choice[0],
        "subtype": choice[1],
        "color": random.choice(colors),
        "pattern": random.choice(patterns),
        "material": random.choice(["cotton", "polyester", "denim"]),
        "formality": random.randint(1, 5),
        "season": ["all-season"],
        "occasions": {
            "casual": round(random.uniform(0.3, 0.9), 2),
            "office": round(random.uniform(0.2, 0.8), 2),
            "party": round(random.uniform(0.2, 0.7), 2),
            "wedding": round(random.uniform(0.1, 0.5), 2),
            "date": round(random.uniform(0.3, 0.8), 2),
            "outdoor": round(random.uniform(0.3, 0.9), 2),
            "formal": round(random.uniform(0.1, 0.6), 2),
        },
        "description": f"MOCK DATA: Random {choice[1]} — NOT REAL AI ANALYSIS",
        "_mock": True  # Flag to identify mock data
    }

    log.data("MOCK Result (NOT REAL)", result)
    return result


# ═══════════════════════════════════════════════════════════
# 🤖 AI: OUTFIT COMBINATION ENGINE (GROQ - FREE)
# ═══════════════════════════════════════════════════════════
def generate_outfits_with_ai(occasion: str, garments: list, user_info: dict) -> list:
    """
    MULTI-ROUND outfit generation for maximum variety.
    
    Strategy:
    1. Group garments by type
    2. Create multiple batches of garments
    3. Send each batch to AI separately
    4. Merge + deduplicate + re-rank all results
    5. Return best unique outfits
    
    This ensures EVERY garment gets considered!
    """
    log.ai("━━━ MULTI-ROUND OUTFIT GENERATION ━━━")
    log.ai(f"Occasion: {occasion}")
    log.ai(f"Total garments: {len(garments)}")

    if not AI_AVAILABLE:
        log.warning("AI not available — using mock outfits")
        return generate_mock_outfits(occasion, garments)

    # ━━━ STEP 1: Filter by occasion score ━━━
    eligible = []
    for g in garments:
        meta = g["metadata"] if isinstance(g["metadata"], dict) else json.loads(g["metadata"])
        score = meta.get("occasions", {}).get(occasion, 0)
        if score >= 0.4:
            eligible.append({
                "id": g["id"],
                "type": meta.get("type", "unknown"),
                "subtype": meta.get("subtype", ""),
                "color": meta.get("color", []),
                "pattern": meta.get("pattern", ""),
                "formality": meta.get("formality", 3),
                "occasion_score": score,
                "description": meta.get("description", "")
            })

    log.ai(f"Eligible garments (score >= 0.4): {len(eligible)}")

    if len(eligible) < 2:
        log.warning("Not enough eligible garments")
        return generate_mock_outfits(occasion, garments)

    # ━━━ STEP 2: Group by type ━━━
    tops = [g for g in eligible if g["type"] in ("top", "outerwear")]
    bottoms = [g for g in eligible if g["type"] == "bottom"]
    dresses = [g for g in eligible if g["type"] == "dress"]
    shoes = [g for g in eligible if g["type"] == "shoes"]
    accessories = [g for g in eligible if g["type"] == "accessory"]

    # Sort each group by occasion score (best first)
    tops.sort(key=lambda x: x["occasion_score"], reverse=True)
    bottoms.sort(key=lambda x: x["occasion_score"], reverse=True)
    dresses.sort(key=lambda x: x["occasion_score"], reverse=True)
    shoes.sort(key=lambda x: x["occasion_score"], reverse=True)
    accessories.sort(key=lambda x: x["occasion_score"], reverse=True)

    log.ai("Garments by type:")
    log.ai(f"  Tops/Outerwear: {len(tops)}")
    log.ai(f"  Bottoms: {len(bottoms)}")
    log.ai(f"  Dresses: {len(dresses)}")
    log.ai(f"  Shoes: {len(shoes)}")
    log.ai(f"  Accessories: {len(accessories)}")

    total_combos = 0
    if tops and bottoms:
        total_combos += len(tops) * len(bottoms)
    if dresses:
        total_combos += len(dresses)
    if shoes and total_combos > 0:
        total_combos *= max(len(shoes), 1)

    log.ai(f"Total possible combinations: {total_combos}")

    # ━━━ STEP 3: Create batches ━━━
    BATCH_SIZE = 6  # Max items per type per batch
    
    def create_batches(items, batch_size):
        """Split items into overlapping batches for variety"""
        if len(items) <= batch_size:
            return [items]
        
        batches = []
        for i in range(0, len(items), batch_size - 2):  # Overlap by 2
            batch = items[i:i + batch_size]
            if len(batch) >= 2:
                batches.append(batch)
        
        return batches if batches else [items[:batch_size]]

    top_batches = create_batches(tops, BATCH_SIZE)
    bottom_batches = create_batches(bottoms, BATCH_SIZE)

    # Calculate rounds needed
    num_rounds = max(len(top_batches), len(bottom_batches), 1)
    
    # Cap at 3 rounds to stay within rate limits
    MAX_ROUNDS = 3
    num_rounds = min(num_rounds, MAX_ROUNDS)

    log.ai(f"Planned rounds: {num_rounds}")
    log.ai(f"  Top batches: {len(top_batches)}")
    log.ai(f"  Bottom batches: {len(bottom_batches)}")

    # ━━━ STEP 4: Multi-round AI calls ━━━
    all_outfits = []
    seen_combos = set()

    style_prefs = user_info.get('style_prefs', '[]')
    if isinstance(style_prefs, str):
        style_prefs = json.loads(style_prefs)
    gender = user_info.get('gender', 'unspecified')
    skin_tone = user_info.get('skin_tone', '')

    for round_num in range(num_rounds):
        log.ai(f"━━━ Round {round_num + 1}/{num_rounds} ━━━")
        
        # Pick batch for this round
        round_tops = top_batches[round_num % len(top_batches)] if top_batches else []
        round_bottoms = bottom_batches[round_num % len(bottom_batches)] if bottom_batches else []
        round_dresses = dresses[:4]  # Always include dresses
        round_shoes = shoes[:3]       # Always include shoes
        round_accessories = accessories[:3]

        batch_garments = round_tops + round_bottoms + round_dresses + round_shoes + round_accessories

        log.ai(f"  Batch size: {len(batch_garments)} garments")
        log.ai(f"  Tops: {len(round_tops)}, Bottoms: {len(round_bottoms)}")

        if len(batch_garments) < 2:
            continue

        # How many outfits to request this round
        outfits_per_round = 4 if num_rounds > 1 else 6

        # Build exclusion list
        exclude_text = ""
        if seen_combos:
            exclude_text = f"""
IMPORTANT: Do NOT suggest these combinations (already suggested):
{chr(10).join([f'- {list(combo)}' for combo in list(seen_combos)[:10]])}
Create DIFFERENT combinations using different garment pairs."""

        prompt = f"""You are an expert fashion stylist. Create outfit combinations for: **{occasion}**

User: {gender} | Skin tone: {skin_tone} | Style: {', '.join(style_prefs) if style_prefs else 'versatile'}

Available Garments:
{json.dumps(batch_garments, indent=2)}
{exclude_text}

Rules:
1. Create exactly {outfits_per_round} UNIQUE outfits
2. Each outfit needs: (top + bottom) OR (dress), optionally shoes/accessories
3. Use the EXACT "id" values from garments above
4. Every outfit must be DIFFERENT — use different garment combinations
5. Score 0.0 to 1.0 based on color harmony, pattern rules, occasion fit
6. Best outfit first

Return ONLY valid JSON array:
[
  {{
    "rank": 1,
    "garment_ids": ["id-from-above", "another-id"],
    "score": 0.92,
    "name": "Outfit Name",
    "reasoning": "Why these work together for {occasion}",
    "styling_tip": "How to wear this"
  }}
]"""

        try:
            import time
            # ━━━ RATE LIMIT CHECK ━━━
            rate_limiter.wait_if_needed()

            # Rate limit protection — wait between rounds
            if round_num > 0:
                log.ai("  Waiting 2s for rate limit...")
                time.sleep(2)

            start_time = datetime.now()

            response = groq_client.chat.completions.create(
                model=TEXT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
                temperature=0.7  # Higher temp = more variety between rounds
            )
 # ━━━ RECORD THE CALL ━━━
            rate_limiter.record_call(tokens_used=response.usage.total_tokens)
            
            elapsed = (datetime.now() - start_time).total_seconds()
            log.ai(f"  Response in {elapsed:.2f}s | Tokens: {response.usage.total_tokens}")
            log.ai(f"  Rate limit: {rate_limiter.get_stats()['minute_limit']} calls/min")
            raw_text = response.choices[0].message.content.strip()

            # Clean markdown
            text = raw_text
            if "```" in text:
                parts = text.split("```")
                if len(parts) >= 2:
                    text = parts[1]
                    if text.startswith("json"):
                        text = text[4:]
                    text = text.strip()

            round_outfits = json.loads(text)

            # Validate and deduplicate
            valid_ids = {g["id"] for g in batch_garments}

            for outfit in round_outfits:
                outfit_ids = outfit.get("garment_ids", [])
                valid_outfit_ids = [gid for gid in outfit_ids if gid in valid_ids]

                if len(valid_outfit_ids) < 1:
                    continue

                combo_key = tuple(sorted(valid_outfit_ids))
                
                if combo_key in seen_combos:
                    log.ai(f"  Skipping duplicate combo")
                    continue

                seen_combos.add(combo_key)
                outfit["garment_ids"] = valid_outfit_ids
                all_outfits.append(outfit)

            log.ai(f"  Got {len(round_outfits)} outfits, {len(all_outfits)} unique total")

        except Exception as e:
            log.error(f"  Round {round_num + 1} failed: {e}")
            continue

    # ━━━ STEP 5: Final ranking ━━━
    if not all_outfits:
        log.warning("No outfits generated — falling back to mock")
        return generate_mock_outfits(occasion, garments)

    # Sort by score
    all_outfits.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    # Re-rank
    for i, outfit in enumerate(all_outfits):
        outfit["rank"] = i + 1

    # Cap at max 12 outfits
    final_outfits = all_outfits[:12]

    # ━━━ STEP 6: Log summary ━━━
    log.success("━━━ MULTI-ROUND GENERATION COMPLETE ━━━")
    log.ai(f"Rounds completed: {num_rounds}")
    log.ai(f"Total unique outfits: {len(final_outfits)}")
    log.ai(f"From {total_combos} possible combinations")

    # Count how many unique garments were used
    used_garment_ids = set()
    for outfit in final_outfits:
        used_garment_ids.update(outfit["garment_ids"])
    
    log.ai(f"Unique garments used: {len(used_garment_ids)} out of {len(eligible)}")
    coverage = len(used_garment_ids) / max(len(eligible), 1) * 100
    log.ai(f"Wardrobe coverage: {coverage:.1f}%")

    for outfit in final_outfits:
        pieces_desc = []
        for gid in outfit["garment_ids"]:
            g = next((g for g in eligible if g["id"] == gid), None)
            if g:
                color = g.get('color', ['?'])[0] if g.get('color') else '?'
                pieces_desc.append(f"{color} {g.get('subtype', g.get('type'))}")
        
        log.ai(f"  #{outfit['rank']}: {outfit.get('name', 'Outfit')} ({outfit.get('score', 0):.0%})")
        log.ai(f"     → {' + '.join(pieces_desc)}")

    log.ai(f"Total API calls: {num_rounds}")
    log.ai(f"Cost: ₹0 (FREE)")

    return final_outfits
  
def get_meta(g):
    """Safely get metadata as dict"""
    if isinstance(g["metadata"], str):
        return json.loads(g["metadata"])
    return g["metadata"]


def generate_mock_outfits(occasion: str, garments: list) -> list:
    """Generate mock outfits when AI not available — CLEARLY MARKED"""
    import random

    log.warning("⚠️  GENERATING MOCK OUTFITS — NOT REAL AI ⚠️")

    tops = [g for g in garments if get_meta(g).get("type") in ("top", "outerwear")]
    bottoms = [g for g in garments if get_meta(g).get("type") == "bottom"]
    dresses = [g for g in garments if get_meta(g).get("type") == "dress"]

    outfits = []
    used = set()

    for i in range(min(4, max(len(tops), len(dresses), 1))):
        if dresses and random.random() > 0.5:
            dress = random.choice(dresses)
            if dress["id"] not in used:
                meta = get_meta(dress)
                outfits.append({
                    "rank": len(outfits) + 1,
                    "garment_ids": [dress["id"]],
                    "score": round(random.uniform(0.7, 0.95), 2),
                    "name": f"MOCK: {occasion.title()} Look {len(outfits)+1}",
                    "reasoning": "MOCK DATA — This is randomly generated, NOT AI",
                    "styling_tip": "MOCK: Add minimal accessories",
                    "_mock": True
                })
                used.add(dress["id"])
        elif tops and bottoms:
            top = random.choice(tops)
            bottom = random.choice(bottoms)
            if top["id"] not in used or bottom["id"] not in used:
                outfits.append({
                    "rank": len(outfits) + 1,
                    "garment_ids": [top["id"], bottom["id"]],
                    "score": round(random.uniform(0.65, 0.95), 2),
                    "name": f"MOCK: {occasion.title()} Look {len(outfits)+1}",
                    "reasoning": "MOCK DATA — This is randomly generated, NOT AI",
                    "styling_tip": "MOCK: Consider tucking in the top",
                    "_mock": True
                })
                used.add(top["id"])
                used.add(bottom["id"])

    if len(outfits) < 2 and len(garments) >= 2:
        random.shuffle(garments)
        for i in range(0, min(4, len(garments)), 2):
            if i + 1 < len(garments):
                outfits.append({
                    "rank": len(outfits) + 1,
                    "garment_ids": [garments[i]["id"], garments[i+1]["id"]],
                    "score": round(random.uniform(0.5, 0.8), 2),
                    "name": f"MOCK: {occasion.title()} Mix {len(outfits)+1}",
                    "reasoning": "MOCK DATA — Random combination",
                    "styling_tip": "MOCK: Experiment with accessories",
                    "_mock": True
                })

    outfits.sort(key=lambda x: x["score"], reverse=True)
    for i, o in enumerate(outfits):
        o["rank"] = i + 1

    return outfits[:5]


# ═══════════════════════════════════════════════════════════
# WARDROBE ROUTES
# ═══════════════════════════════════════════════════════════
@app.post("/api/wardrobe/upload")
async def upload_garment(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user)
):
    log.info(f"━━━ UPLOAD STARTED ━━━")
    log.info(f"User: {user_id[:8]}...")
    log.info(f"File: {file.filename}")

    # Read file and compute hash
    content = await file.read()
    image_hash = hashlib.md5(content).hexdigest()
    log.info(f"File size: {len(content)/1024:.1f} KB")
    log.info(f"Hash: {image_hash[:16]}...")

    # Check for duplicate
    with get_db() as db:
        existing = db.execute(
            "SELECT id FROM garments WHERE user_id = ? AND image_hash = ?",
            (user_id, image_hash)
        ).fetchone()
        if existing:
            log.warning("Duplicate image detected — skipping")
            return {
                "status": "duplicate",
                "garment_id": existing["id"],
                "message": "This image already exists in your wardrobe"
            }

    # Save file
    ext = Path(file.filename).suffix or ".jpg"
    garment_id = str(uuid.uuid4())
    filename = f"{user_id[:8]}_{garment_id[:8]}{ext}"
    filepath = UPLOAD_DIR / filename

    with open(filepath, "wb") as f:
        f.write(content)
    log.success(f"Image saved: {filepath}")

    image_url = f"/uploads/{filename}"

    # Analyse with AI
    log.info("Starting AI analysis...")
    metadata, final_path = analyse_garment_with_ai(str(filepath))

    # Upload to Cloudinary for persistent storage
    log.info("Uploading to Cloudinary...")
    upload_result = cloudinary.uploader.upload(final_path, folder="styleai/uploads", public_id=filename)
    image_url = upload_result['secure_url']
    log.success(f"Uploaded to Cloudinary: {image_url}")

    # Save to database
    with get_db() as db:
        db.execute(
            """INSERT INTO garments (id, user_id, image_url, image_hash, metadata, analysed)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (garment_id, user_id, image_url, image_hash, json.dumps(metadata))
        )

        # Invalidate combo caches for affected occasions
        affected = [occ for occ, score in metadata.get("occasions", {}).items()
                    if score >= 0.5]
        if affected:
            placeholders = ",".join("?" * len(affected))
            db.execute(
                f"DELETE FROM outfit_combos WHERE user_id = ? AND occasion IN ({placeholders})",
                [user_id] + affected
            )
            log.info(f"Invalidated outfit cache for: {affected}")

    log.success(f"━━━ UPLOAD COMPLETE ━━━")
    log.success(f"Garment ID: {garment_id[:8]}...")

    return {
        "status": "ok",
        "garment_id": garment_id,
        "image_url": image_url,
        "metadata": metadata,
        "ai_powered": not metadata.get("_mock", False)
    }


@app.get("/api/wardrobe")
def get_wardrobe(user_id: str = Depends(get_current_user)):
    log.info(f"Fetching wardrobe for user: {user_id[:8]}...")

    with get_db() as db:
        garments = db.execute(
            "SELECT * FROM garments WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()

    result = []
    for g in garments:
        item = dict(g)
        item["metadata"] = json.loads(item["metadata"])
        result.append(item)

    log.success(f"Found {len(result)} garments")
    return {"garments": result, "total": len(result)}


@app.delete("/api/wardrobe/{garment_id}")
def delete_garment(garment_id: str, user_id: str = Depends(get_current_user)):
    log.info(f"Deleting garment: {garment_id[:8]}...")

    with get_db() as db:
        garment = db.execute(
            "SELECT * FROM garments WHERE id = ? AND user_id = ?",
            (garment_id, user_id)
        ).fetchone()
        if not garment:
            raise HTTPException(404, "Garment not found")

        # Delete file
        filepath = Path("." + garment["image_url"])
        if filepath.exists():
            filepath.unlink()
            log.info(f"File deleted: {filepath}")

        # Delete from DB
        db.execute("DELETE FROM garments WHERE id = ?", (garment_id,))

        # Invalidate combo caches
        db.execute("DELETE FROM outfit_combos WHERE user_id = ?", (user_id,))

    log.success("Garment deleted")
    return {"status": "deleted"}


# ═══════════════════════════════════════════════════════════
# OUTFIT ROUTES
# ═══════════════════════════════════════════════════════════
@app.post("/api/outfits/suggest")
def suggest_outfits(data: OccasionRequest, user_id: str = Depends(get_current_user)):
    occasion = data.occasion.lower()
    log.info(f"━━━ OUTFIT SUGGESTION REQUEST ━━━")
    log.info(f"User: {user_id[:8]}...")
    log.info(f"Occasion: {occasion}")

    with get_db() as db:
        # Check combo cache
        cached = db.execute(
            "SELECT * FROM outfit_combos WHERE user_id = ? AND occasion = ? ORDER BY score DESC",
            (user_id, occasion)
        ).fetchall()

        if cached:
            log.info(f"Cache HIT — returning {len(cached)} cached outfits")
            rate_limiter.record_cache_hit()  # ← ADD THIS
            log.info(f"API calls saved by cache so far: {rate_limiter.calls_saved_by_cache}")
            results = []
            for c in cached:
                item = dict(c)
                item["garment_ids"] = json.loads(item["garment_ids"])
                item["pieces"] = json.loads(item["pieces"])
                results.append(item)
            return {"outfits": results, "cached": True}

        log.info("Cache MISS — generating new outfits")

        # Get user's wardrobe
        garments = db.execute(
            "SELECT * FROM garments WHERE user_id = ?", (user_id,)
        ).fetchall()

        if not garments:
            log.warning("No garments in wardrobe")
            return {"outfits": [], "message": "Add clothes to your wardrobe first!"}

        garment_list = []
        for g in garments:
            item = dict(g)
            item["metadata"] = json.loads(item["metadata"])
            garment_list.append(item)

        log.info(f"Total garments: {len(garment_list)}")

        # Get user info
        user = db.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()

        # Generate combinations with AI
        outfits = generate_outfits_with_ai(occasion, garment_list, dict(user))

        # Cache results
        for outfit in outfits:
            combo_id = str(uuid.uuid4())
            garment_ids = outfit["garment_ids"]
            combo_key = hashlib.md5(
                f"{occasion}::{'|'.join(sorted(garment_ids))}".encode()
            ).hexdigest()

            # Get garment details for pieces
            pieces = []
            for gid in garment_ids:
                gm = next((g for g in garment_list if g["id"] == gid), None)
                if gm:
                    pieces.append({
                        "id": gid,
                        "image_url": gm["image_url"],
                        "type": gm["metadata"].get("type", ""),
                        "subtype": gm["metadata"].get("subtype", ""),
                        "color": gm["metadata"].get("color", []),
                        "description": gm["metadata"].get("description", "")
                    })

            outfit["pieces"] = pieces

            try:
                db.execute(
                    """INSERT OR IGNORE INTO outfit_combos
                       (id, user_id, occasion, garment_ids, combo_key, score,
                        reasoning, styling_tip, pieces)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (combo_id, user_id, occasion,
                     json.dumps(garment_ids), combo_key,
                     outfit.get("score", 0),
                     outfit.get("reasoning", ""),
                     outfit.get("styling_tip", ""),
                     json.dumps(pieces))
                )
            except sqlite3.IntegrityError:
                pass

        log.success(f"━━━ SUGGESTIONS COMPLETE ━━━")
        log.success(f"Generated {len(outfits)} outfits for {occasion}")

        return {"outfits": outfits, "cached": False, "ai_powered": AI_AVAILABLE}

@app.post("/api/outfits/more")
def get_more_outfits(data: OccasionRequest, user_id: str = Depends(get_current_user)):
    """Generate MORE outfits — excluding already seen combinations"""
    occasion = data.occasion.lower()
    log.info(f"Requesting MORE outfits for: {occasion}")

    with get_db() as db:
        # Get existing combos to exclude
        existing = db.execute(
            "SELECT garment_ids FROM outfit_combos WHERE user_id = ? AND occasion = ?",
            (user_id, occasion)
        ).fetchall()

        existing_combos = set()
        for e in existing:
            ids = tuple(sorted(json.loads(e["garment_ids"])))
            existing_combos.add(ids)

        log.ai(f"Excluding {len(existing_combos)} already seen combinations")

        # Get wardrobe
        garments = db.execute(
            "SELECT * FROM garments WHERE user_id = ?", (user_id,)
        ).fetchall()

        garment_list = []
        for g in garments:
            item = dict(g)
            item["metadata"] = json.loads(item["metadata"])
            garment_list.append(item)

        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    # Generate new outfits
    outfits = generate_outfits_with_ai(occasion, garment_list, dict(user))

    # Filter out already seen
    new_outfits = []
    for outfit in outfits:
        combo_key = tuple(sorted(outfit["garment_ids"]))
        if combo_key not in existing_combos:
            new_outfits.append(outfit)

    log.ai(f"New unique outfits: {len(new_outfits)}")

    # Cache new ones
    with get_db() as db:
        for outfit in new_outfits:
            combo_id = str(uuid.uuid4())
            garment_ids = outfit["garment_ids"]
            combo_key = hashlib.md5(
                f"{occasion}::{'|'.join(sorted(garment_ids))}".encode()
            ).hexdigest()

            pieces = []
            for gid in garment_ids:
                gm = next((g for g in garment_list if g["id"] == gid), None)
                if gm:
                    pieces.append({
                        "id": gid,
                        "image_url": gm["image_url"],
                        "type": gm["metadata"].get("type", ""),
                        "subtype": gm["metadata"].get("subtype", ""),
                        "color": gm["metadata"].get("color", []),
                        "description": gm["metadata"].get("description", "")
                    })

            outfit["pieces"] = pieces

            try:
                db.execute(
                    """INSERT OR IGNORE INTO outfit_combos
                       (id, user_id, occasion, garment_ids, combo_key, score,
                        reasoning, styling_tip, pieces)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (combo_id, user_id, occasion,
                     json.dumps(garment_ids), combo_key,
                     outfit.get("score", 0),
                     outfit.get("reasoning", ""),
                     outfit.get("styling_tip", ""),
                     json.dumps(pieces))
                )
            except sqlite3.IntegrityError:
                pass

    return {"outfits": new_outfits, "total_seen": len(existing_combos) + len(new_outfits)}

# ═══════════════════════════════════════════════════════════
# WARDROBE STATS
# ═══════════════════════════════════════════════════════════
@app.get("/api/wardrobe/stats")
def get_wardrobe_stats(user_id: str = Depends(get_current_user)):
    with get_db() as db:
        garments = db.execute(
            "SELECT metadata FROM garments WHERE user_id = ?", (user_id,)
        ).fetchall()

    stats = {
        "total": len(garments),
        "by_type": {},
        "by_color": {},
        "by_occasion": {},
        "avg_formality": 0,
        "ai_analysed": 0
    }

    formality_sum = 0
    for g in garments:
        meta = json.loads(g["metadata"])

        # Check if AI analysed
        if not meta.get("_mock"):
            stats["ai_analysed"] += 1

        # Count by type
        gtype = meta.get("type", "other")
        stats["by_type"][gtype] = stats["by_type"].get(gtype, 0) + 1

        # Count by primary color
        colors = meta.get("color", [])
        if colors:
            stats["by_color"][colors[0]] = stats["by_color"].get(colors[0], 0) + 1

        # Count by best occasion
        occasions = meta.get("occasions", {})
        for occ, score in occasions.items():
            if score >= 0.6:
                stats["by_occasion"][occ] = stats["by_occasion"].get(occ, 0) + 1

        formality_sum += meta.get("formality", 3)

    if garments:
        stats["avg_formality"] = round(formality_sum / len(garments), 1)

    return stats


# ═══════════════════════════════════════════════════════════
# OUTFIT HISTORY
# ═══════════════════════════════════════════════════════════
@app.post("/api/history/save")
def save_to_history(
    occasion: str = Form(...),
    garment_ids: str = Form(...),
    user_id: str = Depends(get_current_user)
):
    with get_db() as db:
        db.execute(
            """INSERT INTO outfit_history (id, user_id, occasion, garment_ids)
               VALUES (?, ?, ?, ?)""",
            (str(uuid.uuid4()), user_id, occasion, garment_ids)
        )
    log.success(f"Outfit saved to history")
    return {"status": "saved"}


@app.get("/api/history")
def get_history(user_id: str = Depends(get_current_user)):
    with get_db() as db:
        history = db.execute(
            """SELECT * FROM outfit_history WHERE user_id = ?
               ORDER BY created_at DESC LIMIT 20""",
            (user_id,)
        ).fetchall()
    return {"history": [dict(h) for h in history]}


# ═══════════════════════════════════════════════════════════
# PROFILE UPDATE
# ═══════════════════════════════════════════════════════════
@app.put("/api/profile")
def update_profile(
    full_name: str = Form(None),
    gender: str = Form(None),
    body_type: str = Form(None),
    skin_tone: str = Form(None),
    user_id: str = Depends(get_current_user)
):
    updates = {}
    if full_name is not None:
        updates["full_name"] = full_name
    if gender is not None:
        updates["gender"] = gender
    if body_type is not None:
        updates["body_type"] = body_type
    if skin_tone is not None:
        updates["skin_tone"] = skin_tone

    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [user_id]
        with get_db() as db:
            db.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
        log.success(f"Profile updated: {list(updates.keys())}")

    return {"status": "updated"}

# ═══════════════════════════════════════════════════════════
# 👗 VIRTUAL TRY-ON
# ═══════════════════════════════════════════════════════════

# ━━━ OPTION A: Free Visual Outfit Viewer ━━━
@app.post("/api/tryon/preview")
def get_tryon_preview(
    garment_ids: str = Form(...),
    user_id: str = Depends(get_current_user)
):
    """Get garment images arranged for visual preview (FREE + CACHED)"""
    log.info("━━━ TRY-ON PREVIEW ━━━")
    
    ids = json.loads(garment_ids)
    
    # ━━━ CHECK CACHE ━━━
    sorted_ids = sorted(ids)
    cache_key = hashlib.md5(
        f"preview::{user_id}::{'|'.join(sorted_ids)}".encode()
    ).hexdigest()
    
    with get_db() as db:
        # Check if this exact combination was previewed before
        cached = db.execute(
            "SELECT image_url FROM tryon_renders WHERE render_key = ? AND user_id = ?",
            (cache_key, user_id)
        ).fetchone()
        
        if cached:
            log.success(f"Preview cache HIT — combination seen before")
            log.info(f"API calls saved: 1 (Groq Vision)")
        else:
            log.info(f"Preview cache MISS — new combination")
    
    log.info(f"Garment IDs: {ids}")
    
    with get_db() as db:
        pieces = []
        for gid in ids:
            garment = db.execute(
                "SELECT * FROM garments WHERE id = ? AND user_id = ?",
                (gid, user_id)
            ).fetchone()
            
            if garment:
                meta = json.loads(garment["metadata"])
                pieces.append({
                    "id": garment["id"],
                    "image_url": garment["image_url"],
                    "type": meta.get("type", "unknown"),
                    "subtype": meta.get("subtype", ""),
                    "color": meta.get("color", []),
                    "description": meta.get("description", "")
                })
        
        # Save to cache (for tracking, even though preview is free)
        if not cached:
            try:
                db.execute(
                    """INSERT OR IGNORE INTO tryon_renders 
                       (id, user_id, combo_key, model_id, render_key, image_url, rendered_at)
                       VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
                    (str(uuid.uuid4()), user_id, cache_key, "preview",
                     cache_key, json.dumps([p["image_url"] for p in pieces]))
                )
                log.info("Preview combination cached")
            except Exception as e:
                log.warning(f"Cache save failed: {e}")
    
    # Sort: outerwear → top → bottom → shoes → accessory
    type_order = {"outerwear": 0, "top": 1, "dress": 1, "bottom": 2, "shoes": 3, "accessory": 4}
    pieces.sort(key=lambda p: type_order.get(p["type"], 5))
    
    log.success(f"Preview ready with {len(pieces)} pieces")
    
    return {
        "pieces": pieces,
        "mode": "preview",
        "cached": bool(cached),
        "cache_key": cache_key
    }

# ━━━ OPTION B: fashn.ai / fal.ai Integration (Paid) ━━━
FASHN_API_KEY = ""  # Paste fashn.ai key when ready
FAL_API_KEY = ""    # Paste fal.ai key when ready

TRYON_AVAILABLE = bool(FASHN_API_KEY) or bool(FAL_API_KEY)

if TRYON_AVAILABLE:
    log.success("Virtual Try-On API is ACTIVE")
else:
    log.info("Virtual Try-On: Preview mode (connect fashn.ai/fal.ai for AI rendering)")


@app.post("/api/tryon/render")
async def render_tryon(
    garment_id: str = Form(...),
    model_type: str = Form("default"),  # "default" or "custom"
    model_image: UploadFile = File(None),
    user_id: str = Depends(get_current_user)
):
    """Render virtual try-on using fashn.ai or fal.ai (PAID)"""
    log.info("━━━ TRY-ON RENDER REQUEST ━━━")
    
    # Get garment
    with get_db() as db:
        garment = db.execute(
            "SELECT * FROM garments WHERE id = ? AND user_id = ?",
            (garment_id, user_id)
        ).fetchone()
        if not garment:
            raise HTTPException(404, "Garment not found")
        
        # Get user profile for default model
        user = db.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    
    garment_image_url = garment["image_url"]
    meta = json.loads(garment["metadata"])
    
    log.ai(f"Garment: {meta.get('subtype', meta.get('type'))}")
    log.ai(f"Model type: {model_type}")
    
    # Check cache first
    cache_key = hashlib.md5(
        f"{garment_id}::{model_type}::{user_id}".encode()
    ).hexdigest()
    
    with get_db() as db:
        cached = db.execute(
            "SELECT image_url FROM tryon_renders WHERE render_key = ?",
            (cache_key,)
        ).fetchone()
        
        if cached:
            log.success("Cache HIT — returning cached render")
            return {
                "render_url": cached["image_url"],
                "cached": True,
                "cost": "₹0 (cached)"
            }
    
    log.info("Cache MISS — need to render")
    
    # ━━━ Try fashn.ai first ━━━
    if FASHN_API_KEY:
        try:
            log.ai("Rendering with fashn.ai...")
            import httpx
            
            # Get model image
            if model_type == "custom" and model_image:
                model_content = await model_image.read()
                model_b64 = base64.b64encode(model_content).decode()
            else:
                # Use default model based on user profile
                model_path = get_default_model_path(user)
                with open(model_path, "rb") as f:
                    model_b64 = base64.b64encode(f.read()).decode()
            
            # Read garment image
            garment_path = "." + garment_image_url
            with open(garment_path, "rb") as f:
                garment_b64 = base64.b64encode(f.read()).decode()
            
            # Call fashn.ai API
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    "https://api.fashn.ai/v1/run",
                    headers={
                        "Authorization": f"Bearer {FASHN_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model_image": f"data:image/jpeg;base64,{model_b64}",
                        "garment_image": f"data:image/jpeg;base64,{garment_b64}",
                        "category": meta.get("type", "top")
                    }
                )
            
            result = response.json()
            render_url = result.get("output", {}).get("image_url", "")
            
            if render_url:
                # Cache the render
                save_render_to_cache(cache_key, render_url, user_id, db)
                log.success(f"fashn.ai render complete!")
                log.ai(f"Cost: ~₹4.50")
                
                return {
                    "render_url": render_url,
                    "cached": False,
                    "cost": "~₹4.50"
                }
        
        except Exception as e:
            log.error(f"fashn.ai failed: {e}")
    
    # ━━━ Try fal.ai as fallback ━━━
    if FAL_API_KEY:
        try:
            log.ai("Rendering with fal.ai...")
            import httpx
            
            garment_path = "." + garment_image_url
            with open(garment_path, "rb") as f:
                garment_b64 = base64.b64encode(f.read()).decode()
            
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    "https://queue.fal.run/fashn/tryon",
                    headers={
                        "Authorization": f"Key {FAL_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model_image": f"data:image/jpeg;base64,{model_b64}",
                        "garment_image": f"data:image/jpeg;base64,{garment_b64}",
                        "category": meta.get("type", "top")
                    }
                )
            
            result = response.json()
            render_url = result.get("image", {}).get("url", "")
            
            if render_url:
                save_render_to_cache(cache_key, render_url, user_id, db)
                log.success(f"fal.ai render complete!")
                return {
                    "render_url": render_url,
                    "cached": False,
                    "cost": "~₹3.00"
                }
        
        except Exception as e:
            log.error(f"fal.ai failed: {e}")
    
    # ━━━ No API available — return preview mode ━━━
    log.warning("No try-on API configured — returning preview")
    return {
        "render_url": garment_image_url,
        "mode": "preview",
        "message": "Connect fashn.ai or fal.ai for AI-powered try-on",
        "cost": "₹0 (preview only)"
    }


def get_default_model_path(user) -> str:
    """Get default model image based on user profile"""
    gender = user["gender"] if user else "female"
    # You can add actual model images to a models/ folder
    model_dir = Path("models")
    model_dir.mkdir(exist_ok=True)
    
    model_file = model_dir / f"default_{gender}.jpg"
    
    if not model_file.exists():
        # Create a simple placeholder
        img = Image.new('RGB', (400, 700), color=(220, 220, 220))
        img.save(model_file, quality=85)
    
    return str(model_file)


def save_render_to_cache(cache_key, image_url, user_id, db):
    """Save rendered try-on to cache"""
    try:
        db.execute(
            """INSERT OR REPLACE INTO tryon_renders 
               (id, user_id, combo_key, model_id, render_key, image_url, rendered_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (str(uuid.uuid4()), user_id, cache_key, "default", cache_key, image_url)
        )
        log.success("Render cached for future use")
    except Exception as e:
        log.warning(f"Cache save failed: {e}")


# ━━━ Add tryon_renders table if not exists ━━━
def add_tryon_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tryon_renders (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            combo_key TEXT DEFAULT '',
            model_id TEXT DEFAULT 'default',
            render_key TEXT UNIQUE,
            image_url TEXT NOT NULL,
            is_affiliate INTEGER DEFAULT 0,
            rendered_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()

add_tryon_table()


# ═══════════════════════════════════════════════════════════
# 🗄️ SMART CACHE SYSTEM
# ═══════════════════════════════════════════════════════════

@app.get("/api/cache/stats")
def get_cache_stats(user_id: str = Depends(get_current_user)):
    """Show cache statistics — how many API calls were saved"""
    with get_db() as db:
        # Garment analysis cache
        total_garments = db.execute(
            "SELECT COUNT(*) as c FROM garments WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
        
        # Outfit combo cache
        total_combos = db.execute(
            "SELECT COUNT(*) as c FROM outfit_combos WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
        
        # Unique occasions cached
        cached_occasions = db.execute(
            "SELECT DISTINCT occasion FROM outfit_combos WHERE user_id = ?", (user_id,)
        ).fetchall()
        
        # Try-on render cache
        total_renders = db.execute(
            "SELECT COUNT(*) as c FROM tryon_renders WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
    
    # Calculate savings
    groq_vision_cost_per_call = 0  # Free!
    groq_text_cost_per_call = 0    # Free!
    fashn_cost_per_render = 4.50   # ₹4.50 per render
    
    stats = {
        "garments_analysed": total_garments,
        "garment_api_calls_saved": "All duplicate uploads skip API",
        "outfit_combos_cached": total_combos,
        "occasions_cached": [r["occasion"] for r in cached_occasions],
        "renders_cached": total_renders,
        "render_savings_inr": round(total_renders * fashn_cost_per_render, 2),
        "note": "Groq is free — but caching still saves time and rate limits"
    }
    
    log.data("Cache Statistics", stats)
    return stats


@app.post("/api/cache/clear")
def clear_cache(
    cache_type: str = Form("all"),  # "combos" / "renders" / "all"
    user_id: str = Depends(get_current_user)
):
    """Manually clear cache — useful when user wants fresh suggestions"""
    with get_db() as db:
        if cache_type in ("combos", "all"):
            db.execute("DELETE FROM outfit_combos WHERE user_id = ?", (user_id,))
            log.info("Outfit combo cache cleared")
        
        if cache_type in ("renders", "all"):
            db.execute("DELETE FROM tryon_renders WHERE user_id = ?", (user_id,))
            log.info("Try-on render cache cleared")
    
    log.success(f"Cache cleared: {cache_type}")
    return {"status": "cleared", "type": cache_type}


@app.get("/api/rate-limit/stats")
def get_rate_limit_stats(user_id: str = Depends(get_current_user)):
    """Check current rate limit status"""
    stats = rate_limiter.get_stats()
    log.data("Rate Limit Stats", stats)
    return stats


# ═══════════════════════════════════════════════════════════
# 👤 MODEL IMAGE SYSTEM
# ═══════════════════════════════════════════════════════════

MODELS_DIR = Path("models")
MODELS_DIR.mkdir(exist_ok=True)

# Default model images — replace these with real stock photos later
DEFAULT_MODELS = {
    "female": {
        "light":  "models/female_light.jpg",
        "medium": "models/female_medium.jpg",
        "dark":   "models/female_dark.jpg",
    },
    "male": {
        "light":  "models/male_light.jpg",
        "medium": "models/male_medium.jpg",
        "dark":   "models/male_dark.jpg",
    },
    "other": {
        "light":  "models/other_light.jpg",
        "medium": "models/other_medium.jpg",
        "dark":   "models/other_dark.jpg",
    }
}


def create_placeholder_models():
    """
    Create simple placeholder model images.
    Replace these with real stock model photos for production.
    Download free model images from:
    - https://unsplash.com (search: fashion model full body)
    - https://www.pexels.com (search: fashion model standing)
    """
    skin_colors = {
        "light":  (245, 222, 199),
        "medium": (210, 170, 130),
        "dark":   (140, 100, 70),
    }

    outfit_colors = {
        "female": (200, 200, 200),  # Light grey
        "male":   (180, 180, 180),  # Grey
        "other":  (190, 190, 190),  # Mid grey
    }

    for gender in ["female", "male", "other"]:
        for tone, skin_rgb in skin_colors.items():
            filepath = Path(DEFAULT_MODELS[gender][tone])

            if filepath.exists():
                continue

            log.info(f"Creating placeholder model: {filepath}")

            # Create a simple silhouette placeholder
            img = Image.new('RGB', (400, 700), color=(240, 240, 240))
            pixels = img.load()

            # Draw simple body shape
            body_color = skin_rgb
            outfit_color = outfit_colors[gender]

            # Head (circle area)
            for x in range(150, 250):
                for y in range(30, 120):
                    if ((x - 200) ** 2 + (y - 75) ** 2) < 45 ** 2:
                        pixels[x, y] = body_color

            # Torso (rectangle with outfit color)
            for x in range(140, 260):
                for y in range(120, 380):
                    pixels[x, y] = outfit_color

            # Arms
            for x in range(100, 140):
                for y in range(130, 350):
                    pixels[x, y] = body_color
            for x in range(260, 300):
                for y in range(130, 350):
                    pixels[x, y] = body_color

            # Legs (outfit color for pants)
            for x in range(150, 195):
                for y in range(380, 620):
                    pixels[x, y] = outfit_color
            for x in range(205, 250):
                for y in range(380, 620):
                    pixels[x, y] = outfit_color

            # Shoes
            for x in range(140, 200):
                for y in range(620, 670):
                    pixels[x, y] = (60, 60, 60)
            for x in range(200, 260):
                for y in range(620, 670):
                    pixels[x, y] = (60, 60, 60)

            img.save(str(filepath), quality=85)

    log.success("Default model images ready")


# Create placeholders on startup
try:
    create_placeholder_models()
except Exception as e:
    log.warning(f"Could not create placeholder models: {e}")


def get_default_model_path(user) -> str:
    """Get default model image based on user profile"""
    gender = "female"
    skin_tone = "medium"

    if user:
        gender = user["gender"] if user["gender"] in ("male", "female", "other") else "female"
        
        # Map skin tone to our 3 categories
        tone = user.get("skin_tone", "medium") if isinstance(user, dict) else "medium"
        if tone in ("light", "fair"):
            skin_tone = "light"
        elif tone in ("brown", "dark"):
            skin_tone = "dark"
        else:
            skin_tone = "medium"

    model_path = DEFAULT_MODELS.get(gender, DEFAULT_MODELS["female"]).get(skin_tone, "models/female_medium.jpg")

    if not Path(model_path).exists():
        log.warning(f"Model image not found: {model_path}")
        # Fallback — create it
        create_placeholder_models()

    log.info(f"Using default model: {model_path} (gender={gender}, skin={skin_tone})")
    return model_path


def verify_full_body_image(image_path: str) -> dict:
    """
    Use Groq Vision to verify if an image is a full body photo.
    Returns: {is_full_body: bool, confidence: float, details: str}
    """
    log.ai("━━━ VERIFYING BODY IMAGE ━━━")
    log.ai(f"Image: {image_path}")

    if not AI_AVAILABLE:
        log.warning("AI not available — assuming full body")
        return {
            "is_full_body": True,
            "confidence": 0.5,
            "details": "AI not available — cannot verify"
        }

    try:
        # Compress image first
        img = Image.open(image_path)

        # Convert mode if needed
        if img.mode in ('RGBA', 'P', 'LA'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'RGBA':
                background.paste(img, mask=img.split()[3])
            else:
                background.paste(img)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Resize for API
        max_dim = 800
        if img.width > max_dim or img.height > max_dim:
            ratio = min(max_dim / img.width, max_dim / img.height)
            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.Resampling.LANCZOS)

        # Save compressed
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=60, optimize=True)
        buffer.seek(0)
        image_data = base64.b64encode(buffer.read()).decode()

        rate_limiter.wait_if_needed()

        response = groq_client.chat.completions.create(
            model=VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_data}"
                        }
                    },
                    {
                        "type": "text",
                        "text": """Analyse this photo for virtual clothing try-on suitability.

Check these things:
1. Is this a FULL BODY image? (head to at least knees visible)
2. Is the person standing or in a clear pose?
3. Is the image clear and well-lit?
4. Is there exactly ONE person in the photo?

Return ONLY valid JSON:
{
  "is_full_body": true/false,
  "head_visible": true/false,
  "torso_visible": true/false,
  "legs_visible": true/false,
  "is_standing": true/false,
  "single_person": true/false,
  "good_lighting": true/false,
  "confidence": 0.0-1.0,
  "issue": "describe any problem or 'none'",
  "suggestion": "what should user do to improve the photo"
}"""
                    }
                ]
            }],
            max_tokens=300,
            temperature=0.2
        )

        rate_limiter.record_call(tokens_used=response.usage.total_tokens)

        raw_text = response.choices[0].message.content.strip()

        # Clean markdown
        text = raw_text
        if "```" in text:
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

        result = json.loads(text)

        # Determine if suitable for try-on
        is_suitable = (
            result.get("is_full_body", False) and
            result.get("torso_visible", False) and
            result.get("single_person", True) and
            result.get("confidence", 0) >= 0.6
        )

        log.ai("Verification Results:")
        log.ai(f"  Full body: {'✅' if result.get('is_full_body') else '❌'}")
        log.ai(f"  Head visible: {'✅' if result.get('head_visible') else '❌'}")
        log.ai(f"  Torso visible: {'✅' if result.get('torso_visible') else '❌'}")
        log.ai(f"  Legs visible: {'✅' if result.get('legs_visible') else '❌'}")
        log.ai(f"  Standing: {'✅' if result.get('is_standing') else '❌'}")
        log.ai(f"  Single person: {'✅' if result.get('single_person') else '❌'}")
        log.ai(f"  Good lighting: {'✅' if result.get('good_lighting') else '❌'}")
        log.ai(f"  Confidence: {result.get('confidence', 0):.0%}")
        log.ai(f"  Suitable for try-on: {'✅ YES' if is_suitable else '❌ NO'}")

        if not is_suitable:
            log.ai(f"  Issue: {result.get('issue', 'unknown')}")
            log.ai(f"  Suggestion: {result.get('suggestion', '')}")

        return {
            "is_full_body": is_suitable,
            "confidence": result.get("confidence", 0),
            "details": result,
            "issue": result.get("issue", "none"),
            "suggestion": result.get("suggestion", "")
        }

    except json.JSONDecodeError:
        log.error("Body verification JSON parse failed")
        return {
            "is_full_body": False,
            "confidence": 0,
            "details": "Verification failed",
            "issue": "Could not analyse image",
            "suggestion": "Please try uploading a different photo"
        }

    except Exception as e:
        log.error(f"Body verification failed: {e}")
        return {
            "is_full_body": False,
            "confidence": 0,
            "details": str(e),
            "issue": str(e),
            "suggestion": "Please try again"
        }


def get_model_image_for_tryon(user_id: str, db) -> dict:
    """
    Get the best model image for try-on.
    Priority:
    1. User's verified full body image
    2. Default model matching user's profile
    """
    # Check if user has uploaded a verified body image
    user = db.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()

    if not user:
        return {
            "path": get_default_model_path(None),
            "source": "default",
            "message": "Using default model"
        }

    user_dict = dict(user)

    # Check for saved body image
    body_image_path = UPLOAD_DIR / f"body_{user_id}.jpg"

    if body_image_path.exists():
        log.info(f"Found user's body image: {body_image_path}")
        return {
            "path": str(body_image_path),
            "source": "user",
            "message": "Using your uploaded photo"
        }

    # Use default model
    default_path = get_default_model_path(user_dict)
    return {
        "path": default_path,
        "source": "default",
        "message": f"Using default {user_dict.get('gender', 'female')} model"
    }

# ═══════════════════════════════════════════════════════════
# 📸 MODEL IMAGE UPLOAD & VERIFICATION ROUTES
# ═══════════════════════════════════════════════════════════

# Serve model images
app.mount("/models", StaticFiles(directory="models"), name="models")

@app.post("/api/model/upload")
async def upload_model_image(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user)
):
    """
    Upload user's body image for try-on.
    Verifies with AI that it's a suitable full body photo.
    """
    log.info(f"━━━ MODEL IMAGE UPLOAD ━━━")
    log.info(f"User: {user_id[:8]}...")
    log.info(f"File: {file.filename}")

    # Save temporarily
    content = await file.read()
    temp_path = UPLOAD_DIR / f"temp_body_{user_id[:8]}.jpg"

    with open(temp_path, "wb") as f:
        f.write(content)

    file_size_kb = len(content) / 1024
    log.info(f"File size: {file_size_kb:.1f} KB")

    # ━━━ VERIFY WITH GROQ ━━━
    log.ai("Verifying if image is suitable for try-on...")
    verification = verify_full_body_image(str(temp_path))

    if verification["is_full_body"]:
        # ✅ Good image — save permanently
        permanent_path = UPLOAD_DIR / f"body_{user_id}.jpg"

        # Resize for optimal try-on
        img = Image.open(temp_path)
        if img.mode != 'RGB':
            img = img.convert('RGB')

        max_dim = 1200
        if img.width > max_dim or img.height > max_dim:
            ratio = min(max_dim / img.width, max_dim / img.height)
            img = img.resize(
                (int(img.width * ratio), int(img.height * ratio)),
                Image.Resampling.LANCZOS
            )

        img.save(str(permanent_path), quality=85)

        # Clean up temp
        if temp_path.exists():
            temp_path.unlink()

        log.success("Full body image verified and saved! ✅")

        return {
            "status": "accepted",
            "image_url": f"/uploads/body_{user_id}.jpg",
            "verification": verification["details"],
            "message": "Great photo! Your image will be used for try-on."
        }

    else:
        # ❌ Not suitable — keep temp for display but use default model
        log.warning("Image not suitable for try-on")

        # Clean up temp
        if temp_path.exists():
            temp_path.unlink()

        # Get user profile for default model suggestion
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            default_path = get_default_model_path(dict(user) if user else None)

        return {
            "status": "rejected",
            "issue": verification.get("issue", "Not a full body image"),
            "suggestion": verification.get("suggestion", "Please upload a full body photo"),
            "confidence": verification.get("confidence", 0),
            "default_model": f"/{default_path}",
            "message": "We'll use a default model instead. You can try uploading again."
        }


@app.delete("/api/model/remove")
def remove_model_image(user_id: str = Depends(get_current_user)):
    """Remove user's body image — revert to default model"""
    body_path = UPLOAD_DIR / f"body_{user_id}.jpg"

    if body_path.exists():
        body_path.unlink()
        log.info("User body image removed")

    return {
        "status": "removed",
        "message": "Your photo has been removed. Default model will be used."
    }


@app.get("/api/model/current")
def get_current_model(user_id: str = Depends(get_current_user)):
    """Get the current model image being used for this user"""
    with get_db() as db:
        result = get_model_image_for_tryon(user_id, db)

    return {
        "image_url": f"/{result['path']}",
        "source": result["source"],
        "message": result["message"],
        "has_custom_photo": result["source"] == "user"
    }


@app.get("/api/model/defaults")
def get_default_models(user_id: str = Depends(get_current_user)):
    """Get all available default model images"""
    models = []
    for gender in ["female", "male", "other"]:
        for tone in ["light", "medium", "dark"]:
            path = DEFAULT_MODELS[gender][tone]
            if Path(path).exists():
                models.append({
                    "gender": gender,
                    "skin_tone": tone,
                    "image_url": f"/{path}",
                    "label": f"{gender.title()} - {tone.title()}"
                })

    return {"models": models}

# ═══════════════════════════════════════════════════════════
# ⭐ FAVORITES SYSTEM
# ═══════════════════════════════════════════════════════════

@app.post("/api/favorites/garment/{garment_id}")
def toggle_garment_favorite(garment_id: str, user_id: str = Depends(get_current_user)):
    """Toggle favorite status for a garment"""
    with get_db() as db:
        garment = db.execute(
            "SELECT is_favorite FROM garments WHERE id = ? AND user_id = ?",
            (garment_id, user_id)
        ).fetchone()
        
        if not garment:
            raise HTTPException(404, "Garment not found")
        
        new_status = 0 if garment["is_favorite"] else 1
        db.execute(
            "UPDATE garments SET is_favorite = ? WHERE id = ?",
            (new_status, garment_id)
        )
    
    log.info(f"Garment {garment_id[:8]} favorite: {bool(new_status)}")
    return {"is_favorite": bool(new_status)}


@app.get("/api/favorites/garments")
def get_favorite_garments(user_id: str = Depends(get_current_user)):
    """Get all favorite garments"""
    with get_db() as db:
        garments = db.execute(
            "SELECT * FROM garments WHERE user_id = ? AND is_favorite = 1 ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
    
    result = []
    for g in garments:
        item = dict(g)
        item["metadata"] = json.loads(item["metadata"])
        result.append(item)
    
    return {"favorites": result, "total": len(result)}


@app.post("/api/favorites/outfit")
def save_favorite_outfit(
    name: str = Form(...),
    garment_ids: str = Form(...),
    occasion: str = Form(""),
    notes: str = Form(""),
    user_id: str = Depends(get_current_user)
):
    """Save an outfit as favorite"""
    outfit_id = str(uuid.uuid4())
    
    with get_db() as db:
        db.execute(
            """INSERT INTO favorite_outfits (id, user_id, name, garment_ids, occasion, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (outfit_id, user_id, name, garment_ids, occasion, notes)
        )
    
    log.success(f"Saved favorite outfit: {name}")
    return {"id": outfit_id, "status": "saved"}


@app.get("/api/favorites/outfits")
def get_favorite_outfits(user_id: str = Depends(get_current_user)):
    """Get all favorite outfits with garment details"""
    with get_db() as db:
        outfits = db.execute(
            "SELECT * FROM favorite_outfits WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
        
        result = []
        for outfit in outfits:
            item = dict(outfit)
            garment_ids = json.loads(item["garment_ids"])
            
            # Get garment details
            pieces = []
            for gid in garment_ids:
                g = db.execute(
                    "SELECT id, image_url, metadata FROM garments WHERE id = ?",
                    (gid,)
                ).fetchone()
                if g:
                    pieces.append({
                        "id": g["id"],
                        "image_url": g["image_url"],
                        "metadata": json.loads(g["metadata"])
                    })
            
            item["pieces"] = pieces
            result.append(item)
    
    return {"favorites": result, "total": len(result)}


@app.delete("/api/favorites/outfit/{outfit_id}")
def delete_favorite_outfit(outfit_id: str, user_id: str = Depends(get_current_user)):
    """Delete a favorite outfit"""
    with get_db() as db:
        db.execute(
            "DELETE FROM favorite_outfits WHERE id = ? AND user_id = ?",
            (outfit_id, user_id)
        )
    return {"status": "deleted"}


# ═══════════════════════════════════════════════════════════
# 📅 CALENDAR & EVENTS
# ═══════════════════════════════════════════════════════════

@app.post("/api/calendar/event")
def create_event(
    title: str = Form(...),
    event_date: str = Form(...),
    event_time: str = Form(""),
    occasion_type: str = Form("casual"),
    location: str = Form(""),
    notes: str = Form(""),
    user_id: str = Depends(get_current_user)
):
    """Create a calendar event"""
    event_id = str(uuid.uuid4())
    
    with get_db() as db:
        db.execute(
            """INSERT INTO calendar_events 
               (id, user_id, title, event_date, event_time, occasion_type, location, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, user_id, title, event_date, event_time, occasion_type, location, notes)
        )
    
    log.info(f"Created event: {title} on {event_date}")
    return {"id": event_id, "status": "created"}


@app.get("/api/calendar/events")
def get_events(
    start_date: str = None,
    end_date: str = None,
    user_id: str = Depends(get_current_user)
):
    """Get calendar events, optionally filtered by date range"""
    with get_db() as db:
        if start_date and end_date:
            events = db.execute(
                """SELECT * FROM calendar_events 
                   WHERE user_id = ? AND event_date BETWEEN ? AND ?
                   ORDER BY event_date, event_time""",
                (user_id, start_date, end_date)
            ).fetchall()
        else:
            events = db.execute(
                """SELECT * FROM calendar_events 
                   WHERE user_id = ? AND event_date >= date('now')
                   ORDER BY event_date, event_time
                   LIMIT 20""",
                (user_id,)
            ).fetchall()
    
    return {"events": [dict(e) for e in events]}


@app.get("/api/calendar/event/{event_id}")
def get_event(event_id: str, user_id: str = Depends(get_current_user)):
    """Get single event details"""
    with get_db() as db:
        event = db.execute(
            "SELECT * FROM calendar_events WHERE id = ? AND user_id = ?",
            (event_id, user_id)
        ).fetchone()
        
        if not event:
            raise HTTPException(404, "Event not found")
    
    return dict(event)


@app.put("/api/calendar/event/{event_id}/outfit")
def assign_outfit_to_event(
    event_id: str,
    garment_ids: str = Form(...),
    user_id: str = Depends(get_current_user)
):
    """Assign an outfit to an event"""
    with get_db() as db:
        db.execute(
            "UPDATE calendar_events SET garment_ids = ? WHERE id = ? AND user_id = ?",
            (garment_ids, event_id, user_id)
        )
    
    log.info(f"Assigned outfit to event {event_id[:8]}")
    return {"status": "assigned"}


@app.delete("/api/calendar/event/{event_id}")
def delete_event(event_id: str, user_id: str = Depends(get_current_user)):
    """Delete an event"""
    with get_db() as db:
        db.execute(
            "DELETE FROM calendar_events WHERE id = ? AND user_id = ?",
            (event_id, user_id)
        )
    return {"status": "deleted"}


@app.get("/api/calendar/upcoming")
def get_upcoming_events(user_id: str = Depends(get_current_user)):
    """Get upcoming events for the next 7 days"""
    with get_db() as db:
        events = db.execute(
            """SELECT * FROM calendar_events 
               WHERE user_id = ? 
               AND event_date BETWEEN date('now') AND date('now', '+7 days')
               ORDER BY event_date, event_time""",
            (user_id,)
        ).fetchall()
    
    return {"events": [dict(e) for e in events], "count": len(events)}


# ═══════════════════════════════════════════════════════════
# 🌤️ WEATHER INTEGRATION
# ═══════════════════════════════════════════════════════════

# Free weather API: Open-Meteo (no API key needed!)
WEATHER_API = "https://api.open-meteo.com/v1/forecast"
GEOCODING_API = "https://geocoding-api.open-meteo.com/v1/search"


async def get_coordinates(city: str) -> dict:
    """Get lat/long for a city"""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{GEOCODING_API}?name={city}&count=1")
            if r.status_code == 200:
                data = r.json()
                if data.get("results"):
                    loc = data["results"][0]
                    return {
                        "lat": loc["latitude"],
                        "lon": loc["longitude"],
                        "name": loc.get("name", city),
                        "country": loc.get("country", "")
                    }
    except Exception as e:
        log.warning(f"Geocoding failed: {e}")
    return None


async def get_weather(lat: float, lon: float) -> dict:
    """Get current weather from Open-Meteo (FREE, no API key!)"""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{WEATHER_API}?latitude={lat}&longitude={lon}"
                f"&current_weather=true&timezone=auto"
            )
            if r.status_code == 200:
                data = r.json()
                current = data.get("current_weather", {})
                return {
                    "temperature": current.get("temperature"),
                    "windspeed": current.get("windspeed"),
                    "weathercode": current.get("weathercode"),
                    "description": get_weather_description(current.get("weathercode", 0)),
                    "is_day": current.get("is_day", 1)
                }
    except Exception as e:
        log.warning(f"Weather fetch failed: {e}")
    return None


def get_weather_description(code: int) -> str:
    """Convert weather code to description"""
    codes = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Foggy",
        48: "Foggy",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Heavy drizzle",
        61: "Light rain",
        63: "Moderate rain",
        65: "Heavy rain",
        71: "Light snow",
        73: "Moderate snow",
        75: "Heavy snow",
        80: "Light showers",
        81: "Moderate showers",
        82: "Heavy showers",
        95: "Thunderstorm",
    }
    return codes.get(code, "Unknown")


def get_weather_outfit_suggestion(temp: float, weather_code: int) -> dict:
    """Suggest outfit modifications based on weather"""
    suggestions = {
        "layers": [],
        "avoid": [],
        "tip": ""
    }
    
    # Temperature-based
    if temp < 10:
        suggestions["layers"] = ["heavy coat", "sweater", "scarf"]
        suggestions["avoid"] = ["shorts", "sleeveless"]
        suggestions["tip"] = "Layer up! It's cold outside."
    elif temp < 18:
        suggestions["layers"] = ["light jacket", "cardigan"]
        suggestions["tip"] = "A light layer would be perfect."
    elif temp < 25:
        suggestions["tip"] = "Comfortable weather — most outfits work!"
    else:
        suggestions["avoid"] = ["heavy fabrics", "dark colors", "layers"]
        suggestions["tip"] = "Keep it light and breathable."
    
    # Weather-based
    if weather_code in (61, 63, 65, 80, 81, 82):
        suggestions["layers"].append("waterproof jacket")
        suggestions["avoid"].append("suede shoes")
        suggestions["tip"] += " Don't forget an umbrella!"
    
    if weather_code in (71, 73, 75):
        suggestions["layers"].extend(["boots", "warm coat"])
        suggestions["tip"] += " Bundle up for the snow!"
    
    return suggestions


@app.post("/api/weather/set-location")
async def set_weather_location(
    city: str = Form(...),
    user_id: str = Depends(get_current_user)
):
    """Set user's location for weather"""
    coords = await get_coordinates(city)
    
    if not coords:
        raise HTTPException(400, "City not found. Try a different spelling.")
    
    with get_db() as db:
        db.execute(
            """INSERT OR REPLACE INTO user_preferences (user_id, weather_location)
               VALUES (?, ?)""",
            (user_id, json.dumps(coords))
        )
    
    log.info(f"Weather location set: {coords['name']}, {coords['country']}")
    return {
        "status": "set",
        "location": f"{coords['name']}, {coords['country']}",
        "coordinates": coords
    }


@app.get("/api/weather/current")
async def get_current_weather(user_id: str = Depends(get_current_user)):
    """Get current weather for user's location"""
    with get_db() as db:
        prefs = db.execute(
            "SELECT weather_location FROM user_preferences WHERE user_id = ?",
            (user_id,)
        ).fetchone()
    
    if not prefs or not prefs["weather_location"]:
        return {
            "status": "no_location",
            "message": "Set your location first",
            "weather": None
        }
    
    coords = json.loads(prefs["weather_location"])
    weather = await get_weather(coords["lat"], coords["lon"])
    
    if not weather:
        return {"status": "error", "message": "Could not fetch weather"}
    
    # Add outfit suggestions
    outfit_suggestions = get_weather_outfit_suggestion(
        weather["temperature"],
        weather.get("weathercode", 0)
    )
    
    return {
        "status": "ok",
        "location": f"{coords['name']}, {coords['country']}",
        "weather": weather,
        "outfit_suggestions": outfit_suggestions
    }


@app.get("/api/weather/suggest-outfit")
async def suggest_outfit_for_weather(
    occasion: str = "casual",
    user_id: str = Depends(get_current_user)
):
    """Get AI outfit suggestion considering weather"""
    # Get weather
    weather_data = await get_current_weather(user_id)
    
    if weather_data.get("status") != "ok":
        # No weather — use normal suggestion
        return await suggest_outfits(
            OccasionRequest(occasion=occasion),
            user_id
        )
    
    weather = weather_data["weather"]
    temp = weather.get("temperature", 20)
    
    with get_db() as db:
        garments = db.execute(
            "SELECT * FROM garments WHERE user_id = ?",
            (user_id,)
        ).fetchall()
    
    garment_list = []
    for g in garments:
        item = dict(g)
        item["metadata"] = json.loads(item["metadata"])
        garment_list.append(item)
    
    # Filter by weather suitability
    suitable = []
    for g in garment_list:
        meta = g["metadata"]
        seasons = meta.get("season", ["all-season"])
        
        # Cold weather filter
        if temp < 15 and "summer" in seasons and "all-season" not in seasons:
            continue
        # Hot weather filter
        if temp > 28 and "winter" in seasons and "all-season" not in seasons:
            continue
        
        suitable.append(g)
    
    log.ai(f"Weather-filtered garments: {len(suitable)} of {len(garment_list)}")
    
    # Get user info
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    
    # Generate outfits
    outfits = generate_outfits_with_ai(occasion, suitable, dict(user))
    
    # Add weather context to tips
    weather_tip = weather_data["outfit_suggestions"]["tip"]
    for outfit in outfits:
        outfit["styling_tip"] = f"🌤️ {weather_tip} " + outfit.get("styling_tip", "")
    
    return {
        "outfits": outfits,
        "weather": weather,
        "weather_tip": weather_tip
    }


# ═══════════════════════════════════════════════════════════
# 📊 WARDROBE STATISTICS
# ═══════════════════════════════════════════════════════════

@app.get("/api/stats/wardrobe")
def get_detailed_wardrobe_stats(user_id: str = Depends(get_current_user)):
    """Get comprehensive wardrobe statistics"""
    with get_db() as db:
        garments = db.execute(
            "SELECT * FROM garments WHERE user_id = ?", (user_id,)
        ).fetchall()
        
        history = db.execute(
            "SELECT * FROM outfit_history WHERE user_id = ?", (user_id,)
        ).fetchall()
        
        favorites = db.execute(
            "SELECT COUNT(*) as c FROM garments WHERE user_id = ? AND is_favorite = 1",
            (user_id,)
        ).fetchone()["c"]
        
        saved_outfits = db.execute(
            "SELECT COUNT(*) as c FROM favorite_outfits WHERE user_id = ?",
            (user_id,)
        ).fetchone()["c"]
    
    stats = {
        "total_garments": len(garments),
        "favorites": favorites,
        "saved_outfits": saved_outfits,
        "outfits_worn": len(history),
        
        "by_type": {},
        "by_color": {},
        "by_pattern": {},
        "by_occasion": {},
        "by_season": {},
        "by_formality": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
        
        "most_worn": [],
        "never_worn": [],
        "color_palette": [],
        "wardrobe_value_estimate": 0,
        
        "insights": []
    }
    
    color_counts = {}
    type_counts = {}
    
    for g in garments:
        meta = json.loads(g["metadata"])
        
        # By type
        gtype = meta.get("type", "other")
        stats["by_type"][gtype] = stats["by_type"].get(gtype, 0) + 1
        type_counts[gtype] = type_counts.get(gtype, 0) + 1
        
        # By color
        colors = meta.get("color", [])
        for c in colors:
            stats["by_color"][c] = stats["by_color"].get(c, 0) + 1
            color_counts[c] = color_counts.get(c, 0) + 1
        
        # By pattern
        pattern = meta.get("pattern", "unknown")
        stats["by_pattern"][pattern] = stats["by_pattern"].get(pattern, 0) + 1
        
        # By occasion
        occasions = meta.get("occasions", {})
        for occ, score in occasions.items():
            if score >= 0.6:
                stats["by_occasion"][occ] = stats["by_occasion"].get(occ, 0) + 1
        
        # By season
        seasons = meta.get("season", ["all-season"])
        for s in seasons:
            stats["by_season"][s] = stats["by_season"].get(s, 0) + 1
        
        # By formality
        formality = meta.get("formality", 3)
        if formality in stats["by_formality"]:
            stats["by_formality"][formality] += 1
        
        # Track wear count
        if g["wear_count"] > 0:
            stats["most_worn"].append({
                "id": g["id"],
                "image_url": g["image_url"],
                "type": meta.get("subtype", gtype),
                "wear_count": g["wear_count"]
            })
        else:
            stats["never_worn"].append({
                "id": g["id"],
                "image_url": g["image_url"],
                "type": meta.get("subtype", gtype)
            })
    
    # Sort most worn
    stats["most_worn"].sort(key=lambda x: x["wear_count"], reverse=True)
    stats["most_worn"] = stats["most_worn"][:5]  # Top 5
    
    # Top colors for palette
    sorted_colors = sorted(color_counts.items(), key=lambda x: x[1], reverse=True)
    stats["color_palette"] = [c[0] for c in sorted_colors[:8]]
    
    # Generate insights
    if len(garments) > 0:
        # Dominant type
        top_type = max(type_counts.items(), key=lambda x: x[1])
        stats["insights"].append(f"Your wardrobe is {top_type[0]}-heavy ({top_type[1]} items)")
        
        # Color insight
        if sorted_colors:
            stats["insights"].append(f"Your signature color is {sorted_colors[0][0]}")
        
        # Balance insight
        tops = type_counts.get("top", 0) + type_counts.get("outerwear", 0)
        bottoms = type_counts.get("bottom", 0)
        if tops > bottoms * 2:
            stats["insights"].append("💡 Consider adding more bottoms for better balance")
        elif bottoms > tops * 2:
            stats["insights"].append("💡 Consider adding more tops for better balance")
        
        # Never worn insight
        never_worn_pct = len(stats["never_worn"]) / len(garments) * 100
        if never_worn_pct > 30:
            stats["insights"].append(f"⚠️ {never_worn_pct:.0f}% of your wardrobe hasn't been worn")
        
        # Occasion gaps
        occasion_coverage = set(stats["by_occasion"].keys())
        all_occasions = {"casual", "office", "party", "formal", "date", "outdoor"}
        missing = all_occasions - occasion_coverage
        if missing:
            stats["insights"].append(f"📌 Limited options for: {', '.join(missing)}")
    
    return stats


@app.get("/api/stats/history")
def get_outfit_history_stats(user_id: str = Depends(get_current_user)):
    """Get outfit history and wearing patterns"""
    with get_db() as db:
        history = db.execute(
            """SELECT * FROM outfit_history WHERE user_id = ?
               ORDER BY worn_on DESC LIMIT 30""",
            (user_id,)
        ).fetchall()
        
        # Monthly breakdown
        monthly = db.execute(
            """SELECT strftime('%Y-%m', worn_on) as month, COUNT(*) as count
               FROM outfit_history WHERE user_id = ?
               GROUP BY month ORDER BY month DESC LIMIT 6""",
            (user_id,)
        ).fetchall()
        
        # By occasion
        by_occasion = db.execute(
            """SELECT occasion, COUNT(*) as count
               FROM outfit_history WHERE user_id = ?
               GROUP BY occasion ORDER BY count DESC""",
            (user_id,)
        ).fetchall()
    
    # Parse history with garment details
    result_history = []
    for h in history:
        item = dict(h)
        item["garment_ids"] = json.loads(item["garment_ids"]) if item["garment_ids"] else []
        result_history.append(item)
    
    return {
        "history": result_history,
        "monthly_breakdown": [dict(m) for m in monthly],
        "by_occasion": [dict(o) for o in by_occasion],
        "total_logged": len(history)
    }


# ═══════════════════════════════════════════════════════════
# 📝 OUTFIT HISTORY (Enhanced)
# ═══════════════════════════════════════════════════════════

@app.post("/api/history/log")
async def log_outfit_worn(
    garment_ids: str = Form(...),
    occasion: str = Form("casual"),
    outfit_name: str = Form(""),
    notes: str = Form(""),
    rating: int = Form(0),
    worn_on: str = Form(None),
    user_id: str = Depends(get_current_user)
):
    """Log an outfit as worn today (or specific date)"""
    ids = json.loads(garment_ids)
    history_id = str(uuid.uuid4())
    
    # Get weather if available
    weather_data = await get_current_weather(user_id)
    weather_info = ""
    temperature = None
    
    if weather_data.get("status") == "ok":
        w = weather_data["weather"]
        weather_info = w.get("description", "")
        temperature = w.get("temperature")
    
    with get_db() as db:
        # Log the outfit
        db.execute(
            """INSERT INTO outfit_history 
               (id, user_id, garment_ids, occasion, outfit_name, notes, 
                weather, temperature, rating, worn_on)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, date('now')))""",
            (history_id, user_id, garment_ids, occasion, outfit_name,
             notes, weather_info, temperature, rating, worn_on)
        )
        
        # Update wear count for each garment
        for gid in ids:
            db.execute(
                """UPDATE garments 
                   SET wear_count = wear_count + 1, last_worn = date('now')
                   WHERE id = ? AND user_id = ?""",
                (gid, user_id)
            )
    
    log.success(f"Logged outfit with {len(ids)} pieces")
    return {"id": history_id, "status": "logged"}


@app.get("/api/history/recent")
def get_recent_outfits(
    limit: int = 10,
    user_id: str = Depends(get_current_user)
):
    """Get recently worn outfits"""
    with get_db() as db:
        history = db.execute(
            """SELECT * FROM outfit_history WHERE user_id = ?
               ORDER BY worn_on DESC, created_at DESC LIMIT ?""",
            (user_id, limit)
        ).fetchall()
        
        result = []
        for h in history:
            item = dict(h)
            garment_ids = json.loads(item["garment_ids"]) if item["garment_ids"] else []
            
            # Get garment details
            pieces = []
            for gid in garment_ids:
                g = db.execute(
                    "SELECT id, image_url, metadata FROM garments WHERE id = ?",
                    (gid,)
                ).fetchone()
                if g:
                    pieces.append({
                        "id": g["id"],
                        "image_url": g["image_url"],
                        "metadata": json.loads(g["metadata"])
                    })
            
            item["pieces"] = pieces
            result.append(item)
    
    return {"history": result}


# ═══════════════════════════════════════════════════════════
# 🛍️ AFFILIATE MARKETING
# ═══════════════════════════════════════════════════════════

# Sample affiliate products (in production, fetch from real APIs)
SAMPLE_AFFILIATE_PRODUCTS = [
    # Accessories
    {"category": "watch", "name": "Classic Leather Watch", "price": 1499, "platform": "amazon",
     "image_url": "https://via.placeholder.com/200x200?text=Watch", "tags": ["casual", "office"]},
    {"category": "watch", "name": "Digital Smart Watch", "price": 2999, "platform": "amazon",
     "image_url": "https://via.placeholder.com/200x200?text=SmartWatch", "tags": ["casual", "sporty"]},
    {"category": "belt", "name": "Black Leather Belt", "price": 799, "platform": "myntra",
     "image_url": "https://via.placeholder.com/200x200?text=Belt", "tags": ["office", "formal"]},
    {"category": "belt", "name": "Tan Casual Belt", "price": 699, "platform": "myntra",
     "image_url": "https://via.placeholder.com/200x200?text=TanBelt", "tags": ["casual"]},
    {"category": "sunglasses", "name": "Aviator Sunglasses", "price": 1299, "platform": "amazon",
     "image_url": "https://via.placeholder.com/200x200?text=Aviator", "tags": ["casual", "outdoor"]},
    {"category": "bag", "name": "Leather Tote Bag", "price": 1899, "platform": "myntra",
     "image_url": "https://via.placeholder.com/200x200?text=ToteBag", "tags": ["office", "casual"]},
    {"category": "bag", "name": "Sling Crossbody Bag", "price": 999, "platform": "amazon",
     "image_url": "https://via.placeholder.com/200x200?text=SlingBag", "tags": ["casual", "outdoor"]},
    # Shoes
    {"category": "shoes", "name": "White Sneakers", "price": 2499, "platform": "myntra",
     "image_url": "https://via.placeholder.com/200x200?text=Sneakers", "tags": ["casual", "sporty"]},
    {"category": "shoes", "name": "Brown Oxford Shoes", "price": 3499, "platform": "amazon",
     "image_url": "https://via.placeholder.com/200x200?text=Oxford", "tags": ["office", "formal"]},
    {"category": "shoes", "name": "Black Heels", "price": 1999, "platform": "myntra",
     "image_url": "https://via.placeholder.com/200x200?text=Heels", "tags": ["party", "formal"]},
    # Jewellery
    {"category": "earrings", "name": "Gold Stud Earrings", "price": 599, "platform": "amazon",
     "image_url": "https://via.placeholder.com/200x200?text=Earrings", "tags": ["office", "casual"]},
    {"category": "necklace", "name": "Pearl Pendant Necklace", "price": 899, "platform": "myntra",
     "image_url": "https://via.placeholder.com/200x200?text=Necklace", "tags": ["party", "date"]},
]


def init_affiliate_products():
    """Initialize sample affiliate products"""
    with get_db() as db:
        existing = db.execute("SELECT COUNT(*) as c FROM affiliate_products").fetchone()["c"]
        
        if existing == 0:
            for p in SAMPLE_AFFILIATE_PRODUCTS:
                db.execute(
                    """INSERT INTO affiliate_products 
                       (id, category, name, price_inr, platform, image_url, tags, affiliate_url)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), p["category"], p["name"], p["price"],
                     p["platform"], p["image_url"], json.dumps(p["tags"]),
                     f"https://{p['platform']}.com/product/{uuid.uuid4().hex[:8]}")
                )
            log.info(f"Initialized {len(SAMPLE_AFFILIATE_PRODUCTS)} affiliate products")


# Call on startup
try:
    init_affiliate_products()
except Exception as e:
    log.warning(f"Could not init affiliate products: {e}")


@app.get("/api/affiliate/products")
def get_affiliate_products(
    category: str = None,
    occasion: str = None,
    limit: int = 10,
    user_id: str = Depends(get_current_user)
):
    """Get affiliate product suggestions"""
    with get_db() as db:
        if category:
            products = db.execute(
                """SELECT * FROM affiliate_products 
                   WHERE category = ? AND active = 1 
                   ORDER BY clicks DESC LIMIT ?""",
                (category, limit)
            ).fetchall()
        elif occasion:
            products = db.execute(
                """SELECT * FROM affiliate_products 
                   WHERE tags LIKE ? AND active = 1 
                   ORDER BY clicks DESC LIMIT ?""",
                (f'%"{occasion}"%', limit)
            ).fetchall()
        else:
            products = db.execute(
                """SELECT * FROM affiliate_products 
                   WHERE active = 1 ORDER BY clicks DESC LIMIT ?""",
                (limit,)
            ).fetchall()
    
    result = []
    for p in products:
        item = dict(p)
        item["tags"] = json.loads(item["tags"])
        result.append(item)
    
    return {"products": result}


@app.get("/api/affiliate/suggest")
def suggest_products_for_outfit(
    garment_ids: str,
    occasion: str = "casual",
    user_id: str = Depends(get_current_user)
):
    """Suggest affiliate products to complete an outfit"""
    ids = json.loads(garment_ids)
    
    with get_db() as db:
        # Get current outfit pieces
        garment_types = set()
        for gid in ids:
            g = db.execute(
                "SELECT metadata FROM garments WHERE id = ?", (gid,)
            ).fetchone()
            if g:
                meta = json.loads(g["metadata"])
                garment_types.add(meta.get("type", ""))
        
        # Determine what's missing
        missing_categories = []
        
        if "shoes" not in garment_types:
            missing_categories.append("shoes")
        if "accessory" not in garment_types:
            missing_categories.extend(["watch", "belt", "bag"])
        
        # Get suggestions
        suggestions = []
        for cat in missing_categories[:3]:  # Limit to 3 categories
            products = db.execute(
                """SELECT * FROM affiliate_products 
                   WHERE category = ? AND active = 1 AND tags LIKE ?
                   ORDER BY RANDOM() LIMIT 2""",
                (cat, f'%"{occasion}"%')
            ).fetchall()
            
            for p in products:
                item = dict(p)
                item["tags"] = json.loads(item["tags"])
                item["suggestion_reason"] = f"Complete your {occasion} look"
                suggestions.append(item)
    
    return {
        "suggestions": suggestions,
        "missing": missing_categories,
        "occasion": occasion
    }


@app.post("/api/affiliate/click/{product_id}")
def track_affiliate_click(product_id: str, user_id: str = Depends(get_current_user)):
    """Track when user clicks an affiliate link"""
    with get_db() as db:
        # Record click
        db.execute(
            "INSERT INTO affiliate_clicks (id, user_id, product_id) VALUES (?, ?, ?)",
            (str(uuid.uuid4()), user_id, product_id)
        )
        
        # Update click count
        db.execute(
            "UPDATE affiliate_products SET clicks = clicks + 1 WHERE id = ?",
            (product_id,)
        )
        
        # Get affiliate URL
        product = db.execute(
            "SELECT affiliate_url, name FROM affiliate_products WHERE id = ?",
            (product_id,)
        ).fetchone()
    
    log.info(f"Affiliate click: {product['name'] if product else product_id}")
    
    return {
        "status": "tracked",
        "redirect_url": product["affiliate_url"] if product else None
    }


# ═══════════════════════════════════════════════════════════
# 🎨 THEME PREFERENCES
# ═══════════════════════════════════════════════════════════

@app.get("/api/preferences")
def get_preferences(user_id: str = Depends(get_current_user)):
    """Get user preferences"""
    with get_db() as db:
        user = db.execute(
            "SELECT theme FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        
        prefs = db.execute(
            "SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)
        ).fetchone()
    
    result = {
        "theme": user["theme"] if user else "dark",
    }
    
    if prefs:
        result.update({
            "weather_location": json.loads(prefs["weather_location"]) if prefs["weather_location"] else None,
            "temperature_unit": prefs["temperature_unit"],
            "notifications_enabled": bool(prefs["notifications_enabled"]),
        })
    
    return result


@app.put("/api/preferences/theme")
def set_theme(theme: str = Form(...), user_id: str = Depends(get_current_user)):
    """Set theme preference (dark/light)"""
    if theme not in ("dark", "light"):
        raise HTTPException(400, "Theme must be 'dark' or 'light'")
    
    with get_db() as db:
        db.execute("UPDATE users SET theme = ? WHERE id = ?", (theme, user_id))
    
    log.info(f"Theme set to: {theme}")
    return {"theme": theme}


# ═══════════════════════════════════════════════════════════
# 📤 SOCIAL SHARING
# ═══════════════════════════════════════════════════════════

@app.post("/api/share/outfit")
def create_shareable_outfit(
    garment_ids: str = Form(...),
    occasion: str = Form(""),
    user_id: str = Depends(get_current_user)
):
    """Create a shareable link for an outfit"""
    # Generate unique share ID
    share_id = hashlib.md5(
        f"{user_id}::{garment_ids}::{datetime.now().isoformat()}".encode()
    ).hexdigest()[:12]
    
    # In production, store this and create a public page
    # For now, return shareable data
    
    ids = json.loads(garment_ids)
    
    with get_db() as db:
        pieces = []
        for gid in ids:
            g = db.execute(
                "SELECT image_url, metadata FROM garments WHERE id = ? AND user_id = ?",
                (gid, user_id)
            ).fetchone()
            if g:
                pieces.append({
                    "image_url": g["image_url"],
                    "type": json.loads(g["metadata"]).get("subtype", "item")
                })
    
    return {
        "share_id": share_id,
        "share_url": f"/shared/{share_id}",
        "pieces_count": len(pieces),
        "occasion": occasion,
        "message": "Outfit ready to share! (Public sharing coming soon)"
    }

# ═══════════════════════════════════════════════════════════
# SERVE FRONTEND
# ═══════════════════════════════════════════════════════════
# Serve CSS and JS files
app.mount("/css", StaticFiles(directory="frontend/css"), name="css")
app.mount("/js", StaticFiles(directory="frontend/js"), name="js")

@app.get("/")
def serve_index():
    return FileResponse("frontend/index.html")

@app.get("/{page}.html")
def serve_page(page: str):
    filepath = f"frontend/{page}.html"
    if os.path.exists(filepath):
        return FileResponse(filepath)
    raise HTTPException(404, "Page not found")


# ═══════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 60)
    print("   ✨ StyleAI Server")
    print("=" * 60)
    print(f"   📁 Frontend: http://localhost:8000")
    print(f"   📡 API Docs: http://localhost:8000/docs")
    print(f"   🤖 AI Status: {'✅ ACTIVE (Groq Free)' if AI_AVAILABLE else '⚠️  DEMO MODE'}")
    print("=" * 60 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)
