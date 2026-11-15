# Trains the note-start model for the instrument Transmitter.py currently plays, on the
# takes in training/data/instrument_NNN, and saves training/models/instrument_NNN.pt.
#
#   python training/train.py              # 5000 steps
#   python training/train.py --steps 8000
#
# Every 5th take is held out for testing. Each training example is a random 6 s slice
# of a take, at a random volume, with room noise mixed in at a random level, and often
# moved up or down a semitone or two so the model hears every note in every key.

import argparse
import math
import random

import torch

import common
import evaluate

CROP_FRAMES = 256   # ~6 s per training example
BATCH = 16
MAX_SHIFT = 2       # semitones a training example may be moved up or down

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--steps', type=int, default=5000)
    args = parser.parse_args()

    torch.manual_seed(0)
    random.seed(0)
    device = 'mps' if torch.backends.mps.is_available() else 'cuda' if torch.cuda.is_available() else 'cpu'
    program = common.current_program()

    takes = common.load_takes(program)
    train_takes = [t for t in takes if not common.is_validation(t)]
    val_takes = [t for t in takes if common.is_validation(t) and t['notes']]
    noise = [torch.from_numpy(t['audio']) for t in train_takes if not t['notes']]
    for take in train_takes:
        take['target'] = common.targets_for(take, len(take['audio']) // common.HOP + 1)
    keys = sorted({t['key'] for t in train_takes if t['notes']})
    print('instrument %d: %d training takes (%d of them room noise) in %d keys, %d held out, training on %s'
          % (program, len(train_takes), len(noise), len(keys), len(val_takes), device), flush=True)

    def batch():
        audio = torch.zeros(BATCH, CROP_FRAMES * common.HOP)
        target = torch.zeros(BATCH, len(common.NOTE_PITCHES), CROP_FRAMES + 1)
        for i in range(BATCH):
            take = random.choice(train_takes)
            start = random.randrange(len(take['audio']) // common.HOP - CROP_FRAMES)
            clip = torch.from_numpy(take['audio'][start * common.HOP:(start + CROP_FRAMES) * common.HOP])
            if noise and take['notes'] and random.random() < 0.7:
                room = random.choice(noise)
                at = random.randrange(len(room) - len(clip))
                clip = clip + random.uniform(0, 3) * room[at:at + len(clip)]
            audio[i] = clip * math.exp(random.uniform(-1.5, 1.0))  # random volume
            target[i] = torch.from_numpy(take['target'][:, start:start + CROP_FRAMES + 1])
        feats = common.features(audio.to(device))
        target = target.to(device)
        # Move half the examples to a nearby key: shift the sound and its labels together.
        for i in range(BATCH):
            shift = random.randint(-MAX_SHIFT, MAX_SHIFT) if random.random() < 0.5 else 0
            feats[i] = common.shift_semitones(feats[i], shift, common.BINS_PER_SEMITONE, math.log(1e-5))
            target[i] = common.shift_semitones(target[i], shift, 1, 0.0)
        return feats, target

    model = common.OnsetNet().to(device)
    optimiser = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-2)
    schedule = torch.optim.lr_scheduler.OneCycleLR(optimiser, max_lr=2e-3, total_steps=args.steps)
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=torch.tensor(3.0, device=device))

    running = 0.0
    for step in range(1, args.steps + 1):
        model.train()
        feats, target = batch()
        loss = loss_fn(model(feats), target)
        optimiser.zero_grad()
        loss.backward()
        optimiser.step()
        schedule.step()
        running += loss.item()

        if step % 500 == 0 or step == args.steps:
            model.eval()
            total = evaluate.score(model, val_takes, verbose=False)
            print('step %d  loss %.4f  held-out: %s' % (step, running / 500, evaluate.summary(total)), flush=True)
            running = 0.0

    common.save_model(model, program)
    print('saved', common.model_path(program))
    model.eval()
    print(evaluate.summary(evaluate.score(model, val_takes)))
