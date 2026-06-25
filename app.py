import os
from flask import Flask, render_template_string, request, jsonify
import chess
import chess.engine
import chess.pgn
import io

app = Flask(__name__)
STOCKFISH_PATH = "/usr/games/stockfish"

ENGINE_OPTIONS = {
    "Threads": 1,        
    "Hash": 16          
}

HTML_INTERFACE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>SnezkaChess Pro Analysis</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/cm-chessboard@4.3.0/assets/styles/cm-chessboard.css">
    <style>
        :root {
            --bg-main: #161512;
            --bg-panel: #262421;
            --bg-input: #312e2b;
            --accent: #81b64c;
            --accent-hover: #a3d16c;
            --text: #bababa;
            --text-light: #ffffff;
            --border: #403c38;
        }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; 
            background: var(--bg-main); 
            color: var(--text); 
            margin: 0; 
            padding: 20px;
            display: flex;
            justify-content: center;
        }
        .main-wrapper {
            display: flex;
            gap: 30px;
            max-width: 1200px;
            width: 100%;
            flex-wrap: wrap;
            justify-content: center;
        }
        .board-container {
            flex: 0 0 500px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        /* Стилизация современной доски под Lichess */
        .chessboard {
            width: 100%;
            border-radius: 4px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.6);
        }
        .chessboard .board.brown {
            background-color: #b58863;
        }
        .chessboard .square.black {
            background-color: #b58863 !important;
        }
        .chessboard .square.white {
            background-color: #f0d9b5 !important;
        }
        /* Маркер подсветки возможных ходов */
        .chessboard .marker-dot {
            background: rgba(0, 0, 0, 0.15) !important;
            border-radius: 50%;
            width: 30% !important;
            height: 30% !important;
            position: absolute;
            top: 35%;
            left: 35%;
        }
        .panel {
            flex: 1;
            min-width: 380px;
            background: var(--bg-panel);
            border-radius: 8px;
            padding: 25px;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            box-shadow: 0 10px 30px rgba(0,0,0,0.4);
        }
        h2 { margin-top: 0; color: var(--text-light); font-size: 22px; border-bottom: 1px solid var(--border); padding-bottom: 12px; }
        h3 { color: var(--text-light); margin: 20px 0 10px 0; font-size: 16px; }
        textarea { 
            width: 100%; background: var(--bg-input); border: 1px solid var(--border); 
            color: #fff; padding: 12px; margin-bottom: 15px; box-sizing: border-box; 
            border-radius: 4px; resize: vertical; font-family: monospace; font-size: 13px;
        }
        .button-group { display: flex; gap: 10px; margin-bottom: 15px; }
        button { 
            background: var(--accent); color: white; border: none; padding: 12px 20px; 
            font-weight: bold; cursor: pointer; border-radius: 4px;
            transition: background 0.15s; font-size: 14px; text-transform: uppercase;
        }
        button:hover { background: var(--accent-hover); }
        .btn-flex { flex: 1; }
        .btn-secondary { background: #45423e; text-transform: none; padding: 8px 12px; font-size: 13px; }
        .btn-secondary:hover { background: #5a5752; }
        .btn-danger { background: #b64c4c; }
        .btn-danger:hover { background: #d16c6c; }
        
        #eval-box { 
            background: var(--bg-main); padding: 15px; border-radius: 4px; 
            border-left: 4px solid var(--accent); margin-bottom: 15px;
        }
        .eval-line { margin-bottom: 8px; font-size: 14px; }
        .eval-line strong { color: var(--text-light); }
        
        .history-section {
            border-top: 1px solid var(--border);
            padding-top: 15px;
            display: flex;
            flex-direction: column;
            flex-grow: 1;
        }
        .history-list {
            list-style: none; padding: 0; margin: 10px 0 0 0;
            max-height: 150px; overflow-y: auto;
        }
        .history-item {
            background: var(--bg-input); padding: 10px 12px; margin-bottom: 6px;
            border-radius: 4px; display: flex; justify-content: space-between;
            align-items: center; font-size: 13px; cursor: pointer;
        }
        .history-item:hover { background: #3d3935; }
        .history-item .title { color: #fff; font-weight: 500; }
    </style>
</head>
<body>

<div class="main-wrapper">
    <div class="board-container">
        <div id="myBoard" class="chessboard"></div>
        <div style="display: flex; gap: 10px;">
            <button class="btn-secondary btn-flex" onclick="board.setOrientation(board.getOrientation() === 'white' ? 'black' : 'white')">🔄 Перевернуть</button>
            <button class="btn-secondary btn-flex" onclick="copyCurrentFen()">📋 Копировать FEN</button>
            <button class="btn-secondary btn-flex btn-danger" onclick="resetBoard()">重 Сброс</button>
        </div>
    </div>

    <div class="panel">
        <h2>SnezkaChess Premium</h2>
        
        <label>Вставьте FEN или PGN (или просто двигайте фигуры):</label>
        <textarea id="inputData" rows="3" placeholder="1. e4 e5 2. Nf3... или FEN строка"></textarea>
        
        <div class="button-group">
            <button class="btn-flex" onclick="sendToVPS()">Анализ на VPS</button>
        </div>
        
        <div id="eval-box">
            <div class="eval-line"><strong>Статус:</strong> <span id="status" style="color: #e2b714;">Ожидание ходов</span></div>
            <div class="eval-line"><strong>Лучший ход:</strong> <span id="bestMove" style="color: #fff; font-weight: bold;">-</span></div>
            <div class="eval-line"><strong>Оценка:</strong> <span id="evaluation" style="color: var(--accent); font-weight: bold;">-</span></div>
        </div>

        <div class="history-section">
            <h3>💾 Локальные сохранения</h3>
            <div style="display: flex; gap: 10px;">
                <input type="text" id="saveName" placeholder="Название записи" style="flex: 1; background: var(--bg-input); border: 1px solid var(--border); color:#fff; padding:8px; border-radius:4px;">
                <button onclick="saveCurrentGame()" style="padding: 0 15px; font-size: 12px;">Сохранить</button>
            </div>
            <ul id="historyList" class="history-list"></ul>
        </div>
    </div>
</div>

<script type="module">
    import { Chessboard, BORDER_TYPE } from "https://cdn.jsdelivr.net/npm/cm-chessboard@4.3.0/src/cm-chessboard/Chessboard.js";
    import { MOVE_INPUT_MODE } from "https://cdn.jsdelivr.net/npm/cm-chessboard@4.3.0/src/cm-chessboard/extensions/move-input/MoveInput.js";
    import { Chess } from "https://cdnjs.cloudflare.com/ajax/libs/chess.js/0.13.4/chess.js";

    window.chess = new Chess();
    
    // Кастомный набор фигур напрямую с серверов Lichess
    const LICHESS_PIECES = "https://lichess1.org/assets/piece/cburnett/#piece#.svg";

    window.board = new Chessboard(document.getElementById("myBoard"), {
        position: "start",
        assetsUrl: "https://cdn.jsdelivr.net/npm/cm-chessboard@4.3.0/assets/",
        style: { pieces: { type: "custom", url: LICHESS_PIECES, size: 40 } },
        borderType: BORDER_TYPE.none
    });

    // Включаем полноценный ввод ходов с проверкой правил
    window.board.enableMoveInput((event) => {
        switch (event.type) {
            case MOVE_INPUT_MODE.moveStart:
                // Подсвечиваем легальные ходы при клике на фигуру
                const moves = window.chess.moves({ square: event.square, verbose: true });
                moves.forEach(move => window.board.addMarker(move.to, { class: "marker-dot" }));
                return true;
            case MOVE_INPUT_MODE.moveDone:
                window.board.removeMarkers();
                const move = window.chess.move({ from: event.squareFrom, to: event.squareTo, promotion: "q" });
                if (move) {
                    // Если ход валидный, обновляем доску и поле ввода
                    window.board.setPosition(window.chess.fen(), true);
                    document.getElementById("inputData").value = window.chess.fen();
                    return true;
                }
                return false;
            case MOVE_INPUT_MODE.moveCanceled:
                window.board.removeMarkers();
                break;
        }
    });

    window.syncWithText = function(data) {
        if (!data) return;
        let validated = new Chess();
        if (data.startsWith('1.') || data.includes(' ')) {
            if (validated.load_pgn(data)) { window.chess = validated; }
            else if (validated.load(data)) { window.chess = validated; }
        } else {
            if (validated.load(data)) { window.chess = validated; }
        }
        window.board.setPosition(window.chess.fen(), true);
    };
</script>

<script>
    function sendToVPS() {
        // Синхронизируем текст с доской перед отправкой
        var textData = $('#inputData').val().trim();
        if (textData && typeof window.syncWithText === 'function') {
            window.syncWithText(textData);
        }
        
        var currentFen = window.chess ? window.chess.fen() : 'start';
        var depth = $('#depthInput').val() || 14;
        
        $('#status').text('Stockfish анализирует...').css('color', '#e2b714');
        
        $.post('/analyze', { data: currentFen, depth: depth }, function(res) {
            if(res.error) {
                $('#status').text('Ошибка: ' + res.error).css('color', '#ff5252');
            } else {
                $('#status').text('Анализ завершен').css('color', '#81b64c');
                $('#bestMove').text(res.best_move);
                $('#evaluation').text(res.evaluation);
            }
        }).fail(function() {
            $('#status').text('Ошибка сети VPS').css('color', '#ff5252');
        });
    }

    function resetBoard() {
        if(window.chess) {
            window.chess.reset();
            window.board.setPosition(window.chess.fen(), true);
            $('#inputData').val('');
            $('#bestMove').text('-');
            $('#evaluation').text('-');
            $('#status').text('Доска сброшена').css('color', '#bababa');
        }
    }

    function copyCurrentFen() {
        var fen = window.chess ? window.chess.fen() : 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
        navigator.clipboard.writeText(fen);
        alert('FEN скопирован!');
    }

    function saveCurrentGame() {
        var name = $('#saveName').val().trim() || "Позиция " + new Date().toLocaleTimeString();
        var fen = window.chess ? window.chess.fen() : 'start';
        var games = JSON.parse(localStorage.getItem('chess_games_v2') || '[]');
        games.push({ name: name, fen: fen });
        localStorage.setItem('chess_games_v2', JSON.stringify(games));
        $('#saveName').val('');
        renderHistory();
    }

    function renderHistory() {
        var games = JSON.parse(localStorage.getItem('chess_games_v2') || '[]');
        var $list = $('#historyList').empty();
        games.forEach(function(game, index) {
            var $item = $('<li class="history-item"></li>');
            $item.append('<span class="title">' + game.name + '</span>');
            var $del = $('<button class="delete-btn" style="background:none;color:#ff5252;width:auto;padding:0;">✕</button>');
            $del.click(function(e) {
                e.stopPropagation();
                games.splice(index, 1);
                localStorage.setItem('chess_games_v2', JSON.stringify(games));
                renderHistory();
            });
            $item.append($del);
            $item.click(function() {
                if(window.chess && window.board) {
                    window.chess.load(game.fen);
                    window.board.setPosition(game.fen, true);
                    $('#inputData').val(game.fen);
                }
            });
            $list.append($item);
        });
    }

    $(document).ready(function() {
        setTimeout(renderHistory, 500);
    });
</script>

</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_INTERFACE)

@app.route('/analyze', methods=['POST'])
def analyze():
    raw_data = request.form.get('data', '').strip()
    depth = int(request.form.get('depth', 14))
    if depth > 20: depth = 20 

    board = chess.Board()
    if raw_data.startswith('1.') or '[' in raw_data or (' ' in raw_data and not '/' in raw_data):
        try:
            pgn = chess.pgn.read_game(io.StringIO(raw_data))
            if pgn is not None: board = pgn.end().board()
        except Exception: return jsonify({"error": "Не удалось распарсить PGN"})
    else:
        try: board = chess.Board(raw_data)
        except ValueError: return jsonify({"error": "Некорректный FEN"})

    try:
        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
            engine.configure(ENGINE_OPTIONS)
            result = engine.analyse(board, chess.engine.Limit(depth=depth))
            score = result["score"].white()
            eval_str = f"M{abs(score.mate())}" if score.is_mate() else f"{score.score() / 100:+.2f}"
            best_move = result.get("pv")[0].uci() if result.get("pv") else "Нет ходов"
            return jsonify({"best_move": best_move, "evaluation": eval_str, "current_fen": board.fen()})
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
