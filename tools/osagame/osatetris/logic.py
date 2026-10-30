import random

# SRS (Super Rotation System) Wall kick data
# (dx, dy) 
KICK_JLSTZ = {
    (0, 1): [(0,0), (-1,0), (-1, 1), (0,-2), (-1,-2)],
    (1, 0): [(0,0), ( 1,0), ( 1,-1), (0, 2), ( 1, 2)],
    (1, 2): [(0,0), ( 1,0), ( 1,-1), (0, 2), ( 1, 2)],
    (2, 1): [(0,0), (-1,0), (-1, 1), (0,-2), (-1,-2)],
    (2, 3): [(0,0), ( 1,0), ( 1, 1), (0,-2), ( 1,-2)],
    (3, 2): [(0,0), (-1,0), (-1,-1), (0, 2), (-1, 2)],
    (3, 0): [(0,0), (-1,0), (-1,-1), (0, 2), (-1, 2)],
    (0, 3): [(0,0), ( 1,0), ( 1, 1), (0,-2), ( 1,-2)],
}
KICK_I = {
    (0, 1): [(0,0), (-2,0), ( 1,0), (-2,-1), ( 1, 2)],
    (1, 0): [(0,0), ( 2,0), (-1,0), ( 2, 1), (-1,-2)],
    (1, 2): [(0,0), (-1,0), ( 2,0), (-1, 2), ( 2,-1)],
    (2, 1): [(0,0), ( 1,0), (-2,0), ( 1,-2), (-2, 1)],
    (2, 3): [(0,0), ( 2,0), (-1,0), ( 2, 1), (-1,-2)],
    (3, 2): [(0,0), (-2,0), ( 1,0), (-2,-1), ( 1, 2)],
    (3, 0): [(0,0), ( 1,0), (-2,0), ( 1,-2), (-2, 1)],
    (0, 3): [(0,0), (-1,0), ( 2,0), (-1, 2), ( 2,-1)],
}

MINOS = {
    'T': [(0,1), (-1,0), (0,0), (1,0)],
    'J': [(-1,1), (-1,0), (0,0), (1,0)],
    'L': [(1,1), (-1,0), (0,0), (1,0)],
    'S': [(0,1), (1,1), (-1,0), (0,0)],
    'Z': [(-1,1), (0,1), (0,0), (1,0)],
    'I': [(-1,0), (0,0), (1,0), (2,0)],
    'O': [(0,0), (1,0), (0,1), (1,1)]
}

def get_rotated_blocks(shape, rot):
    if shape == 'O':
        return MINOS['O']
    if shape == 'I':
        if rot == 0: return [(-1, 0), ( 0, 0), ( 1, 0), ( 2, 0)]
        if rot == 1: return [( 0, 1), ( 0, 0), ( 0,-1), ( 0,-2)]
        if rot == 2: return [(-1,-1), ( 0,-1), ( 1,-1), ( 2,-1)]
        if rot == 3: return [( 1, 1), ( 1, 0), ( 1,-1), ( 1,-2)]
    blocks = MINOS[shape]
    for _ in range(rot):
        blocks = [(y, -x) for x, y in blocks]
    return blocks

class TetrisLogic:
    def __init__(self):
        self.width = 10
        self.height = 20
        self.board = [[0]*self.width for _ in range(self.height)]
        self.score = 0
        self.bag = []
        self.next_minos = []
        self.hold_mino = None
        self.can_hold = True
        
        self.current_shape = None
        self.current_x = 0
        self.current_y = 0
        self.current_rot = 0
        
        self.game_over = False
        self.fall_timer = 0.0
        self.fall_speed = 1.0 

        self._fill_next()
        self.spawn()

    def _get_bag(self):
        bag = list('TJLSIZO')
        random.shuffle(bag)
        return bag

    def _fill_next(self):
        while len(self.next_minos) < 5:
            if not self.bag:
                self.bag = self._get_bag()
            self.next_minos.append(self.bag.pop(0))

    def spawn(self):
        self.current_shape = self.next_minos.pop(0)
        self._fill_next()
        self.current_rot = 0
        self.current_x = 4
        self.current_y = 18
        self.can_hold = True
        if self._is_collision(self.current_x, self.current_y, self.current_rot):
            self.game_over = True

    def hold(self):
        if not self.can_hold:
            return
        if self.hold_mino is None:
            self.hold_mino = self.current_shape
            self.spawn()
        else:
            self.current_shape, self.hold_mino = self.hold_mino, self.current_shape
            self.current_rot = 0
            self.current_x = 4
            self.current_y = 18
        self.can_hold = False

    def _is_collision(self, cx, cy, rot):
        blocks = get_rotated_blocks(self.current_shape, rot)
        for bx, by in blocks:
            x = cx + bx
            y = cy + by
            if x < 0 or x >= self.width or y < 0:
                return True
            if y < self.height and self.board[y][x]:
                return True
        return False

    def move(self, dx, dy):
        if not self._is_collision(self.current_x + dx, self.current_y + dy, self.current_rot):
            self.current_x += dx
            self.current_y += dy
            return True
        return False

    def rotate(self, dir):
        if self.current_shape == 'O': return
        
        new_rot = (self.current_rot + dir) % 4
        kick_table = KICK_I if self.current_shape == 'I' else KICK_JLSTZ
        
        kicks = kick_table.get((self.current_rot, new_rot), [(0,0)])
        for dx, dy in kicks:
            if not self._is_collision(self.current_x + dx, self.current_y + dy, new_rot):
                self.current_x += dx
                self.current_y += dy
                self.current_rot = new_rot
                return

    def hard_drop(self):
        while self.move(0, -1):
            self.score += 2
        self.lock()

    def lock(self):
        blocks = get_rotated_blocks(self.current_shape, self.current_rot)
        for bx, by in blocks:
            x = self.current_x + bx
            y = self.current_y + by
            if 0 <= y < self.height:
                self.board[y][x] = 1
        
        self._clear_lines()
        self.spawn()

    def _clear_lines(self):
        lines_cleared = 0
        new_board = []
        for row in self.board:
            if all(row):
                lines_cleared += 1
            else:
                new_board.append(row)
        while len(new_board) < self.height:
            new_board.append([0]*self.width)
        self.board = new_board
        
        if lines_cleared == 1: self.score += 100
        elif lines_cleared == 2: self.score += 300
        elif lines_cleared == 3: self.score += 500
        elif lines_cleared == 4: self.score += 800

    def update(self, dt):
        if self.game_over:
            return
        self.fall_timer += dt
        if self.fall_timer >= self.fall_speed:
            self.fall_timer = 0
            if not self.move(0, -1):
                self.lock()