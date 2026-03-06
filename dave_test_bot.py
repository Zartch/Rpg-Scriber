import asyncio
import os
import discord
from dotenv import load_dotenv

load_dotenv()
token = os.environ.get("DISCORD_BOT_TOKEN")

# MONKEY PATCH START
import logging
log = logging.getLogger(__name__)

from discord.ext.voice_recv.opus import PacketDecoder
_original_decode_packet = PacketDecoder._decode_packet

def _patched_decode_packet(self, packet):
    assert self._decoder is not None

    if not hasattr(self, '_dave_fail_logged'):
        self._dave_fail_logged = False

    def _decrypt_dave(data):
        """Returns decrypted bytes on success, None on failure."""
        try:
            vc = self.sink.voice_client
            if hasattr(vc, '_connection') and getattr(vc._connection, 'dave_session', None) is not None:
                dave = vc._connection.dave_session
                user_id = None
                try:
                    import davey
                    user_id = self._cached_id
                    if user_id is None:
                        user_id = vc._get_id_from_ssrc(self.ssrc)
                        self._cached_id = user_id

                    if user_id is not None:
                        result = dave.decrypt(user_id, davey.MediaType.audio, data)
                        if self._dave_fail_logged:
                            print(f"DAVE recovered for ssrc {self.ssrc} (user {user_id})")
                            self._dave_fail_logged = False
                        return result
                except Exception as e:
                    if not self._dave_fail_logged:
                        print(f"DAVE decrypt failed (user {user_id}): {repr(e)}")
                        self._dave_fail_logged = True
            else:
                return data  # No DAVE session, passthrough
        except Exception as e:
            if not self._dave_fail_logged:
                print(f"DAVE wrapper error: {repr(e)}")
                self._dave_fail_logged = True
        return None  # Decryption failed

    if packet:
        decrypted = _decrypt_dave(packet.decrypted_data)
        if decrypted is not None:
            try:
                pcm = self._decoder.decode(decrypted, fec=False)
                return packet, pcm
            except Exception as e:
                print(f"Opus error (post-DAVE) len {len(decrypted)}: {e}")
        # Failed → generate silence
        pcm = self._decoder.decode(None, fec=False)
        return packet, pcm

    # No packet — silence
    pcm = self._decoder.decode(None, fec=False)
    return packet, pcm

PacketDecoder._decode_packet = _patched_decode_packet
# MONKEY PATCH END

class TestClient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())

    async def on_ready(self):
        print(f"Bot connected: {self.user}")
        guild = self.guilds[0]
        vc = guild.get_channel(703311007748980837)
        if not vc:
            vc = [c for c in guild.voice_channels][0]
        print(f"Connecting to {vc.name}...")
        try:
            from discord.ext import voice_recv

            received_count = 0
            def audio_callback(user, data):
                nonlocal received_count
                if user is not None:
                    received_count += 1
                    if received_count <= 5 or received_count % 50 == 0:
                        print(f"Audio #{received_count}: from {user} ({len(data.pcm)} bytes)")

            v_client = await vc.connect(cls=voice_recv.VoiceRecvClient)
            print("Connected successfully!")
            v_client.listen(voice_recv.BasicSink(audio_callback))

            await asyncio.sleep(15)
            print(f"\nTotal audio packets received: {received_count}")
            await v_client.disconnect()
            print("Disconnected safely.")
        except Exception as e:
            print(f"Error connecting: {repr(e)}")
        finally:
            await self.close()

client = TestClient()
client.run(token)
