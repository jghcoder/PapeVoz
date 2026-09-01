import gradio as gr
import sqlite3
import datetime
import pandas as pd
import re
import speech_recognition as sr
from gtts import gTTS
import tempfile
import plotly.express as px
import plotly.graph_objects as go

# ============ CATÁLOGO ============
CATALOGO = {
    "cuaderno profesional rayado": {"precio": 42.00, "alias": ["cuaderno profesional", "cuaderno rayado", "cuaderno"]},
    "cuaderno de cuadro chico": {"precio": 38.00, "alias": ["cuaderno de cuadro", "cuaderno cuadriculado", "cuaderno cuadro"]},
    "pluma azul": {"precio": 8.00, "alias": ["pluma", "boligrafo azul", "boli azul", "plumas"]},
    "pluma negra": {"precio": 8.00, "alias": ["pluma negra", "boligrafo negro", "boli negro"]},
    "pluma roja": {"precio": 9.00, "alias": ["pluma roja", "boligrafo rojo", "boli rojo"]},
    "lapiz": {"precio": 6.00, "alias": ["lapices", "lapices de madera"]},
    "marcatextos amarillo": {"precio": 12.00, "alias": ["marcatextos", "marca textos", "resaltador", "marcatexto"]},
    "juego de geometria": {"precio": 55.00, "alias": ["juego de geometria", "juego geometrico", "geometria", "escuadras"]},
    "calculadora cientifica": {"precio": 210.00, "alias": ["calculadora", "calculadora cientifica"]},
    "hojas de colores": {"precio": 25.00, "alias": ["hojas de color", "papel de colores"]},
    "papel bond tamano carta": {"precio": 1.50, "alias": ["hojas blancas", "hojas", "papel bond", "hojas sueltas"]},
    "carpeta": {"precio": 18.00, "alias": ["carpetas", "folder", "folders"]},
    "sacapuntas": {"precio": 10.00, "alias": ["tajador", "sacapuntes"]},
    "goma de borrar": {"precio": 7.00, "alias": ["goma", "borrador", "goma blanca"]},
    "tijeras": {"precio": 22.00, "alias": ["tijera"]},
    "resistol 5000": {"precio": 15.00, "alias": ["resistol", "pegamento", "pegamento blanco", "cola blanca"]},
    "cinta adhesiva": {"precio": 14.00, "alias": ["cinta", "cinta transparente", "diurex", "cinta scotch", "sinta"]},
    "cinta canela": {"precio": 13.00, "alias": ["cinta canela", "tape", "cinta masking", "cinta de papel"]},
    "corrector de cinta": {"precio": 32.00, "alias": ["corrector", "liquid paper", "correcto", "corrector de cinta"]},
    "regla 30 cm": {"precio": 11.00, "alias": ["regla"]},
    "colores normales": {"precio": 45.00, "alias": ["colores", "caja de colores", "colores de madera"]},
    "crayones": {"precio": 30.00, "alias": ["crayolas", "crayones", "caja de crayolas"]},
    "plumones": {"precio": 52.00, "alias": ["plumones", "marcadores", "plumon"]},
}

# Mapa alias -> clave canónica
ALIAS = {}
for clave, datos in CATALOGO.items():
    ALIAS[clave.lower()] = clave
    for a in datos.get("alias", []):
        ALIAS[a.lower()] = clave

# ============ BASE DE DATOS ============
DB = "ventas_papeleria.db"
conn = sqlite3.connect(DB, check_same_thread=False)
c = conn.cursor()

SQL = '''CREATE TABLE IF NOT EXISTS ventas (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 fecha TEXT NOT NULL,
 total REAL NOT NULL,
 num_articulos INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS detalle (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 venta_id INTEGER NOT NULL,
 articulo TEXT NOT NULL,
 cantidad INTEGER NOT NULL,
 precio_unitario REAL NOT NULL,
 subtotal REAL NOT NULL,
 FOREIGN KEY (venta_id) REFERENCES ventas(id)
);'''
c.executescript(SQL)
conn.commit()

def guardar_venta(items, total):
    fecha = datetime.datetime.now().isoformat(timespec="seconds")
    num = sum(i["cantidad"] for i in items)
    c.execute("INSERT INTO ventas (fecha, total, num_articulos) VALUES (?, ?, ?)",
        (fecha, total, num))
    venta_id = c.lastrowid
    for i in items:
        c.execute("INSERT INTO detalle (venta_id, articulo, cantidad, precio_unitario, subtotal) VALUES (?, ?, ?, ?, ?)",
            (venta_id, i["articulo"], i["cantidad"], i["precio_unitario"], i["subtotal"]))
    conn.commit()
    return venta_id, fecha

# ============ PARSER DE VOZ ============
PALABRAS_NUM = {
    "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11,
    "doce": 12, "quince": 15, "veinte": 20, "treinta": 30, "cincuenta": 50, "cien": 100,
}

def _num_a_int(txt):
    txt = txt.strip().lower()
    if txt.isdigit():
        return int(txt)
    return PALABRAS_NUM.get(txt, 1)

def parsear_pedido(texto):
    texto = texto.lower()
    items = []
    no_reconocido = []
    segmentos = re.split(r"\s*(?:y\s+|,\s*|,|\s+y\s+)\s*", texto)
    for seg in segmentos:
        seg = seg.strip()
        if not seg:
            continue
        m = re.match(
            r"^(\d+|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|quince|veinte|treinta|cincuenta|cien)\s+(.+)$",
            seg)
        if m:
            cantidad = _num_a_int(m.group(1))
            nombre = m.group(2).strip()
        else:
            cantidad = 1
            nombre = seg
        nombre = re.sub(r"\b(de|del|por favor|porfa|favor|me das|quiero|dame|necesito|ocupo|una|un)\b", " ", nombre)
        nombre = re.sub(r"\s+", " ", nombre).strip()
        clave = ALIAS.get(nombre)
        if clave is None:
            for alias, canon in ALIAS.items():
                if alias in nombre or nombre in alias:
                    clave = canon
                    break
        if clave:
            precio = CATALOGO[clave]["precio"]
            items.append({
                "articulo": clave,
                "cantidad": cantidad,
                "precio_unitario": precio,
                "subtotal": round(precio * cantidad, 2),
            })
        else:
            no_reconocido.append(nombre)
    return items, no_reconocido

# ============ VOZ ============
rec = sr.Recognizer()

def voz_a_texto(audio_file=None):
    if audio_file is not None:
        with sr.AudioFile(audio_file) as fuente:
            audio = rec.record(fuente)
    else:
        with sr.Microphone() as fuente:
            audio = rec.listen(fuente)
    try:
        return rec.recognize_google(audio, language="es-MX")
    except sr.UnknownValueError:
        return "No entendí, ¿puedes repetirlo?"
    except sr.RequestError as e:
        return f"Error: {e}"

def hablar(texto, lang="es"):
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    tts = gTTS(text=texto, lang=lang)
    tts.save(tmp.name)
    return tmp.name

def total_a_texto(total):
    pesos = int(total)
    centavos = round((total - pesos) * 100)
    if centavos:
        return f"{pesos} pesos con {centavos} centavos."
    return f"{pesos} pesos."

# ============ CARRITO ============
class Venta:
    def __init__(self):
        self.items = []

    def agregar_items(self, lista):
        self.items.extend(lista)

    def total(self):
        return round(sum(i["subtotal"] for i in self.items), 2)

    def cerrar_venta(self):
        total = self.total()
        if not self.items:
            return None, None, total
        venta_id, fecha = guardar_venta(self.items, total)
        return venta_id, fecha, total

    def vaciar(self):
        self.items = []

    def tabla(self):
        return pd.DataFrame(self.items)

ESTADO = {"carrito": Venta()}

# ============ INTERFAZ GRADIO ============
def _lineas_items():
    if not ESTADO["carrito"].items:
        return "**Carrito vacío.** Dicta tu primer artículo. 🎙️"
    df = ESTADO["carrito"].tabla()
    df["subtotal"] = df["subtotal"].map("${:,.2f}".format)
    df["precio_unitario"] = df["precio_unitario"].map("${:,.2f}".format)
    try:
        lineas = df.to_markdown(index=False)
    except Exception:
        lineas = df.to_string(index=False)
    total = ESTADO["carrito"].total()
    return f"{lineas}\n\n**Total: ${total:,.2f}**"

def procesar_voz(frase, audio):
    texto = frase or ""
    if audio is not None:
        voz = voz_a_texto(audio)
        texto = (texto + " " + voz).strip()
    if not texto:
        return _lineas_items(), "Di algo o escribe un pedido."
    its, faltan = parsear_pedido(texto)
    ESTADO["carrito"].agregar_items(its)
    msgs = []
    for i in its:
        msgs.append(f"➕ {i['cantidad']} × {i['articulo']} = ${i['subtotal']:.2f}")
    if faltan:
        msgs.append("⚠ No reconocí: " + ", ".join(faltan))
    detalle = "\n".join(msgs) if msgs else "No se agregó nada."
    return _lineas_items(), detalle

def cerrar_venta():
    venta_id, fecha, total = ESTADO["carrito"].cerrar_venta()
    if venta_id is None:
        detalle = "No hay artículos que cobrar."
        return _lineas_items(), detalle, None
    detalle = f"💰 Venta #{venta_id} cerrada el {fecha} · **Total: ${total:,.2f}**"
    ESTADO["carrito"].vaciar()
    frase_total = f"Tu total es de {total_a_texto(total)} ¡Gracias por tu compra!"
    archivo_audio = hablar(frase_total)
    return _lineas_items(), detalle, archivo_audio

def cargar_datos():
    ventas = pd.read_sql_query("SELECT * FROM ventas ORDER BY id", conn)
    detalle = pd.read_sql_query("SELECT * FROM detalle", conn)
    if ventas.empty:
        return ventas, detalle
    ventas["fecha_dt"] = pd.to_datetime(ventas["fecha"])
    ventas["dia"] = ventas["fecha_dt"].dt.date
    return ventas, detalle

def pestana_dashboard():
    ventas, detalle = cargar_datos()
    if ventas.empty:
        return "📭 Aún no hay ventas registradas.", None, None
    total_vendido = ventas["total"].sum()
    num_ventas = len(ventas)
    por_dia = ventas.groupby("dia")["total"].sum().reset_index()
    fig1 = px.bar(por_dia, x="dia", y="total", labels={"dia": "Día", "total": "Total ($)"},
        title="Ventas por día", text_auto=True)
    if not detalle.empty:
        por_art = detalle.groupby("articulo")["cantidad"].sum().reset_index().sort_values("cantidad", ascending=False)
        fig2 = px.bar(por_art, x="cantidad", y="articulo", orientation="h",
            labels={"cantidad": "Unidades", "articulo": "Artículo"},
            title="Artículos más vendidos", text_auto=True)
        fig2.update_yaxes(autorange="reversed")
    else:
        fig2 = go.Figure()
    resumen = (f"### 📈 Resumen\n{num_ventas} ventas · Total ${total_vendido:,.2f} · "
        f"Ticket promedio ${total_vendido/num_ventas:,.2f}")
    return resumen, fig1, fig2

# ============ APP ============
with gr.Blocks(title="Papelería La Escuadra · Punto de venta con voz") as app:
    gr.Markdown("# ✂️ Papelería La Escuadra\n_Punto de venta con voz — dicta, cobra y guarda tus ventas._")
    with gr.Tabs():
        with gr.Tab("🧾 Venta"):
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### 🎙️ Dicta el pedido del cliente")
                    voz = gr.Audio(sources=["microphone", "upload"], type="filepath", label="Micrófono")
                    frase = gr.Textbox(label="...o escríbelo", placeholder="Ej: cinco cuadernos y tres plumas", lines=2)
                    gr.Examples(["cinco cuadernos y tres plumas",
                        "dos lapices, una goma y un sacapuntas",
                        "una calculadora cientifica y veinte hojas"], inputs=frase)
                    boton_cobrar = gr.Button("💰 Cerrar venta", variant="primary")
                with gr.Column():
                    gr.Markdown("### 🧾 Carrito")
                    carrito_md = gr.Markdown(_lineas_items())
                    detalle_md = gr.Markdown("")
                    audio_total = gr.Audio(label="🔊 Total en voz alta", type="filepath", autoplay=True)
            voz.change(procesar_voz, inputs=[frase, voz], outputs=[carrito_md, detalle_md])
            frase.submit(procesar_voz, inputs=[frase, voz], outputs=[carrito_md, detalle_md])
            boton_cobrar.click(cerrar_venta, outputs=[carrito_md, detalle_md, audio_total])
        with gr.Tab("📊 Dashboard"):
            boton_refrescar = gr.Button("🔄 Actualizar")
            resumen = gr.Markdown()
            fig1 = gr.Plot()
            fig2 = gr.Plot()
            boton_refrescar.click(pestana_dashboard, outputs=[resumen, fig1, fig2])
            app.load(pestana_dashboard, outputs=[resumen, fig1, fig2])

if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=8000, share=False)
