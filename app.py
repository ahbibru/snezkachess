import os
from flask import Flask, render_template_string, request, jsonify
import chess
import chess.engine

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
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SnezkaChess | Auto-Analysis</title>
    
    <!-- Надежные библиотеки для шахматной логики и отрисовки -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/chessboard-js/1.0.0/chessboard-1.0.0.min.css">
    <script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/chessboard-js/1.0.0/chessboard-1.0.0.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/chess.js/0.10.3/chess.min.js"></script>
    
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
            --board-dark: #b58863;
            --board-light: #f0d9b5;
        }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            background: var(--bg-main); color: var(--text); 
            margin: 0; padding: 20px;
            display: flex; justify-content: center;
        }
        .container {
            display: flex; gap: 30px; max-width: 1000px; width: 100%; flex-wrap: wrap; justify-content: center;
        }
        
        /* Стилизация доски */
        .board-wrapper { flex: 0 0 450px; width: 100%; max-width: 450px; }
        .white-1e1d7 { background-color: var(--board-light); }
        .black-3c85d { background-color: var(--board-dark); }
        .board-b72b1 { border: none !important; border-radius: 6px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
        
        /* Панель управления */
        .panel {
            flex: 1; min-width: 320px; background: var(--bg-panel); border-radius: 8px;
            padding: 25px; box-sizing: border-box; display: flex; flex-direction: column;
            box-shadow: 0 10px 25px rgba(0,0,0,0.3);
        }
        h2 { margin-top: 0; color: var(--text-light); font-size: 22px; border-bottom: 1px solid var(--border); padding-bottom: 12px; }
        
        /* Блок анализа */
        .eval-container {
            background: var(--bg-main); padding: 20px; border-radius: 6px; 
            border-left: 5px solid var(--accent); margin-bottom: 20px;
        }
        .eval-status { color: #e2b714; font-size: 13px; text-transform: uppercase; font-weight: bold; margin-bottom: 10px; }
        .eval-score { font-size: 36px; font-weight: bold; color: var(--text-light); margin: 10px 0; }
        .eval-bestmove { font-size: 18px; color: var(--accent); font-weight: bold; }
        
        textarea { 
            width: 100%; background: var(--bg-input); border: 1px solid var(--border); 
            color: #fff; padding: 12px; margin-bottom: 15px; border-radius: 4px; resize: vertical; font-family: monospace;
        }
        .controls { display: flex; gap: 10px; margin-bottom: 15px; }
        button { 
            background: #45423e; color: white; border: none; padding: 10px; 
            font-weight: bold; cursor: pointer; border-radius: 4px; flex: 1; transition: 0.2s;
        }
        button:hover { background: #5a5752; }
        .btn-primary { background: var(--accent); }
        .btn-primary:hover { background: var(--accent-hover); }
        .btn-danger { background: #b64c4c; }
        .btn-danger:hover { background: #d16c6c; }
    </style>
</head>
<body>

<div class="container">
    <div class="board-wrapper">
        <div id="myBoard"></div>
        <div class="controls" style="margin-top: 15px;">
            <button onclick="board.flip()">🔄 Развернуть</button>
            <button onclick="copyFen()">📋 Скопировать FEN</button>
            <button class="btn-danger" onclick="resetGame()">重 Сброс</button>
        </div>
    </div>

    <div class="panel">
        <h2>Анализ Stockfish</h2>
        
        <div class="eval-container">
            <div class="eval-status" id="statusText">Готов к работе</div>
            <div style="color: var(--text);">Оценка:</div>
            <div class="eval-score" id="scoreText">0.00</div>
            <div style="color: var(--text);">Лучший ход: <span class="eval-bestmove" id="bestMoveText">-</span></div>
        </div>
        
        <label>Вставить FEN / Редактировать позицию:</label>
        <textarea id="fenInput" rows="2" placeholder="Вставьте FEN сюда..."></textarea>
        <button class="btn-primary" onclick="loadFenFromInput()">Загрузить позицию</button>
    </div>
</div>

<script>
    var board = null;
    var game = new Chess();
    var analysisTimer = null;

    // 1. НАСТРОЙКА ДОСКИ С ФИГУРАМИ LICHESS
    var config = {
        draggable: true,
        position: 'start',
        pieceTheme: 'https://lichess1.org/assets/piece/cburnett/{piece}.svg',
        onDragStart: onDragStart,
        onDrop: onDrop,
        onSnapEnd: onSnapEnd
    };
    board = ChessBoard('myBoard', config);
    $('#fenInput').val(game.fen());

    // 2. ЛОГИКА ХОДОВ И ПРАВИЛ
    function onDragStart (source, piece, position, orientation) {
        if (game.game_over()) return false;
        // Разрешаем брать только фигуры того цвета, чей сейчас ход
        if ((game.turn() === 'w' && piece.search(/^b/) !== -1) ||
            (game.turn() === 'b' && piece.search(/^w/) !== -1)) {
            return false;
        }
    }

    function onDrop (source, target) {
        // Проверяем валидность хода
        var move = game.move({
            from: source,
            to: target,
            promotion: 'q' // Авто-превращение в ферзя
        });

        // Если ход запрещен правилами - возвращаем фигуру назад
        if (move === null) return 'snapback';

        // АВТО-АНАЛИЗ: Ход сделан успешно, запускаем анализ
        triggerAnalysis();
    }

    // Обновляем доску (важно для рокировок и взятия на проходе)
    function onSnapEnd () {
        board.position(game.fen());
        $('#fenInput').val(game.fen());
    }

    // 3. АВТОМАТИЧЕСКИЙ АНАЛИЗ НА VPS
    function triggerAnalysis() {
        var currentFen = game.fen();
        $('#statusText').text('⏳ Stockfish думает...').css('color', '#e2b714');
        
        $.post('/analyze', { data: currentFen, depth: 15 }, function(res) {
            if(res.error) {
                $('#statusText').text('❌ Ошибка').css('color', '#ff5252');
            } else {
                $('#statusText').text('✅ Анализ завершен').css('color', '#81b64c');
                $('#scoreText').text(res.evaluation);
                $('#bestMoveText').text(res.best_move);
            }
        }).fail(function() {
            $('#statusText').text('❌ Нет связи с сервером').css('color', '#ff5252');
        });
    }

    // 4. ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ
    function resetGame() {
        game.reset();
        board.start();
        $('#fenInput').val(game.fen());
        $('#scoreText').text('0.00');
        $('#bestMoveText').text('-');
        $('#statusText').text('Начальная позиция');
        triggerAnalysis(); // Анализируем стартовую позицию
    }

    function copyFen() {
        navigator.clipboard.writeText(game.fen());
        alert('FEN скопирован!');
    }

    function loadFenFromInput() {
        var fen = $('#fenInput').val().trim();
        if (game.load(fen)) {
            board.position(game.fen());
            triggerAnalysis();
        } else {
            alert('Некорректный FEN');
        }
    }

    // Запускаем анализ начальной позиции при загрузке страницы
    $(document).ready(function() {
        triggerAnalysis();
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
    depth = int(request.form.get('depth', 15))
    if depth > 20: depth = 20 

    try: 
        board = chess.Board(raw_data)
    except ValueError: 
        return jsonify({"error": "Некорректный FEN"})

    try:
        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
            engine.configure(ENGINE_OPTIONS)
            result = engine.analyse(board, chess.engine.Limit(depth=depth))
            
            score = result["score"].white()
            eval_str = f"M{abs(score.mate())}" if score.is_mate() else f"{score.score() / 100:+.2f}"
            best_move = result.get("pv")[0].uci() if result.get("pv") else "Мат/Пат"
            
            return jsonify({"best_move": best_move, "evaluation": eval_str})
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
