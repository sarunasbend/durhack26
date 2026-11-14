# Midi chord and note recognition and processing
# assumptions:
#  - single notes may also be played, by themselves.
#  - chords are only major and minor triads
#  - only one chord is played at a time
#  - able to be done via microphone input and existing midi files
#  - tempo is known in advance, and is constant throughout the song
#  - commments should be used to explain the code, and the code should be well structured and organized
#
# Approach: the tempo is known, so the input is cut into fixed time slots
# (one symbol per slot) and each slot is classified on its own as a rest,
# a single note, or a major/minor triad.

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Union

import numpy as np
import pretty_midi

tempo = 120  # default tempo (beats per minute)

# Pitch-class number <-> name. Uses sharps to match Scale.chromatic_scale in Avison.py.
NUM_TO_ABS_SCALE = {0: 'C', 1: 'C#', 2: 'D', 3: 'D#', 4: 'E', 5: 'F', 6: 'F#', 7: 'G', 8: 'G#', 9: 'A', 10: 'A#', 11: 'B'}
ABS_SCALE_TO_NUM = {name: num for num, name in NUM_TO_ABS_SCALE.items()}

# Chord qualities as intervals (in semitones) above the root.
QUALITIES = {'maj': (0, 4, 7), 'min': (0, 3, 7)}


@dataclass
class Symbol:
    """One recognised symbol occupying one time slot."""
    slot: int                      # index on the beat grid
    kind: str                      # 'rest', 'note' or 'chord'
    root: Optional[int] = None     # pitch class 0-11
    quality: Optional[str] = None  # 'maj' or 'min' for chords
    pitch: Optional[int] = None    # exact MIDI number for single notes, when known
    confidence: float = 1.0        # best match score minus the runner-up

    @property
    def name(self) -> str:
        """Label without octave: 'N' (rest), 'C' (note) or 'A:min' (chord)."""
        if self.kind == 'rest':
            return 'N'
        if self.kind == 'note':
            return NUM_TO_ABS_SCALE[self.root]
        return '%s:%s' % (NUM_TO_ABS_SCALE[self.root], self.quality)


def build_templates(allowed_symbols: Optional[Iterable[str]] = None):
    """Return (labels, templates): one unit-length 12-bin template per note/chord.

    labels[i] is (kind, root, quality). allowed_symbols (names like 'C' or
    'A:min') optionally restricts recognition to a smaller set.
    """
    labels = [('note', root, None) for root in range(12)]
    labels += [('chord', root, q) for root in range(12) for q in QUALITIES]

    if allowed_symbols is not None:
        allowed = set(allowed_symbols)
        labels = [l for l in labels
                  if (NUM_TO_ABS_SCALE[l[1]] if l[0] == 'note' else '%s:%s' % (NUM_TO_ABS_SCALE[l[1]], l[2])) in allowed]
        if not labels:
            raise ValueError('allowed_symbols contains no notes or chords')

    templates = np.zeros((len(labels), 12))
    for i, (kind, root, quality) in enumerate(labels):
        for interval in ((0,) if kind == 'note' else QUALITIES[quality]):
            templates[i, (root + interval) % 12] = 1.0
    templates /= np.linalg.norm(templates, axis=1, keepdims=True)
    return labels, templates


class Receiver(object):
    """Turns a performance (MIDI file, later audio) into a list of Symbols."""

    def __init__(self, tempo: float = tempo, beats_per_symbol: float = 1,
                 allowed_symbols: Optional[Iterable[str]] = None):
        self.tempo = tempo
        self.beats_per_symbol = beats_per_symbol
        self.labels, self.templates = build_templates(allowed_symbols)

    @property
    def slot_seconds(self) -> float:
        """Length of one symbol slot in seconds."""
        return 60.0 / self.tempo * self.beats_per_symbol

    # ----- Inputs -------------------------------------------------------------

    def from_midi(self, midi: Union[str, pretty_midi.PrettyMIDI]) -> List[Symbol]:
        """Recognise symbols from a MIDI file path or a loaded PrettyMIDI object."""
        if isinstance(midi, str):
            midi = pretty_midi.PrettyMIDI(midi)
        return [self._classify_pitches(pitches, slot)
                for slot, pitches in enumerate(self._midi_to_slots(midi))]

    def from_audio_file(self, path: str) -> List[Symbol]:
        """Recognise symbols from a recording (to do: chroma per slot -> _classify_chroma)."""
        raise NotImplementedError

    def from_microphone(self, seconds: float) -> List[Symbol]:
        """Record from the microphone, then recognise as for an audio file (to do)."""
        raise NotImplementedError

    # ----- MIDI path ----------------------------------------------------------

    def _midi_to_slots(self, midi: pretty_midi.PrettyMIDI) -> List[List[int]]:
        """Return the MIDI pitches sounding at the middle of each slot.

        The grid starts at the first note, so leading silence is ignored, and
        sampling the middle of each slot tolerates slightly early/late notes.
        """
        notes = [n for inst in midi.instruments if not inst.is_drum for n in inst.notes]
        if not notes:
            return []

        start = min(n.start for n in notes)
        last_start = max(n.start for n in notes)
        n_slots = int(np.floor((last_start - start) / self.slot_seconds + 0.5)) + 1

        slots = []
        for slot in range(n_slots):
            middle = start + (slot + 0.5) * self.slot_seconds
            slots.append(sorted(n.pitch for n in notes if n.start <= middle < n.end))
        return slots

    def _classify_pitches(self, pitches: List[int], slot: int) -> Symbol:
        """Classify one MIDI slot from its exact pitches.

        Silence, one pitch class, or an exact triad are decided directly;
        anything else (e.g. a stray extra note) uses the template matcher.
        """
        pitch_classes = {p % 12 for p in pitches}

        if not pitch_classes:
            return Symbol(slot, 'rest')

        if len(pitch_classes) == 1 and ('note', pitches[0] % 12, None) in self.labels:
            # Lowest pitch played, in case of octave doubling.
            return Symbol(slot, 'note', root=pitches[0] % 12, pitch=pitches[0])

        if len(pitch_classes) == 3:
            for root in pitch_classes:
                intervals = {(pc - root) % 12 for pc in pitch_classes}
                for quality, quality_intervals in QUALITIES.items():
                    if intervals == set(quality_intervals) and ('chord', root, quality) in self.labels:
                        return Symbol(slot, 'chord', root=root, quality=quality)

        chroma = np.zeros(12)
        chroma[list(pitch_classes)] = 1.0
        symbol = self._classify_chroma(chroma, slot)
        if symbol.kind == 'note':
            symbol.pitch = next((p for p in pitches if p % 12 == symbol.root), None)
        return symbol

    # ----- Shared classifier (MIDI fallback now, audio later) ---------------

    def _classify_chroma(self, chroma: np.ndarray, slot: int) -> Symbol:
        """Pick the template closest (by cosine similarity) to a 12-bin chroma vector."""
        norm = np.linalg.norm(chroma)
        if norm == 0:
            return Symbol(slot, 'rest')

        scores = self.templates @ (chroma / norm)
        order = np.argsort(scores)[::-1]
        confidence = float(scores[order[0]] - scores[order[1]]) if len(order) > 1 else 1.0
        kind, root, quality = self.labels[order[0]]
        return Symbol(slot, kind, root=root, quality=quality, confidence=confidence)


if __name__ == '__main__':
    # Usage: python Receiver.py path/to/song.mid [tempo]
    import sys

    receiver = Receiver(tempo=float(sys.argv[2]) if len(sys.argv) > 2 else tempo)
    for symbol in receiver.from_midi(sys.argv[1]):
        print(symbol.slot, symbol.name, symbol.pitch or '', '%.2f' % symbol.confidence)
