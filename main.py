import os
import time
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands, tasks

# ───────────────────────── НАСТРОЙКИ ─────────────────────────
TOKEN = os.getenv("DISCORD_TOKEN")          # токен бота (переменная окружения)
SUPER_ADMIN_ID = 1012623951719051284        # тот, кто может секретные команды
MAX_ROLES = 5                               # лимит ролей на одного человека
SECRET_PREFIX = "!"                         # префикс секретных команд

# Цвета, из которых можно выбирать
COLORS = {
    "🔴 Красный": 0xE74C3C,
    "🟠 Оранжевый": 0xE67E22,
    "🟡 Жёлтый": 0xF1C40F,
    "🟢 Зелёный": 0x2ECC71,
    "🔵 Синий": 0x3498DB,
    "🟣 Фиолетовый": 0x9B59B6,
    "🩷 Розовый": 0xFF69B4,
    "🩵 Бирюзовый": 0x1ABC9C,
    "⚪ Белый": 0xFFFFFF,
    "⚫ Тёмно-серый": 0x2C2F33,
}
COLOR_CHOICES = [app_commands.Choice(name=n, value=v) for n, v in COLORS.items()]

# ───────────────────────── БАЗА ДАННЫХ ─────────────────────────
conn = sqlite3.connect("roles.db", check_same_thread=False)
conn.execute(
    """CREATE TABLE IF NOT EXISTS roles (
        role_id    INTEGER PRIMARY KEY,
        guild_id   INTEGER NOT NULL,
        owner_id   INTEGER NOT NULL,
        expires_at REAL
    )"""
)
conn.execute(
    """CREATE TABLE IF NOT EXISTS settings (
        guild_id         INTEGER PRIMARY KEY,
        default_ttl_days REAL
    )"""
)
conn.commit()


def get_row(role_id: int):
    return conn.execute(
        "SELECT role_id, guild_id, owner_id, expires_at FROM roles WHERE role_id=?",
        (role_id,),
    ).fetchone()


def count_owned(guild_id: int, owner_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM roles WHERE guild_id=? AND owner_id=?",
        (guild_id, owner_id),
    ).fetchone()[0]


def get_default_ttl(guild_id: int):
    row = conn.execute(
        "SELECT default_ttl_days FROM settings WHERE guild_id=?", (guild_id,)
    ).fetchone()
    return row[0] if row and row[0] else None


def delete_row(role_id: int):
    conn.execute("DELETE FROM roles WHERE role_id=?", (role_id,))
    conn.commit()


# ───────────────────────── БОТ ─────────────────────────
intents = discord.Intents.default()
intents.message_content = True  # нужен для секретных текстовых команд
bot = commands.Bot(command_prefix=SECRET_PREFIX, intents=intents, help_command=None)


@bot.event
async def setup_hook():
    await bot.tree.sync()
    expire_loop.start()


@bot.event
async def on_ready():
    print(f"Бот запущен как {bot.user} ({bot.user.id})")


@bot.event
async def on_guild_role_delete(role: discord.Role):
    # если роль удалили вручную — чистим базу
    if get_row(role.id):
        delete_row(role.id)


# ───────────────────────── ПРОВЕРКА ВЛАДЕЛЬЦА ─────────────────────────
async def check_owner(interaction: discord.Interaction, role: discord.Role) -> bool:
    row = get_row(role.id)
    if not row:
        await interaction.response.send_message(
            "❌ Эта роль не создана через бота.", ephemeral=True
        )
        return False
    if row[2] != interaction.user.id:
        await interaction.response.send_message(
            "❌ Это не твоя роль — управлять ей может только её создатель.",
            ephemeral=True,
        )
        return False
    return True


def can_manage(guild: discord.Guild, role: discord.Role) -> bool:
    return role < guild.me.top_role and not role.managed


# ───────────────────────── СЛЭШ-КОМАНДЫ ─────────────────────────
@bot.tree.command(name="role_create", description="Создать свою роль")
@app_commands.describe(name="Название роли", color="Цвет роли")
@app_commands.choices(color=COLOR_CHOICES)
@app_commands.guild_only()
async def role_create(
    interaction: discord.Interaction,
    name: app_commands.Range[str, 1, 100],
    color: app_commands.Choice[int],
):
    guild = interaction.guild
    if count_owned(guild.id, interaction.user.id) >= MAX_ROLES:
        return await interaction.response.send_message(
            f"❌ Лимит: не больше {MAX_ROLES} ролей на человека. "
            "Удали одну через `/role_delete`.",
            ephemeral=True,
        )

    await interaction.response.defer(ephemeral=True)
    try:
        role = await guild.create_role(
            name=name,
            colour=discord.Colour(color.value),
            permissions=discord.Permissions.none(),  # роль чисто косметическая
            mentionable=False,
            hoist=False,
            reason=f"Создал {interaction.user} ({interaction.user.id})",
        )
    except discord.Forbidden:
        return await interaction.followup.send(
            "❌ У бота нет права «Управление ролями».", ephemeral=True
        )
    except discord.HTTPException as e:
        return await interaction.followup.send(f"❌ Ошибка Discord: {e}", ephemeral=True)

    ttl = get_default_ttl(guild.id)
    expires = time.time() + ttl * 86400 if ttl else None
    conn.execute(
        "INSERT INTO roles (role_id, guild_id, owner_id, expires_at) VALUES (?,?,?,?)",
        (role.id, guild.id, interaction.user.id, expires),
    )
    conn.commit()

    msg = f"✅ Роль {role.mention} создана. Выдать: `/role_give`."
    if expires:
        msg += f"\n⏳ Удалится <t:{int(expires)}:R>."
    await interaction.followup.send(msg, ephemeral=True)


@bot.tree.command(name="role_give", description="Выдать свою роль участнику")
@app_commands.describe(role="Твоя роль", member="Кому выдать")
@app_commands.guild_only()
async def role_give(
    interaction: discord.Interaction, role: discord.Role, member: discord.Member
):
    if not await check_owner(interaction, role):
        return
    if not can_manage(interaction.guild, role):
        return await interaction.response.send_message(
            "❌ Бот не может управлять этой ролью (она выше роли бота).", ephemeral=True
        )
    try:
        await member.add_roles(role, reason=f"Выдал {interaction.user}")
    except discord.HTTPException as e:
        return await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)
    await interaction.response.send_message(
        f"✅ {member.mention} получил роль {role.mention}.", ephemeral=True
    )


@bot.tree.command(name="role_take", description="Забрать свою роль у участника")
@app_commands.describe(role="Твоя роль", member="У кого забрать")
@app_commands.guild_only()
async def role_take(
    interaction: discord.Interaction, role: discord.Role, member: discord.Member
):
    if not await check_owner(interaction, role):
        return
    try:
        await member.remove_roles(role, reason=f"Забрал {interaction.user}")
    except discord.HTTPException as e:
        return await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)
    await interaction.response.send_message(
        f"✅ Роль {role.mention} снята с {member.mention}.", ephemeral=True
    )


@bot.tree.command(name="role_edit", description="Изменить название/цвет своей роли")
@app_commands.describe(role="Твоя роль", name="Новое название", color="Новый цвет")
@app_commands.choices(color=COLOR_CHOICES)
@app_commands.guild_only()
async def role_edit(
    interaction: discord.Interaction,
    role: discord.Role,
    name: app_commands.Range[str, 1, 100] | None = None,
    color: app_commands.Choice[int] | None = None,
):
    if not await check_owner(interaction, role):
        return
    if name is None and color is None:
        return await interaction.response.send_message(
            "❌ Укажи новое название и/или цвет.", ephemeral=True
        )
    try:
        await role.edit(
            name=name if name else role.name,
            colour=discord.Colour(color.value) if color else role.colour,
            reason=f"Изменил {interaction.user}",
        )
    except discord.HTTPException as e:
        return await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)
    await interaction.response.send_message(
        f"✅ Роль обновлена: {role.mention}", ephemeral=True
    )


@bot.tree.command(name="role_delete", description="Удалить свою роль")
@app_commands.describe(role="Твоя роль")
@app_commands.guild_only()
async def role_delete(interaction: discord.Interaction, role: discord.Role):
    if not await check_owner(interaction, role):
        return
    name = role.name
    try:
        await role.delete(reason=f"Удалил {interaction.user}")
    except discord.HTTPException as e:
        return await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)
    delete_row(role.id)
    await interaction.response.send_message(f"🗑️ Роль **{name}** удалена.", ephemeral=True)


@bot.tree.command(name="role_list", description="Показать мои роли")
@app_commands.guild_only()
async def role_list(interaction: discord.Interaction):
    rows = conn.execute(
        "SELECT role_id, expires_at FROM roles WHERE guild_id=? AND owner_id=?",
        (interaction.guild.id, interaction.user.id),
    ).fetchall()
    if not rows:
        return await interaction.response.send_message(
            "У тебя пока нет ролей. Создай: `/role_create`", ephemeral=True
        )
    lines = []
    for role_id, exp in rows:
        r = interaction.guild.get_role(role_id)
        if not r:
            continue
        line = f"• {r.mention}"
        if exp:
            line += f" — удалится <t:{int(exp)}:R>"
        lines.append(line)
    await interaction.response.send_message(
        f"**Твои роли ({len(lines)}/{MAX_ROLES}):**\n" + "\n".join(lines), ephemeral=True
    )


# ───────────────────────── СЕКРЕТНЫЕ КОМАНДЫ ─────────────────────────
# Текстовые (не слэш), поэтому их нет в списке команд. Работают только
# для SUPER_ADMIN_ID, остальным бот не отвечает вообще.
def super_admin_only():
    async def predicate(ctx: commands.Context):
        return ctx.guild is not None and ctx.author.id == SUPER_ADMIN_ID

    return commands.check(predicate)


async def hide(ctx: commands.Context):
    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass


@bot.command(name="sa_give")
@super_admin_only()
async def sa_give(ctx: commands.Context, member: discord.Member, *roles: discord.Role):
    """!sa_give @участник @роль1 @роль2 ...   |   !sa_give @участник all"""
    await hide(ctx)
    guild = ctx.guild
    to_give = []
    if not roles and ctx.message.content.lower().rstrip().endswith(" all"):
        to_give = [
            r for r in guild.roles if not r.is_default() and can_manage(guild, r)
        ]
    else:
        to_give = [r for r in roles if can_manage(guild, r)]
    if not to_give:
        return await ctx.send("Нечего выдавать (роли выше бота или не указаны).", delete_after=8)
    try:
        await member.add_roles(*to_give, reason="sa_give")
    except discord.HTTPException as e:
        return await ctx.send(f"Ошибка: {e}", delete_after=8)
    await ctx.send(f"✅ Выдано ролей: {len(to_give)} → {member.mention}", delete_after=8)


@bot.command(name="sa_take")
@super_admin_only()
async def sa_take(ctx: commands.Context, member: discord.Member, *roles: discord.Role):
    """!sa_take @участник @роль1 @роль2 ..."""
    await hide(ctx)
    to_take = [r for r in roles if can_manage(ctx.guild, r)]
    if not to_take:
        return await ctx.send("Нечего снимать.", delete_after=8)
    try:
        await member.remove_roles(*to_take, reason="sa_take")
    except discord.HTTPException as e:
        return await ctx.send(f"Ошибка: {e}", delete_after=8)
    await ctx.send(f"✅ Снято ролей: {len(to_take)} у {member.mention}", delete_after=8)


@bot.command(name="sa_expire")
@super_admin_only()
async def sa_expire(ctx: commands.Context, days: float, role: discord.Role | None = None):
    """
    !sa_expire 5            — все роли, созданные ботом, удалятся через 5 дней
                              (и новые роли тоже будут получать этот срок)
    !sa_expire 5 @роль      — срок только для одной роли
    !sa_expire 0            — убрать срок (у всех)
    !sa_expire 0 @роль      — убрать срок у одной роли
    """
    await hide(ctx)
    guild = ctx.guild
    expires = time.time() + days * 86400 if days > 0 else None

    if role is not None:
        if not get_row(role.id):
            return await ctx.send("Эта роль создана не через бота.", delete_after=8)
        conn.execute("UPDATE roles SET expires_at=? WHERE role_id=?", (expires, role.id))
        conn.commit()
        text = f"⏳ {role.name}: " + (f"удалится через {days:g} дн." if expires else "срок снят")
        return await ctx.send(text, delete_after=8)

    conn.execute("UPDATE roles SET expires_at=? WHERE guild_id=?", (expires, guild.id))
    conn.execute(
        "INSERT INTO settings (guild_id, default_ttl_days) VALUES (?, ?) "
        "ON CONFLICT(guild_id) DO UPDATE SET default_ttl_days=excluded.default_ttl_days",
        (guild.id, days if days > 0 else None),
    )
    conn.commit()
    text = (
        f"⏳ Все роли бота удалятся через {days:g} дн. (новые — тоже)."
        if expires
        else "⏳ Срок жизни ролей отключён."
    )
    await ctx.send(text, delete_after=8)


@bot.event
async def on_command_error(ctx: commands.Context, error):
    # чужим людям — полная тишина; секретные команды не должны «светиться»
    if isinstance(error, (commands.CheckFailure, commands.CommandNotFound)):
        return
    if ctx.author.id == SUPER_ADMIN_ID:
        await ctx.send(f"Ошибка: {error}", delete_after=10)


# ───────────────────────── АВТОУДАЛЕНИЕ ПО СРОКУ ─────────────────────────
@tasks.loop(minutes=1)
async def expire_loop():
    now = time.time()
    rows = conn.execute(
        "SELECT role_id, guild_id FROM roles WHERE expires_at IS NOT NULL AND expires_at<=?",
        (now,),
    ).fetchall()
    for role_id, guild_id in rows:
        guild = bot.get_guild(guild_id)
        role = guild.get_role(role_id) if guild else None
        if role:
            try:
                await role.delete(reason="Истёк срок жизни роли")
            except discord.HTTPException:
                continue  # попробуем в следующую минуту
        delete_row(role_id)


@expire_loop.before_loop
async def before_expire():
    await bot.wait_until_ready()


# ───────────────────────── ОШИБКИ СЛЭШ-КОМАНД ─────────────────────────
@bot.tree.error
async def on_app_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    msg = f"❌ Ошибка: {error}"
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Задай переменную окружения DISCORD_TOKEN")
    bot.run(TOKEN)
