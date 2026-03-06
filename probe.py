import davey

try:
    d = davey.DaveSession(1, 1, 1)
except Exception as e:
    print(f"session init error: {e}")
    exit(1)

print("Testing 1 arg...")
try:
    d.decrypt(davey.MediaType.audio)
except Exception as e:
    print(f"1 arg error: {repr(e)}")

print("Testing proper args...")
try:
    d = davey.DaveSession(1, 1, 1)
    res = d.decrypt(123456789, davey.MediaType.audio, b'0000000000000000')
    print("Success! Res len:", len(res))
except Exception as e:
    print(f"proper args error: {repr(e)}")

