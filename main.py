from discord.ext import commands
import os
import traceback
from openai import OpenAI
import json
import re
 
print(">>> Iniciando reporte-de-pesadas-bot...")
print(">>> Iniciando bot de reporte de pesadas...")
 
# ================== CONFIGURACIÓN ==================
TOKEN = os.getenv("TOKEN")
 
if not TOKEN:
    raise RuntimeError("❌ ERROR: Falta la variable de entorno TOKEN")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("❌ ERROR: Falta la variable de entorno DISCORD_TOKEN")
 
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
 
bot = commands.Bot(command_prefix="!", intents=intents)
 
reports = {}
client = OpenAI(
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1",
)
 
# Estado por canal:
# {
#   "user_id": int,
#   "paso": int,
#   "answers": { "0": "...", ... },
#   "buffer": str,
# }
conversation_state = {}
 
# ================== PREGUNTAS ==================
# ================== PREGUNTAS + REGLAS ==================
# tipo:
#   cantidad      → número / peso (puede ir con unidades, potes, multilínea)
#   adicionales   → lista producto + cantidad
#   transferencia → no / sí + productos y cantidades (recargas de bultos)
#   si_no         → sí/no
#   stock_bajo    → productos cerca de acabarse (acepta "no hay" = 0)
#   abierta       → texto libre; "no"/"ninguna" OK
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
    {
        "texto": "¿Con cuánta leche comenzó el día?",
        "tipo": "cantidad",
        "reglas": (
            "Válido: número de cantidad/peso (9.30, 14.40, 4,30). "
            "Unidades opcionales (kg, bultos). "
            "Inválido: solo punto o sin número."
        ),
    },
    {
        "texto": "¿Con cuánta leche terminó el día?",
        "tipo": "cantidad",
        "reglas": "Igual que leche inicial. Número de cierre válido.",
    },
    {
        "texto": "¿Con cuánto azúcar comenzó el día?",
        "tipo": "cantidad",
        "reglas": "Número de cantidad/peso. Válido.",
    },
    {
        "texto": "¿Con cuánto azúcar terminó el día?",
        "tipo": "cantidad",
        "reglas": "Número de cantidad/peso. Válido.",
    },
    {
        "texto": "¿Con cuánto suero comenzó el día?",
        "tipo": "cantidad",
        "reglas": "Número de cantidad/peso. Válido.",
    },
    {
        "texto": "¿Con cuánto suero terminó el día?",
        "tipo": "cantidad",
        "reglas": "Número de cantidad/peso. Válido.",
    },
    {
        "texto": "¿Con cuánto cacao comenzó el día?",
        "tipo": "cantidad",
        "reglas": (
            "Válido si hay un número de cantidad (3.217, 2.197, 4.104). "
            "Puede traer 'pote', decimales con punto o coma, y líneas extra "
            "como 2N 2C 2G (conteos de potes/líneas). "
            "CRÍTICO: '3.217 pote' + '2N 2C 2G' YA tiene la cantidad → válido. "
            "NO digas 'no me dijiste con cuánto comenzó' si hay un número claro. "
            "Foto + número también válido."
        ),
    },
    {
        "texto": "¿Con cuánto cacao terminó el día?",
        "tipo": "cantidad",
        "reglas": (
            "Igual que cacao inicial. Número + notas/pote/líneas extra OK. "
            "No rechaces multilínea si el número está."
        ),
    },
    {
        "texto": "¿Con cuánto arequipe comenzó el día?",
        "tipo": "cantidad",
        "reglas": "Número de cantidad/peso (kg o potes). Válido.",
    },
    {
        "texto": "¿Con cuánto arequipe terminó el día?",
        "tipo": "cantidad",
        "reglas": (
            "Número válido, incluido 0 o 0.00 si el pote en uso quedó vacío. "
            "Si aclara potes nuevos aparte, mejor, pero no es obligatorio."
        ),
    },
    {
        "texto": (
            "¿Hubo transferencia del almacén de bultos al almacén de pesadas hoy? "
            "Si sí, indica qué productos se transfirieron (por ejemplo leche, azúcar, cacao, "
            "estabilizante, conos) y en qué cantidades. Si no hubo, responde **No**."
        ),
        "tipo": "transferencia",
        "reglas": (
            "Válido 'No' / 'No hubo' / 'Ninguna' si no hubo transferencia. "
            "Si sí hubo: lista producto + cantidad (ej. 'Leche 25.25, azúcar 1 bulto, "
            "cacao 1 bulto, estabilizante 0,8515, 1 caja de conos'). "
            "Eso es lo que antes se olvidaba reportar como 'recargas de bultos'. "
            "NO exijas un solo número total. El desglose ES la respuesta correcta. "
            "Si dice 'sí' sin productos, pide qué y cuánto."
        ),
    },
    {
        "texto": (
            "¿Qué adicionales se dejaron hoy? Indica producto y cantidad "
            "(ej. leche, azúcar, glucosa, crema de leche). Si no hubo, responde **No** o **0**."
        ),
        "tipo": "adicionales",
        "reglas": (
            "Válido: lista con producto y cantidad "
            "('270 azúcar café, 1300 leche, 63 azúcar bianchi, 18 glucosa'). "
            "Válido: 'No', 'Ninguno', '0'. "
            "CRÍTICO: NO digas 'responde con el número o la cantidad' rechazando el desglose. "
            "El desglose ES lo que se necesita. "
            "NO fuerces un único número total (ej. '4') que borre el detalle."
        ),
    },
    {
        "texto": "¿Las bandejas quedaron marcadas correctamente?",
        "tipo": "si_no",
        "reglas": "Sí/No válido. Puede matizar.",
    },
    {
        "texto": "¿Recogiste los vasitos y las tapas del día anterior?",
        "tipo": "si_no",
        "reglas": "Sí/No válido.",
    },
    {
        "texto": "¿Anotaste en el cuaderno los vasos entregados hoy?",
        "tipo": "si_no",
        "reglas": "Sí/No válido. 'Lo dejé en el cuaderno, no había internet' ES válido.",
    },
    {
        "texto": "¿Dejaste las tapitas para los vasitos de helado que se van a producir hoy?",
        "tipo": "si_no",
        "reglas": "Sí/No válido.",
    },
    {
        "texto": "¿Las tapitas están correctamente ordenadas por líneas y sabores?",
        "tipo": "si_no",
        "reglas": "Sí/No válido. Puede reportar un error (ej. tapas de coco en chocooreo).",
    },
    {
        "texto": (
            "¿Qué productos están cerca de acabarse? Indica el producto y la cantidad "
            "aproximada que queda (si no hay, pon 0 o 'no hay')."
        ),
        "tipo": "stock_bajo",
        "reglas": (
            "Válido: lista producto + cantidad o 'no hay' / 0. "
            "'Bandejas de un litro no hay' ES válido (= 0). "
            "'Bianchi quedan 4' ES válido. "
            "Si pide una planilla o algo operativo sin listar stock, pide al menos un producto "
            "o que diga 'ninguno cerca de acabarse'. "
            "NO rechaces 'no hay' por no traer un número explícito."
        ),
    },
    {
        "texto": "¿Hubo alguna incidencia, problema o área de mejora hoy?",
        "tipo": "abierta",
        "reglas": "'No' / 'Ninguna' ES válido. Descripción de incidencia también.",
    },
    {
        "texto": (
            "¿Comentarios finales del día? "
            "(Puedes incluir pesadas que quedan, cacao por línea, recargas que faltaron anotar, etc.)"
        ),
        "tipo": "abierta",
        "reglas": (
            "'No' / 'Ninguno' ES válido. "
            "Listas tipo 'Dejó pesadas: 5N 2S…' o recargas ES válido y útil."
        ),
    },
]
 
 
class ReporteCancelado(Exception):
    pass
# ================== HELPERS ==================
def _vacio_o_basura(texto: str, tiene_adjuntos: bool) -> bool:
    t = (texto or "").strip()
    if tiene_adjuntos and not t:
        return False
    if not t:
        return True
    return t.lower() in {".", "..", "...", "ok", "vale", "listo", "k", "ya", "-", "—"}
 
 
# ================== HELPER PARA OBTENER RESPUESTA ====================
async def obtener_respuesta(channel, user):
    # Usamos IDs para comparación robusta (funciona mejor con slash commands, hilos, etc.)
    msg = await bot.wait_for(
        "message",
        check=lambda m: m.author.id == user.id and m.channel.id == channel.id
    )
    contenido = msg.content.strip().lower()
def _parece_cancelar(content_lower: str) -> bool:
    patrones = [
        r"^cancelar(\s+reporte)?$",
        r"^cancel(\s+report)?$",
        r"^cancela(r)?$",
        r"^canelar(\s+reporte)?$",
        r"^reporte\s+cancelado$",
        r"^detener(\s+reporte)?$",
    ]
    return any(re.match(p, content_lower) for p in patrones)
 
    # Detección flexible de cancelar (acepta "cancelar", "cancel", y frases que los contengan)
    if "cancelar" in contenido or "cancel" in contenido:
        await channel.send("✅ **Reporte de Pesadas cancelado.**\nPuedes iniciar uno nuevo con `/reporte-pesadas` o escribiendo `reporte de pesadas`.")
        if user.id in reports:
            del reports[user.id]
        raise ReporteCancelado()
 
    return msg
def _parece_inicio(content_lower: str) -> bool:
    return content_lower in {
        "reporte de pesadas",
        "iniciar reporte de pesadas",
        "inicio reporte de pesadas",
        "/inicio reporte de pesadas",
        "/ inicio reporte de pesadas",
    }
 
 
# ================== FUNCIÓN PRINCIPAL ====================
async def iniciar_reporte(channel, user):
    if user.id in reports:
        await channel.send("Ya tienes un reporte de pesadas en curso. Termínalo o cancélalo primero.")
        return
def _tiene_numero(texto: str) -> bool:
    return bool(re.search(r"\d+([.,]\d+)?", texto or ""))
 
    reports[user.id] = {"answers": {}}
 
    await channel.send(
        f"📋 **Reporte de Pesadas iniciado** por {user.mention}\n\n"
        "_Escribe **cancelar** o **cancel** en cualquier momento para detenerlo._"
    )
def _es_si_no_corto(texto: str) -> bool | None:
    t = re.sub(r"[¡!?.]", "", (texto or "").strip().lower())
    if t in {"si", "sí", "yes", "s", "1", "correcto"}:
        return True
    if t in {"no", "n", "0", "nop", "ninguno", "ninguna", "nada"}:
        return False
    if re.match(r"^(si|sí)\b", t) and len(t) <= 60:
        return True
    if re.match(r"^no\b", t) and len(t) <= 60:
        return False
    return None
 
    try:
        for i, pregunta in enumerate(PREGUNTAS, 1):
            await channel.send(f"**{i}.** {pregunta}")
            msg = await obtener_respuesta(channel, user)
            await channel.send("✅")
            reports[user.id]["answers"][f"q{i}"] = msg.content
 
        await channel.send("✅ **Reporte de Pesadas completado. ¡Gracias!**")
        if user.id in reports:
            del reports[user.id]
async def iniciar_reporte(channel, user: discord.abc.User):
    channel_id = str(channel.id)
    if channel_id in conversation_state:
        dueño = conversation_state[channel_id]["user_id"]
        await channel.send(
            f"Ya hay un reporte de pesadas en curso (iniciado por <@{dueño}>). "
            f"Termínenlo o escriban **cancelar reporte**."
        )
        return
 
    except ReporteCancelado:
        if user.id in reports:
            del reports[user.id]
    conversation_state[channel_id] = {
        "user_id": user.id,
        "paso": 0,
        "answers": {},
        "buffer": "",
    }
    n = len(PREGUNTAS)
    await channel.send(
        f"**Reporte de Pesadas iniciado** por {user.mention}\n\n"
        f"**Pregunta 1 de {n}:**\n"
        f"{PREGUNTAS[0]['texto']}\n\n"
        f"_Solo {user.display_name} puede responder este reporte._\n"
        f"_Escribe **cancelar** o **cancelar reporte** para detenerlo._"
    )
 
 
# ================== COMANDO SLASH ==================
# ================== SLASH ==================
@bot.tree.command(name="reporte-pesadas", description="Inicia el Reporte de Pesadas")
async def reporte_pesadas(interaction: discord.Interaction):
    # Responder inmediatamente a la interacción (evita "The application did not respond")
async def reporte_pesadas_slash(interaction: discord.Interaction):
    channel_id = str(interaction.channel.id)
    if channel_id in conversation_state:
        dueño = conversation_state[channel_id]["user_id"]
        await interaction.response.send_message(
            f"Ya hay un reporte en curso (iniciado por <@{dueño}>).",
            ephemeral=True,
        )
        return
 
    await interaction.response.defer(ephemeral=True)
    await iniciar_reporte(interaction.channel, interaction.user)
    try:
        await interaction.followup.send("Reporte iniciado en el canal.", ephemeral=True)
    except Exception:
        pass
 
 
# ================== COMANDO POR TEXTO ==================
@bot.event
async def on_message(message):
    if message.author == bot.user:
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} slash commands sincronizados")
    except Exception as e:
        print(f"❌ Error al sincronizar: {e}")
        traceback.print_exc()
 
 
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
 
    content = message.content.strip().lower()
    content_lower = (message.content or "").strip().lower()
    channel_id = str(message.channel.id)
    state = conversation_state.get(channel_id)
 
    if state and _parece_cancelar(content_lower):
        es_dueño = message.author.id == state["user_id"]
        if es_dueño or content_lower in {"cancelar reporte", "reporte cancelado", "canelar reporte"}:
            del conversation_state[channel_id]
            await message.channel.send("✅ Reporte de Pesadas cancelado.")
        return
 
    if "reporte de pesadas" in content:
    if _parece_inicio(content_lower):
        await iniciar_reporte(message.channel, message.author)
        return
 
    if not state:
        return
 
    # Solo el dueño avanza (evita que Tania/Martha “cierren” la pregunta del cacao)
    if message.author.id != state["user_id"]:
        return
 
    await manejar_respuesta(message)
 
    await bot.process_commands(message)
 
# ================== GROK ==================
async def consultar_grok(
    pregunta_item: dict,
    respuesta_nueva: str,
    buffer: str,
    tiene_adjuntos: bool,
) -> dict:
    system_prompt = """
Eres validador del Reporte de Pesadas de una fábrica de helados.
Responde ÚNICAMENTE JSON:
{
  "respuesta_valida": true o false,
  "mensaje": null o "texto corto pidiendo SOLO lo que falta"
}
 
@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
Principios:
1. Sé RAZONABLE. Evalúa si la INFORMACIÓN está, no si la frase es perfecta.
2. Números con punto o coma (3.217 / 3,217) son válidos.
3. Multilínea con número + notas (pote, 2N 2C 2G) es VÁLIDA si el número está.
4. Listas producto+cantidad son la respuesta CORRECTA en adicionales y transferencias.
5. "No" / "No hubo" / "Ninguno" / "0" son válidos cuando la pregunta lo permite.
6. "No hay" en stock bajo = cantidad 0 → válido.
7. Sí/No cortos válidos en checklists.
8. BUFFER + respuesta nueva se evalúan juntos.
9. Español informal y typos OK.
10. Nunca digas solo "Responde completo..." sin decir qué falta.
11. Nunca digas "no me dijiste la cantidad" si hay un dígito claro en el texto.
12. Punto "." solo → inválido.
 
Errores REALES que debes evitar:
- Rechazar "3.217 pote / 2N 2C 2G" pidiendo de nuevo el cacao.
- Rechazar desglose de adicionales pidiendo "un número".
- Rechazar "Bandejas de un litro no hay".
- Tragar mensajes de otras personas (eso lo filtra el código; tú solo validas el texto dado).
"""
 
    user_content = f"""
Pregunta:
{pregunta_item["texto"]}
 
Tipo: {pregunta_item.get("tipo")}
Reglas de esta pregunta:
{pregunta_item.get("reglas", "")}
 
Tiene_adjuntos: {tiene_adjuntos}
 
BUFFER (intentos previos misma pregunta):
\"\"\"{buffer or "(vacío)"}\"\"\"
 
Respuesta NUEVA:
\"\"\"{respuesta_nueva}\"\"\"
"""
 
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} slash commands sincronizados correctamente")
        response = client.chat.completions.create(
            model="grok-4-1-fast",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        return {
            "respuesta_valida": bool(data.get("respuesta_valida", False)),
            "mensaje": data.get("mensaje"),
        }
    except Exception as e:
        print(f"❌ Error al sincronizar comandos: {e}")
        print(f"Error al consultar Grok: {e}")
        traceback.print_exc()
        if _vacio_o_basura(respuesta_nueva, tiene_adjuntos):
            return {
                "respuesta_valida": False,
                "mensaje": "Escribe la respuesta con datos (no uses solo un punto).",
            }
        return {"respuesta_valida": True, "mensaje": None}
 
 
# ================== MANEJO ==================
async def manejar_respuesta(message: discord.Message):
    channel_id = str(message.channel.id)
    state = conversation_state.get(channel_id)
    if not state:
        return
 
    paso = state["paso"]
    if paso < 0 or paso >= len(PREGUNTAS):
        del conversation_state[channel_id]
        return
 
    item = PREGUNTAS[paso]
    texto = (message.content or "").strip()
    tiene_adjuntos = bool(message.attachments)
    tipo = item.get("tipo")
 
    if _vacio_o_basura(texto, tiene_adjuntos):
        await message.channel.send(
            "Escribe la respuesta con datos (no uses solo un punto). "
            "Si es una cantidad, pon el número (ej. 3.217). "
            "Si no aplica, di **No** o **No hubo**."
        )
        return
 
    # Atajos locales: menos tokens y menos rechazos absurdos
    sn = _es_si_no_corto(texto)
 
    if tipo == "si_no" and sn is not None:
        await _aceptar_y_avanzar(message, state, texto)
        return
 
    if tipo in {"abierta", "transferencia", "adicionales"} and sn is False:
        # "No" / "Ninguno" / "Nada"
        await _aceptar_y_avanzar(message, state, texto)
        return
 
    if tipo == "cantidad" and _tiene_numero(texto):
        # Número presente → aceptar (evita el bug del cacao 3.217 pote)
        await _aceptar_y_avanzar(message, state, texto)
        return
 
    if tipo == "cantidad" and tiene_adjuntos and not texto:
        await message.channel.send(
            "Recibí la foto. Escribe también la **cantidad en número** "
            "(ej. 3,217) para poder registrar el dato."
        )
        return
 
    if tipo == "stock_bajo":
        # "no hay", listas con productos, o 0
        if re.search(r"\bno\s+hay\b|\bninguno\b|\bnada\b|\b0\b", texto.lower()) or _tiene_numero(texto):
            if len(texto) >= 3:
                await _aceptar_y_avanzar(message, state, texto)
                return
 
    if tipo in {"adicionales", "transferencia"}:
        # Desglose con al menos un número o "no"
        if _tiene_numero(texto) or sn is False:
            await _aceptar_y_avanzar(message, state, texto)
            return
        if sn is True:
            # Dijo "sí" sin detalle en transferencia
            state["buffer"] = ((state.get("buffer") or "") + "\n" + texto).strip()
            await message.channel.send(
                "Ok, hubo movimiento. Indica **qué productos** y **en qué cantidades**."
            )
            return
 
    # Resto → Grok (con buffer)
    buffer_prev = state.get("buffer") or ""
    respuesta_para_ia = texto
    if tiene_adjuntos:
        nombres = ", ".join(a.filename for a in message.attachments)
        respuesta_para_ia = f"{texto}\n[Adjuntos: {nombres}]".strip()
 
    decision = await consultar_grok(item, respuesta_para_ia, buffer_prev, tiene_adjuntos)
 
# ================== INICIO DEL BOT ==================
bot.run(TOKEN)
    if not decision.get("respuesta_valida", False):
        state["buffer"] = (buffer_prev + "\n" + texto).strip() if buffer_prev else texto
        msg = decision.get("mensaje") or "Falta un dato. Completa solo lo que falta."
        if msg.strip().lower() in {
            "responde completo lo que se te preguntó.",
            "responde con el número o la cantidad.",
            "te falta decirme la cantidad.",
            "no me dijiste con cuánto comenzó.",
            "no me dijiste con cuánto comenzó / terminó.",
            "no me dijiste con cuánto cacao comenzó el día.",
        }:
            # Si en realidad hay número, no castigar
            if _tiene_numero(state["buffer"]):
                await _aceptar_y_avanzar(message, state, state["buffer"])
                return
            msg = "Necesito la cantidad en número (puedes agregar notas en la misma respuesta)."
        await message.channel.send(msg)
        return
 
    final = (buffer_prev + "\n" + texto).strip() if buffer_prev else texto
    await _aceptar_y_avanzar(message, state, final)
 
 
async def _aceptar_y_avanzar(message: discord.Message, state: dict, texto_final: str):
    channel_id = str(message.channel.id)
    paso = state["paso"]
 
    try:
        await message.add_reaction("✅")
    except Exception:
        pass
 
    state["answers"][str(paso)] = texto_final
    state["buffer"] = ""
    state["paso"] = paso + 1
 
    if state["paso"] < len(PREGUNTAS):
        n = state["paso"] + 1
        total = len(PREGUNTAS)
        await message.channel.send(
            f"**Pregunta {n} de {total}:**\n"
            f"{PREGUNTAS[state['paso']]['texto']}"
        )
    else:
        await message.channel.send(
            "✅ **Reporte de Pesadas completado.**\n\n"
            f"Todas las respuestas han sido registradas. ¡Gracias!\n"
            f"_Respondido por <@{state['user_id']}>._"
        )
        print(
            f"[PESADAS OK] channel={channel_id} "
            f"answers={json.dumps(state['answers'], ensure_ascii=False)}"
        )
        del conversation_state[channel_id]
 
 
# ================== INICIO ==================
bot.run(DISCORD_TOKEN)
