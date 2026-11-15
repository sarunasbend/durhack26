"""
receiver_planet.py - the planet that hears the message.

Receiver Joe stands in the middle of an island. Sound waves fly in from the
edge of the screen to his antenna, he plays each note he hears (lighting up
in that note's colour and throwing out a note sprite), the other aliens boogie
to the beat, and the decoded text appears at the top as it is received.

Sources of music:
    python receiver_planet.py                    listen on the microphone with the
                                                 trained model (training/common.py),
                                                 key and scale from Settings.py
    python receiver_planet.py --demo "Hello"     no mic: plays the message through the
                                                 speakers and feeds the notes on schedule
    python receiver_planet.py --demo "Hi" --silent   same, without playing audio

Controls:
    Space       demo mode: replay the message
    R           re-shuffle the crowd
    [ / ]       sync offset for the demo's audio (shared with tune_island.py)
    Esc / close quit
"""

import math
import os
import random
import sys
import tempfile
import threading
import time
from collections import deque

import numpy as np
import pygame

import Avison
import Settings
from Notes import Notes
from Transmitter import Transmitter
import monster_land as ml
from monster_land import MonsterLand, Monster, NUM_TYPES, FRAME_W, FEET_Y, TILE_TOP_H
from tune_island import (pitch_colours, recolour, load_note_cells, SETTINGS_PATH,
                         DEFAULT_LATENCY, CELL_QUAVER, CELL_PAIR)

HERE = os.path.dirname(os.path.abspath(__file__))
JOE_PATH = os.path.join(ml.ASSET_DIR, "reciever_joe.png")
WAVE_PATH = os.path.join(ml.ASSET_DIR, "soundwave.png")
JOE_W, JOE_H, JOE_FEET = 32, 80, 64        # sprite metrics
JOE_ANTENNA = (16, 4)                       # antenna tip inside the sprite

VIEW_SCALE = 2
WINDOW = (1024, 800)
TOP_MARGIN = 150
GRID = 12
CROWD = 11
JOE_KIND = -1

MIC_SR = 22050                               # what the model was trained on (common.SR)
LEVEL_FLOOR, LEVEL_CEIL = 0.004, 0.12        # mic RMS mapped to 0..1 for the wave effect
WAVE_SPEED = 420                             # px/s
FLASH_TIME = 0.35                            # Joe stays lit this long after a note
PARTICLE_LIFE = 1.1


# ============================================================================ sources
class MicSource:
    """Microphone + trained model, run in a background thread.

    Attributes read by the UI (all plain values, swapped atomically):
        status   'loading model', 'listening', 'receiving', 'done', 'error: ...'
        level    0..1 loudness right now
        notes    note names heard so far in the current message
        text     decoded text of the current message
        active   True while a message is being received
        history  texts of finished messages
        device   name of the microphone
    """

    def __init__(self, composer, device=None):
        self.composer = composer
        self.device = device
        self.status = "loading model"
        self.level = 0.0
        self.notes = []
        self.text = ""
        self.active = False
        self.history = []
        self.device_name = "?"
        self.silent_for = 0.0        # seconds of exact digital silence (muted / dead mic)
        self.error = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        try:
            import sounddevice as sd
            sys.path.insert(0, os.path.join(HERE, "training"))
            import common
            model = common.load_model()
            drone = common.drone_for(self.composer.scale.key)
            make = lambda: common.MessageReceiver(model, self.composer, drone)
            receiver = make()
            try:
                info = sd.query_devices(self.device if self.device is not None else sd.default.device[0], "input")
                self.device_name = info["name"]
            except Exception:
                pass
            block = 8 * common.HOP
            done_at = None
            self.status = "listening"
            with sd.InputStream(samplerate=common.SR, channels=1, blocksize=block, device=self.device) as stream:
                while not self._stop.is_set():
                    samples, _ = stream.read(block)
                    mono = samples[:, 0]
                    rms = float(np.sqrt(np.mean(mono ** 2)))
                    self.silent_for = self.silent_for + len(mono) / common.SR if rms == 0.0 else 0.0
                    self.level = max(0.0, min(1.0, (rms - LEVEL_FLOOR) / (LEVEL_CEIL - LEVEL_FLOOR)))
                    if done_at is not None:
                        if time.perf_counter() - done_at > 1.5:   # breathe, then wait for the next message
                            receiver = make()
                            done_at = None
                            self.notes, self.text, self.active = [], "", False
                            self.status = "listening"
                        continue
                    receiver.add_audio(mono)
                    self.notes = list(receiver.notes)
                    self.text = receiver.text
                    self.active = receiver.clock is not None
                    if receiver.finished:
                        self.status = "done"
                        self.history.append(receiver.text)
                        done_at = time.perf_counter()
                    elif self.active:
                        self.status = "receiving"
        except Exception as exc:                      # no model, no mic, torch missing...
            self.error = str(exc)
            self.status = f"error: {exc}"


class DemoSource:
    """Plays a message locally and reveals its notes on the sender's own timeline."""

    def __init__(self, composer, text, play_audio=True, latency=0.0):
        self.composer = composer
        self.text_full = text
        self.play_audio = play_audio
        self.latency = latency
        self.status = "demo"
        self.level = 0.0
        self.notes = []
        self.text = ""
        self.active = False
        self.history = []
        self.device_name = "demo (no microphone)"
        self.error = None

        self.encoded, self.metadata = composer.encode_message(text)
        beat = 60.0 / Settings.TEMPO
        self.starts, clock = [], 0.0
        for meta in self.metadata:
            start = clock + meta.get("previous", 0)
            self.starts.append(start * beat)
            clock = start + meta.get("time", 0)
        self.song_end = max((s + m["duration"] * beat for s, m in zip(self.starts, self.metadata)), default=0.0)
        self.table = composer.stream_decode().decoding_table
        self.size = composer.configuration.cluster_size
        self.midi_path = os.path.join(tempfile.gettempdir(), "receiver_planet_demo.mid")
        self.play_started = None
        self.start()

    def start(self):
        self.notes, self.text, self.active = [], "", False
        if self.play_audio and self.encoded:
            try:
                tr = Transmitter()
                tr.tempo = Settings.TEMPO
                tr.drone = Settings.DRONE
                tr.config()
                tr.write(self.encoded, self.metadata, None, 0)
                tr.save(self.midi_path)
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
                pygame.mixer.music.load(self.midi_path)
                pygame.mixer.music.play()
            except Exception as exc:
                print(f"[receiver_planet] demo audio failed: {exc}")
        self.play_started = time.perf_counter()

    def stop(self):
        try:
            pygame.mixer.music.stop()
        except pygame.error:
            pass

    def poll(self):
        if self.play_started is None:
            return
        t = time.perf_counter() - self.play_started - self.latency
        n = sum(1 for s in self.starts if s <= t)
        if n != len(self.notes):
            self.notes = self.encoded[:n]
            sure = self.notes[: len(self.notes) // self.size * self.size]
            self.text = "".join(self.table.get(",".join(sure[i:i + self.size]), "?")
                                for i in range(0, len(sure), self.size))
        sounding = any(s <= t < s + m["duration"] * 60 / Settings.TEMPO for s, m in zip(self.starts, self.metadata))
        self.level = 0.8 if sounding else 0.0
        was_active = self.active
        self.active = 0 <= t <= self.song_end
        if was_active and not self.active and self.text:
            self.history.append(self.text)
            self.status = "done"
        elif self.active:
            self.status = "receiving"


# ============================================================================ planet
class ReceiverPlanet(MonsterLand):
    def __init__(self, composer, source_factory):
        self.composer = composer
        cfg = composer.configuration
        notes = Notes()
        notes.create_note_table(composer.scale, cfg.octaves, cfg.first_octave)
        self.note_table = notes.notes
        self.drone_note = Settings.DRONE or None
        self.source = None
        self.joe = None
        self.flash_until = 0.0
        self.flash_pitch = None
        self.seen_notes = 0
        self.message_started = None
        self.waves = []
        self.particles = []
        self.wave_budget = 0.0
        self.beat = 60.0 / Settings.TEMPO
        self.latency = self._load_latency()

        super().__init__(seed=1, scale=VIEW_SCALE, window=WINDOW)
        pygame.display.set_caption("Receiver Planet")
        self.big_font = pygame.font.SysFont("consolas", 26)
        self.small_font = pygame.font.SysFont("consolas", 15)
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
        except pygame.error as exc:
            print(f"[receiver_planet] audio unavailable: {exc}")
        self._load_extra_sprites()
        self.source = source_factory(self)

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _load_latency():
        try:
            import json
            with open(SETTINGS_PATH) as f:
                return float(json.load(f).get("latency", DEFAULT_LATENCY))
        except (OSError, ValueError):
            return DEFAULT_LATENCY

    def _load_extra_sprites(self):
        self.pitch_colour = pitch_colours(self.note_table, len(self.composer.scale.scale), self.drone_note)
        self.tinted = {}
        joe = pygame.transform.scale_by(pygame.image.load(JOE_PATH).convert_alpha(), self.scale)
        self.joe_frames = {None: joe}
        for name, col in self.pitch_colour.items():
            self.joe_frames[name] = recolour(joe, col)
        wave = pygame.transform.scale_by(pygame.image.load(WAVE_PATH).convert_alpha(), self.scale)
        self.wave_base = wave
        self.wave_tints = {}
        for name, col in list(self.pitch_colour.items()) + [("white", pygame.Color(230, 230, 255))]:
            w = wave.copy()
            w.fill(col, special_flags=pygame.BLEND_RGB_MAX)
            self.wave_tints[name] = w
        cells = load_note_cells(self.scale)
        self.note_sprites = {}
        for name, col in self.pitch_colour.items():
            for c, cell in enumerate(cells):
                s = cell.copy()
                s.fill(col, special_flags=pygame.BLEND_RGB_MAX)
                self.note_sprites[(name, c)] = s

    # ------------------------------------------------------------------ world
    def generate(self):
        rng = random.Random(7)
        self.build_terrain(GRID, rng)
        self.monsters = []
        c = (GRID - 1) / 2
        centre = min(self.tiles, key=lambda t: (t[0] - c) ** 2 + (t[1] - c) ** 2)
        self.tiles[centre] += 1
        self.joe = Monster(JOE_KIND, centre[0], centre[1], self.tiles[centre])
        self.joe.auto = False
        self.joe.pitch = None
        self.monsters.append(self.joe)
        self.shuffle_crowd()
        self.center_island(top_margin=TOP_MARGIN)

    def shuffle_crowd(self):
        """Aliens around Joe, each wearing the colour of one pitch of the scale."""
        rng = random.Random()
        self.monsters = [self.joe]
        c = (GRID - 1) / 2
        ring = [t for t in self.tiles
                if 2.0 <= math.hypot(t[0] - c, t[1] - c) <= 0.9 * c]
        rng.shuffle(ring)
        kinds = [k for k in range(NUM_TYPES)]
        rng.shuffle(kinds)
        pitches = list(self.note_table)
        for i, tile in enumerate(ring[:CROWD]):
            m = Monster(kinds[i % len(kinds)], tile[0], tile[1], self.tiles[tile])
            m.auto = False
            m.pitch = pitches[i % len(pitches)]
            m.style = rng.randrange(3)
            m.offset = rng.uniform(0, math.tau)
            m.kick = 0.0
            self.monsters.append(m)

    # ------------------------------------------------------------------ update
    def handle_event(self, ev):
        if ev.type == pygame.QUIT:
            return False
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                return False
            if ev.key == pygame.K_r:
                self.shuffle_crowd()
            if ev.key == pygame.K_SPACE and isinstance(self.source, DemoSource):
                self.seen_notes = 0
                self.source.start()
            if ev.key in (pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET) and isinstance(self.source, DemoSource):
                step = -0.02 if ev.key == pygame.K_LEFTBRACKET else 0.02
                self.latency = max(0.0, min(0.8, round(self.latency + step, 3)))
                self.source.latency = self.latency
        return True

    def update(self, dt):
        now = time.perf_counter()
        src = self.source
        if isinstance(src, DemoSource):
            src.poll()

        # a new note arrived -> Joe plays it
        notes = src.notes
        if len(notes) < self.seen_notes:
            self.seen_notes = 0                        # new message
        if src.active and self.message_started is None:
            self.message_started = now
        if not src.active:
            self.message_started = None
        while self.seen_notes < len(notes):
            self._play_note(notes[self.seen_notes])
            self.seen_notes += 1

        # sound waves pour in while there is sound
        level = src.level
        self.wave_budget += dt * (2 + 18 * level) * (1.0 if level > 0.05 or src.active else 0.0)
        while self.wave_budget >= 1.0:
            self.wave_budget -= 1.0
            self._spawn_wave()
        target = self._antenna_pos()
        for w in self.waves:
            dx, dy = target[0] - w["x"], target[1] - w["y"]
            d = math.hypot(dx, dy)
            step = WAVE_SPEED * dt * (0.6 + level)
            if d <= step + 4:
                w["dead"] = True
            else:
                w["x"] += dx / d * step
                w["y"] += dy / d * step
        self.waves = [w for w in self.waves if not w.get("dead")]

        # dancers
        for m in self.monsters:
            if m is self.joe:
                continue
            m.kick = max(0.0, m.kick - dt * 3)
            m.phase += dt * 2
        self.joe.singing = now < self.flash_until

        for p in self.particles:
            p["age"] += dt
            p["y"] -= 26 * self.scale * dt
            p["x"] += p["vx"] * dt
        self.particles = [p for p in self.particles if p["age"] < PARTICLE_LIFE]

    def _play_note(self, pitch):
        now = time.perf_counter()
        self.flash_until = now + FLASH_TIME
        self.flash_pitch = pitch if pitch in self.pitch_colour else None
        for m in self.monsters:
            if m is not self.joe and m.pitch == pitch:
                m.kick = 1.0
        if self.joe.rect.width and self.flash_pitch:
            cell = CELL_QUAVER
            s = self.note_sprites.get((pitch, cell))
            if s:
                self.particles.append({
                    "surf": s.copy(),
                    "x": self.joe.rect.centerx - s.get_width() // 2 + random.randint(-8, 8) * self.scale,
                    "y": self.joe.rect.top + 10 * self.scale,
                    "vx": random.uniform(-10, 10) * self.scale,
                    "age": 0.0,
                })

    def _antenna_pos(self):
        if not self.joe.rect.width:
            return (self.win_w // 2, self.win_h // 2)
        return (self.joe.rect.left + JOE_ANTENNA[0] * self.scale,
                self.joe.rect.top + JOE_ANTENNA[1] * self.scale)

    def _spawn_wave(self):
        side = random.random()
        if side < 0.5:                                        # top edge (below the text panel)
            x, y = random.uniform(0, self.win_w), TOP_MARGIN + random.uniform(0, 40)
        elif side < 0.75:
            x, y = -20, random.uniform(TOP_MARGIN, self.win_h)
        else:
            x, y = self.win_w + 20, random.uniform(TOP_MARGIN, self.win_h)
        tint = self.flash_pitch if (self.flash_pitch and time.perf_counter() < self.flash_until) else "white"
        self.waves.append({"x": x, "y": y, "tint": tint})

    # ------------------------------------------------------------------ hooks
    def frame_for(self, m):
        if m is self.joe:
            return self.joe_frames[self.flash_pitch if m.singing else None]
        key = (m.pitch, m.kind)
        if key not in self.tinted:
            self.tinted[key] = tuple(recolour(f, self.pitch_colour[m.pitch]) for f in self.frames[m.kind])
        dancing = self._dance_phase() is not None
        mouth = 0
        if dancing:
            phase = self._dance_phase() + m.offset
            if m.style == 1:
                mouth = int(phase) % 2
            elif m.style == 2:
                mouth = int(phase / 2) % 2
        if m.kick > 0.5:
            mouth = 1
        return self.tinted[key][mouth]

    def _dance_phase(self):
        """Beats since the message started, or None when nothing is playing."""
        if self.message_started is None:
            return None
        return (time.perf_counter() - self.message_started) / self.beat

    def offset_for(self, m):
        if m is self.joe:
            return 0, 0
        phase = self._dance_phase()
        s = self.scale
        if phase is None:
            return int(math.sin(m.phase * 0.7 + m.offset) * 1.5 * s), 0           # idle sway
        p = phase + m.offset / math.tau
        if m.style == 0:
            lift = abs(math.sin(math.pi * p)) * 4 * s
            dx = math.sin(math.pi * p / 2) * 2 * s
        elif m.style == 1:
            lift = abs(math.sin(math.pi * p / 2)) * 6 * s
            dx = 0
        else:
            lift = (1 - abs((p % 2) - 1)) * 3 * s
            dx = math.cos(math.pi * p / 2) * 3 * s
        lift += m.kick * 8 * s
        return int(dx), int(lift)

    # ------------------------------------------------------------------ draw
    def _draw_monster(self, m):
        if m is not self.joe:
            return super()._draw_monster(m)
        sx, sy = self.grid_to_screen(m.gx, m.gy, m.height)
        foot_x, foot_y = sx, sy + (TILE_TOP_H // 2) * self.scale
        frame = self.frame_for(m)
        shadow = pygame.transform.scale(self.shadow, (24 * self.scale, 8 * self.scale))
        self.screen.blit(shadow, shadow.get_rect(center=(foot_x, foot_y)))
        x = foot_x - JOE_W * self.scale // 2
        y = foot_y - JOE_FEET * self.scale
        m.rect = self.screen.blit(frame, (x, y))
        # antenna glow
        level = self.source.level if self.source else 0.0
        glow = 0.25 + 0.75 * level + (0.6 if m.singing else 0.0)
        ax, ay = self._antenna_pos()
        col = self.pitch_colour.get(self.flash_pitch, pygame.Color(230, 230, 255)) if m.singing else pygame.Color(230, 230, 255)
        r = int((3 + 5 * glow) * self.scale)
        halo = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
        pygame.draw.circle(halo, (col.r, col.g, col.b, int(60 * glow)), (r * 2, r * 2), r * 2)
        pygame.draw.circle(halo, (col.r, col.g, col.b, int(160 * min(1, glow))), (r * 2, r * 2), r)
        self.screen.blit(halo, halo.get_rect(center=(ax, ay)))

    def _draw_notes(self, m, cx, top_y):
        pass

    def draw_overlay(self):
        target = self._antenna_pos()
        for w in self.waves:
            ang = math.degrees(math.atan2(-(target[1] - w["y"]), target[0] - w["x"]))
            surf = pygame.transform.rotate(self.wave_tints[w["tint"]], ang - 180)
            self.screen.blit(surf, surf.get_rect(center=(int(w["x"]), int(w["y"]))))
        for p in self.particles:
            fade = 1.0 - p["age"] / PARTICLE_LIFE
            p["surf"].set_alpha(int(255 * min(1.0, fade * 1.5)))
            self.screen.blit(p["surf"], (int(p["x"]), int(p["y"])))

    def _draw_hud(self):
        src = self.source
        panel = pygame.Surface((self.win_w, TOP_MARGIN), pygame.SRCALPHA)
        panel.fill((8, 8, 18, 200))
        self.screen.blit(panel, (0, 0))
        pygame.draw.line(self.screen, (90, 80, 130), (0, TOP_MARGIN - 1), (self.win_w, TOP_MARGIN - 1))

        label = self.small_font.render("Incoming transmission:", True, (170, 170, 200))
        self.screen.blit(label, (20, 12))

        # previous message, dim
        history = src.history if src else []
        if history:
            prev = self.small_font.render(history[-1][-100:], True, (120, 120, 150))
            self.screen.blit(prev, (20, 32))

        box = pygame.Rect(20, 52, self.win_w - 40, 44)
        pygame.draw.rect(self.screen, (24, 24, 40), box, border_radius=6)
        pygame.draw.rect(self.screen, (120, 110, 170), box, 2, border_radius=6)
        text = src.text if src else ""
        caret = "|" if (src and src.active and (pygame.time.get_ticks() // 400) % 2 == 0) else ""
        surf = self.big_font.render(text + caret, True, (240, 240, 250))
        inner = box.inflate(-20, -12)
        x = inner.x if surf.get_width() <= inner.width else inner.right - surf.get_width()
        self.screen.set_clip(inner)
        self.screen.blit(surf, (x, inner.y + (inner.height - surf.get_height()) // 2))
        self.screen.set_clip(None)

        # status + level meter
        status = src.status if src else "starting"
        pretty = {"loading model": "loading the ear model...",
                  "listening": "listening, waiting for a message",
                  "receiving": "receiving",
                  "done": "message complete",
                  "demo": "demo"}.get(status, status)
        notes = len(src.notes) if src else 0
        scale = self.composer.scale
        info = f"{scale.key} {scale.scale_type}  |  {pretty}  |  {notes} notes heard  |  mic: {src.device_name if src else '?'}"
        if getattr(src, "silent_for", 0.0) > 2.0:
            info += "  |  MIC SILENT - check it is unmuted and the default input"
        self.screen.blit(self.small_font.render(info, True, (190, 190, 215)), (20, 106))
        meter = pygame.Rect(20, 128, 200, 10)
        pygame.draw.rect(self.screen, (40, 40, 60), meter, border_radius=3)
        lvl = src.level if src else 0.0
        if lvl > 0:
            fill = meter.copy()
            fill.width = int(meter.width * lvl)
            pygame.draw.rect(self.screen, (120, 220, 140), fill, border_radius=3)
        self.screen.blit(self.small_font.render("mic level", True, (150, 150, 175)), (228, 124))

        keys = "[R] shuffle crowd   [Esc] quit"
        if isinstance(src, DemoSource):
            keys = f"[Space] replay   [ / ] sync offset: {int(self.latency * 1000)} ms   " + keys
        self.screen.blit(self.font.render(keys, True, (150, 150, 175)), (12, self.win_h - 28))

    def run(self):
        try:
            while self.step():
                pass
        finally:
            if self.source:
                self.source.stop()
            pygame.quit()


# ============================================================================ main
def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    demo_text, silent, device = None, False, None
    if "--demo" in args:
        i = args.index("--demo")
        demo_text = args[i + 1] if i + 1 < len(args) else "Hello earth"
        del args[i:i + 2]
    if "--silent" in args:
        silent = True
        args.remove("--silent")
    if "--device" in args:
        i = args.index("--device")
        device = int(args[i + 1])
        del args[i:i + 2]

    composer = Avison.Composer(Settings.KEY, Settings.SCALE_TYPE)
    if demo_text is not None:
        factory = lambda planet: DemoSource(composer, demo_text, play_audio=not silent, latency=planet.latency)
    else:
        factory = lambda planet: MicSource(composer, device=device)
    ReceiverPlanet(composer, factory).run()


if __name__ == "__main__":
    main()
