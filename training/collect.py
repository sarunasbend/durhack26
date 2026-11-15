# Makes training data: plays encoded messages through the speaker while recording the mic.
#
#   python training/collect.py --noise 45            # 45 s of the room with nothing playing
#   python training/collect.py --takes 24            # 24 random messages (~50 s each), cycling through all 12 keys
#   python training/collect.py --takes 6 --keys f#,c # only these keys
#
# Takes go in training/data/instrument_NNN/, where NNN is the instrument Transmitter.py
# plays (its General MIDI program number). Each take is saved as:
#   take_0001.wav   what the microphone heard
#   take_0001.mid   what was played
#   take_0001.json  the text, key, encoded notes, and when each note started
# Running it again adds more takes; nothing is overwritten.

import argparse
import json
import os
import random
import time

import pygame
import sounddevice as sd

import common

LEAD_IN = 0.5   # seconds of recording before playback starts
TAIL = 1.5      # seconds of recording after the MIDI file ends


def next_index(folder):
    used = [int(n[5:9]) for n in os.listdir(folder) if n.startswith('take_') and n.endswith('.json')]
    return max(used, default=0) + 1


def record_take(base, key, chars):
    composer = common.make_composer(key)
    # Random characters, so every character (and so every note) turns up equally often.
    characters = list(composer.stream_decode().decoding_table.values())
    text = ''.join(random.choice(characters) for _ in range(chars))
    print('%s  key %-2s  %r' % (os.path.basename(base), key, text), flush=True)

    drone = common.drone_for(key)
    encoded = common.write_midi(composer, text, base + '.mid', drone)
    onsets, length, program = common.midi_onsets(base + '.mid')

    pygame.mixer.music.load(base + '.mid')
    recording = sd.rec(int((LEAD_IN + length + TAIL) * common.SR), samplerate=common.SR, channels=1)
    time.sleep(LEAD_IN)
    pygame.mixer.music.play()
    sd.wait()
    pygame.mixer.music.stop()
    audio = recording[:, 0]

    common.save_wav(base + '.wav', audio)
    with open(base + '.json', 'w') as f:
        json.dump({'text': text, 'notes': encoded, 'onsets': onsets,
                   'offset': common.playback_offset(audio, [t for t, _ in onsets]),
                   'tempo': common.TEMPO, 'key': key, 'scale': common.SCALE_TYPE,
                   'drone': drone, 'program': program}, f)


def record_noise(base, seconds):
    print('%s  recording %.0f s of room noise' % (os.path.basename(base), seconds), flush=True)
    recording = sd.rec(int(seconds * common.SR), samplerate=common.SR, channels=1)
    sd.wait()
    common.save_wav(base + '.wav', recording[:, 0])
    with open(base + '.json', 'w') as f:
        json.dump({'text': '', 'notes': [], 'onsets': [], 'offset': 0.0}, f)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--takes', type=int, default=0, help='number of messages to play and record')
    parser.add_argument('--chars', type=int, default=40, help='characters per message')
    parser.add_argument('--keys', default=','.join(common.KEYS), help='keys to cycle through, e.g. f#,c,g (default: all 12)')
    parser.add_argument('--noise', type=float, default=0, help='seconds of room noise to record (nothing played)')
    args = parser.parse_args()

    folder = common.data_dir(common.current_program())
    os.makedirs(folder, exist_ok=True)
    keys = [k.strip().upper() for k in args.keys.split(',')]

    if args.noise:
        record_noise(os.path.join(folder, 'take_%04d' % next_index(folder)), args.noise)

    if args.takes:
        pygame.mixer.init()
        for _ in range(args.takes):
            index = next_index(folder)
            record_take(os.path.join(folder, 'take_%04d' % index), keys[index % len(keys)], args.chars)
