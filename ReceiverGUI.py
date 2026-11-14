import threading
import pygame

class ReceiverGUI(object):
    def __init__(self, composer):
        self.composer = composer
        decoder = composer.stream_decode()
        self.decoder = decoder

        pygame.init()
        self.screen = pygame.display.set_mode((800, 500))
        pygame.display.set_caption("Receiver")
        self.heading_font = pygame.font.Font(None, 48)
        self.text_font = pygame.font.Font(None, 30)
        self._decoded = ""
        self._decoded_lock = threading.Lock()
        self._running = True

        self._listener_thread = threading.Thread(
            target=self._listen, daemon=True
        )
        self._listener_thread.start()

    def _listen(self):
        """Run decoding away from the pygame/UI thread."""
        self.decoder.begin_decode()
        while self._running:
            decoded = self.decoder.stream_decoded
            if decoded is not None:
                with self._decoded_lock:
                    self._decoded = str(decoded)
            threading.Event().wait(0.05)

    def get_decoded(self):
        """Return the latest decoded text for display or other callers."""
        with self._decoded_lock:
            return self._decoded

    def run(self):
        """Render the receiver window until it is closed."""
        clock = pygame.time.Clock()
        while self._running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._running = False

            self.screen.fill((30, 30, 30))
            heading = self.heading_font.render("receiver", True, (255, 255, 255))
            self.screen.blit(heading, (30, 20))

            textbox = pygame.Rect(30, 90, 740, 370)
            pygame.draw.rect(self.screen, (245, 245, 245), textbox)
            pygame.draw.rect(self.screen, (120, 120, 120), textbox, 2)
            text = self.text_font.render(self.get_decoded(), True, (20, 20, 20))
            self.screen.blit(text, (textbox.x + 12, textbox.y + 12))

            pygame.display.flip()
            clock.tick(30)

        pygame.quit()

