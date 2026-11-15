# Tests for Receiver.py. Run with: python test_receiver.py   (or pytest)
# MIDI and audio are generated in memory, so no fixtures or microphone are needed.

import numpy as np
import pretty_midi

from Receiver import SAMPLE_RATE, WINDOW, find_root, note_name, root_from_audio, roots_from_midi

SLOT = 0.5  # seconds per note/chord


def make_midi(slots, articulation=0.8):
    """Build a PrettyMIDI where slots[i] is a list of pitches played together (empty = rest)."""
    midi = pretty_midi.PrettyMIDI()
    piano = pretty_midi.Instrument(program=4)  # Electric Piano 1, the instrument Transmitter.py uses
    for i, pitches in enumerate(slots):
        for pitch in pitches:
            piano.notes.append(pretty_midi.Note(velocity=100, pitch=pitch,
                                                start=i * SLOT, end=(i + articulation) * SLOT))
    midi.instruments.append(piano)
    return midi


def tone(pitches, harmonics=6):
    """A block of audio playing the given MIDI pitches, each with some overtones."""
    t = np.arange(WINDOW) / SAMPLE_RATE
    out = np.zeros(WINDOW)
    for p in pitches:
        f = 440.0 * 2 ** ((p - 69) / 12)
        for h in range(1, harmonics + 1):
            out += np.sin(2 * np.pi * f * h * t) / h
    return 0.3 * out / np.abs(out).max()


def test_note_name():
    assert note_name(60) == 'C4' and note_name(66) == 'F#4' and note_name(21) == 'A0'


def test_find_root():
    assert find_root([]) is None
    assert find_root([62]) == 62                  # single note
    assert find_root([60, 64, 67]) == 60          # C major, root position
    assert find_root([64, 67, 72]) == 72          # C major, 1st inversion -> C5
    assert find_root([55, 60, 64]) == 60          # C major, 2nd inversion
    assert find_root([57, 60, 64]) == 57          # A minor
    assert find_root([48, 60, 64, 67]) == 48      # doubled root -> lowest C
    assert find_root([43, 50]) == 43              # power chord G-D
    assert find_root([60, 61]) == 60              # no triad: lowest note


def test_midi_notes_chords_and_repeats():
    slots = [[60], [60, 64, 67], [], [57, 60, 64], [59, 62, 67], [62, 66, 69], [62, 66, 69], [76]]
    roots = roots_from_midi(make_midi(slots, articulation=1.0))
    assert roots == ['C4', 'C4', 'A3', 'G4', 'D4', 'D4', 'E5']


def test_generated_sequence_round_trip():
    # The sequence generate_test_midi.py writes, both exact and humanised.
    from generate_test_midi import SEQUENCE, build_midi
    expected = [label.split(':')[0] for label, _ in SEQUENCE if label != 'N']
    for humanize in (False, True):
        roots = roots_from_midi(build_midi(SEQUENCE, humanize=humanize))
        assert [r.rstrip('0123456789') for r in roots] == expected


def test_audio_single_notes():
    for pitch in (48, 55, 60, 62, 66, 69, 74, 81):
        assert root_from_audio(tone([pitch])) == note_name(pitch), pitch


def test_audio_chords():
    assert root_from_audio(tone([60, 64, 67])) == 'C4'
    assert root_from_audio(tone([57, 60, 64])) == 'A3'
    assert root_from_audio(tone([62, 66, 69])) == 'D4'


def test_audio_silence():
    assert root_from_audio(np.zeros(WINDOW)) is None


def test_noise_is_not_a_note():
    rng = np.random.default_rng(0)
    for seed in range(20):
        noise = np.random.default_rng(seed).normal(0, 0.1, WINDOW)
        assert root_from_audio(noise) is None
    # A clap: a short, loud burst of noise that dies away.
    clap = rng.normal(0, 0.5, WINDOW) * np.exp(-np.arange(WINDOW) / 300)
    assert root_from_audio(clap) is None


def test_out_of_tune_tone_is_not_a_note():
    # Exactly halfway between C4 and C#4: not a real note.
    assert root_from_audio(tone([60.5])) is None
    # Slightly off (15 cents) still counts.
    assert root_from_audio(tone([60.15])) == 'C4'


def test_notes_in_background_noise():
    rng = np.random.default_rng(1)
    for pitch in (55, 60, 62, 69, 74):
        noisy = tone([pitch]) + rng.normal(0, 0.02, WINDOW)
        assert root_from_audio(noisy) == note_name(pitch), pitch
    noisy_chord = tone([57, 60, 64]) + rng.normal(0, 0.02, WINDOW)
    assert root_from_audio(noisy_chord) == 'A3'


def test_background_subtraction_removes_hum():
    # Loud 100 Hz mains hum (close to G2) plus hiss, measured beforehand as the background.
    from Receiver import spectrum_of
    rng = np.random.default_rng(2)
    t = np.arange(WINDOW) / SAMPLE_RATE

    def room():
        return 0.2 * np.sin(2 * np.pi * 100 * t + rng.uniform(0, 6)) + rng.normal(0, 0.01, WINDOW)

    background = np.mean([spectrum_of(room())[1] for _ in range(10)], axis=0)
    assert root_from_audio(room(), background=background) is None
    for pitch in (60, 64, 69):
        assert root_from_audio(tone([pitch]) + room(), background=background) == note_name(pitch), pitch


if __name__ == '__main__':
    tests = [f for name, f in sorted(globals().items()) if name.startswith('test_')]
    for test in tests:
        test()
        print('passed', test.__name__)
    print('all %d tests passed' % len(tests))
