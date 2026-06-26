import os
import io
import json
import random
from flask import Flask, request, jsonify
import chess
import chess.engine

app = Flask(__name__)
STOCKFISH_PATH = "/usr/games/stockfish"

ENGINE_OPTIONS = {"Threads": 1, "Hash": 16}

PUZZLES_DB = [
    {"id": 1, "elo": 850, "fen": "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4", "moves": ["h5f7"], "desc": "Мат в 1 ход"},
    {"id": 2, "elo": 1100, "fen": "r1b1k2r/ppppnppp/2n2q2/2b5/3NP3/2P1B3/PP3PPP/RN1QKB1R w KQkq - 3 7", "moves": ["d4c6", "c5e3", "c6d8"], "desc": "Вскрытый удар"},
    {"id": 3, "elo": 1400, "fen": "2r3k1/p4ppp/1p2p3/3b4/3P4/q3PN2/1Q3PPP/2R3K1 b - - 1 22", "moves": ["c8c1", "b2c1", "a3c1"], "desc": "Слабость 1-й горизонтали"},
    {"id": 4, "elo": 1650, "fen": "r2q1rk1/ppp2ppp/2n1bn2/8/1b1P4/2N1BN2/PPP1BPPP/R2Q1RK1 w - - 8 10", "moves": ["a2a3", "b4c3", "b2c3"], "desc": "Выигрыш темпа"},
    {"id": 5, "elo": 1900, "fen": "5rk1/pp3ppp/4p3/1b1pP3/1q1P4/1Pr1PN2/P2Q2PP/2R1R1K1 b - - 4 19", "moves": ["f8c8", "c1c3", "b4c3"], "desc": "Борьба за вертикаль"},
    {"id": 6, "elo": 2200, "fen": "r2q1rk1/1pp1nppp/p2bp3/8/3PN3/3Q1N2/PPP2PPP/4RRK1 w - - 4 13", "moves": ["e4f6", "g7f6", "d3h7"], "desc": "Жертва разрушения"}
]

def get_optimal_depth(req_depth):
    if req_depth != "auto":
        return min(max(int(req_depth), 8), 22)
    try:
        load1, _, _ = os.getloadavg()
        cores = os.cpu_count() or 1
        ratio = load1 / cores
        if ratio > 0.85: return 11    # Сервер сильно перегружен
        elif ratio > 0.50: return 14  # Средняя нагрузка
        elif ratio > 0.25: return 16  # Комфортная работа
        else: return 18               # Сервер абсолютно свободен
    except Exception:
        return 14  # Фоллбэк

# Используем raw-строку r"..." для защиты JavaScript от Python-парсера
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>SnezkaChess | Lichess Interface</title>
    
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/chessboard-js/1.0.0/chessboard-1.0.0.min.css">
    <script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/chessboard-js/1.0.0/chessboard-1.0.0.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/chess.js/0.10.3/chess.min.js"></script>
    
    <style>
        :root {
            --bg: #161512; --surface: #262421; --surface-hover: #363431;
            --accent: #629924; --accent-light: #81b64c;
            --text: #bababa; --text-bright: #ffffff; --border: #403d39;
            --board-light: #f0d9b5; --board-dark: #b58863;
        }
        
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 15px; }
        
        .header { text-align: center; margin-bottom: 15px; }
        .header h1 { margin: 0; color: var(--text-bright); font-size: 20px; letter-spacing: 1px; }
        
        /* Табы Lichess */
        .tabs { display: flex; gap: 4px; max-width: 960px; margin: 0 auto 15px auto; background: var(--surface); padding: 4px; border-radius: 6px; border: 1px solid var(--border); }
        .tab-btn { flex: 1; padding: 10px; text-align: center; cursor: pointer; border-radius: 4px; font-weight: 600; font-size: 13px; color: var(--text); transition: 0.15s; }
        .tab-btn:hover { color: var(--text-bright); }
        .tab-btn.active { background: var(--accent-light); color: #fff; }
        
        .grid { display: flex; gap: 20px; max-width: 960px; margin: 0 auto; align-items: flex-start; }
        .board-col { flex: 0 0 450px; width: 100%; max-width: 450px; }
        .panel-col { flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 20px; min-height: 450px; display: flex; flex-direction: column; }
        
        /* Оформление доски */
        .white-1e1d7 { background-color: var(--board-light); }
        .black-3c85d { background-color: var(--board-dark); }
        .board-b72b1 { border: none !important; border-radius: 4px; box-shadow: 0 8px 25px rgba(0,0,0,0.6); }
        
        /* Точки для клик-ходов (Lichess Style) */
        .hint-dot { position: relative; }
        .hint-dot::after { content: ''; position: absolute; width: 30%; height: 30%; background: rgba(20, 85, 30, 0.45); border-radius: 50%; top: 35%; left: 35%; pointer-events: none; }
        .hint-capture { position: relative; }
        .hint-capture::after { content: ''; position: absolute; width: 84%; height: 84%; border: 6px solid rgba(20, 85, 30, 0.45); border-radius: 50%; top: 8%; left: 8%; pointer-events: none; }
        
        /* Виджет оценки */
        .eval-box { background: var(--bg); border-radius: 4px; padding: 15px; border-left: 4px solid var(--accent-light); margin-bottom: 15px; }
        .move-badge { display: inline-block; padding: 3px 8px; border-radius: 3px; font-weight: bold; font-size: 11px; text-transform: uppercase; color: #fff; margin-bottom: 6px; }
        .score-val { font-size: 34px; font-weight: bold; color: var(--text-bright); font-family: monospace; }
        
        .btn-row { display: flex; gap: 8px; margin-top: 12px; }
        .btn { background: var(--surface-hover); color: var(--text-bright); border: 1px solid var(--border); padding: 11px; border-radius: 4px; font-weight: 600; font-size: 13px; cursor: pointer; text-align: center; flex: 1; }
        .btn:hover { background: #423f3b; }
        .btn-accent { background: var(--accent); border-color: var(--accent); }
        .btn-accent:hover { background: var(--accent-light); }
        .btn-red { color: #ff6b6b; }
        
        select, textarea { width: 100%; background: var(--bg); border: 1px solid var(--border); color: #fff; padding: 10px; border-radius: 4px; margin-top: 6px; font-size: 13px; outline: none; }
        label { font-size: 12px; color: var(--text); font-weight: 600; }
        
        @media (max-width: 768px) {
            .grid { flex-direction: column; gap: 15px; }
            .board-col { max-width: 100%; }
            .panel-col { min-height: auto; padding: 15px; }
            .tabs { margin-bottom: 10px; }
            .tab-btn { font-size: 12px; padding: 8px 4px; }
        }
    </style>
</head>
<body>

<div class="header">
    <h1>lichess.org <span style="font-size:12px; color:var(--accent-light); font-weight:normal;">VPS CLONE</span></h1>
</div>

<div class="tabs">
    <div class="tab-btn active" data-tab="sandbox">🔬 Анализ</div>
    <div class="tab-btn" data-tab="bot">🤖 Бот Stockfish</div>
    <div class="tab-btn" data-tab="puzzles">🧩 Задачи (<span id="eloUI">1200</span>)</div>
</div>

<div class="grid">
    <div class="board-col">
        <div id="myBoard"></div>
        <div class="btn-row">
            <div class="btn" id="btnFlip">🔄 Перевернуть</div>
            <div class="btn btn-red" id="btnReset">重 Сбросить</div>
        </div>
    </div>

    <div class="panel-col">
        <!-- Вкладка 1: Анализ -->
        <div class="tab-pane" id="pane-sandbox">
            <div class="eval-box">
                <div class="move-badge" id="tagUI" style="background:#444;">Позиция</div>
                <div class="score-val" id="scoreUI">0.00</div>
                <div style="font-size:13px; margin-top:8px;">Лучший ход: <b id="bestUI" style="color:var(--accent-light)">-</b> <span id="depthUsedUI" style="font-size:11px; color:#666;"></span></div>
            </div>
            
            <label>Глубина расчёта:</label>
            <select id="depthSelect">
                <option value="auto" selected>⚡ Авто-баланс (По нагрузке VPS)</option>
                <option value="12">Быстрый (Глубина 12)</option>
                <option value="16">Баланс (Глубина 16)</option>
                <option value="20">Глубокий (Глубина 20)</option>
            </select>
            
            <label style="margin-top:15px; display:block;">FEN строка:</label>
            <textarea id="fenInput" rows="2"></textarea>
            <div class="btn btn-accent" style="margin-top:8px;" id="btnLoadFen">Загрузить FEN</div>
        </div>

        <!-- Вкладка 2: Игра с ботом -->
        <div class="tab-pane" id="pane-bot" style="display:none;">
            <h3 style="margin:0 0 10px 0; color:#fff; font-size:16px;">Настройка противника</h3>
            <label>Уровень мастерства: <b id="botLvlTxt" style="color:var(--accent-light); font-size:15px;">10</b> / 20</label>
            <input type="range" id="botSlider" min="1" max="20" value="10" style="width:100%; accent-color:var(--accent-light); margin:12px 0;">
            
            <div id="botMsg" style="padding:12px; background:var(--bg); border-radius:4px; text-align:center; font-weight:bold; margin-top:15px;">Твой ход, белые!</div>
        </div>

        <!-- Вкладка 3: Задачи -->
        <div class="tab-pane" id="pane-puzzles" style="display:none;">
            <h3 style="margin:0; color:#fff; font-size:16px;">Тактический штурм</h3>
            <p id="puzTask" style="color:var(--accent-light); font-size:14px; margin:8px 0;"></p>
            <div id="puzStatus" style="font-size:18px; font-weight:bold; margin:25px 0; text-align:center;">-</div>
            <div class="btn btn-accent" id="btnNextPuz">Следующая задача ⏭️</div>
        </div>
    </div>
</div>

<script>
    var board = null;
    var game = new Chess();
    var CUR_TAB = 'sandbox';
    var selectedSq = null;
    var curPuz = null;
    var puzStep = 0;
    var myElo = parseInt(localStorage.getItem('lichess_elo_v4') || '1200');

    $(document).ready(function() {
        $('#eloUI').text(myElo);

        board = ChessBoard('myBoard', {
            draggable: true,
            position: 'start',
            pieceTheme: 'https://lichess1.org/assets/piece/cburnett/{piece}.svg',
            onDragStart: onDragStart,
            onDrop: onDrop,
            onSnapEnd: onSnapEnd
        });

        // Слушатели кнопок (БЕЗ inline onclick)
        $('.tab-btn').on('click', function() {
            var tab = $(this).data('tab');
            $('.tab-btn').removeClass('active');
            $(this).addClass('active');
            $('.tab-pane').hide();
            $('#pane-' + tab).fadeIn(120);
            CUR_TAB = tab;
            startMode(tab);
        });

        $('#btnFlip').on('click', function() {
            var orient = board.orientation();
            board.orientation(orient === 'white' ? 'black' : 'white');
        });

        $('#btnReset').on('click', function() { startMode(CUR_TAB); });
        $('#btnLoadFen').on('click', loadManualFen);
        $('#btnNextPuz').on('click', fetchPuzzle);
        $('#botSlider').on('input', function() { $('#botLvlTxt').text(this.value); });

        // Ходы кликами
        $('#myBoard').on('click', '.square-55d63', function() {
            onSquareClick($(this).attr('data-square'));
        });

        startMode('sandbox');
    });

    // Логика клик-ходов
    function onSquareClick(sq) {
        if (game.game_over()) return;

        if (selectedSq && ($('.square-' + sq).hasClass('hint-dot') || $('.square-' + sq).hasClass('hint-capture'))) {
            processMove({from: selectedSq, to: sq, promotion: 'q'});
            clearHints();
            return;
        }

        var piece = game.get(sq);
        if (!piece || piece.color !== game.turn()) {
            clearHints();
            return;
        }

        clearHints();
        selectedSq = sq;
        game.moves({square: sq, verbose: true}).forEach(function(m) {
            var el = $('.square-' + m.to);
            if (game.get(m.to)) el.addClass('hint-capture');
            else el.addClass('hint-dot');
        });
    }

    function clearHints() {
        selectedSq = null;
        $('#myBoard .square-55d63').removeClass('hint-dot hint-capture');
    }

    // Правила Drag&Drop
    function onDragStart(src, piece) {
        if (game.game_over()) return false;
        if ((game.turn() === 'w' && piece.search(/^b/) !== -1) ||
            (game.turn() === 'b' && piece.search(/^w/) !== -1)) return false;
        clearHints();
    }

    function onDrop(src, tgt) {
        var res = processMove({from: src, to: tgt, promotion: 'q'});
        if (res === null) return 'snapback';
    }

    function onSnapEnd() { board.position(game.fen()); }

    // Главный диспетчер ходов
    function processMove(mObj) {
        var fenPrior = game.fen();
        var move = game.move(mObj);
        if (!move) return null;

        board.position(game.fen());
        $('#fenInput').val(game.fen());

        if (CUR_TAB === 'sandbox') {
            gradeTurn(fenPrior, game.fen());
        } else if (CUR_TAB === 'bot') {
            $('#botMsg').text('🤔 Stockfish считает...').css('color', '#f0d9b5');
            setTimeout(botAIMove, 250);
        } else if (CUR_TAB === 'puzzles') {
            validatePuzMove(move.from + move.to);
        }
        return move;
    }

    function startMode(mode) {
        game.reset();
        board.start();
        clearHints();
        $('#fenInput').val(game.fen());

        if (mode === 'sandbox') gradeTurn(game.fen(), game.fen());
        if (mode === 'bot') $('#botMsg').text('Твой ход, белые!').css('color', '#fff');
        if (mode === 'puzzles') fetchPuzzle();
    }

    // --- РЕЖИМ 1 ---
    function gradeTurn(f1, f2) {
        $('#tagUI').text('...').css('background', '#444');
        var depthReq = $('#depthSelect').val();

        $.post('/grade_move', {before: f1, after: f2, depth: depthReq}, function(data) {
            $('#tagUI').text(data.tag).css('background', data.color);
            $('#scoreUI').text(data.eval);
            $('#bestUI').text(data.best);
            $('#depthUsedUI').text('(гл. ' + data.depth + ')');
        });
    }

    function loadManualFen() {
        var val = $('#fenInput').val().trim();
        if (game.load(val)) { board.position(val); gradeTurn(val, val); }
        else alert('Некорректный FEN');
    }

    // --- РЕЖИМ 2 ---
    function botAIMove() {
        if (game.game_over()) return;
        $.post('/bot_turn', {fen: game.fen(), skill: $('#botSlider').val()}, function(res) {
            game.move(res.move, {sloppy: true});
            board.position(game.fen());
            if (game.in_checkmate()) $('#botMsg').text('Мат! Победа бота ☠️').css('color', '#ff6b6b');
            else $('#botMsg').text('Твой ход!').css('color', 'var(--accent-light)');
        });
    }

    // --- РЕЖИМ 3 ---
    function fetchPuzzle() {
        $.get('/get_puzzle?elo=' + myElo, function(data) {
            curPuz = data;
            puzStep = 0;
            game.load(curPuz.fen);
            board.position(game.fen());
            $('#puzTask').text('Задача #' + curPuz.id + ': ' + curPuz.desc);
            $('#puzStatus').text('Ход белых').css('color', '#fff');
        });
    }

    function validatePuzMove(uci) {
        if (uci === curPuz.moves[puzStep]) {
            puzStep++;
            if (puzStep >= curPuz.moves.length) {
                myElo += 14;
                saveElo();
                $('#puzStatus').text('🟢 РЕШЕНО! +14 Elo').css('color', 'var(--accent-light)');
            } else {
                setTimeout(function() {
                    game.move(curPuz.moves[puzStep], {sloppy: true});
                    board.position(game.fen());
                    puzStep++;
                    $('#puzStatus').text('Продолжай...').css('color', '#f0d9b5');
                }, 350);
            }
        } else {
            myElo = Math.max(600, myElo - 12);
            saveElo();
            $('#puzStatus').text('🔴 ОШИБКА! -12 Elo').css('color', '#ff6b6b');
        }
    }

    function saveElo() {
        localStorage.setItem('lichess_elo_v4', myElo);
        $('#eloUI').text(myElo);
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
            
            # Анализ ДО
            b1 = chess.Board(f_before)
            res1 = eng.analyse(b1, chess.engine.Limit(depth=calc_depth))
            best_m = res1["pv"][0].uci() if "pv" in res1 else "-"
            s1 = res1["score"].white().score(mate_score=10000)
            
            # Анализ ПОСЛЕ
            b2 = chess.Board(f_after)
            res2 = eng.analyse(b2, chess.engine.Limit(depth=calc_depth))
            s2 = res2["score"].white().score(mate_score=10000)
            
            turn = 1 if b1.turn == chess.WHITE else -1
            delta = (s2 - s1) * turn if s1 is not None and s2 is not None else 0
            
            if delta >= 180: tag, col = "Бриллиантовый 💎", "#1baca6"
            elif delta >= -10: tag, col = "Лучший ход ⭐", "#81b64c"
            elif delta >= -35: tag, col = "Отличный ход 🟢", "#629924"
            elif delta >= -85: tag, col = "Хороший ход 🔵", "#5c8bb5"
            elif delta >= -160: tag, col = "Неточность 🟡", "#e6a817"
            elif delta >= -320: tag, col = "Ошибка 🟠", "#ca5216"
            else: tag, col = "Зевок 🔴", "#ca3431"
            
            ev_str = f"{s2/100:+.2f}" if abs(s2) != 10000 else "МАТ"
            return jsonify({"tag": tag, "color": col, "eval": ev_str, "best": best_m, "depth": calc_depth})
    except Exception:
        return jsonify({"tag": "Старт", "color": "#444", "eval": "0.00", "best": "-", "depth": calc_depth})

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
    elo = int(request.args.get('elo', 1200))
    puz = min(PUZZLES_DB, key=lambda x: abs(x['elo'] - elo))
    return jsonify(puz)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
