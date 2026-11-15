# To do

Where things stand: the receiver has one model per instrument, and each model reads every key.
The only one trained so far is Electric Piano 1 (program 4, `training/models/instrument_004.pt`).
On 8 held-out recordings in 5 keys it gets 956 of 960 notes right (4 character errors in 320).
All of that was measured on one MacBook's speaker into its own microphone. Nothing here has
been run live between two devices.

## Must do before the demo

Step-by-step instructions for the two laptops are in `TWO_LAPTOPS.md`.

- [ ] **Commit the work.** Nothing from this session is committed yet (branch `Receiver`).
- [ ] **Live test between the two real devices.** Sender runs `python main.py`, receiver runs
      `python Receiver.py --message`. Expect it to be worse than the recorded tests at first.
- [ ] **Record takes on the real sender/receiver pair and retrain.** A different speaker, microphone
      or system synth can sound different from the training data.
      `python training/collect.py --noise 45 --takes 24`, then `python training/train.py`. About 35 minutes.
- [ ] **Decide the playback volume.** `SenderGUI._transmit` plays at 10% volume; every training take
      was at full volume. Either raise it or record takes at the demo volume.
- [ ] **Show decoded text in `ReceiverGUI`.** Its background thread should loop over
      `Receiver.listen_message()` and append each piece it yields. At the moment it shows nothing.

## Other keys and instruments

- [x] **One model for every key.** Done: 24 outputs (C4 to B5), trained on 42 takes across all 12 keys.
- [ ] **The receiver has to know the key and scale.** It reads `Settings.py`, so sender and receiver
      must run with the same file. Decide how the key is chosen for the demo.
- [ ] **Other scales are only spot-checked.** Training was major pentatonic only. One message each:
      D major decoded perfectly (90 of 90 notes), A minor got 85 of 90. Record takes in the scales
      you plan to use (`collect.py` needs a `--scale` option first) and retrain.
- [ ] **Train the other instruments you want.** Change the program in `Transmitter.write`, then run
      `collect.py`, `train.py` and `evaluate.py`. About 45 minutes per instrument for the same amount of data.
- [ ] **Choose the model by ear at runtime.** At the moment the receiver picks the model from the program
      number in its own copy of `Transmitter.py`. Suggested approach: run every instrument's model on
      the first few seconds and keep the one that is most confident on the rhythm.

## Should do

- [ ] **`Decoder.decode` crashes on a group of notes that is not a character** (`KeyError`).
      `Receiver.listen_message()` does not use it and shows `?` instead, but `main.py`'s path does.
- [ ] **`SenderGUI.run` replays the message forever**, and `_transmit` calls `pygame.quit()` on window
      close and then keeps using pygame.
- [ ] **Messages of one character are not detected.** The receiver needs two characters to be sure
      a message has started.
- [ ] **Chords are not supported.** The model was trained on single notes plus the drone.
- [ ] **Error correction.** One misheard note is one wrong character. A check note per word would catch it.

## Clean-up that needs a decision

- [ ] **`M_Receiver.py`**: nothing imports it. Delete it if the model-based receiver is the one being used.
- [ ] **`training/archive_chiff_c_minor/`** (34 MB, not in git): recordings and model for the old chiff-lead,
      C minor settings. Delete if those settings are never coming back.
- [ ] **`training/archive_f_sharp_only/`** (1.4 MB, not in git): the earlier F#-only model, replaced by the
      any-key one. Safe to delete.
- [ ] **Old root-note functions in `Receiver.py`** (`find_root`, `listen`, `roots_from_midi`) and their tests
      (`test_receiver.py`, `generate_test_midi.py`): not used by message decoding. Keep or remove.
- [ ] **`README.md`** is one line.
