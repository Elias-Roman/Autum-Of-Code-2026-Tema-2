extends Node

# ═══════════════════════════════════════════════════════════
#  LLMBridge.gd  v3  — Godot 4.6
#  - Prompts IDÉNTICOS a Dungeon.py
#  - Parser regex con re.DOTALL equivalente ([\s\S]*?)
#  - Verificación de Ollama al inicio con lista de modelos
#  - Señal ollama_status para mostrar info en el log
# ═══════════════════════════════════════════════════════════

const OLLAMA_URL    = "http://localhost:11434/api/generate"
const OLLAMA_TAGS   = "http://localhost:11434/api/tags"
const OLLAMA_MODEL  = "llama3:latest"

signal respuesta_lista(data: Dictionary)
signal error_llm(msg: String)
signal ollama_status(ok: bool, info: String)

# ── Prompts exactos de Dungeon.py ────────────────────────
const SYSTEM_PROMPT_MAPA = \
"""Eres un parser de comandos para un juego de dungeons.
Convierte la instrucción del jugador a JSON válido.
Sin texto extra, sin backticks, sin markdown.

ESQUEMAS:

1) Movimiento (siempre 1 sola celda, 1 solo paso):
{"accion":"mover","pasos":[{"direccion":"arriba","cantidad":1}]}

2) Moverse hacia el objeto más cercano:
{"accion":"mover","objetivo":"cofre"}

3) Abrir cofre adyacente:
{"accion":"abrir","direccion":"derecha"}

4) Esperar:
{"accion":"esperar"}

REGLAS:
- ir/ve/muévete/camina/avanza/desplázate → "mover"
- abrir/interactuar → "abrir" si el objetivo es un cofre
- si el jugador pide abrir o usar la puerta → {"accion":"mover","objetivo":"puerta"}
- esperar/pasar/descansar → "esperar"
- Direcciones válidas: arriba, abajo, izquierda, derecha, arriba-izquierda, arriba-derecha, abajo-izquierda, abajo-derecha
- Objetivos válidos: cofre, orco, puerta, llave
- Si hay objeto destino → formato 2. Si hay dirección → formato 1.
- IMPORTANTE: el movimiento es SIEMPRE de 1 sola celda. "cantidad" siempre vale 1.
- Si el jugador pide moverse múltiples pasos o en múltiples direcciones, interpretá solo el PRIMER paso con cantidad 1.
- Si no entendés: {"accion":"desconocido"}
- Solo JSON."""

const SYSTEM_PROMPT_COMBATE = \
"""Eres un parser de comandos de combate para un dungeon.
Convierte la instrucción a JSON válido. Sin texto extra ni backticks.

{"accion":"atacar"}
{"accion":"defensa"}
{"accion":"desconocido"}

- atacar: golpear, pegar, ataque, embisto, fight, attack
- defensa: defender, guardia, escudo, proteger, bloquear, block
- Solo JSON."""

var _http_game   : HTTPRequest   # para llamadas al LLM
var _http_check  : HTTPRequest   # para verificar Ollama al inicio

var _pendiente   : bool = false
var _combate     : bool = false


func _ready():
	_http_game = HTTPRequest.new()
	add_child(_http_game)
	_http_game.request_completed.connect(_on_game_done)

	_http_check = HTTPRequest.new()
	add_child(_http_check)
	_http_check.request_completed.connect(_on_check_done)

	# Verificar Ollama al arrancar (igual que verificar_modelo() en Dungeon.py)
	_verificar_ollama()


# ═══════════════════════════════════════════════════════════
#  VERIFICACIÓN DE OLLAMA AL INICIO
# ═══════════════════════════════════════════════════════════

func _verificar_ollama():
	var err = _http_check.request(OLLAMA_TAGS, [], HTTPClient.METHOD_GET)
	if err != OK:
		ollama_status.emit(false, "✗ No se pudo conectar a Ollama. ¿Está corriendo?\n  Inicialo con: ollama serve")


func _on_check_done(result, code, _headers, body):
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		ollama_status.emit(false, "✗ Ollama no responde (HTTP %d). Inicialo con: ollama serve" % code)
		return

	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if parsed == null:
		ollama_status.emit(false, "✗ Ollama respondió con formato inesperado.")
		return

	var modelos : Array = parsed.get("models", [])
	var nombres : Array = []
	for m in modelos:
		var nombre = str(m.get("name", ""))
		if nombre != "":
			nombres.append(nombre)

	var base = OLLAMA_MODEL.split(":")[0]
	var encontrado = false
	for n in nombres:
		if n.split(":")[0] == base:
			encontrado = true
			break

	if not encontrado:
		var lista = ", ".join(nombres) if nombres.size() > 0 else "(ninguno)"
		ollama_status.emit(false,
			"✗ Modelo '%s' no instalado.\n  Disponibles: %s\n  Instalalo con: ollama pull %s" \
			% [OLLAMA_MODEL, lista, OLLAMA_MODEL])
	else:
		ollama_status.emit(true,
			"✔ Ollama listo · modelo: %s  |  otros: %s" \
			% [OLLAMA_MODEL, ", ".join(nombres) if nombres.size() > 1 else "(solo este)"])


# ═══════════════════════════════════════════════════════════
#  LLAMADAS AL LLM
# ═══════════════════════════════════════════════════════════

func interpretar_mapa(texto: String):
	_llamar(texto, SYSTEM_PROMPT_MAPA, false)

func interpretar_combate(texto: String):
	_llamar(texto, SYSTEM_PROMPT_COMBATE, true)

func _llamar(texto: String, prompt: String, combate: bool):
	if _pendiente:
		return
	_pendiente = true
	_combate   = combate
	GameState.notify_thinking(true)

	var body = JSON.stringify({
		"model":  OLLAMA_MODEL,
		"stream": false,
		"system": prompt,
		"prompt": 'Instrucción: "%s"' % texto,
	})
	var err = _http_game.request(
		OLLAMA_URL,
		["Content-Type: application/json"],
		HTTPClient.METHOD_POST,
		body
	)
	if err != OK:
		_pendiente = false
		GameState.notify_thinking(false)
		error_llm.emit("✗ No se pudo conectar a Ollama (puerto 11434).")


func _on_game_done(result, code, _headers, body):
	_pendiente = false
	GameState.notify_thinking(false)

	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		error_llm.emit("✗ Error HTTP %d — ¿Ollama sigue corriendo?" % code)
		return

	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if parsed == null:
		error_llm.emit("✗ Ollama devolvió una respuesta no parseable.")
		return

	var raw  : String     = str(parsed.get("response", ""))
	var data : Dictionary = _parsear_json(raw)
	respuesta_lista.emit(data)


# ═══════════════════════════════════════════════════════════
#  PARSER JSON  (equivalente a _parsear_json_con_estado en Dungeon.py)
#  Usa [\s\S]*? para capturar JSONs multilinea, igual que re.DOTALL
# ═══════════════════════════════════════════════════════════

func _parsear_json(raw: String) -> Dictionary:
	# Intento 1: parsear el string completo directamente
	var direct = JSON.parse_string(raw.strip_edges())
	if direct is Dictionary and "accion" in direct:
		return direct

	# Intento 2: regex greedy que captura el PRIMER { ... } incluyendo saltos de línea
	# equivalente a re.search(r'\{.*\}', raw, re.DOTALL) de Python
	var re = RegEx.new()
	re.compile(r'\{[\s\S]*?\}')   # non-greedy, multilinea
	var matches = re.search_all(raw)
	for m in matches:
		var candidate = m.get_string()
		var d = JSON.parse_string(candidate)
		if d is Dictionary and "accion" in d:
			return d

	# Intento 3: regex greedy para JSONs más largos con texto dentro
	var re2 = RegEx.new()
	re2.compile(r'\{[\s\S]*\}')
	var m2 = re2.search(raw)
	if m2:
		var d2 = JSON.parse_string(m2.get_string())
		if d2 is Dictionary and "accion" in d2:
			return d2

	# Intento 4: buscar manualmente las palabras clave del JSON esperado
	# (fallback para cuando el LLM devuelve texto con el JSON embebido)
	var lower = raw.to_lower()
	if '"accion"' in lower or "'accion'" in lower:
		# Buscar desde el primer { hasta el último }
		var start = raw.find("{")
		var end   = raw.rfind("}")
		if start != -1 and end != -1 and end > start:
			var d3 = JSON.parse_string(raw.substr(start, end - start + 1))
			if d3 is Dictionary and "accion" in d3:
				return d3

	return {"accion": "desconocido"}
