import os
import json
import random
from flask import Flask, request, jsonify
import chess
import chess.engine

app = Flask(__name__)
STOCKFISH_PATH = "/usr/games/stockfish"
ENGINE_OPTIONS = {"Threads": 1, "Hash": 16}

# База данных задач
PUZZLES_DB = [
    {"id": 1, "elo": 850, "fen": "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4", "moves": ["h5f7"], "desc": "Мат в 1 ход"},
    {"id": 2, "elo": 1100, "fen": "r1b1k2r/ppppnppp/2n2q2/2b5/3NP3/2P1B3/PP3PPP/RN1QKB1R w KQkq - 3 7", "moves": ["d4c6", "c5e3", "c6d8"], "desc": "Вскрытый удар"},
    {"id": 3, "elo": 1400, "fen": "2r3k1/p4ppp/1p2p3/3b4/3P4/q3PN2/1Q3PPP/2R3K1 b - - 1 22", "moves": ["c8c1", "b2c1", "a3c1"], "desc": "Слабость первой горизонтали"},
    {"id": 4, "elo": 1650, "fen": "r2q1rk1/ppp2ppp/2n1bn2/8/1b1P4/2N1BN2/PPP1BPPP/R2Q1RK1 w - - 8 10", "moves": ["a2a3", "b4c3", "b2c3"], "desc": "Выигрыш темпа"},
    {"id": 5, "elo": 1900, "fen": "5rk1/pp3ppp/4p3/1b1pP3/1q1P4/1Pr1PN2/P2Q2PP/2R1R1K1 b - - 4 19", "moves": ["f8c8", "c1c3", "b4c3"], "desc": "Борьба за открытую вертикаль"}
]

# База дебютной теории
THEORY_DB = {
    "sicilian": {"name": "Сицилианская защита", "fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6 0 2", "desc": "Самый популярный и агрессивный ответ на 1.e4. Черные сразу борются за центр асимметричным путем."},
    "italian": {"name": "Итальянская партия", "fen": "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3", "desc": "Классический открытый дебют. Белые развивают слона на активную диагональ c4, атакуя пункт f7."},
    "queens_gambit": {"name": "Ферзевый гамбит", "fen": "rnbqkbnr/ppp1pppp/8/3p4/2PP4/8/PP2PPPP/RNBQKBNR b KQkq c3 0 2", "desc": "Белые временно жертвуют фланговую пешку 'c' ради захвата контроля над центром поля."},
    "carokann": {"name": "Защита Каро-Канн", "fen": "rnbqkbnr/pp1ppppp/2p5/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2", "desc": "Прочная оборонительная система черных. Подготовка к ходу d5 без блокировки белопольного слона."}
}

# Имена для симуляции онлайн игроков
BOT_NAMES = ["GrandmasterX", "ChessKnight_99", "DeepMind_Pro", "AlphaPawn", "SnezkaFan", "BlitzCrush", "E4_Master", "TacticsWizard"]

def get_optimal_depth(req_depth):
    if req_depth != "auto":
        return min(max(int(req_depth), 8), 20)
    try:
        load1, _, _ = os.getloadavg()
        cores = os.cpu_count() or 1
        if (load1 / cores) > 0.8: return 11
        elif (load1 / cores) > 0.5: return 13
        return 16
    except Exception:
        return 14

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SnezkaChess | Ультимативная Арена</title>
    
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
        
        * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: var(--bg); color: var(--text); padding: 10px; }
        
        .navbar { display: flex; justify-content: space-between; align-items: center; max-width: 1200px; margin: 0 auto 10px auto; padding: 5px 10px; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; }
        .logo { font-weight: bold; color: var(--text-bright); font-size: 18px; letter-spacing: 0.5px; }
        .logo span { color: var(--accent-light); }
        .global-elo { font-size: 13px; font-weight: bold; background: var(--bg); padding: 4px 10px; border-radius: 4px; border: 1px solid var(--border); }
        
        /* Меню табов */
        .tabs { display: flex; gap: 4px; max-width: 1200px; margin: 0 auto 15px auto; overflow-x: auto; }
        .tab-btn { flex: 1; min-width: 100px; padding: 12px 6px; text-align: center; cursor: pointer; background: var(--surface); border: 1px solid var(--border); font-weight: 600; font-size: 13px; color: var(--text); transition: 0.1s; border-radius: 4px; white-space: nowrap; }
        .tab-btn.active { background: var(--accent-light); color: #fff; border-color: var(--accent-light); }
        
        /* Главный контейнер игры */
        .main-container { display: flex; gap: 15px; max-width: 1200px; margin: 0 auto; align-items: flex-start; flex-wrap: wrap; }
        
        /* Сетка игрового пространства */
        .game-zone { display: flex; flex: 0 0 520px; gap: 10px; width: 100%; max-width: 520px; }
        
        /* Умный Lichess Эвал-Бар */
        .eval-bar-container { width: 20px; height: 480px; background: #fff; border-radius: 3px; overflow: hidden; display: flex; flex-direction: column; position: relative; border: 1px solid var(--border); }
        .eval-black { width: 100%; height: 50%; background: #000; transition: height 0.4s ease; }
        
        /* Игровая доска с часами */
        .board-wrapper { flex: 1; display: flex; flex-direction: column; gap: 6px; }
        
        /* Шахматные часы */
        .chess-clock { display: flex; justify-content: space-between; align-items: center; background: var(--surface); padding: 8px 12px; border-radius: 4px; border: 1px solid var(--border); font-family: monospace; font-size: 18px; font-weight: bold; color: var(--text-bright); }
        .clock-active { background: #3d3a35; border-color: var(--accent-light); }
        .player-info { font-size: 13px; font-family: sans-serif; display: flex; align-items: center; gap: 6px; }
        
        /* Стилизация доски chessboard.js */
        .white-1e1d7 { background-color: var(--board-light); }
        .black-3c85d { background-color: var(--board-dark); }
        .board-b72b1 { border: none !important; border-radius: 4px; box-shadow: 0 5px 15px rgba(0,0,0,0.5); }
        
        /* Lichess маркеры возможных ходов */
        .hint-dot::after { content: ''; position: absolute; width: 26%; height: 26%; background: rgba(20, 85, 30, 0.4); border-radius: 50%; top: 37%; left: 37%; pointer-events: none; }
        .hint-capture::after { content: ''; position: absolute; width: 80%; height: 80%; border: 5px solid rgba(20, 85, 30, 0.4); border-radius: 50%; top: 10%; left: 10%; pointer-events: none; }
        
        /* Правая функциональная панель */
        .panel-zone { flex: 1; min-width: 300px; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 15px; display: flex; flex-direction: column; min-height: 540px; }
        
        /* Инфо коробки */
        .eval-box { background: var(--bg); border-radius: 4px; padding: 12px; border-left: 4px solid var(--accent-light); margin-bottom: 15px; }
        .score-val { font-size: 30px; font-weight: bold; color: var(--text-bright); font-family: monospace; }
        
        /* Кнопки управления */
        .btn-group { display: flex; gap: 6px; margin-top: 8px; width: 100%; flex-wrap: wrap; }
        .btn { background: var(--surface-hover); color: var(--text-bright); border: 1px solid var(--border); padding: 10px 14px; border-radius: 4px; font-weight: 600; font-size: 13px; cursor: pointer; text-align: center; flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 4px; transition: 0.1s; }
        .btn:hover { background: #45423d; }
        .btn-accent { background: var(--accent); border-color: var(--accent); }
        .btn-accent:hover { background: var(--accent-light); }
        .btn-danger { color: #ff6b6b; }
        
        /* Стили радио и селектов контролей */
        .control-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 12px; }
        .time-card { background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 8px; text-align: center; cursor: pointer; transition: 0.1s; }
        .time-card:hover { border-color: #666; }
        .time-card.active { border-color: var(--accent-light); background: rgba(98, 153, 36, 0.1); }
        .time-card h4 { font-size: 13px; color: var(--text-bright); }
        .time-card p { font-size: 11px; color: #777; }
        
        select, textarea { width: 100%; background: var(--bg); border: 1px solid var(--border); color: #fff; padding: 8px; border-radius: 4px; margin-top: 4px; font-size: 13px; outline: none; }
        label { font-size: 12px; color: var(--text); font-weight: 600; }
        
        /* Карточки теории */
        .theory-list { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; max-height: 250px; overflow-y: auto; }
        .theory-item { background: var(--bg); padding: 10px; border-radius: 4px; cursor: pointer; border: 1px solid var(--border); transition: 0.1s; }
        .theory-item:hover { border-color: var(--accent-light); }
        
        /* Очередь поиска */
        .lobby-screen { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px 10px; text-align: center; }
        .spinner { width: 40px; height: 40px; border: 4px solid rgba(255,255,255,0.1); border-top-color: var(--accent-light); border-radius: 50%; animation: spin 1s linear infinite; margin-bottom: 15px; }
        
        @keyframes spin { to { transform: rotate(360deg); } }
        @media (max-width: 880px) {
            .game-zone { flex: 0 0 100%; max-width: 100%; }
            .eval-bar-container { height: 320px; width: 14px; }
            .panel-zone { min-height: auto; }
        }
    </style>
</head>
<body>

<div class="navbar">
    <div class="logo">Snezka<span>Chess</span></div>
    <div class="global-elo">⚔️ Твой ELO: <span id="playerEloUI">1500</span></div>
</div>

<div class="tabs">
    <div class="tab-btn active" data-tab="sandbox">🔬 Анализ партии</div>
    <div class="tab-btn" data-tab="arena">⚡ Онлайн Арена</div>
    <div class="tab-btn" data-tab="puzzles">🧩 Задачи ЭЛО</div>
    <div class="tab-btn" data-tab="theory">📚 Дебютная Теория</div>
</div>

<div class="main-container">
    <div class="game-zone">
        <div class="eval-bar-container">
            <div class="eval-black" id="evalBar"></div>
        </div>
        
        <div class="board-wrapper">
            <div class="chess-clock" id="clockTop">
                <div class="player-info">👤 <span id="nameTop">Соперник</span> <span style="opacity:0.6" id="eloTop"></span></div>
                <div id="timeTop">--:--</div>
            </div>
            
            <div id="mainBoard"></div>
            
            <div class="chess-clock" id="clockBottom">
                <div class="player-info">👑 Ты (Белые)</div>
                <div id="timeBottom">--:--</div>
            </div>
            
            <div class="btn-group">
                <button class="btn" id="btnFlip">🔄 Разворот доски</button>
                <button class="btn btn-danger" id="btnReset">↩️ Сброс</button>
            </div>
        </div>
    </div>

    <div class="panel-zone">
        <div class="tab-pane" id="pane-sandbox">
            <div class="eval-box">
                <span id="moveBadgeUI" style="display:inline-block; padding:3px 8px; border-radius:3px; color:#fff; background:#555; font-size:11px; font-weight:bold; margin-bottom:5px;">СТАРТ</span>
                <div class="score-val" id="scoreUI">0.00</div>
                <div style="font-size:13px; margin-top:6px;">Рекомендуется: <b id="bestMoveUI" style="color:var(--accent-light)">-</b> <span id="depthUI" style="color:#666; font-size:11px;"></span></div>
            </div>
            
            <label>Глубина Stockfish:</label>
            <select id="depthSelect">
                <option value="auto" selected>⚡ Динамическая (Нагрузка VPS)</option>
                <option value="12">Быстрая (Глубина 12)</option>
                <option value="16">Стандарт (Глубина 16)</option>
                <option value="20">Глубокая (Глубина 20)</option>
            </select>
            
            <label style="margin-top:12px; display:block;">Строка FEN:</label>
            <textarea id="fenInput" rows="2"></textarea>
            <button class="btn btn-accent" style="margin-top:8px; width:100%;" id="btnLoadFen">Загрузить позицию</button>
        </div>

        <div class="tab-pane" id="pane-arena" style="display:none;">
            <div id="arenaSetup">
                <h3 style="color:#fff; margin-bottom:10px; font-size:15px;">Выбор контроля времени:</h3>
                <div class="control-grid">
                    <div class="time-card active" data-mode="bullet" data-time="60" data-inc="0">
                        <h4>Bullet 🚀</h4>
                        <p>1 мин + 0 сек</p>
                    </div>
                    <div class="time-card" data-mode="blitz" data-time="180" data-inc="2">
                        <h4>Blitz ⚡</h4>
                        <p>3 мин + 2 сек</p>
                    </div>
                    <div class="time-card" data-mode="rapid" data-time="600" data-inc="0">
                        <h4>Rapid ⏱️</h4>
                        <p>10 мин + 0 сек</p>
                    </div>
                    <div class="time-card" data-mode="classical" data-time="1800" data-inc="0">
                        <h4>Classical ⏳</h4>
                        <p>30 мин + 0 сек</p>
                    </div>
                </div>
                <button class="btn btn-accent" style="width:100%; padding:14px;" id="btnFindMatch">🔎 Найти рейтингового соперника</button>
            </div>
            
            <div id="arenaLobby" style="display:none;" class="lobby-screen">
                <div class="spinner"></div>
                <h4 style="color:#fff;" id="lobbyStatusTxt">Поиск оппонента твоего уровня...</h4>
                <p style="font-size:12px; margin-top:5px;">Ищем близкий ELO в глобальной базе...</p>
            </div>
            
            <div id="arenaActive" style="display:none;">
                <div style="background:var(--bg); padding:10px; border-radius:4px; text-align:center; font-weight:bold; color:var(--accent-light);" id="arenaGameMsg">Игра началась! Твой ход.</div>
                <p style="font-size:12px; margin-top:10px; text-align:center;">Выход из вкладки или сброс засчитает поражение!</p>
            </div>
        </div>

        <div class="tab-pane" id="pane-puzzles" style="display:none;">
            <h3 style="color:#fff; font-size:15px; margin-bottom:5px;">Тактический тренажер</h3>
            <div style="background:var(--bg); padding:10px; border-radius:4px; font-size:13px;" id="puzTaskDesc">-</div>
            <div id="puzStatus" style="font-size:20px; font-weight:bold; margin:30px 0; text-align:center; color:var(--text-bright);">-</div>
            <button class="btn btn-accent" style="width:100%;" id="btnNextPuzzle">Следующая задача ⏭️</button>
        </div>

        <div class="tab-pane" id="pane-theory" style="display:none;">
            <h3 style="color:#fff; font-size:15px; margin-bottom:5px;">Популярные дебюты мира</h3>
            <p style="font-size:12px;">Изучи теорию и начни разыгрывать позицию прямо на доске.</p>
            <div class="theory-list" id="theoryListContainer"></div>
            <div style="margin-top:12px; background:var(--bg); padding:12px; border-radius:4px; font-size:13px; display:none;" id="theoryDescBox"></div>
        </div>
    </div>
</div>

<script>
    var board = null;
    var game = new Chess();
    var CURRENT_MODE = 'sandbox';
    var selectedSquare = null;
    
    // Аудиосистема Web Audio API (Синтезирует сочные звуки ходов и взятий)
    var audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    function playSound(type) {
        if (audioCtx.state === 'suspended') audioCtx.resume();
        var osc = audioCtx.createOscillator();
        var gain = audioCtx.createGain();
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        if (type === 'capture') {
            osc.type = 'triangle'; osc.frequency.setValueAtTime(180, audioCtx.currentTime);
            osc.frequency.exponentialRampToValueAtTime(70, audioCtx.currentTime + 0.12);
            gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
            gain.gain.linearRampToValueAtTime(0.01, audioCtx.currentTime + 0.12);
            osc.start(); osc.stop(audioCtx.currentTime + 0.12);
        } else {
            osc.type = 'sine'; osc.frequency.setValueAtTime(320, audioCtx.currentTime);
            osc.frequency.exponentialRampToValueAtTime(240, audioCtx.currentTime + 0.08);
            gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
            gain.gain.linearRampToValueAtTime(0.01, audioCtx.currentTime + 0.08);
            osc.start(); osc.stop(audioCtx.currentTime + 0.08);
        }
    }

    // Состояние игрока
    var myElo = parseInt(localStorage.getItem('snezka_elo_v1') || '1500');
    
    // Переменные часов
    var timers = { w: 0, b: 0, inc: 0 };
    var clockInterval = null;
    var arenaOpponent = null;

    // Состояние задач
    var activePuzzle = null;
    var puzzleProgress = 0;

    $(document).ready(function() {
        $('#playerEloUI').text(myElo);

        // Конфигурация доски
        board = ChessBoard('mainBoard', {
            draggable: true,
            position: 'start',
            pieceTheme: 'https://lichess1.org/assets/piece/cburnett/{piece}.svg',
            onDragStart: onDragStart,
            onDrop: onDrop,
            onSnapEnd: onSnapEnd
        });

        // Навешиваем слушатели событий (Уничтожили inline-onclick ошибки)
        $('.tab-btn').on('click', function() {
            var tab = $(this).data('tab');
            $('.tab-btn').removeClass('active');
            $(this).addClass('active');
            $('.tab-pane').hide();
            $('#pane-' + tab).show();
            switchTabMode(tab);
        });

        $('#btnFlip').on('click', function() {
            board.orientation(board.orientation() === 'white' ? 'black' : 'white');
        });

        $('#btnReset').on('click', function() { switchTabMode(CURRENT_MODE); });
        $('#btnLoadFen').on('click', loadManualFen);
        $('#btnNextPuzzle').on('click', getNewPuzzle);
        
        $('.time-card').on('click', function() {
            $('.time-card').removeClass('active');
            $(this).addClass('active');
        });

        $('#btnFindMatch').on('click', startMatchmaking);

        // Клики по клеткам (для ходов в один клик)
        $('#mainBoard').on('click', '.square-55d63', function() {
            handleSquareClick($(this).attr('data-square'));
        });

        initTheoryTab();
        switchTabMode('sandbox');
    });

    function switchTabMode(mode) {
        CURRENT_MODE = mode;
        clearInterval(clockInterval);
        game.reset();
        board.position('start');
        board.orientation('white');
        clearHighlights();
        updateClocksUI(false);
        setEvalBar(0);

        $('#arenaSetup').show(); $('#arenaLobby').hide(); $('#arenaActive').hide();
        $('#nameTop').text('Соперник'); $('#eloTop').text('');
        $('#timeTop').text('--:--'); $('#timeBottom').text('--:--');

        if (mode === 'sandbox') {
            $('#fenInput').val(game.fen());
            triggerEngineAnalysis(game.fen(), game.fen());
        } else if (mode === 'puzzles') {
            getNewPuzzle();
        }
    }

    // Обработка клик-ходов
    function handleSquareClick(sq) {
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
