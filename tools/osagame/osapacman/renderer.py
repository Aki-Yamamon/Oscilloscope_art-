import numpy as np
import math
from osagame.ui import rect_polyline, text_to_polylines

CELL = 11
OFFSET_X = (255 - 19 * CELL) / 2
OFFSET_Y = 240

def draw_circle(x, y, r, start_ang=0, end_ang=2*math.pi, steps=8):
    pts = []
    pts.append((x, y))
    for i in range(steps + 1):
        ang = start_ang + (end_ang - start_ang) * i / steps
        pts.append((x + math.cos(ang) * r, y + math.sin(ang) * r))
    pts.append((x, y))
    return np.array(pts, dtype=np.float64)

def draw_ghost(x, y, size):
    pts = []
    pts.append((x + size, y - size))
    steps = 4
    for i in range(steps + 1):
        ang = i * (math.pi / steps)
        pts.append((x + math.cos(ang) * size, y + math.sin(ang) * size))
    pts.append((x - size, y - size))
    pts.append((x + size, y - size))
    return np.array(pts, dtype=np.float64)

def render_pacman_scene(logic, time_t, state="play"):
    polys = []
    
    # 画面上部UI (SCORE, STAGE, LIFE)
    polys.extend(text_to_polylines(f"SCORE {logic.score}", 5, 245, 10))
    polys.extend(text_to_polylines(f"STAGE {logic.stage}", 100, 245, 10))
    polys.extend(text_to_polylines(f"LIFE {logic.lives}", 185, 245, 10))

    # エサの描画
    for y in range(logic.height):
        for x in range(logic.width):
            val = logic.grid[y][x]
            px = OFFSET_X + x * CELL + CELL/2
            py = OFFSET_Y - y * CELL - CELL/2
            
            if val == 2:
                polys.append(np.array([(px-1, py), (px+1, py)], dtype=np.float64))
            elif val == 3:
                polys.append(np.array([(px-3, py), (px+3, py)], dtype=np.float64))
                polys.append(np.array([(px, py-3), (px, py+3)], dtype=np.float64))

    # 壁のワイヤーフレーム描画
    for y in range(logic.height):
        x = 0
        while x < logic.width:
            if logic.grid[y][x] == 1:
                start_x = x
                while x < logic.width and logic.grid[y][x] == 1:
                    x += 1
                end_x = x - 1
                if start_x != end_x:
                    px1 = OFFSET_X + start_x * CELL + CELL/2
                    px2 = OFFSET_X + end_x * CELL + CELL/2
                    py = OFFSET_Y - y * CELL - CELL/2
                    polys.append(np.array([(px1, py), (px2, py)], dtype=np.float64))
            else:
                x += 1

    for x in range(logic.width):
        y = 0
        while y < logic.height:
            if logic.grid[y][x] == 1:
                start_y = y
                while y < logic.height and logic.grid[y][x] == 1:
                    y += 1
                end_y = y - 1
                if start_y != end_y:
                    px = OFFSET_X + x * CELL + CELL/2
                    py1 = OFFSET_Y - start_y * CELL - CELL/2
                    py2 = OFFSET_Y - end_y * CELL - CELL/2
                    polys.append(np.array([(px, py1), (px, py2)], dtype=np.float64))
            else:
                y += 1

    def get_pos(ent):
        dx, dy = 0, 0
        if ent.dir == 'up': dy = -1
        elif ent.dir == 'down': dy = 1
        elif ent.dir == 'left': dx = -1
        elif ent.dir == 'right': dx = 1
        return OFFSET_X + (ent.x + dx * ent.move_frac) * CELL + CELL/2, \
               OFFSET_Y - (ent.y + dy * ent.move_frac) * CELL - CELL/2

    # パックマンの描画 (死亡時は高速で点滅させる)
    if state != "dead" or (state == "dead" and int(time_t * 15) % 2 == 0):
        px, py = get_pos(logic.pacman)
        mouth_open = (math.sin(time_t * 15) + 1) / 2 if state == "play" else 1.0 # 死んでいる時は口を開いたまま
        mouth_angle = mouth_open * (math.pi / 4)
        
        base_ang = 0
        if logic.pacman.dir == 'up': base_ang = math.pi/2
        elif logic.pacman.dir == 'down': base_ang = -math.pi/2
        elif logic.pacman.dir == 'left': base_ang = math.pi
        elif logic.pacman.dir == 'right': base_ang = 0
        
        polys.append(draw_circle(px, py, CELL/2 - 1.5, base_ang + mouth_angle, base_ang + 2*math.pi - mouth_angle))

    # ゴーストの描画 (ゲームオーバー時・死亡時は非表示)
    if state != "dead" and state != "gameover":
        for g in logic.ghosts:
            gx, gy = get_pos(g)
            g_poly = draw_ghost(gx, gy, CELL/2 - 1.5)
            if logic.power_mode:
                shake = math.sin(time_t * 30) * 1.5
                g_poly[:, 0] += shake
            polys.append(g_poly)

    # 状態テキスト (CLEARテキストは廃止)
    if state == "start":
        polys.extend(text_to_polylines("READY!", 100, 120, 14))
    elif state == "gameover":
        polys.extend(text_to_polylines("GAME OVER", 80, 120, 14))

    return polys