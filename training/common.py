# Shared pieces for collect.py, train.py and evaluate.py:
# the transmission settings, MIDI writing, audio features, the model, and decoding.

import json
import os
import sys
import wave

import numpy as np
import torch
import torch.nn as nn

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # so Avison, Transmitter etc. can be imported

import Avison
import Settings
import Transmitter

# ----- What the sender plays (from Settings.py, shared with the sender) ----------
KEY, SCALE_TYPE = Settings.KEY, Settings.SCALE_TYPE
TEMPO = Settings.TEMPO
KEYS = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# The model has one output per semitone across the octaves a message can use,
# so one model reads every key and scale. With the default Configuration that
# is C4 to B5: 24 outputs.
_config = Avison.Configuration()
NOTE_PITCHES = list(range((_config.first_octave + 1) * 12, (_config.first_octave + 1 + _config.octaves) * 12))


# ----- One data folder and one model per instrument ------------------------------
# The instrument is whatever Transmitter.write sets (a General MIDI program number).

def current_program():
    """The instrument the sender plays right now, read from a MIDI file it writes."""
    import tempfile
    transmitter = Transmitter.Transmitter()
    transmitter.config()
    transmitter.write(['C4'], [{'duration': 1, 'time': 1, 'volume': 90, 'previous': 0}], None, 0)
    with tempfile.TemporaryDirectory() as folder:
        transmitter.save(os.path.join(folder, 'probe.mid'))
        return midi_onsets(os.path.join(folder, 'probe.mid'))[2]


def data_dir(program):
    return os.path.join(HERE, 'data', 'instrument_%03d' % program)      # recordings and labels


def model_path(program):
    return os.path.join(HERE, 'models', 'instrument_%03d.pt' % program)

# ----- Audio ---------------------------------------------------------------------
SR = 22050            # sample rate of every recording
N_FFT = 2048          # ~93 ms analysis window
HOP = 512             # ~23 ms between frames
FRAME = HOP / SR      # seconds per frame
LOW_MIDI, HIGH_MIDI = 45, 108   # frequency range of the features (A2 to C8)
BINS_PER_SEMITONE = 3

# ----- Turning model output into notes ------------------------------------------
PEAK_THRESHOLD = 0.5  # how sure the model must be that a note started
PEAK_DISTANCE = 4     # frames either side the message's first note must stand out from


def make_composer(key=None, scale_type=None):
    """A Composer for the given key and scale (default: the ones in Settings.py)."""
    return Avison.Composer(key or KEY, scale_type or SCALE_TYPE)


def drone_for(key):
    """The drone the sender plays in a key: the key's root, in the octave Settings.DRONE uses."""
    return key.upper() + Settings.DRONE[-1] if Settings.DRONE else False


def note_table(composer):
    """The notes a message can use, e.g. ['C4', 'D#4', ...], and their MIDI pitches."""
    names = composer.stream_decode().notes.notes
    pitches = [Transmitter.Transmitter().calculatePitch(n) for n in names]
    return names, pitches


def write_midi(composer, text, path, drone=Settings.DRONE):
    """Encode text and write it as a MIDI file, exactly as the sender would play it."""
    encoded, metadata = composer.encode_message(text)
    transmitter = Transmitter.Transmitter()
    transmitter.config()
    transmitter.tempo = TEMPO
    transmitter.drone = drone
    transmitter.write(encoded, metadata, None, 0)
    transmitter.save(path)
    return encoded


def midi_onsets(path):
    """[(seconds, MIDI pitch)] for every note-on in a MIDI file, the file's length,
    and the instrument (General MIDI program number) it plays."""
    import mido
    midi = mido.MidiFile(path)
    onsets, t, program = [], 0.0, 0
    for msg in midi:
        t += msg.time
        if msg.type == 'note_on' and msg.velocity > 0:
            onsets.append((t, msg.note))
        if msg.type == 'program_change':
            program = msg.program
    return onsets, midi.length, program


# ----- Reading and writing recordings -----------------------------------------------

def save_wav(path, audio):
    with wave.open(path, 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def load_wav(path):
    with wave.open(path, 'rb') as f:
        assert f.getframerate() == SR and f.getnchannels() == 1, path
        return np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32767


def load_takes(program):
    """Every take recorded for an instrument, as a dict: its json fields plus 'name' and 'audio'."""
    folder, takes = data_dir(program), []
    for name in sorted(os.listdir(folder)):
        if name.endswith('.json'):
            with open(os.path.join(folder, name)) as f:
                take = json.load(f)
            take['name'] = name[:-5]
            take['audio'] = load_wav(os.path.join(folder, name[:-5] + '.wav'))
            takes.append(take)
    return takes


def is_validation(take):
    """Every 5th take is held out and never trained on."""
    return int(take['name'].split('_')[-1]) % 5 == 0


# ----- Features ----------------------------------------------------------------------

def _filterbank():
    """Matrix that turns an FFT magnitude spectrum into bins spaced evenly in pitch."""
    fft_freqs = np.fft.rfftfreq(N_FFT, 1.0 / SR)
    midi = np.arange(LOW_MIDI * BINS_PER_SEMITONE - 1, HIGH_MIDI * BINS_PER_SEMITONE + 1) / BINS_PER_SEMITONE
    centres = 440.0 * 2 ** ((midi - 69) / 12)
    bank = np.zeros((len(centres) - 2, len(fft_freqs)), dtype=np.float32)
    bin_hz = fft_freqs[1]
    for i in range(1, len(centres) - 1):
        # Triangle around each centre, never narrower than one FFT bin either side.
        lo = min(centres[i - 1], centres[i] - bin_hz)
        hi = max(centres[i + 1], centres[i] + bin_hz)
        up = (fft_freqs - lo) / (centres[i] - lo)
        down = (hi - fft_freqs) / (hi - centres[i])
        tri = np.clip(np.minimum(up, down), 0, None)
        bank[i - 1] = tri / tri.sum()
    return torch.from_numpy(bank)


FILTERBANK = _filterbank()
N_BINS = FILTERBANK.shape[0]


def features(audio, hop=HOP):
    """Log spectrogram with pitch-spaced bins. audio: (..., samples) tensor -> (..., N_BINS, frames).

    Frame i is centred on sample i * hop.
    """
    window = torch.hann_window(N_FFT, device=audio.device)
    spec = torch.stft(audio, N_FFT, hop_length=hop, window=window, return_complex=True).abs()
    return torch.log(FILTERBANK.to(audio.device) @ spec + 1e-5)


def playback_offset(audio, onset_times, max_offset=2.0):
    """Seconds into the recording at which the MIDI file's time 0 happens.

    Slides the expected note starts along the recording and picks the position
    where they best line up with sudden rises in the sound.
    """
    hop = 128  # finer than HOP, for ~6 ms precision
    feats = features(torch.from_numpy(audio), hop=hop)
    rise = torch.clamp(feats[:, 1:] - feats[:, :-1], min=0).sum(0).numpy()
    expected = np.round(np.array(onset_times) * SR / hop).astype(int)
    best, best_score = 0, -1.0
    for lag in range(int(max_offset * SR / hop)):
        idx = expected + lag
        idx = idx[idx < len(rise)]
        score = rise[idx].sum()
        if score > best_score:
            best, best_score = lag, score
    return best * hop / SR


def targets_for(take, n_frames):
    """(semitones, frames) array: 1 on the frame where each note starts and its two neighbours.
    Notes outside NOTE_PITCHES (the drone) get no row, so the model learns to ignore them."""
    target = np.zeros((len(NOTE_PITCHES), n_frames), dtype=np.float32)
    for t, pitch in take['onsets']:
        if pitch in NOTE_PITCHES:
            frame = int(round((t + take['offset']) / FRAME))
            target[NOTE_PITCHES.index(pitch), max(0, frame - 1):frame + 2] = 1.0
    return target


def shift_semitones(array, semitones, rows_per_semitone, fill):
    """Move a (..., rows, frames) tensor up by a number of semitones along its pitch axis.
    Used in training to turn one recording into the same music in a nearby key."""
    if semitones == 0:
        return array
    moved = torch.full_like(array, fill)
    n = semitones * rows_per_semitone
    if n > 0:
        moved[..., n:, :] = array[..., :-n, :]
    else:
        moved[..., :n, :] = array[..., -n:, :]
    return moved


# ----- Model -----------------------------------------------------------------------

class OnsetNet(nn.Module):
    """For every frame, says how likely it is that each message note started there.

    It sees about 0.3 s around each frame, and works on any length of audio.
    """

    def __init__(self, n_notes=len(NOTE_PITCHES)):
        super().__init__()

        def block(cin, cout, pool):
            layers = [nn.Conv2d(cin, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU()]
            if pool:
                layers.append(nn.MaxPool2d((3, 1)))  # shrink pitch axis only, keep time
            return layers

        self.conv = nn.Sequential(*block(1, 32, False), *block(32, 32, True),
                                  *block(32, 64, True), *block(64, 64, True))
        self.head = nn.Sequential(nn.Conv1d(64 * (N_BINS // 27), 128, 5, padding=2), nn.ReLU(),
                                  nn.Dropout(0.3), nn.Conv1d(128, n_notes, 1))

    def forward(self, feats):                 # (batch, N_BINS, frames)
        x = self.conv(feats.unsqueeze(1))     # (batch, 64, N_BINS/27, frames)
        return self.head(x.flatten(1, 2))     # (batch, notes, frames) logits


def save_model(model, program):
    os.makedirs(os.path.dirname(model_path(program)), exist_ok=True)
    torch.save({'state': model.state_dict(), 'program': program, 'pitches': NOTE_PITCHES}, model_path(program))


def load_model(program=None, device='cpu'):
    """The trained model for an instrument (default: the one the sender plays now)."""
    program = current_program() if program is None else program
    if not os.path.exists(model_path(program)):
        raise FileNotFoundError('No model for instrument %d yet. Record takes with training/collect.py '
                                'and run training/train.py.' % program)
    saved = torch.load(model_path(program), map_location=device)
    assert saved['pitches'] == NOTE_PITCHES, 'model was trained for a different range of notes'
    model = OnsetNet(len(saved['pitches']))
    model.load_state_dict(saved['state'])
    return model.to(device).eval()


# ----- Scoring -------------------------------------------------------------------------

def edit_distance(a, b):
    """Number of single-character insertions, deletions or swaps to turn a into b."""
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        previous, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (ca != cb))
    return row[-1]


# ----- Rhythm-based receiver ----------------------------------------------------------
# The sender's rhythm is fixed (Encoder.note_pattern at TEMPO), so once the first
# note is heard we know when every later note is due. Instead of hunting for note
# starts, we look at each due time and ask the model which note it was.

SEARCH = 3            # frames either side of the due time to look for the note (~70 ms)
MARGIN = 10           # frames at the edge of the audio that need more context before being trusted
END_THRESHOLD = 0.5   # below this, the model did not clearly hear a note at a due time
END_SLOTS = 3         # this many empty due times in a row (one whole character) means the message is over
DRONE_EVERY = 8       # Transmitter.write restarts the drone on every 8th note
DRONE_OVERTONE = 19   # semitones above the drone where its loudest overtone sits (an octave and a fifth)
OVERTONE_RIVAL = 0.3  # when the drone restarts, another note this strong beats the drone's overtone
START_CHECK = 5       # notes after the first that must fit the rhythm before a message counts as started


def rhythm_gaps(composer):
    """Frames between each note start and the next, for one cycle of the sender's rhythm."""
    encoder = Avison.e.Encoder(composer.configuration, Avison.Tokenizer(''), composer.scale)
    # Transmitter.write starts the next note 2 x 'time' beats after this one.
    beats = [2 * encoder.convert_to_meta(kind)['time'] for kind in encoder.note_pattern]
    return [b * 60.0 / TEMPO / FRAME for b in beats]


class MessageReceiver:
    """Feed it audio as it arrives; it decodes the message as it goes.
    The composer says which key and scale the message is in.

        receiver = MessageReceiver(model, composer)
        new_text = receiver.add_audio(samples)   # call repeatedly; returns newly decoded characters
        receiver.text, receiver.notes, receiver.finished
    """

    def __init__(self, model, composer, drone=Settings.DRONE):
        self.model = model
        # The model has an output for every semitone; only the ones in this key can be
        # message notes, so the rest are ignored.
        self.names, pitches = note_table(composer)
        self.rows = [NOTE_PITCHES.index(p) for p in pitches]
        # The drone is too low for a laptop speaker, so what is heard of it is mostly its
        # overtones, and the loudest one can land exactly on a message note. Each time the
        # drone restarts, that note is distrusted (see _look).
        overtone = Transmitter.Transmitter().calculatePitch(drone) + DRONE_OVERTONE if drone else None
        self.overtone_row = pitches.index(overtone) if overtone in pitches else None
        decoder = composer.stream_decode()
        self.table = decoder.decoding_table
        self.size = decoder.configuration.cluster_size
        self.first_notes = {key.split(',')[0] for key in self.table}  # notes a character can start with
        self.first_rows = [i for i, name in enumerate(self.names) if name in self.first_notes]
        self.gaps = rhythm_gaps(composer)

        self.audio = np.zeros(0, dtype=np.float32)   # audio not yet fully analysed
        self.audio_frame = 0                          # frame number of self.audio[0]
        self.probs = np.zeros((len(self.names), 0), dtype=np.float32)  # model output for every frame so far
        self.scan = 0                                 # next frame to check for the first note
        self.heard = []                               # last few notes heard while waiting: (seconds, name)
        self._reset()

    def _reset(self):
        self.notes = []        # note names heard so far
        self.weak = 0          # how many of the latest due times had nothing there
        self.clock = None      # frame at which the next note is due (None = still waiting for the first)
        self.text = ''
        self.finished = False

    def add_audio(self, samples):
        if self.finished:
            return ''
        self.audio = np.concatenate([self.audio, np.asarray(samples, dtype=np.float32)])
        self._run_model()
        return self._decode()

    def finish(self):
        """Call when no more audio is coming, so the last few frames get used too."""
        return self.add_audio(np.zeros(2 * MARGIN * HOP, dtype=np.float32))

    def _run_model(self):
        """Extend self.probs with every frame that now has enough audio either side of it."""
        done = self.probs.shape[1]
        end = self.audio_frame + len(self.audio) // HOP + 1 - MARGIN
        if end <= done or len(self.audio) <= N_FFT:
            return
        device = next(self.model.parameters()).device
        with torch.no_grad():
            out = torch.sigmoid(self.model(features(torch.from_numpy(self.audio).to(device)).unsqueeze(0)))[0]
        out = out.cpu().numpy()[self.rows]
        self.probs = np.concatenate([self.probs, out[:, done - self.audio_frame:end - self.audio_frame]], axis=1)
        # Keep only the audio the next call needs.
        keep_from = max(self.audio_frame, end - MARGIN)
        self.audio = self.audio[(keep_from - self.audio_frame) * HOP:]
        self.audio_frame = keep_from

    def _look(self, due, drone_restarts=False):
        """The most likely note around frame `due`: (name, how sure, the frame it was at)."""
        window = self.probs[:, due - SEARCH:due + SEARCH + 1]
        strengths = window.max(axis=1)
        best = int(strengths.argmax())
        if drone_restarts and best == self.overtone_row:
            # Probably the drone's overtone, not a message note, if anything else was heard too.
            strengths[best] = 0
            if strengths.max() >= OVERTONE_RIVAL:
                best = int(strengths.argmax())
        return self.names[best], float(window[best].max()), due - SEARCH + int(window[best].argmax())

    def _decode(self):
        available = self.probs.shape[1]
        while not self.finished:
            if self.clock is None:
                # Waiting for the message to start. The first note must be a clear peak on a
                # note that can start a character, and the notes after it must arrive on the
                # rhythm too, or a stray sound before the message would set the timing wrong.
                check = np.cumsum(self.gaps[:START_CHECK])            # when the next few notes are due
                if self.scan + check[-1] + SEARCH + 1 >= available:
                    break
                t = self.scan
                self.scan += 1
                nearby = self.probs[:, max(0, t - PEAK_DISTANCE):t + PEAK_DISTANCE + 1]
                if self.probs[:, t].max() >= PEAK_THRESHOLD and self.probs[:, t].max() >= nearby.max():
                    # Keep a short log of what is being heard, for showing while waiting.
                    self.heard = (self.heard + [(t * FRAME, self.names[int(self.probs[:, t].argmax())])])[-10:]
                # A possible first note: a clear peak on a note that can start a character. It need
                # not be the strongest note at that moment, because the drone starts with it and
                # the drone's overtone can be louder.
                first = max(self.first_rows, key=lambda row: self.probs[row, t])
                if self.probs[first, t] < PEAK_THRESHOLD or self.probs[first, t] < nearby[first].max():
                    continue
                heard = [self._look(int(round(t + c))) for c in check]
                heard.insert(0, (self.names[first], 1.0, t))
                starts_ok = all(heard[i][0] in self.first_notes for i in range(0, len(heard), self.size))
                clear = sum(strength >= PEAK_THRESHOLD for _, strength, _ in heard)
                if starts_ok and clear >= len(heard) - 1:
                    self.notes = [heard[0][0]]
                    self.clock = t + self.gaps[0]
                continue

            due = int(round(self.clock))
            if due + SEARCH >= available:
                break
            note, strength, heard = self._look(due, drone_restarts=len(self.notes) % DRONE_EVERY == 0)
            self.notes.append(note)
            self.weak = self.weak + 1 if strength < END_THRESHOLD else 0
            if strength >= PEAK_THRESHOLD:
                # Heard clearly: nudge the clock towards where the note really was,
                # so the two devices' clocks can't slowly drift apart.
                self.clock += 0.5 * (heard - self.clock)
            self.clock += self.gaps[(len(self.notes) - 1) % len(self.gaps)]

            if self.weak >= END_SLOTS:
                del self.notes[-self.weak:]
                if len(self.notes) < self.size:
                    # Not even one character: it was a false start, keep listening.
                    self.scan = due
                    self._reset()
                    continue
                self.weak = 0
                self.finished = True

        # Decode complete groups, leaving out trailing notes that may turn out to be nothing.
        sure = self.notes[:len(self.notes) - self.weak]
        text = ''.join(self.table.get(','.join(sure[i:i + self.size]), '?')
                       for i in range(0, len(sure) - self.size + 1, self.size))
        new, self.text = text[len(self.text):], text
        return new


def decode_recording(model, composer, audio, drone=Settings.DRONE):
    """Decode a whole recording. Returns the MessageReceiver (see .text and .notes)."""
    receiver = MessageReceiver(model, composer, drone)
    receiver.add_audio(audio)
    receiver.finish()
    return receiver
