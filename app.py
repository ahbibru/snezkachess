import os
import io
import json
import random
from flask import Flask, render_template_string, request, jsonify
import chess
import chess.engine

app = Flask(__name__)
STOCKFISH_PATH = "/usr/games/stockfish"

ENGINE_OPTIONS = {"Threads": 1, "Hash": 16}

# Вшитая база тактических задач разных уровней (от 800 до 2200 Elo)
PUZZLES_DB = [
    {"id": 1, "elo": 850, "fen": "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4", "moves": ["h5f7"], "desc": "Мат в 1 ход (Детский)"},
    {"id": 2, "elo": 1050, "fen": "r1b1k2r/ppppnppp/2n2q2/2b5/3NP3/2P1B3/PP3PPP/RN1QKB1R w KQkq - 3 7", "moves": ["d4c6", "c5e3", "c6d8"], "desc": "Вскрытый удар и выигрыш ферзя"},
    {"id": 3, "elo": 1300, "fen": "2r3k1/p4ppp/1p2p3/3b4/3P4/q3PN2/1Q3PPP/2R3K1 b - - 1 22", "solution_fen": "8/p4ppp/1p2p3/3b4/3P4/4PN2/1q3PPP/2q3K1 w - - 0 24", "moves": ["c8c1", "b2c1", "a3c1"], "desc": "Слабость 1-й горизонтали"},
    {"id": 4, "elo": 1550, "fen": "r2q1rk1/ppp2ppp/2n1bn2/8/1b1P4/2N1BN2/PPP1BPPP/R2Q1RK1 w - - 8 10", "moves": ["a2a3", "b4c3", "b2c3"], "desc": "Упрощение игры"},
    {"id": 5, "elo": 1800, "fen": "5rk1/pp3ppp/4p3/1b1pP3/1q1P4/1Pr1PN2/P2Q2PP/2R1R1K1 b - - 4 19", "moves": ["f8c8", "c1c3", "b4c3"], "desc": "Борьба за единственную открытую вертикаль"},
    {"id": 6, "elo": 2150, "fen": "r2q1rk1/1pp1nppp/p2bp3/8/3PN3/3Q1N2/PPP2PPP/4RRK1 w - - 4 13", "moves": ["e4f6", "g7f6", "d3h7"], "desc": "Классическая жертва на h7"}
]

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>SnezkaChess v3 | Grandmaster</title>
    
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/chessboard-js/1.0.0/chessboard-1.0.0.min.css">
    <script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/chessboard-js/1.0.0/chessboard-1.0.0.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/chess.js/0.10.3/chess.min.js"></script>
    
    <style>
        :root {
            --bg: #11100f; --panel: #211f1c; --input: #2c2a27;
            --accent: #81b64c; --accent-hover: #98d65a;
            --text: #c3c0bc; --white: #ffffff; --border: #383531;
            
            /* Цвета оценок ходов */
            --brilliant: #1baca6; --best: #81b64c; --good: #5c8bb5; 
            --inaccuracy: #f0c15c; --mistake: #e68f2e; --blunder: #ca3431;
        }
        
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body { font-family: -apple-system, system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 10px; }
        
        .nav-tabs { display: flex; gap: 6px; max-width: 950px; margin: 0 auto 15px auto; }
        .tab-btn { flex: 1; background: var(--panel); color: var(--text); border: 1px solid var(--border); padding: 12px 5px; font-weight: bold; border-radius: 8px; cursor: pointer; text-align: center; font-size: 13px; }
        .tab-btn.active { background: var(--accent); color: var(--white); border-color: var(--accent); }
        
        .app-grid { display: flex; gap: 20px; max-width: 950px; margin: 0 auto; align-items: flex-start; }
        .board-zone { flex: 0 0 420px; width: 100%; max-width: 420px; }
        .panel-zone { flex: 1; background: var(--panel); border-radius: 12px; padding: 20px; border: 1px solid var(--border); min-height: 420px; display: flex; flex-direction: column; }
        
        /* Доска */
        .white-1e1d7 { background-color: #edeed1; }
        .black-3c85d { background-color: #779952; }
        .board-b72b1 { border: none !important; border-radius: 8px; overflow: hidden; box-shadow: 0 15px 35px rgba(0,0,0,0.7); }
        
        /* Точки для клик-ходов */
        .click-dot::after { content: ''; position: absolute; width: 28%; height: 28%; background: rgba(0,0,0,0.25); border-radius: 50%; top: 36%; left: 36%; pointer-events: none; }
        .click-capture::after { content: ''; position: absolute; width: 80%; height: 80%; border: 6px solid rgba(0,0,0,0.25); border-radius: 50%; top: 10%; left: 10%; pointer-events: none; }
        
        /* Виджет оценки */
        .eval-card { background: var(--bg); border-radius: 8px; padding: 15px; margin-bottom: 15px; border-left: 5px solid var(--accent); }
        .badge { display: inline-block; padding: 4px 10px; border-radius: 4px; font-weight: bold; font-size: 13px; color: #fff; margin-bottom: 8px;}
        .big-eval { font-size: 32px; font-weight: 800; color: var(--white); }
        
        /* Элементы управления */
        .btn-row { display: flex; gap: 8px; margin-top: 12px; }
        .btn { background: var(--input); color: var(--white); border: 1px solid var(--border); padding: 10px; border-radius: 6px; font-weight: bold; cursor: pointer; flex: 1; text-align: center; font-size: 13px;}
        .btn-green { background: var(--accent); border-color: var(--accent); }
        .btn-red { background: var(--blunder); border-color: var(--blunder); }
        
        textarea { width: 100%; background: var(--input); border: 1px solid var(--border); color: #fff; padding: 10px; border-radius: 6px; font-family: monospace; font-size: 12px; margin-top: 10px;}
        
        .slider-box { margin: 15px 0; background: var(--bg); padding: 12px; border-radius: 8px; }
        input[type=range] { width: 100%; accent-color: var(--accent); }
        
        /* Мобильная адаптация */
        @media (max-width: 768px) {
            .app-grid { flex-direction: column; gap: 12px; }
            .board-zone { flex: none; max-width: 100%; }
            .panel-zone { min-height: auto; padding: 15px; }
            .nav-tabs { gap: 4px; }
            .tab-btn { font-size: 11px; padding: 10px 2px; }
        }
    </style>
</head>
<body>

<div class="nav-tabs">
    <div class="tab-btn active" onclick="switchMode('sandbox')">🔬 Анализ</div>
    <div class="tab-btn" onclick="switchMode('bot')">🤖 Игра с Ботом</div>
    <div class="tab-btn" onclick="switchMode('puzzles')">🧩 Задачи (<span id="puzzleEloTxt">1200</span>)</div>
</div>

<div class="app-grid">
    <div class="board-zone">
        <div id="board"></div>
        <div class="btn-row">
            <div class="btn" onclick="board.flip()">🔄 Перевернуть</div>
            <div class="btn btn-red" onclick="initCurrentMode()">重 Начать заново</div>
        </div>
    </div>

    <div class="panel-zone">
        <!-- ТАБ 1: АНАЛИЗ -->
        <div id="panel-sandbox" class="mode-panel">
            <div class="eval-card" id="sandboxCard">
                <div class="badge" id="moveTag" style="background: var(--good);">Ход в игре</div>
                <div class="big-eval" id="evalScore">0.00</div>
                <div style="font-size:13px; margin-top:5px;">Лучший ответ движка: <b id="bestMoveTxt" style="color:var(--accent)">-</b></div>
            </div>
            <label style="font-size:12px;">Позиция (FEN):</label>
            <textarea id="fenIO" rows="2"></textarea>
            <div class="btn btn-green" style="margin-top:8px;" onclick="loadCustomFen()">Загрузить FEN</div>
        </div>

        <!-- ТАБ 2: БОТ -->
        <div id="panel-bot" class="mode-panel" style="display:none;">
            <h3 style="margin:0 0 10px 0; color:#fff;">Схватка со Stockfish</h3>
            <div class="slider-box">
                <div style="display:flex; justify-content:space-between; margin-bottom:5px;">
                    <span>Уровень Бота: <b id="botLvlTxt" style="color:var(--accent)">10</b></span>
                    <span style="font-size:11px; color:#888;">(1=Новичок, 20=Бог)</span>
                </div>
                <input type="range" id="botSlider" min="1" max="20" value="10" oninput="$('#botLvlTxt').text(this.value)">
            </div>
            <div id="botStatus" style="padding:10px; background:var(--input); border-radius:6px; text-align:center; font-weight:bold;">Твой ход, белые!</div>
        </div>

        <!-- ТАБ 3: ЗАДАЧИ -->
        <div id="panel-puzzles" class="mode-panel" style="display:none;">
            <h3 style="margin:0; color:#fff;">Тактический штурм</h3>
            <p id="puzzleDesc" style="color:var(--accent); font-size:14px;">Найди сильнейшее продолжение</p>
            <div id="puzzleFeedback" style="font-size:18px; font-weight:bold; margin:20px 0; text-align:center;">-</div>
            <div class="btn btn-green" onclick="nextPuzzle()">Следующая задача ⏭️</div>
        </div>
    </div>
</div>

<script>
    var board = null;
    var game = new Chess();
    var MODE = 'sandbox'; // 'sandbox' | 'bot' | 'puzzles'
    
    // Переменные логики
    var selectedSq = null;
    var curPuzzle = null;
    var puzzleStep = 0;
    var userElo = parseInt(localStorage.getItem('snezka_elo') || '1200');
    $('#puzzleEloTxt').text(userElo);

    // --- ИНИЦИАЛИЗАЦИЯ ДОСКИ ---
    var cfg = {
        draggable: true,
        position: 'start',
        pieceTheme: 'https://lichess1.org/assets/piece/cburnett/{piece}.svg',
        onDragStart: onDragStart,
        onDrop: onDrop,
        onSnapEnd: onSnapEnd
    };
    board = ChessBoard('board', cfg);

    // Обработка кликов по квадратам (Ходы кликами!)
    $('#board').on('click', '.square-55d63', function() {
        var sq = $(this).attr('data-square');
        handleSquareClick(sq);
    });

    function handleSquareClick(sq) {
        if (game.game_over()) return;

        // Если кликнули по подсвеченной точке — делаем ход
        if (selectedSq && ($('.square-' + sq).hasClass('click-dot') || $('.square-' + sq).hasClass('click-capture'))) {
            makeClientMove({from: selectedSq, to: sq, promotion: 'q'});
            clearHighlight();
            return;
        }

        // Иначе пытаемся выбрать фигуру своего цвета
        var piece = game.get(sq);
        if (!piece || piece.color !== game.turn()) {
            clearHighlight();
            return;
        }

        clearHighlight();
        selectedSq = sq;
        
        var moves = game.moves({square: sq, verbose: true});
        moves.forEach(m => {
            var el = $('.square-' + m.to);
            if (game.get(m.to)) el.addClass('click-capture');
            else el.addClass('click-dot');
        });
    }

    function clearHighlight() {
        selectedSq = null;
        $('#board .square-55d63').removeClass('click-dot click-capture');
    }

    // --- ЛОГИКА ПРАВИЛ ---
    function onDragStart(source, piece) {
        if (game.game_over()) return false;
        if ((game.turn() === 'w' && piece.search(/^b/) !== -1) ||
            (game.turn() === 'b' && piece.search(/^w/) !== -1)) return false;
        clearHighlight();
    }

    function onDrop(source, target) {
        var move = makeClientMove({from: source, to: target, promotion: 'q'});
        if (move === null) return 'snapback';
    }

    function onSnapEnd() { board.position(game.fen()); }

    function makeClientMove(moveObj) {
        var fenBefore = game.fen();
        var move = game.move(moveObj);
        if (!move) return null;

        board.position(game.fen());
        $('#fenIO').val(game.fen());

        // Роутинг действий после хода игрока
        if (MODE === 'sandbox') {
            analyzeMoveQuality(fenBefore, game.fen());
        } else if (MODE === 'bot') {
            $('#botStatus').text('🤖 Бот размышляет...').css('color', '#f0c15c');
            setTimeout(makeBotMove, 250);
        } else if (MODE === 'puzzles') {
            checkPuzzleMove(move.from + move.to);
        }
        return move;
    }

    // --- РЕЖИМ 1: АНАЛИЗ И КОММЕНТАТОР ---
    function analyzeMoveQuality(fBefore, fAfter) {
        $('#moveTag').text('Оценка...').css('background', '#444');
        $.post('/grade_move', {before: fBefore, after: fAfter}, function(data) {
            $('#moveTag').text(data.tag).css('background', data.color);
            $('#evalScore').text(data.eval);
            $('#bestMoveTxt').text(data.best);
        });
    }

    function loadCustomFen() {
        var f = $('#fenIO').val().trim();
        if(game.load(f)) { board.position(f); analyzeMoveQuality(f, f); }
        else alert('Кривой FEN!');
    }

    // --- РЕЖИМ 2: ИГРА С БОТОМ ---
    function makeBotMove() {
        if (game.game_over()) { $('#botStatus').text('Партия окончена!'); return; }
        
        var lvl = $('#botSlider').val();
        $.post('/bot_turn', {fen: game.fen(), level: lvl}, function(res) {
            game.move(res.move, {sloppy: true});
            board.position(game.fen());
            
            if(game.in_checkmate()) $('#botStatus').text('Шах и Мат! Бот победил ☠️').css('color', '#ca3431');
            else $('#botStatus').text('Твой ход!').css('color', '#81b64c');
        });
    }

    // --- РЕЖИМ 3: ЗАДАЧИ ---
    function nextPuzzle() {
        $.get('/get_puzzle?elo=' + userElo, function(data) {
            curPuzzle = data;
            puzzleStep = 0;
            game.load(curPuzzle.fen);
            board.position(game.fen());
            $('#puzzleDesc').text('Задача #' + curPuzzle.id + ' (' + curPuzzle.desc + ')');
            $('#puzzleFeedback').text('Белые начинают').css('color', '#fff');
        });
    }

    function checkPuzzleMove(userUci) {
        if (userUci === curPuzzle.moves[puzzleStep]) {
            puzzleStep++;
            if (puzzleStep >= curPuzzle.moves.length) {
                userElo += 15;
                saveElo();
                $('#puzzleFeedback').text('🟢 ВЕЛИКОЛЕПНО! +15 Рейтинга').css('color', 'var(--best)');
            } else {
                // Ход бота в задаче
                setTimeout(function() {
                    game.move(curPuzzle.moves[puzzleStep], {sloppy: true});
                    board.position(game.fen());
                    puzzleStep++;
                    $('#puzzleFeedback').text('Продолжай комбинацию...').css('color', 'var(--inaccuracy)');
                }, 400);
            }
        } else {
            userElo = Math.max(500, userElo - 10);
            saveElo();
            $('#puzzleFeedback').text('🔴 ОШИБКА! -10 Рейтинга').css('color', 'var(--blunder)');
        }
    }

    function saveElo() {
        localStorage.setItem('snezka_elo', userElo);
        $('#puzzleEloTxt').text(userElo);
    }

    // --- ПЕРЕКЛЮЧЕНИЕ ВКЛАДОК ---
    window.switchMode = function(m) {
        MODE = m;
        $('.tab-btn').removeClass('active');
        $('[onclick="switchMode(\''+m+'\')"]').addClass('active');
        $('.mode-panel').hide();
        $('#panel-' + m).fadeIn(150);
        initCurrentMode();
    };

    function initCurrentMode() {
        game.reset();
        board.start();
        clearHighlight();
        if (MODE === 'puzzles') nextPuzzle();
        if (MODE === 'bot') $('#botStatus').text('Твой ход, белые!').css('color', '#fff');
        if (MODE === 'sandbox') { $('#fenIO').val(game.fen()); analyzeMoveQuality(game.fen(), game.fen()); }
    }

    $(document).ready(function() { initCurrentMode(); });
</script>

</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

# Оценщик ходов (Бестовый, Брилльянт, Зевок)
@app.route('/grade_move', methods=['POST'])
def grade_move():
    f_before = request.form.get('before')
    f_after = request.form.get('after')
    
    try:
        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as eng:
            eng.configure(ENGINE_OPTIONS)
            # Анализируем позицию ДО
            b_before = chess.Board(f_before)
            res1 = eng.analyse(b_before, chess.engine.Limit(depth=11))
            best_move = res1["pv"][0].uci() if "pv" in res1 else "нет"
            score_b = res1["score"].white().score(mate_score=10000)
            
            # Анализируем позицию ПОСЛЕ
            b_after = chess.Board(f_after)
            res2 = eng.analyse(b_after, chess.engine.Limit(depth=11))
            score_a = res2["score"].white().score(mate_score=10000)
            
            # Считаем разницу с точки зрения того, кто ходил
            turn = 1 if b_before.turn == chess.WHITE else -1
            delta = (score_a - score_b) * turn
            
            # Раздаём ярлыки
            if delta >= 150: tag, col = "Бриллиантовый 💎", "var(--brilliant)"
            elif delta >= -15: tag, col = "Лучший ход ⭐", "var(--best)"
            elif delta >= -40: tag, col = "Отличный ход 🟢", "var(--accent)"
            elif delta >= -90: tag, col = "Хороший ход 🔵", "var(--good)"
            elif delta >= -180: tag, col = "Неточность 🟡", "var(--inaccuracy)"
            elif delta >= -350: tag, col = "Ошибка 🟠", "var(--mistake)"
            else: tag, col = "Зевок 🔴", "var(--blunder)"
            
            eval_txt = f"{score_a/100:+.2f}" if abs(score_a) != 10000 else "МАТ"
            return jsonify({"tag": tag, "color": col, "eval": eval_txt, "best": best_move})
    except Exception as e:
        return jsonify({"tag": "ОК", "color": "#444", "eval": "0.00", "best": "-"})

# Ход Бота с урезанным скиллом
@app.route('/bot_turn', methods=['POST'])
def bot_turn():
    fen = request.form.get('fen')
    lvl = int(request.form.get('level', 10))
    board = chess.Board(fen)
    
    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as eng:
        # Честно глупим движок через официальный параметр Skill Level (0 - 20)
        eng.configure({"Skill Level": lvl})
        res = eng.play(board, chess.engine.Limit(time=0.2))
        return jsonify({"move": res.move.uci()})

# Выдача задачи под уровень
@app.route('/get_puzzle')
def get_puzzle():
    user_elo = int(request.args.get('elo', 1200))
    # Берём задачу, максимально близкую к рейтингу игрока
    best_p = min(PUZZLES_DB, key=lambda x: abs(x['elo'] - user_elo))
    return jsonify(best_p)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
