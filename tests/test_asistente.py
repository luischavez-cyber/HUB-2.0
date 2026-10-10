"""Pruebas del asistente sin llamar a la API (cliente simulado)."""
import json
from types import SimpleNamespace as NS

from caepsa.asistente.agente import Asistente
from caepsa.asistente.herramientas import DEFINICIONES, Contexto, ejecutar


def test_herramientas_cubren_flujo_completo():
    ctx = Contexto(usuario="qa")
    salida, error = ejecutar(ctx, "consultar_ficha", {})
    assert error and "No hay proyecto activo" in salida
    assert not ejecutar(ctx, "crear_proyecto", {"nombre": "Nueva Italia"})[1]
    assert not ejecutar(ctx, "actualizar_ficha", {"usos_suelo": ["agricola"], "producto": "Diésel"})[1]
    salida, error = ejecutar(ctx, "registrar_resultados", {"filas": [
        {"muestra": "M1", "punto": "P1", "zona": "Zona 1", "parametro": "HFM", "valor": "1500"},
        {"muestra": "M1", "parametro": "Benzo(a)pireno", "valor": "<0.01"}]})
    assert json.loads(salida)["errores"] == []
    ev = json.loads(ejecutar(ctx, "evaluar_nom138", {"solo_excedencias": True})[0])
    m = ev["muestras"][0]
    hfm = next(r for r in m["resultados"] if r["parametro"] == "HFM")
    assert m["dictamen"] == "Excede" and hfm["lmp"] == 1200 and hfm["estado"] == "Excede"
    assert "Dibenzo[a,h]antraceno" not in str(m) and "DBAHA" in m["parametros_faltantes_tabla1"]
    norma = json.loads(ejecutar(ctx, "consultar_norma", {"parametro": "fracción pesada",
                                                         "usos_suelo": ["agricola", "residencial"]})[0])
    assert norma["lmp"][0]["lmp_aplicable_uso_mixto"] == 1500
    salida, error = ejecutar(ctx, "exportar_evaluacion", {"formato": "excel"})
    assert not error and ctx.archivos_generados[0].exists()
    assert ejecutar(ctx, "consultar_norma", {"parametro": "Plomo"})[1]  # no normado en NOM-138
    assert ejecutar(ctx, "inexistente", {})[1]
    assert ejecutar(ctx, "consultar_ficha", {"campo_raro": 1})[1]  # argumentos inválidos -> error controlado
    assert len(DEFINICIONES) == 30


class ClienteFalso:
    """Simula dos respuestas: una llamada a herramienta y luego texto final."""

    def __init__(self):
        self.llamadas = []
        self.respuestas = [
            NS(stop_reason="tool_use", content=[
                NS(type="tool_use", id="t1", name="crear_proyecto", input={"nombre": "Demo"})]),
            NS(stop_reason="end_turn", content=[NS(type="text", text="Proyecto creado.")]),
        ]
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.llamadas.append(kw)
        return self.respuestas.pop(0)


def test_loop_del_agente_ejecuta_herramientas_y_conserva_historial():
    cliente = ClienteFalso()
    a = Asistente(Contexto(), cliente=cliente)
    eventos = []
    assert a.enviar("Crea el proyecto Demo", eventos.append) == "Proyecto creado."
    assert a.ctx.proyecto == "demo"
    assert [e.tipo for e in eventos] == ["herramienta", "texto"]
    roles = [m["role"] for m in a.mensajes]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert a.mensajes[2]["content"][0]["tool_use_id"] == "t1"
    kw = cliente.llamadas[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
