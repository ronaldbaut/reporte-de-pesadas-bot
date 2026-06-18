import discord
from discord.ext import commands
import os
import traceback

print(">>> Iniciando reporte-de-pesadas-bot...")

# ================== CONFIGURACIÓN ==================
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise RuntimeError("❌ ERROR: Falta la variable de entorno TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

reports = {}

# ================== PREGUNTAS ==================
PREGUNTAS = [
    "¿Con cuánta leche comenzó el día?",
    "¿Con cuánta leche terminó el día?",
    "¿Con cuánto azúcar comenzó el día?",
    "¿Con cuánto azúcar terminó el día?",
    "¿Con cuánto suero comenzó el día?",
    "¿Con cuánto suero terminó el día?",
    "¿Con cuánto cacao comenzó el día?",
    "¿Con cuánto cacao terminó el día?",
    "¿Cuántos adicionales dejaron hoy?",
    "¿Las bandejas quedaron marcadas correctamente?",
    "¿Recogiste los vasitos y las tapas del día anterior?",
    "¿Anotaste en el cuaderno los vasos entregados hoy?",
    "¿Dejaste las tapitas para los vasitos de helado que se van a producir hoy?",
    "¿Las tapitas están correctamente ordenadas por líneas y sabores?",
    "¿Qué productos están cerca de acabarse? (indica el producto y la cantidad aproximada que queda)",
    "¿Hubo alguna incidencia, problema o área de mejora hoy?",
    "¿Comentarios finales del día?"
]


class ReporteCancelado(Exception):
    pass


# ================== HELPER PARA OBTENER RESPUESTA ====================
async def obtener_respuesta(channel, user):
    msg = await bot.wait_for("message", check=lambda m: m.author == user and m.channel == channel)
    contenido = msg.content.strip().lower()

    # Detección flexible de cancelar
    if "cancelar" in contenido:
        await channel.send("✅ **Reporte de Pesadas cancelado.**\nPuedes iniciar uno nuevo con `/reporte-pesadas`.")
        if user.id in reports:
            del reports[user.id]
        raise ReporteCancelado()

    return msg


# ================== FUNCIÓN PRINCIPAL ====================
async def iniciar_reporte(channel, user):
    if user.id in reports:
        await channel.send("Ya tienes un reporte de pesadas en curso. Termínalo o cancélalo primero.")
        return

    reports[user.id] = {"answers": {}}

    await channel.send(
        f"📋 **Reporte de Pesadas iniciado** por {user.mention}\n\n"
        "_Escribe **cancelar** en cualquier momento para detenerlo._"
    )

    try:
        for i, pregunta in enumerate(PREGUNTAS, 1):
            await channel.send(f"**{i}.** {pregunta}")
            msg = await obtener_respuesta(channel, user)
            await channel.send("✅")
            reports[user.id]["answers"][f"q{i}"] = msg.content

        await channel.send("✅ **Reporte de Pesadas completado. ¡Gracias!**")
        if user.id in reports:
            del reports[user.id]

    except ReporteCancelado:
        pass


# ================== COMANDO SLASH ==================
@bot.tree.command(name="reporte-pesadas", description="Inicia el Reporte de Pesadas")
async def reporte_pesadas(interaction: discord.Interaction):
    await iniciar_reporte(interaction.channel, interaction.user)


# ================== COMANDO POR TEXTO ==================
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    content = message.content.strip().lower()

    if "reporte de pesadas" in content:
        await iniciar_reporte(message.channel, message.author)

    await bot.process_commands(message)


@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} slash commands sincronizados correctamente")
    except Exception as e:
        print(f"❌ Error al sincronizar comandos: {e}")
        traceback.print_exc()


# ================== INICIO DEL BOT ==================
bot.run(TOKEN)
