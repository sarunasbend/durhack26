# Receiver training

Trains a small neural network to hear which note has just started, from microphone
recordings of the sender's own output. There is one model per instrument, and each
model reads every key and scale: it has one output per semitone from C4 to B5.

Run everything from the repo root, on one machine with a speaker and a microphone:

    python training/collect.py --noise 45     # record the room with nothing playing
    python training/collect.py --takes 24     # play and record 24 random messages, cycling through all 12 keys
    python training/train.py                  # train, saves training/models/instrument_NNN.pt
    python training/evaluate.py               # decode the held-out takes and compare with the sent text

- **Instrument.** `NNN` is the General MIDI program number that `Transmitter.write` sets
  (004 = Electric Piano 1). All three scripts read it from there. To train another
  instrument, change it in `Transmitter.py` and run the same four commands; its takes and
  model get their own names and the existing ones are left alone.
- **Data.** `data/instrument_NNN/` holds every recording (`.wav`), what was played (`.mid`)
  and its labels (`.json`). Copy the folder to move training data to another machine;
  `collect.py` adds to it. It is not in git.
- **Testing.** Every 5th take is held out and never trained on.
- **Key, scale and tempo** come from `Settings.py` in the repo root, shared with the sender.
  The receiver must be told the key and scale (it only listens for that key's notes), but
  changing them needs no retraining. A different tempo or rhythm has not been tested;
  record a few takes and run `evaluate.py` before relying on it.
- `archive_*/` folders hold recordings and models made with earlier settings.
- Needs `torch`, `mido`, `pygame`, `sounddevice` and `numpy`.
