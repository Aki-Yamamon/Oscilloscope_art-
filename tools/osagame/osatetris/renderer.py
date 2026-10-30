import numpy as np
from osagame.ui import rect_polyline, text_to_polylines
from osagame.osatetris.logic import get_rotated_blocks

CELL_SIZE = 10
FIELD_W = 10 * CELL_SIZE
FIELD_H = 20 * CELL_SIZE
FIELD_X = (255 - FIELD_W) / 2  # 真ん中へ配置
FIELD_Y = (255 - FIELD_H) / 2

def draw_mino(cx, cy, shape, rot, offset_x, offset_y, size=CELL_SIZE):
    blocks = get_rotated_blocks(shape, rot)
    polys = []
    for bx, by in blocks:
        x = offset_x + (cx + bx) * size
        y = offset_y + (cy + by) * size
        polys.append(rect_polyline(x, y, size, size))
    return polys

def render_tetris(logic):
    polys = []
    
    # 枠線
    polys.append(rect_polyline(FIELD_X, FIELD_Y, FIELD_W, FIELD_H))

    # 配置済みブロック
    for y in range(logic.height):
        for x in range(logic.width):
            if logic.board[y][x]:
                polys.append(rect_polyline(FIELD_X + x * CELL_SIZE, FIELD_Y + y * CELL_SIZE, CELL_SIZE, CELL_SIZE))
    
    if not logic.game_over and logic.current_shape:
        # 操作中のミノ
        polys.extend(draw_mino(logic.current_x, logic.current_y, logic.current_shape, logic.current_rot, FIELD_X, FIELD_Y))
        
        # 落下予測のゴーストブロック (ポリゴン節約のため少し小さく描画)
        ghost_y = logic.current_y
        while not logic._is_collision(logic.current_x, ghost_y - 1, logic.current_rot):
            ghost_y -= 1
        g_polys = draw_mino(logic.current_x, ghost_y, logic.current_shape, logic.current_rot, FIELD_X, FIELD_Y, size=CELL_SIZE-2)
        for p in g_polys:
            p[:, 0] += 1
            p[:, 1] += 1
        polys.extend(g_polys)

    # UI: 左上 HOLD
    hx, hy = 15, 210
    polys.extend(text_to_polylines("HOLD", hx, hy, 10))
    polys.append(rect_polyline(hx, hy - 40, 40, 35))
    if logic.hold_mino:
        polys.extend(draw_mino(1, 0, logic.hold_mino, 0, hx, hy - 30, size=CELL_SIZE))
        
    # UI: HOLD下 SCORE
    sx, sy = 15, 120
    polys.extend(text_to_polylines("SCORE", sx, sy, 10))
    polys.extend(text_to_polylines(str(logic.score), sx, sy - 15, 10))
    
    # UI: 右側 NEXT5
    nx, ny = 190, 210
    polys.extend(text_to_polylines("NEXT", nx, ny, 10))
    for i, shape in enumerate(logic.next_minos):
        y = ny - 25 - i * 35
        polys.extend(draw_mino(0, 0, shape, 0, nx + 10, y, size=8))

    if logic.game_over:
        polys.extend(text_to_polylines("GAME OVER", FIELD_X - 10, FIELD_Y + FIELD_H / 2, 14))
        polys.extend(text_to_polylines("PRESS ESC", FIELD_X, FIELD_Y + FIELD_H / 2 - 20, 10))

    return polys