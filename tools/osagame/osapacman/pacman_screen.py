import numpy as np
from pathlib import Path
from osagame.screens import Screen
from osagame.osapacman.logic import PacmanLogic
from osagame.osapacman.renderer import render_pacman_scene
from osagame.app import SOURCE_DIR

PACSOUNDS_DIR = SOURCE_DIR / "pacsounds"

class PacmanScreen(Screen):
    def __init__(self, back="game"):
        self.back = back
        self.logic = None
        self.time_t = 0.0
        
        self.wav_start = PACSOUNDS_DIR / "pacman_start.wav"
        self.wav_siren = PACSOUNDS_DIR / "pacman_siren.wav"
        self.wav_fright = PACSOUNDS_DIR / "pacman_fright.wav"
        self.wav_chomp = PACSOUNDS_DIR / "pacman_chomp.wav"
        self.wav_eatghost = PACSOUNDS_DIR / "pacman_eatghost.wav"
        self.wav_death = PACSOUNDS_DIR / "pacman_death.wav" # 死亡時SE
        
        self.is_playing_power = False
        self.state = "start"
        self.state_timer = 0.0

    def on_enter(self, app):
        self.logic = PacmanLogic()
        self.time_t = 0.0
        self._start_stage(app)

    def _start_stage(self, app):
        self.is_playing_power = False
        self.state = "start"
        self.state_timer = 4.2  # スタートメロディの長さ（約4秒）
        self._play_bgm(app, self.wav_start, loops=0) 

    def _play_bgm(self, app, wav_path, loops=-1):
        if wav_path.is_file():
            app.audio.play(wav_path, loops=loops)
        else:
            print(f"[warning] Audio file not found: {wav_path}")

    def handle(self, app, key, ch=None):
        if key == "esc":
            app.audio.stop()
            app.goto(self.back)
            return
            
        if self.state == "gameover":
            if key == "enter":
                # リトライではなく、名前入力画面へスコアとステージ数を渡して遷移
                app.screens["name_entry"].setup("pacman", self.logic.score, str(self.logic.stage))
                app.goto("name_entry")
            return
        
        if self.state == "play":
            if key == "up":
                self.logic.pacman.next_dir = 'up'
            elif key == "down":
                self.logic.pacman.next_dir = 'down'
            elif key == "left":
                self.logic.pacman.next_dir = 'left'
            elif key == "right":
                self.logic.pacman.next_dir = 'right'

    def polylines(self, app, dt):
        self.time_t += dt
        
        if self.state == "start":
            self.state_timer -= dt
            if self.state_timer <= 0:
                self.state = "play"
                self._play_bgm(app, self.wav_siren)
                
        elif self.state == "dead":
            self.state_timer -= dt
            if self.state_timer <= 0:
                if self.logic.lives > 0:
                    self.logic.reset_entities()
                    self._start_stage(app) # 残機があればリスタート
                else:
                    self.logic.game_over = True
                    self.state = "gameover"

        elif self.state == "clear":
            self.state_timer -= dt
            if self.state_timer <= 0:
                self.logic.stage += 1
                self.logic._load_map() # 新しいステージのマップを読み込み
                self._start_stage(app)
                
        elif self.state == "play":
            self.logic.update(dt)
            
            # イベント検知
            if self.logic.event_death:
                self.logic.event_death = False
                self.logic.lives -= 1
                self.state = "dead"
                self.state_timer = 2.5 # 死亡待機時間
                app.audio.stop()
                if self.wav_death.is_file():
                    app.audio.play_se(self.wav_death)
                    
            elif self.logic.event_clear:
                self.logic.event_clear = False
                self.state = "clear"
                self.state_timer = 2.0 # クリア待機時間は文字を出さずに静止
                app.audio.stop()
                
            else:
                # 効果音の再生
                if self.logic.event_chomp:
                    if self.wav_chomp.is_file():
                        app.audio.play_se(self.wav_chomp)
                    self.logic.event_chomp = False
                    
                if self.logic.event_eatghost:
                    if self.wav_eatghost.is_file():
                        app.audio.play_se(self.wav_eatghost)
                    self.logic.event_eatghost = False
                
                # BGMの切り替え
                if self.logic.power_mode and not self.is_playing_power:
                    self.is_playing_power = True
                    self._play_bgm(app, self.wav_fright)
                elif not self.logic.power_mode and self.is_playing_power:
                    self.is_playing_power = False
                    self._play_bgm(app, self.wav_siren)

        return render_pacman_scene(self.logic, self.time_t, self.state)