"""
app.py - Aplikasi Utama Flask CipherQuest
CipherQuest — Decode the Message, Complete the Mission
Game Edukasi Kriptografi Matematika: Komposisi & Invers Fungsi
"""

import os
import uuid
import hmac
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, abort
)

from config import Config
from database import (
    init_db, get_player_stats, get_missions_list,
    get_mission_for_session, get_mission_chapters, regenerate_mission_question,
    submit_mission_answer, restart_progress, set_player_rank
)
from cipher import get_formula_metadata, DEFAULT_A, DEFAULT_B
from encrypt import encrypt_message
from decrypt import decrypt_ciphertext

app = Flask(__name__)
app.config.from_object(Config)
app.jinja_env.filters['chr'] = chr

# Inisialisasi Database saat aplikasi dijalankan
with app.app_context():
    try:
        init_db()
    except Exception as e:
        app.logger.warning("Inisialisasi database awal ditangguhkan: %s", str(e))


@app.before_request
def ensure_session_identity():
    """Memastikan setiap pengunjung memiliki session_id unik untuk progres game."""
    if 'player_id' not in session:
        session['player_id'] = uuid.uuid4().hex


@app.context_processor
def inject_global_game_data():
    """Menyediakan data statistik pemain dan metadata rumus default ke seluruh template."""
    player_id = session.get('player_id', '')
    stats = get_player_stats(player_id)
    return {
        "player_stats": stats,
        "formulas": get_formula_metadata(),
        "is_admin": bool(session.get("is_admin"))
    }


# ==========================================
# ROUTES UTAMA
# ==========================================

@app.route('/')
def index():
    """Halaman Beranda dengan Hero Section, Briefing Intelijen, dan Dashboard."""
    player_id = session.get('player_id', '')
    stats = get_player_stats(player_id)
    missions = get_missions_list(player_id)
    return render_template('index.html', stats=stats, missions=missions)


@app.route('/missions')
def missions():
    """Halaman Papan Misi."""
    player_id = session.get('player_id', '')
    missions_list = get_missions_list(player_id)
    chapters = get_mission_chapters(player_id)
    boss = next((item for item in missions_list if item.get('is_boss')), None)
    stats = get_player_stats(player_id)
    return render_template('missions.html', missions=missions_list, chapters=chapters, boss=boss, stats=stats)


@app.route('/mission/<int:mission_id>', methods=['GET', 'POST'])
def mission_detail(mission_id: int):
    """Halaman pengerjaan misi dengan sistem nyawa, timer, dan ronde bos."""
    player_id = session.get('player_id', '')
    missions_list = get_missions_list(player_id)
    current_entry = next((item for item in missions_list if item['id'] == mission_id), None)
    if not current_entry:
        abort(404)
    admin_mode = bool(session.get('is_admin'))
    if not current_entry['is_unlocked'] and not admin_mode:
        flash("Misi ini masih terkunci! Selesaikan misi sebelumnya terlebih dahulu.", "warning")
        return redirect(url_for('missions'))

    restart = (
        request.args.get('retry') == '1' and current_entry.get('status') in ('failed', 'completed')
    ) or (admin_mode and current_entry.get('status') in ('failed', 'completed'))
    mission = get_mission_for_session(player_id, mission_id, restart=restart)
    if not mission:
        abort(404)

    if request.method == 'POST':
        if request.form.get('time_expired') == '1':
            # Server tetap memeriksa waktu; pengiriman manual lebih awal tidak dapat menghabiskan timer.
            get_mission_for_session(player_id, mission_id)
            flash("Waktu misi telah habis. Anda dapat mengulang misi dari papan misi.", "danger")
            return redirect(url_for('missions'))

        user_answer = request.form.get('answer', '')
        used_hint = request.form.get('used_hint', '0') == '1'
        if not user_answer.strip():
            flash("Silakan masukkan jawaban terlebih dahulu.", "danger")
            return redirect(url_for('mission_detail', mission_id=mission_id))

        result = submit_mission_answer(player_id, mission_id, user_answer, used_hint=used_hint)
        if result.get('expired'):
            flash("Waktu misi telah habis. Ulangi misi untuk mencoba lagi.", "danger")
            return redirect(url_for('missions'))
        if not result.get('success'):
            flash(result.get('error', "Misi tidak dapat diproses."), "warning")
            return redirect(url_for('mission_detail', mission_id=mission_id))

        # Ronde bos: satu jawaban benar mengurangi HP dan langsung memunculkan soal baru.
        if result.get('boss_hit'):
            flash(f"Serangan berhasil! HP bos tersisa {result['boss_hp_remaining']}/5.", "success")
            return redirect(url_for('mission_detail', mission_id=mission_id))

        if result.get('boss_defeated'):
            flash("BOS DIKALAHKAN! Seluruh ronde berhasil diselesaikan.", "success")

        solution_steps = None
        solution_type = None
        formula_info = None
        derivation_steps = None
        correct_answer = mission.get('correct_answer', '')
        target_input = mission.get('target_input', '')
        param_a = mission.get('param_a', 2)
        param_b = mission.get('param_b', 1)

        try:
            if mission.get('mission_type') == 'encrypt':
                enc = encrypt_message(target_input, a=param_a, b=param_b)
                if enc.get('success'):
                    solution_steps = enc['steps']
                    formula_info = enc['formula_info']
                    solution_type = 'encrypt'
            elif mission.get('mission_type') == 'decrypt':
                dec = decrypt_ciphertext(target_input, a=param_a, b=param_b)
                if dec.get('success'):
                    solution_steps = dec['steps']
                    formula_info = dec['formula_info']
                    derivation_steps = dec['derivation_steps']
                    solution_type = 'decrypt'
        except Exception:
            pass

        session['last_result'] = {
            "mission_id": mission_id,
            "mission_title": mission['title'],
            "mission_code": mission['code'],
            "user_answer": user_answer,
            "is_correct": result['is_correct'],
            "earned_score": result.get('earned_score', 0),
            "penalty": result.get('penalty', 0),
            "total_mission_score": result.get('total_mission_score', 0),
            "explanation": result.get('explanation', ''),
            "next_mission_id": mission_id + 1 if mission_id < 25 else None,
            "solution_type": solution_type,
            "solution_steps": solution_steps,
            "formula_info": formula_info,
            "derivation_steps": derivation_steps,
            "correct_answer": correct_answer,
            "target_input": target_input,
            "param_a": param_a,
            "param_b": param_b,
            "lives_remaining": result.get('lives_remaining', mission.get('lives_remaining', 0)),
            "game_over": result.get('game_over', False),
            "boss_hp_remaining": result.get('boss_hp_remaining', mission.get('boss_hp', 5)),
            "boss_defeated": result.get('boss_defeated', False),
        }
        return redirect(url_for('mission_result'))

    return render_template(
        'mission_detail.html',
        mission=mission,
        mission_failed=mission.get('status') == 'failed',
        mission_completed=mission.get('status') == 'completed'
    )


@app.route('/mission/<int:mission_id>/new-question', methods=['POST'])
def new_mission_question(mission_id: int):
    """Mengacak soal tanpa mengisi ulang nyawa atau mengulang timer."""
    player_id = session.get('player_id', '')
    mission_entry = next((item for item in get_missions_list(player_id) if item['id'] == mission_id), None)
    if not mission_entry or (not mission_entry['is_unlocked'] and not session.get('is_admin')):
        abort(404)
    active_mission = get_mission_for_session(player_id, mission_id)
    if active_mission and active_mission.get('status') not in ('failed', 'completed'):
        regenerate_mission_question(player_id, mission_id)
        flash("Markas Intelijen telah mengirimkan transmisi target baru untuk misi ini! Nyawa dan timer tetap berjalan.", "info")
    else:
        flash("Misi ini tidak aktif. Mulai ulang dari papan misi.", "warning")
    return redirect(url_for('mission_detail', mission_id=mission_id))


@app.route('/mission/result')
def mission_result():
    """Halaman Menampilkan Hasil Evaluasi Misi."""
    result_data = session.get('last_result')
    if not result_data:
        return redirect(url_for('missions'))
    return render_template('result.html', result=result_data)


@app.route('/encrypt', methods=['GET', 'POST'])
def encrypt_lab():
    """Halaman Laboratorium Enkripsi Pesan dengan Parameter Kustom."""
    result = None
    input_text = ""
    
    # Ambil parameter kustom a dan b
    raw_a = request.form.get('param_a') or request.args.get('a') or str(DEFAULT_A)
    raw_b = request.form.get('param_b') or request.args.get('b') or str(DEFAULT_B)

    try:
        a_val = int(raw_a)
    except (ValueError, TypeError):
        a_val = DEFAULT_A

    try:
        b_val = int(raw_b)
    except (ValueError, TypeError):
        b_val = DEFAULT_B

    if request.method == 'POST':
        input_text = request.form.get('plaintext', '')
        result = encrypt_message(input_text, a=a_val, b=b_val)

    if request.method == 'GET' and request.args.get('demo') == 'aku':
        input_text = "AKU"
        a_val, b_val = DEFAULT_A, DEFAULT_B
        result = encrypt_message(input_text, a=a_val, b=b_val)

    formula_info = get_formula_metadata(a_val, b_val)
    return render_template(
        'encrypt.html',
        result=result,
        input_text=input_text,
        param_a=a_val,
        param_b=b_val,
        formula_info=formula_info
    )

@app.route('/decrypt', methods=['GET', 'POST'])
def decrypt_lab():
    """Halaman Laboratorium Dekripsi Pesan dengan Parameter Kustom dan Langkah Penurunan."""
    result = None
    input_text = ""

    # Ambil parameter kustom a dan b
    raw_a = request.form.get('param_a') or request.args.get('a') or str(DEFAULT_A)
    raw_b = request.form.get('param_b') or request.args.get('b') or str(DEFAULT_B)

    try:
        a_val = int(raw_a)
    except (ValueError, TypeError):
        a_val = DEFAULT_A

    try:
        b_val = int(raw_b)
    except (ValueError, TypeError):
        b_val = DEFAULT_B

    if request.method == 'POST':
        input_text = request.form.get('ciphertext', '')
        result = decrypt_ciphertext(input_text, a=a_val, b=b_val)

    if request.method == 'GET' and request.args.get('demo') == 'aku':
        input_text = "5 25 45"
        a_val, b_val = DEFAULT_A, DEFAULT_B
        result = decrypt_ciphertext(input_text, a=a_val, b=b_val)

    formula_info = get_formula_metadata(a_val, b_val)
    return render_template(
        'decrypt.html',
        result=result,
        input_text=input_text,
        param_a=a_val,
        param_b=b_val,
        formula_info=formula_info
    )


@app.route('/tutorial')
def tutorial():
    """Halaman Tutorial Materi Kriptografi, Komposisi Fungsi, dan Invers."""
    demo_enc = encrypt_message("AKU", a=DEFAULT_A, b=DEFAULT_B)
    demo_dec = decrypt_ciphertext("5 25 45", a=DEFAULT_A, b=DEFAULT_B)
    return render_template('tutorial.html', demo_enc=demo_enc, demo_dec=demo_dec)


@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    """Halaman admin untuk demo presentasi: lompat misi dan mengatur rank."""
    player_id = session.get('player_id', '')
    if not session.get('is_admin'):
        if request.method == 'POST':
            supplied = request.form.get('admin_code', '').strip().upper()
            expected = os.environ.get('CIPHERQUEST_ADMIN_CODE', 'JOSJIS BOLO').strip().upper()
            if hmac.compare_digest(supplied.encode('utf-8'), expected.encode('utf-8')):
                session['is_admin'] = True
                flash("Akses admin berhasil dibuka. Mode presentasi aktif.", "success")
                return redirect(url_for('admin_panel'))
            flash("Kode admin tidak sesuai.", "danger")
        return render_template('admin.html', admin_authenticated=False)

    if request.method == 'POST':
        action = request.form.get('action', '')
        if action == 'set_rank':
            try:
                rank = int(request.form.get('rank', '1'))
            except (TypeError, ValueError):
                rank = 0
            if set_player_rank(player_id, rank):
                flash(f"Rank presentasi berhasil diatur ke Rank {rank}.", "success")
            else:
                flash("Rank harus berada pada rentang 1 sampai 5.", "danger")
            return redirect(url_for('admin_panel'))
        if action == 'jump':
            try:
                mission_id = int(request.form.get('mission_id', '0'))
            except (TypeError, ValueError):
                mission_id = 0
            if 1 <= mission_id <= 25:
                return redirect(url_for('mission_detail', mission_id=mission_id))
            flash("Pilih misi yang valid.", "warning")
            return redirect(url_for('admin_panel'))
        if action == 'logout':
            session.pop('is_admin', None)
            flash("Mode admin ditutup.", "info")
            return redirect(url_for('index'))

    return render_template(
        'admin.html',
        admin_authenticated=True,
        missions=get_missions_list(player_id),
        stats=get_player_stats(player_id),
    )


@app.route('/reset-progress', methods=['POST'])
def reset_user_progress():
    """Restart penuh terkunci sampai bos dikalahkan dan dibatasi lima kali."""
    player_id = session.get('player_id', '')
    outcome = restart_progress(player_id)
    if not outcome.get('success'):
        if outcome.get('reason') == 'limit':
            flash("Batas lima kali restart sudah tercapai.", "warning")
        else:
            flash("Restart Progres masih terkunci. Kalahkan bos setelah menyelesaikan 24 misi terlebih dahulu.", "warning")
        return redirect(url_for('missions'))
    session.pop('last_result', None)
    flash(f"Restart ke-{outcome['restart_count']}/5 berhasil. Skor restart bertambah dan rank meningkat!", "success")
    return redirect(url_for('missions'))


# ==========================================
# ERROR HANDLERS
# ==========================================

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('404.html', custom_message="Terjadi gangguan transmisi internal server (500)."), 500

# --- TAMBAHKAN RUTE VARIAN 1: DEKRIPSI DI SINI ---
@app.route('/mission/decrypt', methods=['GET', 'POST'])
def mission_decrypt():
    cipher_text_display = "25 45 31 9 21"
    correct_plaintext = "KUNCI"
    
    if request.method == 'POST':
        user_answer = request.form.get('answer').strip().upper()
        if user_answer == correct_plaintext:
            return render_template('result_decrypt.html', status="SUCCESS", user=user_answer)
        else:
            return render_template('result_decrypt.html', status="FAILED", user=user_answer, correct=correct_plaintext)
            
    return render_template('mission_decrypt.html', cipher=cipher_text_display)

if __name__ == '__main__':
    host = os.environ.get('FLASK_RUN_HOST', os.environ.get('HOST', '127.0.0.1'))
    port = int(os.environ.get('FLASK_RUN_PORT', os.environ.get('PORT', 5000)))
    debug = os.environ.get('FLASK_DEBUG', '0') in ('1', 'true', 'True')
    app.run(host=host, port=port, debug=debug)

