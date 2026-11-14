import Avison as a

if __name__ == "__main__":
    composer = a.Composer()
    encoded = composer.encode_message("Hello, World!")
    decoded = composer.decode_message(encoded)