class Characters(object):
    def __init__(self):
        self.characters = []

    def load_character_set(self,c_set="reduced"):
        if c_set == "reduced":
            self.characters = list(
                "abcdefghijklmnopqrstuvwxyz"
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "0123456789"
                " .,!?;:'\"()-\n"
            )