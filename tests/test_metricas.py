from app.services.metricas import DIAS_VENTANA, calcular_metricas
from tests.datos_metricas import cargar_datos


def test_sin_tickets_todo_a_cero(db, reloj):
    m = calcular_metricas(db, reloj)
    assert m.total == 0
    assert set(m.por_estado.values()) == {0}
    assert set(m.por_categoria.values()) == {0}
    assert set(m.por_prioridad.values()) == {0}
    assert m.vencidos == 0
    assert m.tiempo_medio_resolucion_horas is None
    assert m.resueltos_por_agente == []


def test_total_y_totales_por_estado(db, reloj):
    cargar_datos(db)
    m = calcular_metricas(db, reloj)
    assert m.total == 9
    assert m.por_estado == {
        "nuevo": 1,
        "en_curso": 1,
        "esperando_cliente": 1,
        "resuelto": 5,
        "cerrado": 1,
    }


def test_totales_por_categoria_incluye_sin_categoria(db, reloj):
    cargar_datos(db)
    m = calcular_metricas(db, reloj)
    assert m.por_categoria == {
        "facturacion": 2,
        "tecnico": 2,
        "cuenta": 1,
        "comercial": 1,
        "envio": 0,
        "otro": 1,
        "sin_clasificar": 2,
    }


def test_totales_por_prioridad(db, reloj):
    cargar_datos(db)
    m = calcular_metricas(db, reloj)
    assert m.por_prioridad == {"baja": 3, "media": 4, "alta": 1, "urgente": 1}


def test_vencidos_solo_cuentan_tickets_sin_terminar_con_plazo_superado(db, reloj):
    cargar_datos(db)
    assert calcular_metricas(db, reloj).vencidos == 2


def test_vencidos_dependen_del_reloj(db, reloj):
    cargar_datos(db)
    reloj.avanzar(hours=4)  # el ticket 2 (límite 12:00) pasa a estar vencido
    assert calcular_metricas(db, reloj).vencidos == 3


def test_tiempo_medio_de_resolucion_en_horas(db, reloj):
    cargar_datos(db)
    # (4 + 12 + 8 + 1 + 6 + 4) / 6 tickets resueltos o cerrados
    assert calcular_metricas(db, reloj).tiempo_medio_resolucion_horas == 35 / 6


def test_resueltos_por_agente_ultimos_7_dias(db, reloj):
    ids = cargar_datos(db)
    m = calcular_metricas(db, reloj)
    assert m.dias_ventana == DIAS_VENTANA == 7
    assert [(a.agente_id, a.nombre, a.resueltos) for a in m.resueltos_por_agente] == [
        (ids["ana"], "Ana", 2),
        (ids["luis"], "Luis", 2),
        (ids["eva"], "Eva", 0),
    ]


def test_la_ventana_de_7_dias_se_mueve_con_el_reloj(db, reloj):
    ids = cargar_datos(db)
    reloj.avanzar(days=1)  # el ticket 9 sale de la ventana
    m = calcular_metricas(db, reloj)
    assert {a.nombre: a.resueltos for a in m.resueltos_por_agente} == {
        "Ana": 2,
        "Luis": 1,
        "Eva": 0,
    }
    assert ids["ana"] == m.resueltos_por_agente[0].agente_id


def test_agente_desactivado_con_resueltos_sigue_apareciendo(db, reloj):
    ids = cargar_datos(db)
    db.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (ids["ana"],))
    db.commit()
    nombres = [a.nombre for a in calcular_metricas(db, reloj).resueltos_por_agente]
    assert "Ana" in nombres
