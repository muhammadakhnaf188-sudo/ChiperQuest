"""
database.py - Pengelolaan Database SQLite untuk Progres, Skor, dan Soal Misi Dinamis

Tanggung jawab:
- Menginisialisasi database SQLite di instance/cipherquest.db atau fallback /tmp untuk Vercel.
- Menghasilkan soal misi secara dinamis (2-3 kata untuk umum, 4 kata untuk soal langka).
- Menyimpan soal yang sedang dikerjakan per sesi pemain sehingga tidak berubah saat refresh atau retry.
- Menyimpan progres pemain per sesi dan skor (idempotent, tanpa duplikasi).
- Mengunci/membuka akses misi berikutnya secara berurutan.
"""

import os
import random
import sqlite3
import tempfile
import time
from typing import Dict, List, Any, Optional, Tuple

from encrypt import encrypt_message
from decrypt import decrypt_ciphertext
from cipher import DEFAULT_A, DEFAULT_B

# ─── Bank Kata Intelijen Kriptografi ──────────────────────────────────────────
WORD_BANK_1 = [
    "KODE", "AGEN", "MISI", "SANDI", "KUNCI", "SINYAL", "DATA", "RADAR",
    "TARGET", "BERKAS", "KAPAL", "SATELIT", "VEKTOR", "MATRIX", "LOGIKA",
    "OPERASI", "PATROLI", "INTEL", "CYBER", "SISTEM", "PASUKAN", "JALUR"
]

WORD_BANK_2 = [
    "RAHASIA", "AKTIF", "AMAN", "GELAP", "CEPAT", "SENYAP", "VALID", "TEPAT",
    "UTAMA", "SIAGA", "FOKUS", "LINEAR", "INVERS", "DIGITAL", "KOREKSI",
    "TERKUNCI", "TERBUKA", "KHUSUS", "TAKTIK", "STRATEGIS", "OPTIMAL"
]

WORD_BANK_3 = [
    "KITA", "KOTA", "BUMI", "PUNCAK", "MALAM", "SUBUH", "SIANG", "BARAT",
    "TIMUR", "PUSAT", "ALPHA", "BETA", "DELTA", "OMEGA", "GARIS", "TITIK"
]

WORD_BANK_4 = [
    "SEKARANG", "SEGERA", "BERSAMA", "SELAMAT", "SEMPURNA", "TERAKHIR", "MUTLAK", "BERHASIL"
]


def generate_random_message() -> Tuple[str, int, bool]:
    """
    Menghasilkan kalimat sandi secara dinamis dengan aturan:
    - 2 kata: peluang ~44% (soal biasa)
    - 3 kata: peluang ~44% (soal biasa)
    - 4 kata: peluang ~12% (soal langka / rare intel mission)
    Mengembalikan (pesan_teks, jumlah_kata, is_rare).
    """
    r = random.random()
    w1 = random.choice(WORD_BANK_1)
    w2 = random.choice(WORD_BANK_2)

    if r < 0.12:
        # Soal langka 4 kata
        w3 = random.choice(WORD_BANK_3)
        w4 = random.choice(WORD_BANK_4)
        words = [w1, w2, w3, w4]
        is_rare = True
    elif r < 0.56:
        # Soal biasa 2 kata
        words = [w1, w2]
        is_rare = False
    else:
        # Soal biasa 3 kata
        w3 = random.choice(WORD_BANK_3)
        words = [w1, w2, w3]
        is_rare = False

    return " ".join(words), len(words), is_rare


BOSS_WORD_BANK = ["DATA", "SANDI", "KUNCI", "RADAR", "SINYAL", "KODE", "MISI", "TARGET"]


def generate_boss_mission_data(word: Optional[str] = None) -> Dict[str, Any]:
    """Membuat satu ronde teka-teki Caesar untuk pertarungan bos."""
    word = word or random.choice(BOSS_WORD_BANK)
    cipher_text = "".join(
        chr((ord(char) - ord('A') + 3) % 26 + ord('A')) if char.isalpha() else char
        for char in word.upper()
    )
    return {
        "target_input": word.upper(),
        "correct_answer": cipher_text,
        "prompt_question": (
            f"Enkripsikan kata '{word.upper()}' dengan menggeser setiap huruf 3 posisi ke kanan. "
            "Contoh: A menjadi D. Masukkan hasil huruf kapital."
        ),
        "hint": "Geser setiap huruf tiga langkah ke kanan dalam alfabet. Setelah Z, kembali ke A.",
        "explanation": f"Setiap huruf digeser 3 posisi ke kanan: {word.upper()} menjadi {cipher_text}.",
        "param_a": 3,
        "param_b": 0,
        "word_count": 1,
        "is_rare": False,
        "rare_tag": "",
        "mission_type": "boss",
    }


def generate_mission_data(mission_id: int) -> Dict[str, Any]:
    """
    Membuat soal baru secara dinamis untuk misi tertentu.
    Tipe soal (enkripsi atau dekripsi) dipilih secara ACAK untuk setiap misi,
    sehingga pemain bergantian mengerjakan soal huruf→angka dan angka→huruf.

    - Enkripsi: Pemain mengubah plainteks menjadi deretan angka cipherteks.
    - Dekripsi: Pemain mengubah deretan angka cipherteks menjadi plainteks.
    """
    if mission_id == 25:
        return generate_boss_mission_data("AGEN")

    message, word_count, is_rare = generate_random_message()
    a, b = DEFAULT_A, DEFAULT_B  # a=2, b=1 -> E(x) = 2x+3

    enc_res = encrypt_message(message, a=a, b=b)
    ciphertext = enc_res["ciphertext"]

    rare_tag = " [SOAL LANGKA // 4 KATA]" if is_rare else ""

    # Acak tipe soal: enkripsi (huruf→angka) atau dekripsi (angka→huruf)
    mission_type = random.choice(['encrypt', 'decrypt'])

    if mission_type == 'encrypt':
        # Soal Enkripsi: input plainteks, jawaban cipherteks
        if mission_id == 1:
            prompt_q = f"Enkripsikan pesan rahasia '{message}' menjadi deretan angka cipherteks yang dipisahkan spasi menggunakan rumus E(x) = 2x + 3."
            hint = (
                f"Setiap huruf dikonversi: A=1 s.d. Z=26, dan SPASI = 0. "
                f"Gunakan rumus E(x) = 2x + 3. Contoh: SPASI bernilai x=0 sehingga E(0) = 2(0)+3 = 3."
            )
        elif mission_id == 2:
            prompt_q = f"Enkripsikan pesan rahasia '{message}' menggunakan komposisi fungsi f(x) = 2x + 1 dan g(x) = x + 2."
            hint = (
                f"Komposisi: (g ∘ f)(x) = g(2x + 1) = (2x + 1) + 2 = 2x + 3. "
                f"Spasi bernilai x = 0 → E(0) = 3. Setiap huruf kapital A=1 s.d. Z=26."
            )
        else:
            prompt_q = f"Enkripsikan pesan rahasia '{message}' menjadi deretan angka cipherteks menggunakan komposisi (g ∘ f)(x) = 2x + 3."
            hint = (
                f"Terapkan E(x) = 2x + 3 untuk setiap huruf (A=1..Z=26, spasi=0). "
                f"Pisahkan hasil angka dengan spasi tunggal."
            )

        explanation = (
            f"Langkah enkripsi untuk '{message}':\n"
            f"1. Konversi karakter ke nilai x (A-Z = 1..26, spasi = 0).\n"
            f"2. Terapkan E(x) = 2x + 3 ke setiap nilai x.\n"
            f"3. Hasil cipherteks yang benar: {ciphertext}."
        )
        return {
            "target_input": message,
            "correct_answer": ciphertext,
            "prompt_question": prompt_q,
            "hint": hint,
            "explanation": explanation,
            "param_a": a,
            "param_b": b,
            "word_count": word_count,
            "is_rare": is_rare,
            "rare_tag": rare_tag,
            "mission_type": "encrypt"
        }

    else:
        # Soal Dekripsi: input cipherteks, jawaban plainteks
        if mission_id == 1:
            prompt_q = f"Dekripsikan deretan angka cipherteks '{ciphertext}' menjadi kalimat plainteks aslinya menggunakan rumus invers D(y) = (y - 3) / 2."
            hint = (
                f"Gunakan fungsi invers D(y) = (y - 3) / 2. "
                f"Token dengan nilai 3 menghasilkan D(3) = 0 yang merupakan SPASI pemisah kata."
            )
        elif mission_id == 2:
            prompt_q = f"Deskripsikan deretan angka cipherteks '{ciphertext}' kembali menjadi pesan asli menggunakan invers komposisi D(y) = (y - 3) / 2."
            hint = (
                f"Invers (g ∘ f)⁻¹(y) = D(y) = (y - 3) / 2. "
                f"Hasil D(y) dipetakan ke huruf: 1=A..26=Z, 0=SPASI."
            )
        else:
            prompt_q = f"Pecahkan kode cipherteks '{ciphertext}' dan ungkap pesan aslinya menggunakan fungsi invers D(y) = (y - 3) / 2."
            hint = (
                f"Terapkan D(y) = (y - 3) / 2 untuk setiap token angka. "
                f"Petakan hasilnya ke huruf (1-26 = A-Z, 0 = spasi)."
            )

        explanation = (
            f"Langkah dekripsi cipherteks '{ciphertext}':\n"
            f"1. Kurangi setiap token y dengan 3: (y - 3).\n"
            f"2. Bagi hasilnya dengan 2: x = (y - 3) / 2.\n"
            f"3. Petakan x ke huruf (1..26 → A..Z, 0 → spasi).\n"
            f"Pesan asli terungkap: '{message}'."
        )
        return {
            "target_input": ciphertext,
            "correct_answer": message,
            "prompt_question": prompt_q,
            "hint": hint,
            "explanation": explanation,
            "param_a": a,
            "param_b": b,
            "word_count": word_count,
            "is_rare": is_rare,
            "rare_tag": rare_tag,
            "mission_type": "decrypt"
        }


# Enam bab, masing-masing empat misi. Definisi soal dibuat saat pemain membuka misi.
_CHAPTERS = [
    (1, "Bab 1 — Dasar Enkripsi"),
    (2, "Bab 2 — Komposisi Fungsi"),
    (3, "Bab 3 — Invers dan Dekripsi"),
    (4, "Bab 4 — Analisis Pola"),
    (5, "Bab 5 — Operasi Lanjutan"),
    (6, "Bab 6 — Final Cipher"),
]

_MISSION_TITLES = [
    ("First Transmission", "Mengenali konversi huruf dan angka menggunakan fungsi linear."),
    ("Double Encryption", "Memahami komposisi fungsi f dan g serta inversnya."),
    ("Reverse the Code", "Menerapkan fungsi invers untuk mengungkap pesan."),
    ("Formula Investigation", "Menentukan pola fungsi linear dari data yang diberikan."),
    ("Signal Interception", "Mengenkripsi transmisi baru dengan fungsi komposisi."),
    ("Hidden Coordinates", "Mengubah pesan angka menjadi huruf secara akurat."),
    ("Cipher Relay", "Memproses rangkaian pesan dengan fungsi linear."),
    ("Encrypted Archive", "Menyelesaikan enkripsi dan dekripsi pesan acak."),
    ("Inverse Protocol", "Menggunakan invers fungsi untuk memulihkan plainteks."),
    ("Silent Frequency", "Mengenali nilai karakter dan spasi pada cipherteks."),
    ("Number Breaker", "Memecahkan deretan angka dengan fungsi invers."),
    ("Signal Recovery", "Memulihkan pesan yang disamarkan melalui fungsi linear."),
    ("Pattern Hunter", "Menemukan aturan perubahan nilai pada sebuah sandi."),
    ("Matrix Message", "Menganalisis hubungan data dan hasil enkripsi."),
    ("Deep Encryption", "Menggunakan komposisi dan invers secara bergantian."),
    ("Cipher Analysis", "Memeriksa pesan dan membuktikan hasil perhitungan."),
    ("Phantom Signal", "Memecahkan pesan panjang dengan ketelitian tinggi."),
    ("Codebreaker Elite", "Menggabungkan konsep enkripsi, dekripsi, dan invers."),
    ("Blackout Protocol", "Menafsirkan transmisi kompleks menggunakan fungsi linear."),
    ("Final Coordinates", "Menyelesaikan rangkaian operasi sebelum misi terakhir."),
    ("Quantum Cipher", "Menganalisis transformasi nilai karakter secara menyeluruh."),
    ("Last Transmission", "Menguji konsistensi hasil enkripsi dan dekripsi."),
    ("Zero Hour", "Menyelesaikan tantangan tingkat ahli dengan batas waktu."),
    ("Master Cipher", "Membuktikan penguasaan fungsi komposisi dan invers."),
]

_DIFFICULTIES = [
    "Mudah", "Menengah", "Mahir", "Ahli",
    "Mudah", "Menengah", "Menengah", "Menengah",
    "Menengah", "Menengah", "Mahir", "Mahir",
    "Mahir", "Mahir", "Ahli", "Ahli",
    "Ahli", "Ahli", "Ahli", "Ahli",
    "Ahli", "Ahli", "Ahli", "Ahli",
]

MISSIONS_DATA = []
for _mission_id, (_title, _objective) in enumerate(_MISSION_TITLES, start=1):
    _chapter_no = (_mission_id - 1) // 4 + 1
    _difficulty = _DIFFICULTIES[_mission_id - 1]
    _badge = "badge-easy" if _difficulty == "Mudah" else (
        "badge-medium" if _difficulty == "Menengah" else "badge-hard"
    )
    MISSIONS_DATA.append({
        "id": _mission_id,
        "code": f"MISI-{_mission_id:02d}",
        "title": _title,
        "difficulty": _difficulty,
        "difficulty_badge": _badge,
        "description": (
            f"Operasi {_title.lower()} menantang agen memecahkan transmisi dengan "
            "enkripsi E(x) = 2x + 3 atau fungsi invers D(y) = (y − 3) / 2. "
            "Soal dibuat otomatis dan dapat berupa huruf ke angka maupun angka ke huruf."
        ),
        "learning_objective": _objective,
        "prompt_question": "Selesaikan operasi kriptografi sesuai instruksi.",
        "target_input": "Dibuat otomatis saat misi dimulai.",
        "correct_answer": "",
        "hint": "Gunakan E(x) = 2x + 3 atau D(y) = (y − 3) / 2 sesuai jenis soal.",
        "explanation": "Soal dinamis dibuat untuk setiap sesi pemain.",
        "mission_type": "encrypt",
        "chapter_no": _chapter_no,
        "chapter_title": _CHAPTERS[_chapter_no - 1][1],
    })

# Misi khusus bos dibuka setelah seluruh 24 misi dari enam bab selesai.
MISSIONS_DATA.append({
    "id": 25,
    "code": "BOSS-01",
    "title": "The Cipher Guardian",
    "difficulty": "Ahli",
    "difficulty_badge": "badge-hard",
    "description": "Hadapi penjaga terakhir. Setiap jawaban benar mengurangi HP bos satu poin, sedangkan jawaban salah mengurangi nyawa agen.",
    "learning_objective": "Menerapkan pergeseran huruf Caesar tiga langkah untuk mengenkripsi kata.",
    "prompt_question": "Kalahkan bos dengan menyelesaikan lima ronde sandi Caesar.",
    "target_input": "AGEN",
    "correct_answer": "DJHQ",
    "hint": "Geser setiap huruf tiga langkah ke kanan dalam alfabet.",
    "explanation": "AGEN digeser tiga posisi ke kanan menjadi DJHQ.",
    "mission_type": "boss",
    "chapter_no": 7,
    "chapter_title": "Pertarungan Bos",
    "is_boss": True,
})


def get_db_path() -> str:
    """Mengembalikan path file database SQLite dengan fallback aman untuk serverless."""
    if os.environ.get('VERCEL') or os.environ.get('AWS_LAMBDA_FUNCTION_NAME') or os.environ.get('LAMBDA_TASK_ROOT'):
        return os.path.join(tempfile.gettempdir(), 'cipherquest.db')

    base_dir = os.path.abspath(os.path.dirname(__file__))
    instance_dir = os.path.join(base_dir, 'instance')

    try:
        os.makedirs(instance_dir, exist_ok=True)
        test_file = os.path.join(instance_dir, '.write_test')
        with open(test_file, 'w') as f:
            f.write('')
        os.remove(test_file)
        return os.path.join(instance_dir, 'cipherquest.db')
    except (OSError, IOError, PermissionError):
        return os.path.join(tempfile.gettempdir(), 'cipherquest.db')


def _raw_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def initial_lives(mission: Dict[str, Any]) -> int:
    return 3 if mission.get("difficulty") in ("Mahir", "Ahli") or mission.get("is_boss") else 5


def time_limit_seconds(mission: Dict[str, Any]) -> int:
    return 20 * 60 if mission.get("difficulty") in ("Mahir", "Ahli") or mission.get("is_boss") else 30 * 60


def init_db():
    """Membuat tabel progres dan menambahkan kolom game tanpa menghapus data lama."""
    conn = _raw_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS player_progress (
            session_id TEXT NOT NULL,
            mission_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'locked',
            score INTEGER NOT NULL DEFAULT 0,
            hints_used INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_answer TEXT,
            target_input TEXT,
            correct_answer TEXT,
            hint_text TEXT,
            explanation_text TEXT,
            param_a INTEGER DEFAULT 2,
            param_b INTEGER DEFAULT 1,
            word_count INTEGER DEFAULT 2,
            is_rare INTEGER DEFAULT 0,
            question_prompt TEXT,
            mission_type TEXT DEFAULT 'encrypt',
            lives_remaining INTEGER DEFAULT 5,
            started_at REAL,
            time_limit_seconds INTEGER DEFAULT 1800,
            boss_hp INTEGER DEFAULT 5,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (session_id, mission_id)
        )
    """)

    cursor.execute("PRAGMA table_info(player_progress)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    new_cols = [
        ("target_input", "TEXT"), ("correct_answer", "TEXT"),
        ("hint_text", "TEXT"), ("explanation_text", "TEXT"),
        ("param_a", "INTEGER DEFAULT 2"), ("param_b", "INTEGER DEFAULT 1"),
        ("word_count", "INTEGER DEFAULT 2"), ("is_rare", "INTEGER DEFAULT 0"),
        ("question_prompt", "TEXT"), ("mission_type", "TEXT DEFAULT 'encrypt'"),
        ("lives_remaining", "INTEGER DEFAULT 5"), ("started_at", "REAL"),
        ("time_limit_seconds", "INTEGER DEFAULT 1800"), ("boss_hp", "INTEGER DEFAULT 5"),
    ]
    for col_name, col_type in new_cols:
        if col_name not in existing_columns:
            cursor.execute(f"ALTER TABLE player_progress ADD COLUMN {col_name} {col_type}")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS player_meta (
            session_id TEXT PRIMARY KEY,
            restart_count INTEGER NOT NULL DEFAULT 0,
            rank_override INTEGER
        )
    """)

    conn.commit()
    conn.close()


def get_db_connection() -> sqlite3.Connection:
    db_path = get_db_path()
    if not os.path.exists(db_path):
        init_db()
    return _raw_db_connection()


def get_mission_by_id(mission_id: int) -> Optional[Dict[str, Any]]:
    for mission in MISSIONS_DATA:
        if mission["id"] == mission_id:
            return dict(mission)
    return None


def _merge_saved_question(mission: Dict[str, Any], row: sqlite3.Row) -> Dict[str, Any]:
    saved = dict(mission)
    for key, column in (
        ("target_input", "target_input"), ("correct_answer", "correct_answer"),
        ("hint", "hint_text"), ("explanation", "explanation_text"),
        ("prompt_question", "question_prompt"), ("mission_type", "mission_type"),
    ):
        if column in row.keys() and row[column] is not None:
            saved[key] = row[column]
    for key in ("param_a", "param_b", "word_count", "is_rare", "status", "score",
                "hints_used", "attempts", "last_answer", "lives_remaining", "started_at",
                "time_limit_seconds", "boss_hp"):
        if key in row.keys():
            saved[key] = row[key]
    saved["is_rare"] = bool(saved.get("is_rare", False))
    saved["is_boss"] = saved.get("mission_type") == "boss" or saved.get("id") == 25
    saved["initial_lives"] = initial_lives(saved)
    # Data dari database versi lama disesuaikan; nilai 0 tetap berarti game over.
    stored_lives = saved.get("lives_remaining")
    if stored_lives is None:
        stored_lives = saved["initial_lives"]
    saved["lives_remaining"] = min(stored_lives, saved["initial_lives"])
    expected_limit = time_limit_seconds(saved)
    saved["time_limit_seconds"] = min(saved.get("time_limit_seconds") or expected_limit, expected_limit)
    start = saved.get("started_at") or time.time()
    saved["started_at"] = start
    saved["time_limit_minutes"] = int(saved.get("time_limit_seconds", expected_limit) / 60)
    saved["remaining_seconds"] = max(0, int(saved.get("time_limit_seconds", expected_limit) - (time.time() - start)))
    return saved


def get_mission_for_session(session_id: str, mission_id: int, force_new: bool = False,
                            restart: bool = False) -> Optional[Dict[str, Any]]:
    """Memuat soal yang stabil per sesi; retry mereset nyawa dan timer misi itu saja."""
    base_mission = get_mission_by_id(mission_id)
    if not base_mission:
        return None

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM player_progress WHERE session_id = ? AND mission_id = ?
    """, (session_id, mission_id))
    row = cursor.fetchone()
    now = time.time()

    if row and row["target_input"] and not force_new and not restart:
        mission = _merge_saved_question(base_mission, row)
        # Persist defaults/migration values once so refresh tidak mengulang timer lama.
        if (not row["started_at"] or row["lives_remaining"] != mission["lives_remaining"] or
                row["time_limit_seconds"] != mission["time_limit_seconds"]):
            cursor.execute("""UPDATE player_progress SET started_at=?, lives_remaining=?, time_limit_seconds=?
                              WHERE session_id=? AND mission_id=?""",
                           (mission["started_at"], mission["lives_remaining"], mission["time_limit_seconds"],
                            session_id, mission_id))
            conn.commit()
        if mission.get("status") not in ("completed", "failed") and mission["remaining_seconds"] <= 0:
            cursor.execute("""
                UPDATE player_progress SET status='failed', updated_at=CURRENT_TIMESTAMP
                WHERE session_id=? AND mission_id=?
            """, (session_id, mission_id))
            conn.commit()
            mission["status"] = "failed"
        conn.close()
        return mission

    new_data = generate_mission_data(mission_id)
    lives = initial_lives(base_mission)
    limit_seconds = time_limit_seconds(base_mission)
    if row and not restart:
        lives = row["lives_remaining"] if row["lives_remaining"] is not None else lives
        started_at = row["started_at"] or now
        limit_seconds = row["time_limit_seconds"] or limit_seconds
        boss_hp = row["boss_hp"] if row["boss_hp"] is not None else 5
        current_score = row["score"] or 0
        current_attempts = row["attempts"] or 0
        current_hints = row["hints_used"] or 0
        current_status = row["status"] if row["status"] not in ("failed", "completed") else "available"
    else:
        started_at = now
        boss_hp = 5
        current_score = 0
        current_attempts = 0
        current_hints = 0
        current_status = "available"

    cursor.execute("""
        INSERT INTO player_progress (
            session_id, mission_id, status, score, hints_used, attempts,
            target_input, correct_answer, hint_text, explanation_text,
            param_a, param_b, word_count, is_rare, question_prompt, mission_type,
            lives_remaining, started_at, time_limit_seconds, boss_hp, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(session_id, mission_id) DO UPDATE SET
            status=excluded.status,
            score=excluded.score,
            hints_used=excluded.hints_used,
            attempts=excluded.attempts,
            target_input=excluded.target_input,
            correct_answer=excluded.correct_answer,
            hint_text=excluded.hint_text,
            explanation_text=excluded.explanation_text,
            param_a=excluded.param_a,
            param_b=excluded.param_b,
            word_count=excluded.word_count,
            is_rare=excluded.is_rare,
            question_prompt=excluded.question_prompt,
            mission_type=excluded.mission_type,
            lives_remaining=excluded.lives_remaining,
            started_at=excluded.started_at,
            time_limit_seconds=excluded.time_limit_seconds,
            boss_hp=excluded.boss_hp,
            updated_at=CURRENT_TIMESTAMP
    """, (
        session_id, mission_id, current_status, current_score, current_hints, current_attempts,
        new_data["target_input"], new_data["correct_answer"], new_data["hint"],
        new_data["explanation"], new_data["param_a"], new_data["param_b"],
        new_data["word_count"], 1 if new_data["is_rare"] else 0,
        new_data["prompt_question"], new_data["mission_type"], lives, started_at,
        limit_seconds, boss_hp,
    ))
    conn.commit()
    cursor.execute("SELECT * FROM player_progress WHERE session_id=? AND mission_id=?", (session_id, mission_id))
    saved_row = cursor.fetchone()
    conn.close()
    return _merge_saved_question(base_mission, saved_row)


def get_player_meta(session_id: str) -> Dict[str, Any]:
    """Mengambil penghitung restart dan pilihan rank pemain."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO player_meta (session_id) VALUES (?)", (session_id,))
    cursor.execute("SELECT restart_count, rank_override FROM player_meta WHERE session_id=?", (session_id,))
    row = cursor.fetchone()
    conn.commit()
    conn.close()
    return dict(row) if row else {"restart_count": 0, "rank_override": None}


def set_player_rank(session_id: str, rank: int) -> bool:
    """Mengatur rank pemain dari halaman admin (1 sampai 5)."""
    if rank not in range(1, 6):
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO player_meta (session_id) VALUES (?)", (session_id,))
    cursor.execute("UPDATE player_meta SET rank_override=? WHERE session_id=?", (rank, session_id))
    conn.commit()
    conn.close()
    return True


def get_player_stats(session_id: str) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT mission_id, status, score FROM player_progress WHERE session_id=?", (session_id,))
    rows = cursor.fetchall()
    conn.close()
    progress = {row["mission_id"]: dict(row) for row in rows}
    total_score = sum(item["score"] for item in progress.values() if item["status"] == "completed")
    completed_count = sum(1 for item in progress.values() if item["status"] == "completed")
    total_missions = len(MISSIONS_DATA)
    progress_pct = int(completed_count / total_missions * 100) if total_missions else 0
    last_mission = next((m["title"] for m in reversed(MISSIONS_DATA)
                         if m["id"] in progress and progress[m["id"]]["status"] == "completed"),
                        "Misi 01 (Belum Dimulai)")
    meta = get_player_meta(session_id)
    restart_count = int(meta.get("restart_count") or 0)
    rank = meta.get("rank_override") or min(5, restart_count + 1)
    boss_defeated = bool(progress.get(25) and progress[25]["status"] == "completed")
    return {
        "total_score": total_score,
        "completed_count": completed_count,
        "total_missions": total_missions,
        "progress_pct": progress_pct,
        "last_mission": last_mission,
        "restart_count": restart_count,
        "restart_limit": 5,
        "rank": int(rank),
        "rank_override": meta.get("rank_override"),
        "boss_defeated": boss_defeated,
        "can_restart_progress": boss_defeated and restart_count < 5,
    }


def get_missions_list(session_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM player_progress WHERE session_id=?", (session_id,))
    rows = cursor.fetchall()
    conn.close()
    progress = {row["mission_id"]: dict(row) for row in rows}

    result = []
    previous_completed = True
    for base in MISSIONS_DATA:
        item = dict(base)
        row = progress.get(item["id"])
        if row and row["status"] == "completed":
            item.update(status="completed", status_label="Selesai", is_unlocked=True,
                        score=row["score"], hints_used=row["hints_used"], attempts=row["attempts"])
            previous_completed = True
        elif previous_completed:
            failed = bool(row and row["status"] == "failed")
            item.update(status="failed" if failed else "available",
                        status_label="Gagal" if failed else "Tersedia", is_unlocked=True,
                        score=row["score"] if row else 0,
                        hints_used=row["hints_used"] if row else 0,
                        attempts=row["attempts"] if row else 0)
            previous_completed = False
        else:
            item.update(status="locked", status_label="Terkunci", is_unlocked=False,
                        score=0, hints_used=0, attempts=0)
        result.append(item)
    return result


def get_mission_chapters(session_id: str) -> List[Dict[str, Any]]:
    missions = get_missions_list(session_id)
    chapters = []
    for number, title in _CHAPTERS:
        chapter_missions = [m for m in missions if m.get("chapter_no") == number]
        chapters.append({"number": number, "title": title, "missions": chapter_missions})
    return chapters


def _mark_failed(cursor, session_id: str, mission_id: int):
    cursor.execute("""
        UPDATE player_progress SET status='failed', updated_at=CURRENT_TIMESTAMP
        WHERE session_id=? AND mission_id=?
    """, (session_id, mission_id))


def submit_mission_answer(session_id: str, mission_id: int, user_answer: str,
                          used_hint: bool = False) -> Dict[str, Any]:
    mission = get_mission_for_session(session_id, mission_id)
    if not mission:
        return {"success": False, "error": "Misi tidak ditemukan."}

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM player_progress WHERE session_id=? AND mission_id=?", (session_id, mission_id))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"success": False, "error": "Data progres misi tidak ditemukan."}

    now = time.time()
    remaining = (row["time_limit_seconds"] or time_limit_seconds(mission)) - (now - (row["started_at"] or now))
    if row["status"] in ("failed", "completed") or remaining <= 0:
        if remaining <= 0 and row["status"] != "completed":
            _mark_failed(cursor, session_id, mission_id)
            conn.commit()
        lives_left = row["lives_remaining"] or 0
        conn.close()
        return {"success": False, "is_correct": False, "expired": remaining <= 0,
                "lives_remaining": lives_left, "error": "Waktu habis atau misi sudah tidak aktif."}

    expected = (row["correct_answer"] or "").strip()
    supplied = (user_answer or "").strip()
    mission_type = row["mission_type"] or mission.get("mission_type", "encrypt")
    if mission_type == "encrypt":
        is_correct = " ".join(supplied.split()) == " ".join(expected.split())
    else:
        is_correct = " ".join(supplied.upper().split()) == " ".join(expected.upper().split())

    attempts = (row["attempts"] or 0) + 1
    lives_left = row["lives_remaining"] if row["lives_remaining"] is not None else initial_lives(mission)
    if is_correct and mission_type == "boss":
        boss_hp = max(0, (row["boss_hp"] if row["boss_hp"] is not None else 5) - 1)
        if boss_hp == 0:
            cursor.execute("""
                UPDATE player_progress SET status='completed', score=500, attempts=?, last_answer=?,
                    boss_hp=0, updated_at=CURRENT_TIMESTAMP
                WHERE session_id=? AND mission_id=?
            """, (attempts, supplied, session_id, mission_id))
            conn.commit()
            conn.close()
            return {"success": True, "is_correct": True, "boss_defeated": True,
                    "boss_hp_remaining": 0, "lives_remaining": lives_left,
                    "earned_score": 500, "total_mission_score": 500,
                    "penalty": 0, "explanation": mission["explanation"], "mission": mission}

        next_question = generate_boss_mission_data()
        cursor.execute("""
            UPDATE player_progress SET target_input=?, correct_answer=?, hint_text=?,
                explanation_text=?, param_a=?, param_b=?, word_count=1, is_rare=0,
                question_prompt=?, mission_type='boss', boss_hp=?, attempts=?, last_answer=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE session_id=? AND mission_id=?
        """, (next_question["target_input"], next_question["correct_answer"],
              next_question["hint"], next_question["explanation"], next_question["param_a"],
              next_question["param_b"], next_question["prompt_question"], boss_hp,
              attempts, supplied, session_id, mission_id))
        conn.commit()
        conn.close()
        return {"success": True, "is_correct": True, "boss_hit": True,
                "boss_hp_remaining": boss_hp, "lives_remaining": lives_left,
                "earned_score": 100, "total_mission_score": 0, "penalty": 0,
                "explanation": "Serangan berhasil! HP penjaga berkurang satu.", "mission": mission}

    if is_correct:
        score = max(row["score"] or 0, 100 - (20 if used_hint else 0))
        cursor.execute("""
            UPDATE player_progress SET status='completed', score=?, hints_used=?, attempts=?,
                last_answer=?, updated_at=CURRENT_TIMESTAMP
            WHERE session_id=? AND mission_id=?
        """, (score, 1 if used_hint else row["hints_used"], attempts, supplied, session_id, mission_id))
        conn.commit()
        conn.close()
        return {"success": True, "is_correct": True, "earned_score": score,
                "total_mission_score": score, "penalty": 20 if used_hint else 0,
                "lives_remaining": lives_left, "explanation": mission["explanation"], "mission": mission}

    lives_left = max(0, lives_left - 1)
    new_status = "failed" if lives_left == 0 else row["status"]
    cursor.execute("""
        UPDATE player_progress SET status=?, lives_remaining=?, attempts=?, last_answer=?,
            hints_used=CASE WHEN ?=1 THEN 1 ELSE hints_used END,
            updated_at=CURRENT_TIMESTAMP
        WHERE session_id=? AND mission_id=?
    """, (new_status, lives_left, attempts, supplied, 1 if used_hint else 0, session_id, mission_id))
    conn.commit()
    conn.close()
    return {"success": True, "is_correct": False, "earned_score": 0,
            "total_mission_score": row["score"] or 0, "penalty": 0,
            "lives_remaining": lives_left, "game_over": lives_left == 0,
            "boss_hp_remaining": row["boss_hp"] if mission_type == "boss" else None,
            "explanation": "Jawaban belum sesuai. Periksa kembali petunjuk dan perhitungan Anda.",
            "mission": mission}


def regenerate_mission_question(session_id: str, mission_id: int) -> Optional[Dict[str, Any]]:
    return get_mission_for_session(session_id, mission_id, force_new=True)


def restart_progress(session_id: str) -> Dict[str, Any]:
    """Restart penuh hanya tersedia setelah bos dikalahkan, maksimal lima kali."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("BEGIN IMMEDIATE")
    cursor.execute("SELECT status FROM player_progress WHERE session_id=? AND mission_id=25", (session_id,))
    boss_row = cursor.fetchone()
    cursor.execute("INSERT OR IGNORE INTO player_meta (session_id) VALUES (?)", (session_id,))
    cursor.execute("SELECT restart_count FROM player_meta WHERE session_id=?", (session_id,))
    meta_row = cursor.fetchone()
    restart_count = int(meta_row["restart_count"] or 0) if meta_row else 0

    if not boss_row or boss_row["status"] != "completed":
        conn.rollback()
        conn.close()
        return {"success": False, "reason": "locked", "restart_count": restart_count}
    if restart_count >= 5:
        conn.rollback()
        conn.close()
        return {"success": False, "reason": "limit", "restart_count": restart_count}

    restart_count += 1
    cursor.execute("DELETE FROM player_progress WHERE session_id=?", (session_id,))
    cursor.execute("UPDATE player_meta SET restart_count=? WHERE session_id=?", (restart_count, session_id))
    conn.commit()
    conn.close()
    return {"success": True, "restart_count": restart_count}



# Kompatibilitas untuk fixture/pembersihan pengujian lama.
def reset_progress(session_id: str):
    """Menghapus data progres sesi untuk keperluan setup pengujian lokal."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM player_progress WHERE session_id=?", (session_id,))
    cursor.execute("DELETE FROM player_meta WHERE session_id=?", (session_id,))
    conn.commit()
    conn.close()
