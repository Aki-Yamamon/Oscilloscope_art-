import numpy as np
from osagame.ui import rect_polyline, text_to_polylines
from osagame.osatetris.logic import get_rotated_blocks

CELL_SIZE = 10
FIELD_W = 10 * CELL_SIZE
FIELD_H = 20 * CELL_SIZE
FIELD_X = (255 - FIELD_W) / 2
FIELD_Y = (255 - FIELD_H) / 2

def draw_mino(cx, cy, shape, rot, offset_x, offset_y, size=CELL_SIZE):
    blocks = get_rotated_blocks(shape, rot)
    polys = []
    for bx, by in blocks:
        x = offset_x + (cx + bx) * size
        y = offset_y + (cy + by) * size
        polys.append(rect_polyline(x, y, size, size))
        polys.append(np.array([(x, y), (x + size, y + size)], dtype=np.float64))
    return polys

def render_tetris(logic):
    polys = []
    
    # 枠線
    polys.append(rect_polyline(FIELD_X, FIELD_Y, FIELD_W, FIELD_H))

    # 配置済みブロック
    for y in range(logic.height):
        for x in range(logic.width):
            if logic.board[y][x]:
                px = FIELD_X + x * CELL_SIZE
                py = FIELD_Y + y * CELL_SIZE
                polys.append(rect_polyline(px, py, CELL_SIZE, CELL_SIZE))
                polys.append(np.array([(px, py), (px + CELL_SIZE, py + CELL_SIZE)], dtype=np.float64))
    
    if not logic.game_over and logic.current_shape:
        polys.extend(draw_mino(logic.current_x, logic.current_y, logic.current_shape, logic.current_rot, FIELD_X, FIELD_Y))

    # UI: 左側 SCORE (元の位置 sx=15 に戻しました)
    sx, sy = 15, 120
    polys.extend(text_to_polylines(str(logic.score), sx, sy, 10))
    
    # UI: 右側 NEXT (上位3つまで)
    nx, ny = 190, 210
    polys.extend(text_to_polylines("NEXT", nx, ny, 10))
    for i, shape in enumerate(logic.next_minos[:3]): 
        y = ny - 25 - i * 35
        polys.extend(draw_mino(0, 0, shape, 0, nx + 10, y, size=8))

    if logic.game_over:
        polys.extend(text_to_polylines("GAME OVER", FIELD_X - 10, FIELD_Y + FIELD_H / 2, 14))
        polys.extend(text_to_polylines("PRESS ENTER", FIELD_X, FIELD_Y + FIELD_H / 2 - 20, 10))

    return polys