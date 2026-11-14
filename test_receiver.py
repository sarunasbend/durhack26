# Tests for Receiver.py. Run with: python test_receiver.py   (or pytest)
# MIDI files are generated in memory, so no fixtures are needed.

import numpy as np
import pretty_midi

from Receiver import Receiver, build_templates

TEMPO = 120
SLOT = 60.0 / TEMPO  # seconds per symbol at one beat per symbol


def make_midi(slots, tempo=TEMPO, articulation=0.8, offset=0.0, extra_pitches=None):
    """Build a PrettyMIDI where slots[i] is a list of pitches (empty = rest).

    articulation: fraction of the slot each note sounds for
    offset:       leading silence before the first slot, in seconds
    """
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    piano = pretty_midi.Instrument(program=0)
    for i, pitches in enumerate(slots):
        start = offset + i * SLOT
        for pitch in pitches:
            piano.notes.append(pretty_midi.Note(velocity=100, pitch=pitch,
                                                start=start, end=start + SLOT * articulation))
    midi.instruments.append(piano)
    return midi


def names(symbols):
    return [s.name for s in symbols]


def test_templates_default_count():
    labels, templates = build_templates()
    assert len(labels) == 36
    assert np.allclose(np.linalg.norm(templates, axis=1), 1.0)


def test_notes_chords_and_rests():
    # C4, C major, rest, A minor, G major (1st inversion), E5
    slots = [[60], [60, 64, 67], [], [57, 60, 64], [59, 62, 67], [76]]
    symbols = Receiver(tempo=TEMPO).from_midi(make_midi(slots))
    assert names(symbols) == ['C', 'C:maj', 'N', 'A:min', 'G:maj', 'E']
    assert symbols[0].pitch == 60 and symbols[5].pitch == 76


def test_repeated_symbols_stay_separate():
    # Legato (no gap) repeated chords must still give one symbol per slot.
    slots = [[60, 64, 67]] * 3
    symbols = Receiver(tempo=TEMPO).from_midi(make_midi(slots, articulation=1.0))
    assert names(symbols) == ['C:maj'] * 3


def test_leading_silence_ignored():
    symbols = Receiver(tempo=TEMPO).from_midi(make_midi([[62], [62, 65, 69]], offset=1.3))
    assert names(symbols) == ['D', 'D:min']


def test_octave_doubling_and_stray_note():
    # C major with doubled root, then C major with an extra D (falls back to templates).
    slots = [[48, 60, 64, 67], [60, 62, 64, 67]]
    symbols = Receiver(tempo=TEMPO).from_midi(make_midi(slots))
    assert names(symbols) == ['C:maj', 'C:maj']
    assert symbols[0].confidence == 1.0 and symbols[1].confidence < 1.0


def test_allowed_symbols_restricts_matches():
    # C#,E,G# (C# minor) is not allowed; it shares E and G# with E major, so it should snap to that.
    receiver = Receiver(tempo=TEMPO, allowed_symbols=['C', 'C:maj', 'E:maj'])
    assert len(receiver.labels) == 3
    symbols = receiver.from_midi(make_midi([[61, 64, 68]]))
    assert symbols[0].name == 'E:maj'


def test_generated_sequence_round_trip():
    # The same sequence generate_test_midi.py writes, both exact and humanised.
    from generate_test_midi import SEQUENCE, build_midi
    expected = [label for label, _ in SEQUENCE]
    for humanize in (False, True):
        assert names(Receiver(tempo=TEMPO).from_midi(build_midi(SEQUENCE, humanize=humanize))) == expected


if __name__ == '__main__':
    tests = [f for name, f in sorted(globals().items()) if name.startswith('test_')]
    for test in tests:
        test()
        print('passed', test.__name__)
    print('all %d tests passed' % len(tests))
