import discord
from discord import app_commands
from discord.ext import commands
from discord import FFmpegPCMAudio
import json
import os
import asyncio
import yt_dlp

TOKEN = 'ВАШ_ТОКЕН_СЮДА'  # ЗАМЕНИТЕ

DATA_FILE = 'radio_urls.json'
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
}

# Создаём интенты, НЕ включая никакие привилегированные
intents = discord.Intents.default()
# intents.message_content = False  # даже не упоминаем
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree

# ---------- Остальной код (без изменений) ----------
def load_urls():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_urls(urls):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(urls, f, indent=4, ensure_ascii=False)

radio_urls = load_urls()

class GuildPlayer:
    def __init__(self, guild_id):
        self.guild_id = guild_id
        self.voice_client = None
        self.current_source = None
        self.current_url = None
        self.is_playing = False
        self.ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

    async def play_audio(self, source_url, source_type='radio'):
        if self.voice_client is None or not self.voice_client.is_connected():
            return False
        if self.voice_client.is_playing():
            self.voice_client.stop()
        actual_url = source_url
        if source_type == 'yt':
            try:
                info = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.ytdl.extract_info(source_url, download=False)
                )
                if 'entries' in info:
                    info = info['entries'][0]
                actual_url = info['url']
            except Exception as e:
                print(f"Ошибка получения аудио с YouTube: {e}")
                return False
        audio = FFmpegPCMAudio(actual_url, **FFMPEG_OPTIONS)
        self.voice_client.play(audio)
        self.current_source = source_type
        self.current_url = source_url
        self.is_playing = True
        return True

    async def stop(self):
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
        self.is_playing = False

players = {}

def get_player(guild_id):
    if guild_id not in players:
        players[guild_id] = GuildPlayer(guild_id)
    return players[guild_id]

@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    try:
        await tree.sync()
        print('✅ Слеш-команды синхронизированы!')
    except Exception as e:
        print(f'❌ Ошибка синхронизации: {e}')

@tree.command(name="в_войс", description="Подключить бота к голосовому каналу")
@app_commands.describe(канал="Выберите голосовой канал")
async def join_voice(interaction: discord.Interaction, канал: discord.VoiceChannel = None):
    if interaction.user.voice is None:
        await interaction.response.send_message("❌ Вы не в голосовом канале!", ephemeral=True)
        return
    target = канал or interaction.user.voice.channel
    if not target.permissions_for(interaction.guild.me).connect:
        await interaction.response.send_message("❌ Нет прав на подключение.", ephemeral=True)
        return
    voice = interaction.guild.voice_client
    player = get_player(interaction.guild.id)
    if voice and voice.is_connected():
        if voice.channel == target:
            await interaction.response.send_message("ℹ️ Бот уже здесь.", ephemeral=True)
            return
        await voice.move_to(target)
    else:
        voice = await target.connect()
        player.voice_client = voice
    url = radio_urls.get(str(interaction.guild.id))
    if url:
        success = await player.play_audio(url, 'radio')
        if success:
            await interaction.response.send_message(f"✅ Подключён к **{target.name}**, играет радио.")
        else:
            await interaction.response.send_message(f"✅ Подключён, но не удалось запустить радио.")
    else:
        await interaction.response.send_message(f"✅ Подключён к **{target.name}**. Используйте `/плей` или `/настройка_юрл`.")

@tree.command(name="из_войса", description="Отключить бота")
async def leave_voice(interaction: discord.Interaction):
    voice = interaction.guild.voice_client
    if voice and voice.is_connected():
        player = get_player(interaction.guild.id)
        if player.is_playing:
            await player.stop()
        await voice.disconnect()
        player.voice_client = None
        await interaction.response.send_message("✅ Отключён.")
    else:
        await interaction.response.send_message("❌ Бот не в канале.", ephemeral=True)

@tree.command(name="настройка_юрл", description="Сохранить URL радиостанции для сервера")
@app_commands.describe(url="Ссылка на аудиопоток (mp3, aac, etc.)")
async def set_radio(interaction: discord.Interaction, url: str):
    guild_id = str(interaction.guild.id)
    radio_urls[guild_id] = url
    save_urls(radio_urls)
    player = get_player(interaction.guild.id)
    if player.voice_client and player.voice_client.is_connected():
        success = await player.play_audio(url, 'radio')
        if success:
            await interaction.response.send_message("✅ URL обновлён, радио перезапущено.")
        else:
            await interaction.response.send_message("❌ Не удалось запустить поток. Проверьте URL.")
    else:
        await interaction.response.send_message("✅ URL сохранён. Подключите бота командой `/в_войс`.")

@tree.command(name="плей", description="Воспроизвести YouTube/Rutube (прямой эфир или видео)")
@app_commands.describe(запрос="Ссылка или поисковый запрос")
async def play(interaction: discord.Interaction, запрос: str):
    if interaction.user.voice is None:
        await interaction.response.send_message("❌ Вы не в голосовом канале!", ephemeral=True)
        return
    target = interaction.user.voice.channel
    voice = interaction.guild.voice_client
    player = get_player(interaction.guild.id)
    if not voice or not voice.is_connected():
        if not target.permissions_for(interaction.guild.me).connect:
            await interaction.response.send_message("❌ Нет прав на подключение.", ephemeral=True)
            return
        voice = await target.connect()
        player.voice_client = voice
    elif voice.channel != target:
        await voice.move_to(target)
    await interaction.response.send_message(f"🔍 Ищу `{запрос}`...")
    try:
        ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: ytdl.extract_info(запрос, download=False))
        if 'entries' in info:
            info = info['entries'][0]
        audio_url = info['url']
        title = info.get('title', 'неизвестный трек')
        success = await player.play_audio(audio_url, 'yt')
        if success:
            await interaction.edit_original_response(content=f"🎶 Сейчас играет: **{title}**")
        else:
            await interaction.edit_original_response(content="❌ Не удалось воспроизвести.")
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Ошибка: {str(e)}")

@tree.command(name="стоп", description="Остановить воспроизведение")
async def stop(interaction: discord.Interaction):
    player = get_player(interaction.guild.id)
    if player.voice_client and player.voice_client.is_playing():
        await player.stop()
        await interaction.response.send_message("⏹ Воспроизведение остановлено.")
    else:
        await interaction.response.send_message("ℹ️ Сейчас ничего не играет.", ephemeral=True)

if __name__ == "__main__":
    bot.run(TOKEN)
