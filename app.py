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
<html>
<head>
    <title>SnezkaChess Premium Analysis</title>
    <meta charset="utf-8">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/chessboard-js/1.0.0/chessboard-1.0.0.min.css">
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
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            background: var(--bg-main); 
            color: var(--text); 
            margin: 0; 
            padding: 20px;
            display: flex;
            justify-content: center;
        }
        .main-wrapper {
            display: flex;
            gap: 25px;
            max-width: 1100px;
            width: 100%;
            flex-wrap: wrap;
        }
        .board-container {
            flex: 0 0 500px;
        }
        #myBoard {
            width: 100%;
            border-radius: 4px;
            overflow: hidden;
            box-shadow: 0 8px 24px rgba(0,0,0,0.5);
        }
        .panel {
            flex: 1;
            min-width: 350px;
            background: var(--bg-panel);
            border-radius: 6px;
            padding: 20px;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            box-shadow: 0 8px 24px rgba(0,0,0,0.3);
        }
        h2 { margin-top: 0; color: var(--text-light); border-bottom: 1px solid var(--border); padding-bottom: 10px; font-weight: 600; }
        h3 { color: var(--text-light); margin-bottom: 10px; font-size: 16px; }
        textarea { 
            width: 100%; background: var(--bg-input); border: 1px solid var(--border); 
            color: #fff; padding: 10px; margin-bottom: 15px; box-sizing: border-box; 
            border-radius: 4px; resize: vertical; font-family: monospace;
        }
        .row { display: flex; gap: 10px; margin-bottom: 15px; align-items: center; }
        .row input { 
            background: var(--bg-input); border: 1px solid var(--border); color: #fff; 
            padding: 8px; width: 70px; border-radius: 4px; text-align: center;
        }
        button { 
            background: var(--accent); color: white; border: none; padding: 12px 20px; 
            font-weight: bold; cursor: pointer; border-radius: 4px; width: 100%;
            transition: background 0.2s; font-size: 15px; text-transform: uppercase; letter-spacing: 0.5px;
        }
        button:hover { background: var(--accent-hover); }
        .btn-secondary { background: #45423e; margin-top: 8px; text-transform: none; font-size: 13px; padding: 8px; }
        .btn-secondary:hover { background: #5a5752; }
        
        #eval-box { 
            background: var(--bg-main); padding: 15px; border-radius: 4px; 
            margin-top: 15px; border-left: 4px solid var(--accent);
        }
        .eval-line { margin-bottom: 6px; font-size: 14px; }
        .eval-line strong { color: var(--text-light); }
        
        /* Стили для Блока Сохранений */
        .history-section {
            margin-top: 20px;
            border-top: 1px solid var(--border);
            padding-top: 15px;
            flex-grow: 1;
            display: flex;
            flex-direction: column;
        }
        .history-list {
            list-style: none; padding: 0; margin: 10px 0 0 0;
            max-height: 180px; overflow-y: auto;
        }
        .history-item {
            background: var(--bg-input); padding: 8px 12px; margin-bottom: 6px;
            border-radius: 4px; display: flex; justify-content: space-between;
            align-items: center; font-size: 13px; cursor: pointer; transition: background 0.2s;
        }
        .history-item:hover { background: #3d3935; }
        .history-item .title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px; color: #fff; }
        .delete-btn { color: #ff5252; border: none; background: none; cursor: pointer; font-weight: bold; width: auto; padding: 0 5px; }
        .delete-btn:hover { color: #ff7d7d; background: none; }
    </style>
    <script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/chessboard-js/1.0.0/chessboard-1.0.0.min.js"></script>
</head>
<body>

<div class="main-wrapper">
    <div class="board-container">
        <div id="myBoard"></div>
        <button class="btn-secondary" onclick="copyCurrentFen()">📋 Скопировать текущий FEN</button>
    </div>

    <div class="panel">
        <h2>SnezkaChess Engine v1.0</h2>
        
        <label>Вставьте FEN-позицию или PGN-партию:</label>
        <textarea id="inputData" rows="4" placeholder="1. e4 e5 2. Nf3... или FEN строка"></textarea>
        
        <div class="row">
            <label>Глубина Stockfish (10-20):</label>
            <input type="number" id="depthInput" value="14" min="5" max="20">
        </div>
        
        <button onclick="sendToVPS()">Запустить анализ на VPS</button>
        
        <div id="eval-box">
            <div class="eval-line"><strong>Статус VPS:</strong> <span id="status" style="color: #e2b714;">Ожидание команды</span></div>
            <div class="eval-line"><strong>Лучший ход:</strong> <span id="bestMove" style="color: #fff; font-weight: bold;">-</span></div>
            <div class="eval-line"><strong>Оценка позиции:</strong> <span id="evaluation" style="color: var(--accent); font-weight: bold;">-</span></div>
        </div>

        <div class="history-section">
            <h3>💾 Сохраненные партии (В браузере)</h3>
            <div style="display: flex; gap: 10px;">
                <input type="text" id="saveName" placeholder="Название партии" style="flex: 1; width: auto; margin: 0; background: var(--bg-input); border: 1px solid var(--border); color:#fff; padding:8px; border-radius:4px;">
                <button onclick="saveCurrentGame()" style="width: auto; padding: 0 15px; font-size: 13px;">Сохранить</button>
            </div>
            <ul id="historyList" class="history-list"></ul>
        </div>
    </div>
</div>

<script>
    var board;
    var currentLoadedFen = 'start';

    // Инициализация доски
    $(document).ready(function() {
        board = ChessBoard('myBoard', {
            draggable: true,
            dropOffBoard: 'trash',
            sparePieces: false,
            position: 'start',
            onChange: function(oldPos, newPos) {
                // Синхронизируем внутренний FEN при ручном движении фигур
                setTimeout(function() {
                    currentLoadedFen = board.fen();
                }, 100);
            }
        });
        renderHistory();
    });

    // Анализ на сервере
    function sendToVPS() {
        var data = $('#inputData').val().trim();
        var depth = $('#depthInput').val();
        if(!data) { data = board.fen(); } // Если поле пустое, анализируем текущую позицию на доске
        
        $('#status').text('Stockfish думает...').style = "color: #e2b714;";
        
        $.post('/analyze', { data: data, depth: depth }, function(res) {
            if(res.error) {
                $('#status').text('Ошибка: ' + res.error).css('color', '#ff5252');
            } else {
                $('#status').text('Расчет окончен').css('color', '#81b64c');
                $('#bestMove').text(res.best_move);
                $('#evaluation').text(res.evaluation);
                board.position(res.current_fen);
                currentLoadedFen = res.current_fen;
            }
        }).fail(function() {
            $('#status').text('VPS недоступен (проверьте порт 5000 без HTTPS)').css('color', '#ff5252');
        });
    }

    function copyCurrentFen() {
        navigator.clipboard.writeText(currentLoadedFen);
        alert('FEN скопирован в буфер обмена!');
    }

    // --- ЛОГИКА LOCALSTORAGE ---
    function saveCurrentGame() {
        var name = $('#saveName').val().trim() || "Партия от " + new Date().toLocaleTimeString();
        var dataToSave = $('#inputData').val().trim() || currentLoadedFen;
        
        var games = JSON.parse(localStorage.getItem('chess_games') || '[]');
        games.push({ name: name, data: dataToSave, fen: currentLoadedFen });
        localStorage.setItem('chess_games', JSON.stringify(games));
        
        $('#saveName').val('');
        renderHistory();
    }

    function renderHistory() {
        var games = JSON.parse(localStorage.getItem('chess_games') || '[]');
        var $list = $('#historyList').empty();
        
        games.forEach(function(game, index) {
            var $item = $('<li class="history-item"></li>');
            $item.append('<span class="title" title="'+game.name+'">' + game.name + '</span>');
            
            var $deleteBtn = $('<button class="delete-btn">✕</button>');
            $deleteBtn.click(function(e) {
                e.stopPropagation();
                deleteGame(index);
            });
            
            $item.append($deleteBtn);
            $item.click(function() {
                $('#inputData').val(game.data);
                board.position(game.fen);
                currentLoadedFen = game.fen;
            });
            
            $list.append($item);
        });
    }

    function deleteGame(index) {
        var games = JSON.parse(localStorage.getItem('chess_games') || '[]');
        games.splice(index, 1);
        localStorage.setItem('chess_games', JSON.stringify(games));
        renderHistory();
    }
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
        except ValueError: return jsonify({"error": "Некорректный FEN или PGN"})

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
