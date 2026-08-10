import discord
from discord.ext import commands
import os
import traceback
from openai import OpenAI
import json
import re
from typing import Optional

print(">>> Iniciando bot de reporte de pesadas...")

# ================== CONFIGURACIÓN ==================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("❌ ERROR: Falta la variable de entorno DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

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

# ================== PREGUNTAS + REGLAS ==================
# tipo:
#   cantidad      → número / peso (puede ir con unidades, potes, multilínea)
#   adicionales   → lista producto + cantidad
#   transferencia → no / sí + productos y cantidades (recargas de bultos)
#   si_no         → sí/no
#   stock_bajo    → productos cerca de acabarse (acepta "no hay" = 0)
#   abierta       → texto libre; "no"/"ninguna" OK
PREGUNTAS = [
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


# ================== HELPERS ==================
def _vacio_o_basura(texto: str, tiene_adjuntos: bool) -> bool:
    t = (texto or "").strip()
    if tiene_adjuntos and not t:
        return False
    if not t:
        return True
    return t.lower() in {".", "..", "...", "ok", "vale", "listo", "k", "ya", "-", "—"}


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


def _parece_inicio(content_lower: str) -> bool:
    return content_lower in {
        "reporte de pesadas",
        "iniciar reporte de pesadas",
        "inicio reporte de pesadas",
        "/inicio reporte de pesadas",
        "/ inicio reporte de pesadas",
    }


def _tiene_numero(texto: str) -> bool:
    if not texto:
        return False
    # Busca digitos con decimal opcional (punto o coma)
    patron = r"\d+(?:[.,]\d+)?"
    return re.search(patron, texto) is not None


def _es_si_no_corto(texto: str) -> Optional[bool]:
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


def _mensaje_inicio(user: discord.abc.User) -> str:
    n = len(PREGUNTAS)
    return (
        f"**Reporte de Pesadas iniciado** por {user.mention}\n\n"
        f"**Pregunta 1 de {n}:**\n"
        f"{PREGUNTAS[0]['texto']}\n\n"
        f"_Solo {user.display_name} puede responder este reporte._\n"
        f"_Escribe **cancelar** o **cancelar reporte** para detenerlo._"
    )


def _crear_estado(user_id: int) -> dict:
    return {
        "user_id": user_id,
        "paso": 0,
        "answers": {},
        "buffer": "",
    }


async def iniciar_reporte(channel, user: discord.abc.User) -> bool:
    """Inicia por texto. True si arrancó, False si ya había uno."""
    channel_id = str(channel.id)
    if channel_id in conversation_state:
        dueño = conversation_state[channel_id]["user_id"]
        await channel.send(
            f"Ya hay un reporte de pesadas en curso (iniciado por <@{dueño}>). "
            f"Termínenlo o escriban **cancelar reporte**."
        )
        return False

    conversation_state[channel_id] = _crear_estado(user.id)
    await channel.send(_mensaje_inicio(user))
    return True


# ================== SLASH ==================
# Discord exige responder la interacción en < 3 segundos.
# Si el bot está caído o tarda, el usuario ve: "La aplicación no respondió".
@bot.tree.command(name="reporte-pesadas", description="Inicia el Reporte de Pesadas")
async def reporte_pesadas_slash(interaction: discord.Interaction):
    try:
        channel_id = str(interaction.channel.id) if interaction.channel else None
        if not channel_id:
            await interaction.response.send_message(
                "❌ No pude identificar el canal. Usa el comando dentro de #pesadas.",
                ephemeral=True,
            )
            return

        if channel_id in conversation_state:
            dueño = conversation_state[channel_id]["user_id"]
            await interaction.response.send_message(
                f"Ya hay un reporte en curso (iniciado por <@{dueño}>).\n"
                f"Escribe **cancelar reporte** para reiniciar.",
                ephemeral=True,
            )
            return

        # Estado + respuesta pública inmediata (cumple el deadline de Discord)
        conversation_state[channel_id] = _crear_estado(interaction.user.id)
        await interaction.response.send_message(_mensaje_inicio(interaction.user))
        print(f"[PESADAS] slash OK user={interaction.user.id} channel={channel_id}")

    except discord.errors.NotFound:
        print("[PESADAS] slash NotFound: interacción expirada (>3s)")
        return
    except discord.errors.InteractionResponded:
        try:
            await interaction.followup.send(
                "El reporte ya se estaba iniciando…", ephemeral=True
            )
        except Exception:
            pass
    except Exception as e:
        print(f"[PESADAS] Error en slash: {e}")
        traceback.print_exc()
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"⚠️ Error al iniciar el reporte: `{type(e).__name__}`. "
                    f"Prueba escribir: **inicio reporte de pesadas**",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"⚠️ Error: `{type(e).__name__}`. "
                    f"Prueba: **inicio reporte de pesadas**",
                    ephemeral=True,
                )
        except Exception:
            pass


@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user} (id={bot.user.id})")
    print(f"   Guilds: {[g.name for g in bot.guilds]}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} slash commands sincronizados: {[c.name for c in synced]}")
    except Exception as e:
        print(f"❌ Error al sincronizar slash: {e}")
        traceback.print_exc()


@bot.event
async def on_error(event_method, *args, **kwargs):
    print(f"❌ on_error en {event_method}")
    traceback.print_exc()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    print(f"❌ Error en app command: {error}")
    traceback.print_exc()
    try:
        msg = "⚠️ Falló el comando. Escribe en el canal: **inicio reporte de pesadas**"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content_lower = (message.content or "").strip().lower()
    channel_id = str(message.channel.id)
    state = conversation_state.get(channel_id)

    if state and _parece_cancelar(content_lower):
        es_dueño = message.author.id == state["user_id"]
        if es_dueño or content_lower in {
            "cancelar reporte",
            "reporte cancelado",
            "canelar reporte",
        }:
            del conversation_state[channel_id]
            await message.channel.send("✅ Reporte de Pesadas cancelado.")
        return

    if _parece_inicio(content_lower):
        await iniciar_reporte(message.channel, message.author)
        return

    if not state:
        return

    # Solo el dueño avanza (evita que Tania/Martha “cierren” la pregunta del cacao)
    if message.author.id != state["user_id"]:
        return

    await manejar_respuesta(message)


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
        if re.search(
            r"\bno\s+hay\b|\bninguno\b|\bnada\b|\b0\b", texto.lower()
        ) or _tiene_numero(texto):
            if len(texto) >= 3:
                await _aceptar_y_avanzar(message, state, texto)
                return

    if tipo in {"adicionales", "transferencia"}:
        if _tiene_numero(texto) or sn is False:
            await _aceptar_y_avanzar(message, state, texto)
            return
        if sn is True:
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
            "Todas las respuestas han sido registradas. ¡Gracias!\n"
            f"_Respondido por <@{state['user_id']}>._"
        )
        print(
            f"[PESADAS OK] channel={channel_id} "
            f"answers={json.dumps(state['answers'], ensure_ascii=False)}"
        )
        del conversation_state[channel_id]


# ================== INICIO ==================
bot.run(DISCORD_TOKEN)
