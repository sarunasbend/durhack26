# Two-laptop guide: training, then sending a message

- **Laptop A = the sender.** It plays the music. Use the M5 Mac for this: it already has the
  recordings and can train the model. It must be the same laptop that plays in the demo,
  because the model learns that laptop's speaker.
- **Laptop B = the receiver.** It listens and shows the decoded text.
- **The mic** is plugged into A while recording training data, then moved to B.

Run every command from the `durhack26` folder, with the project's Python environment active.

## Stage 1: get both laptops ready

| Step | Laptop A (sender) | Laptop B (receiver) |
|---|---|---|
| 1 | `git push origin Receiver` | |
| 2 | | `git checkout Receiver`, `git pull`, `pip install -r requirements.txt` |

## Stage 2: record training data (about 25 minutes, B is not used)

| Step | Laptop A (sender) | Laptop B (receiver) |
|---|---|---|
| 3 | Plug the mic into A. Make it the default input in System Settings > Sound. Turn off any noise reduction for it. | idle |
| 4 | Put the mic where it will sit in the demo. Set the speaker volume you will use in the demo. Do not move either from now on. | idle |
| 5 | `python training/collect.py --takes 1` and check you hear about 50 seconds of music. | idle |
| 6 | `python training/collect.py --noise 45 --takes 24` and keep the room as it will be in the demo. | idle |

## Stage 3: train (about 10 minutes, B is not used)

| Step | Laptop A (sender) | Laptop B (receiver) |
|---|---|---|
| 7 | `python training/train.py` | idle |
| 8 | `python training/evaluate.py` and read the last line. Aim for a character error rate under 3%. | idle |
| 9 | `git add training/models`, `git commit -m "Retrained model"`, `git push origin Receiver` | |

## Stage 4: send a message from A to B

| Step | Laptop A (sender) | Laptop B (receiver) |
|---|---|---|
| 10 | | `git pull` to get the new model |
| 11 | Unplug the mic. | Plug the mic into B and make it the default input. Put it in the same spot as in stage 2. |
| 11a | | **On Windows: turn off the mic's audio processing.** Settings > System > Sound > Input > the mic's properties > "Audio enhancements" off. With it on, Windows removes held notes as if they were noise and the message comes out wrong. |
| 12 | Set `message` in `main.py` to at least two characters (it is empty at the moment). | |
| 13 | | `python Receiver.py --message` and wait for "Listening. Waiting for a message..." |
| 14 | `python main.py` | Text appears as it is decoded. It stops by itself when the message ends. |

## If something goes wrong

| What you see | Likely cause |
|---|---|
| `collect.py` prints its usage and exits | It was run without `--takes` or `--noise`. |
| `No module named 'pygame'` (or `torch`) | The project's Python environment is not active, or the requirements are not installed. |
| No sound in step 5 | A's output is muted or going to headphones. |
| `evaluate.py` scores are very low | The mic was not the default input during recording, so the takes are silence or the built-in mic. |
| B prints nothing in step 14 | B started listening after A started playing, or B's default input is not the mic. |
| B decodes part of the message, with wrong characters or an early stop ("5el?" for "Yellow") | Windows audio enhancements are on for the mic. Turn them off (step 11a). |
| B prints mostly `?` | A and B have different `Settings.py` or `Transmitter.py` (pull on both), or the mic is much further away than in stage 2. |
