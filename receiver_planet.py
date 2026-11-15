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
WINDOW = (1280, 900)
TOP_MARGIN = 96                              # status panel height
TEXT_TOP = TOP_MARGIN + 80                   # first line of floating letters
TEXT_LINE_H = 36
TEXT_MARGIN = 60
ISLAND_TOP = TOP_MARGIN + 110                # island is centred below the floating text
LETTER_FLIGHT = 0.7                          # seconds a letter takes to reach its slot
LETTER_FADE = 1.2                            # seconds an old message takes to fade out
GRID = 15
BASE_CROWD = 3                               # aliens already there before a message
MAX_CROWD = 18
JOIN_EVERY = 6                               # a new alien wanders in every N notes heard
WALK_SPEED = 1.6                             # tiles per second
LEAVE_AFTER = 6.0                            # seconds after a message ends before the party thins out
JOE_KIND = -1

MIC_SR = 22050                               # what the model was trained on (common.SR)
LEVEL_FLOOR, LEVEL_CEIL = 0.004, 0.12        # mic RMS mapped to 0..1 for the wave effect
WAVE_SPEED = 420                             # px/s
FLASH_TIME = 0.35                            # Joe stays lit this long after a note
PARTICLE_LIFE = 1.1


START_MARK = "`"                             # Encoder puts this before every message


def after_start_mark(decoded):
    """The message proper: everything after the first start mark, or '' if it has not arrived yet.

    The sender begins every message with a backtick. Nothing is shown until it has been
    decoded, and the mark itself is never shown. Anything decoded before it is dropped.
    """
    at = decoded.find(START_MARK)
    return decoded[at + 1:] if at >= 0 else ""


# ============================================================================ sources
class MicSource:
    """Microphone + trained model, run in a background thread.

    Attributes read by the UI (all plain values, swapped atomically):
        status   'loading model', 'listening', 'waiting for start', 'receiving', 'done', 'error: ...'
        level    0..1 loudness right now
        notes    note names heard so far in the current message
        text     decoded text of the current message, from after its start mark
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
                    self.text = after_start_mark(receiver.text)
                    self.active = receiver.clock is not None
                    if receiver.finished:
                        self.status = "done"
                        if self.text:
                            self.history.append(self.text)
                        done_at = time.perf_counter()
                    elif self.active:
                        # notes are arriving, but nothing counts until the start mark is decoded
                        self.status = "receiving" if START_MARK in receiver.text else "waiting for start"
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
            decoded = "".join(self.table.get(",".join(sure[i:i + self.size]), "?")
                              for i in range(0, len(sure), self.size))
            self.text = after_start_mark(decoded)
        sounding = any(s <= t < s + m["duration"] * 60 / Settings.TEMPO for s, m in zip(self.starts, self.metadata))
        self.level = 0.8 if sounding else 0.0
        was_active = self.active
        self.active = 0 <= t <= self.song_end
        if was_active and not self.active and self.text:
            self.history.append(self.text)
            self.status = "done"
        elif self.active:
            self.status = "receiving" if len(self.notes) >= self.size else "waiting for start"   # the mark is the first character


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
        self.letters = []            # letters of the current message, flying or settled
        self.old_letters = []        # letters of the previous message, fading out
        self.seen_text = ""
        self.party_over_at = None
        self.beat = 60.0 / Settings.TEMPO
        self.latency = self._load_latency()

        super().__init__(seed=1, scale=VIEW_SCALE, window=WINDOW)
        pygame.display.set_caption("Receiver Planet")
        self.big_font = pygame.font.SysFont("consolas", 26)
        self.letter_font = pygame.font.SysFont("consolas", 30, bold=True)
        self.char_w = self.letter_font.size("M")[0]
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
        self.center_island(top_margin=ISLAND_TOP)

    def shuffle_crowd(self):
        """Reset to the small base crowd standing around Joe."""
        self.monsters = [self.joe]
        c = (GRID - 1) / 2
        self.spots = [t for t in self.tiles
                      if 2.0 <= math.hypot(t[0] - c, t[1] - c) <= 0.85 * c]
        self.shore = [t for t in self.tiles
                      if any((t[0] + dx, t[1] + dy) not in self.tiles
                             for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
        self.kinds = list(range(NUM_TYPES))
        random.shuffle(self.kinds)
        self.next_kind = 0
        for _ in range(BASE_CROWD):
            spot = self._free_spot()
            if spot:
                self._new_alien(spot, spot)

    def aliens(self):
        return [m for m in self.monsters if m is not self.joe]

    def _free_spot(self):
        taken = {(round(m.gx), round(m.gy)) for m in self.monsters}
        taken |= {m.walk["to"] for m in self.aliens() if m.walk}
        free = [t for t in self.spots if t not in taken]
        return random.choice(free) if free else None

    def _shore_near(self, spot):
        """A shore tile on the same side of the island as spot, so walks are short."""
        c = (GRID - 1) / 2
        ang = math.atan2(spot[1] - c, spot[0] - c)
        def diff(t):
            a = math.atan2(t[1] - c, t[0] - c)
            return abs((a - ang + math.pi) % math.tau - math.pi)
        near = sorted(self.shore, key=diff)[:6]
        return random.choice(near)

    def _new_alien(self, start, target):
        kind = self.kinds[self.next_kind % len(self.kinds)]
        self.next_kind += 1
        m = Monster(kind, start[0], start[1], self.tiles[start])
        m.auto = False
        m.pitch = self.note_table[(self.next_kind * 3) % len(self.note_table)]
        m.style = random.randrange(3)
        m.offset = random.uniform(0, math.tau)
        m.kick = 0.0
        m.leaving = False
        m.walk = None
        if start != target:
            self._send(m, target)
        self.monsters.append(m)
        return m

    def _send(self, m, target):
        dist = math.hypot(target[0] - m.gx, target[1] - m.gy)
        m.walk = {"from": (m.gx, m.gy), "to": target, "t": 0.0, "dur": max(0.3, dist / WALK_SPEED)}

    def _alien_arrives(self):
        spot = self._free_spot()
        if spot is None or len(self.aliens()) >= MAX_CROWD:
            return
        self._new_alien(self._shore_near(spot), spot)

    def _party_thins(self):
        """Everyone beyond the base crowd wanders back to the shore."""
        settled = [m for m in self.aliens() if not m.leaving]
        for m in settled[BASE_CROWD:]:
            m.leaving = True
            self._send(m, self._shore_near((round(m.gx), round(m.gy))))

    def _update_walkers(self, dt):
        for m in self.aliens():
            if not m.walk:
                continue
            w = m.walk
            w["t"] = min(1.0, w["t"] + dt / w["dur"])
            p = w["t"]
            m.gx = w["from"][0] + (w["to"][0] - w["from"][0]) * p
            m.gy = w["from"][1] + (w["to"][1] - w["from"][1]) * p
            m.height = self.tiles.get((round(m.gx), round(m.gy)), m.height)
            if p >= 1.0:
                m.gx, m.gy = w["to"]
                m.walk = None
                if m.leaving:
                    self.monsters.remove(m)

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
                self._retire_letters()
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

        # new characters -> Joe emits them as floating letters
        text = src.text
        if not text.startswith(self.seen_text):          # a new message began
            self._retire_letters()
        for i in range(len(self.seen_text), len(text)):
            self._emit_letter(i, text[i])
        self.seen_text = text
        for L in self.letters:
            L["t"] = min(1.0, L["t"] + dt / LETTER_FLIGHT)
        for L in self.old_letters:
            L["fade"] += dt / LETTER_FADE
        self.old_letters = [L for L in self.old_letters if L["fade"] < 1.0]

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

        # the party grows as the transmission goes on, and thins out after it
        if src.active:
            self.party_over_at = None
            wanted = min(MAX_CROWD, BASE_CROWD + self.seen_notes // JOIN_EVERY)
            if len([m for m in self.aliens() if not m.leaving]) < wanted:
                self._alien_arrives()
        elif self.party_over_at is None and len(self.aliens()) > BASE_CROWD:
            self.party_over_at = now
        elif self.party_over_at is not None and now - self.party_over_at > LEAVE_AFTER:
            self._party_thins()
            self.party_over_at = None
        self._update_walkers(dt)

        # dancers
        for m in self.aliens():
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

    def _slot(self, index, total=None):
        """Screen position of the index-th character of the floating message.

        Each line is centred over the island, so slots shift a little as the
        last line grows; settled letters glide to follow.
        """
        total = len(self.seen_text) if total is None else total
        per_line = max(1, (self.win_w - 2 * TEXT_MARGIN) // self.char_w)
        line, col = divmod(index, per_line)
        on_line = per_line if (line + 1) * per_line <= total else total - line * per_line
        x0 = self.origin_x - on_line * self.char_w / 2
        return x0 + col * self.char_w, TEXT_TOP + line * TEXT_LINE_H

    def _emit_letter(self, index, ch):
        colour = self.pitch_colour.get(self.flash_pitch) if self.flash_pitch else None
        col = pygame.Color(240, 240, 250)
        if colour is not None:                      # tint towards the note that finished it
            col = pygame.Color((col.r + colour.r) // 2, (col.g + colour.g) // 2, (col.b + colour.b) // 2)
        surf = self.letter_font.render(ch, True, col) if ch.strip() else None
        sx, sy = self._antenna_pos()
        tx, ty = self._slot(index)
        self.letters.append({"ch": ch, "surf": surf, "sx": sx, "sy": sy, "tx": tx, "ty": ty,
                             "t": 0.0, "index": index, "fade": 0.0})

    def _retire_letters(self):
        for L in self.letters:
            L["t"] = 1.0
        self.old_letters = self.letters
        self.letters = []
        self.seen_text = ""

    def _draw_letters(self):
        now = time.perf_counter()
        for L in self.old_letters + self.letters:
            if L["surf"] is None:
                continue
            p = L["t"]
            if L["fade"] == 0:                      # follow the centred slot as the line grows
                tx, ty = self._slot(L["index"])
                L["tx"] += (tx - L["tx"]) * 0.2
                L["ty"] = ty
            ease = 1 - (1 - p) ** 3
            x = L["sx"] + (L["tx"] - L["sx"]) * ease
            y = L["sy"] + (L["ty"] - L["sy"]) * ease - math.sin(math.pi * p) * 35
            if p >= 1.0:                            # settled: gentle wave along the line
                y += math.sin(now * 2.2 + L["index"] * 0.45) * 3
            y += L["fade"] * 30                     # old message sinks as it fades
            if L["fade"] > 0:
                L["surf"].set_alpha(int(255 * (1.0 - L["fade"])))
            self.screen.blit(L["surf"], (int(x), int(y)))
        # caret after the last letter while receiving
        src = self.source
        if src and src.active and (pygame.time.get_ticks() // 400) % 2 == 0:
            cx, cy = self._slot(len(self.seen_text))
            pygame.draw.rect(self.screen, (200, 200, 230), (cx, cy + 4, 3, TEXT_LINE_H - 10))

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
        dancing = self._dance_phase() is not None and not m.walk
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
        if m.walk:                                                             # walking: little hops
            return 0, int(abs(math.sin(m.walk["t"] * m.walk["dur"] * 9)) * 2 * s)
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
        self._draw_letters()
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
        history = src.history if src else []
        if history:
            prev = self.small_font.render("previous: " + history[-1][-90:], True, (120, 120, 150))
            self.screen.blit(prev, (20, 32))

        # status + level meter
        status = src.status if src else "starting"
        pretty = {"loading model": "loading the ear model...",
                  "listening": "listening, waiting for a message",
                  "waiting for start": "hearing notes, waiting for the start signal",
                  "receiving": "receiving",
                  "done": "message complete",
                  "demo": "demo"}.get(status, status)
        notes = len(src.notes) if src else 0
        scale = self.composer.scale
        info = (f"{scale.key} {scale.scale_type}  |  {pretty}  |  {notes} notes heard  |  "
                f"{len(self.aliens())} at the party  |  mic: {src.device_name if src else '?'}")
        if getattr(src, "silent_for", 0.0) > 2.0:
            info += "  |  MIC SILENT - check it is unmuted and the default input"
        self.screen.blit(self.small_font.render(info, True, (190, 190, 215)), (20, 54))
        meter = pygame.Rect(20, 76, 200, 10)
        pygame.draw.rect(self.screen, (40, 40, 60), meter, border_radius=3)
        lvl = src.level if src else 0.0
        if lvl > 0:
            fill = meter.copy()
            fill.width = int(meter.width * lvl)
            pygame.draw.rect(self.screen, (120, 220, 140), fill, border_radius=3)
        self.screen.blit(self.small_font.render("mic level", True, (150, 150, 175)), (228, 72))

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
