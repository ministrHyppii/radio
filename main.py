import discord
from discord import app_commands
from discord.ext import commands
from discord import FFmpegPCMAudio
import json
import os
from config import TOKEN  # Импортируем токен из отдельного файла

# ========== НАСТРОЙКИ ==========
DATA_FILE = 'radio_urls.json'  # Файл для хранения URL радиостанций по серверам
# ================================

# Включаем все необходимые интенты
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

# Создаём экземпляр бота (префикс ! не используется, но обязателен)
bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree

# ---------- Работа с файлом URL ----------
def load_urls():
    """Загружает сохранённые URL из JSON-файла."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_urls(urls):
    """Сохраняет URL в JSON-файл."""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(urls, f, indent=4, ensure_ascii=False)

radio_urls = load_urls()
# -----------------------------------------

# ---------- Событие готовности ----------
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    try:
        # Синхронизируем слеш-команды (глобально)
        await tree.sync()
        print('✅ Слеш-команды синхронизированы!')
    except Exception as e:
        print(f'❌ Ошибка синхронизации: {e}')

# ---------- КОМАНДА: /в войс ----------
@tree.command(name="в_войс", description="Подключить бота к голосовому каналу")
@app_commands.describe(канал="Выберите голосовой канал (можно ввести ID или выбрать из списка)")
async def join_voice(interaction: discord.Interaction, канал: discord.VoiceChannel):
    """
    Подключает бота к указанному голосовому каналу и начинает воспроизведение радио,
    если URL уже настроен.
    """
    # Проверяем, что пользователь сам в голосовом канале (необязательно, но логично)
    if interaction.user.voice is None:
        await interaction.response.send_message("❌ Вы не находитесь в голосовом канале! Сначала зайдите в голос.", ephemeral=True)
        return

    # Проверяем права бота на подключение
    if not канал.permissions_for(interaction.guild.me).connect:
        await interaction.response.send_message("❌ У бота нет права на подключение к этому каналу.", ephemeral=True)
        return

    # Получаем текущее голосовое соединение
    voice_client = interaction.guild.voice_client

    # Если бот уже в другом канале, перемещаем
    if voice_client and voice_client.is_connected():
        if voice_client.channel == канал:
            await interaction.response.send_message("ℹ️ Бот уже в этом канале.", ephemeral=True)
            return
        else:
            await voice_client.move_to(канал)
    else:
        # Подключаемся
        voice_client = await канал.connect()

    # Проверяем, есть ли сохранённый URL для этого сервера
    url = radio_urls.get(str(interaction.guild.id))
    if url:
        # Останавливаем текущее воспроизведение, если есть
        if voice_client.is_playing():
            voice_client.stop()
        # Создаём аудиоисточник с переподключением
        audio = FFmpegPCMAudio(url, before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5")
        voice_client.play(audio)
        await interaction.response.send_message(f"✅ Подключён к **{канал.name}** и начато вещание радио.")
    else:
        await interaction.response.send_message(
            f"✅ Подключён к **{канал.name}**, но URL радио не настроен. "
            "Используйте `/настройка_юрл` для установки ссылки."
        )

# ---------- КОМАНДА: /из войса ----------
@tree.command(name="из_войса", description="Отключить бота от голосового канала")
async def leave_voice(interaction: discord.Interaction):
    """Отключает бота от текущего голосового канала."""
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        await interaction.response.send_message("✅ Бот отключён от голосового канала.")
    else:
        await interaction.response.send_message("❌ Бот не находится в голосовом канале.", ephemeral=True)

# ---------- КОМАНДА: /настройка_юрл ----------
@tree.command(name="настройка_юрл", description="Установить URL радиостанции для этого сервера")
@app_commands.describe(url="Прямая ссылка на аудиопоток (например, http://radio.example.com:8000/stream)")
async def set_radio_url(interaction: discord.Interaction, url: str):
    """Сохраняет URL радиостанции для данного сервера."""
    guild_id = str(interaction.guild.id)
    radio_urls[guild_id] = url
    save_urls(radio_urls)

    # Если бот уже в голосовом канале, обновляем воспроизведение
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_connected():
        if voice_client.is_playing():
            voice_client.stop()
        audio = FFmpegPCMAudio(url, before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5")
        voice_client.play(audio)
        await interaction.response.send_message(f"✅ URL обновлён и воспроизведение перезапущено с новым потоком.")
    else:
        await interaction.response.send_message(f"✅ URL сохранён. Используйте `/в войс` для подключения и начала вещания.")

# ---------- ЗАПУСК ----------
if __name__ == "__main__":
    bot.run(TOKEN)