# Receiver: works out the root note of whatever is being played.
#
# Two inputs:
#   roots_from_midi('song.mid')   -> ['D4', 'G3', 'A3', ...]   one root per note/chord
#   for root in listen(): ...      -> yields roots live from the microphone
#
# Roots come back as note names with an octave (e.g. 'F#4'), in the same
# format as the notes table in Encoder.py.
#
# How the root is chosen (find_root):
#   - a single note is its own root
#   - for a chord, the root is the note that has a third (3 or 4 semitones)
#     and a fifth (7 semitones) above it, so inversions still give the right root
#   - failing that, a note with a fifth above it (e.g. a power chord)
#   - failing that, the lowest note
#
# Command line:
#   python Receiver.py song.mid
#   python Receiver.py --mic

import sys

import numpy as np

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# MIDI: notes starting within this many seconds of each other count as one chord.
CHORD_WINDOW = 0.1

# Live audio settings.
SAMPLE_RATE = 44100
WINDOW = 4096          # samples analysed at once (~93 ms)
HOP = 1024             # new samples read each step (~23 ms)
SILENCE = 0.01         # RMS below this counts as silence
ONSET_RATIO = 1.5      # a jump in loudness this big means a new note was played
SETTLE_HOPS = 3        # wait this many hops after an onset before reading the note
MIN_FREQ = 50.0        # ignore spectrum peaks outside this range (Hz)
MAX_FREQ = 2000.0
PEAK_THRESHOLD = 0.1   # peaks quieter than this fraction of the loudest are ignored

# Noise filtering.
MAX_CENTS = 30           # a peak must be within this many cents (1/100 semitone) of a real note
NOISE_FLOOR_RATIO = 10   # a peak must be this many times louder than the median of the spectrum
MIN_TONAL = 0.6          # at least this fraction of the sound must be in in-tune peaks to be a note
PEAK_WIDTH = 8           # spectrum bins either side of a peak that belong to it
CALIBRATE_SECONDS = 1.0  # listen() measures the background noise for this long first
NOISE_MARGIN = 2.0       # sound must be this many times louder than the background


def note_name(midi_pitch):
    """60 -> 'C4'."""
    return NOTE_NAMES[midi_pitch % 12] + str(midi_pitch // 12 - 1)


def find_root(pitches):
    """Return the MIDI pitch of the root of a note or chord, or None if empty."""
    pitches = sorted(set(pitches))
    if not pitches:
        return None
    pitch_classes = {p % 12 for p in pitches}

    # Lowest first, so the root comes back in the octave it is lowest in.
    for p in pitches:
        has_third = (p + 3) % 12 in pitch_classes or (p + 4) % 12 in pitch_classes
        has_fifth = (p + 7) % 12 in pitch_classes
        if has_third and has_fifth:
            return p

    for p in pitches:
        if (p + 7) % 12 in pitch_classes:
            return p

    return pitches[0]


# ----- MIDI ------------------------------------------------------------------

def roots_from_midi(midi):
    """Root note name of every note/chord in a MIDI file, in order.

    midi can be a file path or a pretty_midi.PrettyMIDI object.
    """
    import pretty_midi

    if isinstance(midi, str):
        midi = pretty_midi.PrettyMIDI(midi)

    notes = [n for inst in midi.instruments if not inst.is_drum for n in inst.notes]
    notes.sort(key=lambda n: n.start)

    # Group notes that start together into chords.
    groups = []
    for note in notes:
        if groups and note.start - groups[-1][0].start <= CHORD_WINDOW:
            groups[-1].append(note)
        else:
            groups.append([note])

    return [note_name(find_root([n.pitch for n in group])) for group in groups]


# ----- Live audio ------------------------------------------------------------

def spectrum_of(samples, sample_rate=SAMPLE_RATE):
    """Return (frequency of each bin, magnitude spectrum) of a block of audio."""
    n = 4 * len(samples)  # zero-padded for finer bins
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples)), n=n))
    freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)
    return freqs, spectrum


def pitches_in_audio(samples, sample_rate=SAMPLE_RATE, background=None):
    """MIDI pitches of the in-tune peaks in a block of audio.

    Returns [] if the block doesn't sound like a note. Noise is filtered by:
      - subtracting the background spectrum (measured by listen()), if given
      - ignoring peaks that barely rise above the rest of the spectrum
      - ignoring peaks more than MAX_CENTS away from a real note
      - rejecting the whole block if most of its energy isn't in those in-tune
        peaks (noise, claps and speech spread their energy everywhere)

    The pitches include each note's overtones as well as the notes themselves,
    which suits find_root: a single C gives C, G and E overtones, which read
    as a C major chord, so the root is still C.
    """
    freqs, spectrum = spectrum_of(samples, sample_rate)
    if background is not None:
        spectrum = np.maximum(spectrum - NOISE_MARGIN * background, 0)

    in_range = np.nonzero((freqs >= MIN_FREQ) & (freqs <= MAX_FREQ))[0]
    loudest = spectrum[in_range].max()
    if loudest == 0:
        return []
    noise_floor = np.median(spectrum[in_range])
    threshold = max(PEAK_THRESHOLD * loudest, NOISE_FLOOR_RATIO * noise_floor)

    pitches = set()
    in_tune = np.zeros(len(spectrum), dtype=bool)  # bins belonging to in-tune peaks
    for i in in_range:
        is_peak = spectrum[i] > spectrum[i - 1] and spectrum[i] >= spectrum[i + 1]
        if not is_peak or spectrum[i] < threshold:
            continue

        # Find the exact peak frequency between bins: fit a parabola through
        # the peak bin and its two neighbours (on a log scale).
        a, b, c = np.log(spectrum[i - 1:i + 2] + 1e-12)
        offset = 0.5 * (a - c) / (a - 2 * b + c)
        freq = (i + offset) * freqs[1]

        exact = 69 + 12 * np.log2(freq / 440.0)  # fractional MIDI pitch
        pitch = int(round(exact))
        if abs(exact - pitch) * 100 > MAX_CENTS:
            continue  # between two notes, so not a real note

        pitches.add(pitch)
        in_tune[i - PEAK_WIDTH:i + PEAK_WIDTH + 1] = True

    power = spectrum[in_range] ** 2
    if power[in_tune[in_range]].sum() < MIN_TONAL * power.sum():
        return []  # too much of the sound is noise
    return sorted(pitches)


def root_from_audio(samples, sample_rate=SAMPLE_RATE, background=None, silence=SILENCE):
    """Root note name of a block of audio, or None if it is silent or not a note."""
    if np.sqrt(np.mean(samples ** 2)) < silence:
        return None
    root = find_root(pitches_in_audio(samples, sample_rate, background))
    return None if root is None else note_name(root)


def listen(device=None):
    """Listen to the microphone and yield the root of each note/chord as it is played.

    It first spends CALIBRATE_SECONDS measuring the background noise (keep quiet),
    which is then subtracted from everything it hears.

    A note is reported a few hops after its onset (a jump in loudness), so the
    analysis window is mostly the new note rather than the tail of the last one.
    """
    import sounddevice as sd

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, blocksize=HOP, device=device) as stream:
        # Measure the background: its average spectrum, and a loudness threshold above it.
        print('Measuring background noise, stay quiet...', flush=True)
        quiet = [stream.read(WINDOW)[0][:, 0] for _ in range(int(CALIBRATE_SECONDS * SAMPLE_RATE / WINDOW))]
        background = np.mean([spectrum_of(block)[1] for block in quiet], axis=0)
        silence = max(SILENCE, NOISE_MARGIN * np.sqrt(np.mean(np.concatenate(quiet) ** 2)))
        print('Listening... (Ctrl+C to stop)', flush=True)

        window = np.zeros(WINDOW)
        previous_rms = 0.0
        countdown = None  # hops left before reading a note that has just started

        while True:
            hop, _ = stream.read(HOP)
            hop = hop[:, 0]
            window = np.concatenate([window[HOP:], hop])

            rms = np.sqrt(np.mean(hop ** 2))
            if rms > silence and rms > ONSET_RATIO * previous_rms:
                countdown = SETTLE_HOPS
            previous_rms = rms

            if countdown is not None:
                countdown -= 1
                if countdown <= 0:
                    countdown = None
                    root = root_from_audio(window, background=background, silence=silence)
                    if root is not None:
                        yield root


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] != '--mic':
        print(' '.join(roots_from_midi(sys.argv[1])))
    else:
        try:
            for root in listen():
                print(root, flush=True)
        except KeyboardInterrupt:
            pass
