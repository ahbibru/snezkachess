import os
import io
import json
import time
import uuid
import shutil
import random
import requests
from flask import Flask, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
import chess
import chess.engine
import chess.pgn

app = Flask(__name__)
app.config['SECRET_KEY'] = 'snezka_super_secret_master_key_999'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///snezkachess_v2.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
login_manager = LoginManager(app)

STOCKFISH_PATH = shutil.which("stockfish") or "/usr/games/stockfish"
ENGINE_OPTIONS = {"Threads": 1, "Hash": 16}

# --- МОДЕЛИ БАЗЫ ДАННЫХ SQLITE ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    elo_bullet = db.Column(db.Integer, default=1500)
    elo_blitz = db.Column(db.Integer, default=1500)
    elo_rapid = db.Column(db.Integer, default=1500)
    elo_classical = db.Column(db.Integer, default=1500)
    puzzles_elo = db.Column(db.Integer, default=1200)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

# --- ВНУТРЕННЯЯ ПАМЯТЬ МУЛЬТИПЛЕЕРА ---

MATCHMAKING_QUEUES = {"bullet": [], "blitz": [], "rapid": [], "classical": []}
ACTIVE_ROOMS = {}
USER_SID_MAP = {}

# --- БАЗА ДАННЫХ ДЕБЮТОВ (25 ПОЛНЫХ СИСТЕМ) ---

OPENINGS_DB = {
    "ruy_lopez": {"name": "Испанская партия (Ruy Lopez)", "eco": "C60", "fen": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3", "desc": "Король открытых дебютов. Белые связывают коня c6, оказывая косвенное давление на пешку e5."},
    "sicilian_najdorf": {"name": "Сицилианская: Вариант Найдорфа", "eco": "B90", "fen": "rnbqkb1r/1p2pppp/p2p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6", "desc": "Излюбленное оружие Гарри Каспарова и Роберта Фишеры. Ход a6 берет под контроль поле b5."},
    "sicilian_dragon": {"name": "Сицилианская: Вариант Дракона", "eco": "B70", "fen": "rnbq1rk1/pp2ppbp/3p1np1/8/3NP3/2N1BP2/PPP3PP/R2QKB1R w KQ - 3 8", "desc": "Черная пешечная структура напоминает созвездие Дракона. Фианкеттированный слон g7 простреливает всю диагональ."},
    "italian_game": {"name": "Итальянская партия (Giuoco Piano)", "eco": "C50", "fen": "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3", "desc": "Белые развивают слона на самую уязвимую точку черных — пункт f7."},
    "evans_gambit": {"name": "Гамбит Эванса", "eco": "C51", "fen": "r1bqk1nr/pppp1ppp/2n5/2b1p3/1PB1P3/5N2/P1PP1PPP/RNBQK2R b KQkq b3 0 4", "desc": "Агрессивная жертва пешки b4 ради мгновенного вскрытия центральных вертикалей."},
    "qgd": {"name": "Ферзевый гамбит отклоненный", "eco": "D30", "fen": "rnbqkbnr/ppp2ppp/4p3/3p4/2PP4/8/PP2PPPP/RNBQKBNR w KQkq - 0 3", "desc": "Железобетонная классика. Черные укрепляют центр ходом e6, сохраняя контроль над полем d5."},
    "qga": {"name": "Ферзевый гамбит принятый", "eco": "D20", "fen": "rnbqkbnr/ppp1pppp/8/8/2pP4/8/PP2PPPP/RNBQKBNR w KQkq - 0 3", "desc": "Черные забирают пешку c4, временно уступая центр ради быстрой фигурной контригры."},
    "kings_indian": {"name": "Староиндийская защита", "eco": "E60", "fen": "rnbq1rk1/ppp1ppbp/3p1np1/8/2PPP3/2N2N2/PP3PPP/R1BQKB1R w KQ - 2 6", "desc": "Черные отдают белым весь пешечный центр, чтобы в миттельшпиле обрушить на него шквал ударов."},
    "nimzo_indian": {"name": "Защита Нимзовича", "eco": "E20", "fen": "rnbqk2r/pppp1ppp/4pn2/8/1bPP4/2N5/PP2PPPP/R1BQKBNR w KQkq - 2 4", "desc": "Связка коня c3 мешает белым провести захват центра ходом e4."},
    "caro_kann": {"name": "Защита Каро-Канн", "eco": "B10", "fen": "rnbqkbnr/pp1ppppp/2p5/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2", "desc": "Один из самых прочных ответов на 1.e4. Пешка c6 подготавливает удар d5 без блокировки слона c8."},
    "french": {"name": "Французская защита", "eco": "C00", "fen": "rnbqkbnr/pppp1ppp/4p3/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2", "desc": "Острая стратегическая борьба. Черные создают прочную пешечную цепь d5-e6."},
    "slav": {"name": "Славянская защита", "eco": "D10", "fen": "rnbqkbnr/pp2pppp/2p5/3p4/2PP4/8/PP2PPPP/RNBQKBNR w KQkq - 0 3", "desc": "Улучшенная версия ферзевого гамбита. Слон c8 остается открытым для выхода в игру."},
    "english": {"name": "Английское начало", "eco": "A10", "fen": "rnbqkbnr/pppppppp/8/8/2P5/8/PP1PPPPP/RNBQKBNR b KQkq c3 0 1", "desc": "Фланговый дебют. Белые борются за поле d5 не пешкой e, а боковой пешкой c."},
    "reti": {"name": "Дебют Рети", "eco": "A04", "fen": "rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 1 1", "desc": "Гибкое гипермодернистское начало. Конь f3 контролирует центральные поля без немедленного выдвижения пешек."},
    "kings_gambit": {"name": "Королевский гамбит", "eco": "C30", "fen": "rnbqkbnr/pppp1ppp/8/4p3/4PP2/8/PPPP2PP/RNBQKBNR b KQkq f3 0 2", "desc": "Дебют романтиков XIX века. Белые жертвуют пешку f4 ради атаки по открытой вертикали 'f'."},
    "vienna": {"name": "Венская партия", "eco": "C25", "fen": "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/2N5/PPPP1PPP/R1BQKBNR w KQkq - 2 3", "desc": "Спокойное развитие коня на c3 подготавливает поздний подрыв центра f2-f4."},
    "scotch": {"name": "Шотландская партия", "eco": "C45", "fen": "r1bqkbnr/pppp1ppp/2n5/4p3/3PP3/5N2/PPP2PPP/RNBQKB1R b KQkq d3 0 3", "desc": "Белые мгновенно вскрывают игру в центре ходом d2-d4."},
    "scandinavian": {"name": "Скандинавская защита", "eco": "B01", "fen": "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2", "desc": "Прямолинейный немедленный вызов пешке e4 ходом ферзевой пешки."},
    "alekhine": {"name": "Защита Алехина", "eco": "B02", "fen": "rnbqkb1r/pppppppp/5n2/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 1 2", "desc": "Провокация. Черный конь заманивает пешки белых вперед, чтобы сделать их объектами атаки."},
    "pirc": {"name": "Защита Пирца-Уфимцева", "eco": "B07", "fen": "rnbqkbnr/ppp1pp1p/3p2p1/8/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 3", "desc": "Черные строят малый пешечный редут на фланге и готовят фианкетто слона."},
    "grunfeld": {"name": "Защита Грюнфельда", "eco": "D80", "fen": "rnbqkb1r/ppp1pp1p/5np1/3p4/2PP4/2N5/PP2PPPP/R1BQKBNR w KQkq d6 0 4", "desc": "Сочетание идей ферзевого гамбита и староиндийской защиты. Центр белых подвергается бомбардировке."},
    "dutch": {"name": "Голландская защита", "eco": "A80", "fen": "rnbqkbnr/ppppp1pp/8/5p2/3P4/8/PPP1PPPP/RNBQKBNR w KQkq f6 0 2", "desc": "Агрессивная борьба за пункт e4 ходом f7-f5."},
    "benoni": {"name": "Модерн-Бенони", "eco": "A56", "fen": "rnbqkbnr/pp1p1ppp/4p3/2p5/3PP3/8/PPP2PPP/RNBQKBNR w KQkq c6 0 3", "desc": "Острейшая асимметричная позиция. Черные получают большинство пешек на ферзевом фланге."},
    "trompowsky": {"name": "Атака Тромповского", "eco": "A45", "fen": "rnbqkb1r/pppppppp/5n2/6B1/3P4/8/PPP1PPPP/RN1QKBNR b KQkq - 2 2", "desc": "Неоригинальный выпад слоном на g5 сразу лишает черных привычных схем развития."},
    "london": {"name": "Лондонская система", "eco": "D02", "fen": "rnbqkb1r/ppp1pppp/5n2/3p4/3P1B2/5N2/PPP1PPPP/RN1QKB1R b KQkq - 3 3", "desc": "Универсальная расстановка белых. Слон f4 выходит за пределы пешечной цепи e3-c3."}
}

FALLBACK_PUZZLES = [
    {"id": 101, "rating": 1100, "fen": "r1b1k2r/ppppnppp/2n2q2/2b5/3NP3/2P1B3/PP3PPP/RN1QKB1R w KQkq - 3 7", "solution": ["d4c6", "c5e3", "c6d8"], "desc": "Локальная задача: Вскрытый удар"},
    {"id": 102, "rating": 1450, "fen": "2r3k1/p4ppp/1p2p3/3b4/3P4/q3PN2/1Q3PPP/2R3K1 b - - 1 22", "solution": ["c8c1", "b2c1", "a3c1"], "desc": "Локальная задача: Завлечение на 1-ю горизонталь"}
]

def get_optimal_depth(req_depth):
    if req_depth != "auto":
        return min(max(int(req_depth), 8), 20)
    try:
        load1, _, _ = os.getloadavg()
        cores = os.cpu_count() or 1
        return 11 if (load1 / cores) > 0.8 else (13 if (load1 / cores) > 0.5 else 16)
    except Exception:
        return 14

# --- МОНОЛИТНЫЙ HTML + CSS + JS ФРОНТЕНД ---

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>SnezkaChess | Grandmaster Arena v2</title>
    
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/chessboard-js/1.0.0/chessboard-1.0.0.min.css">
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/chessboard-js/1.0.0/chessboard-1.0.0.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/chess.js/0.10.3/chess.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
    
    <style>
        :root {
            --bg: #161512; --surface: #262421; --surface-hover: #363431;
            --accent: #629924; --accent-light: #81b64c;
            --text: #bababa; --text-bright: #ffffff; --border: #403d39;
            --board-light: #f0d9b5; --board-dark: #b58863;
        }
        
        * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); padding: 12px; }
        
        .navbar { display: flex; justify-content: space-between; align-items: center; max-width: 1150px; margin: 0 auto 12px auto; padding: 10px 16px; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; }
        .logo { font-weight: 800; color: var(--text-bright); font-size: 20px; letter-spacing: 0.5px; }
        .logo span { color: var(--accent-light); }
        .auth-zone { font-size: 13px; display: flex; gap: 10px; align-items: center; }
        
        .tabs { display: flex; gap: 4px; max-width: 1150px; margin: 0 auto 15px auto; overflow-x: auto; background: var(--surface); padding: 4px; border-radius: 6px; border: 1px solid var(--border); }
        .tab-btn { flex: 1; min-width: 130px; padding: 10px; text-align: center; cursor: pointer; font-weight: 600; font-size: 13px; color: var(--text); transition: 0.15s; border-radius: 4px; }
        .tab-btn:hover { color: var(--text-bright); }
        .tab-btn.active { background: var(--accent-light); color: #fff; }
        
        .main-grid { display: flex; gap: 18px; max-width: 1150px; margin: 0 auto; align-items: flex-start; flex-wrap: wrap; }
        .board-col { display: flex; flex: 0 0 500px; gap: 12px; width: 100%; max-width: 500px; }
        
        .eval-bar-wrapper { width: 18px; height: 460px; background: #ffffff; border-radius: 3px; overflow: hidden; display: flex; flex-direction: column; border: 1px solid var(--border); }
        .eval-black-fill { width: 100%; height: 50%; background: #111; transition: height 0.3s ease; }
        
        .board-container { flex: 1; display: flex; flex-direction: column; gap: 6px; }
        
        .chess-clock { display: flex; justify-content: space-between; align-items: center; background: var(--surface); padding: 8px 14px; border-radius: 4px; border: 1px solid var(--border); font-family: monospace; font-size: 19px; font-weight: bold; color: var(--text-bright); }
        .clock-active { background: #3c3831; border-color: var(--accent-light); color: #fff; box-shadow: 0 0 8px rgba(129,182,76,0.3); }
        .player-info { font-size: 13px; font-family: sans-serif; font-weight: normal; color: var(--text); display: flex; align-items: center; gap: 6px; }
        
        .white-1e1d7 { background-color: var(--board-light); }
        .black-3c85d { background-color: var(--board-dark); }
        .board-b72b1 { border: none !important; border-radius: 4px; box-shadow: 0 8px 24px rgba(0,0,0,0.6); }
        
        .hint-dot::after { content: ''; position: absolute; width: 28%; height: 28%; background: rgba(20, 85, 30, 0.45); border-radius: 50%; top: 36%; left: 36%; pointer-events: none; }
        .hint-capture::after { content: ''; position: absolute; width: 82%; height: 82%; border: 6px solid rgba(20, 85, 30, 0.45); border-radius: 50%; top: 9%; left: 9%; pointer-events: none; }
        
        .panel-col { flex: 1; min-width: 310px; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 18px; min-height: 520px; display: flex; flex-direction: column; }
        
        .eval-box { background: var(--bg); border-radius: 4px; padding: 14px; border-left: 4px solid var(--accent-light); margin-bottom: 15px; }
        .score-val { font-size: 32px; font-weight: bold; color: var(--text-bright); font-family: monospace; }
        
        .btn-row { display: flex; gap: 8px; margin-top: 10px; width: 100%; }
        .btn { background: var(--surface-hover); color: var(--text-bright); border: 1px solid var(--border); padding: 11px; border-radius: 4px; font-weight: 600; font-size: 13px; cursor: pointer; text-align: center; flex: 1; transition: 0.1s; }
        .btn:hover { background: #44413c; }
        .btn-accent { background: var(--accent); border-color: var(--accent); }
        .btn-accent:hover { background: var(--accent-light); }
        .btn-red { color: #ff6b6b; }
        
        .control-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 15px; }
        .time-card { background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 10px; text-align: center; cursor: pointer; transition: 0.1s; }
        .time-card:hover { border-color: #666; }
        .time-card.active { border-color: var(--accent-light); background: rgba(129, 182, 76, 0.12); }
        .time-card h4 { font-size: 14px; color: var(--text-bright); }
        .time-card p { font-size: 11px; color: #777; margin-top: 2px; }
        
        select, textarea, input[type="text"], input[type="password"] { width: 100%; background: var(--bg); border: 1px solid var(--border); color: #fff; padding: 10px; border-radius: 4px; margin-top: 6px; font-size: 13px; outline: none; }
        label { font-size: 12px; color: var(--text); font-weight: 600; }
        
        .theory-list { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; max-height: 280px; overflow-y: auto; padding-right: 4px; }
        .theory-item { background: var(--bg); padding: 10px; border-radius: 4px; cursor: pointer; border: 1px solid var(--border); transition: 0.1s; font-size: 13px; display: flex; justify-content: space-between; }
        .theory-item:hover { border-color: var(--accent-light); }
        
        /* МОДАЛЬНОЕ ОКНО АВТОРИЗАЦИИ */
        .modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); z-index: 9999; align-items: center; justify-content: center; padding: 15px; }
        .modal-box { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; width: 100%; max-width: 360px; padding: 22px; }
        .modal-tabs { display: flex; gap: 5px; margin-bottom: 15px; }
        
        .spinner { width: 42px; height: 42px; border: 4px solid rgba(255,255,255,0.1); border-top-color: var(--accent-light); border-radius: 50%; animation: spin 0.9s linear infinite; margin: 0 auto 15px auto; }
        @keyframes spin { to { transform: rotate(360deg); } }
        
        @media (max-width: 860px) {
            .board-col { flex: 0 0 100%; max-width: 100%; }
            .eval-bar-wrapper { height: 340px; width: 14px; }
            .panel-col { min-height: auto; }
        }
    </style>
</head>
<body>

<div class="navbar">
    <div class="logo">Snezka<span>Chess</span></div>
    <div class="auth-zone" id="authNavbarUI">
        <span style="color:#777">Загрузка...</span>
    </div>
</div>

<div class="tabs">
    <div class="tab-btn active" data-tab="sandbox">🔬 Анализ Stockfish</div>
    <div class="tab-btn" data-tab="arena">⚔️ Онлайн Арена</div>
    <div class="tab-btn" data-tab="puzzles">🧩 Задачи Lichess</div>
    <div class="tab-btn" data-tab="theory">📚 Энциклопедия</div>
</div>

<div class="main-grid">
    <div class="board-col">
        <div class="eval-bar-wrapper">
            <div class="eval-black-fill" id="evalBarUI"></div>
        </div>
        
        <div class="board-container">
            <div class="chess-clock" id="clockTopUI">
                <div class="player-info">👤 <span id="nameTopUI">Оппонент</span> <b id="eloTopUI" style="color:var(--accent-light)"></b></div>
                <div id="timeTopUI">--:--</div>
            </div>
            
            <div id="mainBoard"></div>
            
            <div class="chess-clock" id="clockBotUI">
                <div class="player-info">👑 <span id="nameBotUI">Ты</span> <b id="eloBotUI" style="color:var(--accent-light)"></b></div>
                <div id="timeBotUI">--:--</div>
            </div>
            
            <div class="btn-row">
                <div class="btn" id="btnFlip">🔄 Перевернуть</div>
                <div class="btn btn-red" id="btnReset">↩️ Сбросить</div>
            </div>
        </div>
    </div>

    <div class="panel-col">
        <div class="tab-pane" id="pane-sandbox">
            <div class="eval-box">
                <span id="tagUI" style="display:inline-block; padding:3px 8px; border-radius:3px; color:#fff; background:#555; font-size:11px; font-weight:bold; margin-bottom:6px;">ОЦЕНКА ПОЗИЦИИ</span>
                <div class="score-val" id="scoreUI">0.00</div>
                <div style="font-size:13px; margin-top:8px;">Лучший ход: <b id="bestUI" style="color:var(--accent-light)">-</b> <span id="depthUI" style="color:#666; font-size:11px;"></span></div>
            </div>
            
            <label>Глубина расчета:</label>
            <select id="depthSelect">
                <option value="auto" selected>⚡ Авто-баланс (По ядрам VPS)</option>
                <option value="12">Быстрый (Глубина 12)</option>
                <option value="16">Баланс (Глубина 16)</option>
                <option value="20">Глубокий (Глубина 20)</option>
            </select>
            
            <label style="margin-top:14px; display:block;">FEN строка:</label>
            <textarea id="fenInput" rows="2"></textarea>
            <div class="btn btn-accent" style="margin-top:8px; width:100%;" id="btnLoadFen">Загрузить FEN</div>
        </div>

        <div class="tab-pane" id="pane-arena" style="display:none;">
            <div id="arenaMenuUI">
                <h3 style="color:#fff; margin-bottom:12px; font-size:16px;">Контроль времени:</h3>
                <div class="control-grid">
                    <div class="time-card active" data-mode="bullet"><h4>Bullet 🚀</h4><p>1 мин + 0 c</p></div>
                    <div class="time-card" data-mode="blitz"><h4>Blitz ⚡</h4><p>3 мин + 2 c</p></div>
                    <div class="time-card" data-mode="rapid"><h4>Rapid ⏱️</h4><p>10 мин + 0 c</p></div>
                    <div class="time-card" data-mode="classical"><h4>Classical ⏳</h4><p>30 мин + 0 c</p></div>
                </div>
                <div class="btn btn-accent" style="padding:14px; width:100%;" id="btnJoinMM">🔎 Найти живого соперника</div>
            </div>
            
            <div id="arenaSearchingUI" style="display:none; text-align:center; padding:40px 10px;">
                <div class="spinner"></div>
                <h4 style="color:#fff;">Поиск игрока в сети...</h4>
                <p style="font-size:12px; margin-top:6px; color:#777;">Очередь матчмейкинга активна</p>
                <div class="btn btn-red" style="margin-top:20px;" id="btnCancelMM">Отменить поиск</div>
            </div>
            
            <div id="arenaPlayingUI" style="display:none;">
                <div style="background:var(--bg); padding:12px; border-radius:4px; text-align:center; font-weight:bold; color:var(--accent-light);" id="arenaStatusMsg">Игра началась!</div>
                <div class="btn btn-red" style="margin-top:15px; width:100%;" id="btnResign">Сдаться</div>
            </div>
        </div>

        <div class="tab-pane" id="pane-puzzles" style="display:none;">
            <h3 style="color:#fff; font-size:16px; margin-bottom:6px;">Тренажер Lichess Daily</h3>
            <div style="background:var(--bg); padding:12px; border-radius:4px; font-size:13px; line-height:1.4;" id="puzDescUI">Загрузка задачи...</div>
            <div id="puzStatusUI" style="font-size:20px; font-weight:bold; margin:30px 0; text-align:center; color:#fff;">-</div>
            <div class="btn btn-accent" style="width:100%;" id="btnNextPuz">Следующая задача ⏭️</div>
        </div>

        <div class="tab-pane" id="pane-theory" style="display:none;">
            <h3 style="color:#fff; font-size:16px; margin-bottom:6px;">База дебютов мира</h3>
            <div class="theory-list" id="theoryContainer"></div>
            <div style="margin-top:12px; background:var(--bg); padding:12px; border-radius:4px; font-size:13px; display:none; line-height:1.4;" id="theoryInfoBox"></div>
        </div>
    </div>
</div>

<div class="modal-overlay" id="authModal">
    <div class="modal-box">
        <div class="modal-tabs">
            <div class="btn active" id="tabLoginBtn">Вход</div>
            <div class="btn" id="tabRegBtn">Регистрация</div>
        </div>
        <label>Имя пользователя:</label>
        <input type="text" id="authUsername">
        <label style="margin-top:10px; display:block;">Пароль:</label>
        <input type="password" id="authPassword">
        <div style="color:#ff6b6b; font-size:12px; margin-top:8px; display:none;" id="authErrTxt"></div>
        <div class="btn btn-accent" style="margin-top:15px; width:100%;" id="authSubmitBtn">Продолжить</div>
        <div style="text-align:center; margin-top:12px;"><span style="font-size:12px; cursor:pointer; text-decoration:underline;" id="closeModalBtn">Закрыть окно</span></div>
    </div>
</div>

<script>
    var board = null;
    var game = new Chess();
    var socket = io();
    var CUR_MODE = 'sandbox';
    var selSq = null;
    
    // Звуковой движок Web Audio
    var audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    function snd(type) {
        if (audioCtx.state === 'suspended') audioCtx.resume();
        var osc = audioCtx.createOscillator(), g = audioCtx.createGain();
        osc.connect(g); g.connect(audioCtx.destination);
        if (type === 'cap') {
            osc.type = 'triangle'; osc.frequency.setValueAtTime(190, audioCtx.currentTime);
            osc.frequency.exponentialRampToValueAtTime(60, audioCtx.currentTime + 0.12);
            g.gain.setValueAtTime(0.35, audioCtx.currentTime); g.gain.linearRampToValueAtTime(0.01, audioCtx.currentTime + 0.12);
            osc.start(); osc.stop(audioCtx.currentTime + 0.12);
        } else {
            osc.type = 'sine'; osc.frequency.setValueAtTime(310, audioCtx.currentTime);
            osc.frequency.exponentialRampToValueAtTime(230, audioCtx.currentTime + 0.08);
            g.gain.setValueAtTime(0.18, audioCtx.currentTime); g.gain.linearRampToValueAtTime(0.01, audioCtx.currentTime + 0.08);
            osc.start(); osc.stop(audioCtx.currentTime + 0.08);
        }
    }

    var ME = null;
    var curRoom = null;
    var mySide = 'w';
    var curPuz = null;
    var puzStep = 0;
    var authAction = 'login';

    $(document).ready(function() {
        board = ChessBoard('mainBoard', {
            draggable: true, position: 'start',
            pieceTheme: 'https://lichess1.org/assets/piece/cburnett/{piece}.svg',
            onDragStart: onDragStart, onDrop: onDrop, onSnapEnd: onSnapEnd
        });

        checkAuth();
        loadTheory();

        $('.tab-btn').on('click', function() {
            var m = $(this).data('tab');
            $('.tab-btn').removeClass('active'); $(this).addClass('active');
            $('.tab-pane').hide(); $('#pane-' + m).show();
            initMode(m);
        });

        $('#btnFlip').on('click', function() { board.orientation(board.orientation()==='white' ? 'black' : 'white'); });
        $('#btnReset').on('click', function() { initMode(CUR_MODE); });
        $('#btnLoadFen').on('click', manualFen);
        $('#btnNextPuz').on('click', fetchPuzzle);
        $('.time-card').on('click', function() { $('.time-card').removeClass('active'); $(this).addClass('active'); });

        $('#mainBoard').on('click', '.square-55d63', function() { sqClick($(this).attr('data-square')); });

        // Авторизация UI
        $('#tabLoginBtn').on('click', function() { authAction='login'; $('#tabLoginBtn').addClass('active'); $('#tabRegBtn').removeClass('active'); });
        $('#tabRegBtn').on('click', function() { authAction='register'; $('#tabRegBtn').addClass('active'); $('#tabLoginBtn').removeClass('active'); });
        $('#closeModalBtn').on('click', function() { $('#authModal').fadeOut(100); });
        $('#authSubmitBtn').on('click', submitAuth);

        // Мультиплеер кнопки
        $('#btnJoinMM').on('click', function() {
            if (!ME) { $('#authModal').fadeIn(100); return; }
            var mode = $('.time-card.active').data('mode');
            socket.emit('join_queue', {mode: mode});
            $('#arenaMenuUI').hide(); $('#arenaSearchingUI').fadeIn(150);
        });
        $('#btnCancelMM').on('click', function() {
            socket.emit('leave_queue');
            $('#arenaSearchingUI').hide(); $('#arenaMenuUI').fadeIn(150);
        });
        $('#btnResign').on('click', function() { socket.emit('resign', {room: curRoom}); });

        initMode('sandbox');
    });

    // --- ЛОГИКА СОКЕТОВ МУЛЬТИПЛЕЕРА ---

    socket.on('match_start', function(data) {
        curRoom = data.room;
        mySide = data.color;
        game.reset(); board.position('start'); board.orientation(mySide==='w' ? 'white' : 'black');
        
        $('#arenaSearchingUI').hide(); $('#arenaPlayingUI').fadeIn(150);
        $('#nameTopUI').text(data.opp_name); $('#eloTopUI').text('(' + data.opp_elo + ')');
        $('#nameBotUI').text(ME.username); $('#eloBotUI').text('(' + ME['elo_' + data.mode] + ')');
        
        $('#timeTopUI').text(fmt(data.time)); $('#timeBotUI').text(fmt(data.time));
        $('#arenaStatusMsg').text('Игра началась! Ход белых').css('color', '#fff');
    });

    socket.on('board_sync', function(data) {
        var cap = game.get(data.last_move.substring(2,4));
        game.move(data.last_move, {sloppy: true});
        board.position(game.fen());
        snd(cap ? 'cap' : 'move');

        $('#timeTopUI').text(fmt(mySide==='w' ? data.time_b : data.time_w));
        $('#timeBotUI').text(fmt(mySide==='w' ? data.time_w : data.time_b));

        $('.chess-clock').removeClass('clock-active');
        if (data.turn === mySide) $('#clockBotUI').addClass('clock-active');
        else $('#clockTopUI').addClass('clock-active');

        if (data.is_over) {
            $('.chess-clock').removeClass('clock-active');
            var txt = data.reason + ". ";
            if (data.winner === 'draw') txt += "Ничья!";
            else if (data.winner === mySide) txt += "Твоя ПОБЕДА! 🏆";
            else txt += "Ты проиграл ☠️";
            $('#arenaStatusMsg').text(txt).css('color', data.winner===mySide ? 'var(--accent-light)' : '#ff6b6b');
            checkAuth(); // обновить ЭЛО в шапке
        }
    });

    // --- ПРАВИЛА ХОДОВ ---

    function sqClick(sq) {
        if (game.game_over()) return;
        if (CUR_MODE === 'arena' && game.turn() !== mySide) return;

        if (selSq && ($('.square-' + sq).hasClass('hint-dot') || $('.square-' + sq).hasClass('hint-capture'))) {
            makeTurn({from: selSq, to: sq, promotion: 'q'});
            clrHints(); return;
        }
        var p = game.get(sq);
        if (!p || p.color !== game.turn()) { clrHints(); return; }
        clrHints(); selSq = sq;
        game.moves({square: sq, verbose: true}).forEach(function(m) {
            var el = $('.square-' + m.to);
            if (game.get(m.to)) el.addClass('hint-capture'); else el.addClass('hint-dot');
        });
    }

    function clrHints() { selSq = null; $('#mainBoard .square-55d63').removeClass('hint-dot hint-capture'); }
    function onDragStart(s, p) {
        if (game.game_over()) return false;
        if (CUR_MODE === 'arena' && game.turn() !== mySide) return false;
        if ((game.turn()==='w' && p.search(/^b/)!==-1) || (game.turn()==='b' && p.search(/^w/)!==-1)) return false;
        clrHints();
    }
    function onDrop(s, t) { var r = makeTurn({from: s, to: t, promotion: 'q'}); if (r === null) return 'snapback'; }
    function onSnapEnd() { board.position(game.fen()); }

    function makeTurn(mObj) {
        var prior = game.fen(), cap = game.get(mObj.to);
        var m = game.move(mObj);
        if (!m) return null;

        board.position(game.fen());
        $('#fenInput').val(game.fen());
        snd(cap ? 'cap' : 'move');

        if (CUR_MODE === 'sandbox') grade(prior, game.fen());
        else if (CUR_MODE === 'arena') socket.emit('send_move', {room: curRoom, move: m.from + m.to + (m.promotion||'')});
        else if (CUR_MODE === 'puzzles') verPuz(m.from + m.to);
        return m;
    }

    function initMode(mode) {
        CUR_MODE = mode;
        if (curRoom) socket.emit('resign', {room: curRoom}); curRoom = null;
        game.reset(); board.start(); board.orientation('white'); clrHints();
        setEval(0);
        $('#clockTopUI, #clockBotUI').removeClass('clock-active');
        $('#timeTopUI, #timeBotUI').text('--:--');
        $('#nameTopUI').text('Оппонент'); $('#nameBotUI').text(ME ? ME.username : 'Ты');
        $('#eloTopUI, #eloBotUI').text('');

        if (mode === 'sandbox') { $('#fenInput').val(game.fen()); grade(game.fen(), game.fen()); }
        if (mode === 'arena') { $('#arenaSearchingUI, #arenaPlayingUI').hide(); $('#arenaMenuUI').show(); }
        if (mode === 'puzzles') fetchPuzzle();
    }

    function setEval(s) {
        var p = Math.min(Math.max(50 - (s * 5), 3), 97);
        $('#evalBarUI').css('height', p + '%');
    }

    // --- РЕЖИМ 1: АНАЛИЗ ---

    function grade(b, a) {
        $('#tagUI').text('...').css('background', '#555');
        $.post('/grade_move', {before: b, after: a, depth: $('#depthSelect').val()}, function(d) {
            $('#tagUI').text(d.tag).css('background', d.color);
            $('#scoreUI').text(d.eval); $('#bestUI').text(d.best); $('#depthUI').text('(гл. ' + d.depth + ')');
            var f = parseFloat(d.eval); if (!isNaN(f)) setEval(f);
        });
    }

    function manualFen() {
        var v = $('#fenInput').val().trim();
        if (game.load(v)) { board.position(v); grade(v, v); } else alert('Некорректный FEN');
    }

    // --- РЕЖИМ 3: ЗАДАЧИ ---

    function fetchPuzzle() {
        $('#puzDescUI').text('Запросили сервер Lichess...');
        $.get('/api/puzzle/lichess', function(d) {
            curPuz = d; puzStep = 0;
            game.load(curPuz.fen); board.position(game.fen());
            $('#puzDescUI').text('Задача #' + curPuz.id + ' (Рейтинг ' + curPuz.rating + '): Найди выигрывающую комбинацию!');
            $('#puzStatusUI').text('Твой ход').css('color', '#fff');
        });
    }

    function verPuz(u) {
        if (u === curPuz.solution[puzStep]) {
            puzStep++;
            if (puzStep >= curPuz.solution.length) {
                $('#puzStatusUI').text('🟢 РЕШЕНО БЕЗ ОШИБОК!').css('color', 'var(--accent-light)');
            } else {
                setTimeout(function() {
                    var em = curPuz.solution[puzStep], cap = game.get(em.substring(2,4));
                    game.move(em, {sloppy: true}); board.position(game.fen()); snd(cap ? 'cap' : 'move');
                    puzStep++;
                    $('#puzStatusUI').text('Продолжай комбинацию...').css('color', '#f0d9b5');
                }, 350);
            }
        } else {
            $('#puzStatusUI').text('🔴 ОШИБКА КОМБИНАЦИИ!').css('color', '#ff6b6b');
        }
    }

    // --- РЕЖИМ 4: ТЕОРИЯ ---

    function loadTheory() {
        $.get('/get_theory', function(d) {
            var c = $('#theoryContainer'); c.empty();
            Object.keys(d).forEach(function(k) {
                var it = $('<div class="theory-item"><span><b>' + d[k].eco + '</b>: ' + d[k].name + '</span> <span style="color:var(--accent-light)">➔</span></div>');
                it.on('click', function() {
                    CUR_MODE = 'sandbox'; $('.tab-btn').removeClass('active'); $('[data-tab="sandbox"]').addClass('active');
                    $('.tab-pane').hide(); $('#pane-sandbox').show();
                    game.load(d[k].fen); board.position(d[k].fen); $('#fenInput').val(d[k].fen);
                    $('#theoryInfoBox').text(d[k].desc).show();
                    grade(d[k].fen, d[k].fen);
                });
                c.append(it);
            });
        });
    }

    // --- АВТОРИЗАЦИЯ ВСЕГО ПРИЛОЖЕНИЯ ---

    function checkAuth() {
        $.get('/api/auth/me', function(res) {
            ME = res.logged ? res.user : null;
            var box = $('#authNavbarUI'); box.empty();
            if (ME) {
                box.append('<span>👤 <b>' + ME.username + '</b> (⚡ ' + ME.elo_blitz + ')</span>');
                var out = $('<div class="btn btn-red" style="padding:5px 10px;">Выход</div>');
                out.on('click', function() { $.post('/api/auth/logout', function() { checkAuth(); }); });
                box.append(out);
            } else {
                var lg = $('<div class="btn btn-accent" style="padding:6px 12px;">Войти / Создать</div>');
                lg.on('click', function() { $('#authModal').fadeIn(100); });
                box.append(lg);
            }
        });
    }

    function submitAuth() {
        var u = $('#authUsername').val().trim(), p = $('#authPassword').val().trim();
        if(!u || !p) { $('#authErrTxt').text('Заполни поля').show(); return; }
        $.post('/api/auth/' + authAction, {username: u, password: p}, function(res) {
            if (res.success) { $('#authModal').fadeOut(100); $('#authErrTxt').hide(); checkAuth(); }
            else { $('#authErrTxt').text(res.error).show(); }
        });
    }

    function fmt(sec) { var m = Math.floor(sec/60), s = Math.floor(sec%60); return (m<10?'0':'')+m+':'+(s<10?'0':'')+s; }
</script>

</body>
</html>
"""

# --- МАРШРУТЫ ФЛАСК БЭКЕНДА ---

@app.route('/')
def index():
    return HTML_TEMPLATE

@app.route('/api/auth/me')
def get_me():
    if current_user.is_authenticated:
        return jsonify({"logged": True, "user": {
            "id": current_user.id, "username": current_user.username,
            "elo_bullet": current_user.elo_bullet, "elo_blitz": current_user.elo_blitz,
            "elo_rapid": current_user.elo_rapid, "elo_classical": current_user.elo_classical
        }})
    return jsonify({"logged": False})

@app.route('/api/auth/register', methods=['POST'])
def register():
    u = request.form.get('username', '').strip()
    p = request.form.get('password', '').strip()
    if len(u) < 3: return jsonify({"success": False, "error": "Имя слишком короткое"})
    if User.query.filter_by(username=u).first(): return jsonify({"success": False, "error": "Ник занят"})
    new_u = User(username=u, password_hash=generate_password_hash(p))
    db.session.add(new_u); db.session.commit()
    login_user(new_u)
    return jsonify({"success": True})

@app.route('/api/auth/login', methods=['POST'])
def login():
    u = request.form.get('username', '').strip()
    p = request.form.get('password', '').strip()
    usr = User.query.filter_by(username=u).first()
    if usr and check_password_hash(usr.password_hash, p):
        login_user(usr)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Неверный логин или пароль"})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    logout_user()
    return jsonify({"success": True})

@app.route('/grade_move', methods=['POST'])
def grade_move():
    b_str = request.form.get('before')
    a_str = request.form.get('after')
    depth = get_optimal_depth(request.form.get('depth', 'auto'))
    try:
        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as eng:
            eng.configure(ENGINE_OPTIONS)
            b1 = chess.Board(b_str)
            r1 = eng.analyse(b1, chess.engine.Limit(depth=depth))
            best = r1["pv"][0].uci() if "pv" in r1 else "-"
            s1 = r1["score"].white().score(mate_score=10000)
            
            b2 = chess.Board(a_str)
            r2 = eng.analyse(b2, chess.engine.Limit(depth=depth))
            s2 = r2["score"].white().score(mate_score=10000)
            
            mul = 1 if b1.turn == chess.WHITE else -1
            delta = (s2 - s1) * mul if s1 is not None and s2 is not None else 0
            
            if delta >= 160: tag, col = "Бриллиантовый 💎", "#1baca6"
            elif delta >= -15: tag, col = "Лучший ход ⭐", "#81b64c"
            elif delta >= -45: tag, col = "Отличный 🟢", "#629924"
            elif delta >= -95: tag, col = "Хороший 🔵", "#5c8bb5"
            elif delta >= -190: tag, col = "Неточность 🟡", "#e6a817"
            elif delta >= -360: tag, col = "Ошибка 🟠", "#ca5216"
            else: tag, col = "Зевок 🔴", "#ca3431"
            
            ev_txt = f"{s2/100:+.2f}" if abs(s2) != 10000 else "МАТ"
            return jsonify({"tag": tag, "color": col, "eval": ev_txt, "best": best, "depth": depth})
    except Exception:
        return jsonify({"tag": "Позиция", "color": "#555", "eval": "0.00", "best": "-", "depth": depth})

@app.route('/api/puzzle/lichess')
def lichess_puz():
    try:
        r = requests.get("https://lichess.org/api/puzzle/daily", headers={"User-Agent": "SnezkaChess/2.0"}, timeout=4)
        if r.status_code == 200:
            data = r.json()
            game_obj = chess.pgn.read_game(io.StringIO(data['game']['pgn']))
            board = game_obj.end().board()
            return jsonify({"id": data['puzzle']['id'], "rating": data['puzzle']['rating'], "fen": board.fen(), "solution": data['puzzle']['solution']})
    except Exception:
        pass
    return jsonify(random.choice(FALLBACK_PUZZLES))

@app.route('/get_theory')
def get_theory():
    return jsonify(OPENINGS_DB)

# --- СОКЕТЫ: ДИСПЕТЧЕР ОЧЕРЕДЕЙ И ТАЙМЕРОВ ---

@socketio.on('join_queue')
def join_mm(data):
    if not current_user.is_authenticated: return
    mode = data.get('mode', 'blitz')
    sid = request.sid
    USER_SID_MAP[current_user.id] = sid
    
    # Удаляем из других очередей
    for q in MATCHMAKING_QUEUES.values():
        q[:] = [x for x in q if x['id'] != current_user.id]
        
    MATCHMAKING_QUEUES[mode].append({
        "sid": sid, "id": current_user.id, "username": current_user.username,
        "elo": getattr(current_user, f'elo_{mode}', 1500)
    })
    
    if len(MATCHMAKING_QUEUES[mode]) >= 2:
        p1 = MATCHMAKING_QUEUES[mode].pop(0)
        p2 = MATCHMAKING_QUEUES[mode].pop(0)
        
        room_id = str(uuid.uuid4())
        times = {"bullet": 60, "blitz": 180, "rapid": 600, "classical": 1800}
        incs = {"bullet": 0, "blitz": 2, "rapid": 0, "classical": 0}
        
        ACTIVE_ROOMS[room_id] = {
            "board": chess.Board(), "w": p1, "b": p2, "mode": mode,
            "time_w": float(times[mode]), "time_b": float(times[mode]), "inc": float(incs[mode]),
            "last_ts": time.time()
        }
        
        join_room(room_id, sid=p1['sid'])
        join_room(room_id, sid=p2['sid'])
        
        emit('match_start', {"room": room_id, "color": "w", "time": times[mode], "mode": mode, "opp_name": p2['username'], "opp_elo": p2['elo']}, to=p1['sid'])
        emit('match_start', {"room": room_id, "color": "b", "time": times[mode], "mode": mode, "opp_name": p1['username'], "opp_elo": p1['elo']}, to=p2['sid'])

@socketio.on('leave_queue')
def leave_mm():
    if not current_user.is_authenticated: return
    for q in MATCHMAKING_QUEUES.values():
        q[:] = [x for x in q if x['id'] != current_user.id]

@socketio.on('send_move')
def handle_move(data):
    room_id = data.get('room')
    move_uci = data.get('move')
    if room_id not in ACTIVE_ROOMS: return
    rm = ACTIVE_ROOMS[room_id]
    
    board = rm['board']
    active_side_char = 'w' if board.turn == chess.WHITE else 'b'
    if rm[active_side_char]['sid'] != request.sid: return # Чужой ход
    
    try:
        m = chess.Move.from_uci(move_uci)
        if m in board.legal_moves:
            now = time.time()
            elapsed = now - rm['last_ts']
            rm[f'time_{active_side_char}'] -= elapsed
            rm[f'time_{active_side_char}'] += rm['inc']
            rm['last_ts'] = now
            
            board.push(m)
            
            is_over, winner, reason = False, None, ""
            if board.is_checkmate():
                is_over = True; winner = active_side_char; reason = "Мат"
            elif board.is_stalemate() or board.is_insufficient_material() or board.is_fifty_moves():
                is_over = True; winner = "draw"; reason = "Ничья"
            elif rm['time_w'] <= 0:
                is_over = True; winner = 'b'; reason = "У белых вышло время"
            elif rm['time_b'] <= 0:
                is_over = True; winner = 'w'; reason = "У черных вышло время"
                
            emit('board_sync', {
                "last_move": move_uci, "turn": 'w' if board.turn == chess.WHITE else 'b',
                "time_w": rm['time_w'], "time_b": rm['time_b'],
                "is_over": is_over, "winner": winner, "reason": reason
            }, to=room_id)
            
            if is_over:
                # Перерасчет рейтинга в SQL
                u_w = User.query.get(rm['w']['id'])
                u_b = User.query.get(rm['b']['id'])
                if u_w and u_b and winner != "draw":
                    k = 32
                    attr = f"elo_{rm['mode']}"
                    ew = 1 / (1 + 10 ** ((getattr(u_b, attr) - getattr(u_w, attr)) / 400))
                    sw = 1 if winner == 'w' else 0
                    setattr(u_w, attr, int(getattr(u_w, attr) + k * (sw - ew)))
                    setattr(u_b, attr, int(getattr(u_b, attr) + k * ((1 - sw) - (1 - ew))))
                    db.session.commit()
                del ACTIVE_ROOMS[room_id]
    except Exception:
        pass

@socketio.on('resign')
def resign_game(data):
    room_id = data.get('room')
    if room_id in ACTIVE_ROOMS:
        rm = ACTIVE_ROOMS[room_id]
        loser = 'w' if rm['w']['sid'] == request.sid else 'b'
        winner = 'b' if loser == 'w' else 'w'
        emit('board_sync', {"last_move": "0000", "turn": "-", "time_w": 0, "time_b": 0, "is_over": True, "winner": winner, "reason": "Соперник сдался"}, to=room_id)
        del ACTIVE_ROOMS[room_id]

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
 if (game.game_over()) return;
        if (CURRENT_MODE === 'arena' && game.turn() === 'b') return; // Ход симулированного соперника

        if (selectedSquare && ($('.square-' + sq).hasClass('hint-dot') || $('.square-' + sq).hasClass('hint-capture'))) {
            executeMove({from: selectedSquare, to: sq, promotion: 'q'});
            clearHighlights();
            return;
        }

        var piece = game.get(sq);
        if (!piece || piece.color !== game.turn()) {
            clearHighlights();
            return;
        }

        clearHighlights();
        selectedSquare = sq;
        game.moves({square: sq, verbose: true}).forEach(function(m) {
            var cell = $('.square-' + m.to);
            if (game.get(m.to)) cell.addClass('hint-capture');
            else cell.addClass('hint-dot');
        });
    }

    function clearHighlights() {
        selectedSquare = null;
        $('#mainBoard .square-55d63').removeClass('hint-dot hint-capture');
    }

    function onDragStart(src, piece) {
        if (game.game_over()) return false;
        if (CURRENT_MODE === 'arena' && game.turn() === 'b') return false;
        if ((game.turn() === 'w' && piece.search(/^b/) !== -1) ||
            (game.turn() === 'b' && piece.search(/^w/) !== -1)) return false;
        clearHighlights();
    }

    function onDrop(src, tgt) {
        var m = executeMove({from: src, to: tgt, promotion: 'q'});
        if (m === null) return 'snapback';
    }

    function onSnapEnd() { board.position(game.fen()); }

    // Главный исполнитель ходов
    function executeMove(moveObj) {
        var priorFen = game.fen();
        var captured = game.get(moveObj.to);
        var move = game.move(moveObj);
        if (!move) return null;

        board.position(game.fen());
        $('#fenInput').val(game.fen());
        playSound(captured ? 'capture' : 'move');

        if (CURRENT_MODE === 'sandbox') {
            triggerEngineAnalysis(priorFen, game.fen());
        } else if (CURRENT_MODE === 'arena') {
            timers[move.color] += timers.inc; // Добавление времени за ход
            if (game.game_over()) {
                handleMatchEnd('win');
            } else {
                toggleClockTimer();
                setTimeout(triggerArenaBotResponse, 300);
            }
        } else if (CURRENT_MODE === 'puzzles') {
            checkPuzzleMove(move.from + move.to);
        }
        return move;
    }

    // Логика эвал бара Lichess
    function setEvalBar(score) {
        var percent = 50 - (score * 5); 
        percent = Math.min(Math.max(percent, 3), 97);
        $('#evalBar').css('height', percent + '%');
    }

    // ТАБ 1: ДВИЖОК / АНАЛИЗ
    function triggerEngineAnalysis(f1, f2) {
        $('#moveBadgeUI').text('Расчет...').css('background', '#444');
        $.post('/grade_move', {before: f1, after: f2, depth: $('#depthSelect').val()}, function(data) {
            $('#moveBadgeUI').text(data.tag).css('background', data.color);
            $('#scoreUI').text(data.eval);
            $('#bestMoveUI').text(data.best);
            $('#depthUI').text('(гл. ' + data.depth + ')');
            
            var parsedScore = parseFloat(data.eval);
            if (!isNaN(parsedScore)) setEvalBar(parsedScore);
        });
    }

    function loadManualFen() {
        var val = $('#fenInput').val().trim();
        if (game.load(val)) {
            board.position(val);
            triggerEngineAnalysis(val, val);
        } else {
            alert('Ошибка: неверный формат строки FEN');
        }
    }

    // ТАБ 2: ОНЛАЙН АРЕНА (Матчмейкинг и Часы)
    function startMatchmaking() {
        $('#arenaSetup').hide();
        $('#arenaLobby').show();
        var activeCard = $('.time-card.active');
        
        timers.w = parseInt(activeCard.data('time'));
        timers.b = timers.w;
        timers.inc = parseInt(activeCard.data('inc'));

        setTimeout(function() {
            // Имитация успешного поиска по базе данных ELO
            $('#arenaLobby').hide();
            $('#arenaActive').show();
            
            var generatedDiff = Math.floor(Math.random() * 60) - 30;
            arenaOpponent = {
                name: BOT_NAMES[Math.floor(Math.random() * BOT_NAMES.length)],
                elo: myElo + generatedDiff
            };
            
            $('#nameTop').text(arenaOpponent.name);
            $('#eloTop').text('(' + arenaOpponent.elo + ')');
            
            $('#timeTop').text(formatTime(timers.b));
            $('#timeBottom').text(formatTime(timers.w));
            
            $('#clockBottom').addClass('clock-active');
            startClockTicker();
        }, 1800);
    }

    function startClockTicker() {
        clearInterval(clockInterval);
        clockInterval = setInterval(function() {
            var activeSide = game.turn();
            timers[activeSide]--;
            
            $('#timeTop').text(formatTime(timers.b));
            $('#timeBottom').text(formatTime(timers.w));

            if (timers[activeSide] <= 0) {
                clearInterval(clockInterval);
                handleMatchEnd(activeSide === 'w' ? 'lose_time' : 'win_time');
            }
        }, 1000);
    }

    function toggleClockTimer() {
        $('.chess-clock').removeClass('clock-active');
        if (game.turn() === 'w') $('#clockBottom').addClass('clock-active');
        else $('#clockTop').addClass('clock-active');
    }

    function triggerArenaBotResponse() {
        if (game.game_over() || CURRENT_MODE !== 'arena') return;
        
        var calculatedSkill = Math.min(20, Math.max(1, Math.floor(arenaOpponent.elo / 100)));
        
        $.post('/bot_turn', {fen: game.fen(), skill: calculatedSkill}, function(res) {
            if (CURRENT_MODE !== 'arena') return;
            var captured = game.get(res.move.substring(2,4));
            game.move(res.move, {sloppy: true});
            board.position(game.fen());
            playSound(captured ? 'capture' : 'move');
            
            timers.b += timers.inc;
            toggleClockTimer();
            
            if (game.game_over()) {
                handleMatchEnd('lose');
            }
        });
    }

    function handleMatchEnd(outcome) {
        clearInterval(clockInterval);
        var eloChange = 0;
        var msg = "";
        
        if (outcome === 'win') { eloChange = 16; msg = "🏆 Победа матом! +16 ELO"; }
        else if (outcome === 'win_time') { eloChange = 12; msg = "⏳ Соперник просрочил время! +12 ELO"; }
        else if (outcome === 'lose') { eloChange = -14; msg = "☠️ Ты получил мат. -14 ELO"; }
        else if (outcome === 'lose_time') { eloChange = -16; msg = "⏰ Время истекло! -16 ELO"; }

        myElo += eloChange;
        localStorage.setItem('snezka_elo_v1', myElo);
        $('#playerEloUI').text(myElo);
        $('#arenaGameMsg').text(msg).css('color', eloChange > 0 ? 'var(--accent-light)' : '#ff6b6b');
    }

    function formatTime(sec) {
        var m = Math.floor(sec / 60);
        var s = sec % 60;
        return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
    }

    // ТАБ 3: ЗАДАЧИ
    function getNewPuzzle() {
        $.get('/get_puzzle?elo=' + myElo, function(data) {
            activePuzzle = data;
            puzzleProgress = 0;
            game.load(activePuzzle.fen);
            board.position(game.fen());
            $('#puzTaskDesc').text('Задача #' + activePuzzle.id + ' (Рейтинг ' + activePuzzle.elo + '): ' + activePuzzle.desc);
            $('#puzStatus').text('Твой ход').css('color', '#fff');
        });
    }

    function checkPuzzleMove(uciMove) {
        if (uciMove === activePuzzle.moves[puzzleProgress]) {
            puzzleProgress++;
            if (puzzleProgress >= activePuzzle.moves.length) {
                myElo += 15;
                localStorage.setItem('snezka_elo_v1', myElo);
                $('#playerEloUI').text(myElo);
                $('#puzStatus').text('🟢 РЕШЕНО! +15 ELO').css('color', 'var(--accent-light)');
            } else {
                // Ход за противника по условию задачи
                setTimeout(function() {
                    var enemyMove = activePuzzle.moves[puzzleProgress];
                    var captured = game.get(enemyMove.substring(2,4));
                    game.move(enemyMove, {sloppy: true});
                    board.position(game.fen());
                    playSound(captured ? 'capture' : 'move');
                    puzzleProgress++;
                    $('#puzStatus').text('Продолжай серию ходов...').css('color', '#f0d9b5');
                }, 400);
            }
        } else {
            myElo = Math.max(500, myElo - 11);
            localStorage.setItem('snezka_elo_v1', myElo);
            $('#playerEloUI').text(myElo);
            $('#puzStatus').text('🔴 Неверный ход! -11 ELO').css('color', '#ff6b6b');
        }
    }

    // ТАБ 4: ТЕОРИЯ ДЕБЮТОВ
    function initTheoryTab() {
        $.get('/get_theory', function(data) {
            var container = $('#theoryListContainer');
            container.empty();
            Object.keys(data).forEach(function(key) {
                var item = $('<div class="theory-item"><b>' + data[key].name + '</b></div>');
                item.on('click', function() {
                    CURRENT_MODE = 'sandbox'; // переводим в песочницу для анализа
                    game.load(data[key].fen);
                    board.position(data[key].fen);
                    $('#fenInput').val(data[key].fen);
                    $('#theoryDescBox').text(data[key].desc).fadeIn(150);
                    triggerEngineAnalysis(data[key].fen, data[key].fen);
                });
                container.append(item);
            });
        });
    }
</script>

</body>
</html>
"""

@app.route('/')
def index():
    return HTML_TEMPLATE

@app.route('/grade_move', methods=['POST'])
def grade_move():
    f_before = request.form.get('before')
    f_after = request.form.get('after')
    req_depth = request.form.get('depth', 'auto')
    
    calc_depth = get_optimal_depth(req_depth)

    try:
        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as eng:
            eng.configure(ENGINE_OPTIONS)
            
            b1 = chess.Board(f_before)
            res1 = eng.analyse(b1, chess.engine.Limit(depth=calc_depth))
            best_m = res1["pv"][0].uci() if "pv" in res1 else "-"
            s1 = res1["score"].white().score(mate_score=10000)
            
            b2 = chess.Board(f_after)
            res2 = eng.analyse(b2, chess.engine.Limit(depth=calc_depth))
            s2 = res2["score"].white().score(mate_score=10000)
            
            turn_multiplier = 1 if b1.turn == chess.WHITE else -1
            delta = (s2 - s1) * turn_multiplier if s1 is not None and s2 is not None else 0
            
            if delta >= 150: tag, col = "Бриллиантовый ход 💎", "#1baca6"
            elif delta >= -15: tag, col = "Лучший ход ⭐", "#81b64c"
            elif delta >= -40: tag, col = "Отличный ход 🟢", "#629924"
            elif delta >= -90: tag, col = "Хороший ход 🔵", "#5c8bb5"
            elif delta >= -180: tag, col = "Неточность 🟡", "#e6a817"
            elif delta >= -350: tag, col = "Ошибка 🟠", "#ca5216"
            else: tag, col = "Зевок 🔴", "#ca3431"
            
            ev_str = f"{s2/100:+.2f}" if abs(s2) != 10000 else "МАТ"
            return jsonify({"tag": tag, "color": col, "eval": ev_str, "best": best_m, "depth": calc_depth})
    except Exception:
        return jsonify({"tag": "Анализ", "color": "#444", "eval": "0.00", "best": "-", "depth": calc_depth})

@app.route('/bot_turn', methods=['POST'])
def bot_turn():
    fen = request.form.get('fen')
    skill = int(request.form.get('skill', 10))
    board = chess.Board(fen)
    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as eng:
        eng.configure({"Skill Level": skill})
        res = eng.play(board, chess.engine.Limit(time=0.15))
        return jsonify({"move": res.move.uci()})

@app.route('/get_puzzle')
def get_puzzle():
    elo = int(request.args.get('elo', 1500))
    puz = min(PUZZLES_DB, key=lambda x: abs(x['elo'] - elo))
    return jsonify(puz)

@app.route('/get_theory')
def get_theory():
    return jsonify(THEORY_DB)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
