# Tests the trained model on the held-out takes (every 5th one, never trained on):
# recording -> notes -> decoded text, compared with the text that was actually sent.
#
#   python training/evaluate.py            # held-out takes
#   python training/evaluate.py --all      # every take, including ones it trained on

import sys

import common

_composers = {}


def composer_for(take):
    """The Composer for the key and scale a take was played in."""
    key = (take['key'], take['scale'])
    if key not in _composers:
        _composers[key] = common.make_composer(*key)
    return _composers[key]


def score(model, takes, verbose=True):
    """Decode each take and compare with what was sent. Returns the totals."""
    total = {'notes': 0, 'notes_right': 0, 'chars': 0, 'char_errors': 0}
    for take in takes:
        heard = common.decode_recording(model, composer_for(take), take['audio'], take['drone'])
        notes_right = sum(a == b for a, b in zip(heard.notes, take['notes']))
        char_errors = common.edit_distance(heard.text, take['text'])
        if verbose:
            print('%s  key %-2s  notes %d/%d right, character errors %d/%d'
                  % (take['name'], take['key'], notes_right, len(take['notes']), char_errors, len(take['text'])))
            if char_errors:
                print('    sent:    %r\n    decoded: %r' % (take['text'], heard.text))
        total['notes'] += len(take['notes'])
        total['notes_right'] += notes_right
        total['chars'] += len(take['text'])
        total['char_errors'] += char_errors
    return total


def summary(total):
    return ('notes right %.1f%% (%d of %d), character error rate %.1f%% (%d of %d)'
            % (100.0 * total['notes_right'] / max(1, total['notes']), total['notes_right'], total['notes'],
               100.0 * total['char_errors'] / max(1, total['chars']), total['char_errors'], total['chars']))


if __name__ == '__main__':
    program = common.current_program()
    takes = [t for t in common.load_takes(program) if t['notes'] and ('--all' in sys.argv or common.is_validation(t))]
    print('instrument %d: %d takes' % (program, len(takes)))
    print(summary(score(common.load_model(program), takes)))
