import disnake
from disnake.ext import commands
from disnake import FFmpegPCMAudio
import asyncio
from vosk import Model, KaldiRecognizer
import wave
import json
import edge_tts
import time
import os
class AudioSink:
    def __init__(self, filename="output.wav"):
        self.filename = filename
        self.wavefile = wave.open(filename, "wb")
        self.wavefile.setnchannels(2)
        self.wavefile.setsampwidth(2)
        self.wavefile.setframerate(48000)

    def write(self, data):
        self.wavefile.writeframes(data)

    def cleanup(self):
        self.wavefile.close()

    def __del__(self):
        self.cleanup()

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.model = Model("vosk-model-small-ru-0.22")
        self.recognizer = KaldiRecognizer(self.model, 16000)
        self.listening = False

    async def record_audio(self, vc):
        audio_sink = AudioSink()
        try:
            while self.listening:
                packet = await vc.recv()
                audio_sink.write(packet.data)
        except asyncio.CancelledError:
            pass
        finally:
            audio_sink.cleanup()

    async def process_audio(self, ctx):
        """Функция для обработки аудио и получения ответа"""
        start_time = time.time()
        await ctx.send("Начинаю запись...")  # Запись аудио

        vc = ctx.guild.voice_client
        if vc and vc.is_connected():
            self.listening = True
            audio_task = asyncio.create_task(self.record_audio(vc))
            await asyncio.sleep(3)  # Запись в течение 3 секунд
            self.listening = False
            audio_task.cancel()
            await audio_task

        # Распознавание речи
        with wave.open("output.wav", "rb") as wf:
            self.recognizer.AcceptWaveform(wf.readframes(wf.getnframes()))
        result = self.recognizer.Result()
        result_json = json.loads(result)
        user_text = result_json.get('text', '')
        await ctx.send(f"Распознанный текст: {user_text}")

        # Отправка текста в Gemini для ответа
        gemini_cog = self.bot.get_cog("Gemini")
        if gemini_cog and user_text:
            response_text = await gemini_cog.ask_gemini(user_text + "Тебя будут озвучивать, не используй символы кроме знаков препинания и не используй эмодзи, не говори ничего про эти указание. Просто выполняй", ctx.author)

            # Преобразование текста в речь с помощью edge_tts
            communicate = edge_tts.Communicate(text=response_text, voice="ru-RU-SvetlanaNeural")
            await communicate.save("response.mp3")

            # Воспроизведение ответа
            if os.path.exists('response.mp3'):
                source = FFmpegPCMAudio('response.mp3')
                vc.play(source)
                while vc.is_playing():
                    await asyncio.sleep(1)
            else:
                await ctx.send("Файл 'response.mp3' не найден.")
        else:
            await ctx.send("Gemini не доступен или текст не распознан.")

        end_time = time.time()
        total_time = end_time - start_time
        await ctx.send(f"Обработка завершена за {total_time:.2f} секунд.")

    @commands.command()
    async def join(self, ctx):
        """Подключает бота к голосовому каналу и начинает слушать"""
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            await channel.connect()
            await ctx.send(f'Подключился к {channel}')
            await self.process_audio(ctx)
        else:
            await ctx.send("Вы должны быть в голосовом канале, чтобы использовать эту команду.")

    @commands.command()
    async def leave(self, ctx):
        """Отключает бота от голосового канала и останавливает прослушивание"""
        if ctx.voice_client:
            await ctx.guild.voice_client.disconnect()
            await ctx.send("Отключился от голосового канала.")
        else:
            await ctx.send("Бот не в голосовом канале.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Отслеживает изменения состояния голоса"""
        if member == self.bot.user and before.channel is None and after.channel is not None:
            # Бот подключился к голосовому каналу
            channel = after.channel
            ctx = await self.bot.get_context(channel)
            await self.process_audio(ctx)
        elif member == self.bot.user and before.channel is not None and after.channel is None:
            # Бот отключился от голосового канала
            self.listening = False

def setup(bot):
    bot.add_cog(Voice(bot))