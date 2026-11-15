# Draws the graphs used in devlog/receiver.md. Run from the repo root:
#
#   python devlog/make_graphs.py
#
# Needs matplotlib (not in requirements.txt). Graphs 1-4 are drawn from the numbers
# written below, which were copied from the training and evaluation output during
# development. Graph 5 runs the trained model on a held-out recording, so it needs
# training/models/ and training/data/ to be present; it is skipped if they are not.

import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'training'))

# Colours: three series colours that stay distinguishable for colour-blind readers,
# on a near-white surface, with all text in neutral ink.
BLUE, ORANGE, AQUA = '#2a78d6', '#eb6834', '#1baf7a'
SURFACE, INK, MUTED, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#e4e3df'

plt.rcParams.update({
    'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE, 'savefig.facecolor': SURFACE,
    'font.size': 11, 'text.color': INK, 'axes.labelcolor': MUTED, 'axes.edgecolor': GRID,
    'xtick.color': MUTED, 'ytick.color': MUTED, 'axes.titlesize': 13, 'axes.titleweight': 'bold',
    'axes.titlelocation': 'left', 'axes.spines.top': False, 'axes.spines.right': False,
    'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.8, 'axes.axisbelow': True,
    'legend.frameon': False,
})


def save(fig, name):
    fig.savefig(os.path.join(HERE, name), dpi=160, bbox_inches='tight')
    plt.close(fig)
    print('wrote', name)


# ----- 1. Character error rate at each stage of development ---------------------------
# (stage, character errors, characters tested). Each is measured on held-out recordings,
# but the set of recordings grew over time, so neighbouring bars are not the same test.
STAGES = [
    ('Chiff lead: find note starts\n(with a double-counting bug)', 41, 120),
    ('Double-counting bug fixed', 15, 120),
    ("Decode on the sender's rhythm", 4, 120),
    ('New instrument (electric piano),\nF# only', 2, 120),
    ('One model for all 12 keys', 8, 320),
    ('Drone-overtone rule and\nstricter end of message', 4, 320),
    ('Detachable-mic takes added', 6, 480),
]

fig, ax = plt.subplots(figsize=(9, 4.8))
rates = [100.0 * errors / chars for _, errors, chars in STAGES]
ys = np.arange(len(STAGES))[::-1]
ax.barh(ys, rates, height=0.55, color=BLUE)
for y, rate, (_, errors, chars) in zip(ys, rates, STAGES):
    ax.text(rate + 0.6, y, '%.1f%%  (%d of %d)' % (rate, errors, chars), va='center', color=INK)
ax.set_yticks(ys)
ax.set_yticklabels([s[0] for s in STAGES], color=INK)
ax.set_xlim(0, 44)
ax.set_xlabel('Characters decoded wrongly on held-out recordings (%)')
ax.set_title('Character error rate fell from 34% to about 1%')
ax.grid(axis='y', visible=False)
save(fig, '1_error_rate_by_stage.png')


# ----- 2. Training curves for the three electric-piano training runs --------------------
RUNS = [
    # name, colour, held-out notes right (%) and training loss at steps 500, 1000, ...
    ('F# only (18 takes)', BLUE,
     [98.6, 98.9, 99.7, 99.4, 99.2, 99.4, 99.4, 99.4],
     [0.1197, 0.0274, 0.0196, 0.0163, 0.0143, 0.0127, 0.0116, 0.0113]),
    ('All 12 keys (42 takes)', ORANGE,
     [88.2, 99.0, 90.0, 99.4, 99.5, 99.5, 99.5, 99.5, 99.5, 99.4],
     [0.1118, 0.0183, 0.0127, 0.0104, 0.0091, 0.0082, 0.0074, 0.0070, 0.0066, 0.0063]),
    ('All 12 keys, two microphones (67 takes)', AQUA,
     [65.8, 99.0, 99.4, 99.3, 99.3, 99.4, 99.6, 99.4, 99.7, 99.7, 99.7, 99.7],
     [0.1198, 0.0234, 0.0160, 0.0133, 0.0116, 0.0109, 0.0097, 0.0095, 0.0087, 0.0084, 0.0082, 0.0079]),
]

fig, (top, bottom) = plt.subplots(2, 1, figsize=(9, 6.6), sharex=True, gridspec_kw={'hspace': 0.28})
for name, colour, accuracy, loss in RUNS:
    steps = 500 * np.arange(1, len(accuracy) + 1)
    top.plot(steps, accuracy, color=colour, linewidth=2, marker='o', markersize=5, label=name)
    bottom.plot(steps, loss, color=colour, linewidth=2, marker='o', markersize=5, label=name)
top.set_ylim(60, 101)
top.set_ylabel('Held-out notes right (%)')
top.set_title('Every run reaches about 99% of notes within 2,000 steps')
top.legend(loc='lower right')
top.annotate('one held-out take decoded from\nthe wrong starting point', xy=(1500, 90.0), xytext=(2100, 78),
             color=MUTED, fontsize=10, arrowprops={'arrowstyle': '-', 'color': MUTED, 'linewidth': 0.8})
bottom.set_yscale('log')
bottom.set_ylabel('Training loss (log scale)')
bottom.set_xlabel('Training step')
bottom.set_title('Training loss')
save(fig, '2_training_curves.png')


# ----- 3. Reading other keys ------------------------------------------------------------
# One 20-character message (60 notes) per key, none of them used in training.
KEYS = ['F', 'G', 'A', 'C', 'D']
KEY_RESULTS = [
    ('F#-only model, as is', BLUE, [0, 0, 0, 0, 0]),
    ('F#-only model, audio pitch-shifted to F#', ORANGE, [60, 59, 55, 53, 48]),
    ('Any-key model (final)', AQUA, [60, 60, 60, 60, 56]),
]

fig, ax = plt.subplots(figsize=(9, 4.6))
width = 0.25
for i, (name, colour, right) in enumerate(KEY_RESULTS):
    xs = np.arange(len(KEYS)) + (i - 1) * (width + 0.02)
    ax.bar(xs, right, width=width, color=colour, label=name)
    for x, value in zip(xs, right):
        ax.text(x, value + 1, str(value), ha='center', color=INK, fontsize=10)
ax.set_xticks(np.arange(len(KEYS)))
ax.set_xticklabels(['%s major\npentatonic' % k for k in KEYS], color=INK)
ax.set_ylim(0, 66)
ax.set_yticks([0, 20, 40, 60])
ax.set_ylabel('Notes right, out of 60')
ax.set_title('Reading keys the model was not trained for', pad=34)
ax.legend(loc='lower left', ncol=3, bbox_to_anchor=(0.0, 1.0), columnspacing=1.2, handlelength=1.2, borderaxespad=0.2)
ax.grid(axis='x', visible=False)
save(fig, '3_other_keys.png')


# ----- 4. The whole receiver, from microphone to text -----------------------------------
STEPS = [
    ('Microphone', '22,050 samples\na second', None),
    ('Spectrogram', '2,048-sample windows\nevery 23 ms, squashed into\n189 pitch bins (3 per\nsemitone, A2 to C8)', None),
    ('4 convolution blocks', '3x3 filters with\n32, 32, 64, 64 channels.\nPitch axis shrunk\n189 > 63 > 21 > 7', BLUE),
    ('Time convolution', '448 > 128 channels,\n5 frames wide,\nthen dropout', BLUE),
    ('24 outputs per frame', 'One per semitone,\nC4 to B5: "did this note\nstart here?" (0 to 1)', BLUE),
    ("Keep the key's notes", 'e.g. 10 of the 24\noutputs for F# major\npentatonic', None),
    ('Rhythm decoder', "Find the first note, then\nread the strongest note\neach time the sender's\nrhythm says one is due", None),
    ('Text', 'Every 3 notes\nlook up one\ncharacter', None),
]

fig, ax = plt.subplots(figsize=(13, 5.4))
ax.set_axis_off()
ax.set_xlim(0, 4 * 3.2)
ax.set_ylim(0, 5.4)
box_w, box_h = 2.75, 1.95
positions = [(0.15 + 3.2 * col, 3.05 - 2.75 * row) for row in range(2) for col in range(4)]
for (x, y), (title, detail, colour) in zip(positions, STEPS):
    ax.add_patch(FancyBboxPatch((x, y), box_w, box_h, boxstyle='round,pad=0.02,rounding_size=0.12',
                                facecolor='#e9f1fb' if colour else '#f1f0ec', edgecolor=colour or '#b9b8b2', linewidth=1.4))
    ax.text(x + box_w / 2, y + box_h - 0.33, title, ha='center', va='center', fontsize=12, fontweight='bold', color=INK)
    ax.text(x + box_w / 2, y + (box_h - 0.55) / 2, detail, ha='center', va='center', fontsize=10, color=MUTED, linespacing=1.35)
for i in range(len(positions) - 1):
    (x0, y0), (x1, y1) = positions[i], positions[i + 1]
    if y0 == y1:
        start, end = (x0 + box_w + 0.04, y0 + box_h / 2), (x1 - 0.04, y1 + box_h / 2)
    else:
        # From the end of the top row, down and back across to the start of the bottom row.
        middle = (y0 + y1 + box_h) / 2
        ax.plot([x0 + box_w / 2, x0 + box_w / 2, x1 + box_w / 2], [y0 - 0.05, middle, middle], color=MUTED, linewidth=1.3)
        start, end = (x1 + box_w / 2, middle), (x1 + box_w / 2, y1 + box_h + 0.05)
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle='-|>', mutation_scale=14, color=MUTED, linewidth=1.3))
ax.text(0.15, 5.25, 'From microphone to text', fontsize=13, fontweight='bold', color=INK, va='center')
ax.text(4.35, 5.25, 'Blue boxes are the neural network (355,320 weights). The rest is ordinary code.', fontsize=10, color=MUTED, va='center')
save(fig, '4_receiver_pipeline.png')


# ----- 5. What the network hears and what it says, on a held-out recording --------------
try:
    import torch
    import common
    program = common.current_program()
    take = next(t for t in common.load_takes(program) if t['name'] == 'take_0050')   # held out, key of D
    model = common.load_model(program)
except Exception as problem:   # no data or model on this machine
    print('skipped 5_what_the_network_hears.png:', problem)
else:
    seconds = 8.0
    frames = int(seconds / common.FRAME)
    audio = torch.from_numpy(take['audio'])
    feats = common.features(audio)
    with torch.no_grad():
        outputs = torch.sigmoid(model(feats.unsqueeze(0)))[0].numpy()
    names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

    fig, (top, bottom) = plt.subplots(2, 1, figsize=(11, 7.4), sharex=True, gridspec_kw={'hspace': 0.2, 'height_ratios': [1.15, 1]})
    extent = [0, frames * common.FRAME, 0, common.N_BINS]
    top.imshow(feats[:, :frames].numpy(), origin='lower', aspect='auto', cmap='Blues', extent=extent, vmin=-9, vmax=1)
    octave_bins = [(12 * (o + 1) - common.LOW_MIDI) * common.BINS_PER_SEMITONE for o in range(3, 9)]
    top.set_yticks(octave_bins)
    top.set_yticklabels(['C%d' % o for o in range(3, 9)])
    top.set_ylabel('Pitch')
    top.set_title('What goes in: 8 seconds of a message in D, as the network sees it')
    top.grid(False)

    extent = [0, frames * common.FRAME, -0.5, len(common.NOTE_PITCHES) - 0.5]
    bottom.imshow(outputs[:, :frames], origin='lower', aspect='auto', cmap='Blues', extent=extent, vmin=0, vmax=1)
    sent = [(t + take['offset'], common.NOTE_PITCHES.index(p)) for t, p in take['onsets']
            if p in common.NOTE_PITCHES and t + take['offset'] < seconds]
    bottom.scatter([t for t, _ in sent], [row for _, row in sent], s=70, facecolors='none', edgecolors=ORANGE, linewidths=1.6,
                   label='note the sender actually played')
    rows = range(0, len(common.NOTE_PITCHES), 2)
    bottom.set_yticks(list(rows))
    bottom.set_yticklabels(['%s%d' % (names[common.NOTE_PITCHES[r] % 12], common.NOTE_PITCHES[r] // 12 - 1) for r in rows])
    bottom.set_ylabel('Network output (one row per semitone)')
    bottom.set_xlabel('Seconds')
    bottom.set_title('What comes out: note starts found by the network (rings = notes actually sent)')
    bottom.grid(False)
    save(fig, '5_what_the_network_hears.png')


# ----- 6. The network layer by layer ----------------------------------------------------
# Each stage is drawn as a stack of sheets. For the blue stages a sheet is a picture
# (pitch up the side, time along the bottom) and the sheet's height shows how many
# pitch rows are left. For the orange stages pitch has been folded away and the
# column's height shows how many values there are per frame.
LAYERS = [
    # kind, sheets drawn, size shown as height, shape text, what produced it, weights
    ('input', 1, 189, '1 x 189', 'Spectrogram\n189 pitch bins\nper frame', None),
    ('2d', 3, 189, '32 x 189', 'Conv 3x3\nBatchNorm, ReLU', 384),
    ('2d', 3, 63, '32 x 63', 'Conv 3x3\nBatchNorm, ReLU\nMaxPool 3 (pitch)', 9312),
    ('2d', 5, 21, '64 x 21', 'Conv 3x3\nBatchNorm, ReLU\nMaxPool 3 (pitch)', 18624),
    ('2d', 5, 7, '64 x 7', 'Conv 3x3\nBatchNorm, ReLU\nMaxPool 3 (pitch)', 37056),
    ('1d', 1, 448, '448', 'Flatten:\n64 x 7 values\nside by side', 0),
    ('1d', 1, 128, '128', 'Conv over time\n5 frames wide\nReLU, Dropout 0.3', 286848),
    ('1d', 1, 24, '24', 'Conv 1 frame wide\nSigmoid:\none value per\nsemitone, C4 to B5', 3096),
]

fig, ax = plt.subplots(figsize=(14, 6.6))
ax.set_axis_off()
ax.set_xlim(0, 14)
ax.set_ylim(0, 6.6)
centre_y, pitch = 3.75, 14 / len(LAYERS)
previous_right = None
for i, (kind, sheets, size, shape, made_by, weights) in enumerate(LAYERS):
    cx = pitch * (i + 0.5)
    if kind == '1d':
        width, height = 0.34, 0.45 + 2.5 * (size / 448) ** 0.5
        face, edge = '#fbe6dc', ORANGE
    else:
        width, height = 0.95, 0.45 + 2.5 * (size / 189) ** 0.5
        face, edge = ('#f1f0ec', '#b9b8b2') if kind == 'input' else ('#e9f1fb', BLUE)
    step = 0.07
    left = cx - (width + step * (sheets - 1)) / 2
    bottom = centre_y - (height + step * (sheets - 1)) / 2
    for s in range(sheets - 1, -1, -1):   # back sheet first
        ax.add_patch(plt.Rectangle((left + s * step, bottom + s * step), width, height,
                                   facecolor=face, edgecolor=edge, linewidth=1.3))
    right = left + width + step * (sheets - 1)
    top = bottom + height + step * (sheets - 1)
    if previous_right is not None:
        ax.add_patch(FancyArrowPatch((previous_right + 0.08, centre_y), (left - 0.08, centre_y),
                                     arrowstyle='-|>', mutation_scale=13, color=MUTED, linewidth=1.2))
    previous_right = right
    ax.text(cx, top + 0.16, shape, ha='center', va='bottom', fontsize=12, fontweight='bold', color=INK)
    ax.text(cx, 1.78, made_by, ha='center', va='top', fontsize=9.5, color=INK, linespacing=1.35)
    if weights is not None:
        ax.text(cx, 0.52, '{:,} weights'.format(weights) if weights else 'no weights', ha='center', va='top',
                fontsize=9.5, color=MUTED)

ax.text(0.15, 6.4, 'The network, layer by layer', fontsize=13, fontweight='bold', color=INK, va='center')
ax.text(0.15, 6.02, 'Numbers above each stage: channels x pitch rows, for every 23 ms frame. '
                    'Time is never shrunk, so there is one answer per frame.', fontsize=10, color=MUTED, va='center')
ax.add_patch(plt.Rectangle((8.05, 6.29), 0.22, 0.22, facecolor='#e9f1fb', edgecolor=BLUE, linewidth=1.3))
ax.text(8.37, 6.4, 'still a picture: pitch x time', fontsize=10, color=INK, va='center')
ax.add_patch(plt.Rectangle((11.1, 6.29), 0.22, 0.22, facecolor='#fbe6dc', edgecolor=ORANGE, linewidth=1.3))
ax.text(11.42, 6.4, 'a list of values per frame', fontsize=10, color=INK, va='center')
ax.text(0.15, 0.1, '355,320 weights in total. Each output is computed from 13 frames of audio, about 0.3 seconds.',
        fontsize=10, color=MUTED, va='center')
save(fig, '6_network_layers.png')
