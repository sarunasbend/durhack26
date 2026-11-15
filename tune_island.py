"""
tune_island.py - type a message, watch an island of monsters grow, hear it sing.

Every keystroke is encoded with the project's Composer (Avison.py) into a note
stream. The island is rebuilt from that stream:

    * one monster per distinct pitch in the tune (busy pitches get extra copies)
    * a big monster in the middle for the drone
    * monsters placed around a ring in circle-of-fifths order, so pitches that
      harmonise sit next to each other
    * the island footprint grows with the length of the message

After you pause typing the tune is written to MIDI via Transmitter and played
with pygame.mixer. Monsters switch to their singing frame exactly when their
note sounds, and a tinted note sprite (assets/notes.png) floats up from them.

Run:
    python tune_island.py [key] [scale] [--latency 0.2]   e.g. python tune_island.py f# major-pentatonic

Controls:
    type        edit the message (island rebuilds live, song restarts after a pause)
    Enter       replay from the start
    [ / ]       nudge the sync offset (visuals wait for slow audio devices,
                e.g. Bluetooth headphones); remembered between runs
    Ctrl+Bksp   delete the last word
    Esc / close quit
"""

import json
import os
import random
import sys
import tempfile
import time
import zlib
from collections import Counter

import pygame

import Avison
from Characters import Characters
from Notes import Notes
from Transmitter import Transmitter
import monster_land as ml
from monster_land import MonsterLand, Monster, NUM_TYPES

NOTES_PATH = os.path.join(ml.ASSET_DIR, "notes.png")
NOTE_CELL = 16                   # notes.png is 3 cells of 16x16
CELL_QUAVER, CELL_CROTCHET, CELL_PAIR = 0, 1, 2

DRONE_KIND = 9                   # the big round blob
BODY_GREY = (97, 97, 97)         # sprite palette: body fill
LOW_OCTAVE_BRIGHTNESS = 50       # HSV value (%) of the lowest octave; top octave is 100
SHADE_GREY = (66, 66, 66)        # sprite palette: shaded fill
PITCH_KINDS = [k for k in range(NUM_TYPES) if k != DRONE_KIND]

TOP_MARGIN = 128                 # text panel height
VIEW_SCALE = 2                   # sprite scale (island can reach 13x13)
WINDOW = (1024, 800)
TEMPO = 200
RETYPE_DELAY = 0.7               # seconds of quiet typing before the song (re)starts
LOOP_GAP = 1.0                   # pause before the song loops
MAX_MONSTERS = 18
MIN_SING = 0.24                  # shortest visible sing, seconds (quavers are 0.3s apart)
DEFAULT_LATENCY = 0.15           # seconds the visuals wait for the audio device
LATENCY_STEP = 0.02
SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".tune_island.json")
PARTICLE_LIFE = 1.1

PITCH_CLASS = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
               "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def split_note(name):
    """'F#4' -> ('F#', 4)"""
    return name[:-1], int(name[-1])


def fifths_key(name):
    """Sort key placing pitches a fifth apart next to each other."""
    pc, octave = split_note(name)
    return ((PITCH_CLASS[pc] * 7) % 12, octave)



def pitch_colours(note_table, degrees, drone_note=None):
    """Colour per pitch name: scale degree sets the hue, octave sets brightness
    only (dark low octave -> bright high octave), so F#4 and F#5 share a hue."""
    colours = {}
    degrees = max(1, degrees)
    octaves = max(1, len(note_table) // degrees)
    for i, name in enumerate(note_table):
        degree, octave = i % degrees, i // degrees
        t = octave / max(1, octaves - 1)
        col = pygame.Color(0)
        col.hsva = (degree * 300 / degrees, 85,
                    LOW_OCTAVE_BRIGHTNESS + (100 - LOW_OCTAVE_BRIGHTNESS) * t, 100)
        colours[name] = col
    if drone_note:
        colours[drone_note] = pygame.Color(225, 225, 240)
    return colours


def recolour(frame, colour):
    """Swap the sprite sheets' body grey (97) and shade grey (66) for a colour."""
    h, s, v, _ = colour.hsva
    body = pygame.Color(0)
    body.hsva = (h, min(100, s), v, 100)
    shade = pygame.Color(0)
    shade.hsva = (h, min(100, s + 10), v * 0.6, 100)
    out = frame.copy()
    px = pygame.PixelArray(out)
    px.replace(BODY_GREY, body)
    px.replace(SHADE_GREY, shade)
    px.close()
    return out


def load_note_cells(scale):
    """The three glyphs in notes.png (quaver, crotchet, beamed pair), scaled."""
    sheet = pygame.image.load(NOTES_PATH).convert_alpha()
    return [pygame.transform.scale_by(
        sheet.subsurface(pygame.Rect(i * NOTE_CELL, 0, NOTE_CELL, NOTE_CELL)), scale) for i in range(3)]


class SingEvent:
    __slots__ = ("start", "end", "monster", "cell", "fired")

    def __init__(self, start, end, monster, cell):
        self.start = start
        self.end = end
        self.monster = monster
        self.cell = cell
        self.fired = False


class TuneIsland(MonsterLand):
    def __init__(self, composer, tempo=TEMPO, latency=None):
        self.composer = composer
        self.tempo = tempo
        self.latency = latency if latency is not None else self._load_latency()
        cfg = composer.configuration
        notes = Notes()
        notes.create_note_table(composer.scale, cfg.octaves, cfg.first_octave)
        self.note_table = notes.notes                 # e.g. ['F#4', 'G#4', ...]
        self.drone_note = composer.scale.key + "2"
        chars = Characters()
        chars.load_character_set()
        self.allowed = set(chars.characters) - {"\n"}

        self.text = ""
        self.encoded = []
        self.metadata = []
        self.events = []
        self.song_end = 0.0
        self.playing = False
        self.play_started = 0.0
        self.dirty_since = None
        self.particles = []
        self.midi_path = os.path.join(tempfile.gettempdir(), "tune_island.mid")
        self.audio_ok = False

        super().__init__(seed=0, scale=VIEW_SCALE, window=WINDOW)   # loads assets, calls generate()
        pygame.display.set_caption("Tune Island")
        self.big_font = pygame.font.SysFont("consolas", 26)
        self.small_font = pygame.font.SysFont("consolas", 15)
        self._init_audio()
        self._load_note_sprites()
        pygame.key.start_text_input()

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _load_latency():
        try:
            with open(SETTINGS_PATH) as f:
                return float(json.load(f).get("latency", DEFAULT_LATENCY))
        except (OSError, ValueError):
            return DEFAULT_LATENCY

    def set_latency(self, value):
        self.latency = max(0.0, min(0.8, round(value, 3)))
        try:
            with open(SETTINGS_PATH, "w") as f:
                json.dump({"latency": self.latency}, f)
        except OSError:
            pass

    def _init_audio(self):
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self.audio_ok = True
        except pygame.error as exc:
            print(f"[tune_island] audio unavailable: {exc}")
            self.audio_ok = False

    def _load_note_sprites(self):
        """Slice notes.png and tint one copy per pitch (plus one for the drone)."""
        sheet = pygame.image.load(NOTES_PATH).convert_alpha()
        cells = []
        for i in range(3):
            cell = sheet.subsurface(pygame.Rect(i * NOTE_CELL, 0, NOTE_CELL, NOTE_CELL))
            cells.append(pygame.transform.scale_by(cell, self.scale))
        self.note_sprites = {}        # (pitch_name, cell) -> tinted surface
        self.pitch_colour = pitch_colours(self.note_table, len(self.composer.scale.scale), self.drone_note)
        self.tinted = {}              # (pitch, kind) -> (idle, singing) recoloured frames
        for name, col in self.pitch_colour.items():
            for c, cell in enumerate(cells):
                tinted = cell.copy()
                tinted.fill(col, special_flags=pygame.BLEND_RGB_MAX)
                self.note_sprites[(name, c)] = tinted

    # ------------------------------------------------------------------ world
    def generate(self):
        """Called by MonsterLand.__init__ and whenever the text changes."""
        self.build_island()

    def _encode(self):
        if not self.text:
            return [], []
        try:
            return self.composer.encode_message(self.text)
        except KeyError as exc:
            print(f"[tune_island] cannot encode {exc}")
            return [], []

    def build_island(self):
        self.encoded, self.metadata = self._encode()
        encoded = self.encoded
        beat = 60.0 / self.tempo

        # --- timeline, replicating Transmitter.write's clock arithmetic
        starts = []
        clock = 0.0
        for meta in self.metadata:
            start = clock + meta.get("previous", 0)
            starts.append(start)
            clock = start + meta.get("time", 0)
        song_end_beats = max((s + m["duration"] for s, m in zip(starts, self.metadata)),
                             default=0.0)
        self.song_end = song_end_beats * beat

        # --- which monsters: one per pitch, extra copies for busy pitches
        counts = Counter(encoded)
        distinct = [p for p in self.note_table if p in counts]
        copies = {p: 1 for p in distinct}
        if distinct:
            mean = len(encoded) / len(distinct)
            budget = MAX_MONSTERS - 1 - len(distinct)      # keep a slot for the drone
            for p in sorted(distinct, key=lambda q: -counts[q]):
                extra = min(2, int(counts[p] // (2 * mean))) if mean else 0
                extra = min(extra, max(0, budget))
                copies[p] += extra
                budget -= extra

        # --- terrain: footprint grows with the tune (and never crowds the cast),
        #     shape fixed by the opening characters so it stays put while typing
        cast = sum(copies.values()) + 1
        n = max(6, min(13, max(6 + len(encoded) // 24, 5 + cast // 2)))
        seed = zlib.crc32(self.text[:4].encode("utf-8"))
        rng = random.Random(seed)
        self.build_terrain(n, rng)

        # --- placement: ring in circle-of-fifths order, drone in the middle
        self.monsters = []
        self.pitch_monsters = {}
        c = (n - 1) / 2
        ring = [(gx, gy) for (gx, gy) in self.tiles
                if 0.4 * c <= ((gx - c) ** 2 + (gy - c) ** 2) ** 0.5 <= 0.9 * c]
        if len(ring) < sum(copies.values()):
            ring = list(self.tiles)
        ring.sort(key=lambda p: -_angle(p, c))        # clockwise from the back

        order = sorted(distinct, key=fifths_key)
        slots = [p for p in order for _ in range(copies[p])]
        used = set()
        for i, pitch in enumerate(slots):
            if not ring:
                break
            j = int(i * len(ring) / len(slots))
            # step forward to the next free ring tile
            for k in range(len(ring)):
                tile = ring[(j + k) % len(ring)]
                if tile not in used:
                    used.add(tile)
                    break
            kind = PITCH_KINDS[self.note_table.index(pitch) % len(PITCH_KINDS)]
            self._add_monster(kind, tile, pitch)

        self.drone_monster = None
        if encoded and self.drone_note:
            centre = min((t for t in self.tiles if t not in used),
                         key=lambda t: (t[0] - c) ** 2 + (t[1] - c) ** 2, default=None)
            if centre is not None:
                self.tiles[centre] += 1                   # pedestal
                self.drone_monster = self._add_monster(DRONE_KIND, centre, self.drone_note)

        # --- sing events
        self.events = []
        occurrence = Counter()
        for i, (note, meta) in enumerate(zip(encoded, self.metadata)):
            owners = self.pitch_monsters.get(note)
            if not owners:
                continue
            idx = owners[occurrence[note] % len(owners)]
            occurrence[note] += 1
            start = starts[i] * beat
            end = start + max(meta["duration"] * beat, MIN_SING)
            cell = CELL_QUAVER if meta["duration"] <= 0.5 else CELL_CROTCHET
            self.events.append(SingEvent(start, end, idx, cell))
        if self.drone_monster is not None:
            for i in range(0, len(starts), 8):
                start = starts[i] * beat
                end = (starts[i + 8] if i + 8 < len(starts) else song_end_beats) * beat
                self.events.append(SingEvent(start, end, self.drone_monster, CELL_PAIR))
        self.events.sort(key=lambda e: e.start)

        self.particles = []
        self.center_island(top_margin=TOP_MARGIN)

    def _add_monster(self, kind, tile, pitch):
        gx, gy = tile
        m = Monster(kind, gx, gy, self.tiles[tile])
        m.auto = False
        m.pitch = pitch
        self.monsters.append(m)
        idx = len(self.monsters) - 1
        self.pitch_monsters.setdefault(pitch, []).append(idx)
        return idx

    # ------------------------------------------------------------------ audio
    def stop_playback(self):
        self.playing = False
        for m in self.monsters:
            m.singing = False
        if self.audio_ok:
            try:
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
            except pygame.error:
                pass

    def _write_midi(self):
        tr = Transmitter()
        tr.tempo = self.tempo
        tr.drone = self.drone_note
        tr.config()
        tr.write(self.encoded, self.metadata, None, 0)
        tr.save(self.midi_path)

    def start_playback(self):
        """(Re)generate the MIDI for the current text and play it from the top."""
        self.stop_playback()
        if not self.events:
            return
        for e in self.events:
            e.fired = False
        if self.audio_ok:
            try:
                self._write_midi()
                pygame.mixer.music.load(self.midi_path)
                pygame.mixer.music.play()
            except Exception as exc:          # no MIDI synth, locked file, ...
                print(f"[tune_island] playback failed: {exc}")
        self.play_started = time.perf_counter()
        self.playing = True

    # ------------------------------------------------------------------ input
    def _set_text(self, text):
        if text == self.text:
            return
        self.text = text
        self.stop_playback()
        self.build_island()
        self.dirty_since = time.perf_counter()

    def handle_event(self, ev):
        if ev.type == pygame.QUIT:
            return False
        if ev.type == pygame.TEXTINPUT:
            clean = "".join(ch for ch in ev.text if ch in self.allowed)
            if clean:
                self._set_text(self.text + clean)
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                return False
            if ev.key == pygame.K_BACKSPACE:
                if ev.mod & pygame.KMOD_CTRL:
                    words = self.text.rstrip()
                    self._set_text(words.rsplit(" ", 1)[0] + " " if " " in words else "")
                else:
                    self._set_text(self.text[:-1])
            elif ev.key == pygame.K_RETURN:
                self.dirty_since = None
                self.start_playback()
            elif ev.key == pygame.K_LEFTBRACKET:
                self.set_latency(self.latency - LATENCY_STEP)
            elif ev.key == pygame.K_RIGHTBRACKET:
                self.set_latency(self.latency + LATENCY_STEP)
        return True

    # ------------------------------------------------------------------ update
    def update(self, dt):
        now = time.perf_counter()
        if self.dirty_since is not None and now - self.dirty_since >= RETYPE_DELAY:
            self.dirty_since = None
            self.start_playback()

        if self.playing:
            # visuals run `latency` behind the mixer clock so they land when the
            # sound actually leaves the speakers / headphones
            t = now - self.play_started - self.latency
            if t > self.song_end + LOOP_GAP:
                self.start_playback()
                t = 0.0
            active = set()
            for e in self.events:
                if e.start > t:
                    break
                if t < e.end:
                    active.add(e.monster)
                    if not e.fired:
                        e.fired = True
                        self._spawn_note(e)
            for i, m in enumerate(self.monsters):
                m.singing = i in active

        super().update(dt)

        for p in self.particles:
            p["age"] += dt
            p["y"] -= 28 * self.scale * dt
            p["x"] += p["vx"] * dt
        self.particles = [p for p in self.particles if p["age"] < PARTICLE_LIFE]

    def _spawn_note(self, event):
        m = self.monsters[event.monster]
        if m.rect.width == 0:
            return
        surf = self.note_sprites.get((m.pitch, event.cell))
        if surf is None:
            return
        self.particles.append({
            "surf": surf.copy(),
            "x": m.rect.centerx - surf.get_width() // 2 + random.randint(-3, 3) * self.scale,
            "y": m.rect.top - 4 * self.scale,
            "vx": random.uniform(-6, 6) * self.scale,
            "age": 0.0,
        })

    # ------------------------------------------------------------------ draw
    def frame_for(self, m):
        """Monsters wear the colour of their pitch (same ramp as the notes)."""
        key = (m.pitch, m.kind)
        if key not in self.tinted:
            self.tinted[key] = tuple(self._recolour(f, self.pitch_colour[m.pitch])
                                     for f in self.frames[m.kind])
        return self.tinted[key][1 if m.singing else 0]

    @staticmethod
    def _recolour(frame, colour):
        return recolour(frame, colour)

    def _draw_notes(self, m, cx, top_y):
        pass  # replaced by sprite particles in draw_overlay

    def draw_overlay(self):
        for p in self.particles:
            fade = 1.0 - p["age"] / PARTICLE_LIFE
            p["surf"].set_alpha(int(255 * min(1.0, fade * 1.5)))
            self.screen.blit(p["surf"], (int(p["x"]), int(p["y"])))

    def _draw_hud(self):
        # top panel
        panel = pygame.Surface((self.win_w, TOP_MARGIN), pygame.SRCALPHA)
        panel.fill((8, 8, 18, 200))
        self.screen.blit(panel, (0, 0))
        pygame.draw.line(self.screen, (90, 80, 130), (0, TOP_MARGIN - 1), (self.win_w, TOP_MARGIN - 1))

        label = self.small_font.render("Type a message for the monsters to sing:", True, (170, 170, 200))
        self.screen.blit(label, (20, 14))

        box = pygame.Rect(20, 38, self.win_w - 40, 44)
        pygame.draw.rect(self.screen, (24, 24, 40), box, border_radius=6)
        pygame.draw.rect(self.screen, (120, 110, 170), box, 2, border_radius=6)
        caret = "|" if (pygame.time.get_ticks() // 500) % 2 == 0 else " "
        text_surf = self.big_font.render(self.text + caret, True, (240, 240, 250))
        inner = box.inflate(-20, -12)
        x = inner.x
        if text_surf.get_width() > inner.width:   # show the tail while typing
            x = inner.right - text_surf.get_width()
        self.screen.set_clip(inner)
        self.screen.blit(text_surf, (x, inner.y + (inner.height - text_surf.get_height()) // 2))
        self.screen.set_clip(None)

        # status line
        scale = self.composer.scale
        if self.playing:
            t = min(max(0.0, time.perf_counter() - self.play_started - self.latency), self.song_end)
            status = f"playing {t:4.1f}s / {self.song_end:4.1f}s"
        elif self.dirty_since is not None:
            status = "typing..."
        elif self.events:
            status = "paused"
        else:
            status = "silent"
        singing = sum(1 for m in self.monsters if m.singing)
        info = (f"{scale.key} {scale.scale_type}  |  {len(self.text)} chars -> {len(self.encoded)} notes  |  "
                f"{len(self.monsters)} monsters ({singing} singing)  |  {status}")
        if not self.audio_ok:
            info += "  |  NO AUDIO"
        self.screen.blit(self.small_font.render(info, True, (190, 190, 215)), (20, 94))

        hint = self.font.render(
            f"[Enter] replay   [Ctrl+Backspace] delete word   "
            f"[ / ] sync offset: {int(self.latency * 1000)} ms   [Esc] quit", True, (150, 150, 175))
        self.screen.blit(hint, (12, self.win_h - 28))

    def run(self):
        while self.step():
            pass
        self.stop_playback()
        pygame.quit()


def _angle(tile, c):
    import math
    return math.atan2(tile[1] - c, tile[0] - c)

def islandInit():
    args = sys.argv[1:]
    latency = None
    if "--latency" in args:                       # e.g. --latency 0.25
        i = args.index("--latency")
        latency = float(args[i + 1])
        del args[i:i + 2]
    key = args[0] if len(args) > 0 else "f#"
    scale_type = args[1] if len(args) > 1 else "major-pentatonic"
    composer = Avison.Composer(key, scale_type)
    TuneIsland(composer, latency=latency).run()

if __name__ == "__main__":
    islandInit()
