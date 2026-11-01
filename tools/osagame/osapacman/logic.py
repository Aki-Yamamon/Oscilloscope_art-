import random

MAP_DATA = [
    "WWWWWWWWWWWWWWWWWWW",
    "W........W........W",
    "W.WW.WWW.W.WWW.WW.W",
    "WPWW.WWW.W.WWW.WWPW",
    "W.................W",
    "W.WW.W.WWWWW.W.WW.W",
    "W....W...W...W....W",
    "WWWW.WWW W WWW.WWWW",
    "   W.W       W.W   ",
    "WWWW.W WW WW W.WWWW",
    "    .  W   W  .    ",
    "WWWW.W WWWWW W.WWWW",
    "   W.W       W.W   ",
    "WWWW.W WWWWW W.WWWW",
    "W........W........W",
    "W.WW.WWW.W.WWW.WW.W",
    "WP.W..... .....W.PW",
    "WW.W.W.WWWWW.W.W.WW",
    "W....W...W...W....W",
    "W.WWWWWW.W.WWWWWW.W",
    "W.................W",
    "WWWWWWWWWWWWWWWWWWW"
]

DIRS = {
    'up': (0, -1),
    'down': (0, 1),
    'left': (-1, 0),
    'right': (1, 0),
    'none': (0, 0)
}

class Entity:
    def __init__(self, x, y, is_ghost=False):
        self.x = x
        self.y = y
        self.start_x = x
        self.start_y = y
        self.dir = 'none'
        self.next_dir = 'none'
        self.is_ghost = is_ghost
        self.move_frac = 0.0

    def reset(self):
        self.x = self.start_x
        self.y = self.start_y
        self.dir = 'none'
        self.next_dir = 'none'
        self.move_frac = 0.0

class PacmanLogic:
    def __init__(self):
        self.width = len(MAP_DATA[0])
        self.height = len(MAP_DATA)
        self.grid = []
        
        self.score = 0
        self.stage = 1
        self.lives = 3
        self.game_over = False
        
        self.power_timer = 0.0
        self.power_mode = False
        self.dots_left = 0
        
        self.pacman = None
        self.ghosts = []
        
        self.pacman_speed = 7.5 # パックマンも全体的にスピードアップ
        
        self.event_chomp = False
        self.event_eatghost = False
        self.event_death = False
        self.event_clear = False
        
        self._load_map()

    def _load_map(self):
        self.grid = []
        self.dots_left = 0
        self.power_mode = False
        self.power_timer = 0.0
        
        for y, row in enumerate(MAP_DATA):
            grid_row = []
            for x, char in enumerate(row):
                if char == 'W':
                    grid_row.append(1)
                elif char == '.':
                    grid_row.append(2)
                    self.dots_left += 1
                elif char == 'P':
                    grid_row.append(3)
                    self.dots_left += 1
                else:
                    grid_row.append(0)
            self.grid.append(grid_row)
            
        self.reset_entities()

    def reset_entities(self):
        self.pacman = Entity(9, 16)
        self.ghosts = [
            Entity(8, 10, True),
            Entity(9, 10, True),
            Entity(10, 10, True),
            Entity(9, 9, True)
        ]
        self.power_mode = False

    def _is_wall(self, x, y):
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            return True
        return self.grid[y][x] == 1

    def _make_decision(self, ent):
        """交差点に来るたびに進行方向を決定する（ゴーストのUターン禁止処理を含む）"""
        if not ent.is_ghost:
            ndx, ndy = DIRS[ent.next_dir]
            if ent.next_dir != 'none' and not self._is_wall((ent.x + ndx) % self.width, (ent.y + ndy) % self.height):
                ent.dir = ent.next_dir
                ent.next_dir = 'none'

            cx, cy = DIRS[ent.dir]
            if self._is_wall((ent.x + cx) % self.width, (ent.y + cy) % self.height):
                ent.dir = 'none'
        else:
            opp = {'up':'down', 'down':'up', 'left':'right', 'right':'left', 'none':'none'}
            valid_dirs = []
            for d_name, (vx, vy) in DIRS.items():
                if d_name == 'none': continue
                if not self._is_wall((ent.x + vx) % self.width, (ent.y + vy) % self.height):
                    valid_dirs.append(d_name)
            
            # 進行可能な道が複数ある場合、Uターン(逆走)を選択肢から外す（スタック防止）
            if len(valid_dirs) > 1 and opp[ent.dir] in valid_dirs:
                valid_dirs.remove(opp[ent.dir])
            
            if not valid_dirs:
                ent.dir = 'none'
            elif len(valid_dirs) == 1:
                ent.dir = valid_dirs[0]
            else:
                # 難易度調整: 追跡確率のベースを高くし、ほぼ迷わなくする
                smartness = min(0.98, 0.65 + self.stage * 0.1)
                if random.random() < smartness and not self.power_mode:
                    best_dir = valid_dirs[0]
                    min_dist = float('inf')
                    for d_name in valid_dirs:
                        vx, vy = DIRS[d_name]
                        nx = (ent.x + vx) % self.width
                        ny = (ent.y + vy) % self.height
                        dist = abs(nx - self.pacman.x) + abs(ny - self.pacman.y)
                        if dist < min_dist:
                            min_dist = dist
                            best_dir = d_name
                    ent.dir = best_dir
                elif random.random() < smartness and self.power_mode:
                    best_dir = valid_dirs[0]
                    max_dist = -1
                    for d_name in valid_dirs:
                        vx, vy = DIRS[d_name]
                        nx = (ent.x + vx) % self.width
                        ny = (ent.y + vy) % self.height
                        dist = abs(nx - self.pacman.x) + abs(ny - self.pacman.y)
                        if dist > max_dist:
                            max_dist = dist
                            best_dir = d_name
                    ent.dir = best_dir
                else:
                    ent.dir = random.choice(valid_dirs)

    def _update_entity(self, ent, dt, speed):
        # 停止している場合は先に方向決定
        if ent.dir == 'none':
            self._make_decision(ent)
            if ent.dir == 'none':
                ent.move_frac = 0.0
                return

        ent.move_frac += dt * speed
        while ent.move_frac >= 1.0:
            dx, dy = DIRS[ent.dir]
            ent.x = (ent.x + dx) % self.width
            ent.y = (ent.y + dy) % self.height
            ent.move_frac -= 1.0
            
            # 1マス進むごとに次の行動を決定
            self._make_decision(ent)
            if ent.dir == 'none':
                ent.move_frac = 0.0
                break

    def update(self, dt):
        if self.game_over:
            return

        if self.power_mode:
            self.power_timer -= dt
            if self.power_timer <= 0:
                self.power_mode = False

        self._update_entity(self.pacman, dt, self.pacman_speed)
        
        cell_val = self.grid[self.pacman.y][self.pacman.x]
        if cell_val == 2:
            self.grid[self.pacman.y][self.pacman.x] = 0
            self.score += 10
            self.dots_left -= 1
            self.event_chomp = True
        elif cell_val == 3:
            self.grid[self.pacman.y][self.pacman.x] = 0
            self.score += 50
            self.dots_left -= 1
            self.power_mode = True
            self.power_timer = max(1.5, 6.0 - self.stage * 1.0)
            self.event_chomp = True

        if self.dots_left <= 0:
            self.event_clear = True
            return
            
        # ゴーストの基本スピードを上昇
        base_ghost_speed = min(9.0, 5.5 + self.stage * 0.5)
        g_speed = base_ghost_speed * 0.5 if self.power_mode else base_ghost_speed
        
        for g in self.ghosts:
            self._update_entity(g, dt, g_speed)
            
            dist = abs(self.pacman.x - g.x) + abs(self.pacman.y - g.y)
            if dist < 1.0:
                if self.power_mode:
                    g.reset()
                    self.score += 200
                    self.event_eatghost = True
                else:
                    self.event_death = True