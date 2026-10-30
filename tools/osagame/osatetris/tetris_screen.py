import numpy as np
from pathlib import Path
from osagame.screens import Screen
from osagame.osatetris.logic import TetrisLogic
from osagame.osatetris.renderer import render_tetris
from osagame.app import SOURCE_DIR

TETRIS_SOUND_DIR = SOURCE_DIR / "tetrissounds"

class TetrisScreen(Screen):
    def __init__(self, back="game"):
        self.back = back
        self.logic = None
        
        # 音声ファイルのパス
        self.wav_bgm = TETRIS_SOUND_DIR / "tetris_bgm.wav"
        self.wav_harddrop = TETRIS_SOUND_DIR / "tetris_harddrop.wav"
        self.wav_rotate = TETRIS_SOUND_DIR / "tetris_rotate.wav"
        self.wav_lock = TETRIS_SOUND_DIR / "tetris_lock.wav"
        self.wav_clear = TETRIS_SOUND_DIR / "tetris_clear.wav"
        self.wav_move = TETRIS_SOUND_DIR / "tetris_move.wav"
        self.wav_spin = TETRIS_SOUND_DIR / "tetris_spin.wav"

    def on_enter(self, app):
        # 画面に入るときにゲームを初期化
        self.logic = TetrisLogic()
        
        # BGM再生
        if self.wav_bgm.is_file():
            app.audio.play(self.wav_bgm, loops=-1)
        else:
            print(f"[warning] Audio file not found: {self.wav_bgm}")

    def handle(self, app, key, ch=None):

        if key == "esc":
            app.audio.stop()
            app.goto(self.back) # メニューに戻る
            return
            
        if self.logic.game_over:
            if key == "enter":
                app.audio.stop()
                # リトライではなく、名前入力画面へスコアを渡して遷移
                app.screens["name_entry"].setup("tetris", self.logic.score)
                app.goto("name_entry")
            return

        if key == "left":
            self.logic.move(-1, 0)
        elif key == "right":
            self.logic.move(1, 0)
            
        elif key == "z":
            self.logic.rotate(-1)
        elif key == "x":
            self.logic.rotate(1)
            
        elif key == "down":
            if self.logic.move(0, -1):
                self.logic.score += 1
        elif key == "up":
            self.logic.hard_drop()
            
        elif key == "a" or key == "d":
            self.logic.hold()

    def polylines(self, app, dt):
        if not self.logic.game_over:
            self.logic.update(dt)
            
            # SEの再生処理 (優先度の低いものからチェック)
            if self.logic.event_move:
                self.logic.event_move = False
                if self.wav_move.is_file():
                    app.audio.play_se(self.wav_move)
                    
            if self.logic.event_rotate:
                self.logic.event_rotate = False
                if self.wav_rotate.is_file():
                    app.audio.play_se(self.wav_rotate)
                    
            # 設置関連のSEは排他的に鳴らす
            if self.logic.event_clear:
                self.logic.event_clear = False
                if self.wav_clear.is_file():
                    app.audio.play_se(self.wav_clear)
            elif self.logic.event_harddrop:
                self.logic.event_harddrop = False
                if self.wav_harddrop.is_file():
                    app.audio.play_se(self.wav_harddrop)
            elif self.logic.event_spin:
                self.logic.event_spin = False
                if self.wav_spin.is_file():
                    app.audio.play_se(self.wav_spin)
            elif self.logic.event_lock:
                self.logic.event_lock = False
                if self.wav_lock.is_file():
                    app.audio.play_se(self.wav_lock)

        return render_tetris(self.logic)