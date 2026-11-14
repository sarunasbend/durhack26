class Tokenizer(object):
    def __init__(self, message):
        self.message = message
        self.tokens = self.tokenize(message)
    def tokenize(self, message):
        pass
        

class Composer(object):
    def __init__(self):
        self.receiver = None
        self.transmitter = None
    def encode_message(self, message):
        print(message)
        self.tokenizer = Tokenizer(message)
        print(self.tokenizer.tokens)
    def decode_message(self, song):
        print(song)
