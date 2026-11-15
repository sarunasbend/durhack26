"""
sheet_music.py - render an encoded message as sheet music and save it as a PDF.

The sender's note stream (Composer.encode_message -> notes, metadata) is laid out
on a treble staff in 4/4 exactly as Transmitter.write times it: each note starts
when the MIDI note starts and sounds for its MIDI duration; the gaps are rests.
Notes that cross a barline are split and tied. Accidentals follow the usual
rules (key signature, then an accidental holds for the rest of the bar in that
octave), so a musician reading the page plays exactly the transmitted pitches.

    from sheet_music import render_pdf
    render_pdf(encoded, metadata, composer, tempo=200, drone="F#2", path="encrypted.pdf")

Everything is drawn with Pillow, so no extra dependencies and no system fonts
are required (a font is used for the treble clef only when one with the glyph
is installed; otherwise a drawn clef is used).
"""

import datetime
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

TITLE = "encrypted"
BEATS_PER_BAR = 4
BARS_PER_SYSTEM = 4

# page geometry (A4 at 150 dpi)
PAGE_W, PAGE_H = 1240, 1754
DPI = 150
MARGIN = 90
SPACE = 10                      # distance between staff lines
STAFF_H = 4 * SPACE
SYSTEM_GAP = 150                # vertical distance between systems
HEADER_W = 150                  # room for clef + key + time signature
PAD = 26                        # padding inside a bar before the first beat

LETTERS = "CDEFGAB"
PITCH_CLASS = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
               "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
SHARP_ORDER = "FCGDAEB"
FLAT_ORDER = "BEADGCF"
# staff steps (E4 on the bottom line = 0, one step per line or space) of the
# accidentals in a treble-clef key signature
SHARP_STEPS = {"F": 8, "C": 5, "G": 9, "D": 6, "A": 3, "E": 7, "B": 4}
FLAT_STEPS = {"B": 4, "E": 7, "A": 3, "D": 6, "G": 2, "C": 5, "F": 1}
# semitones from the scale's tonic to the major key whose signature it uses
RELATIVE_MAJOR = {"major": 0, "major-pentatonic": 0, "lydian": 7, "mixolydian": 5,
                  "minor": 3, "minor-pentatonic": 3, "dorian": 10, "phrygian": 8, "locrian": 1}
NOTE_VALUES = (4.0, 2.0, 1.0, 0.5, 0.25)       # whole, half, quarter, eighth, sixteenth


# ============================================================================ music
def split_note(name):
    """'F#4' -> ('F#', 4)"""
    return name[:-1], int(name[-1])


def key_signature(key, scale_type):
    """(kind, letters) for the key: kind is 'sharp', 'flat' or None; letters in
    signature order, e.g. ('sharp', 'FCGDAE') for F# major."""
    tonic = PITCH_CLASS[key.upper()]
    major = (tonic + RELATIVE_MAJOR.get(scale_type, 0)) % 12
    fifths = (major * 7) % 12                 # position on the circle of fifths from C
    if fifths == 0:
        return None, ""
    if fifths <= 6:
        return "sharp", SHARP_ORDER[:fifths]
    return "flat", FLAT_ORDER[:12 - fifths]


def spell(name, kind):
    """Note name -> (letter, accidental, octave) with accidental in {-1, 0, 1}.
    Sharps in the project's names become flats in flat keys (A#4 -> Bb4)."""
    pc, octave = split_note(name)
    if len(pc) == 2:
        if kind == "flat":
            letter = LETTERS[(LETTERS.index(pc[0]) + 1) % 7]
            if letter == "C":                 # B# -> C of the next octave
                octave += 1
            return letter, -1, octave
        return pc[0], 1, octave
    return pc, 0, octave


def staff_step(letter, octave):
    """Diatonic steps above E4 (bottom line of the treble staff)."""
    return LETTERS.index(letter) + 7 * octave - (LETTERS.index("E") + 7 * 4)


def timeline(encoded, metadata):
    """[(start_beat, duration_beats, note_name)] replicating Transmitter.write."""
    events, clock = [], 0.0
    for note, meta in zip(encoded, metadata):
        start = clock + meta.get("previous", 0)
        clock = start + meta.get("time", 0)
        if isinstance(note, list):            # chords are not produced by the encoder
            note = note[0]
        events.append((start, float(meta["duration"]), note))
    # a note never sounds past the start of the next one
    out = []
    for i, (start, dur, note) in enumerate(events):
        if i + 1 < len(events):
            dur = min(dur, events[i + 1][0] - start)
        out.append((start, dur, note))
    return out


def decompose(duration):
    """Split a duration (beats) into standard note values, longest first."""
    parts = []
    remaining = round(duration * 16) / 16
    for value in NOTE_VALUES:
        while remaining >= value - 1e-9:
            parts.append(value)
            remaining -= value
    return parts


def layout(encoded, metadata):
    """Bars of symbols. Each symbol is a dict: kind 'note' or 'rest', pos (beat in
    bar), value (beats), and for notes name, tie_to_next."""
    events = timeline(encoded, metadata)
    if not events:
        return []
    end = events[-1][0] + events[-1][1]
    total_bars = max(1, math.ceil(end / BEATS_PER_BAR - 1e-9))
    bars = [[] for _ in range(total_bars)]

    def place(kind, start, dur, name=None):
        """Place a span, splitting at barlines and into standard values."""
        pieces = []
        t = start
        remaining = dur
        while remaining > 1e-9:
            bar = int(t // BEATS_PER_BAR)
            room = (bar + 1) * BEATS_PER_BAR - t
            chunk = min(room, remaining)
            for value in decompose(chunk):
                pieces.append((bar, t - bar * BEATS_PER_BAR, value))
                t += value
            remaining -= chunk
        for i, (bar, pos, value) in enumerate(pieces):
            sym = {"kind": kind, "pos": pos, "value": value, "name": name,
                   "tie_to_next": kind == "note" and i + 1 < len(pieces)}
            bars[bar].append(sym)

    for i, (start, dur, note) in enumerate(events):
        place("note", start, dur, note)
        next_start = events[i + 1][0] if i + 1 < len(events) else total_bars * BEATS_PER_BAR
        gap = next_start - (start + dur)
        if gap > 1e-9:
            place("rest", start + dur, gap)
    for bar in bars:
        bar.sort(key=lambda s: s["pos"])
    return bars


def mark_accidentals(bars, kind, sig_letters):
    """Decide which notes show an accidental (standard bar/octave rule)."""
    sig_acc = {letter: (1 if kind == "sharp" else -1) for letter in sig_letters}
    for bar in bars:
        state = {}
        for sym in bar:
            if sym["kind"] != "note":
                continue
            letter, acc, octave = spell(sym["name"], kind)
            sym["letter"], sym["acc"], sym["octave"] = letter, acc, octave
            sym["step"] = staff_step(letter, octave)
            current = state.get((letter, octave), sig_acc.get(letter, 0))
            sym["show_acc"] = acc != current
            state[(letter, octave)] = acc
    return bars


# ============================================================================ drawing
def _font(size, bold=False):
    candidates = ["C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/georgia.ttf",
                  "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"]
    if bold:
        candidates = ["C:/Windows/Fonts/timesbd.ttf", "C:/Windows/Fonts/georgiab.ttf",
                      "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"] + candidates
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


CLEF = "\U0001D11E"
CLEF_HEIGHT = 7.6 * SPACE          # ink height of the drawn clef


def _ink_metrics(font, text):
    """(left, top, width, height, curl_row) of the glyph's ink relative to the text
    origin; curl_row is the widest row in the lower part (the loop round the G line)."""
    import numpy as np
    size = font.size
    im = Image.new("L", (size * 3, size * 3), 255)
    ImageDraw.Draw(im).text((size, size), text, font=font, fill=0)
    ink = np.array(im) < 128
    rows = np.nonzero(ink.any(axis=1))[0]
    cols = np.nonzero(ink.any(axis=0))[0]
    if len(rows) == 0:
        return None
    top, bottom, left, right = rows[0], rows[-1], cols[0], cols[-1]
    widths = ink.sum(axis=1)
    lower = range(top + int((bottom - top) * 0.45), bottom + 1)
    curl = max(lower, key=lambda r: widths[r])
    return left - size, top - size, right - left + 1, bottom - top + 1, curl - size


def _clef_font():
    """(font, metrics) for a font that really has the treble clef, sized so the
    glyph is CLEF_HEIGHT tall; or None when no installed font has it."""
    for path in ["C:/Windows/Fonts/seguisym.ttf", "/System/Library/Fonts/Apple Symbols.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if not os.path.exists(path):
            continue
        probe = ImageFont.truetype(path, 100)
        m = _ink_metrics(probe, CLEF)
        missing = _ink_metrics(probe, "\U0010FFFD")
        if m is None or (missing and abs(m[3] - missing[3]) < 3 and abs(m[2] - missing[2]) < 3):
            continue                                   # a "missing glyph" box
        size = max(8, int(round(100 * CLEF_HEIGHT / m[3])))
        font = ImageFont.truetype(path, size)
        return font, _ink_metrics(font, CLEF)
    return None


class Page:
    def __init__(self, number):
        self.im = Image.new("RGB", (PAGE_W, PAGE_H), "white")
        self.d = ImageDraw.Draw(self.im)
        self.number = number


class Renderer:
    def __init__(self, bars, kind, sig_letters, subtitle, note_count):
        self.bars = bars
        self.kind = kind
        self.sig = sig_letters
        self.subtitle = subtitle
        self.note_count = note_count
        self.title_font = _font(64)
        self.sub_font = _font(22)
        self.small_font = _font(18)
        self.time_font = _font(int(STAFF_H * 0.58), bold=True)
        self.clef_font = _clef_font()
        self.pages = []

    # ------------------------------------------------------------- helpers
    def y_of(self, top, step):
        """y of a staff step (0 = bottom line) for a staff whose top line is at top."""
        return top + STAFF_H - step * SPACE / 2

    def head(self, d, x, y, filled, width=1.0):
        """Oval note head centred at (x, y), tilted like engraved music."""
        rx, ry = SPACE * 0.68 * width, SPACE * 0.48
        pts = []
        for i in range(32):
            a = math.tau * i / 32
            px, py = rx * math.cos(a), ry * math.sin(a)
            t = math.radians(-20)
            pts.append((x + px * math.cos(t) - py * math.sin(t), y + px * math.sin(t) + py * math.cos(t)))
        if filled:
            d.polygon(pts, fill="black")
        else:
            d.line(pts + [pts[0]], fill="black", width=max(2, SPACE // 4), joint="curve")

    def accidental(self, d, x, y, acc):
        s = SPACE
        w = max(2, s // 5)
        if acc == 1:                                    # sharp
            for dx in (-s * 0.22, s * 0.22):
                d.line([(x + dx, y - s * 1.1), (x + dx, y + s * 1.1)], fill="black", width=w)
            for dy in (-s * 0.32, s * 0.32):
                d.line([(x - s * 0.55, y + dy + s * 0.15), (x + s * 0.55, y + dy - s * 0.15)], fill="black", width=w + 1)
        elif acc == -1:                                 # flat
            d.line([(x - s * 0.35, y - s * 1.6), (x - s * 0.35, y + s * 0.5)], fill="black", width=w)
            d.arc([x - s * 0.35, y - s * 0.55, x + s * 0.55, y + s * 0.5], 240, 120, fill="black", width=w + 1)
            d.line([(x - s * 0.35, y + s * 0.5), (x + s * 0.2, y + s * 0.1)], fill="black", width=w)
        else:                                           # natural
            d.line([(x - s * 0.3, y - s * 1.1), (x - s * 0.3, y + s * 0.5)], fill="black", width=w)
            d.line([(x + s * 0.3, y - s * 0.5), (x + s * 0.3, y + s * 1.1)], fill="black", width=w)
            for dy in (-s * 0.4, s * 0.4):
                d.line([(x - s * 0.3, y + dy + s * 0.12), (x + s * 0.3, y + dy - s * 0.12)], fill="black", width=w + 1)

    def rest(self, d, x, top, value):
        s = SPACE
        mid = top + 2 * s                               # middle line
        w = max(2, s // 4)
        if value >= 4.0:                                # whole: hangs from the 4th line
            d.rectangle([x - s * 0.7, top + s, x + s * 0.7, top + s * 1.5], fill="black")
        elif value >= 2.0:                              # half: sits on the middle line
            d.rectangle([x - s * 0.7, mid - s * 0.5, x + s * 0.7, mid], fill="black")
        elif value >= 1.0:                              # quarter
            pts = [(x - s * 0.3, top + s * 0.6), (x + s * 0.4, top + s * 1.5), (x - s * 0.2, top + s * 2.1),
                   (x + s * 0.4, top + s * 2.9)]
            d.line(pts, fill="black", width=w + 2, joint="curve")
            d.arc([x - s * 0.5, top + s * 2.6, x + s * 0.3, top + s * 3.5], 20, 250, fill="black", width=w)
        elif value >= 0.5:                              # eighth
            d.ellipse([x - s * 0.55, mid - s * 0.45, x - s * 0.05, mid + s * 0.05], fill="black")
            d.line([(x + s * 0.35, mid - s * 0.3), (x - s * 0.25, mid + s * 1.3)], fill="black", width=w)
            d.line([(x - s * 0.3, mid - s * 0.1), (x + s * 0.35, mid - s * 0.3)], fill="black", width=w)
        else:                                           # sixteenth
            for k in range(2):
                yy = mid - s * 0.45 + k * s * 0.8
                d.ellipse([x - s * 0.55, yy, x - s * 0.05, yy + s * 0.5], fill="black")
                d.line([(x - s * 0.3, yy + s * 0.35), (x + s * 0.35 - k * s * 0.3, mid - s * 0.3)], fill="black", width=w)
            d.line([(x + s * 0.35, mid - s * 0.3), (x - s * 0.45, mid + s * 1.6)], fill="black", width=w)

    def clef(self, d, x, top):
        if self.clef_font:
            font, (left, _, _, _, curl) = self.clef_font
            # anchor the loop of the clef on the G line (second line from the bottom)
            d.text((x - left, self.y_of(top, 1) - curl), CLEF, font=font, fill="black")
            return
        # drawn fallback: a spiral around the G line with a tall loop
        s = SPACE
        g = self.y_of(top, 1)                           # G4 line
        pts = []
        for i in range(0, 200):
            t = i / 199
            a = -math.pi / 2 + t * 3.6 * math.pi
            r = s * (0.25 + 1.0 * (1 - t))
            pts.append((x + s * 1.2 + r * math.cos(a), g + r * math.sin(a) * 0.9))
        d.line(pts, fill="black", width=max(2, s // 4), joint="curve")
        d.line([(x + s * 1.2, g + s * 1.0), (x + s * 1.6, top - s * 2.2), (x + s * 2.2, top - s * 1.0),
                (x + s * 1.3, top + s * 0.8)], fill="black", width=max(2, s // 4), joint="curve")
        d.line([(x + s * 1.2, g + s * 1.0), (x + s * 1.0, top + STAFF_H + s * 1.8)], fill="black", width=max(2, s // 4))
        d.ellipse([x + s * 0.4, top + STAFF_H + s * 1.4, x + s * 1.1, top + STAFF_H + s * 2.1], fill="black")

    def signature(self, d, x, top):
        steps = SHARP_STEPS if self.kind == "sharp" else FLAT_STEPS
        acc = 1 if self.kind == "sharp" else -1
        for i, letter in enumerate(self.sig):
            self.accidental(d, x + i * SPACE * 1.1, self.y_of(top, steps[letter]), acc)
        return x + len(self.sig) * SPACE * 1.1

    def time_sig(self, d, x, top):
        for text, y in (("4", top), ("4", top + 2 * SPACE)):
            bbox = d.textbbox((0, 0), text, font=self.time_font)
            d.text((x - bbox[0], y - bbox[1] + (2 * SPACE - (bbox[3] - bbox[1])) / 2), text, font=self.time_font, fill="black")

    # ------------------------------------------------------------- systems
    def draw_system(self, page, top, bar_index, first):
        d = page.d
        x0, x1 = MARGIN, PAGE_W - MARGIN
        for i in range(5):
            y = top + i * SPACE
            d.line([(x0, y), (x1, y)], fill="black", width=2)
        d.line([(x0, top), (x0, top + STAFF_H)], fill="black", width=2)
        self.clef(d, x0 + SPACE * 0.6, top)
        x = self.signature(d, x0 + SPACE * 4.2, top)
        if first:
            self.time_sig(d, x + SPACE * 0.8, top)
            x += SPACE * 3.2
        content_left = max(x0 + HEADER_W, x + SPACE)
        bars = self.bars[bar_index:bar_index + BARS_PER_SYSTEM]
        bar_w = (x1 - content_left) / BARS_PER_SYSTEM
        pending_tie = None
        for b, bar in enumerate(bars):
            bx = content_left + b * bar_w
            beat_w = (bar_w - 2 * PAD) / BEATS_PER_BAR
            for sym in bar:
                x = bx + PAD + sym["pos"] * beat_w
                if sym["kind"] == "rest":
                    self.rest(d, x, top, sym["value"])
                    continue
                y = self.y_of(top, sym["step"])
                step = sym["step"]
                # ledger lines
                for ledger in range(-2, step - 1, -2) if step <= -2 else range(10, step + 1, 2):
                    ly = self.y_of(top, ledger)
                    d.line([(x - SPACE * 0.95, ly), (x + SPACE * 0.95, ly)], fill="black", width=2)
                if sym["show_acc"]:
                    self.accidental(d, x - SPACE * 1.35, y, sym["acc"])
                filled = sym["value"] < 2.0
                self.head(d, x, y, filled, width=1.25 if sym["value"] >= 4.0 else 1.0)
                stem_up = step < 4                     # below the middle line: stems up
                if sym["value"] < 4.0:
                    sx = x + SPACE * 0.6 if stem_up else x - SPACE * 0.6
                    tip = y - SPACE * 3.5 if stem_up else y + SPACE * 3.5
                    d.line([(sx, y), (sx, tip)], fill="black", width=max(2, SPACE // 5))
                    flags = {0.5: 1, 0.25: 2}.get(sym["value"], 0)
                    for f in range(flags):
                        fy = tip + (f * SPACE * 0.8) * (1 if stem_up else -1)
                        direction = 1 if stem_up else -1
                        d.line([(sx, fy), (sx + SPACE * 0.9, fy + direction * SPACE * 1.1),
                                (sx + SPACE * 0.7, fy + direction * SPACE * 2.0)],
                               fill="black", width=max(2, SPACE // 4), joint="curve")
                if pending_tie:
                    px, py, p_up = pending_tie
                    yy = (py + SPACE * 0.9) if p_up else (py - SPACE * 0.9)
                    bulge = SPACE * 0.8 if p_up else -SPACE * 0.8
                    d.line([(px + SPACE * 0.5, yy), ((px + x) / 2, yy + bulge), (x - SPACE * 0.5, yy)],
                           fill="black", width=max(2, SPACE // 4), joint="curve")
                    pending_tie = None
                if sym["tie_to_next"]:
                    pending_tie = (x, y, stem_up)
            # barline
            bar_right = bx + bar_w
            last = bar_index + b == len(self.bars) - 1
            if last:
                d.line([(bar_right - 7, top), (bar_right - 7, top + STAFF_H)], fill="black", width=2)
                d.rectangle([bar_right - 3, top, bar_right + 1, top + STAFF_H], fill="black")
            else:
                d.line([(bar_right, top), (bar_right, top + STAFF_H)], fill="black", width=2)
        if pending_tie:                                 # tie continues onto the next system
            px, py, p_up = pending_tie
            yy = (py + SPACE * 0.9) if p_up else (py - SPACE * 0.9)
            d.line([(px + SPACE * 0.5, yy), (x1 - SPACE, yy + (SPACE * 0.6 if p_up else -SPACE * 0.6))],
                   fill="black", width=max(2, SPACE // 4))
        # bar number
        d.text((x0, top - SPACE * 3.2), str(bar_index + 1), font=self.small_font, fill="black")

    def render(self):
        page = Page(1)
        d = page.d
        bbox = d.textbbox((0, 0), TITLE, font=self.title_font)
        d.text(((PAGE_W - (bbox[2] - bbox[0])) / 2 - bbox[0], MARGIN - 10), TITLE, font=self.title_font, fill="black")
        bbox = d.textbbox((0, 0), self.subtitle, font=self.sub_font)
        d.text(((PAGE_W - (bbox[2] - bbox[0])) / 2 - bbox[0], MARGIN + 80), self.subtitle, font=self.sub_font, fill="black")
        top = MARGIN + 180
        bar_index = 0
        first = True
        while bar_index < len(self.bars):
            if top + STAFF_H + SPACE * 4 > PAGE_H - MARGIN:
                self.finish_page(page)
                page = Page(len(self.pages) + 1)
                top = MARGIN + SPACE * 4
            self.draw_system(page, top, bar_index, first)
            first = False
            bar_index += BARS_PER_SYSTEM
            top += SYSTEM_GAP
        self.finish_page(page)
        return [p.im for p in self.pages]

    def finish_page(self, page):
        text = f"{TITLE}  -  page {page.number}"
        bbox = page.d.textbbox((0, 0), text, font=self.small_font)
        page.d.text(((PAGE_W - (bbox[2] - bbox[0])) / 2, PAGE_H - MARGIN + 30), text, font=self.small_font, fill="black")
        self.pages.append(page)


# ============================================================================ api
def build(encoded, metadata, composer):
    """Bars with accidentals decided, plus the key signature, for tests and rendering."""
    kind, letters = key_signature(composer.scale.key, composer.scale.scale_type)
    bars = mark_accidentals(layout(encoded, metadata), kind, letters)
    return bars, kind, letters


def render_pdf(encoded, metadata, composer, tempo, drone, path, text_length=None):
    """Write the sheet music PDF. Returns the number of pages."""
    if not encoded:
        raise ValueError("nothing to render: the message is empty")
    bars, kind, letters = build(encoded, metadata, composer)
    scale = composer.scale
    parts = [f"{scale.key} {scale.scale_type.replace('-', ' ')}", f"quarter note = {tempo}"]
    if drone:
        parts.append(f"drone {drone} held throughout")
    if text_length is not None:
        parts.append(f"{text_length} characters")
    parts.append(f"{len(encoded)} notes")
    parts.append(datetime.date.today().isoformat())
    subtitle = "   -   ".join(parts)
    pages = Renderer(bars, kind, letters, subtitle, len(encoded)).render()
    pages[0].save(path, "PDF", resolution=DPI, save_all=True, append_images=pages[1:])
    return len(pages)


def open_file(path):
    """Open the PDF with the system viewer; never raises."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)                      # noqa
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
    except Exception as exc:
        print(f"[sheet_music] could not open {path}: {exc}")


if __name__ == "__main__":
    import Avison
    import Settings
    text = " ".join(sys.argv[1:]) or "Hello earth"
    composer = Avison.Composer(Settings.KEY, Settings.SCALE_TYPE)
    encoded, metadata = composer.encode_message(text)
    n = render_pdf(encoded, metadata, composer, Settings.TEMPO, Settings.DRONE, "encrypted.pdf", len(text))
    print(f"wrote encrypted.pdf ({n} pages)")
