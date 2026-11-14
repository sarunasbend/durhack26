import Avison as a

if __name__ == "__main__":
    message = """
To the red country and part of the gray country of Oklahoma, the last rains came gently, and they did not cut the scarred earth. The plows crossed and recrossed the rivulet marks. The last rains lifted the corn quickly and scattered weed colonies and grass along the sides of the roads so that the gray country and the dark red country began to disappear under a green cover. In the last part of May the sky grew pale and the clouds that had hung in high puffs for so long in the spring were dissipated. The sun flared down on the growing corn day after day until a line of brown spread along the edge of each green bayonet. The clouds appeared, and went away, and in a while they did not try any more. The weeds grew darker green to protect themselves, and they did not spread any more. The surface of the earth crusted, a thin hard crust, and as the sky became pale, so the earth became pale, pink in the red country and white in the gray country.
    """

    composer = a.Composer()
    encoded = composer.encode_message(message)
    decoded = composer.decode_message(encoded)