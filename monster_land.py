"""
monster_land.py - an isometric island populated by singing monsters.

Standalone pygame scene built from assets/iso_tile.png and assets/monsters.png.

Sprite sheet layout (monsters.png, 384x128):
    12 columns of 32px  -> 12 distinct monster types
    2 rows of 64px      -> row 0 = idle, row 1 = singing

Run directly:
    python monster_land.py [seed]

Or embed in something else:
    land = MonsterLand()
    land.set_singing(monster_index, True)   # drive from music events
    land.run()

Controls:
    SPACE       everyone sings / stops
    R           regenerate the island
    Left click  toggle a monster singing
    ESC / close quit
"""

import math
import os
import random
import sys

import pygame

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
TILE_PATH = os.path.join(ASSET_DIR, "iso_tile.png")
MONSTER_PATH = os.path.join(ASSET_DIR, "monsters.png")

# Native asset metrics (pre-scale)
TILE_W, TILE_H = 32, 24       # full tile image
TILE_TOP_H = 16               # height of the top diamond
TILE_DEPTH = TILE_H - TILE_TOP_H
STEP_X, STEP_Y = TILE_W // 2, TILE_TOP_H // 2   # grid-to-screen half steps
FRAME_W, FRAME_H = 32, 64
NUM_TYPES = 12
FEET_Y = 50                   # sprite feet row inside a 64px frame

SCALE = 3
WINDOW_W, WINDOW_H = 1024, 720
FPS = 60

SKY_TOP = (18, 20, 34)
SKY_BOTTOM = (46, 40, 72)


class Monster:
    def __init__(self, kind, gx, gy, height):
        self.kind = kind
        self.gx = gx
        self.gy = gy
        self.height = height
        self.singing = False
        self.sing_timer = 0.0        # seconds left in current state
        self.phase = random.uniform(0, math.tau)
        self.rect = pygame.Rect(0, 0, 0, 0)  # last drawn rect (for clicking)
        self.auto = True              # auto-cycle singing unless driven externally

    def update(self, dt):
        self.phase += dt * (9.0 if self.singing else 2.0)
        if not self.auto:
            return
        self.sing_timer -= dt
        if self.sing_timer <= 0:
            if self.singing:
                self.singing = False
                self.sing_timer = random.uniform(1.5, 6.0)
            else:
                self.singing = True
                self.sing_timer = random.uniform(0.8, 2.5)


class MonsterLand:
    def __init__(self, size=11, population=18, seed=None, scale=SCALE,
                 window=(WINDOW_W, WINDOW_H)):
        pygame.init()
        pygame.display.set_caption("Monster Land")
        self.scale = scale
        self.win_w, self.win_h = window
        self.screen = pygame.display.set_mode((self.win_w, self.win_h))
        self.clock = pygame.time.Clock()
        self.size = size
        self.population = population
        self.rng = random.Random(seed)
        random.seed(seed)

        self._load_assets()
        self._build_background()
        self.generate()

    # ------------------------------------------------------------------ assets
    def _load_assets(self):
        tile = pygame.image.load(TILE_PATH).convert_alpha()
        sheet = pygame.image.load(MONSTER_PATH).convert_alpha()
        self.tile = pygame.transform.scale_by(tile, self.scale)
        # slice frames at native resolution, then scale each one
        self.frames = []  # frames[kind] = (idle_surface, singing_surface)
        for kind in range(NUM_TYPES):
            pair = []
            for row in range(2):
                r = pygame.Rect(kind * FRAME_W, row * FRAME_H, FRAME_W, FRAME_H)
                frame = sheet.subsurface(r)
                pair.append(pygame.transform.scale_by(frame, self.scale))
            self.frames.append(tuple(pair))
        # shadow blob under each monster
        self.shadow = pygame.Surface((16 * self.scale, 7 * self.scale), pygame.SRCALPHA)
        pygame.draw.ellipse(self.shadow, (0, 0, 0, 90), self.shadow.get_rect())
        self.font = pygame.font.SysFont("consolas", 16)

    def _build_background(self):
        self.background = pygame.Surface((self.win_w, self.win_h))
        for y in range(self.win_h):
            t = y / self.win_h
            c = tuple(int(SKY_TOP[i] + (SKY_BOTTOM[i] - SKY_TOP[i]) * t) for i in range(3))
            pygame.draw.line(self.background, c, (0, y), (self.win_w, y))
        for _ in range(140):  # stars
            x, y = random.randrange(self.win_w), random.randrange(self.win_h // 2)
            b = random.randint(120, 255)
            self.background.set_at((x, y), (b, b, b))

    # ------------------------------------------------------------------ world
    def generate(self):
        """Build a blobby island with gentle hills, then scatter monsters."""
        self.build_terrain(self.size, self.rng)
        self.populate_random(self.population, self.rng)
        self.center_island()

    def build_terrain(self, n, rng):
        """Fill self.tiles with a blobby island of size n using rng."""
        self.size = n
        c = (n - 1) / 2
        radius_noise = [rng.uniform(0.75, 1.0) for _ in range(16)]

        def inside(x, y):
            dx, dy = x - c, y - c
            d = math.hypot(dx, dy)
            ang = math.atan2(dy, dx)
            k = int(((ang + math.pi) / math.tau) * 16) % 16
            return d <= c * radius_noise[k] + 0.3

        # height field: random then smoothed
        h = [[rng.uniform(0, 2.4) for _ in range(n)] for _ in range(n)]
        for _ in range(2):
            nh = [[0.0] * n for _ in range(n)]
            for y in range(n):
                for x in range(n):
                    s, cnt = 0.0, 0
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            xx, yy = x + dx, y + dy
                            if 0 <= xx < n and 0 <= yy < n:
                                s += h[yy][xx]
                                cnt += 1
                    nh[y][x] = s / cnt
            h = nh

        self.tiles = {}  # (gx, gy) -> height level (int)
        for y in range(n):
            for x in range(n):
                if inside(x, y):
                    edge = math.hypot(x - c, y - c) / c
                    lvl = int(round(h[y][x] * (1.0 - edge * 0.6)))
                    self.tiles[(x, y)] = max(0, lvl)

    def populate_random(self, population, rng):
        """One monster per tile at most, all 12 kinds represented when possible."""
        spots = list(self.tiles.keys())
        rng.shuffle(spots)
        spots = spots[: min(population, len(spots))]
        kinds = list(range(NUM_TYPES))
        rng.shuffle(kinds)
        self.monsters = []
        for i, (gx, gy) in enumerate(spots):
            kind = kinds[i] if i < NUM_TYPES else rng.randrange(NUM_TYPES)
            m = Monster(kind, gx, gy, self.tiles[(gx, gy)])
            m.sing_timer = rng.uniform(0.5, 5.0)
            self.monsters.append(m)

    def center_island(self, top_margin=0):
        """Centre the island in the window, below top_margin pixels."""
        n = self.size
        max_h = max(self.tiles.values()) if self.tiles else 0
        self.origin_x = self.win_w // 2
        self.origin_y = (top_margin + (self.win_h - top_margin) // 2
                         - ((2 * n - 1) * STEP_Y * self.scale) // 2
                         + max_h * TILE_DEPTH * self.scale // 2 + 20)

    # ------------------------------------------------------------------ api
    def set_singing(self, index, singing, lock=True):
        """Drive a monster from outside (e.g. music events).

        lock=True stops the monster auto-cycling so it stays as set.
        """
        m = self.monsters[index % len(self.monsters)]
        m.singing = singing
        m.auto = not lock

    def set_all(self, singing, lock=False):
        for m in self.monsters:
            m.singing = singing
            m.auto = not lock
            m.sing_timer = random.uniform(1.0, 3.0)

    def monsters_of_kind(self, kind):
        return [i for i, m in enumerate(self.monsters) if m.kind == kind]

    # ------------------------------------------------------------------ drawing
    def grid_to_screen(self, gx, gy, level):
        """Screen position of the top-centre of a tile's bounding box."""
        sx = self.origin_x + (gx - gy) * STEP_X * self.scale
        sy = self.origin_y + (gx + gy) * STEP_Y * self.scale - level * TILE_DEPTH * self.scale
        return sx, sy

    def draw(self):
        self.screen.blit(self.background, (0, 0))
        by_pos = {}                      # tile -> monsters standing on (or walking over) it
        for m in self.monsters:
            by_pos.setdefault((round(m.gx), round(m.gy)), []).append(m)

        # painter order: back to front by gx+gy
        for (gx, gy) in sorted(self.tiles, key=lambda p: (p[0] + p[1], p[0])):
            lvl = self.tiles[(gx, gy)]
            sx, sy = self.grid_to_screen(gx, gy, 0)
            # draw a column of tiles up to this level so cliffs look solid
            for l in range(lvl + 1):
                tx = sx - TILE_W * self.scale // 2
                ty = sy - l * TILE_DEPTH * self.scale
                self.screen.blit(self.tile, (tx, ty))
            for m in sorted(by_pos.get((gx, gy), ()), key=lambda m: m.gx + m.gy):
                self._draw_monster(m)

        self.draw_overlay()
        self._draw_hud()

    def draw_overlay(self):
        """Hook for subclasses: drawn after the island, before the HUD."""

    def frame_for(self, m):
        """Hook: the surface to draw for a monster in its current state."""
        return self.frames[m.kind][1 if m.singing else 0]

    def offset_for(self, m):
        """Hook: (dx, lift) in pixels applied to a monster's sprite this frame."""
        if m.singing:
            return 0, int(abs(math.sin(m.phase)) * 3 * self.scale)
        return 0, 0

    def _draw_monster(self, m):
        sx, sy = self.grid_to_screen(m.gx, m.gy, m.height)
        foot_x = sx
        foot_y = sy + (TILE_TOP_H // 2) * self.scale   # centre of the top diamond
        dx, bob = self.offset_for(m)
        frame = self.frame_for(m)
        self.screen.blit(self.shadow, self.shadow.get_rect(center=(foot_x, foot_y)))
        x = foot_x - FRAME_W * self.scale // 2 + dx
        y = foot_y - FEET_Y * self.scale - bob
        m.rect = self.screen.blit(frame, (x, y))
        if m.singing:
            self._draw_notes(m, foot_x, y)

    def _draw_notes(self, m, cx, top_y):
        """Little rising music notes above a singing monster."""
        for i in range(2):
            p = (m.phase * 0.35 + i * 0.5) % 1.0
            nx = cx + int(math.sin(p * math.tau + i) * 8 * self.scale) + (i * 2 - 1) * 6 * self.scale
            ny = top_y + 16 * self.scale - int(p * 24 * self.scale)
            alpha = int(255 * (1 - p))
            col = (255, 230, 120, alpha)
            s = pygame.Surface((4 * self.scale, 6 * self.scale), pygame.SRCALPHA)
            pygame.draw.ellipse(s, col, (0, 3 * self.scale, 3 * self.scale, 3 * self.scale))
            pygame.draw.line(s, col, (3 * self.scale - 1, 0), (3 * self.scale - 1, 4 * self.scale), self.scale)
            self.screen.blit(s, (nx, ny))

    def _draw_hud(self):
        singing = sum(1 for m in self.monsters if m.singing)
        text = (f"{len(self.monsters)} monsters, {singing} singing   "
                f"[SPACE] all sing  [R] new island  [click] toggle")
        surf = self.font.render(text, True, (220, 220, 230))
        self.screen.blit(surf, (12, self.win_h - 28))

    # ------------------------------------------------------------------ loop
    def monsters_draw_order(self):
        return sorted(self.monsters, key=lambda m: (m.gx + m.gy, m.gx))

    def handle_event(self, ev):
        """Returns False when the app should quit."""
        if ev.type == pygame.QUIT:
            return False
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                return False
            if ev.key == pygame.K_r:
                self.generate()
            if ev.key == pygame.K_SPACE:
                any_quiet = any(not m.singing for m in self.monsters)
                self.set_all(any_quiet)
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            # front-most monster under the cursor wins
            for m in reversed(self.monsters_draw_order()):
                if m.rect.collidepoint(ev.pos):
                    m.singing = not m.singing
                    m.auto = False
                    break
        return True

    def update(self, dt):
        for m in self.monsters:
            m.update(dt)

    def step(self):
        """One frame: events, update, draw, flip. Returns False on quit."""
        dt = min(self.clock.tick(FPS) / 1000.0, 0.05)   # clamp after stalls
        for ev in pygame.event.get():
            if not self.handle_event(ev):
                return False
        self.update(dt)
        self.draw()
        pygame.display.flip()
        return True

    def run(self):
        while self.step():
            pass
        pygame.quit()


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else None
    MonsterLand(seed=seed).run()
