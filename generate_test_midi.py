# Generates a MIDI file with a known sequence of notes, chords and rests,
# so the Receiver can be checked against the expected answer.
#
# Usage:
#   python generate_test_midi.py                 -> writes generated_test.mid
#   python generate_test_midi.py out.mid --humanize
#
# --humanize nudges note starts/ends and velocities randomly, imitating a
# recording that was not perfectly snapped to the beat.

import random
import sys

import pretty_midi

TEMPO = 120                # must match the Receiver's tempo
SLOT = 60.0 / TEMPO        # one symbol per beat
ARTICULATION = 0.8         # each symbol sounds for 80% of its slot, then a short gap

# The test sequence: (expected label, MIDI pitches). Empty pitches = rest.
# Mostly in D major (the key used in main.py), plus a few awkward cases.
SEQUENCE = [
    ('D',     [62]),            # single note D4
    ('D:maj', [62, 66, 69]),    # D major, root position
    ('G:maj', [55, 59, 62]),    # G major, lower register
    ('A:maj', [61, 64, 69]),    # A major, 1st inversion (C# in the bass)
    ('N',     []),              # rest
    ('B:min', [59, 62, 66]),    # B minor
    ('E:min', [64, 67, 71]),    # E minor
    ('F#',    [66]),            # single note F#4
    ('F#:min', [61, 66, 69]),   # F# minor, 2nd inversion
    ('D:maj', [50, 62, 66, 69]),  # D major with doubled root
    ('D:maj', [62, 66, 69]),    # repeated chord: must stay a separate symbol
    ('A',     [81]),            # single high note A5
    ('N',     []),              # rest
    ('C:maj', [60, 64, 67]),    # outside the key
    ('A:min', [57, 60, 64]),    # shares two notes with C major
    ('D',     [74]),            # single note D5 as the last symbol
]


def build_midi(sequence, humanize=False, seed=0):
    """Return a PrettyMIDI object playing `sequence` at TEMPO, one symbol per slot."""
    rng = random.Random(seed)
    midi = pretty_midi.PrettyMIDI(initial_tempo=TEMPO)
    # Program 4 = Electric Piano 1, similar to the original test.mid.
    piano = pretty_midi.Instrument(program=4, name='Test Piano')

    for slot, (_, pitches) in enumerate(sequence):
        for pitch in pitches:
            start = slot * SLOT
            end = start + SLOT * ARTICULATION
            velocity = 90
            if humanize:
                start += rng.uniform(-0.04, 0.04)   # +-40 ms timing error
                end += rng.uniform(-0.05, 0.05)
                velocity += rng.randint(-20, 20)
            piano.notes.append(pretty_midi.Note(velocity=velocity, pitch=pitch,
                                                start=max(0.0, start), end=end))

    midi.instruments.append(piano)
    return midi


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    out_path = args[0] if args else 'generated_test.mid'
    build_midi(SEQUENCE, humanize='--humanize' in sys.argv).write(out_path)
    print('Wrote %s (%d symbols, %.1f s at %d bpm)' % (out_path, len(SEQUENCE), len(SEQUENCE) * SLOT, TEMPO))
    print('Expected:', ' '.join(label for label, _ in SEQUENCE))
