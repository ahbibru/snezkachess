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
    <title>VPS Chess Analysis</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/chessboard-js/1.0.0/chessboard-1.0.0.min.css">
    <style>
        body { font-family: Arial, sans-serif; max-width: 900px; margin: 20px auto; padding: 0 10px; background: #262522; color: #bababa; }
        .container { display: flex; gap: 30px; flex-wrap: wrap; }
        .controls { flex: 1; min-width: 300px; }
        textarea, input { width: 100%; background: #312e2b; border: 1px solid #403c38; color: #fff; padding: 8px; margin-bottom: 10px; box-sizing: border-box; }
        button { background: #81b64c; color: white; border: none; padding: 10px 20px; font-weight: bold; cursor: pointer; width: 100%; border-radius: 4px; }
        button:hover { background: #a3d16c; }
        #eval-box { background: #312e2b; padding: 15px; border-radius: 4px; margin-top: 15px; min-height: 50px; }
    </style>
    <script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/chessboard-js/1.0.0/chessboard-1.0.0.min.js"></script>
</head>
<body>
    <h2>Серверный анализ (Stockfish на VPS)</h2>
    <div class="container">
        <div id="myBoard" style="width: 450px"></div>
        <div class="controls">
            <h3>Ввод данных</h3>
            <label>Вставьте FEN или PGN партии:</label>
            <textarea id="inputData" rows="6" placeholder="1. e4 e5 2. Nf3... или FEN строка"></textarea>
            
            <label>Глубина анализа (рекомендуется 12-15 для 1 ядра):</label>
            <input type="number" id="depthInput" value="14" min="5" max="20">
            
            <button onclick="sendToVPS()">Анализировать позицию</button>
            
            <div id="eval-box">
                <strong>Статус:</strong> <span id="status">Ожидание...</span><br><br>
                <strong>Лучший ход:</strong> <span id="bestMove">-</span><br>
                <strong>Оценка VPS:</strong> <span id="evaluation">-</span>
            </div>
        </div>
    </div>

    <script>
        var board = ChessBoard('myBoard', 'start');
        function sendToVPS() {
            var data = $('#inputData').val().trim();
            var depth = $('#depthInput').val();
            if(!data) { alert('Введите FEN или PGN'); return; }
            $('#status').text('VPS производит расчеты...');
            $.post('/analyze', { data: data, depth: depth }, function(res) {
                if(res.error) { $('#status').text('Ошибка: ' + res.error); } 
                else {
                    $('#status').text('Готово!');
                    $('#bestMove').text(res.best_move);
                    $('#evaluation').text(res.evaluation);
                    board.position(res.current_fen);
                }
            }).fail(function() { $('#status').text('Ошибка соединения с VPS'); });
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
    if raw_data.startswith('1.') or '[' in raw_data or ' ' in raw_data and not '/' in raw_data:
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
