"""Gráficos de barras SVG generados en el servidor (sin JavaScript)."""

from markupsafe import Markup, escape

ANCHO = 520
ANCHO_ETIQUETA = 150
ANCHO_BARRA_MAX = 270
ALTO_FILA = 30
ALTO_BARRA = 18
MARGEN = 8


def barras_svg(datos: list[tuple[str, int]], titulo: str) -> Markup:
    """Barras horizontales: etiqueta a la izquierda y valor escrito junto a cada barra."""
    maximo = max((valor for _, valor in datos), default=0)
    alto = max(len(datos), 1) * ALTO_FILA + 2 * MARGEN
    partes = [
        f'<svg class="grafico" role="img" aria-label="{escape(titulo)}" '
        f'viewBox="0 0 {ANCHO} {alto}" xmlns="http://www.w3.org/2000/svg">',
        f"<title>{escape(titulo)}</title>",
    ]
    for i, (etiqueta, valor) in enumerate(datos):
        y = MARGEN + i * ALTO_FILA
        centro = y + ALTO_FILA / 2
        ancho = round(valor / maximo * ANCHO_BARRA_MAX, 1) if maximo else 0
        partes.append(
            f'<text class="grafico-etiqueta" x="{ANCHO_ETIQUETA - 8}" y="{centro}" '
            f'text-anchor="end" dominant-baseline="middle">{escape(etiqueta)}</text>'
        )
        partes.append(
            f'<rect class="grafico-barra" x="{ANCHO_ETIQUETA}" y="{centro - ALTO_BARRA / 2}" '
            f'width="{ancho}" height="{ALTO_BARRA}" rx="3"/>'
        )
        partes.append(
            f'<text class="grafico-valor" x="{ANCHO_ETIQUETA + ancho + 8}" y="{centro}" '
            f'dominant-baseline="middle">{valor}</text>'
        )
    partes.append("</svg>")
    return Markup("".join(partes))
