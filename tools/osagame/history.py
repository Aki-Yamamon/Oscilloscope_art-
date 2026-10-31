import csv
from pathlib import Path
import numpy as np

from osagame.screens import Screen
from osagame.ui import TextBox, text_to_polylines, center_x

# 保存先ディレクトリ (tools/osagame/gamehistory)
HISTORY_DIR = Path(__file__).resolve().parent / "gamehistory"

def save_score(game_name: str, name: str, score: int, extra: str = ""):
    HISTORY_DIR.mkdir(exist_ok=True)
    csv_path = HISTORY_DIR / f"{game_name.lower()}.csv"
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([name, score, extra])

def load_scores(game_name: str):
    csv_path = HISTORY_DIR / f"{game_name.lower()}.csv"
    if not csv_path.exists():
        return []
    scores = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 2:
                extra = row[2] if len(row) > 2 else ""
                try:
                    score = int(row[1])
                    scores.append((row[0], score, extra))
                except ValueError:
                    pass
    # スコアの降順にソート
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores

class NameEntryScreen(Screen):
    """ゲームオーバー時の名前入力画面"""
    def __init__(self, back="game"):
        self.back = back
        self.game_name = ""
        self.score = 0
        self.extra = ""
        self.msg = TextBox(16, 120, 224, 84, size=11, cps=30.0)
        self.inp = TextBox(16, 50, 224, 40, input_mode=True, size=14, max_len=8)
        
    def setup(self, game_name, score, extra=""):
        self.game_name = game_name
        self.score = score
        self.extra = extra

    def on_enter(self, app):
        self.inp.set_text("", typewriter=False)
        self.msg.set_text(f"GAME OVER!\nSCORE: {self.score}\nPLEASE ENTER NICKNAME\n(AND PRESS ENTER)")

    def handle(self, app, key, ch=None):
        if key == "esc":
            app.goto(self.back)
        elif key == "char" and ch:
            self.inp.append(ch)
        elif key == "backspace":
            self.inp.backspace()
        elif key == "enter":
            name = self.inp.text.strip()
            if name: # 空白のみ、または未入力の場合は進めない
                save_score(self.game_name, name, self.score, self.extra)
                app.screens["leaderboard"].setup(self.game_name)
                app.goto("leaderboard")

    def polylines(self, app, dt):
        self.msg.update(dt)
        self.inp.update(dt)
        return self.msg.polylines() + self.inp.polylines()

class LeaderboardScreen(Screen):
    """リーダーボード（ランキング）閲覧画面"""
    def __init__(self, back="leaderboard_menu"):
        self.back = back
        self.scores = []
        self.game_name = ""
        self.scroll = 0

    def setup(self, game_name):
        self.game_name = game_name
        self.scores = load_scores(game_name)
        self.scroll = 0

    def handle(self, app, key, ch=None):
        if key in ("esc", "enter"):
            app.goto(self.back)
        elif key == "up":
            self.scroll = max(0, self.scroll - 1)
        elif key == "down":
            max_scroll = max(0, len(self.scores) - 5)
            self.scroll = min(max_scroll, self.scroll + 1)

    def polylines(self, app, dt):
        polys = []
        title = f"{self.game_name.upper()} RANKING"
        polys.extend(text_to_polylines(title, center_x(title, 14), 220, 14))
        
        if not self.scores:
            polys.extend(text_to_polylines("NO RECORDS", center_x("NO RECORDS", 12), 150, 12))
        else:
            for i in range(5):
                idx = self.scroll + i
                if idx < len(self.scores):
                    name, score, extra = self.scores[idx]
                    y = 170 - i * 30
                    polys.extend(text_to_polylines(str(idx+1), 10, y, 10))
                    polys.extend(text_to_polylines(name[:8], 40, y, 10))
                    polys.extend(text_to_polylines(str(score), 130, y, 10))
                    if extra:
                        polys.extend(text_to_polylines(f"ST{extra}", 200, y, 10))
        
        hint = "UP/DOWN:SCROLL  ESC:BACK"
        polys.extend(text_to_polylines(hint, center_x(hint, 8), 15, 8))
        return polys