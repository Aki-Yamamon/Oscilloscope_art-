import random

# W=Wall, .=Dot, P=Power, ' '=Empty
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
        
        self.pacman_speed = 6.5 # 少しスピードアップ
        
        # イベントフラグ
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

    def _update_entity(self, ent, dt, speed):
        ent.move_frac += dt * speed
        
        while ent.move_frac >= 1.0:
            dx, dy = DIRS[ent.dir]
            ent.x = (ent.x + dx) % self.width
            ent.y = (ent.y + dy) % self.height
            ent.move_frac -= 1.0

            ndx, ndy = DIRS[ent.next_dir]
            if ent.next_dir != 'none' and not self._is_wall((ent.x + ndx) % self.width, (ent.y + ndy) % self.height):
                ent.dir = ent.next_dir
                ent.next_dir = 'none'

            cx, cy = DIRS[ent.dir]
            if self._is_wall((ent.x + cx) % self.width, (ent.y + cy) % self.height):
                ent.dir = 'none'
                ent.move_frac = 0.0
                
            if ent.is_ghost and ent.dir == 'none':
                valid_dirs = []
                for d_name, (vx, vy) in DIRS.items():
                    if d_name == 'none': continue
                    if not self._is_wall((ent.x + vx) % self.width, (ent.y + vy) % self.height):
                        valid_dirs.append(d_name)
                
                if valid_dirs:
                    # 難易度調整: 最初からかなり賢く、ステージが進むとほぼ確実に最短距離を選ぶ
                    smartness = min(0.98, 0.5 + self.stage * 0.15)
                    
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
            # ステージが進むにつれて無敵時間が短くなる（最小2秒）
            self.power_timer = max(2.0, 6.5 - self.stage * 0.8)
            self.event_chomp = True

        if self.dots_left <= 0:
            self.event_clear = True
            return
            
        # 難易度調整: ゴーストの初期速度アップ＆成長速度アップ
        base_ghost_speed = min(7.5, 4.5 + self.stage * 0.4)
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