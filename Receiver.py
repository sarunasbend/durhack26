# Receiver: works out the root note of whatever is being played.
#
# Two inputs:
#   roots_from_midi('song.mid')   -> ['D4', 'G3', 'A3', ...]   one root per note/chord
#   for root in listen(): ...      -> yields roots live from the microphone
#
# And, using the trained model in training/ (see training/README.md):
#   decode_recording('take.wav')   -> the decoded text of a recorded message
#   for chars in listen_message(): -> yields one message's characters live from the microphone
#   for kind, value in listen_messages(): -> the same for message after message, without stopping
#
# A message starts at the sender's mark (a backtick) and ends at the next one.
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
#   python Receiver.py recording.wav
#   python Receiver.py --message            (shows a live level meter while it listens)
#   python Receiver.py --devices            (list microphones)
#   python Receiver.py --level              (only show how loud the microphone is; needs no model)
#   python Receiver.py --message 2          (use microphone number 2)

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


# ----- Decoding a whole message with the trained model -------------------------
# The model (training/models/instrument_NNN.pt) says which note started at each moment;
# training/common.py's MessageReceiver follows the sender's rhythm and turns
# the notes into text. Needs torch, so it is only imported when used.

MESSAGE_MARK = '`'   # the sender plays this before every message; hearing it again ends the message


def between_marks(decoded):
    """Pick the message out of everything decoded so far. Returns (message, ended).

    The message is what follows the first mark, up to the second mark if there is one.
    Nothing counts until the first mark has been decoded, and the marks are never part
    of the message. ended is True once the second mark has arrived.
    """
    start = decoded.find(MESSAGE_MARK)
    if start < 0:
        return '', False
    end = decoded.find(MESSAGE_MARK, start + 1)
    if end < 0:
        return decoded[start + 1:], False
    return decoded[start + 1:end], True


def _message_receiver():
    """Returns (common, a function that makes a fresh MessageReceiver). The model is loaded once."""
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'training'))
    import common
    # The model is chosen by the instrument Transmitter.py plays; the key and scale come from Settings.py.
    model, composer = common.load_model(), common.make_composer()
    return common, lambda: common.MessageReceiver(model, composer)


def decode_recording(wav_path):
    """Decoded text of a recorded message (a mono 22050 Hz .wav, as collect.py saves)."""
    common, make_receiver = _message_receiver()
    receiver = make_receiver()
    receiver.add_audio(common.load_wav(wav_path))
    receiver.finish()
    return receiver.text


def listen_messages(device=None, on_block=None):
    """Listen to the microphone for one message after another, until the generator is closed.

    Yields ('text', new_characters) as a message is decoded, and ('end', whole_message)
    when it ends. It then goes straight back to listening for the next message.

    A message starts at the sender's mark (a backtick) and ends at the next mark, or when
    the music stops (a whole character's worth of silence on the rhythm). The marks are
    not part of the text.

    device:   sounddevice input device number or name (default: the system's default input).
    on_block: optional function called about 5 times a second with (loudness, note_strength, receiver):
              the RMS level of the microphone, how sure the model is (0 to 1) that it just heard
              one of the key's notes, and the MessageReceiver itself. For showing what is being heard.
    """
    import queue
    import sounddevice as sd

    common, make_receiver = _message_receiver()
    receiver = make_receiver()
    receiver.dropped = 0   # times the sound card had to throw audio away
    sent = ''              # characters of the current message already yielded
    block = 8 * common.HOP  # ~0.19 s of audio at a time
    waiting = queue.Queue()

    # The sound card hands audio to this function on its own thread. It only queues it, so
    # no audio is lost if the model is slower than real time; decoding just runs a little late.
    def capture(samples, frames, time_info, status):
        if status.input_overflow:
            receiver.dropped += 1
        waiting.put(samples[:, 0].copy())

    with sd.InputStream(samplerate=common.SR, channels=1, blocksize=block, device=device, callback=capture):
        while True:
            samples = waiting.get()
            while not waiting.empty():          # catch up if we have fallen behind
                samples = np.concatenate([samples, waiting.get_nowait()])
            receiver.add_audio(samples)
            message, ended = between_marks(receiver.text)
            if on_block is not None:
                recent = receiver.probs[:, -8:]
                on_block(float(np.sqrt(np.mean(samples ** 2))), float(recent.max()) if recent.size else 0.0, receiver)
            if len(message) > len(sent):
                yield 'text', message[len(sent):]
                sent = message
            if ended or receiver.finished:
                if MESSAGE_MARK in receiver.text:    # a real message, not noise that never had a start mark
                    yield 'end', message
                # Start again with a fresh receiver, so the next message is caught from its first note.
                dropped = receiver.dropped
                receiver = make_receiver()
                receiver.dropped = dropped
                sent = ''


def listen_message(device=None, on_block=None):
    """Listen for one message and yield its characters as they are decoded, then stop.

    See listen_messages for how a message starts and ends.
    """
    messages = listen_messages(device, on_block)
    try:
        for kind, value in messages:
            if kind == 'end':
                return
            yield value
    finally:
        messages.close()   # closes the microphone


def _run_level_cli(device):
    """python Receiver.py --level [device]: just show how loud the microphone is. Needs no model."""
    import sounddevice as sd

    print('Microphone: %s   (Ctrl+C to stop)\n' % sd.query_devices(device, 'input')['name'], flush=True)
    try:
        with sd.InputStream(samplerate=22050, channels=1, blocksize=4096, device=device) as stream:
            while True:
                samples, _ = stream.read(4096)
                loudness = float(np.sqrt(np.mean(samples ** 2)))
                print('\rlevel %-30s %.4f' % ('#' * min(30, int(loudness * 600)), loudness), end='', flush=True)
    except KeyboardInterrupt:
        print()


def _run_message_cli(device):
    """python Receiver.py --message [device]: decode live, showing what the microphone hears."""
    import sounddevice as sd

    info = sd.query_devices(device, 'input')
    print('Microphone: %s' % info['name'])
    print('Loading the model (this can take a minute the first time)...', flush=True)

    state = {'text': '', 'silent_blocks': 0, 'warned': False, 'started': False}

    def show(loudness, note_strength, receiver):
        if not state['started']:
            state['started'] = True
            print('Listening. Waiting for a message... (Ctrl+C to stop)\n', flush=True)
        state['silent_blocks'] = state['silent_blocks'] + 1 if loudness < 1e-5 else 0
        if state['silent_blocks'] > 15 and not state['warned']:
            state['warned'] = True
            print('\nThe microphone is giving complete silence. Check that this terminal is allowed to use '
                  'the microphone,\nthat the microphone is not muted, and that the right one is selected '
                  '(python Receiver.py --devices).', flush=True)
        bar = '#' * min(20, int(loudness * 400))
        if state['text'] or receiver.clock is not None:
            detail = 'message: ' + state['text'].replace('\n', ' ')
        else:
            # Not started yet: show the last notes heard and the seconds between them.
            # A real message looks like "F#4 0.6 A#5 0.6 C#4 0.6 F#4 0.6 ..." (gaps of 0.3 or 0.6).
            notes = receiver.heard[-6:]
            detail = 'heard: ' + ' '.join(('%.1f ' % (t - notes[i - 1][0]) if i else '') + name
                                          for i, (t, name) in enumerate(notes))
        lost = '  LOST AUDIO x%d' % receiver.dropped if receiver.dropped else ''
        print('\rlevel %-20s note %3d%%%s  %-60s' % (bar, round(note_strength * 100), lost, detail), end='', flush=True)

    try:
        for kind, value in listen_messages(device, on_block=show):
            if kind == 'text':
                state['text'] += value
            else:
                # A message has ended: print it on its own line, then keep listening for the next.
                print('\r%-110s\rMessage: %s' % ('', value), flush=True)
                state['text'] = ''
    except KeyboardInterrupt:
        print('\n\nStopped.' + (' Message so far: %s' % state['text'] if state['text'] else ''))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1].endswith('.wav'):
        print(decode_recording(sys.argv[1]))
    elif len(sys.argv) > 1 and sys.argv[1] == '--devices':
        import sounddevice as sd
        print(sd.query_devices())
        print('\nUse a microphone by its number:  python Receiver.py --message 2')
    elif len(sys.argv) > 1 and sys.argv[1] == '--level':
        chosen = sys.argv[2] if len(sys.argv) > 2 else None
        _run_level_cli(int(chosen) if chosen is not None and chosen.isdigit() else chosen)
    elif len(sys.argv) > 1 and sys.argv[1] == '--message':
        chosen = sys.argv[2] if len(sys.argv) > 2 else None
        _run_message_cli(int(chosen) if chosen is not None and chosen.isdigit() else chosen)
    elif len(sys.argv) > 1 and sys.argv[1] != '--mic':
        print(' '.join(roots_from_midi(sys.argv[1])))
    else:
        try:
            for root in listen():
                print(root, flush=True)
        except KeyboardInterrupt:
            pass
