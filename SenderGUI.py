import pygame
from Transmitter import Transmitter
from Avison import Composer

class SenderGUI:
    def __init__(self, transmitter : Transmitter, encoder : Composer):
        self.transmitter = transmitter
        self.encoder = encoder
        self.path = "out.mid"
        self.screen = pygame.display.set_mode((800, 500))

        pygame.init()
        pygame.display.set_caption("Sender")

        self.heading_font = pygame.font.Font(None, 48)
        self.text_font = pygame.font.Font(None, 30)

        self._running = True

    # generates midi file
    def _generate_midi(self, notes, metadata):
        self.transmitter.config()
        self.transmitter.write(notes, metadata, 0)
        self.transmitter.save("out.mid")        

    def _configure(self):
        pass

    #  plays sound of midi file
    def _transmit(self):
        try:
            pygame.mixer.music.load(self.path)
            pygame.mixer.music.play()
            pygame.mixer.music.set_volume(0.1)

            while pygame.mixer.music.get_busy():
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        pygame.quit()

        except Exception as e:
            print(f"MIDI ERROR: {e}")

    def run(self):

        message = "Hello earth, this is your first contact with an alien."
        encoded, metadata = self.encoder.encode_message(message)

        self._generate_midi(encoded, metadata)

        while self._running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._running = False

            self._transmit()

        pygame.quit()


