"""Varias fotos en un mensaje no cierran el empaque vacío.

En el bulto nuevo solo cuenta la primera y siempre se pide el empaque
vacío en otro mensaje. En el empaque vacío también solo cuenta la primera.
"""
import asyncio
import os
import unittest

os.environ["PESADAS_NO_ARRANCAR"] = "1"
os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("XAI_API_KEY", "test-key")

import main


def _paso_transferencia() -> int:
    return next(i for i, p in enumerate(main.PREGUNTAS) if p["tipo"] == "transferencia")


class Canal:
    def __init__(self, cid=42):
        self.id = cid
        self.messages = []

    async def send(self, content):
        self.messages.append(content)


class Autor:
    def __init__(self, user_id=7):
        self.id = user_id


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


class TestFotosTransferenciaUnaPorMensaje(unittest.TestCase):
    def setUp(self):
        main.conversation_state.clear()

    def tearDown(self):
        main.conversation_state.clear()

    def _estado(self, canal):
        state = main._crear_estado(7)
        state["paso"] = _paso_transferencia()
        main.conversation_state[str(canal.id)] = state
        return state

    def test_dos_fotos_en_bulto_nuevo_piden_el_vacio(self):
        asyncio.run(self._assert_dos_en_nuevo())

    async def _assert_dos_en_nuevo(self):
        canal = Canal()
        state = self._estado(canal)
        paso = state["paso"]
        state["fotos_tx"] = {
            "productos": ["Leche"],
            "idx": 0,
            "paso_foto": "nuevo",
            "capturas": {},
        }
        await main.manejar_respuesta(
            Mensaje(
                "",
                canal,
                [Adjunto("bulto-nuevo.jpg"), Adjunto("otra-llena.jpg")],
            )
        )

        slot = state["fotos_tx"]["capturas"]["Leche"]
        self.assertEqual(slot["nuevo"]["filename"], "bulto-nuevo.jpg")
        self.assertIsNone(slot["vacio"])
        self.assertNotIn("otra-llena.jpg", slot["nuevo"]["filename"])
        self.assertNotIn("otra-llena.jpg", slot["nuevo"]["url"])
        self.assertEqual(list(state["fotos_tx"]["capturas"]), ["Leche"])
        self.assertEqual(state["fotos_tx"]["paso_foto"], "vacio")
        self.assertEqual(state["fotos_tx"]["idx"], 0)
        self.assertEqual(state["paso"], paso)
        self.assertEqual(canal.messages, [main._texto_pedir_foto("Leche", "vacio")])
        self.assertNotIn("Listo, ya tengo las fotos de la transferencia.", canal.messages)
        self.assertNotIn("fotos_transferencia", state["answers"])

    def test_varias_fotos_en_bulto_nuevo_tampoco_guardan_el_vacio(self):
        asyncio.run(self._assert_tres_en_nuevo())

    async def _assert_tres_en_nuevo(self):
        canal = Canal()
        state = self._estado(canal)
        state["fotos_tx"] = {
            "productos": ["Leche"],
            "idx": 0,
            "paso_foto": "nuevo",
            "capturas": {},
        }
        await main.manejar_respuesta(
            Mensaje(
                "",
                canal,
                [
                    Adjunto("bulto-nuevo.jpg"),
                    Adjunto("segunda.jpg"),
                    Adjunto("tercera.jpg"),
                ],
            )
        )

        slot = state["fotos_tx"]["capturas"]["Leche"]
        self.assertEqual(slot["nuevo"]["filename"], "bulto-nuevo.jpg")
        self.assertIsNone(slot["vacio"])
        self.assertEqual(canal.messages, [main._texto_pedir_foto("Leche", "vacio")])
        self.assertIsNotNone(state["fotos_tx"])

    def test_fotos_extra_en_empaque_vacio_no_avanzan_al_siguiente(self):
        asyncio.run(self._assert_dos_en_vacio())

    async def _assert_dos_en_vacio(self):
        canal = Canal()
        state = self._estado(canal)
        state["fotos_tx"] = {
            "productos": ["Leche", "Azúcar"],
            "idx": 0,
            "paso_foto": "vacio",
            "capturas": {
                "Leche": {
                    "nuevo": {
                        "filename": "bulto-nuevo.jpg",
                        "url": "https://cdn.example/bulto-nuevo.jpg",
                        "content_type": "image/jpeg",
                    },
                    "vacio": None,
                }
            },
        }
        await main.manejar_respuesta(
            Mensaje(
                "",
                canal,
                [Adjunto("empaque-vacio.jpg"), Adjunto("no-es-el-siguiente.jpg")],
            )
        )

        leche = state["fotos_tx"]["capturas"]["Leche"]
        self.assertEqual(leche["nuevo"]["filename"], "bulto-nuevo.jpg")
        self.assertEqual(leche["vacio"]["filename"], "empaque-vacio.jpg")
        self.assertNotIn("Azúcar", state["fotos_tx"]["capturas"])
        self.assertNotIn("no-es-el-siguiente.jpg", leche["vacio"]["filename"])
        self.assertNotIn("no-es-el-siguiente.jpg", leche["vacio"]["url"])
        self.assertEqual(state["fotos_tx"]["idx"], 1)
        self.assertEqual(state["fotos_tx"]["paso_foto"], "nuevo")
        self.assertEqual(
            canal.messages,
            [main._texto_pedir_foto("Azúcar", "nuevo")],
        )
        self.assertNotIn("Listo, ya tengo las fotos de la transferencia.", canal.messages)
        self.assertNotIn("fotos_transferencia", state["answers"])


if __name__ == "__main__":
    unittest.main()
