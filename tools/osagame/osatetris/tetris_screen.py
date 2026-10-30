import numpy as np
from osagame.screens import Screen
from osagame.osatetris.logic import TetrisLogic
from osagame.osatetris.renderer import render_tetris

class TetrisScreen(Screen):
    def __init__(self, back="game"):
        self.back = back
        self.logic = None

    def on_enter(self, app):
        # 画面に入るときにゲームを初期化
        self.logic = TetrisLogic()

    def handle(self, app, key, ch=None):
        if key == "esc":
            app.goto(self.back) # メニューに戻る
        if self.logic.game_over:
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
            self.logic.move(0, -1)
            self.logic.score += 1
        elif key == "up":
            self.logic.hard_drop()
            
        elif key == "a" or key == "d":
            self.logic.hold()

    def polylines(self, app, dt):
        self.logic.update(dt)
        return render_tetris(self.logic)