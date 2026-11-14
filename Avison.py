class Tokenizer(object):
    def __init__(self, message):
        self.message = message
        self.tokens = self.tokenize(message)
        self.stream = message.split()
    def tokenize(self, message):
        tokens = []
        for word in message.split():
            current_word = ""
            for char in word:
                if char in [".", ",", "!", "?", ";", ":", "'", '"', "(", ")", "[", "]", "{", "}"]:
                    if current_word:
                        tokens.append(current_word)
                        current_word = ""
                    tokens.append(char)
                else:
                    current_word += char
            if current_word:
                tokens.append(current_word)
        return tokens

class Scale(object):
    def __init__(self, key, scale_type):
        self.key = key.upper()
        self.scale_type = scale_type
        self.chromatic_scale = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        self.intervals = {
            "major": [2, 2, 1, 2, 2, 2, 1],
            "minor": [2, 1, 2, 2, 1, 2, 2],
            "dorian": [2, 1, 2, 2, 2, 1, 2],
            "phrygian": [1, 2, 2, 2, 1, 2, 2],
            "lydian": [2, 2, 2, 1, 2, 2, 1],
            "mixolydian": [2, 2, 1, 2, 2, 1, 2],
            "locrian": [1, 2, 2, 1, 2, 2, 2]
        }
        self.scale = self.generate_scale()
    def generate_scale(self):
        if self.key not in self.chromatic_scale:
            raise ValueError(f"Invalid key: {self.key}")
        if self.scale_type not in self.intervals:
            raise ValueError(f"Invalid scale type: {self.scale_type}")
        scale = []
        start_index = self.chromatic_scale.index(self.key)
        intervals = self.intervals[self.scale_type]

        for interval in intervals:
            scale.append(self.chromatic_scale[start_index])
            start_index = (start_index + interval) % len(self.chromatic_scale)

        return scale


class Key(object):
    def __init__(self, key):
        self.key = key

class Composer(object):
    def __init__(self, key, scale_type):
        self.receiver = None
        self.transmitter = None
        self.scale = Scale(key=key, scale_type=scale_type)
    def encode_message(self, message):
        print(message)
        self.tokenizer = Tokenizer(message)
        print(self.tokenizer.tokens)
    def decode_message(self, song):
        print(song)
