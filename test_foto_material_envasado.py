"""Foto obligatoria del material para envasado, justo después de la pregunta 18.

Esa foto es un paso fijo, así que entra en la numeración: pregunta 19 de 22.
La excepción de conos (sin foto de transferencia) no la cubre ni la anula.
"""
import asyncio
import os
import unittest

os.environ["PESADAS_NO_ARRANCAR"] = "1"
os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("XAI_API_KEY", "test-key")

import main


TEXTO_FOTO = (
    "📸 Envía una foto de cómo dejaste organizado el material para envasado, "
    "donde se vean claramente los nombres de las tapitas."
)


def _indice(fragmento: str) -> int:
    return next(i for i, p in enumerate(main.PREGUNTAS) if fragmento in p["texto"])


class Canal:
    def __init__(self, cid=42):
        self.id = cid
        self.messages = []

    async def send(self, content):
        self.messages.append(content)


class Autor:
    def __init__(self, user_id=7):
        self.id = user_id
        self.mention = f"<@{user_id}>"
        self.display_name = "Ana"


class Adjunto:
    def __init__(self, filename, content_type="image/jpeg"):
        self.filename = filename
        self.url = f"https://cdn.example/{filename}"
        self.content_type = content_type


class Mensaje:
    def __init__(self, content, canal, attachments=None):
        self.content = content
        self.channel = canal
        self.attachments = list(attachments or [])
        self.author = Autor()
        self.reactions = []

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)


class TestFotoMaterialEnvasado(unittest.TestCase):
    def setUp(self):
        self._grok = main.consultar_grok
        self._extraer = main.extraer_productos_transferencia
        main.conversation_state.clear()

        async def _grok_no_debe_entrar(*args, **kwargs):
            raise AssertionError("la foto de envasado no se valida con el modelo")

        main.consultar_grok = _grok_no_debe_entrar

    def tearDown(self):
        main.consultar_grok = self._grok
        main.extraer_productos_transferencia = self._extraer
        main.conversation_state.clear()

    def _estado(self, canal, paso):
        state = main._crear_estado(7)
        state["paso"] = paso
        main.conversation_state[str(canal.id)] = state
        return state

    def test_la_foto_es_la_pregunta_19_de_22(self):
        self.assertEqual(main.TEXTO_FOTO_MATERIAL_ENVASADO, TEXTO_FOTO)
        self.assertEqual(len(main.PREGUNTAS), 22)

        self.assertEqual(
            _indice("¿Dejaste las tapitas para los vasitos"),
            16,
        )
        self.assertEqual(
            _indice("¿Las tapitas están correctamente ordenadas"),
            17,
        )
        self.assertEqual(_indice(TEXTO_FOTO), 18)
        self.assertEqual(_indice("cerca de acabarse"), 19)
        self.assertEqual(_indice("incidencia, problema o área de mejora"), 20)
        self.assertEqual(_indice("Comentarios finales del día"), 21)

        foto = main.PREGUNTAS[18]
        self.assertEqual(foto["tipo"], "foto")
        self.assertEqual(foto["clave"], "foto_material_envasado")
        self.assertEqual(foto["texto"], TEXTO_FOTO)
        self.assertEqual(main.PREGUNTAS[17]["tipo"], "si_no")
        self.assertEqual(main.PREGUNTAS[11]["tipo"], "transferencia")

        inicio = main._mensaje_inicio(Autor())
        self.assertIn("**Pregunta 1 de 22:**", inicio)
        self.assertIn("¿Con cuánta leche comenzó el día?", inicio)

    def test_conos_siguen_fuera_de_la_cola_de_transferencia(self):
        self.assertIsNone(main._estado_fotos_si_aplica(["Conos"]))
        self.assertIsNone(main._estado_fotos_si_aplica(["cónos", "caja de conos"]))
        self.assertEqual(
            main._productos_que_requieren_foto(["Leche", "Conos", "Azúcar"]),
            ["Leche", "Azúcar"],
        )
        self.assertFalse(main._es_producto_conos("material para envasado"))
        self.assertFalse(main._es_producto_conos("tapitas"))

    def test_despues_de_la_18_pide_la_foto_como_19_de_22(self):
        asyncio.run(self._assert_despues_de_la_18())

    async def _assert_despues_de_la_18(self):
        canal = Canal()
        state = self._estado(canal, 16)
        await main.manejar_respuesta(Mensaje("Sí", canal))
        self.assertIn("**Pregunta 18 de 22:**", canal.messages[-1])
        self.assertIn("correctamente ordenadas por líneas y sabores", canal.messages[-1])
        self.assertEqual(state["paso"], 17)

        await main.manejar_respuesta(Mensaje("Sí", canal))
        self.assertEqual(state["paso"], 18)
        self.assertEqual(state["answers"]["17"], "Sí")
        self.assertIn("**Pregunta 19 de 22:**", canal.messages[-1])
        self.assertIn(TEXTO_FOTO, canal.messages[-1])
        self.assertNotIn("foto_material_envasado", state["answers"])

    def test_sin_foto_el_reporte_no_avanza_ni_se_completa(self):
        asyncio.run(self._assert_sin_foto())

    async def _assert_sin_foto(self):
        canal = Canal()
        state = self._estado(canal, 18)
        for texto in ("Sí", "listo", "ya organicé las tapitas", "1 caja de conos", "."):
            await main.manejar_respuesta(Mensaje(texto, canal))
            self.assertEqual(state["paso"], 18, texto)
            self.assertEqual(state["buffer"], "", texto)
            self.assertNotIn("foto_material_envasado", state["answers"])
            self.assertNotIn("18", state["answers"])
            self.assertIn(str(canal.id), main.conversation_state)
            self.assertEqual(
                canal.messages[-1],
                "Necesito **una foto** (imagen adjunta).\n" + TEXTO_FOTO,
            )
            self.assertNotIn("completado", canal.messages[-1].lower())
            self.assertNotIn("báscula", canal.messages[-1].lower())

        pdf = Adjunto("notas.pdf", "application/pdf")
        await main.manejar_respuesta(Mensaje("ahí va", canal, [pdf]))
        self.assertEqual(state["paso"], 18)
        self.assertNotIn("foto_material_envasado", state["answers"])
        self.assertIn("Necesito **una foto**", canal.messages[-1])

    def test_la_foto_cierra_el_paso_y_el_reporte_puede_terminar(self):
        asyncio.run(self._assert_con_foto())

    async def _assert_con_foto(self):
        canal = Canal()
        state = self._estado(canal, 18)
        mensaje = Mensaje(
            "listo",
            canal,
            [Adjunto("tapitas.jpg"), Adjunto("extra.png", "image/png")],
        )
        await main.manejar_respuesta(mensaje)

        self.assertEqual(mensaje.reactions, ["✅"])
        self.assertEqual(state["paso"], 19)
        self.assertEqual(state["buffer"], "")
        self.assertEqual(
            state["answers"]["foto_material_envasado"],
            {
                "filename": "tapitas.jpg",
                "url": "https://cdn.example/tapitas.jpg",
                "content_type": "image/jpeg",
            },
        )
        self.assertEqual(state["answers"]["18"], "listo\n[foto: tapitas.jpg]")
        self.assertIn("**Pregunta 20 de 22:**", canal.messages[-1])
        self.assertIn("cerca de acabarse", canal.messages[-1])

        await main.manejar_respuesta(Mensaje("Bandejas de un litro no hay", canal))
        self.assertIn("**Pregunta 21 de 22:**", canal.messages[-1])
        self.assertIn("incidencia", canal.messages[-1])

        await main.manejar_respuesta(Mensaje("No", canal))
        self.assertIn("**Pregunta 22 de 22:**", canal.messages[-1])
        self.assertIn("Comentarios finales", canal.messages[-1])

        await main.manejar_respuesta(Mensaje("No", canal))
        self.assertIn("✅ **Reporte de Pesadas completado.**", canal.messages[-1])
        self.assertNotIn(str(canal.id), main.conversation_state)
        self.assertIn("tapitas.jpg", state["answers"]["foto_material_envasado"]["filename"])

    def test_solo_la_imagen_basta_aunque_el_texto_sea_basura(self):
        asyncio.run(self._assert_solo_imagen())

    async def _assert_solo_imagen(self):
        canal = Canal()
        state = self._estado(canal, 18)
        await main.manejar_respuesta(Mensaje("ya organicé", canal))
        self.assertEqual(state["paso"], 18)

        adj = Adjunto("organizacion.heic", "image/heic")
        await main.manejar_respuesta(Mensaje("ok", canal, [adj]))
        self.assertEqual(state["paso"], 19)
        self.assertEqual(state["answers"]["18"], "ok\n[foto: organizacion.heic]")
        self.assertEqual(
            state["answers"]["foto_material_envasado"]["filename"],
            "organizacion.heic",
        )

        canal_vacio = Canal(99)
        state_vacio = self._estado(canal_vacio, 18)
        await main.manejar_respuesta(
            Mensaje("   ", canal_vacio, [Adjunto("solo.webp", "image/webp")])
        )
        self.assertEqual(state_vacio["paso"], 19)
        self.assertEqual(state_vacio["answers"]["18"], "[foto: solo.webp]")

    def test_mencionar_conos_no_salta_la_foto_de_envasado(self):
        asyncio.run(self._assert_conos_no_salta_envasado())

    async def _assert_conos_no_salta_envasado(self):
        canal = Canal()
        state = self._estado(canal, 18)
        await main.manejar_respuesta(Mensaje("también pasé 1 caja de cónos", canal))
        self.assertEqual(state["paso"], 18)
        self.assertIsNone(state["fotos_tx"])
        self.assertNotIn("báscula", "\n".join(canal.messages).lower())
        self.assertIn(TEXTO_FOTO, canal.messages[-1])

        await main.manejar_respuesta(
            Mensaje("1 caja de conos", canal, [Adjunto("envasado.jpg")])
        )
        self.assertIsNone(state["fotos_tx"])
        self.assertEqual(state["paso"], 19)
        self.assertEqual(
            state["answers"]["foto_material_envasado"]["filename"],
            "envasado.jpg",
        )
        self.assertIn("cerca de acabarse", canal.messages[-1])

    def test_transferencia_de_solo_conos_sigue_sin_pedir_foto(self):
        asyncio.run(self._assert_transferencia_conos())

    async def _assert_transferencia_conos(self):
        async def _local(texto):
            return main._productos_locales(texto)

        main.extraer_productos_transferencia = _local
        canal = Canal(7)
        state = self._estado(canal, _indice("transferencia del almacén de bultos"))
        await main.manejar_respuesta(Mensaje("1 caja de conos", canal))
        self.assertIsNone(state["fotos_tx"])
        self.assertNotIn("fotos_transferencia", state["answers"])
        junto = "\n".join(canal.messages).lower()
        self.assertNotIn("báscula", junto)
        self.assertIn("no necesitan foto", junto)
        self.assertIn("adicionales", canal.messages[-1])
        self.assertIn("**Pregunta 13 de 22:**", canal.messages[-1])
        self.assertEqual(main.PREGUNTAS[18]["tipo"], "foto")


if __name__ == "__main__":
    unittest.main()
